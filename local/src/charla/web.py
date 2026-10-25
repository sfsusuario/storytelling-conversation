"""Web UI backend (charla-web): FastAPI serving the React app in server/frontend/dist.

A parallel, simpler front end to the Gradio UI (charla-ui stays as the
advanced mode). Long work runs in background jobs; the browser follows each
job through Server-Sent Events, with log lines turned into structured
progress events (stage, per-turn audio/clip, per-video batch status).
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import re
import shutil
import sys
import threading
import uuid
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import (DEFAULT_BATCH_THEME, DEFAULT_BG_VOLUME, DEFAULT_LANGUAGE,
                     DEFAULT_MAX_TURNS, DEFAULT_MIN_TURNS,
                     DEFAULT_OLLAMA_MODEL, DEFAULT_TEXT_MODEL,
                     DEFAULT_TTS_ENGINE, DEFAULT_WATERMARK, LANGUAGE_NAMES,
                     PipelineOptions)

WEB_DIST = Path(__file__).resolve().parents[3] / "server" / "frontend" / "dist"
OUTPUT = Path("output")
DEMO_SCRIPT = Path("examples/demo_script.json")
DEFAULT_PORT = 7870

# Options the browser may set when writing the script; render-only ones
# (pipeline.RENDER_FIELDS) may also be changed again on approve.
_SCRIPT_FIELDS = {"language", "max_turns", "min_turns", "text_provider",
                  "text_model"}


# ---------------------------------------------------------------------------
# Log line -> progress event
# ---------------------------------------------------------------------------

_STAGES = {"[1/4]": "script", "[2/4]": "voice", "[3/4]": "timeline",
           "[4/4]": "render"}
_AUDIO = re.compile(r"^  (?:tts|rvc|xtts|chatterbox): turn_(\d+)")
_CLIP = re.compile(r"^  clip: turn_(\d+)")
_VIDEO = re.compile(r"^\[video (\d+)/(\d+)\] (.*)")
_VIDEO_OK = re.compile(r"^\s*✓ (.*) \((\d+)s\)$")
_VIDEO_FAIL = re.compile(r"^\s*✗ falló: (.*)")


def classify(msg: str, indent: int = 0) -> dict:
    """One pipeline/batch log line as a structured event. `indent` is how
    far the batch shifts the pipeline lines it relays (2 spaces)."""
    text = msg.strip("\n")   # batch prefixes "[video n/m]" with a newline
    event: dict = {"kind": "log", "text": text}
    if m := _VIDEO.match(text):
        event.update(kind="video", index=int(m[1]), total=int(m[2]),
                     topic=m[3])
        return event
    if m := _VIDEO_OK.match(text):
        event.update(kind="video_ok", name=m[1], seconds=int(m[2]))
        return event
    if m := _VIDEO_FAIL.match(text):
        event.update(kind="video_fail", error=m[1])
        return event
    inner = text[indent:] if indent and text.startswith(" " * indent) else text
    for tag, stage in _STAGES.items():
        if inner.startswith(tag):
            event.update(kind="stage", stage=stage)
    if m := _AUDIO.match(inner):
        event.update(kind="audio", turn=int(m[1]))
    elif m := _CLIP.match(inner):
        event.update(kind="clip", turn=int(m[1]))
    elif inner.startswith("done:"):
        event.update(kind="stage", stage="done")
    return event


# ---------------------------------------------------------------------------
# Background jobs (single local user: kept in memory, never purged)
# ---------------------------------------------------------------------------


class Job:
    def __init__(self, indent: int = 0):
        self.id = uuid.uuid4().hex[:12]
        self.events: list[dict] = []
        self.done = False
        self.stop = threading.Event()
        self.indent = indent

    def log(self, msg) -> None:
        self.events.append(classify(str(msg), self.indent))

    def start(self, work) -> "Job":
        """Run work(job) -> result dict in a thread; ends with a result or
        error event, then {"kind": "end"}."""
        def target():
            try:
                self.events.append({"kind": "result", **work(self)})
            except Exception as e:  # shown in the browser
                self.events.append({"kind": "error", "text": str(e)})
            finally:
                self.done = True
                self.events.append({"kind": "end"})
        threading.Thread(target=target, daemon=True).start()
        _JOBS[self.id] = self
        return self


# shortcut: unbounded in-memory registry; fine for a local single-user app.
_JOBS: dict[str, Job] = {}
_DRAFTS: dict[str, object] = {}    # script job id -> pipeline.ScriptDraft


def _media_url(path: Path | str | None) -> str | None:
    if not path:
        return None
    p = Path(path).resolve()
    try:
        rel = p.relative_to(OUTPUT.resolve()).as_posix()
    except ValueError:
        return None
    return f"/media/{rel}?t={int(p.stat().st_mtime)}"


def _engines() -> list[str]:
    from .chatterbox import chatterbox_available
    from .xtts import xtts_available
    return (["edge"] + (["xtts"] if xtts_available() else [])
            + (["chatterbox"] if chatterbox_available() else []))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


class ScriptRequest(BaseModel):
    topic: str = ""
    demo: bool = False
    feedback: str = ""
    options: dict = Field(default_factory=dict)


class ApproveRequest(BaseModel):
    options: dict = Field(default_factory=dict)
    redo_voice: bool = False   # discard voices + clips: a fresh take, same script


class BatchRequest(BaseModel):
    count: int = Field(3, ge=1, le=20)
    source: str = "bank"
    theme: str = DEFAULT_BATCH_THEME
    model: str = DEFAULT_OLLAMA_MODEL
    tts_engine: str = DEFAULT_TTS_ENGINE
    language: str = DEFAULT_LANGUAGE
    topics: list[str] = Field(default_factory=list)


def _script_options(req: ScriptRequest) -> PipelineOptions:
    from .pipeline import RENDER_FIELDS
    unknown = set(req.options) - _SCRIPT_FIELDS - RENDER_FIELDS
    if unknown:
        raise HTTPException(422, "Unknown options: " + ", ".join(sorted(unknown)))
    if not req.demo and not req.topic.strip():
        raise HTTPException(400, "Escribe un tema o usa el guion de ejemplo.")
    opts = dict(req.options)
    if "max_turns" in opts:
        opts["max_turns"] = int(opts["max_turns"])
        opts.setdefault("min_turns", min(DEFAULT_MIN_TURNS, opts["max_turns"]))
    return PipelineOptions(
        input_text="" if req.demo else req.topic.strip(),
        script_file=DEMO_SCRIPT if req.demo else None,
        script_feedback="" if req.demo else req.feedback.strip(), **opts)


def create_app() -> FastAPI:
    app = FastAPI(title="Charla")

    @app.get("/api/defaults")
    def defaults():
        from .batch import ALL_AREAS, bank_areas
        from .script_gen import list_ollama_models
        engines = _engines()
        return {
            "engines": engines,
            "tts_engine": (DEFAULT_TTS_ENGINE if DEFAULT_TTS_ENGINE in engines
                           else "edge"),
            "languages": [{"code": c, "name": n}
                          for c, n in LANGUAGE_NAMES.items()],
            "language": DEFAULT_LANGUAGE,
            "max_turns": DEFAULT_MAX_TURNS,
            "text_provider": "auto",
            "text_model": DEFAULT_TEXT_MODEL,
            "ollama_models": list_ollama_models() or [],
            "ollama_default": DEFAULT_OLLAMA_MODEL,
            "subtitles": True,
            "watermark": DEFAULT_WATERMARK,
            "bg_volume": DEFAULT_BG_VOLUME,
            "areas": [ALL_AREAS] + bank_areas(),
            "batch_theme": DEFAULT_BATCH_THEME,
        }

    @app.get("/api/ideas")
    def ideas(source: str = "bank", area: str = "", model: str = "",
              exclude: list[str] = Query(default=[])):
        from .batch import idea_choices
        try:
            pairs = idea_choices(source, area, model or None, exclude)
        except Exception as e:
            raise HTTPException(400, str(e))
        return [{"label": label, "topic": topic} for label, topic in pairs]

    @app.get("/api/topics")
    def topics(count: int = 3, source: str = "bank",
               theme: str = DEFAULT_BATCH_THEME,
               model: str = DEFAULT_OLLAMA_MODEL):
        from .batch import generate_topics
        try:
            found = generate_topics(count, source, theme, model,
                                    log=lambda *_: None)
        except Exception as e:
            raise HTTPException(400, str(e))
        return [t.tema for t in found]

    @app.post("/api/video/script")
    def video_script(req: ScriptRequest):
        options = _script_options(req)

        def work(job: Job) -> dict:
            from .pipeline import generate_script_stage
            draft = generate_script_stage(options, on_progress=job.log)
            _DRAFTS[job.id] = draft
            return {"draft": job.id, "title": draft.script["title"],
                    "turns": draft.script["turns"], "social": draft.social}
        return {"job": Job().start(work).id}

    @app.post("/api/video/{draft_id}/approve")
    def video_approve(draft_id: str, req: ApproveRequest):
        from .pipeline import with_render_options
        from .timings import engine_key, estimate_seconds
        draft = _DRAFTS.get(draft_id)
        if draft is None:
            raise HTTPException(404, "Ese guion ya no existe; genéralo de nuevo.")
        try:
            draft = with_render_options(draft, **req.options)
        except Exception as e:
            raise HTTPException(422, str(e))

        def work(job: Job) -> dict:
            from .pipeline import _apply_force, continue_pipeline
            if req.redo_voice:  # same invalidation as --force-from tts
                _apply_force(draft.output_dir,
                             dataclasses.replace(draft.options, force=False,
                                                 force_from="tts"), job.log)
            result = continue_pipeline(draft, on_progress=job.log)
            return {"video_url": _media_url(result.final_video),
                    "title": result.title, "social": result.social,
                    "folder": str(result.output_dir.resolve())}
        job = Job().start(work)
        eta = estimate_seconds(engine_key(draft.options.tts_engine,
                                          draft.use_rvc), len(draft.turns))
        return {"job": job.id, "eta": eta, "turns": len(draft.turns)}

    @app.post("/api/batch")
    def batch(req: BatchRequest):
        from .batch import run_batch, topics_from_lines

        def work(job: Job) -> dict:
            result = run_batch(
                count=req.count, theme=req.theme, model=req.model,
                tts_engine=req.tts_engine, language=req.language,
                source=req.source,
                topics=topics_from_lines(req.topics) or None,
                log=job.log, should_stop=job.stop.is_set)
            items = []
            for item in result.items:
                data = dataclasses.asdict(item)
                data["video_url"] = _media_url(item.video) if item.ok else None
                items.append(data)
            return {"folder": str(result.folder.resolve()),
                    "publish_text": result.publish_text, "items": items}
        return {"job": Job(indent=2).start(work).id}

    @app.post("/api/batch/{job_id}/stop")
    def batch_stop(job_id: str):
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "Lote desconocido")
        job.stop.set()
        return {"ok": True}

    @app.delete("/api/history/{name}")
    def history_delete(name: str):
        """Remove one finished run folder (same contract as the escalator
        modality, used by storytelling-studio's shared history)."""
        folder = OUTPUT / name
        # name comes from the client: only a plain run folder name
        if (not name or name.startswith((".", "_")) or Path(name).name != name
                or folder.resolve().parent != OUTPUT.resolve()):
            raise HTTPException(400, f"invalid run name: {name!r}")
        if not (folder / "final.mp4").is_file():
            raise HTTPException(404, "unknown video")
        shutil.rmtree(folder)
        return {"deleted": name}

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, start: int = 0):
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "Trabajo desconocido")

        async def stream():
            i = start
            while True:
                while i < len(job.events):
                    yield ("data: " + json.dumps(job.events[i],
                                                 ensure_ascii=False) + "\n\n")
                    i += 1
                if job.done and i >= len(job.events):
                    return
                await asyncio.sleep(0.3)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    OUTPUT.mkdir(exist_ok=True)
    app.mount("/media", StaticFiles(directory=OUTPUT), name="media")
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    else:
        @app.get("/", response_class=HTMLResponse)
        def missing_build():
            return ("<h2>Falta compilar la interfaz</h2><p>Ejecuta "
                    "<code>.\\run-web.ps1</code> (o <code>cd web; npm install; "
                    "npm run build</code>).</p>")
    return app


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="charla-web",
                                description="Charla web UI (React)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args(argv)
    import uvicorn
    if not WEB_DIST.is_dir():
        print("aviso: falta server/frontend/dist; ejecuta .\\run-web.ps1 o "
              "'cd ../server/frontend; npm install; npm run build'")
    url = f"http://127.0.0.1:{args.port}"
    print(f"Charla web: {url}")
    if not args.no_browser:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port,
                log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
