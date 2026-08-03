from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .ffutil import probe_duration
from .models import Turn, VoiceSpec


class TtsError(RuntimeError):
    pass


async def _synthesize_one(text: str, voice: str, out_path: Path,
                          rate: str, pitch: str) -> list[dict]:
    """Synthesize audio and return word timings [{t, d, w}] in seconds."""
    import edge_tts

    tmp = out_path.with_suffix(".tmp")
    for attempt in (1, 2):
        try:
            words: list[dict] = []
            communicate = edge_tts.Communicate(text, voice, rate=rate,
                                               pitch=pitch,
                                               boundary="WordBoundary")
            with open(tmp, "wb") as f:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        words.append({"t": chunk["offset"] / 1e7,
                                      "d": chunk["duration"] / 1e7,
                                      "w": chunk["text"]})
            if tmp.stat().st_size == 0:
                raise TtsError(f"edge-tts produced an empty file for: {text!r}")
            tmp.replace(out_path)
            return words
        except TtsError:
            tmp.unlink(missing_ok=True)
            raise
        except Exception as e:
            tmp.unlink(missing_ok=True)
            if attempt == 2:
                raise TtsError(
                    f"edge-tts failed for {out_path.name}: {e}\n"
                    "edge-tts needs internet access; check connectivity.") from e
            await asyncio.sleep(2)
    return []


def synthesize_turns(turns: list[Turn], voices: dict[str, VoiceSpec],
                     audio_dir: Path, ffprobe: str, log=print) -> None:
    """Generate one audio file per turn (cached) and fill in durations.

    Each turn is voiced with its speaker's VoiceSpec.
    """
    audio_dir.mkdir(parents=True, exist_ok=True)

    async def run() -> None:
        for turn in turns:
            spec = voices[turn.speaker]
            out = audio_dir / f"{turn.turn_id}.mp3"
            meta = audio_dir / f"{turn.turn_id}.json"
            stamp = (f"{turn.speaker}|{spec.voice}|{spec.rate}|{spec.pitch}"
                     f"|wb|{turn.line}")
            cached_meta = None
            if out.exists() and out.stat().st_size > 0 and meta.exists():
                try:
                    data = json.loads(meta.read_text(encoding="utf-8"))
                    if data.get("stamp") == stamp:
                        cached_meta = data
                except json.JSONDecodeError:
                    pass
            if cached_meta is not None:
                turn.word_timings = cached_meta.get("words") or None
                log(f"  tts: {out.name} (cached)")
            else:
                words = await _synthesize_one(turn.line, spec.voice, out,
                                              spec.rate, spec.pitch)
                turn.word_timings = words or None
                meta.write_text(json.dumps({"stamp": stamp, "words": words},
                                           ensure_ascii=False),
                                encoding="utf-8")
                log(f"  tts: {out.name} ({turn.speaker})")
            turn.audio_path = out

    asyncio.run(run())

    for turn in turns:
        turn.audio_duration = probe_duration(ffprobe, turn.audio_path)
