from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Callable

from .assets import available_emotions, scan_characters, validate_clips
from .config import (AUDIO_TRIGGER_DELAY, CHARACTERS, TURN_END_DELAY,
                     PipelineOptions)
from .ffutil import probe_duration, require_ffmpeg
from .manifest import write_manifest
from .models import Timeline, Turn, VoiceSpec, build_timeline

Progress = Callable[[str], None]

# Stage dependency chain for --force-from: script -> tts -> render.
# "script" keeps 01_script/article.json so a re-script never re-scrapes.
_STAGE_INVALIDATES = {
    "script": ["01_script/script.json", "02_audio", "03_clips", "final.mp4"],
    "tts": ["02_audio", "03_clips", "final.mp4"],
    "render": ["03_clips", "final.mp4"],
}
_FORCE_ALL = ["01_script", "02_audio", "03_clips", "final.mp4"]


class PipelineResult:
    def __init__(self, output_dir: Path, manifest_path: Path,
                 final_video: Path | None, title: str,
                 turns: list[Turn], social: str = ""):
        self.output_dir = output_dir
        self.manifest_path = manifest_path
        self.final_video = final_video
        self.title = title
        self.turns = turns
        self.social = social


class ScriptDraft:
    """Stage 1 output: script + everything stages 2-4 need, so a UI can show
    the dialogue for approval (or regeneration) before paying for audio/render."""

    def __init__(self, options: PipelineOptions, output_dir: Path,
                 ffmpeg: str | None, ffprobe: str | None,
                 voices: dict[str, VoiceSpec], use_rvc: bool,
                 turns: list[Turn], script: dict, social: str):
        self.options = options
        self.output_dir = output_dir
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.voices = voices
        self.use_rvc = use_rvc
        self.turns = turns
        self.script = script
        self.social = social


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:32] or "run"


def resolve_voices(options: PipelineOptions,
                   use_rvc: bool = False) -> dict[str, VoiceSpec]:
    """One VoiceSpec per speaker.

    With RVC on, the TTS source is the character's rvc_source_voice with
    NEUTRAL pitch/rate: warped audio makes the converter produce artifacts,
    and the source is chosen so its natural f0 sits close to the real dub
    actor's (small transpose in CharacterSpec.rvc_pitch = fewer artifacts).
    Explicit --rick-voice/--rick-pitch style overrides still win.
    """
    rick, morty = CHARACTERS["rick"], CHARACTERS["morty"]
    neutral_rate, neutral_pitch = "+0%", "+0Hz"
    return {
        "rick": VoiceSpec(
            options.rick_voice or (rick.rvc_source_voice if use_rvc
                                   else rick.voice),
            options.rick_rate or (neutral_rate if use_rvc else rick.voice_rate),
            options.rick_pitch or (neutral_pitch if use_rvc else rick.voice_pitch)),
        "morty": VoiceSpec(
            options.morty_voice or (morty.rvc_source_voice if use_rvc
                                    else morty.voice),
            options.morty_rate or (neutral_rate if use_rvc else morty.voice_rate),
            options.morty_pitch or (neutral_pitch if use_rvc else morty.voice_pitch)),
    }


def default_output_dir(options: PipelineOptions, emotions: list[str],
                       voices: dict[str, VoiceSpec],
                       use_rvc: bool = False) -> Path:
    if options.script_file:
        identity = options.script_file.read_text(encoding="utf-8")
        label = options.script_file.stem
    else:
        identity = options.input_text
        label = (options.input_text.split("//", 1)[-1] if options.is_url
                 else options.input_text)
    h = hashlib.sha256()
    h.update(identity.encode("utf-8"))
    h.update("|".join(emotions).encode("utf-8"))
    for name, spec in sorted(voices.items()):
        h.update(f"|{name}:{spec.voice}:{spec.rate}:{spec.pitch}".encode())
    h.update(f"|{options.width}x{options.height}@{options.fps}"
             f"|{options.language}|{options.watermark}"
             f"|subs={options.subtitles}"
             f"|chroma={options.chroma_similarity}:{options.chroma_blend}"
             f"|charscale={options.char_scale}"
             f"|rvc={use_rvc}|tts={options.tts_engine}"
             f"|bg={Path(options.background).name}".encode())
    return Path("output") / f"{_slugify(label)}-{h.hexdigest()[:8]}"


