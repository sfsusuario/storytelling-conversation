"""Background runs shared by the modalities that render scene by scene
(Escalera, Cuento).

One pipeline at a time per modality (one GPU) in a worker thread. Its
structured events are kept per run and streamed over SSE, so a reloaded page
or another device replays them from the start (or from Last-Event-ID) and
keeps following. Rerolls asked for while a run works are queued and redone by
a follow-up run; retry and cancel work the same way for every modality.

A modality hands each Run its pipeline function, the exception that pipeline
raises when cancelled, the URL mapper for the files it hands out and its own
registry (so one modality's run never blocks another's).
"""
import dataclasses
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

TERMINAL = {"done", "error", "cancelled"}


def make_file_url(prefix: str, root: Path) -> Callable[[str | Path | None], str | None]:
    """URL mapper: <prefix>/<path relative to root>, None for anything else."""
    def file_url(path: str | Path | None) -> str | None:
        if not path:
            return None
        try:
            rel = Path(path).resolve().relative_to(root.resolve())
        except ValueError:
            return None
        url = f"{prefix}/{rel.as_posix()}"
        # mtime busts the browser cache when a stage regenerates the same file name
        return f"{url}?v={int(Path(path).stat().st_mtime)}" if Path(path).exists() else url
    return file_url


class Run:
    def __init__(self, options, upload_id: str, *, registry: dict,
                 pipeline: Callable, cancelled: type[BaseException],
                 url: Callable[[str | Path | None], str | None]):
        self.id = uuid.uuid4().hex[:12]
        self.upload_id = upload_id
        self.options = options
        self.registry = registry
        self.pipeline = pipeline
        self.cancelled = cancelled
        self.url = url
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
                event[f"{key}_url"] = self.url(event[key])
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
        run = Run(options, self.upload_id, registry=self.registry,
                  pipeline=self.pipeline, cancelled=self.cancelled, url=self.url)
        self.registry[run.id] = run
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
        self.push({"type": "started", "run_id": self.id,
                   "upload_id": self.upload_id})
        try:
            self.pipeline(self.options,
                          on_progress=lambda line: self.push(
                              {"type": "log", "line": str(line)}),
                          on_event=self._on_event, cancel=self.cancel)
        except self.cancelled:
            self.push({"type": "cancelled"})  # a cancel drops queued rerolls too
        except Exception as e:  # reported to the browser, never swallowed
            self._chain()  # the follow-up also retries what failed (all cached)
            self.push({"type": "error", "message": str(e),
                       "kind": type(e).__name__})


def active_run(registry: dict) -> Run | None:
    return next((r for r in registry.values() if r.status == "running"), None)


def add_run_routes(app, registry: dict) -> None:
    """Endpoints every modality shares: live events, reroll, retry, cancel."""
    from fastapi import HTTPException, Request
    from fastapi.responses import StreamingResponse

    def get_run(run_id: str) -> Run:
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(404, "unknown run")
        return run

    @app.post("/api/runs/{run_id}/retry")
    def retry(run_id: str):
        """Same options, nothing forced: resumes at the step that failed."""
        run = get_run(run_id)
        if active_run(registry):
            raise HTTPException(409, "a video is already being generated")
        return {"run_id": run.follow_up().id}

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str, request: Request):
        run = get_run(run_id)
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
        run = get_run(run_id)
        body = await request.json()
        scene_id, kind = str(body.get("scene_id", "")), body.get("kind")
        if kind not in ("image", "motion") or not scene_id:
            raise HTTPException(400, "expected scene_id and kind image|motion")
        if run.status == "running":
            run.queue_reroll(scene_id, kind)
            return {"queued": True}
        if active_run(registry):
            raise HTTPException(409, "a video is already being generated")
        nxt = run.follow_up(*(([scene_id], []) if kind == "image" else ([], [scene_id])))
        return {"run_id": nxt.id}

    @app.post("/api/runs/{run_id}/cancel")
    def cancel(run_id: str):
        get_run(run_id).cancel.set()
        return {"ok": True}
