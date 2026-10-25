from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

from .config import VIDEO_ENCODER, X264_PRESET


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
            "(or unzip a static build into %LOCALAPPDATA%\\ffmpeg\\; on "
            "Linux/Colab: apt-get install ffmpeg), then restart your terminal."
        )
    return ffmpeg, ffprobe


def _run(cmd: list[str], timeout: float | None = None
         ) -> subprocess.CompletedProcess:
    # stdin=DEVNULL: parallel ffmpeg processes must not share the console's
    # stdin. utf-8 + replace: never die decoding a localized error message.
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL, timeout=timeout)


def run_ffmpeg(ffmpeg: str, args: list[str]) -> None:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", *args]
    proc = _run(cmd)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-20:])
        raise FfmpegError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}\n"
                          f"command: {' '.join(cmd)}")


def probe_duration(ffprobe: str, path: os.PathLike | str) -> float:
    proc = _run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    if proc.returncode != 0 or not proc.stdout.strip():
        raise FfmpegError(f"ffprobe could not read duration of {path}:\n{proc.stderr}")
    return float(proc.stdout.strip())


def probe_video(ffprobe: str, path: os.PathLike | str) -> tuple[int, int, float]:
    """Return (width, height, duration_seconds) of the first video stream."""
    info = probe_media(ffprobe, path)
    return info.width, info.height, info.duration


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    duration: float
    frames: int        # video frames (nb_frames, or duration * fps)
    fps: float
    has_audio: bool


def _parse_rate(rate: str | None) -> float:
    num, _, den = (rate or "0/1").partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_media(ffprobe: str, path: os.PathLike | str) -> MediaInfo:
    """Everything the pipeline needs about a video file in one ffprobe call."""
    proc = _run(
        [ffprobe, "-v", "error",
         "-show_entries",
         "stream=codec_type,width,height,nb_frames,r_frame_rate"
         ":format=duration",
         "-of", "json", str(path)])
    if proc.returncode != 0:
        raise FfmpegError(f"ffprobe could not read {path}:\n{proc.stderr}")
    try:
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams") or []
        video = next(s for s in streams if s.get("codec_type") == "video")
        duration = float((data.get("format") or {}).get("duration") or 0.0)
        fps = _parse_rate(video.get("r_frame_rate"))
        try:
            frames = int(video.get("nb_frames"))
        except (TypeError, ValueError):
            frames = round(duration * fps)
        return MediaInfo(
            width=int(video["width"]), height=int(video["height"]),
            duration=duration, frames=frames, fps=fps,
            has_audio=any(s.get("codec_type") == "audio" for s in streams))
    except (StopIteration, KeyError, ValueError, TypeError) as e:
        raise FfmpegError(f"ffprobe returned no video info for {path}") from e


# ---------------------------------------------------------------------------
# Video encoder selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoEncoder:
    """One H.264 encoder profile. `pix_fmt` is what the filter graph must
    end with (h264_qsv only accepts nv12 from a software graph)."""
    name: str                      # qsv | nvenc | x264
    codec: str
    pix_fmt: str
    quality: tuple[str, ...]       # turn clips
    proxy_quality: tuple[str, ...]  # background proxy (re-decoded later)
    uses_threads: bool             # honours -threads (software encoders)

    def args(self, threads: int | None = None, proxy: bool = False,
             gop: int | None = None) -> list[str]:
        a = ["-c:v", self.codec,
             *(self.proxy_quality if proxy else self.quality)]
        if self.name != "qsv":
            a += ["-pix_fmt", self.pix_fmt]
        if gop:
            a += ["-g", str(gop)]
            if self.name == "x264":
                a += ["-keyint_min", str(gop), "-sc_threshold", "0"]
        if threads and self.uses_threads:
            a += ["-threads", str(threads)]
        return a

    @property
    def signature(self) -> str:
        """Goes into clip cache stamps: a stream-copy concat needs every
        clip encoded by the same encoder/settings."""
        return f"{self.codec}:{' '.join(self.quality)}"


_ENCODERS: dict[str, VideoEncoder] = {
    "qsv": VideoEncoder(
        "qsv", "h264_qsv", "nv12",
        ("-preset", "medium", "-global_quality", "22"),
        ("-preset", "medium", "-global_quality", "18"), False),
    "nvenc": VideoEncoder(
        "nvenc", "h264_nvenc", "yuv420p",
        ("-preset", "p4", "-rc", "vbr", "-cq", "22", "-b:v", "0"),
        ("-preset", "p4", "-rc", "vbr", "-cq", "18", "-b:v", "0"), False),
    "x264": VideoEncoder(
        "x264", "libx264", "yuv420p",
        ("-preset", X264_PRESET, "-crf", "20"),
        ("-preset", X264_PRESET, "-crf", "16"), True),
}
_AUTO_ORDER = ("qsv", "nvenc", "x264")
_BROKEN: set[str] = set()


def _encoder_works(ffmpeg: str, enc: VideoEncoder) -> bool:
    """Tiny real encode with the exact quality args: a driver without ICQ
    (qsv) or without NVENC fails here instead of mid-render."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
           "-f", "lavfi", "-i", "color=c=black:s=320x240:r=30",
           "-frames:v", "3", "-vf", f"format={enc.pix_fmt}",
           *enc.args(), "-f", "null", "-"]
    try:
        return _run(cmd, timeout=20).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


@lru_cache(maxsize=None)
def detect_video_encoder(ffmpeg: str,
                         preference: str = VIDEO_ENCODER) -> VideoEncoder:
    """Pick the encoder once per process: auto = qsv -> nvenc -> x264.

    CHARLA_VIDEO_ENCODER=qsv|nvenc|x264 forces one (x264 always works).
    """
    preference = (preference or "auto").lower()
    if preference not in ("auto", *_ENCODERS):
        raise FfmpegError(f"Unknown CHARLA_VIDEO_ENCODER '{preference}' "
                          "(expected auto, qsv, nvenc or x264)")
    order = _AUTO_ORDER if preference == "auto" else (preference,)
    for name in order:
        if name in _BROKEN:
            continue
        enc = _ENCODERS[name]
        if name == "x264" or _encoder_works(ffmpeg, enc):
            return enc
    if preference != "auto":
        raise FfmpegError(
            f"Video encoder '{preference}' is not usable with this ffmpeg/"
            "driver. Use CHARLA_VIDEO_ENCODER=auto (falls back to libx264).")
    return _ENCODERS["x264"]


def mark_encoder_broken(name: str) -> None:
    """Exclude an encoder for the rest of the process (e.g. QSV sessions
    failing mid-render) and forget the cached detection."""
    _BROKEN.add(name)
    detect_video_encoder.cache_clear()


def is_hw_encoder_failure(error: Exception) -> bool:
    """True when ffmpeg's stderr (not the echoed command line, which always
    names the codec) points at the hardware encoder itself."""
    stderr = str(error).split("\ncommand:", 1)[0].lower()
    return any(k in stderr for k in ("qsv", "mfx", "nvenc", "cuda",
                                     "error initializing output stream",
                                     "device creation"))
