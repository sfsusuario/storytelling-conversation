from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class VoiceSpec:
    voice: str
    rate: str    # e.g. "-10%"
    pitch: str   # e.g. "-15Hz"


@dataclass
class Turn:
    index: int                           # 1-based position in the video
    turn_id: str                         # "turn_01"
    speaker: str                         # "rick" | "morty"
    emotion: str                         # "enojo_ira"
    line: str                            # spoken text
    character_clip: Path | None = None   # source emotion loop (green screen)
    audio_path: Path | None = None
    audio_duration: float | None = None  # seconds, from ffprobe
    audio_trigger_delay: float = 0.3
    turn_end_delay: float = 0.4
    turn_start: float | None = None      # absolute start in the final video
    turn_duration: float | None = None   # frame-rounded total duration
    bg_offset: float | None = None       # seek into background.mp4 (continuity)
    char_offset: float | None = None     # seek into the character clip (tail-aligned)
    char_pingpong: bool = False          # long line: forward+mirror loop used
    clip_path: Path | None = None        # rendered clip
    word_timings: list | None = None     # [{t, d, w}] seconds, from edge-tts

    @property
    def raw_duration(self) -> float:
        return self.audio_trigger_delay + (self.audio_duration or 0.0) + self.turn_end_delay


@dataclass
class Timeline:
    turns: list[Turn] = field(default_factory=list)
    width: int = 720
    height: int = 1280
    fps: int = 30
    watermark: str = ""      # bottom-left overlay text; empty = none
    subtitles: bool = True   # burn captions into each turn

    @property
    def total_duration(self) -> float:
        return sum(t.turn_duration or 0.0 for t in self.turns)


def build_timeline(turns: list[Turn], width: int, height: int, fps: int,
                   bg_duration: float, watermark: str = "",
                   subtitles: bool = True) -> Timeline:
    """Fill in frame-rounded durations, absolute starts and background offsets.

    D_i = trigger_delay + audio_duration + end_delay, rounded UP to a whole
    frame so every clip cuts on a frame boundary. Turns are joined with hard
    cuts (shot/reverse-shot); the background keeps advancing across cuts:
    each turn seeks background.mp4 to where the previous turn left it,
    wrapping at its end.
    """
    cursor = 0.0
    for turn in turns:
        if turn.audio_duration is None:
            raise ValueError(f"{turn.turn_id} has no audio duration")
        turn.turn_duration = math.ceil(turn.raw_duration * fps) / fps
        turn.turn_start = round(cursor, 6)
        turn.bg_offset = round(cursor % bg_duration, 3) if bg_duration > 0 else 0.0
        cursor += turn.turn_duration
    return Timeline(turns=turns, width=width, height=height, fps=fps,
                    watermark=watermark, subtitles=subtitles)
