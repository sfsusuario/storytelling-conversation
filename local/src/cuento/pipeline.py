"""Story pipeline: text -> images -> tts -> timeline -> motion -> render.

Same stages, folders, cache stamps and progress events as Escalera, so the
shared run machinery and the web's progress view work unchanged. Scenes carry
a stand-in Persona: level = index + 2 (Escalera's image engines copy the photo
for level 1), name = the visual style, image_detail = this scene's prompt.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from escalator.ffutil import require_ffmpeg
from escalator.image_gen import generate_scene_images
from escalator.models import Persona, Scene
from escalator.motion import generate_motion
from escalator.pipeline import (STAGES, PipelineCancelled, _apply_force,  # noqa: F401
                                _slugify, scene_variants)
from escalator.renderer import render_all
from escalator.text_gen import resolve_text_backend
from escalator.timeline import build_timeline
from escalator.tts import resolve_voice, synthesize_scenes

from .config import (AUDIO_TRIGGER_DELAY, OUTPUT_ROOT, SCENE_END_DELAY, STYLE_PRESETS,
                     StoryOptions, default_style, style_fragment, validate)
from .images import (credits_card, generate_story_images, placeholder_images,
                     resolve_story_image_provider, silence_wav, story_prompt)
from .manifest import write_story_manifest
from .sources import fetch_story
from .story_gen import generate_story

Progress = Callable[[str], None]
EventSink = Callable[[dict], None]
CREDITS_SECONDS = 3.0


def default_output_dir(options: StoryOptions) -> Path:
    # preview is left out on purpose: "continue" must land in the same folder
    h = hashlib.sha256()
    h.update("|".join(str(x) for x in (
        options.premise, options.source, options.tone, options.genre, options.style,
        options.scenes, options.language, options.voice, options.voice_rate,
        options.voice_pitch, f"{options.width}x{options.height}@{options.fps}",
        options.fit, options.watermark, options.subtitles, options.test_mode)).encode("utf-8"))
    h.update(Path(options.base_image).read_bytes() if options.base_image else b"nophoto")
    label = options.premise or options.source.rstrip("/").rsplit("/", 1)[-1]
    return OUTPUT_ROOT / f"{_slugify(label)}-{h.hexdigest()[:8]}"


def run_story(options: StoryOptions, on_progress: Progress = print,
              on_event: EventSink | None = None,
              cancel: threading.Event | None = None) -> Path | None:
    """The final video, or None for a preview (stops after the text)."""
    log = on_progress
    validate(options)
    if options.base_image and not Path(options.base_image).is_file():
        raise FileNotFoundError(f"Protagonist photo not found: {options.base_image}")
    style = default_style(options.tone, options.genre) if options.style == "auto" else options.style
    fragment = style_fragment(style)

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

    output_dir = Path(options.output_dir) if options.output_dir else default_output_dir(options)
    output_dir.mkdir(parents=True, exist_ok=True)
    log(f"output dir: {output_dir}")
    # the photo lives next to the manifest, outside the folders a stage wipes
    base_image = None
    if options.base_image:
        base_image = output_dir / f"protagonista{Path(options.base_image).suffix.lower()}"
        if Path(options.base_image).resolve() != base_image.resolve():
            shutil.copyfile(options.base_image, base_image)

    count = int(options.scenes)
    scenes = [
        Scene(index=i + 1, scene_id=f"scene_{i + 1:02d}",
              persona=Persona(level=i + 2, name=fragment, register="",
                              image_detail="", escalation="story"),
              audio_trigger_delay=AUDIO_TRIGGER_DELAY, scene_end_delay=SCENE_END_DELAY)
        for i in range(count)
    ]
    emit("scenes", style_set=STYLE_PRESETS[style][0], output_dir=str(output_dir),
         scenes=[{"scene_id": s.scene_id, "level": s.index, "persona": f"Escena {s.index}"}
                 for s in scenes])
    _apply_force(output_dir, options, log)
    ffmpeg, ffprobe = require_ffmpeg()

    def kept(name: str) -> bool:
        return bool(options.force_from) and STAGES.index(name) < STAGES.index(options.force_from)

    # 1. the story (invented, or adapted from a real Reddit post)
    provider, text_model = resolve_text_backend(options.text_provider, options.text_model)
    options.text_provider, options.text_model = provider, text_model
    stage("text", f"{provider}: {text_model}")
    source = None
    if options.source:
        source_file = output_dir / "01_text" / "source.json"
        if source_file.exists():
            source = json.loads(source_file.read_text(encoding="utf-8"))
        else:
            source = fetch_story(options.source)
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
        log(f"  historia real: u/{source['author']} en r/{source['subreddit']} ({source['words']} palabras)")
    premise = options.premise.strip() or source["title"]
    story, social = generate_story(premise, options.tone, options.genre, count,
                                   text_model, output_dir / "01_text", provider=provider,
                                   language=options.language, seed=options.seed,
                                   has_photo=base_image is not None, keep=kept("text"),
                                   source=source)
    for scene, src in zip(scenes, story.scenes):
        scene.speech_script = src.narration
        prompt = (f"{src.image_prompt}, {story.protagonist}, {fragment}" if base_image
                  else story_prompt(src.image_prompt, story.protagonist, fragment))
        scene.persona = dataclasses.replace(scene.persona, image_detail=prompt)
        log(f'  escena {scene.index}: "{src.narration}"')
        emit("scene", scene_id=scene.scene_id, kind="text", text=src.narration)
    (output_dir / "social.txt").write_text(social, encoding="utf-8")
    emit("story", title=story.title, outline=story.outline, protagonist=story.protagonist,
         source=({"url": source["url"], "author": source["author"],
                  "subreddit": source["subreddit"]} if source else None))
    if options.preview:
        log("guion listo (solo texto)")
        emit("done", video=None, social=social, output_dir=str(output_dir), duration=0.0)
        return None

    # 2. images
    images_dir = output_dir / "02_images"
    variants = scene_variants(images_dir / "variants.json", options.reroll_images)
    if options.test_mode:
        stage("images", "test mode: placeholders")
        placeholder_images(scenes, images_dir, ffmpeg, base_image, log=log)
        for scene in scenes:
            scene_event("image")(scene, True)
    else:
        options.image_provider = resolve_story_image_provider(options.image_provider,
                                                              base_image is not None)
        stage("images", options.image_provider)
        if base_image is not None:
            generate_scene_images(scenes, base_image, options.image_model, images_dir,
                                  ffmpeg=ffmpeg, provider=options.image_provider,
                                  seed=options.seed, log=log,
                                  on_image=scene_event("image"),
                                  on_step=step_event("images"), variants=variants,
                                  keep=kept("images"))
        else:
            generate_story_images(scenes, images_dir, options.seed, log=log,
                                  on_image=scene_event("image"),
                                  on_step=step_event("images"), variants=variants,
                                  keep=kept("images"))

    # 3. narration
    options.voice = resolve_voice(options.tts_provider, options.voice)
    stage("tts", f"{options.tts_provider}: {options.voice}")
    synthesize_scenes(scenes, options.voice, output_dir / "03_audio", ffprobe,
                      rate=options.voice_rate, pitch=options.voice_pitch,
                      provider=options.tts_provider, language=options.language,
                      log=log, on_scene=scene_event("audio"), keep=kept("tts"))

    # a Reddit story ends with a credits card: a silent still scene the
    # renderer treats like any other (same fit, watermark and fades)
    story_scenes = list(scenes)
    if source:
        scenes.append(Scene(
            index=count + 1, scene_id="credits", persona=scenes[0].persona,
            image_path=credits_card(output_dir / "02_images" / "credits.png", source["author"],
                                    source["subreddit"], ffmpeg, options.width, options.height),
            audio_path=silence_wav(output_dir / "03_audio" / "credits.wav", CREDITS_SECONDS, ffmpeg),
            audio_duration=CREDITS_SECONDS, audio_trigger_delay=0.0, scene_end_delay=0.0))

    # 4. timeline: no level badge, subtitles keep the characters' names
    timeline = build_timeline(scenes, options.width, options.height, options.fps,
                              options.fit, options.watermark, options.subtitles,
                              level_word="")
    timeline.keep_case = True
    stage("timeline", f"{timeline.total_duration:.2f}s total")

    # 5. motion: the same 3D parallax as Escalera; a scene with no figure stays still
    stage("motion", options.motion if options.motion != "none" else "off")
    generate_motion(options.motion, story_scenes, output_dir / "05_motion", options.fps,
                    ffmpeg, seed=options.seed, log=log, on_scene=scene_event("motion"),
                    on_step=step_event("motion"),
                    variants=scene_variants(output_dir / "05_motion" / "variants.json",
                                            options.reroll_motion),
                    keep=kept("motion"), skip_without_subject=True)

    # 6. render
    stage("render")
    final_path = render_all(ffmpeg, timeline, output_dir / "04_clips",
                            output_dir / "final.mp4", log=log,
                            on_clip=scene_event("clip"))
    write_story_manifest(options, story, timeline, output_dir, style, base_image, source)
    log(f"done: {final_path}")
    emit("done", video=str(final_path), social=social, output_dir=str(output_dir),
         duration=timeline.total_duration)
    return final_path
