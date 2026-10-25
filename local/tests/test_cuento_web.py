"""Cuento web app: runs with and without a photo, validation, the shared
run machinery (reroll queue -> follow-up), regenerate and delete."""
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cuento import pipeline, web  # noqa: E402
from escalator.pipeline import STAGES  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # output/ lives under the temp dir
    web.RUNS.clear()
    return TestClient(web.create_app())


def fake_story(options, on_progress, on_event, cancel):
    """Emits the same event shapes as run_story, without any backend."""
    out = web.OUTPUT_ROOT / "run"
    out.mkdir(parents=True, exist_ok=True)
    (out / "final.mp4").write_bytes(b"mp4")
    on_event({"type": "scenes", "style_set": "Acuarela infantil", "output_dir": str(out),
              "scenes": [{"scene_id": "scene_01", "level": 1, "persona": "Escena 1"}]})
    for i, name in enumerate(STAGES, 1):
        on_progress(f"[{i}/6] {name}")
        on_event({"type": "stage", "index": i, "total": 6, "name": name, "detail": ""})
    on_event({"type": "done", "video": str(out / "final.mp4"), "social": "hi",
              "output_dir": str(out), "duration": 3.0})


def sse_events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def test_options_defaults(client):
    o = client.get("/api/options").json()
    assert [t["id"] for t in o["tones"]] == ["infantil", "general"]
    assert o["styles"][0]["id"] == "auto" and "acuarela" in {s["id"] for s in o["styles"]}
    d = o["defaults"]
    assert (d["scenes"], d["motion"], d["tone"], d["style"]) == (6, "rotate3d", "infantil", "auto")
    assert "base_image" not in d and "output_dir" not in d


def test_run_without_photo_streams_events(client, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "run_story",
                        lambda options, **k: seen.append(options) or fake_story(options, **k))
    run = client.post("/api/runs", json={"upload_id": "",
                                         "options": {"premise": "Una tortuga", "scenes": 4}})
    assert run.status_code == 200, run.text
    events = sse_events(client.get(f"/api/runs/{run.json()['run_id']}/events").text)
    types = [e["type"] for e in events]
    assert types[0] == "started" and types[-1] == "done"
    assert [e["name"] for e in events if e["type"] == "stage"] == STAGES
    assert events[-1]["video_url"].startswith("/media/cuento/run/final.mp4")
    assert seen[0].base_image is None and seen[0].scenes == 4
    assert client.get("/api/runs").json() == {"active": None}


def test_run_with_photo(client, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "run_story",
                        lambda options, **k: seen.append(options) or fake_story(options, **k))
    up = client.post("/api/uploads", files={"file": ("p.png", b"\x89PNGfake", "image/png")})
    assert up.status_code == 200 and up.json()["url"].startswith("/media/cuento/_uploads/")
    run = client.post("/api/runs", json={"upload_id": up.json()["upload_id"],
                                         "options": {"premise": "Yo, astronauta", "tone": "general",
                                                     "genre": "scifi"}})
    assert run.status_code == 200, run.text
    sse_events(client.get(f"/api/runs/{run.json()['run_id']}/events").text)
    assert Path(seen[0].base_image).name.startswith(up.json()["upload_id"])


def test_rejects_bad_requests(client):
    post = lambda body: client.post("/api/runs", json=body).status_code
    assert post({"upload_id": "", "options": {"premise": "x", "output_dir": "C:/"}}) == 400
    assert post({"upload_id": "", "options": {"premise": "x", "scenes": 3}}) == 400
    assert post({"upload_id": "", "options": {"premise": "x", "tone": "epic"}}) == 400
    assert post({"upload_id": "", "options": {"premise": "x", "genre": "terror"}}) == 400  # infantil
    assert post({"upload_id": "", "options": {"premise": "   "}}) == 400
    assert post({"upload_id": "../x", "options": {"premise": "x"}}) == 400
    assert client.post("/api/uploads", files={"file": ("p.exe", b"x", "x")}).status_code == 400


def test_second_run_is_rejected_while_busy(client, monkeypatch):
    import threading
    gate = threading.Event()

    def slow(options, on_progress, on_event, cancel):
        gate.wait(5)
        fake_story(options, on_progress, on_event, cancel)

    monkeypatch.setattr(pipeline, "run_story", slow)
    first = client.post("/api/runs", json={"upload_id": "", "options": {"premise": "a"}})
    assert first.status_code == 200
    assert client.post("/api/runs", json={"upload_id": "", "options": {"premise": "b"}}).status_code == 409
    assert client.get("/api/runs").json()["active"] == first.json()["run_id"]
    gate.set()
    sse_events(client.get(f"/api/runs/{first.json()['run_id']}/events").text)


def test_reroll_during_run_is_queued_then_chained(client, monkeypatch):
    import threading
    gate, seen = threading.Event(), []

    def slow(options, on_progress, on_event, cancel):
        seen.append((options.reroll_images, options.reroll_motion))
        if len(seen) == 1:
            gate.wait(5)
        fake_story(options, on_progress, on_event, cancel)

    monkeypatch.setattr(pipeline, "run_story", slow)
    first = client.post("/api/runs", json={"upload_id": "", "options": {"premise": "a"}}).json()["run_id"]
    assert client.post(f"/api/runs/{first}/reroll", json={"scene_id": "scene_02", "kind": "image"}).json() == {"queued": True}
    gate.set()
    events = sse_events(client.get(f"/api/runs/{first}/events").text)
    assert [e["type"] for e in events][-2:] == ["next", "done"]
    sse_events(client.get(f"/api/runs/{events[-2]['run_id']}/events").text)
    assert seen[1] == (["scene_02"], [])


def test_regenerate_and_delete_history_run(client, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "run_story",
                        lambda options, **k: seen.append(options) or fake_story(options, **k))
    run = web.OUTPUT_ROOT / "tortuga-1234"
    (run / "02_images").mkdir(parents=True)
    (run / "final.mp4").write_bytes(b"mp4")
    (run / "pipeline.json").write_text(json.dumps({
        "Title": "La tortuga", "Premise": "Una tortuga que quiere volar", "Tone": "infantil",
        "Genre": "aventura", "Style": "acuarela", "Language": "es", "Seed": 7,
        "Base_Image": None, "Resolution": "540x960", "FPS": 30, "Fit": "crop",
        "Watermark": "", "Subtitles": True, "Voice": "em_alex", "Voice_Rate": "-8%",
        "Voice_Pitch": "-12Hz", "TTS_Provider": "kokoro", "Motion": "rotate3d",
        "Test_Mode": True, "Scenes": [{}, {}, {}, {}, {}]}))
    url = "/api/history/tortuga-1234/regenerate"
    assert client.post(url, json={"force_from": "bogus"}).status_code == 400
    assert client.post("/api/history/nope/regenerate", json={"force_from": "render"}).status_code == 404
    rid = client.post(url, json={"force_from": "images", "motion": "none"}).json()["run_id"]
    sse_events(client.get(f"/api/runs/{rid}/events").text)
    o = seen[0]
    assert (o.force_from, o.motion, o.scenes, o.premise, o.seed) == ("images", "none", 5, "Una tortuga que quiere volar", 7)
    assert Path(o.output_dir) == run and (o.width, o.height) == (540, 960) and o.base_image is None
    (web.OUTPUT_ROOT / "_uploads").mkdir()
    assert client.delete("/api/history/_uploads").status_code == 400
    assert client.delete("/api/history/nope").status_code == 404
    assert client.delete("/api/history/tortuga-1234").status_code == 200
    assert not run.exists() and (web.OUTPUT_ROOT / "_uploads").exists()
