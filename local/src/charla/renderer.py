from __future__ import annotations

import hashlib
import os
import textwrap
import unicodedata
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from pathlib import Path

from .config import (CACHE_DIR, CHARACTERS, RENDER_JOBS, SUBTITLE_FONT,
                     VIDEO_ENCODER)
from .ffutil import (FfmpegError, MediaInfo, VideoEncoder,
                     detect_video_encoder, is_hw_encoder_failure,
                     mark_encoder_broken, probe_media, run_ffmpeg)
from .models import Timeline, Turn

# Bump when the render command changes in a way that alters the output.
STAMP_VERSION = "v6-frames"
_AUDIO_RATE = 44100


def _drawtext_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(":", "\\:")
                .replace("'", "’").replace(",", "\\,"))


# Cross-platform fallback chain after the configured SUBTITLE_FONT:
# bundled Comic Neue (OFL) -> Windows Comic Sans/Arial -> Linux DejaVu.
_FONT_FALLBACKS = [
    Path("assets/fonts/ComicNeue-Bold.ttf"),
    Path("C:/Windows/Fonts/comicbd.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]


def _caption_font() -> tuple[str, bool]:
    """(escaped fontfile path, needs_glyph_normalization).

    Normalization only applies to the Get Schwifty display font, which
    lacks accents and punctuation.
    """
    for font in [SUBTITLE_FONT, *_FONT_FALLBACKS]:
        if font.is_file():
            schwifty = "schwifty" in font.name.lower()
            return (font.resolve().as_posix().replace(":", "\\:"), schwifty)
    raise FileNotFoundError(
        "No caption font found; set CHARLA_SUB_FONT to a valid .ttf")


def _schwifty_text(text: str) -> str:
    """Reduce text to the Get Schwifty glyph set (letters/digits/space):
    strip diacritics (á→a, ñ→n) and drop punctuation the font lacks."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed
                       if not unicodedata.combining(c))
    return "".join(c for c in stripped
                   if c.isascii() and (c.isalnum() or c in " \n"))


def _sub_style(fontcolor: str, fontfile: str) -> str:
    # Captions sit at the TOP of the frame, out of the characters' way.
    # No text_align: it only exists in ffmpeg >= 6.1 (Colab ships older).
    # expansion=none: print the text literally — with the default
    # expansion a line like "el 99.8%?" aborts the render ("Stray %").
    return (
        "expansion=none:"
        f"fontfile='{fontfile}':"
        f"fontsize=h/30:fontcolor={fontcolor}:"
        "borderw=4:bordercolor=black@0.8:"
        "box=1:boxcolor=black@0.3:boxborderw=16:"
        "line_spacing=8:"
        "x=(w-text_w)/2:y=h*0.05"
    )


_CHUNK_MAX_CHARS = 24


def _chunk_words(words: list[dict]) -> list[tuple[str, float, float]]:
    """Group word timings into short caption chunks: (text, start, end)."""
    chunks: list[tuple[str, float, float]] = []
    current: list[dict] = []
    length = 0
    for word in words:
        current.append(word)
        length += len(word["w"]) + 1
        if length >= _CHUNK_MAX_CHARS:
            text = " ".join(w["w"] for w in current)
            chunks.append((text, current[0]["t"],
                           current[-1]["t"] + current[-1]["d"]))
            current, length = [], 0
    if current:
        text = " ".join(w["w"] for w in current)
        chunks.append((text, current[0]["t"],
                       current[-1]["t"] + current[-1]["d"]))
    return chunks


def _sub_textfile(clips_dir: Path, name: str, content: str) -> str:
    f = clips_dir / name
    f.write_text(content, encoding="utf-8", newline="\n")
    return f.resolve().as_posix().replace(":", "\\:")


def _subtitle_filters(turn: Turn, clips_dir: Path, duration: float,
                      trigger_delay: float, style: str,
                      schwifty: bool) -> str:
    """Progressive captions: each chunk appears as it is spoken.

    Falls back to the full (wrapped) text when word timings are unavailable.
    """
    display = _schwifty_text if schwifty else (lambda t: t)
    if turn.word_timings:
        filters = []
        # Casing as written by the scriptwriter: the line already starts
        # capitalized and keeps proper nouns (Rick, Morty, siglas) intact.
        chunks = _chunk_words(turn.word_timings)
        for i, (text, start, end) in enumerate(chunks):
            if i == 0 and text:
                text = text[0].upper() + text[1:]
            text = display(text)
            path = _sub_textfile(
                clips_dir, f"{turn.turn_id}.sub{i:02d}.txt",
                "\n".join(textwrap.wrap(text, width=_CHUNK_MAX_CHARS + 4)))
            show = max(0.0, start + trigger_delay - 0.05)
            # keep each caption up until the next one takes over
            if i + 1 < len(chunks):
                hide = chunks[i + 1][1] + trigger_delay - 0.05
            else:
                hide = min(duration - 0.15, end + trigger_delay + 0.4)
            filters.append(
                f"drawtext=textfile='{path}':{style}:"
                f"enable='between(t,{show:.3f},{hide:.3f})',")
        return "".join(filters)

    text = turn.line.strip()
    text = text[0].upper() + text[1:] if text else text
    text = display(text)
    wrapped = "\n".join(textwrap.wrap(text, width=28))
    path = _sub_textfile(clips_dir, f"{turn.turn_id}.sub.txt", wrapped)
    end = max(0.5, duration - 0.15)
    return (f"drawtext=textfile='{path}':{style}:"
            f"enable='between(t,0.15,{end:.3f})',")


def _watermark_filter(text: str, fontfile: str) -> str:
    """Bottom-left overlay, sized relative to the frame."""
    return (
        f"drawtext=text='{_drawtext_escape(text)}':expansion=none:"
        f"fontfile='{fontfile}':"
        "fontsize=h/42:fontcolor=white@0.85:"
        "borderw=2:bordercolor=black@0.55:"
        "x=w*0.035:y=h-text_h-h*0.03,"
    )


def ensure_pingpong(ffmpeg: str, clip: Path, n_frames: int, cache_dir: Path,
                    log=print) -> Path:
    """Palindrome (forward + mirrored) version of a character clip, cached
    across runs. The mirrored half drops its first and last frame (the
    turnaround frame and frame 0), so looping it with -stream_loop shows
    every frame once per pass — 0..n-1, n-2..1, 0.. — with no frozen frame
    at either end."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{clip.stem}_pingpong.mp4"
    meta_file = out.with_suffix(".meta")
    n_frames = max(3, n_frames)
    stamp = f"pp-v2|{clip.stat().st_mtime_ns}|{n_frames}"
    if (out.exists() and out.stat().st_size > 0 and meta_file.exists()
            and meta_file.read_text(encoding="utf-8") == stamp):
        return out
    tmp = out.with_suffix(".tmp.mp4")
    # Always libx264 at high quality: cached forever and keyed again later.
    run_ffmpeg(ffmpeg, [
        "-y", "-i", str(clip),
        "-filter_complex",
        "[0:v]split[a][b];"
        f"[b]reverse,trim=start_frame=1:end_frame={n_frames - 1},"
        "setpts=PTS-STARTPTS[r];"
        "[a][r]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        "-pix_fmt", "yuv420p",
        str(tmp),
    ])
    tmp.replace(out)
    meta_file.write_text(stamp, encoding="utf-8")
    log(f"  pingpong: {out.name}")
    return out


def ensure_background_proxy(ffmpeg: str, background: Path, width: int,
                            height: int, fps: int, encoder: VideoEncoder,
                            cache_dir: Path | None = None,
                            log=print) -> Path:
    """One-time transcode of the background to the exact output size/fps
    with a keyframe every second, cached across runs.

    Every turn then decodes a light 720p stream (instead of e.g. 1080p
    HEVC), seeks within one second, and skips the per-frame scale. Video
    only: the ambience mix keeps reading the original file.
    """
    cache_dir = cache_dir or CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    st = background.stat()
    key = hashlib.sha256(
        f"bgproxy-v1|{background.resolve().as_posix()}|{st.st_mtime_ns}"
        f"|{st.st_size}|{width}x{height}@{fps}".encode("utf-8")
    ).hexdigest()[:10]
    out = cache_dir / f"bg_{background.stem}_{width}x{height}_{fps}_{key}.mp4"
    if out.exists() and out.stat().st_size > 0:
        log(f"  background: proxy {width}x{height}@{fps} (cached)")
        return out
    for stale in cache_dir.glob(f"bg_{background.stem}_*.mp4"):
        if stale != out:
            stale.unlink(missing_ok=True)
    tmp = out.with_suffix(".tmp.mp4")

    def build(enc: VideoEncoder) -> None:
        run_ffmpeg(ffmpeg, [
            "-y", "-i", str(background),
            "-map", "0:v:0", "-an", "-sn", "-dn",
            "-vf", (f"scale={width}:{height}:flags=bicubic,fps={fps},"
                    f"setsar=1,format={enc.pix_fmt}"),
            *enc.args(proxy=True, gop=fps),
            str(tmp),
        ])

    try:
        build(encoder)
    except FfmpegError:
        if encoder.name == "x264":
            raise
        build(detect_video_encoder(ffmpeg, "x264"))
    tmp.replace(out)
    log(f"  background: proxy {width}x{height}@{fps} creado "
        "(una sola vez por fondo)")
    return out


def plan_character(turn: Turn, char_duration: float) -> None:
    """Short turns play the TAIL of the emotion loop (start offset so it
    ends with the clip) — every turn starts at a different point, so cuts
    don't look identical. Turns longer than the loop use the ping-pong
    version instead of a hard wrap to frame 0."""
    d = turn.turn_duration
    if d <= char_duration:
        turn.char_offset = round(char_duration - d, 3)
        turn.char_pingpong = False
    else:
        turn.char_offset = 0.0
        turn.char_pingpong = True


def render_turn_clip(ffmpeg: str, timeline: Timeline, turn: Turn,
                     bg_video: Path, clips_dir: Path,
                     chroma_similarity: float, chroma_blend: float,
                     encoder: VideoEncoder, pingpong: Path | None = None,
                     scaled_bg: bool = False, threads: int = 0,
                     char_scale: float = 0.72, log=print) -> Path:
    """One dialogue turn: the speaker in their corner, chroma-keyed over the
    background video (which seeks to bg_offset for cross-cut continuity),
    with the TTS line as the only audio.

    Exactly `turn.frames` video frames and the matching number of audio
    samples, so a stream-copy concat never drifts. `scaled_bg` means the
    background is already a proxy at the output size/fps.
    """
    out = clips_dir / f"{turn.turn_id}.mp4"
    meta_file = clips_dir / f"{turn.turn_id}.meta"
    character = CHARACTERS[turn.speaker]
    fontfile, schwifty = _caption_font()
    pingpong_stamp = (pingpong.with_suffix(".meta").read_text(encoding="utf-8")
                      if pingpong else "")
    stamp = "|".join(str(x) for x in (
        STAMP_VERSION,
        turn.speaker, turn.emotion, turn.line, turn.frames,
        turn.bg_offset, turn.char_offset, turn.char_pingpong,
        char_scale, character.anchor, fontfile, schwifty,
        timeline.watermark, timeline.subtitles,
        timeline.width, timeline.height, timeline.fps,
        character.chroma_color, chroma_similarity, chroma_blend,
        len(turn.word_timings or []),
        turn.character_clip.stat().st_mtime_ns,
        bg_video.name, bg_video.stat().st_mtime_ns,
        turn.audio_path.name, turn.audio_path.stat().st_mtime_ns,
        encoder.signature, pingpong_stamp))
    if (out.exists() and out.stat().st_size > 0 and meta_file.exists()
            and meta_file.read_text(encoding="utf-8") == stamp):
        log(f"  clip: {out.name} (cached)")
        turn.clip_path = out
        return out

    w, h, fps = timeline.width, timeline.height, timeline.fps
    delay_ms = round(turn.audio_trigger_delay * 1000)
    samples = round(turn.frames * _AUDIO_RATE / fps)
    thr = ["-threads", str(threads)] if threads else []

    if turn.char_pingpong:
        char_inputs = [*thr, "-stream_loop", "-1", "-i", str(pingpong)]
    else:
        char_inputs = [*thr, "-ss", f"{turn.char_offset:.3f}",
                       "-i", str(turn.character_clip)]

    subtitle = ""
    if timeline.subtitles and turn.line:
        subtitle = _subtitle_filters(
            turn, clips_dir, turn.turn_duration, turn.audio_trigger_delay,
            _sub_style(character.sub_color, fontfile), schwifty)
    watermark = (_watermark_filter(timeline.watermark, fontfile)
                 if timeline.watermark else "")

    # The speaker sits in their own bottom corner (rick right, morty left)
    # at char_scale of the frame height, leaving the top clear for captions.
    char_h = round(h * char_scale / 2) * 2
    overlay_xy = "W-w:H-h" if character.anchor == "right" else "0:H-h"

    # Key at the clip's native resolution (keeps edges tight), then scale.
    # colorkey (RGB), not chromakey (UV): the Veo green is desaturated and
    # in UV space any usable similarity also keys whites and skin.
    # setpts=PTS-STARTPTS on BOTH inputs: a seek rarely lands exactly on a
    # frame boundary, so the first frame arrives with a small positive pts —
    # on the character that showed one background-only frame at t=0, on the
    # background it made ffmpeg emit one extra frame.
    # The graph ends in the encoder's pixel format (h264_qsv needs nv12).
    # Audio is padded/trimmed to exactly frames/fps worth of samples.
    bg_chain = ("setpts=PTS-STARTPTS,setsar=1" if scaled_bg else
                f"setpts=PTS-STARTPTS,scale={w}:{h},fps={fps},setsar=1")
    filter_complex = (
        f"[0:v]{bg_chain}[bg];"
        f"[1:v]setpts=PTS-STARTPTS,"
        f"colorkey={character.chroma_color}:{chroma_similarity:.2f}:"
        f"{chroma_blend:.2f},despill=type=green,"
        f"scale=-2:{char_h},fps={fps},setsar=1[fg];"
        f"[bg][fg]overlay={overlay_xy}:format=auto,"
        f"{subtitle}"
        f"{watermark}"
        f"format={encoder.pix_fmt}[v];"
        f"[2:a]aresample={_AUDIO_RATE},adelay={delay_ms}|{delay_ms},"
        f"apad=whole_len={samples},atrim=end_sample={samples},"
        f"asetpts=N/SR/TB[a]"
    )
    tmp = out.with_suffix(".tmp.mp4")
    run_ffmpeg(ffmpeg, [
        "-y",
        *(["-filter_complex_threads", str(threads)] if threads else []),
        *thr, "-stream_loop", "-1", "-ss", f"{turn.bg_offset:.6f}",
        "-i", str(bg_video),
        *char_inputs,
        "-i", str(turn.audio_path),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-frames:v", str(turn.frames), "-r", str(fps),
        *encoder.args(threads=threads or None),
        "-c:a", "aac", "-b:a", "192k", "-ar", str(_AUDIO_RATE), "-ac", "2",
        str(tmp),
    ])
    tmp.replace(out)
    meta_file.write_text(stamp, encoding="utf-8")
    turn.clip_path = out
    log(f"  clip: {out.name} ({turn.speaker}/{turn.emotion})")
    return out


def concat_clips(ffmpeg: str, timeline: Timeline, clips_dir: Path,
                 final_path: Path, reencode: bool = False, log=print,
                 encoder: VideoEncoder | None = None,
                 faststart: bool = True) -> Path:
    concat_file = clips_dir / "concat.txt"
    lines = [f"file '{t.clip_path.resolve().as_posix()}'" for t in timeline.turns]
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if reencode:
        enc = encoder or detect_video_encoder(ffmpeg)
        codec_args = ["-vf", f"format={enc.pix_fmt}", *enc.args(),
                      "-c:a", "aac", "-b:a", "192k"]
    else:
        codec_args = ["-c", "copy"]
    tmp = final_path.with_suffix(".tmp.mp4")
    run_ffmpeg(ffmpeg, [
        "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        *codec_args,
        # only the deliverable needs the moov atom up front
        *(["-movflags", "+faststart"] if faststart else []),
        str(tmp),
    ])
    tmp.replace(final_path)
    log(f"  final: {final_path.name}")
    return final_path


def mix_background_audio(ffmpeg: str, video_in: Path, background: Path,
                         volume: float, duration: float, out: Path,
                         log=print) -> Path:
    """Mix the background video's own soundtrack under the dialogue.

    The video stream is copied untouched; only audio is re-encoded. The bed
    fades in at the start, out over the last two seconds, and loops if the
    conversation outlasts it.
    """
    fade_out = max(0.0, duration - 2.0)
    tmp = out.with_suffix(".mix.mp4")
    run_ffmpeg(ffmpeg, [
        "-y", "-i", str(video_in),
        "-stream_loop", "-1", "-i", str(background),
        "-filter_complex",
        (f"[1:a]atrim=duration={duration:.3f},"
         "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100,"
         f"volume={volume:.3f},"
         f"afade=t=in:d=1.2,afade=t=out:st={fade_out:.3f}:d=2[bg];"
         "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0:"
         "normalize=0[a]"),
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(tmp),
    ])
    tmp.replace(out)
    log(f"  audio: ambiente del fondo mezclado (volumen {volume:.2f})")
    return out


def _render_turns(ffmpeg: str, timeline: Timeline, bg_video: Path,
                  clips_dir: Path, chroma_similarity: float,
                  chroma_blend: float, encoder: VideoEncoder,
                  pingpongs: dict[Path, Path], scaled_bg: bool, jobs: int,
                  char_scale: float, log) -> None:
    """Render every turn clip, `jobs` ffmpeg processes at a time. Each
    worker only writes its own turn_XX.* files; `log` must be thread-safe
    (print, or the UI's queue.put)."""
    turns = timeline.turns
    jobs = max(1, min(jobs, len(turns)))
    threads = max(1, (os.cpu_count() or 2) // jobs) if jobs > 1 else 0

    def one(turn: Turn) -> Path:
        return render_turn_clip(
            ffmpeg, timeline, turn, bg_video, clips_dir,
            chroma_similarity, chroma_blend, encoder,
            pingpong=pingpongs.get(turn.character_clip) if turn.char_pingpong
            else None,
            scaled_bg=scaled_bg, threads=threads,
            char_scale=char_scale, log=log)

    if jobs == 1:
        for turn in turns:
            one(turn)
        return
    pool = ThreadPoolExecutor(max_workers=jobs)
    try:
        futures = [pool.submit(one, turn) for turn in turns]
        wait(futures, return_when=FIRST_EXCEPTION)
    finally:
        # running renders finish; queued ones are dropped after a failure
        pool.shutdown(wait=True, cancel_futures=True)
    for future in futures:            # first failure in turn order
        if not future.cancelled() and future.exception() is not None:
            raise future.exception()


def render_all(ffmpeg: str, ffprobe: str, timeline: Timeline,
               background: Path, clips_dir: Path, final_path: Path,
               chroma_similarity: float, chroma_blend: float,
               reencode: bool = False, bg_volume: float = 0.0,
               char_scale: float = 0.72, log=print,
               encoder: VideoEncoder | None = None, jobs: int | None = None,
               bg_video: Path | None = None,
               clip_info: dict[Path, MediaInfo] | None = None) -> Path:
    """Render all turns (in parallel) and join them into final_path.

    `background` is the original file (ambience source); `bg_video` an
    optional pre-scaled proxy of it used for the picture.
    """
    clips_dir.mkdir(parents=True, exist_ok=True)
    encoder = encoder or detect_video_encoder(ffmpeg)
    jobs = max(1, jobs or RENDER_JOBS)
    bg_video = bg_video or background
    scaled_bg = Path(bg_video) != Path(background)

    clip_info = dict(clip_info or {})
    for clip in {t.character_clip for t in timeline.turns}:
        if clip not in clip_info:
            clip_info[clip] = probe_media(ffprobe, clip)
    for turn in timeline.turns:
        plan_character(turn, clip_info[turn.character_clip].duration)

    # Ping-pong loops first, one per clip: parallel workers must never race
    # on the shared cache file.
    pingpongs = {
        clip: ensure_pingpong(ffmpeg, clip, clip_info[clip].frames,
                              CACHE_DIR, log=log)
        for clip in dict.fromkeys(t.character_clip for t in timeline.turns
                                  if t.char_pingpong)}

    log(f"  render: {len(timeline.turns)} turnos, "
        f"{min(jobs, len(timeline.turns))} en paralelo ({encoder.codec})")
    try:
        _render_turns(ffmpeg, timeline, bg_video, clips_dir,
                      chroma_similarity, chroma_blend, encoder, pingpongs,
                      scaled_bg, jobs, char_scale, log)
    except FfmpegError as e:
        if (encoder.name == "x264" or VIDEO_ENCODER != "auto"
                or not is_hw_encoder_failure(e)):
            raise
        # Whole-run fallback: the stamp carries the encoder signature, so
        # every clip is re-encoded and the copy-concat stays homogeneous.
        log(f"  aviso: {encoder.codec} falló; se re-renderiza con libx264")
        mark_encoder_broken(encoder.name)
        encoder = detect_video_encoder(ffmpeg)
        _render_turns(ffmpeg, timeline, bg_video, clips_dir,
                      chroma_similarity, chroma_blend, encoder, pingpongs,
                      scaled_bg, jobs, char_scale, log)

    if bg_volume > 0:
        if probe_media(ffprobe, background).has_audio:
            premix = clips_dir / "final_premix.mp4"
            concat_clips(ffmpeg, timeline, clips_dir, premix,
                         reencode=reencode, log=lambda *_: None,
                         encoder=encoder, faststart=False)
            return mix_background_audio(ffmpeg, premix, background,
                                        bg_volume, timeline.total_duration,
                                        final_path, log=log)
        log("  aviso: el fondo no tiene pista de audio; se omite el ambiente")
    return concat_clips(ffmpeg, timeline, clips_dir, final_path,
                        reencode=reencode, log=log, encoder=encoder)