def _estimate_duration(text: str) -> float:
    return max(1.0, len(text.split()) / 2.5)


def _apply_force(output_dir: Path, options: PipelineOptions,
                 log: Progress) -> None:
    if options.force:
        targets = _FORCE_ALL
    elif options.force_from:
        targets = _STAGE_INVALIDATES[options.force_from]
    else:
        return
    for name in targets:
        target = output_dir / name
        if target.is_dir():
            shutil.rmtree(target)
            log(f"  force: cleared {name}/")
        elif target.is_file():
            target.unlink()
            log(f"  force: cleared {name}")


def generate_script_stage(options: PipelineOptions,
                          on_progress: Progress = print) -> ScriptDraft:
    """Stage 1 only: dialogue script. Lets a UI show the turns for approval
    (or regeneration, via options.script_feedback) before spending time/money
    on voice synthesis and rendering."""
    log = on_progress

    if not options.script_file and not options.input_text.strip():
        raise ValueError("Provide an input text/URL or a --script-file")
    if options.script_file and not options.script_file.is_file():
        raise FileNotFoundError(f"Script file not found: {options.script_file}")
    background = Path(options.background)
    if not background.is_file():
        raise FileNotFoundError(f"Background video not found: {background}")

    chars = scan_characters(Path(options.characters_dir))
    emotions = available_emotions(chars)
    log(f"emotions available: {', '.join(emotions)}")

    # Resolve the voice engine up front (affects the run hash and the TTS
    # source settings). xtts/chatterbox generate cloned voices directly
    # (no RVC pass).
    use_rvc = False
    if options.tts_engine == "xtts":
        from .xtts import XttsError, xtts_available, xtts_unavailable_reason
        if not xtts_available():
            raise XttsError(xtts_unavailable_reason())
    elif options.tts_engine == "chatterbox":
        from .chatterbox import (ChatterboxError, chatterbox_available,
                                 chatterbox_unavailable_reason)
        if not chatterbox_available():
            raise ChatterboxError(chatterbox_unavailable_reason())
    else:
        from .rvc import RvcError, rvc_available, rvc_unavailable_reason
        if options.rvc == "on" and not rvc_available():
            raise RvcError(rvc_unavailable_reason())
        use_rvc = options.rvc != "off" and rvc_available()
    voices = resolve_voices(options, use_rvc)

    output_dir = Path(options.output_dir) if options.output_dir \
        else default_output_dir(options, emotions, voices, use_rvc)
    output_dir.mkdir(parents=True, exist_ok=True)
    log(f"output dir: {output_dir}")
    _apply_force(output_dir, options, log)

    ffmpeg = ffprobe = None
    if not options.dry_run:
        ffmpeg, ffprobe = require_ffmpeg()
        validate_clips(ffprobe, chars, log=log)

    # Stage 1: dialogue script — manual file, or scraped/free text -> LLM
    from .script_gen import (generate_script, load_script_file,
                             resolve_text_backend)
    if options.script_file:
        log(f"[1/4] script (manual: {options.script_file})")
        script, social = load_script_file(options.script_file, emotions)
    else:
        source_text = options.input_text
        if options.is_url:
            from .scraper import fetch_article
            log(f"[1/4] script (scraping {options.input_text})")
            source_text = fetch_article(options.input_text,
                                        output_dir / "01_script", log=log)
        if options.script_feedback.strip():
            source_text = (f"{source_text}\n\n[Instrucciones adicionales del "
                           f"usuario para este guion]: {options.script_feedback.strip()}")
        provider, text_model = resolve_text_backend(options.text_provider,
                                                    options.text_model)
        options.text_provider, options.text_model = provider, text_model
        log(f"[1/4] script ({provider}: {text_model})")
        script, social = generate_script(
            source_text, emotions, text_model, output_dir / "01_script",
            provider=provider, language=options.language,
            min_turns=options.min_turns, max_turns=options.max_turns, log=log)

    turns = [
        Turn(index=i + 1, turn_id=f"turn_{i + 1:02d}",
             speaker=t["speaker"], emotion=t["emotion"],
             line=str(t["line"]).strip(),
             character_clip=chars[t["speaker"]][t["emotion"]],
             audio_trigger_delay=AUDIO_TRIGGER_DELAY,
             turn_end_delay=TURN_END_DELAY)
        for i, t in enumerate(script["turns"])
    ]
    for turn in turns:
        log(f'  {turn.turn_id} {turn.speaker} [{turn.emotion}]: "{turn.line}"')
    if social:
        (output_dir / "social.txt").write_text(social, encoding="utf-8")

    return ScriptDraft(options, output_dir, ffmpeg, ffprobe, voices, use_rvc,
                       turns, script, social)


