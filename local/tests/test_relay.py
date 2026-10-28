"""Server relay + worker end to end: web -> server -> worker -> local app."""
from __future__ import annotations

import asyncio
import importlib.util
import socket
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from studio import worker

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "server" / "backend" / "main.py").is_file())
spec = importlib.util.spec_from_file_location("relay_server", ROOT / "server" / "backend" / "main.py")
relay_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay_server)

PASSWORD, TOKEN = "clave-secreta", "t" * 32


def _serve(app) -> tuple[str, uvicorn.Server]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server


SLOW = b"frame-" * 400_000  # ~2.4 MB: several worker chunks
slow_calls: list[int] = []


def _fake_studio(media: Path) -> FastAPI:
    app = FastAPI()

    @app.get("/media/slow.mp4")
    def slow():
        slow_calls.append(1)

        async def gen():
            for i in range(0, len(SLOW), 600_000):
                yield SLOW[i:i + 600_000]
                await asyncio.sleep(0.2)
        return StreamingResponse(gen(), media_type="video/mp4",
                                 headers={"content-length": str(len(SLOW)), "etag": '"s1"'})

    @app.get("/api/history")
    def history():
        return [{"name": "uno"}]

    @app.post("/m/x/api/echo")
    async def echo(request: Request):
        return {"got": (await request.body()).decode()}

    @app.get("/m/x/api/events")
    def events():
        async def gen():
            for i in range(3):
                yield f"data: {i}\n\n"
                await asyncio.sleep(0.05)
        return StreamingResponse(gen(), media_type="text/event-stream")

    app.mount("/media", StaticFiles(directory=media))
    return app


def test_relay_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "0")  # plain http in the test
    media = tmp_path / "media"
    media.mkdir()
    (media / "v.mp4").write_bytes(b"video-1" * 1000)
    local_url, local_srv = _serve(_fake_studio(media))
    app = relay_server.create_app(PASSWORD, TOKEN, tmp_path / "cache", offline_after=1.5)
    server_url, server_srv = _serve(app)
    web = httpx.Client(base_url=server_url, timeout=20)

    assert web.get("/api/history").status_code == 401
    assert web.post("/auth/login", json={"password": "mala"}).status_code == 401
    assert web.post("/auth/login", json={"password": PASSWORD}).status_code == 200
    assert web.get("/api/history").status_code == 503  # PC off, nothing cached yet

    stop = threading.Event()
    t = threading.Thread(target=worker.run, args=(server_url, TOKEN, local_url, stop),
                         kwargs={"wait": 0.5, "log": lambda *_: None}, daemon=True)
    t.start()
    for _ in range(50):
        if web.get("/auth/status").json()["worker_online"]:
            break
        time.sleep(0.1)

    assert web.get("/api/history").json() == [{"name": "uno"}]
    assert web.post("/m/x/api/echo", content=b"hola").json() == {"got": "hola"}
    with web.stream("GET", "/m/x/api/events") as r:
        assert "data: 2" in r.read().decode()
    assert web.get("/media/v.mp4").content == b"video-1" * 1000
    ranged = web.get("/media/v.mp4", headers={"Range": "bytes=0-6"})
    assert ranged.status_code == 206 and ranged.content == b"video-1"
    dl = web.get("/media/v.mp4?dl=1")
    assert "attachment" in dl.headers["content-disposition"]
    assert web.get("/media/../secret").status_code in (403, 404)

    # two phones (or the player and the share button) at once: the PC uploads
    # the file once, the plain request streams it with its size, the ranged one
    # waits for the copy and gets a 206 from the cache
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        plain = pool.submit(web.get, "/media/slow.mp4")
        time.sleep(0.1)
        ranged = pool.submit(web.get, "/media/slow.mp4", headers={"Range": "bytes=0-5"})
        plain, ranged = plain.result(), ranged.result()
    assert plain.content == SLOW and plain.headers["content-length"] == str(len(SLOW))
    assert ranged.status_code == 206 and ranged.content == b"frame-"
    assert slow_calls == [1]

    (media / "v.mp4").write_bytes(b"video-2")  # regenerated: the etag changes
    assert web.get("/media/v.mp4").content == b"video-2"

    stop.set()
    t.join(5)
    time.sleep(1.6)
    offline = web.get("/api/history")
    assert offline.headers.get("x-offline") == "1" and offline.json() == [{"name": "uno"}]
    assert web.get("/media/v.mp4").content == b"video-2"  # sharing still works with the PC off
    assert web.post("/m/x/api/echo", content=b"x").status_code == 503

    local_srv.should_exit = server_srv.should_exit = True
