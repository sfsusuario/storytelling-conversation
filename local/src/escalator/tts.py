from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .ffutil import probe_duration
from .models import Scene

EDGE_PARALLEL = 4
KOKORO_SAMPLE_RATE = 24000


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


def estimate_word_timings(text: str, start: float, duration: float) -> list[dict]:
    """Spread a spoken segment's duration over its words by character length.

    Kokoro gives no word boundaries for Spanish; this keeps captions close
    enough to the speech for the chunked subtitle renderer.
    """
    words = text.split()
    if not words or duration <= 0:
        return []
    weights = [len(w) + 1 for w in words]
    unit = duration / sum(weights)
    timings, t = [], start
    for word, weight in zip(words, weights):
        d = weight * unit
        timings.append({"t": round(t, 3), "d": round(d, 3), "w": word})
        t += d
    return timings


def kokoro_speed(rate: str) -> float:
    """edge-style rate offset ("-8%") -> Kokoro speed multiplier (0.92)."""
    try:
        return max(0.5, min(2.0, 1 + float(rate.strip().rstrip("%")) / 100))
    except ValueError:
        return 1.0


class _Kokoro:
    """Loads the Kokoro model once per run; synthesis is CPU-bound and serial."""

    def __init__(self, lang_code: str):
        try:
            from kokoro import KPipeline
        except ImportError as e:
            raise TtsError(
                "Kokoro (local TTS) is not installed. Install with:\n"
                "  python -m pip install -e \".[tts-local]\"\n"
                "or use --tts-provider edge.") from e
        self.pipeline = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")

    def synthesize(self, text: str, voice: str, speed: float,
                   out_path: Path) -> list[dict]:
        import numpy as np
        import soundfile as sf

        chunks, words, offset = [], [], 0.0
        for result in self.pipeline(text, voice=voice, speed=speed):
            if result.audio is None:
                continue
            audio = result.audio.numpy()
            seconds = len(audio) / KOKORO_SAMPLE_RATE
            words += estimate_word_timings(result.graphemes, offset, seconds)
            chunks.append(audio)
            offset += seconds
        if not chunks:
            raise TtsError(f"Kokoro produced no audio for: {text!r}")
        tmp = out_path.with_suffix(".tmp.wav")
        sf.write(tmp, np.concatenate(chunks), KOKORO_SAMPLE_RATE)
        tmp.replace(out_path)
        return words


# Kokoro language codes (https://huggingface.co/hexgrad/Kokoro-82M)
KOKORO_LANG = {"es": "e", "en": "a", "pt": "p", "fr": "f", "it": "i",
               "hi": "h", "ja": "j", "zh": "z"}


PREVIEW_TEXT = {"es": "Hola, así sonará la narración de tu vídeo.",
                "en": "Hello, this is how your video's narration will sound."}


def preview_voice(provider: str, voice: str, language: str, rate: str,
                  pitch: str, out_dir: Path) -> Path:
    """Short cached sample of a voice, for the UI's listen button."""
    voice = resolve_voice(provider, voice)
    text = PREVIEW_TEXT.get(language, PREVIEW_TEXT["en"])
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = ".wav" if provider == "kokoro" else ".mp3"
    safe = "".join(c if c.isalnum() else "_" for c in f"{voice}_{rate}_{pitch}")
    out = out_dir / f"{provider}_{language}_{safe}{ext}"
    if not (out.exists() and out.stat().st_size > 0):
        if provider == "kokoro":
            _Kokoro(KOKORO_LANG.get(language, "e")).synthesize(
                text, voice, kokoro_speed(rate), out)
        else:
            asyncio.run(_synthesize_one(text, voice, out, rate, pitch))
    return out


def resolve_voice(provider: str, voice: str) -> str:
    """Swap in the provider's default when the voice belongs to the other one."""
    from .config import DEFAULT_KOKORO_VOICE

    is_edge_voice = "Neural" in voice
    if provider == "kokoro" and is_edge_voice:
        return DEFAULT_KOKORO_VOICE
    if provider == "edge" and not is_edge_voice:
        return "es-ES-AlvaroNeural"
    return voice


def synthesize_scenes(scenes: list[Scene], voice: str, audio_dir: Path,
                      ffprobe: str, rate: str = "+0%", pitch: str = "+0Hz",
                      provider: str = "edge", language: str = "es",
                      log=print, on_scene=None, keep: bool = False) -> None:
    """Generate one audio file per scene (cached) and fill in durations.

    keep: reuse existing audio even if its stamp is outdated."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    ext = ".wav" if provider == "kokoro" else ".mp3"

    pending = []
    for scene in scenes:
        out = audio_dir / f"{scene.scene_id}{ext}"
        meta = audio_dir / f"{scene.scene_id}.json"
        stamp = f"{provider}|{voice}|{rate}|{pitch}|wb|{scene.speech_script}"
        cached_meta = None
        if out.exists() and out.stat().st_size > 0 and meta.exists():
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                if keep or data.get("stamp") == stamp:
                    cached_meta = data
            except json.JSONDecodeError:
                pass
        scene.audio_path = out
        if cached_meta is not None:
            scene.word_timings = cached_meta.get("words") or None
            log(f"  tts: {out.name} (cached)")
            if on_scene:
                on_scene(scene, True)
        else:
            pending.append((scene, out, meta, stamp))

    def finish(scene, out, meta, stamp, words):
        scene.word_timings = words or None
        meta.write_text(json.dumps({"stamp": stamp, "words": words},
                                   ensure_ascii=False), encoding="utf-8")
        log(f"  tts: {out.name}")
        if on_scene:
            on_scene(scene, False)

    if pending and provider == "kokoro":
        engine = _Kokoro(KOKORO_LANG.get(language, "e"))
        speed = kokoro_speed(rate)
        for scene, out, meta, stamp in pending:
            words = engine.synthesize(scene.speech_script, voice, speed, out)
            finish(scene, out, meta, stamp, words)
    elif pending:
        async def run() -> None:
            sem = asyncio.Semaphore(EDGE_PARALLEL)

            async def one(scene, out, meta, stamp):
                async with sem:
                    words = await _synthesize_one(scene.speech_script, voice,
                                                  out, rate, pitch)
                finish(scene, out, meta, stamp, words)

            await asyncio.gather(*(one(*p) for p in pending))

        asyncio.run(run())

    with ThreadPoolExecutor(max_workers=EDGE_PARALLEL) as pool:
        durations = pool.map(lambda s: probe_duration(ffprobe, s.audio_path), scenes)
        for scene, duration in zip(scenes, durations):
            scene.audio_duration = duration
