"""pipeline.json of a story run: what the studio's history shows and what
"regenerate from a stage" needs to rebuild the options."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from escalator.history import run_dir
from escalator.models import Timeline

from .config import OUTPUT_ROOT, StoryOptions
from .story_gen import Story


def _rel(path: Path | None, output_dir: Path) -> str | None:
    if not path:
        return None
    try:
        return Path(path).resolve().relative_to(output_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def write_story_manifest(options: StoryOptions, story: Story, timeline: Timeline,
                         output_dir: Path, style: str, base_image: Path | None) -> Path:
    scenes = []
    for scene, src in zip(timeline.scenes, story.scenes):
        scenes.append({
            "Scene_ID": scene.scene_id,
            "Narration": scene.speech_script,
            "Image_Prompt": scene.visual_style_prompt,
            "Scene_Duration": scene.scene_duration,
            "Assets": {"image": _rel(scene.image_path, output_dir),
                       "audio": _rel(scene.audio_path, output_dir),
                       "clip": _rel(scene.clip_path, output_dir)},
            "Story_Image_Prompt": src.image_prompt,
        })
    manifest = {
        "Generated_At": datetime.now().isoformat(timespec="seconds"),
        "Title": story.title,
        "Premise": options.premise,
        "Tone": options.tone,
        "Genre": options.genre,
        "Style": style,
        "Language": options.language,
        "Seed": options.seed,
        "Base_Image": _rel(base_image, output_dir),
        "Resolution": f"{options.width}x{options.height}",
        "FPS": options.fps,
        "Fit": options.fit,
        "Watermark": options.watermark,
        "Subtitles": options.subtitles,
        "Voice": options.voice,
        "Voice_Rate": options.voice_rate,
        "Voice_Pitch": options.voice_pitch,
        "Text_Provider": options.text_provider,
        "Text_Model": options.text_model,
        "Image_Provider": options.image_provider,
        "Image_Model": options.image_model,
        "TTS_Provider": options.tts_provider,
        "Motion": options.motion,
        "Total_Duration": timeline.total_duration,
        "Test_Mode": options.test_mode,
        "Protagonist": story.protagonist,
        "Outline": story.outline,
        "Scenes": scenes,
    }
    path = output_dir / "pipeline.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def regenerate_options(name: str, root: Path = OUTPUT_ROOT) -> dict:
    """StoryOptions fields of a finished run, read back from its manifest."""
    folder = run_dir(name, root)
    m = json.loads((folder / "pipeline.json").read_text(encoding="utf-8"))
    width, height = (int(x) for x in m["Resolution"].split("x"))
    base = m.get("Base_Image")
    photo = folder / base if base else None
    fields = {
        "premise": m["Premise"], "tone": m["Tone"], "genre": m["Genre"],
        "style": m.get("Style", "auto"), "scenes": len(m["Scenes"]),
        "seed": m.get("Seed"), "language": m.get("Language", "es"),
        "voice": m.get("Voice"), "voice_rate": m.get("Voice_Rate"),
        "voice_pitch": m.get("Voice_Pitch"), "width": width, "height": height,
        "fps": m.get("FPS", 30), "fit": m.get("Fit", "crop"),
        "watermark": m.get("Watermark", ""), "subtitles": m.get("Subtitles", True),
        "text_provider": m.get("Text_Provider", "auto"), "text_model": m.get("Text_Model"),
        "image_provider": m.get("Image_Provider", "auto"), "image_model": m.get("Image_Model"),
        "tts_provider": m.get("TTS_Provider"), "motion": m.get("Motion", "none"),
        "test_mode": bool(m.get("Test_Mode")),
        "base_image": photo if photo is not None and photo.is_file() else None,
    }
    return {k: v for k, v in fields.items() if v is not None}
