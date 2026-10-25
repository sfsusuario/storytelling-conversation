"""Storytelling Studio server: the public face (api.storyteller.fierro.dev).

It runs nothing itself. Every /api, /m, /media and /files request from the web
is queued for the worker on the home PC, which runs it against the local
studio and streams the reply back (SSE progress included). Videos, thumbnails
and the last JSON answers are cached on disk, so the history can still be
browsed, downloaded and shared from the phone while the PC is off.

    web (Netlify) --HTTPS--> this server <--long-poll-- worker (home PC) --> studio :7880

Run:  uvicorn main:app --env-file .env   (see install.sh / run-server-local.ps1)
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

RELAYED = ("api", "m", "media", "files")
CACHED_MEDIA = ("/media/", "/files/", "/api/thumb/")
FORWARD_HEADERS = ("content-type", "accept", "last-event-id")
REPLY_HEADERS = ("content-type", "etag", "content-disposition", "cache-control", "last-modified")
COOKIE = "studio_session"
SESSION_DAYS = 30
OFFLINE = "Tu PC está apagado o el worker no está corriendo (.\\run-worker.ps1)."


class Pending:
    """One web request waiting for the worker's reply."""

    def __init__(self, item: dict):
        self.item = item
        self.head: asyncio.Future = asyncio.get_running_loop().create_future()
        self.chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.gone = False  # the browser left: tell the worker to stop streaming


class Hub:
    def __init__(self, offline_after: float):
        self.queue: asyncio.Queue[Pending] = asyncio.Queue()
        self.pending: dict[str, Pending] = {}
        self.polling = 0
        self.last_seen = 0.0
        self.offline_after = offline_after

    def online(self) -> bool:
        return self.polling > 0 or time.monotonic() - self.last_seen < self.offline_after

    def submit(self, item: dict) -> Pending:
        p = Pending({"id": uuid.uuid4().hex, **item})
        self.pending[p.item["id"]] = p
        self.queue.put_nowait(p)
        return p

    def drop(self, p: Pending) -> None:
        p.gone = True
        self.pending.pop(p.item["id"], None)


