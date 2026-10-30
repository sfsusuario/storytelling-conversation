"""Local web app: FastAPI backend for the React UI in web/.

Runs one pipeline at a time (one GPU) in a worker thread and streams its
structured events over SSE. Events are kept per run, so a reloaded page
replays them from the start (or from Last-Event-ID) and keeps following.
"""
# No `from __future__ import annotations`: FastAPI must see the real
# UploadFile/Request types, which are imported inside create_app().
import dataclasses
import functools
import hashlib
import importlib.util
import json
import os
import threading
from pathlib import Path

from studio.runs import Run, add_run_routes, make_file_url
from studio.runs import active_run as _active_run

from .config import (has_secret, CURATED_VOICES, IMAGE_PROVIDERS, KOKORO_VOICES,
                     LANGUAGE_NAMES, STYLE_SETS, PipelineOptions)
from .history import OUTPUT_ROOT, delete_run, list_runs, regenerate_options
from .motion import MOTION_MODES, liveportrait_available
from .pipeline import PipelineCancelled

WEB_DIST = Path(__file__).resolve().parents[3] / "server" / "frontend" / "dist"
UPLOADS = OUTPUT_ROOT / "_uploads"
PREVIEWS = OUTPUT_ROOT / "_previews"
# Options the browser may set; paths and dry-run stay server-controlled.
CLIENT_OPTIONS = {f.name for f in dataclasses.fields(PipelineOptions)} - {
    "base_image", "output_dir", "dry_run"}
SET_LABELS_ES = {
    "medieval": "medieval", "scifi": "ciencia ficción", "corporate": "corporativo",
    "mythology": "mitología", "military": "militar", "pirate": "piratas",
    "arcane": "magia arcana", "epochs": "épocas de la historia",
    "wealth": "escalada de riqueza", "tech": "profesiones tech",
    "anger": "escalada de enfado", "excuses": "excusas absurdas",
    "descenso": "descenso a la oscuridad", "locura": "descenso a la locura",
}


# /files/... URL for a path inside output/escalera, None for anything else.
file_url = make_file_url("/files", OUTPUT_ROOT)
RUNS: dict[str, Run] = {}


def _pipeline(options: PipelineOptions, rerolls=None, **kwargs):
    from .pipeline import run_pipeline  # looked up late: tests monkeypatch it
    # rerolls named here: studio.runs hands live rerolls only to pipelines that take them
    return run_pipeline(options, rerolls=rerolls, **kwargs)


def new_run(options: PipelineOptions, upload_id: str) -> Run:
    return Run(options, upload_id, registry=RUNS, pipeline=_pipeline,
               cancelled=PipelineCancelled, url=file_url)


def active_run() -> Run | None:
    return _active_run(RUNS)


@functools.lru_cache(maxsize=None)
def _encoder() -> str:
    from .ffutil import find_ffmpeg, video_encoder_args
    ffmpeg = find_ffmpeg()
    return video_encoder_args(ffmpeg)[1] if ffmpeg else "missing"


@functools.lru_cache(maxsize=None)
def _xpu() -> bool:
    from .image_local import local_available
    return local_available()


