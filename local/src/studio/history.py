"""Shared history: every modality's finished runs in one normalized shape.

Each modality keeps its own output folder and manifest; a reader turns one
run folder into:
  {modality, name, title, subtitle, created, mtime, duration, video_url,
   thumb_url, social, meta, reuse, delete_url}
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _finished_runs(output: Path):
    """(run_dir, final.mp4) for every finished run. Folders starting with "_"
    or "." are internals (caches, uploads, batches)."""
    if not output.is_dir():
        return
    for video in output.glob("*/final.mp4"):
        if not video.parent.name.startswith(("_", ".")):
            yield video.parent, video


def _url(prefix: str, output: Path, path: Path | None) -> str | None:
    if not path or not path.is_file():
        return None
    rel = path.resolve().relative_to(output.resolve()).as_posix()
    return f"{prefix}/{quote(rel)}?t={int(path.stat().st_mtime)}"


def _base(modality: str, run_dir: Path, video: Path, prefix: str,
          output: Path) -> dict:
    mtime = video.stat().st_mtime
    return {
        "modality": modality,
        "name": run_dir.name,
        "created": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
        "mtime": mtime,
        "video_url": _url(prefix, output, video),
        "social": _read_text(run_dir / "social.txt"),
        "thumb_url": None,
    }


def read_charla(modality: str, output: Path, prefix: str) -> list[dict]:
    """Conversación: output/<run>/manifest.json (Title, Input, Turns)."""
    runs = []
    for run_dir, video in _finished_runs(output):
        m = _read_json(run_dir / "manifest.json")
        turns = m.get("Turns") or []
        topic = (m.get("Input") or "").split("\n")[0].strip()
        runs.append({
            **_base(modality, run_dir, video, prefix, output),
            "title": m.get("Title") or run_dir.name,
            "subtitle": topic[:140],
            "duration": m.get("Total_Duration"),
            # another version = its form with the same topic pre-filled
            "reuse": ({"kind": "prefill", "input": topic}
                      if topic and not m.get("Script_File") else None),
            "meta": {"turnos": len(turns), "voz": m.get("TTS_Engine"),
                     "guion": m.get("Text_Model")},
        })
    return runs


def read_escalator(modality: str, output: Path, prefix: str) -> list[dict]:
    """Escalera: output/escalera/<run>/pipeline.json (Input_Phrase, Scenes)."""
    runs = []
    for run_dir, video in _finished_runs(output):
        m = _read_json(run_dir / "pipeline.json")
        scenes = m.get("Scenes") or []
        first_image = (scenes[0].get("Assets") or {}).get("image") if scenes else None
        run = {
            **_base(modality, run_dir, video, prefix, output),
            "title": m.get("Input_Phrase") or run_dir.name,
            "subtitle": " → ".join(s.get("Style", "") for s in scenes if s.get("Style"))[:140],
            "duration": m.get("Total_Duration"),
            # another version = escalator's own regenerate (same portrait and
            # phrase, everything from the text on is redone)
            "reuse": {"kind": "regenerate",
                      "url": f"/m/{modality}/api/history/{quote(run_dir.name)}/regenerate",
                      "body": {"force_from": "text"}},
            "meta": {"estilo": m.get("Style_Set"), "escenas": len(scenes),
                     "voz": m.get("TTS_Provider")},
        }
        if first_image:
            run["thumb_url"] = _url(prefix, output, run_dir / first_image)
        runs.append(run)
    return runs


def read_cuento(modality: str, output: Path, prefix: str) -> list[dict]:
    """Cuento: output/cuento/<run>/pipeline.json (Title, Premise, Tone, Scenes)."""
    from cuento.config import TONES   # labels only; lazy so the studio stays light
    runs = []
    for run_dir, video in _finished_runs(output):
        m = _read_json(run_dir / "pipeline.json")
        scenes = m.get("Scenes") or []
        first_image = (scenes[0].get("Assets") or {}).get("image") if scenes else None
        tone = TONES.get(m.get("Tone"), ("", "", {}))
        genre = tone[2].get(m.get("Genre"), ("", ""))[0]
        run = {
            **_base(modality, run_dir, video, prefix, output),
            "title": m.get("Title") or run_dir.name,
            "subtitle": " · ".join(x for x in (tone[0], genre, m.get("Premise", "")) if x)[:140],
            "duration": m.get("Total_Duration"),
            # another version = the story's own regenerate (same premise and
            # photo, a new story from the text on)
            "reuse": {"kind": "regenerate",
                      "url": f"/m/{modality}/api/history/{quote(run_dir.name)}/regenerate",
                      "body": {"force_from": "text"}},
            "meta": {"escenas": len(scenes), "tono": tone[0] or m.get("Tone"),
                     "voz": m.get("Voice"), "imágenes": m.get("Image_Provider")},
        }
        if m.get("Source"):
            run["meta"]["fuente"] = f"r/{m.get('Source_Subreddit')} · u/{m.get('Source_Author')}"
        if first_image:
            run["thumb_url"] = _url(prefix, output, run_dir / first_image)
        runs.append(run)
    return runs


def collect(modalities) -> list[dict]:
    """All finished runs of every modality, newest first. One unreadable
    modality folder never hides the others."""
    runs: list[dict] = []
    for mod in modalities:
        try:
            runs += mod.history(mod.id, mod.output, mod.media_route)
        except Exception:  # noqa: BLE001
            continue
    deletable = {m.id for m in modalities if m.can_delete}
    for run in runs:  # no image of its own: the studio extracts a frame
        run["thumb_url"] = run["thumb_url"] or f"/api/thumb/{run['modality']}/{quote(run['name'])}"
        run["delete_url"] = (f"/m/{run['modality']}/api/history/{quote(run['name'])}"
                             if run["modality"] in deletable else None)
    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return runs


def _ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")  # winget install while the PATH is stale
    hits = glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*",
                                  "**", "bin", "ffmpeg.exe"), recursive=True)
    return hits[0] if hits else None


def thumbnail(output: Path, name: str, cache: Path) -> Path:
    """A cached JPEG frame (1 s in) of output/<name>/final.mp4. `name` comes
    from the client: only a plain run folder name is accepted."""
    run_dir = output / name
    if (not name or name.startswith((".", "_")) or Path(name).name != name
            or run_dir.resolve().parent != output.resolve()):
        raise ValueError(f"invalid run name: {name!r}")
    video = run_dir / "final.mp4"
    if not video.is_file():
        raise FileNotFoundError(name)
    out = cache / f"{name}-{int(video.stat().st_mtime)}.jpg"
    if not out.is_file():
        ffmpeg = _ffmpeg()
        if not ffmpeg:
            raise FileNotFoundError("ffmpeg")
        cache.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.jpg")
        subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-y", "-ss", "1", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=270:-2", str(tmp)],
                       check=True, capture_output=True, timeout=30)
        tmp.replace(out)
    return out
