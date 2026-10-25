from __future__ import annotations

import math

from .models import Scene, Timeline


def build_timeline(scenes: list[Scene], width: int, height: int, fps: int,
                   fit: str = "crop", watermark: str = "",
                   subtitles: bool = True, level_word: str = "NIVEL") -> Timeline:
    """Fill in frame-rounded durations and absolute start times.

    D_i = trigger_delay + audio_duration + end_delay, rounded UP to a whole
    frame so every clip cuts on a frame boundary. The 0.5s fade-to-black
    transition lives inside the pauses (0.25s fade-out in each scene's tail,
    0.25s fade-in in the next scene's head) and adds zero duration.
    """
    cursor = 0.0
    for scene in scenes:
        if scene.audio_duration is None:
            raise ValueError(f"{scene.scene_id} has no audio duration")
        raw = scene.raw_duration
        scene.scene_duration = math.ceil(raw * fps) / fps
        scene.scene_start = round(cursor, 6)
        cursor += scene.scene_duration
    return Timeline(scenes=scenes, width=width, height=height, fps=fps,
                    fit=fit, watermark=watermark, subtitles=subtitles,
                    level_word=level_word)
