"""FastAPI app of the story modality, mounted by the studio at /m/cuento/.

Same contract as Escalera's web app (runs, live events, rerolls, retry,
history delete/regenerate); the run machinery itself is studio.runs.
"""
# No `from __future__ import annotations`: FastAPI needs the real types.
import dataclasses
import hashlib
from pathlib import Path

from escalator.config import CURATED_VOICES, KOKORO_VOICES, LANGUAGE_NAMES
from escalator.history import delete_run
from escalator.motion import MOTION_MODES
from escalator.pipeline import PipelineCancelled
from escalator.web import PREVIEWS, system_status
from studio.runs import Run, add_run_routes, make_file_url
from studio.runs import active_run as _active_run

from .config import (CLIENT_OPTIONS, IMAGE_PROVIDERS, OUTPUT_ROOT, STYLE_PRESETS, TONES,
                     StoryOptions, validate)
from .manifest import regenerate_options
from .sources import PERIODS, PRESETS, SourceError, list_stories, used_urls

UPLOADS = OUTPUT_ROOT / "_uploads"
# served by the studio root: output/ is mounted at /media (Conversación)
file_url = make_file_url("/media/cuento", OUTPUT_ROOT)
RUNS: dict[str, Run] = {}


def _pipeline(options: StoryOptions, rerolls=None, **kwargs):
    from .pipeline import run_story  # looked up late: tests monkeypatch it
    # rerolls named here: studio.runs hands live rerolls only to pipelines that take them
    return run_story(options, rerolls=rerolls, **kwargs)


def new_run(options: StoryOptions, upload_id: str) -> Run:
    return Run(options, upload_id, registry=RUNS, pipeline=_pipeline,
               cancelled=PipelineCancelled, url=file_url)


def active_run() -> Run | None:
    return _active_run(RUNS)


def build_options(upload_id: str, raw: dict) -> StoryOptions:
    image = None
    if upload_id:
        image = next(UPLOADS.glob(f"{upload_id}.*"), None) if upload_id.isalnum() else None
        if image is None:
            raise ValueError("upload not found; send the photo again")
    unknown = set(raw) - CLIENT_OPTIONS
    if unknown:
        raise ValueError(f"unknown options: {sorted(unknown)}")
    options = StoryOptions(base_image=image, **raw)
    validate(options)
    return options


def create_app():
    from fastapi import FastAPI, HTTPException, Request, UploadFile
    from fastapi.responses import FileResponse

    app = FastAPI(title="Cuento ilustrado")

    @app.get("/api/options")
    def options():
        from escalator.tts import resolve_voice

        defaults = StoryOptions()
        defaults.voice = resolve_voice(defaults.tts_provider, defaults.voice)
        return {
            "tones": [{"id": t, "label": label,
                       "genres": [{"id": g, "label": gl} for g, (gl, _) in genres.items()]}
                      for t, (label, _, genres) in TONES.items()],
            "styles": [{"id": "auto", "label": "Automático (según el tono; foto realista si es de Reddit)"}]
                      + [{"id": s, "label": label} for s, (label, _) in STYLE_PRESETS.items()],
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

    @app.get("/api/sources")
    def sources():
        return {"presets": PRESETS, "periods": list(PERIODS)}

    @app.get("/api/sources/{subreddit}/stories")
    def source_stories(subreddit: str, period: str = "week", refresh: bool = False):
        """Top stories of a subreddit (cached), minus the ones already made
        into a video and without their full text (the pipeline reads it)."""
        try:
            data = list_stories(subreddit, period, refresh)
        except SourceError as e:
            raise HTTPException(503 if e.retry_in else 400, str(e))
        used = used_urls()
        return {**data, "stories": [{k: v for k, v in s.items() if k != "text"}
                                    for s in data["stories"] if s["url"] not in used]}

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
            opts = build_options(str(body.get("upload_id") or ""), body.get("options") or {})
        except (TypeError, ValueError) as e:
            raise HTTPException(400, str(e))
        run = new_run(opts, str(body.get("upload_id") or ""))
        RUNS[run.id] = run
        run.start()
        return {"run_id": run.id}

    @app.get("/api/runs")
    def runs():
        active = active_run()
        return {"active": active.id if active else None}

    @app.delete("/api/history/{name}")
    def delete_history(name: str):
        active = active_run()
        busy = active and any(Path(e.get("output_dir", "")).name == name
                              for e in active.events if e["type"] == "scenes")
        if busy:
            raise HTTPException(409, "this video is being generated right now")
        try:
            delete_run(name, OUTPUT_ROOT)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except FileNotFoundError:
            raise HTTPException(404, "unknown video")
        return {"deleted": name}

    @app.post("/api/history/{name}/regenerate")
    async def regenerate(name: str, request: Request):
        """Re-run a past story in its own folder from one stage on: every
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
            fields = regenerate_options(name, OUTPUT_ROOT)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except (FileNotFoundError, KeyError):
            raise HTTPException(404, "unknown video or missing manifest")
        if motion:
            fields["motion"] = motion
        run = new_run(StoryOptions(**fields, output_dir=OUTPUT_ROOT / name,
                                   force_from=force_from), "")
        RUNS[run.id] = run
        run.start()
        return {"run_id": run.id}

    # /api/runs/{id}/events, reroll, retry, cancel: shared with every modality
    add_run_routes(app, RUNS)

    @app.get("/api/voice/preview")
    def voice_preview(provider: str, voice: str, language: str = "es",
                      rate: str = "+0%", pitch: str = "+0Hz"):
        if provider not in {"kokoro", "edge"}:
            raise HTTPException(400, "unknown provider")
        from escalator.tts import TtsError, preview_voice
        try:
            return FileResponse(preview_voice(provider, voice, language, rate, pitch, PREVIEWS))
        except TtsError as e:
            raise HTTPException(502, str(e))

    return app
