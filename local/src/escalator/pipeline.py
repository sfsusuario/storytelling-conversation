from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from . import config
from .config import LEVEL_WORDS, OUTPUT_ROOT, PipelineOptions, resolve_personas
from .ffutil import require_ffmpeg
from .models import Persona, Scene
from .timeline import build_timeline
from .manifest import write_manifest

Progress = Callable[[str], None]
# Structured progress for UIs: {"type": "stage"|"scenes"|"scene"|"done", ...}
EventSink = Callable[[dict], None]
STAGES = ["text", "images", "tts", "timeline", "motion", "render"]


class PipelineCancelled(RuntimeError):
    pass

# Stage dependency chain for --force-from: text -> {images, tts} -> render.
# final.mp4 is kept: the render always rewrites it atomically, so a cancelled
# or failed regeneration leaves the previous video in place.
_STAGE_INVALIDATES = {
    "text": ["01_text", "02_images", "03_audio", "05_motion", "04_clips"],
    "images": ["02_images", "05_motion", "04_clips"],
    "tts": ["03_audio", "05_motion", "04_clips"],
    "motion": ["05_motion", "04_clips"],
    "render": ["04_clips"],
}


class PipelineResult:
    def __init__(self, output_dir: Path, manifest_path: Path,
                 final_video: Path | None, style_set: str,
                 personas: list[Persona], social: str = ""):
        self.output_dir = output_dir
        self.manifest_path = manifest_path
        self.final_video = final_video
        self.style_set = style_set
        self.personas = personas
        self.social = social


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:32] or "run"


def default_output_dir(options: PipelineOptions, personas: list[Persona]) -> Path:
    h = hashlib.sha256()
    h.update(options.phrase.encode("utf-8"))
    h.update("|".join(p.name for p in personas).encode("utf-8"))
    h.update(f"{options.width}x{options.height}@{options.fps}|{options.voice}"
             f"|{options.voice_rate}|{options.voice_pitch}|{options.language}"
             f"|{options.fit}|{options.watermark}|subs={options.subtitles}".encode())
    if options.test_mode:
        h.update(b"|test-mode")
    h.update(Path(options.base_image).read_bytes())
    return OUTPUT_ROOT / f"{_slugify(options.phrase)}-{h.hexdigest()[:8]}"


def scene_variants(path: Path, reroll: list[str]) -> dict[str, int]:
    """Per-scene variation counters kept in the output folder. A reroll bumps
    a scene's counter (new seed, so a different result), and later runs keep
    the chosen variation instead of reverting to the first one."""
    variants = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if reroll:
        for scene_id in reroll:
            variants[scene_id] = variants.get(scene_id, 0) + 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(variants), encoding="utf-8")
    return variants


def _estimate_duration(text: str) -> float:
    return max(1.0, len(text.split()) / 2.5)


def _apply_force(output_dir: Path, options: PipelineOptions, log: Progress) -> None:
    if options.force:
        targets = _STAGE_INVALIDATES["text"]
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