def system_status() -> dict:
    import urllib.request

    from .config import OLLAMA_HOST
    from .ffutil import find_ffmpeg

    models: list[str] = []
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=1.5) as r:
            models = [m["name"] for m in json.loads(r.read()).get("models", [])]
        ollama = True
    except Exception:
        ollama = False
    return {
        "ffmpeg": bool(find_ffmpeg()),
        "encoder": _encoder(),
        "ollama": ollama,
        "ollama_models": models,
        "kokoro": importlib.util.find_spec("kokoro") is not None,
        "xpu": _xpu(),
        "liveportrait": liveportrait_available(),
        "claude_key": has_secret("ANTHROPIC_API_KEY"),
        "google_key": has_secret("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    }


def build_options(upload_id: str, raw: dict) -> PipelineOptions:
    image = next(UPLOADS.glob(f"{upload_id}.*"), None) \
        if upload_id.isalnum() else None
    if image is None:
        raise ValueError("upload not found; send the image again")
    unknown = set(raw) - CLIENT_OPTIONS
    if unknown:
        raise ValueError(f"unknown options: {sorted(unknown)}")
    prompts = raw.get("image_prompts", {})
    if not isinstance(prompts, dict) or not all(
            isinstance(v, str) and len(v) <= 2000 for v in prompts.values()):
        raise ValueError("image_prompts must map scene ids to text")
    return PipelineOptions(base_image=image, **raw)


def create_app():
    from fastapi import FastAPI, HTTPException, Request, UploadFile
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="Escalator")

    @app.get("/api/options")
    def options():
        from .tts import resolve_voice

        defaults = PipelineOptions()
        defaults.voice = resolve_voice(defaults.tts_provider, defaults.voice)
        return {
            "style_sets": [{"name": n, "label": SET_LABELS_ES.get(n, n),
                            "personas": [p.name for p in STYLE_SETS[n]]}
                           for n in sorted(STYLE_SETS)],
            "languages": [{"code": c, "name": n} for c, n in LANGUAGE_NAMES.items()],
            "voices": {"kokoro": KOKORO_VOICES, "edge": CURATED_VOICES},
            "providers": {"text": ["auto", "ollama", "claude", "gemini"],
                          "image": IMAGE_PROVIDERS, "tts": ["kokoro", "edge"],
                          "motion": MOTION_MODES},
            "defaults": {k: v for k, v in dataclasses.asdict(defaults).items()
                         if k in CLIENT_OPTIONS},
        }

    @app.get("/api/system")
    def system():
        return system_status()

    @app.post("/api/uploads")
    async def upload(file: UploadFile):
        data = await file.read()
        if not data:
            raise HTTPException(400, "empty file")
        ext = Path(file.filename or "").suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(400, "use a PNG, JPG or WEBP image")
        upload_id = hashlib.sha256(data).hexdigest()[:16]
        UPLOADS.mkdir(parents=True, exist_ok=True)
        target = UPLOADS / f"{upload_id}{ext}"
        if not target.exists():
            target.write_bytes(data)
        return {"upload_id": upload_id, "url": file_url(target)}

    @app.post("/api/runs")
    async def create_run(request: Request):
        body = await request.json()
        if active_run():
            raise HTTPException(409, "a video is already being generated")
        try:
            opts = build_options(str(body.get("upload_id", "")),
                                 body.get("options") or {})
        except (TypeError, ValueError) as e:
            raise HTTPException(400, str(e))
        run = new_run(opts, body["upload_id"])
        RUNS[run.id] = run
        run.start()
        return {"run_id": run.id}

    @app.get("/api/runs")
    def runs():
        active = active_run()
        return {
            "active": active.id if active else None,
            "history": [{
                "name": r["name"], "phrase": r["phrase"],
                "style_set": r["style_set"], "language": r["language"],
                "duration": r["duration"], "test_mode": r["test_mode"],
                "voice": r["voice"], "social": r["social"], "mtime": r["mtime"],
                "video_url": file_url(r["video"]),
                "scenes": [{**s, "image": file_url(s["image"])}
                           for s in r["scenes"]],
            } for r in list_runs()],
        }

    @app.delete("/api/history/{name}")
    def delete_history(name: str):
        active = active_run()
        busy = active and any(Path(e.get("output_dir", "")).name == name
                              for e in active.events if e["type"] == "scenes")
        if busy:
            raise HTTPException(409, "this video is being generated right now")
        try:
            delete_run(name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except FileNotFoundError:
            raise HTTPException(404, "unknown video")
        return {"deleted": name}

    @app.post("/api/history/{name}/regenerate")
    async def regenerate(name: str, request: Request):
        """Re-run a past video in its own folder from one stage on: every
        earlier stage is kept from the cache."""
        body = await request.json()
        force_from, motion = body.get("force_from"), body.get("motion")
        if force_from not in ("text", "images", "tts", "motion", "render"):
            raise HTTPException(400, "force_from must be text|images|tts|motion|render")
        if motion is not None and motion not in MOTION_MODES:
            raise HTTPException(400, f"motion must be one of {MOTION_MODES}")
        if active_run():
            raise HTTPException(409, "a video is already being generated")
        try:
            fields = regenerate_options(name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except (FileNotFoundError, KeyError):
            raise HTTPException(404, "unknown video or missing manifest")
        if motion:
            fields["motion"] = motion
        run = new_run(PipelineOptions(**fields, output_dir=OUTPUT_ROOT / name,
                                      force_from=force_from), "")
        RUNS[run.id] = run
        run.start()
        return {"run_id": run.id}

    # /api/runs/{id}/events, reroll, retry, cancel: shared with every modality
    add_run_routes(app, RUNS)

    @app.get("/api/music/preview")
    def music_preview(style_set: str, source: str = "track"):
        if style_set not in STYLE_SETS or source not in {"track", "synth"}:
            raise HTTPException(400, "unknown style set or source")
        from .music import preview_file
        return FileResponse(preview_file(style_set, source))

    @app.get("/api/voice/preview")
    def voice_preview(provider: str, voice: str, language: str = "es",
                      rate: str = "+0%", pitch: str = "+0Hz"):
        if provider not in {"kokoro", "edge"}:
            raise HTTPException(400, "unknown provider")
        from .tts import TtsError, preview_voice
        try:
            return FileResponse(preview_voice(provider, voice, language, rate,
                                              pitch, PREVIEWS))
        except TtsError as e:
            raise HTTPException(502, str(e))

    @app.get("/files/{path:path}")
    def files(path: str):
        root = OUTPUT_ROOT.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(target)

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


def main() -> int:
    try:
        import uvicorn
    except ImportError:
        print("La web necesita FastAPI y uvicorn. Instálalos con:\n"
              "  pip install -e .[web]")
        return 1
    import webbrowser

    port = int(os.environ.get("ESCALATE_WEB_PORT", "8000"))
    if WEB_DIST.is_dir():
        threading.Timer(1.5, webbrowser.open, [f"http://127.0.0.1:{port}"]).start()
    else:
        print("server/frontend/dist no existe: compila el frontend con  cd ../server/frontend; npm run build\n"
              "(o usa  npm run dev  en server/frontend para desarrollo)")
    uvicorn.run(create_app(), host="127.0.0.1", port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
