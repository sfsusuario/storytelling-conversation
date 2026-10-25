"""Studio (single app) tests: shared history readers on fake run folders,
the registry, and mounting modalities + their media routes.

    python -m pytest tests/test_studio.py      or      python tests/test_studio.py
"""
import json
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio.app import create_app
from studio.history import collect, read_charla, read_escalator, thumbnail
from studio.modalities import Modality, check_unique


def _run(output: Path, name: str, manifest: str, data: dict) -> None:
    d = output / name
    d.mkdir(parents=True)
    (d / "final.mp4").write_bytes(b"x")
    (d / manifest).write_text(json.dumps(data), encoding="utf-8")
    (d / "social.txt").write_text("hola #ciencia", encoding="utf-8")


def _stub_app(tag: str):
    def factory():
        app = FastAPI()

        @app.get("/api/ping")
        def ping():
            return {"modality": tag}
        return app
    return factory


def _mods(root: Path) -> list[Modality]:
    return [
        Modality("conversacion", "Conversación", "🎭", "", _stub_app("c"), root / "output",
                 "/media", read_charla),
        Modality("escalera", "Escalera", "🪜", "", _stub_app("e"), root / "output" / "escalera",
                 "/files", read_escalator),
    ]


def _fixture(root: Path) -> None:
    _run(root / "output", "pulpos-1", "manifest.json",
         {"Title": "Pulpos", "Input": "pulpos\n\ndetalles", "Total_Duration": 30, "Turns": [{}, {}]})
    _run(root / "output", "_lote", "manifest.json", {})        # internal: skipped
    _run(root / "output" / "escalera", "frase-2", "pipeline.json",
         {"Input_Phrase": "A buen hambre", "Scenes": [{"Style": "cadete"}, {"Style": "almirante"}]})


def test_history_merges_modalities(tmp_path):
    _fixture(tmp_path)
    runs = collect(_mods(tmp_path))
    # escalera's folder lives inside output/ but is not a Conversación run
    assert sorted((r["modality"], r["title"]) for r in runs) == [
        ("conversacion", "Pulpos"), ("escalera", "A buen hambre")]
    p = next(r for r in runs if r["modality"] == "conversacion")
    e = next(r for r in runs if r["modality"] == "escalera")
    assert p["video_url"].startswith("/media/pulpos-1/final.mp4")
    assert e["video_url"].startswith("/files/frase-2/final.mp4")
    assert p["reuse"] == {"kind": "prefill", "input": "pulpos"}
    assert e["reuse"]["url"] == "/m/escalera/api/history/frase-2/regenerate"
    assert p["delete_url"] == "/m/conversacion/api/history/pulpos-1"
    assert p["thumb_url"] == "/api/thumb/conversacion/pulpos-1"
    assert e["subtitle"] == "cadete → almirante" and e["social"] == "hola #ciencia"


def test_registry_rejects_duplicates(tmp_path):
    mods = _mods(tmp_path)
    mods[1] = Modality("x", "X", "", "", _stub_app("x"), tmp_path, "/media", read_escalator)
    try:
        check_unique(mods)
    except ValueError:
        return
    raise AssertionError("duplicate media route accepted")


def test_thumbnail_rejects_bad_names(tmp_path):
    for bad in ("../x", "_lote", "a/b", ""):
        try:
            thumbnail(tmp_path, bad, tmp_path / "cache")
        except (ValueError, FileNotFoundError):
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_single_app_mounts_and_media(tmp_path):
    _fixture(tmp_path)
    with TestClient(create_app(_mods(tmp_path))) as c:
        assert [m["id"] for m in c.get("/api/modalities").json()] == ["conversacion", "escalera"]
        assert c.get("/m/conversacion/api/ping").json() == {"modality": "c"}
        assert c.get("/m/escalera/api/ping").json() == {"modality": "e"}
        assert c.get("/media/pulpos-1/final.mp4").content == b"x"
        assert c.get("/files/frase-2/final.mp4").content == b"x"
        hist = c.get("/api/history").json()
        assert {r["modality_name"] for r in hist} == {"Conversación", "Escalera"}
        assert len(c.get("/api/history?modality=escalera").json()) == 1


if __name__ == "__main__":
    for fn in (test_history_merges_modalities, test_registry_rejects_duplicates,
               test_thumbnail_rejects_bad_names, test_single_app_mounts_and_media):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
    print("ok")
