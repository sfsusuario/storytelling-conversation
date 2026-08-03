from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import PipelineOptions
from .models import Timeline, VoiceSpec


def write_manifest(options: PipelineOptions, timeline: Timeline,
                   title: str, output_dir: Path, dry_run: bool,
                   voices: dict[str, VoiceSpec]) -> Path:
    turns = []
    for t in timeline.turns:
        rel = lambda p: p.relative_to(output_dir).as_posix() if p else None
        spec = voices[t.speaker]
        turns.append({
            "Turn_ID": t.turn_id,
            "Speaker": t.speaker,
            "Emotion": t.emotion,
            "Line": t.line,
            "Voice_Config": {"engine": "edge-tts", "voice": spec.voice,
                             "rate": spec.rate, "pitch": spec.pitch},
            "Timing_Map": {
                "Turn_Start": t.turn_start,
                "Audio_Trigger_Delay": t.audio_trigger_delay,
                "Audio_File_Length": t.audio_duration,
                "Estimated": dry_run,
                "Turn_End_Delay": t.turn_end_delay,
                "Turn_Duration": t.turn_duration,
                "Background_Offset": t.bg_offset,
                "Character_Offset": t.char_offset,
                "Character_Pingpong": t.char_pingpong,
            },
            "Assets": {
                "character_clip": (t.character_clip.as_posix()
                                   if t.character_clip else None),
                "audio": rel(t.audio_path),
                "clip": rel(t.clip_path),
            },
        })

    manifest = {
        "Generated_At": datetime.now().isoformat(timespec="seconds"),
        "Title": title,
        "Input": options.input_text or (
            str(options.script_file) if options.script_file else ""),
        "Input_Is_URL": options.is_url,
        "Script_File": str(options.script_file) if options.script_file else None,
        "Language": options.language,
        "Resolution": f"{timeline.width}x{timeline.height}",
        "FPS": timeline.fps,
        "Watermark": timeline.watermark,
        "Subtitles": timeline.subtitles,
        "Background": Path(options.background).resolve().as_posix(),
        "Background_Volume": options.bg_volume,
        "Chroma": {"similarity": options.chroma_similarity,
                   "blend": options.chroma_blend},
        "Text_Provider": options.text_provider,
        "Text_Model": options.text_model,
        "Total_Duration": round(timeline.total_duration, 3),
        "Dry_Run": dry_run,
        "Turns": turns,
    }

    path = output_dir / "manifest.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    return path
