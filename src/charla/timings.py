"""Historical render durations, used for the UI's global time progress bar.

Every finished (non-dry) run of stages 2-4 appends its duration to
output/_timings.json, keyed by voice engine (the dominant cost factor).
The estimate for the next run is the median seconds-per-turn of past runs
times the number of turns.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

_FILE = Path("output") / "_timings.json"
_KEEP = 25  # last runs kept per engine

# Below this per-turn cost the run was clearly served from cache (audio and
# clips reused); recording it would poison the estimates for real runs.
_MIN_SECONDS_PER_TURN = 2.0


def engine_key(tts_engine: str, use_rvc: bool) -> str:
    return f"{tts_engine}+rvc" if use_rvc else tts_engine


def _load() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def record_run(engine: str, turns: int, seconds: float) -> None:
    if turns <= 0 or seconds / max(1, turns) < _MIN_SECONDS_PER_TURN:
        return
    data = _load()
    runs = data.setdefault(engine, [])
    runs.append({"turns": turns, "seconds": round(seconds, 1)})
    del runs[:-_KEEP]
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass  # timing history is best-effort, never break the pipeline


def estimate_seconds(engine: str, turns: int) -> float | None:
    """Expected duration of stages 2-4 for `turns` turns, or None if there
    is no history yet for this engine."""
    runs = _load().get(engine) or []
    per_turn = [r["seconds"] / r["turns"] for r in runs
                if r.get("turns") and r.get("seconds")]
    if not per_turn:
        return None
    return statistics.median(per_turn) * max(1, turns)
