from __future__ import annotations

from pathlib import Path

from .config import CHARACTERS
from .ffutil import probe_video


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


def validate_clips(ffprobe: str, chars: dict[str, dict[str, Path]],
                   log=print) -> None:
    """Warn when a clip strays from the expected 720x1280 ~10s loop format."""
    for name, clips in chars.items():
        for emotion, path in clips.items():
            w, h, dur = probe_video(ffprobe, path)
            if (w, h) != (720, 1280) or not 8.0 <= dur <= 12.0:
                log(f"  warning: {name}/{path.name} is {w}x{h} {dur:.1f}s "
                    "(expected 720x1280 ~10s); render may look off")
