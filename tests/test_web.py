"""Web API smoke test: defaults, ideas, and the full demo flow over SSE.

Run from the repo root (needs characters/, backgrounds/ and ffmpeg):
    python -m pytest tests/test_web.py      or      python tests/test_web.py
"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from charla.web import classify, create_app


def events(client: TestClient, job: str) -> list[dict]:
    out = []
    with client.stream("GET", f"/api/jobs/{job}/events") as res:
        for line in res.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def test_classify():
    assert classify("[2/4] tts (rick: x)")["stage"] == "voice"
    assert classify("  tts: turn_03.mp3 (rick)") == {
        "kind": "audio", "turn": 3, "text": "  tts: turn_03.mp3 (rick)"}
    assert classify("  clip: turn_02.mp4 (cached)")["kind"] == "clip"
    assert classify("\n[video 2/5] Saturno")["index"] == 2
    assert classify("  ✗ falló: boom")["error"] == "boom"
    # batch relays pipeline lines indented by 2
    assert classify("    chatterbox: turn_01.cbx.wav (morty)", indent=2)["turn"] == 1
    assert classify("  pingpong: x.mp4")["kind"] == "log"


def test_history_delete():
    client = TestClient(create_app())
    run = Path("output") / "zz-test-delete-0000"
    run.mkdir(parents=True, exist_ok=True)
    (run / "final.mp4").write_bytes(b"x")
    for bad in ("..%5Cx", "_lote", "zz-nope"):  # traversal, internal folder, unknown
        assert client.delete(f"/api/history/{bad}").status_code in (400, 404)
    assert client.delete(f"/api/history/{run.name}").json() == {"deleted": run.name}
    assert not run.exists()


def test_demo_flow():
    client = TestClient(create_app())
    d = client.get("/api/defaults").json()
    assert d["tts_engine"] in d["engines"] and "edge" in d["engines"]
    assert len(client.get("/api/ideas").json()) == 8
    assert client.post("/api/video/script", json={"topic": ""}).status_code == 400
    assert client.post("/api/video/script",
                       json={"demo": True, "options": {"bogus": 1}}).status_code == 422

    job = client.post("/api/video/script", json={"demo": True}).json()["job"]
    result = [e for e in events(client, job) if e["kind"] == "result"][0]
    assert len(result["turns"]) == 4

    res = client.post(f"/api/video/{result['draft']}/approve",
                      json={"options": {"tts_engine": "edge"}}).json()
    evs = events(client, res["job"])
    kinds = [e["kind"] for e in evs]
    assert "error" not in kinds, [e for e in evs if e["kind"] == "error"]
    assert {e["turn"] for e in evs if e["kind"] == "audio"} == {1, 2, 3, 4}
    assert {e["turn"] for e in evs if e["kind"] == "clip"} == {1, 2, 3, 4}
    assert any(e.get("stage") == "voice" for e in evs)
    video = [e for e in evs if e["kind"] == "result"][0]["video_url"]
    assert video.startswith("/media/") and client.get(video).status_code == 200


if __name__ == "__main__":
    test_classify()
    test_history_delete()
    test_demo_flow()
    print("ok")
