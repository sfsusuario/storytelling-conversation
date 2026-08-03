"""Optional XTTS v2 voice engine: generates each line DIRECTLY in the
character's cloned voice (timbre + more natural prosody than edge-tts),
following the "IA XTTS Text to Voice" Colab strategy.

Two modes, resolved per character automatically:
- Fine-tuned: models/xtts/<char>/ holds the Colab training output
  (best_model.pth + config.json + vocab.json) — best quality.
- Zero-shot: no checkpoint yet — the base XTTS v2 model clones the voice at
  inference time from the reference clips in voices_preview/reales/<char>/.

Runs in a dedicated Python 3.10 venv (.xtts-venv) via scripts/xtts_worker.py
(set up with install-xtts.ps1). CPU inference: slow (~1-2 min per line) but
local and free. XTTS license (CPML) is non-commercial.

No word timings are produced, so captions fall back to full-line mode.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .config import CHARACTERS, XTTS_MODELS_DIR, XTTS_PYTHON, XTTS_REFS_DIR
from .ffutil import probe_duration
from .models import Turn


class XttsError(RuntimeError):
    pass


_WORKER = Path(__file__).resolve().parents[2] / "scripts" / "xtts_worker.py"


def character_refs(name: str) -> list[Path]:
    """Reference clips for a character (prefer the normalized dataset wavs)."""
    root = XTTS_REFS_DIR / name
    dataset = XTTS_REFS_DIR / f"dataset_{name}"
    refs = sorted(dataset.glob("*.wav")) or sorted(
        list(root.glob("*.wav")) + list(root.glob("*.mp3")))
    return refs


def character_model_dir(name: str) -> Path | None:
    d = XTTS_MODELS_DIR / name
    if (d / "config.json").is_file() and (d / "vocab.json").is_file() \
            and list(d.glob("*.pth")):
        return d
    return None


def xtts_available() -> bool:
    if not XTTS_PYTHON.is_file() or not _WORKER.is_file():
        return False
    return all(character_model_dir(n) or character_refs(n)
               for n in CHARACTERS)


def xtts_unavailable_reason() -> str:
    if not XTTS_PYTHON.is_file():
        return (f"XTTS venv not found at {XTTS_PYTHON}. "
                "Run .\\install-xtts.ps1 to set it up.")
    missing = [n for n in CHARACTERS
               if not (character_model_dir(n) or character_refs(n))]
    if missing:
        return (f"No XTTS model or reference clips for: {', '.join(missing)} "
                f"(expected models/xtts/<char>/ or {XTTS_REFS_DIR}/<char>/).")
    return "XTTS is available."


def _voice_stamp(name: str) -> str:
    model_dir = character_model_dir(name)
    if model_dir:
        ckpt = sorted(model_dir.glob("*.pth"))[0]
        return f"ft|{ckpt}|{ckpt.stat().st_mtime_ns}"
    refs = character_refs(name)
    return "zs|" + "|".join(f"{r.name}:{r.stat().st_mtime_ns}" for r in refs)


def synthesize_turns(turns: list[Turn], language: str, audio_dir: Path,
                     ffprobe: str, log=print) -> None:
    """One cloned-voice wav per turn (cached); fills durations.

    Word timings stay None — the renderer's full-line caption fallback
    handles that.
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    jobs: dict[str, dict] = {}
    pending: list[tuple[Turn, Path, Path, str]] = []

    for turn in turns:
        out = audio_dir / f"{turn.turn_id}.xtts.wav"
        meta = audio_dir / f"{turn.turn_id}.xtts.json"
        stamp_src = f"xtts-v1|{language}|{turn.line}|{_voice_stamp(turn.speaker)}"
        stamp = hashlib.sha256(stamp_src.encode("utf-8")).hexdigest()
        if out.exists() and out.stat().st_size > 0 and meta.exists() \
                and meta.read_text(encoding="utf-8") == stamp:
            log(f"  xtts: {out.name} (cached)")
        else:
            model_dir = character_model_dir(turn.speaker)
            job = jobs.setdefault(turn.speaker, {
                "speaker": turn.speaker,
                "model_dir": str(model_dir) if model_dir else "",
                "refs": [str(r) for r in character_refs(turn.speaker)],
                "files": []})
            job["files"].append([turn.line, str(out)])
            pending.append((turn, out, meta, stamp))
        turn.audio_path = out
        turn.word_timings = None

    if pending:
        spec = {"language": language, "jobs": list(jobs.values())}
        jobs_file = audio_dir / "_xtts_jobs.json"
        jobs_file.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        log(f"  xtts: sintetizando {len(pending)} líneas (GPU si hay; "
            "en CPU ~1-2 min por línea)...")
        proc = subprocess.run(
            [str(XTTS_PYTHON), str(_WORKER), str(jobs_file)],
            capture_output=True, text=True)
        if proc.returncode != 0:
            tail = "\n".join((proc.stderr or proc.stdout or "")
                             .strip().splitlines()[-15:])
            raise XttsError(f"XTTS synthesis failed:\n{tail}")
        for turn, out, meta, stamp in pending:
            if not out.exists() or out.stat().st_size == 0:
                raise XttsError(f"XTTS produced no audio for {out.name}")
            meta.write_text(stamp, encoding="utf-8")
            log(f"  xtts: {out.name} ({turn.speaker})")

    for turn in turns:
        turn.audio_duration = probe_duration(ffprobe, turn.audio_path)
