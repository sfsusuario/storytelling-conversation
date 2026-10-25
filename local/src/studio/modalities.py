"""Modality registry: each video generator plugged into the studio.

A modality brings its own FastAPI app (mounted at /m/<id>/), the folder
where it writes finished runs, the route its backend uses for those files
and a history reader. Adding a new one = one more Modality entry here plus
its section in web/src/modalities/.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .history import read_charla, read_cuento, read_escalator


@dataclass(frozen=True)
class Modality:
    id: str                     # URL slug: /m/<id>/ (API), tab id in the web app
    name: str
    icon: str
    description: str
    app: Callable[[], object]   # factory of the modality's FastAPI app
    output: Path                # where its finished runs live
    media_route: str            # absolute URL prefix its backend hands out for files
    history: Callable[[str, Path, str], list[dict]]
    can_delete: bool = True     # its app implements DELETE /api/history/{name}


def _charla_app():
    from charla.web import create_app
    return create_app()


def _escalator_app():
    from escalator.web import create_app
    return create_app()


def _cuento_app():
    from cuento.web import create_app
    return create_app()


def default_modalities() -> list[Modality]:
    from escalator.config import OUTPUT_ROOT as escalera_output
    return [
        Modality(
            id="conversacion", name="Conversación", icon="🎭",
            description="Rick y Morty conversan sobre un tema o noticia.",
            app=_charla_app, output=Path("output"), media_route="/media",
            history=read_charla),
        Modality(
            id="escalera", name="Escalera", icon="🪜",
            description="Tu retrato sube 5 niveles de personajes con una frase.",
            app=_escalator_app, output=escalera_output, media_route="/files",
            history=read_escalator),
        # output/cuento lives under output/, so Conversación's /media mount
        # (first) already serves its files at /media/cuento/...
        Modality(
            id="cuento", name="Cuento", icon="📖",
            description="Un cuento ilustrado en escenas, narrado, con tu foto o con personajes inventados.",
            app=_cuento_app, output=Path("output/cuento"), media_route="/media/cuento",
            history=read_cuento),
    ]


def check_unique(modalities: list[Modality]) -> None:
    """Backends hand out absolute media URLs served at the studio root: two
    modalities may not share an id or a media route."""
    for attr in ("id", "media_route"):
        values = [getattr(m, attr) for m in modalities]
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate modality {attr}: {values}")