def continue_pipeline(draft: ScriptDraft,
                      on_progress: Progress = print) -> PipelineResult:
    """Stages 2-4 (voice, timeline, render) for an already-approved script."""
    log = on_progress
    options = draft.options
    turns = draft.turns
    ffmpeg, ffprobe = draft.ffmpeg, draft.ffprobe
    voices, use_rvc = draft.voices, draft.use_rvc
    output_dir = draft.output_dir
    background = Path(options.background)

    if options.dry_run:
        for turn in turns:
            turn.audio_duration = _estimate_duration(turn.line)
        timeline = build_timeline(turns, options.width, options.height,
                                  options.fps, bg_duration=0.0,
                                  watermark=options.watermark,
                                  subtitles=options.subtitles)
        manifest_path = write_manifest(options, timeline, draft.script["title"],
                                       output_dir, dry_run=True,
                                       voices=voices)
        log(f"[dry-run] manifest: {manifest_path}")
        return PipelineResult(output_dir, manifest_path, None,
                              draft.script["title"], turns, draft.social)

    # Stage 2: voice. Cloned-voice synthesis (xtts / chatterbox) or
    # edge-tts, optionally re-timbred with the Latin dub RVC models.
    if options.tts_engine == "xtts":
        from .xtts import synthesize_turns as synthesize_turns_xtts
        log("[2/4] xtts: voz clonada de los actores del doblaje")
        synthesize_turns_xtts(turns, options.language,
                              output_dir / "02_audio", ffprobe, log=log)
    elif options.tts_engine == "chatterbox":
        from .chatterbox import synthesize_turns as synthesize_turns_cbx
        log("[2/4] chatterbox: voz clonada de los actores del doblaje")
        synthesize_turns_cbx(turns, options.language,
                             output_dir / "02_audio", ffprobe, log=log)
    else:
        from .tts import synthesize_turns
        log(f"[2/4] tts (rick: {voices['rick'].voice}, "
            f"morty: {voices['morty'].voice})")
        synthesize_turns(turns, voices, output_dir / "02_audio", ffprobe,
                         log=log)
        if use_rvc:
            from .rvc import convert_turns
            log("[2/4] rvc: convirtiendo a voces del doblaje latino (CPU)")
            convert_turns(turns, output_dir / "02_audio", ffprobe, log=log)

    # Stage 3: timeline (frame-rounded cuts, continuous background offsets)
    bg_duration = probe_duration(ffprobe, background)
    timeline = build_timeline(turns, options.width, options.height,
                              options.fps, bg_duration=bg_duration,
                              watermark=options.watermark,
                              subtitles=options.subtitles)
    log(f"[3/4] timeline: {timeline.total_duration:.2f}s total, "
        f"{len(turns)} turns")

    # Stage 4: render (chromakey over the background + concat + ambience)
    from .renderer import render_all
    log("[4/4] render")
    final_path = render_all(ffmpeg, ffprobe, timeline, background,
                            output_dir / "03_clips",
                            output_dir / "final.mp4",
                            options.chroma_similarity, options.chroma_blend,
                            reencode=options.reencode_concat,
                            bg_volume=options.bg_volume,
                            char_scale=options.char_scale, log=log)

    manifest_path = write_manifest(options, timeline, draft.script["title"],
                                   output_dir, dry_run=False, voices=voices)
    log(f"done: {final_path}")
    return PipelineResult(output_dir, manifest_path, final_path,
                          draft.script["title"], turns, draft.social)


def run_pipeline(options: PipelineOptions,
                 on_progress: Progress = print) -> PipelineResult:
    """Full pipeline (script + voice + render) in one call: used by the CLI
    and by callers that don't need to review the script before rendering."""
    draft = generate_script_stage(options, on_progress)
    return continue_pipeline(draft, on_progress)
