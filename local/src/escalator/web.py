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
import time
import uuid
from pathlib import Path

from .config import (has_secret, CURATED_VOICES, IMAGE_PROVIDERS, KOKORO_VOICES,
                     LANGUAGE_NAMES, STYLE_SETS, PipelineOptions)
from .history import OUTPUT_ROOT, delete_run, list_runs, regenerate_options
from .motion import MOTION_MODES, liveportrait_available

WEB_DIST = Path(__file__).resolve().parents[3] / "server" / "frontend" / "dist"
UPLOADS = OUTPUT_ROOT / "_uploads"
PREVIEWS = OUTPUT_ROOT / "_previews"
TERMINAL = {"done", "error", "cancelled"}
# Options the browser may set; paths and dry-run stay server-controlled.
CLIENT_OPTIONS = {f.name for f in dataclasses.fields(PipelineOptions)} - {
    "base_image", "output_dir", "dry_run"}
SET_LABELS_ES = {
    "medieval": "medieval", "scifi": "ciencia ficción", "corporate": "corporativo",
    "mythology": "mitología", "military": "militar", "pirate": "piratas",
    "arcane": "magia arcana", "epochs": "épocas de la historia",
    "wealth": "escalada de riqueza", "tech": "profesiones tech",
    "anger": "escalada de enfado", "excuses": "excusas absurdas",
}


def file_url(path: str | Path | None) -> str | None:
    """/files/... URL for a path inside output/, None for anything else."""
    if not path:
        return None
    try:
        rel = Path(path).resolve().relative_to(OUTPUT_ROOT.resolve())
    except ValueError:
        return None
    url = f"/files/{rel.as_posix()}"
    # mtime busts the browser cache when a stage regenerates the same file name
    return f"{url}?v={int(Path(path).stat().st_mtime)}" if Path(path).exists() else url


class Run:
    def __init__(self, options: PipelineOptions, upload_id: str):
        self.id = uuid.uuid4().hex[:12]
        self.upload_id = upload_id
        self.options = options
        self.events: list[dict] = []
        self.cond = threading.Condition()
        self.cancel = threading.Event()
        self.started = time.time()
        # Rerolls asked for while this run works: redone by a follow-up run.
        self.queued: dict[str, list[str]] = {"image": [], "motion": []}

    @property
    def status(self) -> str:
        last = self.events[-1]["type"] if self.events else ""
        return last if last in TERMINAL else "running"

    def push(self, event: dict) -> None:
        event = {**event, "ts": round(time.time() - self.started, 3)}
        for key in ("path", "video"):
            if key in event:
                event[f"{key}_url"] = file_url(event[key])
                del event[key]
        with self.cond:
            self.events.append(event)
            self.cond.notify_all()

    def start(self) -> None:
        threading.Thread(target=self._work, daemon=True).start()

    def queue_reroll(self, scene_id: str, kind: str) -> None:
        with self.cond:
            if scene_id not in self.queued[kind]:
                self.queued[kind].append(scene_id)
        self.push({"type": "queued", "scene_id": scene_id, "kind": kind})

    def follow_up(self, reroll_images=(), reroll_motion=()) -> "Run":
        """A new run with these options that redoes only the given scenes;
        everything else comes from the cache."""
        options = dataclasses.replace(self.options, force=False, force_from=None,
                                      reroll_images=list(reroll_images),
                                      reroll_motion=list(reroll_motion))
        run = Run(options, self.upload_id)
        RUNS[run.id] = run
        run.start()
        return run

    def _chain(self) -> None:
        """Before the terminal event: start the follow-up for queued rerolls
        and announce it, so the browser switches to it."""
        with self.cond:
            images, motion = self.queued["image"], self.queued["motion"]
            self.queued = {"image": [], "motion": []}
        if images or motion:
            self.push({"type": "next", "run_id": self.follow_up(images, motion).id})

    def _on_event(self, event: dict) -> None:
        if event.get("type") == "done":
            self._chain()
        self.push(event)

    def _work(self) -> None:
        from .pipeline import PipelineCancelled, run_pipeline

        self.push({"type": "started", "run_id": self.id,
                   "upload_id": self.upload_id})
        try:
            run_pipeline(self.options,
                         on_progress=lambda line: self.push(
                             {"type": "log", "line": str(line)}),
                         on_event=self._on_event, cancel=self.cancel)
        except PipelineCancelled:
            self.push({"type": "cancelled"})  # a cancel drops queued rerolls too
        except Exception as e:  # reported to the browser, never swallowed
            self._chain()  # the follow-up also retries what failed (all cached)
            self.push({"type": "error", "message": str(e),
                       "kind": type(e).__name__})


RUNS: dict[str, Run] = {}


def active_run() -> Run | None:
    return next((r for r in RUNS.values() if r.status == "running"), None)


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
    return PipelineOptions(base_image=image, **raw)


def create_app():
    from fastapi import FastAPI, HTTPException, Request, UploadFile
    from fastapi.responses import FileResponse, StreamingResponse
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
        run = Run(opts, body["upload_id"])
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
        run = Run(PipelineOptions(**fields, output_dir=OUTPUT_ROOT / name,
                                  force_from=force_from), "")
        RUNS[run.id] = run
        run.start()
        return {"run_id": run.id}

    @app.post("/api/runs/{run_id}/retry")
    def retry(run_id: str):
        """Same options, nothing forced: resumes at the step that failed."""
        run = RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, "unknown run")
        if active_run():
            raise HTTPException(409, "a video is already being generated")
        return {"run_id": run.follow_up().id}

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str, request: Request):
        run = RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, "unknown run")
        start = int(request.headers.get("last-event-id", -1)) + 1

        def stream():
            i = start
            while True:
                with run.cond:
                    if i >= len(run.events):
                        run.cond.wait(timeout=15)
                    batch = run.events[i:]
                if not batch:
                    yield ": keep-alive\n\n"
                    continue
                for event in batch:
                    yield f"id: {i}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    i += 1
                    if event["type"] in TERMINAL:
                        return

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.post("/api/runs/{run_id}/reroll")
    async def reroll(run_id: str, request: Request):
        """Another variation of one scene's image or motion. Queued while the
        run works; otherwise starts a follow-up run right away."""
        run = RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, "unknown run")
        body = await request.json()
        scene_id, kind = str(body.get("scene_id", "")), body.get("kind")
        if kind not in ("image", "motion") or not scene_id:
            raise HTTPException(400, "expected scene_id and kind image|motion")
        if run.status == "running":
            run.queue_reroll(scene_id, kind)
            return {"queued": True}
        if active_run():
            raise HTTPException(409, "a video is already being generated")
        nxt = run.follow_up(*(([scene_id], []) if kind == "image" else ([], [scene_id])))
        return {"run_id": nxt.id}

    @app.post("/api/runs/{run_id}/cancel")
    def cancel(run_id: str):
        run = RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, "unknown run")
        run.cancel.set()
        return {"ok": True}

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
