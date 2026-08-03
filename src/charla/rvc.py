"""Optional RVC voice conversion: re-timbres the edge-tts audio with the
show's real Latin American dub voices (community RVC v2 models trained on
Juan Guzmán / Eder La Barrera — Matius54 on Hugging Face).

Runs in a dedicated Python 3.10 venv (.rvc-venv) via scripts/rvc_worker.py,
because rvc-python's dependency set (fairseq, numpy<=1.23) does not install
on the modern Python that runs charla itself. Set it up with install-rvc.ps1.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import CHARACTERS, RVC_F0_METHOD, RVC_MODELS_DIR, RVC_PYTHON
from .ffutil import probe_duration
from .models import Turn


class RvcError(RuntimeError):
    pass


_WORKER = Path(__file__).resolve().parents[2] / "scripts" / "rvc_worker.py"


def character_model(name: str) -> tuple[Path, Path | None]:
    """(pth, index) for a character; index may be missing."""
    pth = RVC_MODELS_DIR / name / f"{name}.pth"
    index = RVC_MODELS_DIR / name / f"{name}.index"
    return pth, (index if index.is_file() else None)


def rvc_available() -> bool:
    """True when the venv and every character's model are on disk."""
    if not RVC_PYTHON.is_file() or not _WORKER.is_file():
        return False
    return all(character_model(n)[0].is_file() for n in CHARACTERS)


def rvc_unavailable_reason() -> str:
    if not RVC_PYTHON.is_file():
        return (f"RVC venv not found at {RVC_PYTHON}. "
                "Run .\\install-rvc.ps1 to set it up.")
    missing = [n for n in CHARACTERS if not character_model(n)[0].is_file()]
    if missing:
        return (f"RVC models missing for: {', '.join(missing)} "
                f"(expected under {RVC_MODELS_DIR}). Run .\\install-rvc.ps1.")
    return "RVC is available."


def _stamp(turn: Turn, pth: Path, pitch: int) -> str:
    return "|".join(str(x) for x in (
        "rvc-v1", turn.audio_path.stat().st_mtime_ns,
        pth.stat().st_mtime_ns, pitch, RVC_F0_METHOD))


def convert_turns(turns: list[Turn], audio_dir: Path, ffprobe: str,
                  log=print) -> None:
    """Convert each turn's TTS audio to its character's dub voice (cached).

    Replaces turn.audio_path/audio_duration with the converted wav. Grouped
    by character so the worker loads each model only once.
    """
    jobs: dict[str, dict] = {}
    pending: list[tuple[Turn, Path, Path, str]] = []

    for turn in turns:
        pth, index = character_model(turn.speaker)
        pitch = CHARACTERS[turn.speaker].rvc_pitch
        out = audio_dir / f"{turn.turn_id}.rvc.wav"
        meta = audio_dir / f"{turn.turn_id}.rvc.json"
        stamp = _stamp(turn, pth, pitch)
        if out.exists() and out.stat().st_size > 0 and meta.exists() \
                and meta.read_text(encoding="utf-8") == stamp:
            log(f"  rvc: {out.name} (cached)")
        else:
            job = jobs.setdefault(turn.speaker, {
                "model": str(pth), "index": str(index) if index else "",
                "pitch": pitch, "files": []})
            job["files"].append([str(turn.audio_path), str(out)])
            pending.append((turn, out, meta, stamp))
        turn.audio_path = out

    if pending:
        spec = {"device": "cpu", "f0method": RVC_F0_METHOD,
                "jobs": list(jobs.values())}
        jobs_file = audio_dir / "_rvc_jobs.json"
        jobs_file.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        proc = subprocess.run(
            [str(RVC_PYTHON), str(_WORKER), str(jobs_file)],
            capture_output=True, text=True)
        if proc.returncode != 0:
            tail = "\n".join((proc.stderr or proc.stdout or "")
                             .strip().splitlines()[-15:])
            raise RvcError(f"RVC conversion failed:\n{tail}")
        for turn, out, meta, stamp in pending:
            if not out.exists() or out.stat().st_size == 0:
                raise RvcError(f"RVC produced no audio for {out.name}")
            meta.write_text(stamp, encoding="utf-8")
            log(f"  rvc: {out.name} ({turn.speaker})")

    for turn in turns:
        turn.audio_duration = probe_duration(ffprobe, turn.audio_path)
