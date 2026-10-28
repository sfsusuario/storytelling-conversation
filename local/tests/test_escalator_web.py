import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from escalator import pipeline, web  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # output/ lives under the temp dir
    web.RUNS.clear()
    return TestClient(web.create_app())


def fake_pipeline(options, on_progress, on_event, cancel, rerolls=None):
    """Emits the same event shapes as run_pipeline, without any backend."""
    out = web.OUTPUT_ROOT / "run"
    out.mkdir(parents=True, exist_ok=True)
    (out / "final.mp4").write_bytes(b"mp4")
    on_event({"type": "scenes", "style_set": "medieval", "output_dir": str(out),
              "scenes": [{"scene_id": "scene_01", "level": 1, "persona": "P"}]})
    for i, name in enumerate(pipeline.STAGES, 1):
        on_progress(f"[{i}/5] {name}")
        on_event({"type": "stage", "index": i, "total": 5, "name": name, "detail": ""})
    on_event({"type": "done", "video": str(out / "final.mp4"), "social": "hi",
              "output_dir": str(out), "duration": 3.0})


def sse_events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def test_run_streams_stage_and_done_events(client, monkeypatch):
    monkeypatch.setattr(pipeline, "run_pipeline", fake_pipeline)
    up = client.post("/api/uploads", files={"file": ("p.png", b"\x89PNGfake", "image/png")})
    assert up.status_code == 200
    run = client.post("/api/runs", json={"upload_id": up.json()["upload_id"],
                                         "options": {"phrase": "Hola", "test_mode": True}})
    assert run.status_code == 200
    res = client.get(f"/api/runs/{run.json()['run_id']}/events")
    events = sse_events(res.text)
    types = [e["type"] for e in events]
    assert types[0] == "started" and types[-1] == "done"
    assert [e["name"] for e in events if e["type"] == "stage"] == pipeline.STAGES
    done = events[-1]
    assert done["video_url"].startswith("/files/run/final.mp4")
    assert client.get(done["video_url"]).content == b"mp4"


def test_rejects_unknown_options_and_uploads(client):
    up = client.post("/api/uploads", files={"file": ("p.png", b"img", "image/png")}).json()
    bad = client.post("/api/runs", json={"upload_id": up["upload_id"],
                                         "options": {"output_dir": "C:/Windows"}})
    assert bad.status_code == 400
    assert client.post("/api/runs", json={"upload_id": "../x", "options": {}}).status_code == 400
    assert client.post("/api/uploads", files={"file": ("p.exe", b"x", "x")}).status_code == 400


def test_files_blocks_path_traversal(client, tmp_path):
    (tmp_path / "secret.txt").write_text("nope")
    (tmp_path / "output").mkdir()
    for path in ("/files/../secret.txt", "/files/..%2Fsecret.txt", "/files/%2e%2e/secret.txt"):
        assert client.get(path).status_code == 404


def test_delete_history_run(client):
    run = web.OUTPUT_ROOT / "frase-1234"
    (run / "02_images").mkdir(parents=True)
    (run / "final.mp4").write_bytes(b"mp4")
    (web.OUTPUT_ROOT / "_uploads").mkdir()
    assert client.delete("/api/history/_uploads").status_code == 400
    for bad in ("..", "a/../..", "", ".git"):   # URL routing never lets these through
        with pytest.raises(ValueError):
            web.delete_run(bad)
    assert client.delete("/api/history/nope").status_code == 404
    assert client.delete("/api/history/frase-1234").status_code == 200
    assert not run.exists() and (web.OUTPUT_ROOT / "_uploads").exists()


