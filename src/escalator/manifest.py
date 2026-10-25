from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import PipelineOptions, TRANSITION_DURATION
from .models import Timeline


def write_manifest(options: PipelineOptions, timeline: Timeline,
                   style_set_label: str, output_dir: Path,
                   dry_run: bool, music_desc: str = "none") -> Path:
    scenes = []
    for s in timeline.scenes:
        rel = lambda p: p.relative_to(output_dir).as_posix() if p else None
        scenes.append({
            "Scene_ID": s.scene_id,
            "Style": s.persona.name,
            "Style_Level": s.persona.level,
            "Visual_Style_Prompt": s.visual_style_prompt,
            "Speech_Script": s.speech_script,
            "Voice_Config": {"engine": "edge-tts", "voice": options.voice,
                             "rate": options.voice_rate,
                             "pitch": options.voice_pitch},
            "Timing_Map": {
                "Scene_Start": s.scene_start,
                "Audio_Trigger_Delay": s.audio_trigger_delay,
                "Audio_File_Length": s.audio_duration,
                "Estimated": dry_run,
                "Scene_End_Delay": s.scene_end_delay,
                "Scene_Duration": s.scene_duration,
            },
            "Transition_Type": timeline.transition_type,
            "Assets": {
                "image": rel(s.image_path),
                "audio": rel(s.audio_path),
                "clip": rel(s.clip_path),
            },
        })

    manifest = {
        "Generated_At": datetime.now().isoformat(timespec="seconds"),
        "Base_Image": Path(options.base_image).resolve().as_posix(),
        "Input_Phrase": options.phrase,
        "Language": options.language,
        "Style_Set": style_set_label,
        "Seed": options.seed,
        "Resolution": f"{timeline.width}x{timeline.height}",
        "FPS": timeline.fps,
        "Fit": timeline.fit,
        "Watermark": timeline.watermark,
        "Subtitles": timeline.subtitles,
        "Music": {"source": music_desc, "style_set": style_set_label,
                  "volume": options.music_volume},
        "Text_Provider": options.text_provider,
        "Text_Model": options.text_model,
        "Image_Provider": options.image_provider,
        "Image_Model": options.image_model,
        "TTS_Provider": options.tts_provider,
        "Motion": options.motion,
        "Total_Duration": round(timeline.total_duration, 3),
        "Transition_Type": timeline.transition_type,
        "Transition_Duration": TRANSITION_DURATION,
        "Dry_Run": dry_run,
        "Test_Mode": options.test_mode,
        "Scenes": scenes,
    }

    path = output_dir / "pipeline.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    return path
