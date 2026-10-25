"""Storytelling Studio: one FastAPI app, one React app, every modality.

- Each modality's own FastAPI app is mounted at /m/<id>/ (its API, events,
  uploads), so its behavior is unchanged.
- The files each backend hands out with absolute URLs (/media/..., /files/...)
  are served at the root.
- /api/modalities, /api/history (shared, normalized) and /api/thumb.
- / serves the single React app (web/dist).

Run from the repo root (every modality reads ./.env and writes under ./output).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .history import collect, thumbnail
from .modalities import Modality, check_unique, default_modalities

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
THUMBS = Path("output") / "_cache" / "thumbs"
DEFAULT_PORT = 7880


def create_app(modalities: list[Modality] | None = None) -> FastAPI:
    modalities = modalities if modalities is not None else default_modalities()
    check_unique(modalities)
    by_id = {m.id: m for m in modalities}
    app = FastAPI(title="Storytelling Studio")

    @app.get("/api/modalities")
    def list_modalities():
        return [{"id": m.id, "name": m.name, "icon": m.icon,
                 "description": m.description} for m in modalities]

    @app.get("/api/history")
    def history(modality: str = ""):
        runs = collect([by_id[modality]] if modality in by_id else modalities)
        for run in runs:
            mod = by_id[run["modality"]]
            run["modality_name"], run["modality_icon"] = mod.name, mod.icon
        return runs

    @app.get("/api/thumb/{mid}/{name}")
    def thumb(mid: str, name: str):
        if mid not in by_id:
            raise HTTPException(404, "modalidad desconocida")
        try:
            path = thumbnail(by_id[mid].output, name, THUMBS / mid)
        except (ValueError, FileNotFoundError, subprocess.SubprocessError):
            raise HTTPException(404, "sin miniatura")
        return FileResponse(path, headers={"Cache-Control": "max-age=86400"})

    for mod in modalities:
        mod.output.mkdir(parents=True, exist_ok=True)
        app.mount(mod.media_route, StaticFiles(directory=mod.output), name=f"{mod.id}-files")
        app.mount(f"/m/{mod.id}", mod.app(), name=mod.id)

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    else:
        @app.get("/", response_class=HTMLResponse)
        def missing_build():
            return ("<h2>Falta compilar la interfaz</h2><p>Ejecuta "
                    "<code>.\\run-ui.ps1</code> (o <code>cd web; npm install; "
                    "npm run build</code>).</p>")
    return app


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="studio", description="Storytelling Studio (web)")
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("STUDIO_PORT", DEFAULT_PORT)))
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args(argv)
    import uvicorn
    if not WEB_DIST.is_dir():
        print("aviso: falta web/dist; ejecuta .\\run-ui.ps1 o 'cd web; npm install; npm run build'")
    url = f"http://127.0.0.1:{args.port}"
    print(f"Storytelling Studio: {url}")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
