"""Worker: links this PC to the public server (api.storyteller.fierro.dev).

It long-polls the server for the requests the web app queued, runs each one
against the local studio (started here unless it is already running) and
streams the reply back, SSE progress included. Nothing listens on the
internet: every connection goes out from this PC.

    python -m studio.worker            (.\\run-worker.ps1)

Needs STUDIO_WORKER_TOKEN in .env (the server's WORKER_TOKEN) and, unless it
is the default, STUDIO_SERVER_URL.
"""
from __future__ import annotations

import argparse
import base64
import os
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

DEFAULT_SERVER = "https://api.storyteller.fierro.dev"
# only the studio's own routes; the server can never reach anything else here
ALLOWED = ("/api/", "/m/", "/media/", "/files/")
REPLY_HEADERS = ("content-type", "etag", "content-disposition", "cache-control", "last-modified")
FLUSH_BYTES = 1 << 20


class Gone(Exception):
    """The browser stopped waiting: stop reading the local stream."""


def handle(server: httpx.Client, local: httpx.Client, item: dict, log=print) -> None:
    rid, path = item["id"], item["path"]

    def post(what: str, **kw) -> None:
        r = server.post(f"/worker/{rid}/{what}", **kw)
        if r.status_code == 410:
            raise Gone()
        r.raise_for_status()

    try:
        if not path.startswith(ALLOWED) or ".." in path:
            post("head", json={"status": 403, "headers": {}})
            post("end")
            return
        url = path + (f"?{item['query']}" if item.get("query") else "")
        body = base64.b64decode(item["body"]) if item.get("body") else None
        with local.stream(item["method"], url, headers=item.get("headers") or {},
                          content=body) as r:
            headers = {k: v for k, v in r.headers.items() if k.lower() in REPLY_HEADERS}
            post("head", json={"status": r.status_code, "headers": headers})
            sse = r.headers.get("content-type", "").startswith("text/event-stream")
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf += chunk
                if sse or len(buf) >= FLUSH_BYTES:
                    post("chunk", content=bytes(buf))
                    buf.clear()
            if buf:
                post("chunk", content=bytes(buf))
        post("end")
    except Gone:
        pass
    except httpx.HTTPError as exc:
        log(f"  {item['method']} {path}: {exc}")
        try:  # tell the browser instead of leaving it waiting
            post("head", json={"status": 502, "headers": {"content-type": "application/json"}})
            post("chunk", content=b'{"detail": "El estudio local no respondi\\u00f3."}')
            post("end")
        except (Gone, httpx.HTTPError):
            pass


def run(server_url: str, token: str, local_url: str, stop: threading.Event | None = None,
        wait: float = 25, log=print) -> None:
    stop = stop or threading.Event()
    server = httpx.Client(base_url=server_url, headers={"Authorization": f"Bearer {token}"},
                          timeout=httpx.Timeout(60, read=wait + 15))
    local = httpx.Client(base_url=local_url, timeout=httpx.Timeout(30, read=None))
    pool = ThreadPoolExecutor(16, thread_name_prefix="relay")  # SSE streams hold a thread each
    backoff, linked = 2.0, False
    try:
        while not stop.is_set():
            try:
                # first poll answers at once, so "conectado" shows without waiting the long-poll
                r = server.get("/worker/next", params={"wait": wait if linked else 0})
            except httpx.HTTPError as exc:
                log(f"sin conexión con {server_url} ({exc.__class__.__name__}); reintento en {backoff:.0f}s")
                linked = False
                stop.wait(backoff)
                backoff = min(backoff * 2, 30)
                continue
            if r.status_code == 401:
                log("el servidor rechazó STUDIO_WORKER_TOKEN (debe ser igual a WORKER_TOKEN del servidor)")
                stop.wait(30)
                continue
            if r.status_code >= 500:
                stop.wait(backoff)
                continue
            backoff = 2.0
            if not linked:
                log(f"conectado a {server_url}: la web ya puede usar este PC")
                linked = True
            if r.status_code == 200:
                pool.submit(handle, server, local, r.json(), log)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        server.close()


def _port_busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    from charla.config import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser(prog="studio-worker", description=__doc__.splitlines()[0])
    p.add_argument("--server", default=os.environ.get("STUDIO_SERVER_URL", DEFAULT_SERVER))
    p.add_argument("--port", type=int, default=int(os.environ.get("STUDIO_PORT", 7880)),
                   help="puerto del estudio local")
    args = p.parse_args(argv)
    token = os.environ.get("STUDIO_WORKER_TOKEN", "")
    if not token:
        print("error: falta STUDIO_WORKER_TOKEN en .env (el WORKER_TOKEN del servidor)", file=sys.stderr)
        return 1
    if _port_busy(args.port):
        print(f"usando el estudio que ya corre en http://127.0.0.1:{args.port}")
    else:
        import uvicorn
        from .app import create_app
        server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=args.port,
                                               log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        while not server.started:
            time.sleep(0.1)
        print(f"estudio local en http://127.0.0.1:{args.port}")
    try:
        run(args.server.rstrip("/"), token, f"http://127.0.0.1:{args.port}")
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
