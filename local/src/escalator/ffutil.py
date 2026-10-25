from __future__ import annotations

import functools
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


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    # stdin=DEVNULL: parallel ffmpeg processes must not share the console's
    # stdin. utf-8 + replace: never die decoding a localized error message.
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL)


def run_ffmpeg(ffmpeg: str, args: list[str]) -> None:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", *args]
    proc = _run(cmd)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-20:])
        raise FfmpegError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}\n"
                          f"command: {' '.join(cmd)}")


# Intel Quick Sync (iGPU) first: same visual quality at a fraction of the CPU
# time. Probed once with a tiny encode; machines without QSV fall back to x264.
QSV_ARGS = ["-c:v", "h264_qsv", "-preset", "slower", "-global_quality", "20",
            "-look_ahead", "1", "-pix_fmt", "nv12"]
X264_ARGS = ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-tune", "stillimage", "-pix_fmt", "yuv420p"]


@functools.lru_cache(maxsize=None)
def video_encoder_args(ffmpeg: str) -> tuple[str, ...]:
    if os.environ.get("ESCALATE_ENCODER", "auto") != "x264":
        try:
            run_ffmpeg(ffmpeg, ["-f", "lavfi", "-i", "color=s=256x256:d=0.2",
                                *QSV_ARGS, "-f", "null", "-"])
            return tuple(QSV_ARGS)
        except FfmpegError:
            pass
    return tuple(X264_ARGS)


def probe_duration(ffprobe: str, path: os.PathLike | str) -> float:
    proc = _run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    if proc.returncode != 0 or not proc.stdout.strip():
        raise FfmpegError(f"ffprobe could not read duration of {path}:\n{proc.stderr}")
    return float(proc.stdout.strip())
