from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Persona:
    level: int              # 1 (lowest) .. 5 (highest sophistication)
    name: str               # "Medieval Knight"
    register: str           # guidance for the text rewrite (tone, vocabulary, syntax)
    image_detail: str       # wardrobe/background/lighting/art-style block for image gen
    escalation: str = "sophistication"  # what grows level to level: sophistication | absurdity


@dataclass
class Scene:
    index: int                          # 1-based position in the video
    scene_id: str                       # "scene_01"
    persona: Persona
    visual_style_prompt: str = ""
    speech_script: str = ""
    image_path: Path | None = None
    audio_path: Path | None = None
    audio_duration: float | None = None  # seconds, from ffprobe
    audio_trigger_delay: float = 0.3
    scene_end_delay: float = 0.5
    scene_start: float | None = None     # absolute start in the final video
    scene_duration: float | None = None  # frame-rounded total duration
    clip_path: Path | None = None
    word_timings: list | None = None     # [{t, d, w}] seconds, from edge-tts
    motion_path: Path | None = None      # silent animated version of image_path, looped

    @property
    def raw_duration(self) -> float:
        return self.audio_trigger_delay + (self.audio_duration or 0.0) + self.scene_end_delay


@dataclass
class Timeline:
    scenes: list[Scene] = field(default_factory=list)
    width: int = 1080
    height: int = 1920
    fps: int = 30
    fit: str = "crop"   # crop (fill, TikTok-style) | blur (blurred bg) | pad (letterbox)
    watermark: str = ""  # bottom-left overlay text; empty = none
    subtitles: bool = True  # burn narration subtitles into each scene
    level_word: str = "NIVEL"  # word for the top level indicator
    transition_type: str = "FadeToBlack"
    transition_duration: float = 0.5

    @property
    def total_duration(self) -> float:
        return sum(s.scene_duration or 0.0 for s in self.scenes)