class Cache:
    """Last good reply per URL: <sha1>.bin + <sha1>.json (headers)."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _paths(self, key: str) -> tuple[Path, Path]:
        h = hashlib.sha1(key.encode()).hexdigest()
        return self.root / f"{h}.bin", self.root / f"{h}.json"

    def get(self, key: str) -> tuple[Path, dict] | None:
        data, meta = self._paths(key)
        if data.is_file() and meta.is_file():
            return data, json.loads(meta.read_text(encoding="utf-8"))
        return None

    async def store(self, key: str, chunks: asyncio.Queue, headers: dict) -> tuple[Path, dict]:
        data, meta = self._paths(key)
        tmp = data.with_suffix(".part")
        with tmp.open("wb") as f:
            while (chunk := await chunks.get()) is not None:
                f.write(chunk)
        tmp.replace(data)  # atomic: a cut transfer never replaces a good copy
        meta.write_text(json.dumps(headers), encoding="utf-8")
        return data, headers


def create_app(password: str | None = None, worker_token: str | None = None,
               cache_dir: Path | None = None, offline_after: float = 40.0) -> FastAPI:
    password = password if password is not None else os.environ.get("STUDIO_PASSWORD", "")
    worker_token = worker_token if worker_token is not None else os.environ.get("WORKER_TOKEN", "")
    if len(password) < 8 or len(worker_token) < 24:
        raise RuntimeError("Configura STUDIO_PASSWORD (8+ caracteres) y WORKER_TOKEN (24+) en .env")
    secret = (os.environ.get("SECRET_KEY") or worker_token).encode()
    secure = os.environ.get("COOKIE_SECURE", "1") != "0"
    # the production web is always allowed; WEB_ORIGINS adds others (local tests)
    origins = ["https://storyteller.fierro.dev", "https://storytelling.fierro.dev"] + [
        o.strip().rstrip("/") for o in os.environ.get("WEB_ORIGINS", "").split(",") if o.strip()]
    cache = Cache(cache_dir or Path(os.environ.get("CACHE_DIR", "cache")))
    hub = Hub(offline_after)

    app = FastAPI(title="Storytelling Studio (servidor)", docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    # ── sessions (phone/browser) ────────────────────────────────────────────
    def sign(exp: int) -> str:
        return hmac.new(secret, str(exp).encode(), hashlib.sha256).hexdigest()

    def logged_in(request: Request) -> bool:
        exp, _, sig = (request.cookies.get(COOKIE) or "").partition(".")
        return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, sign(int(exp)))

    @app.get("/health")
    def health():
        return {"ok": True, "worker_online": hub.online()}

    @app.post("/auth/login")
    async def login(request: Request):
        body = await request.json()
        if not hmac.compare_digest(str(body.get("password", "")).encode(), password.encode()):
            await asyncio.sleep(1)  # slows down guessing
            raise HTTPException(401, "Contraseña incorrecta")
        exp = int(time.time()) + SESSION_DAYS * 86400
        res = JSONResponse({"ok": True})
        res.set_cookie(COOKIE, f"{exp}.{sign(exp)}", max_age=SESSION_DAYS * 86400,
                       httponly=True, secure=secure, samesite="lax")
        return res

    @app.post("/auth/logout")
    def logout():
        res = JSONResponse({"ok": True})
        res.delete_cookie(COOKIE)
        return res

    @app.get("/auth/status")
    def status(request: Request):
        if not logged_in(request):
            return {"authenticated": False}
        seen = round(time.monotonic() - hub.last_seen) if hub.last_seen else None
        return {"authenticated": True, "worker_online": hub.online(), "worker_seen_ago": seen}

    # ── worker side (home PC, bearer token) ─────────────────────────────────
    def worker_auth(request: Request) -> None:
        got = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(got.encode(), worker_token.encode()):
            raise HTTPException(401, "token de worker inválido")

    def pending(request: Request, rid: str) -> Pending:
        worker_auth(request)
        p = hub.pending.get(rid)
        if p is None or p.gone:
            raise HTTPException(410, "el navegador ya no espera esta respuesta")
        return p

    @app.get("/worker/next")
    async def worker_next(request: Request, wait: float = 25):
        worker_auth(request)
        hub.polling += 1
        try:
            while True:
                try:
                    p = await asyncio.wait_for(hub.queue.get(), min(wait, 30))
                except asyncio.TimeoutError:
                    return Response(status_code=204)
                if not p.gone:
                    # shortcut: if this reply is lost on the way the browser waits until its 60 s timeout
                    return p.item
        finally:
            hub.polling -= 1
            hub.last_seen = time.monotonic()

    @app.post("/worker/{rid}/head")
    async def worker_head(rid: str, request: Request):
        p = pending(request, rid)
        if not p.head.done():
            p.head.set_result(await request.json())
        return {"ok": True}

    @app.post("/worker/{rid}/chunk")
    async def worker_chunk(rid: str, request: Request):
        pending(request, rid).chunks.put_nowait(await request.body())
        return {"ok": True}

    @app.post("/worker/{rid}/end")
    def worker_end(rid: str, request: Request):
        p = pending(request, rid)
        p.chunks.put_nowait(None)
        hub.pending.pop(rid, None)
        return {"ok": True}

    # ── relay (everything the web app calls) ────────────────────────────────
    def from_cache(entry: tuple[Path, dict], download: bool, offline: bool = False) -> FileResponse:
        path, headers = entry
        extra = {"X-Offline": "1"} if offline else {}
        if headers.get("etag"):
            extra["ETag"] = headers["etag"]
        name = headers.get("name") if download else None
        return FileResponse(path, media_type=headers.get("content-type"), headers=extra,
                            filename=name, content_disposition_type="attachment")

    async def stream(p: Pending, sse: bool):
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(p.chunks.get(), 15)
                except asyncio.TimeoutError:
                    if sse:
                        yield b": ping\n\n"  # keeps Apache and the phone from closing a quiet stream
                    continue
                if chunk is None:
                    return
                yield chunk
        finally:
            hub.drop(p)

    async def relay(request: Request):
        if not logged_in(request):
            raise HTTPException(401, "Inicia sesión")
        path = request.url.path
        download = request.query_params.get("dl") == "1"
        query = urlencode([(k, v) for k, v in request.query_params.multi_items() if k != "dl"])
        key = f"{path}?{query}"
        get = request.method == "GET"
        media = get and path.startswith(CACHED_MEDIA)
        entry = cache.get(key) if get else None

        if not hub.online():
            if entry:
                return from_cache(entry, download, offline=True)
            raise HTTPException(503, OFFLINE)

        headers = {h: v for h in FORWARD_HEADERS if (v := request.headers.get(h))}
        if media and entry and entry[1].get("etag"):
            headers["if-none-match"] = entry[1]["etag"]  # unchanged video: worker answers 304
        body = await request.body()
        p = hub.submit({"method": request.method, "path": path, "query": query, "headers": headers,
                        "body": base64.b64encode(body).decode() if body else ""})
        try:
            head = await asyncio.wait_for(asyncio.shield(p.head), 60)
        except asyncio.TimeoutError:
            hub.drop(p)
            raise HTTPException(504, "El PC no respondió a tiempo.")

        status = head.get("status", 502)
        reply = {k: v for k, v in (head.get("headers") or {}).items() if k in REPLY_HEADERS}
        ctype = reply.get("content-type", "")
        if status == 304 and entry:
            hub.drop(p)
            return from_cache(entry, download)
        if status == 200 and (media or (get and ctype.startswith("application/json"))):
            try:
                stored = await cache.store(key, p.chunks, {**reply, "name": Path(path).name})
            finally:
                hub.drop(p)
            return from_cache(stored, download)
        return StreamingResponse(stream(p, ctype.startswith("text/event-stream")),
                                 status_code=status, headers=reply)

    for prefix in RELAYED:
        app.add_api_route(f"/{prefix}/{{rest:path}}", relay,
                          methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    return app


def __getattr__(name: str):
    # `uvicorn main:app` builds the app from the environment on first access,
    # so importing create_app (tests) never needs a configured .env
    if name == "app":
        return create_app()
    raise AttributeError(name)
