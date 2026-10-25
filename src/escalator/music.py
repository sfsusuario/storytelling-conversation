"""Open-source background music per style set.

Tracks by Kevin MacLeod (incompetech.com), licensed CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). They are downloaded once into
a local cache and reused; if the download fails (offline), the caller falls
back to the synthesized ambient soundscapes in config.BACKGROUND_SOUNDS.
"""
from __future__ import annotations

import os
import urllib.parse
import urllib.request
from pathlib import Path

_BASE = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"

# Calm-leaning track per style set (title must match incompetech's filename).
MUSIC_LIBRARY: dict[str, str] = {
    "medieval": "Minstrel Guild",
    "scifi": "Floating Cities",
    "corporate": "Deliberate Thought",
    "mythology": "Virtutes Instrumenti",
    "military": "Drums of the Deep",
    "pirate": "Skye Cuillin",
    "arcane": "Lightless Dawn",
    "epochs": "Teller of the Tales",
    "wealth": "Bossa Antigua",
    "tech": "Space Jazz",
    "anger": "Volatile Reaction",
    "excuses": "Monkeys Spinning Monkeys",
    "_default": "Carefree",
}


def track_title(style_set: str) -> str:
    return MUSIC_LIBRARY.get(style_set) or MUSIC_LIBRARY["_default"]


def attribution(style_set: str) -> str:
    # Exact credit format required by incompetech's CC BY 4.0 license.
    return (f'🎵 "{track_title(style_set)}" Kevin MacLeod (incompetech.com)\n'
            "Licensed under Creative Commons: By Attribution 4.0\n"
            "https://creativecommons.org/licenses/by/4.0/")


def _cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "escalator" / "music"


def music_file(style_set: str, log=print) -> Path | None:
    """Return the cached track for the set, downloading it on first use.

    Returns None when the download fails (caller should fall back to the
    synthesized soundscape).
    """
    title = track_title(style_set)
    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{title}.mp3"
    if out.exists() and out.stat().st_size > 100_000:
        return out

    url = _BASE + urllib.parse.quote(title) + ".mp3"
    tmp = out.with_suffix(".tmp")
    try:
        log(f'  music: descargando "{title}" (CC BY, incompetech.com)...')
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as resp, \
                open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
        if tmp.stat().st_size < 100_000:
            raise OSError("downloaded file too small")
        tmp.replace(out)
        return out
    except Exception as e:
        tmp.unlink(missing_ok=True)
        log(f"  music: descarga fallida ({e}); usando ambiente sintetizado")
        return None


def preview_file(style_set: str, source: str) -> Path:
    """A listenable sample of the background a video with this set would get."""
    if source == "track":
        track = music_file(style_set, log=lambda *_: None)
        if track is not None:
            return track

    from .config import background_graph
    from .ffutil import require_ffmpeg
    from .renderer import render_music_preview

    ffmpeg, _ = require_ffmpeg()
    out = _cache_dir() / f"ambient_{style_set}.m4a"
    if not (out.exists() and out.stat().st_size > 0):
        render_music_preview(ffmpeg, background_graph(style_set), out)
    return out
