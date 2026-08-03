"""Optional Chatterbox voice engine (Resemble AI, MIT license): zero-shot
cloned voices from a single reference clip per character, with an
"exaggeration" control that suits theatrical characters.

Runs in a dedicated Python 3.10 venv (.chatterbox-venv) via
scripts/chatterbox_worker.py — set up with install-chatterbox.ps1. CPU
inference is slow (~1-2 min per line) but local and free; results are
cached per turn. No word timings, so captions fall back to full-line mode.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .config import (CHARACTERS, CHATTERBOX_PYTHON, CHATTERBOX_EXAGGERATION,
                     XTTS_REFS_DIR)
from .ffutil import probe_duration
from .models import Turn
from .textnorm import expand_numbers_for_tts


class ChatterboxError(RuntimeError):
    pass


_WORKER = (Path(__file__).resolve().parents[2] / "scripts"
           / "chatterbox_worker.py")


def character_ref(name: str) -> Path | None:
    """Single best reference clip: the largest normalized dataset wav."""
    dataset = XTTS_REFS_DIR / f"dataset_{name}"
    root = XTTS_REFS_DIR / name
    candidates = (sorted(dataset.glob("*.wav"))
                  or sorted(list(root.glob("*.wav")) + list(root.glob("*.mp3"))))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def chatterbox_available() -> bool:
    if not CHATTERBOX_PYTHON.is_file() or not _WORKER.is_file():
        return False
    return all(character_ref(n) for n in CHARACTERS)


def chatterbox_unavailable_reason() -> str:
    if not CHATTERBOX_PYTHON.is_file():
        return (f"Chatterbox venv not found at {CHATTERBOX_PYTHON}. "
                "Run .\\install-chatterbox.ps1 to set it up.")
    missing = [n for n in CHARACTERS if not character_ref(n)]
    if missing:
        return (f"No reference clips for: {', '.join(missing)} "
                f"(expected under {XTTS_REFS_DIR}/<char>/).")
    return "Chatterbox is available."


def synthesize_turns(turns: list[Turn], language: str, audio_dir: Path,
                     ffprobe: str, log=print) -> None:
    """One cloned-voice wav per turn (cached); fills durations."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    jobs: dict[str, dict] = {}
    pending: list[tuple[Turn, Path, Path, str]] = []

    for turn in turns:
        ref = character_ref(turn.speaker)
        exaggeration = CHATTERBOX_EXAGGERATION[turn.speaker]
        # The model misreads digits: speak numbers as words. Subtitles keep
        # turn.line as written (digits included).
        speech_line = expand_numbers_for_tts(turn.line, language)
        out = audio_dir / f"{turn.turn_id}.cbx.wav"
        meta = audio_dir / f"{turn.turn_id}.cbx.json"
        stamp_src = (f"cbx-v2|{language}|{speech_line}|{exaggeration}"
                     f"|{ref}|{ref.stat().st_mtime_ns}")
        stamp = hashlib.sha256(stamp_src.encode("utf-8")).hexdigest()
        if out.exists() and out.stat().st_size > 0 and meta.exists() \
                and meta.read_text(encoding="utf-8") == stamp:
            log(f"  chatterbox: {out.name} (cached)")
        else:
            job = jobs.setdefault(turn.speaker, {
                "speaker": turn.speaker, "ref": str(ref),
                "exaggeration": exaggeration, "files": []})
            job["files"].append([speech_line, str(out)])
            pending.append((turn, out, meta, stamp))
        turn.audio_path = out
        turn.word_timings = None

    if pending:
        spec = {"language": language, "jobs": list(jobs.values())}
        jobs_file = audio_dir / "_cbx_jobs.json"
        jobs_file.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        log(f"  chatterbox: sintetizando {len(pending)} líneas (GPU si hay; "
            "la 1.ª vez descarga el modelo ~3 GB)...")
        # Streamed (not subprocess.run(capture_output=True)): a single big
        # batch can take minutes on GPU, and a fully silent generator that
        # long makes Gradio's UI (especially through the Colab share tunnel)
        # drop the connection ("Connection to the server was lost..."). The
        # worker prints "synthesized: <path>" per line (flush=True); relay
        # each one so progress keeps flowing.
        by_path = {str(out): (turn, out, meta, stamp)
                  for turn, out, meta, stamp in pending}
        tail: list[str] = []
        proc = subprocess.Popen(
            [str(CHATTERBOX_PYTHON), str(_WORKER), str(jobs_file)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            tail.append(line)
            del tail[:-15]
            if line.startswith("synthesized: "):
                found = by_path.get(line[len("synthesized: "):])
                if found:
                    turn, out, meta, stamp = found
                    meta.write_text(stamp, encoding="utf-8")
                    log(f"  chatterbox: {out.name} ({turn.speaker})")
        proc.wait()
        if proc.returncode != 0:
            raise ChatterboxError(
                "Chatterbox synthesis failed:\n" + "\n".join(tail))
        for turn, out, meta, stamp in pending:
            if not out.exists() or out.stat().st_size == 0:
                raise ChatterboxError(f"No audio produced for {out.name}")

    for turn in turns:
        turn.audio_duration = probe_duration(ffprobe, turn.audio_path)
