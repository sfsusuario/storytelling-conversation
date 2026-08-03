from __future__ import annotations

import glob
import os
import shutil
import subprocess


class FfmpegError(RuntimeError):
    pass


def _local_fallback(exe: str) -> str | None:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    patterns = [
        os.path.join(local, "ffmpeg", "*", "bin", f"{exe}.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Packages",
                     "Gyan.FFmpeg*", "**", "bin", f"{exe}.exe"),
    ]
    for pattern in patterns:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            return matches[0]
    return None


def find_ffmpeg(exe: str = "ffmpeg") -> str | None:
    return shutil.which(exe) or _local_fallback(exe)


def require_ffmpeg() -> tuple[str, str]:
    """Return (ffmpeg, ffprobe) paths or raise with install instructions."""
    ffmpeg = find_ffmpeg("ffmpeg")
    ffprobe = find_ffmpeg("ffprobe")
    if not ffmpeg or not ffprobe:
        raise FfmpegError(
            "ffmpeg/ffprobe not found. Install with:  winget install Gyan.FFmpeg\n"
            "(or unzip a static build into %LOCALAPPDATA%\\ffmpeg\\), "
            "then restart your terminal."
        )
    return ffmpeg, ffprobe


def run_ffmpeg(ffmpeg: str, args: list[str]) -> None:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-20:])
        raise FfmpegError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}\n"
                          f"command: {' '.join(cmd)}")


def probe_duration(ffprobe: str, path: os.PathLike | str) -> float:
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise FfmpegError(f"ffprobe could not read duration of {path}:\n{proc.stderr}")
    return float(proc.stdout.strip())


def probe_video(ffprobe: str, path: os.PathLike | str) -> tuple[int, int, float]:
    """Return (width, height, duration_seconds) of the first video stream."""
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration",
         "-of", "default=noprint_wrappers=1", str(path)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise FfmpegError(f"ffprobe could not read {path}:\n{proc.stderr}")
    values: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    try:
        return int(values["width"]), int(values["height"]), float(values["duration"])
    except (KeyError, ValueError) as e:
        raise FfmpegError(f"ffprobe returned no video info for {path}") from e
