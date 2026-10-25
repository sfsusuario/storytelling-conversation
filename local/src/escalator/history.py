"""Finished runs under output/, read back from their manifests (UI history)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .config import OUTPUT_ROOT  # noqa: E402  output/escalera inside the merged app


def list_runs(root: Path = OUTPUT_ROOT) -> list[dict]:
    """Every run with a final.mp4, newest first. Missing manifests are tolerated."""
    runs = []
    for video in root.glob("*/final.mp4"):
        run_dir = video.parent
        try:
            m = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            m = {}
        social_file = run_dir / "social.txt"
        scenes = m.get("Scenes", [])
        runs.append({
            "name": run_dir.name,
            "dir": run_dir,
            "video": video,
            "mtime": video.stat().st_mtime,
            "phrase": m.get("Input_Phrase", "?"),
            "style_set": m.get("Style_Set", "?"),
            "language": m.get("Language"),
            "duration": m.get("Total_Duration"),
            "test_mode": bool(m.get("Test_Mode")),
            "voice": (scenes[0].get("Voice_Config", {}).get("voice", "?")
                      if scenes else "?"),
            "social": (social_file.read_text(encoding="utf-8")
                       if social_file.exists() else ""),
            "scenes": [{
                "scene_id": s.get("Scene_ID"),
                "level": s.get("Style_Level"),
                "persona": s.get("Style"),
                "text": s.get("Speech_Script", ""),
                "image": (run_dir / s["Assets"]["image"]
                          if s.get("Assets", {}).get("image") else None),
            } for s in scenes],
        })
    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return runs


def run_dir(name: str, root: Path = OUTPUT_ROOT) -> Path:
    """Folder of one finished run. name comes from a client: it must be a
    plain folder name of a run with a final.mp4 directly under root."""
    folder = root / name
    if (not name or name.startswith((".", "_")) or Path(name).name != name
            or folder.resolve().parent != root.resolve()):
        raise ValueError(f"invalid run name: {name!r}")
    if not (folder / "final.mp4").is_file():
        raise FileNotFoundError(name)
    return folder


def delete_run(name: str, root: Path = OUTPUT_ROOT) -> None:
    """Remove one finished run folder (video + all its cached assets)."""
    shutil.rmtree(run_dir(name, root))


def regenerate_options(name: str, root: Path = OUTPUT_ROOT) -> dict:
    """PipelineOptions fields that reproduce a finished run from its manifest.

    Personas are pinned by name (styles), so a random/mix set gives the same
    ladder again and every cached text and image still matches."""
    folder = run_dir(name, root)
    m = json.loads((folder / "pipeline.json").read_text(encoding="utf-8"))
    scenes = m["Scenes"]
    voice = scenes[0].get("Voice_Config", {})
    width, height = (int(v) for v in m["Resolution"].split("x"))
    base = Path(m.get("Base_Image", ""))
    if not base.is_file():
        # The level-1 image is the untouched photo, but it lives in 02_images,
        # which a regenerate from images wipes: work from a copy outside it.
        base = root / "_uploads" / f"{name}.png"
        if not base.is_file():
            base.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(folder / "02_images" / "scene_01.png", base)
    music = m.get("Music", {})
    opts = {
        "base_image": base, "phrase": m["Input_Phrase"],
        "style_set": m.get("Style_Set", "random"),
        "styles": [s["Style"] for s in scenes], "stages": len(scenes),
        "seed": m.get("Seed"), "language": m.get("Language"),
        "voice": voice.get("voice"), "voice_rate": voice.get("rate"),
        "voice_pitch": voice.get("pitch"), "width": width, "height": height,
        "fps": m.get("FPS"), "fit": m.get("Fit"), "watermark": m.get("Watermark"),
        "subtitles": m.get("Subtitles"), "music_volume": music.get("volume"),
        "music_source": ("synth" if str(music.get("source", "")).startswith("synth")
                         else None),
        "text_provider": m.get("Text_Provider"), "text_model": m.get("Text_Model"),
        "image_provider": m.get("Image_Provider"), "image_model": m.get("Image_Model"),
        "tts_provider": m.get("TTS_Provider"), "test_mode": m.get("Test_Mode"),
        # Older manifests have no Motion: a motion folder means it had one.
        "motion": m.get("Motion") or ("rotate3d" if (folder / "05_motion").is_dir()
                                      else "none"),
    }
    return {k: v for k, v in opts.items() if v is not None}  # missing: defaults
