from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .config import CACHE_DIR, CHARACTERS
from .ffutil import FfmpegError, MediaInfo, probe_media


class AssetsError(RuntimeError):
    pass


def scan_characters(chars_dir: Path) -> dict[str, dict[str, Path]]:
    """Map each character to its emotion clips: {"rick": {emotion: path}}.

    Files follow `<emotion>_<character>.mp4`; a bare `<emotion>.mp4` inside
    the character's folder is tolerated too (early asset drops missed the
    suffix).
    """
    if not chars_dir.is_dir():
        raise AssetsError(
            f"Characters directory not found: {chars_dir.resolve()}\n"
            "Expected characters/<name>/<emotion>_<name>.mp4 clips.")
    result: dict[str, dict[str, Path]] = {}
    for name in CHARACTERS:
        folder = chars_dir / name
        if not folder.is_dir():
            raise AssetsError(f"Missing character folder: {folder.resolve()}")
        clips: dict[str, Path] = {}
        for clip in sorted(folder.glob("*.mp4")):
            emotion = clip.stem
            if emotion.endswith(f"_{name}"):
                emotion = emotion[: -len(name) - 1]
            clips[emotion] = clip
        if not clips:
            raise AssetsError(f"No .mp4 clips in {folder.resolve()}")
        result[name] = clips
    return result


def available_emotions(chars: dict[str, dict[str, Path]]) -> list[str]:
    """Sorted intersection: only emotions every character can perform."""
    sets = [set(clips) for clips in chars.values()]
    common = set.intersection(*sets) if sets else set()
    if not common:
        raise AssetsError("Characters share no common emotion clips.")
    return sorted(common)


def probe_clips(ffprobe: str, chars: dict[str, dict[str, Path]],
                cache_file: Path | None = None) -> dict[Path, MediaInfo]:
    """MediaInfo of every character clip, cached across runs.

    Keyed by (path, mtime, size): only new or changed clips hit ffprobe, so
    a normal run spawns no ffprobe process at all for the 14 clips.
    """
    cache_file = cache_file or CACHE_DIR / "clips_probe.json"
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cached = {}
    result: dict[Path, MediaInfo] = {}
    fresh: dict[str, dict] = {}
    changed = False
    for clips in chars.values():
        for path in clips.values():
            st = path.stat()
            key = path.resolve().as_posix()
            stamp = f"{st.st_mtime_ns}|{st.st_size}"
            entry = cached.get(key)
            info = None
            if entry and entry.get("stamp") == stamp:
                try:
                    info = MediaInfo(**entry["info"])
                except (TypeError, KeyError):
                    info = None
            if info is None:
                info = probe_media(ffprobe, path)
                changed = True
            result[path] = info
            fresh[key] = {"stamp": stamp, "info": asdict(info)}
    if changed or set(fresh) != set(cached):
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(fresh, indent=1), encoding="utf-8")
            tmp.replace(cache_file)
        except OSError:
            pass  # best-effort cache
    return result


def validate_clips(ffprobe: str, chars: dict[str, dict[str, Path]],
                   log=print) -> dict[Path, MediaInfo]:
    """Warn when a clip strays from the expected 720x1280 ~10s loop format.
    Returns the probed info so the renderer does not probe again."""
    try:
        infos = probe_clips(ffprobe, chars)
    except FfmpegError as e:
        raise AssetsError(str(e)) from e
    for name, clips in chars.items():
        for emotion, path in clips.items():
            info = infos[path]
            if (info.width, info.height) != (720, 1280) \
                    or not 8.0 <= info.duration <= 12.0:
                log(f"  warning: {name}/{path.name} is "
                    f"{info.width}x{info.height} {info.duration:.1f}s "
                    "(expected 720x1280 ~10s); render may look off")
    return infos