def run_pipeline(options: PipelineOptions,
                 on_progress: Progress = print,
                 on_event: EventSink | None = None,
                 cancel: threading.Event | None = None) -> PipelineResult:
    log = on_progress

    def emit(event_type: str, **data) -> None:
        if on_event:
            on_event({"type": event_type, **data})

    def check() -> None:
        if cancel is not None and cancel.is_set():
            raise PipelineCancelled("cancelled")

    def stage(name: str, detail: str = "") -> None:
        check()
        index = STAGES.index(name) + 1
        log(f"[{index}/{len(STAGES)}] {name}" + (f" ({detail})" if detail else ""))
        emit("stage", index=index, total=len(STAGES), name=name, detail=detail)

    def scene_event(kind: str):
        def handler(scene, cached: bool = False) -> None:
            path = {"image": scene.image_path, "audio": scene.audio_path,
                    "clip": scene.clip_path, "motion": scene.motion_path}[kind]
            emit("scene", scene_id=scene.scene_id, kind=kind, cached=cached,
                 path=str(path) if path else None)
            check()
        return handler

    last_step: dict = {}

    def step_event(stage_name: str):
        """Fine-grained progress inside a slow scene: diffusion steps, frames,
        model loading (scene None). Throttled; the last step always goes out."""
        def handler(scene, step: int, total: int, label: str) -> None:
            key = (stage_name, scene.scene_id if scene else None)
            now = time.monotonic()
            if step < total and now - last_step.get(key, 0.0) < 0.3:
                return
            last_step[key] = now
            emit("progress", stage=stage_name, scene_id=key[1], step=step,
                 total=total, label=label)
            check()
        return handler

    base_image = Path(options.base_image)
    if not base_image.is_file():
        raise FileNotFoundError(f"Base image not found: {base_image}")
    if not options.phrase.strip():
        raise ValueError("Phrase must not be empty")

    style_set, personas = resolve_personas(options)
    log(f"style set: {style_set} -> " + " / ".join(p.name for p in personas))

    scenes = [
        Scene(index=i + 1, scene_id=f"scene_{i + 1:02d}", persona=p,
              visual_style_prompt=config.build_image_prompt(p),
              audio_trigger_delay=config.AUDIO_TRIGGER_DELAY,
              scene_end_delay=config.SCENE_END_DELAY)
        for i, p in enumerate(personas)
    ]

    output_dir = Path(options.output_dir) if options.output_dir \
        else default_output_dir(options, personas)
    output_dir.mkdir(parents=True, exist_ok=True)
    log(f"output dir: {output_dir}")
    emit("scenes", style_set=style_set, output_dir=str(output_dir),
         scenes=[{"scene_id": s.scene_id, "level": s.persona.level,
                  "persona": s.persona.name} for s in scenes])
    _apply_force(output_dir, options, log)

    ffmpeg = ffprobe = None
    if not options.dry_run:
        ffmpeg, ffprobe = require_ffmpeg()

    # "Regenerate from X" keeps every earlier stage exactly as it is on disk,
    # even when its cache stamp is outdated (e.g. a prompt improved since).
    def kept(name: str) -> bool:
        return bool(options.force_from) and STAGES.index(name) < STAGES.index(options.force_from)

    # Stage 1: text rewrites (Ollama, Claude or Gemini)
    from .text_gen import generate_rewrites, resolve_text_backend
    provider, text_model = resolve_text_backend(options.text_provider,
                                                options.text_model)
    options.text_provider, options.text_model = provider, text_model
    stage("text", f"{provider}: {text_model}")
    rewrites, social = generate_rewrites(options.phrase, personas, text_model,
                                         output_dir / "01_text",
                                         provider=provider,
                                         language=options.language,
                                         seed=options.seed, keep=kept("text"))
    for scene, rewrite in zip(scenes, rewrites):
        scene.speech_script = rewrite
        log(f'  L{scene.persona.level} {scene.persona.name}: "{rewrite}"')
        emit("scene", scene_id=scene.scene_id, kind="text", text=rewrite)

    # Resolve the background music. Default is the locally synthesized
    # ambience: unique audio that copyright detectors (TikTok/YouTube) can
    # never flag. "track" uses CC-BY tracks instead — legal with the credit
    # that then rides along in the social text, but automated detection may
    # still block them on some platforms.
    music_source = None
    music_desc = "none"
    # Background music removed from the studio: only the narration is heard
    # (also on regenerate, whose old manifests may still carry a volume).
    options.music_volume = 0.0
    if options.music_volume > 0 and not options.dry_run:
        if options.music_source == "track":
            from .music import attribution as music_attribution, music_file
            music_source = music_file(style_set, log=log)
            if music_source is not None:
                music_desc = music_attribution(style_set)
                social = f"{social}\n\n{music_desc}" if social else music_desc
        if music_source is None:
            music_source = config.background_graph(style_set)
            music_desc = "synthesized ambience (ffmpeg, copyright-free)"
    if social:
        (output_dir / "social.txt").write_text(social, encoding="utf-8")

    if options.dry_run:
        for scene in scenes:
            scene.audio_duration = _estimate_duration(scene.speech_script)
        timeline = build_timeline(scenes, options.width, options.height,
                                  options.fps, options.fit, options.watermark,
                                  options.subtitles,
                                  LEVEL_WORDS.get(options.language, "NIVEL"))
        manifest_path = write_manifest(options, timeline, style_set, output_dir,
                                       dry_run=True)
        log(f"[dry-run] manifest: {manifest_path}")
        return PipelineResult(output_dir, manifest_path, None, style_set,
                              personas, social)

    # Stage 2: styled images (local or Gemini) — or placeholders in test mode
    if options.test_mode:
        from .image_gen import generate_test_images
        stage("images", "test mode: reusing portrait")
        generate_test_images(scenes, base_image, output_dir / "02_images",
                             ffmpeg, log=log)
        for scene in scenes:
            scene_event("image")(scene, True)
    else:
        from .image_gen import generate_scene_images, resolve_image_provider
        options.image_provider = resolve_image_provider(options.image_provider)
        stage("images", options.image_model if options.image_provider == "gemini"
              else options.image_provider)
        generate_scene_images(scenes, base_image, options.image_model,
                              output_dir / "02_images", ffmpeg=ffmpeg,
                              provider=options.image_provider,
                              seed=options.seed, log=log,
                              on_image=scene_event("image"),
                              on_step=step_event("images"),
                              variants=scene_variants(output_dir / "02_images" / "variants.json",
                                                      options.reroll_images),
                              keep=kept("images"))

    # Stage 3: TTS + durations
    from .tts import resolve_voice, synthesize_scenes
    options.voice = resolve_voice(options.tts_provider, options.voice)
    stage("tts", f"{options.tts_provider}: {options.voice}")
    synthesize_scenes(scenes, options.voice, output_dir / "03_audio",
                      ffprobe, rate=options.voice_rate,
                      pitch=options.voice_pitch,
                      provider=options.tts_provider,
                      language=options.language, log=log,
                      on_scene=scene_event("audio"), keep=kept("tts"))

    # Stage 4: timeline
    timeline = build_timeline(scenes, options.width, options.height,
                              options.fps, options.fit, options.watermark,
                              options.subtitles,
                              LEVEL_WORDS.get(options.language, "NIVEL"))
    stage("timeline", f"{timeline.total_duration:.2f}s total")

    # Stage 5: optional motion for each still (3D rotation / LivePortrait)
    from .motion import generate_motion
    stage("motion", options.motion if options.motion != "none" else "off")
    generate_motion(options.motion, scenes, output_dir / "05_motion",
                    options.fps, ffmpeg, seed=options.seed, log=log,
                    on_scene=scene_event("motion"), on_step=step_event("motion"),
                    variants=scene_variants(output_dir / "05_motion" / "variants.json",
                                            options.reroll_motion),
                    keep=kept("motion"))

    # Stage 6: render (with ambient background bed per style set)
    from .renderer import render_all
    stage("render")
    final_path = render_all(ffmpeg, timeline, output_dir / "04_clips",
                            output_dir / "final.mp4",
                            reencode=options.reencode_concat,
                            music_source=music_source,
                            music_volume=options.music_volume, log=log,
                            on_clip=scene_event("clip"))

    manifest_path = write_manifest(options, timeline, style_set, output_dir,
                                   dry_run=False, music_desc=music_desc)
    log(f"done: {final_path}")
    emit("done", video=str(final_path), social=social,
         output_dir=str(output_dir), duration=timeline.total_duration)
    return PipelineResult(output_dir, manifest_path, final_path, style_set,
                          personas, social)