def test_reroll_during_run_is_queued_then_chained(client, monkeypatch):
    import threading
    gate, seen, prompts = threading.Event(), [], []

    def slow_pipeline(options, on_progress, on_event, cancel, rerolls=None):
        seen.append((options.reroll_images, options.reroll_motion))
        prompts.append(options.image_prompts)
        if len(seen) == 1:
            gate.wait(5)  # the first run is "working" until the test releases it
        fake_pipeline(options, on_progress, on_event, cancel)

    monkeypatch.setattr(pipeline, "run_pipeline", slow_pipeline)
    up = client.post("/api/uploads", files={"file": ("p.png", b"\x89PNGfake", "image/png")}).json()
    first = client.post("/api/runs", json={"upload_id": up["upload_id"],
                                           "options": {"phrase": "Hola", "test_mode": True}}).json()["run_id"]
    rr = lambda sid, kind: client.post(f"/api/runs/{first}/reroll", json={"scene_id": sid, "kind": kind})
    assert rr("scene_02", "image").json() == {"queued": True}
    assert rr("scene_03", "motion").json() == {"queued": True}
    assert rr("scene_02", "bogus").status_code == 400
    gate.set()
    events = sse_events(client.get(f"/api/runs/{first}/events").text)
    types = [e["type"] for e in events]
    assert types.count("queued") == 2 and types[-2:] == ["next", "done"]
    second = events[-2]["run_id"]
    assert sse_events(client.get(f"/api/runs/{second}/events").text)[-1]["type"] == "done"
    assert seen[1] == (["scene_02"], ["scene_03"])
    # finished run: a reroll starts a follow-up right away
    third = rr("scene_04", "image").json()["run_id"]
    sse_events(client.get(f"/api/runs/{third}/events").text)
    assert seen[2] == (["scene_04"], [])
    # an image reroll can carry the user's own prompt; motion cannot
    body = {"scene_id": "scene_02", "kind": "image", "prompt": "  un dragón rojo "}
    fourth = client.post(f"/api/runs/{third}/reroll", json=body).json()["run_id"]
    sse_events(client.get(f"/api/runs/{fourth}/events").text)
    assert seen[3] == (["scene_02"], []) and prompts[3] == {"scene_02": "un dragón rojo"}
    assert client.post(f"/api/runs/{fourth}/reroll", json={**body, "kind": "motion"}).status_code == 400


def test_regenerate_history_run_in_its_own_folder(client, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "run_pipeline",
                        lambda options, **k: seen.append(options) or fake_pipeline(options, **k))
    run = web.OUTPUT_ROOT / "frase-1234"
    (run / "02_images").mkdir(parents=True)
    (run / "02_images" / "scene_01.png").write_bytes(b"png")
    (run / "final.mp4").write_bytes(b"mp4")
    (run / "pipeline.json").write_text(json.dumps({
        "Base_Image": "C:/gone/photo.png", "Input_Phrase": "Hola", "Language": "es",
        "Style_Set": "military", "Seed": None, "Resolution": "540x960", "FPS": 30,
        "Fit": "crop", "Watermark": "", "Subtitles": True, "Music": {"volume": 0},
        "Test_Mode": True,
        "Scenes": [{"Style": "Fresh Recruit", "Voice_Config": {"voice": "em_alex"}},
                   {"Style": "General", "Voice_Config": {"voice": "em_alex"}}]}))
    url = "/api/history/frase-1234/regenerate"
    assert client.post(url, json={"force_from": "bogus"}).status_code == 400
    assert client.post("/api/history/nope/regenerate", json={"force_from": "render"}).status_code == 404
    rid = client.post(url, json={"force_from": "images", "motion": "rotate3d"}).json()["run_id"]
    sse_events(client.get(f"/api/runs/{rid}/events").text)
    o = seen[0]
    assert (o.force_from, o.motion, o.styles, o.stages) == ("images", "rotate3d", ["Fresh Recruit", "General"], 2)
    assert Path(o.output_dir) == run and (o.width, o.height) == (540, 960)
    # the missing upload is replaced by a copy outside 02_images (which "images" wipes)
    assert Path(o.base_image) == web.OUTPUT_ROOT / "_uploads" / "frase-1234.png"
