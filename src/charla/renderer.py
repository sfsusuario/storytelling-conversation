from __future__ import annotations

import textwrap
import unicodedata
from pathlib import Path

from .config import CHARACTERS, SUBTITLE_FONT
from .ffutil import probe_duration, run_ffmpeg
from .models import Timeline, Turn


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
    return (
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
        f"drawtext=text='{_drawtext_escape(text)}':"
        f"fontfile='{fontfile}':"
        "fontsize=h/42:fontcolor=white@0.85:"
        "borderw=2:bordercolor=black@0.55:"
        "x=w*0.035:y=h-text_h-h*0.03,"
    )


def ensure_pingpong(ffmpeg: str, clip: Path, cache_dir: Path,
                    log=print) -> Path:
    """Palindrome (forward + mirrored) version of a character clip, cached
    across runs. Looping it with -stream_loop is seamless by construction:
    the mirrored half ends on the exact frame the forward half starts on."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{clip.stem}_pingpong.mp4"
    meta_file = out.with_suffix(".meta")
    stamp = str(clip.stat().st_mtime_ns)
    if (out.exists() and out.stat().st_size > 0 and meta_file.exists()
            and meta_file.read_text(encoding="utf-8") == stamp):
        return out
    tmp = out.with_suffix(".tmp.mp4")
    run_ffmpeg(ffmpeg, [
        "-y", "-i", str(clip),
        "-filter_complex",
        "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1[v]",
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(tmp),
    ])
    tmp.replace(out)
    meta_file.write_text(stamp, encoding="utf-8")
    log(f"  pingpong: {out.name}")
    return out


def render_turn_clip(ffmpeg: str, timeline: Timeline, turn: Turn,
                     background: Path, clips_dir: Path,
                     chroma_similarity: float, chroma_blend: float,
                     char_duration: float, cache_dir: Path,
                     char_scale: float = 0.72, log=print) -> Path:
    """One dialogue turn: the speaker full-frame, chroma-keyed over the
    background video (which seeks to bg_offset for cross-cut continuity),
    with the TTS line as the only audio.

    Short turns play the TAIL of the emotion loop (start offset so it ends
    with the clip) — every turn starts at a different point, so cuts don't
    look identical. Turns longer than the loop use a seamless forward+mirror
    (ping-pong) version instead of a hard wrap to frame 0."""
    d = turn.turn_duration
    if d <= char_duration:
        turn.char_offset = round(char_duration - d, 3)
        turn.char_pingpong = False
    else:
        turn.char_offset = 0.0
        turn.char_pingpong = True

    out = clips_dir / f"{turn.turn_id}.mp4"
    meta_file = clips_dir / f"{turn.turn_id}.meta"
    character = CHARACTERS[turn.speaker]
    fontfile, schwifty = _caption_font()
    stamp = "|".join(str(x) for x in (
        "v5-portable",
        turn.speaker, turn.emotion, turn.line, turn.turn_duration,
        turn.bg_offset, turn.char_offset, turn.char_pingpong,
        char_scale, character.anchor, fontfile, schwifty,
        timeline.watermark, timeline.subtitles,
        timeline.width, timeline.height, timeline.fps,
        character.chroma_color, chroma_similarity, chroma_blend,
        len(turn.word_timings or []),
        turn.character_clip.stat().st_mtime_ns,
        background.stat().st_mtime_ns,
        turn.audio_path.stat().st_mtime_ns))
    if (out.exists() and out.stat().st_size > 0 and meta_file.exists()
            and meta_file.read_text(encoding="utf-8") == stamp):
        log(f"  clip: {out.name} (cached)")
        turn.clip_path = out
        return out

    w, h, fps = timeline.width, timeline.height, timeline.fps
    delay_ms = round(turn.audio_trigger_delay * 1000)

    if turn.char_pingpong:
        pingpong = ensure_pingpong(ffmpeg, turn.character_clip, cache_dir,
                                   log=log)
        char_inputs = ["-stream_loop", "-1", "-i", str(pingpong)]
    else:
        char_inputs = ["-ss", f"{turn.char_offset:.3f}",
                       "-i", str(turn.character_clip)]

    subtitle = ""
    if timeline.subtitles and turn.line:
        subtitle = _subtitle_filters(
            turn, clips_dir, d, turn.audio_trigger_delay,
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
    # setpts=PTS-STARTPTS: the character seek rarely lands on a 24fps frame
    # boundary, so its first frame arrives with a small positive pts and the
    # overlay would show one background-only frame at t=0.
    filter_complex = (
        f"[0:v]scale={w}:{h},fps={fps},setsar=1[bg];"
        f"[1:v]setpts=PTS-STARTPTS,"
        f"colorkey={character.chroma_color}:{chroma_similarity:.2f}:"
        f"{chroma_blend:.2f},despill=type=green,"
        f"scale=-2:{char_h},fps={fps},setsar=1[fg];"
        f"[bg][fg]overlay={overlay_xy}:format=auto,"
        f"{subtitle}"
        f"{watermark}"
        f"format=yuv420p[v];"
        f"[2:a]adelay={delay_ms}|{delay_ms},apad[a]"
    )
    tmp = out.with_suffix(".tmp.mp4")
    run_ffmpeg(ffmpeg, [
        "-y",
        "-stream_loop", "-1", "-ss", f"{turn.bg_offset:.3f}",
        "-i", str(background),
        *char_inputs,
        "-i", str(turn.audio_path),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-t", f"{d:.6f}", "-r", str(fps),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        str(tmp),
    ])
    tmp.replace(out)
    meta_file.write_text(stamp, encoding="utf-8")
    turn.clip_path = out
    log(f"  clip: {out.name} ({turn.speaker}/{turn.emotion})")
    return out


def concat_clips(ffmpeg: str, timeline: Timeline, clips_dir: Path,
                 final_path: Path, reencode: bool = False, log=print) -> Path:
    concat_file = clips_dir / "concat.txt"
    lines = [f"file '{t.clip_path.resolve().as_posix()}'" for t in timeline.turns]
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    codec_args = (["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "192k"]
                  if reencode else ["-c", "copy"])
    tmp = final_path.with_suffix(".tmp.mp4")
    run_ffmpeg(ffmpeg, [
        "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        *codec_args, "-movflags", "+faststart", str(tmp),
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


def render_all(ffmpeg: str, ffprobe: str, timeline: Timeline,
               background: Path, clips_dir: Path, final_path: Path,
               chroma_similarity: float, chroma_blend: float,
               reencode: bool = False, bg_volume: float = 0.0,
               char_scale: float = 0.72, log=print) -> Path:
    clips_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path("output") / "_cache"
    char_durations = {
        clip: probe_duration(ffprobe, clip)
        for clip in {t.character_clip for t in timeline.turns}
    }
    for turn in timeline.turns:
        render_turn_clip(ffmpeg, timeline, turn, background, clips_dir,
                         chroma_similarity, chroma_blend,
                         char_durations[turn.character_clip], cache_dir,
                         char_scale=char_scale, log=log)
    if bg_volume > 0:
        premix = clips_dir / "final_premix.mp4"
        concat_clips(ffmpeg, timeline, clips_dir, premix,
                     reencode=reencode, log=lambda *_: None)
        return mix_background_audio(ffmpeg, premix, background, bg_volume,
                                    timeline.total_duration, final_path,
                                    log=log)
    return concat_clips(ffmpeg, timeline, clips_dir, final_path,
                        reencode=reencode, log=log)
