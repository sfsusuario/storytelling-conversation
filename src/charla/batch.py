"""Automatic batch: science topics -> several videos, end to end.

An optional mode on top of the normal pipeline (nothing in it changes):

  1. Topics: by default drawn from a bank of verified science facts
     (data/temas_ciencia.json, each with supporting details the scriptwriter
     can use), skipping the ones earlier batches already used
     (output/_lote/temas_usados.json). Optionally a local Ollama model
     proposes them instead — measured on small local models (gemma3:4b,
     gpt-oss:20b) most proposed "facts" were false, so review those.
  2. Each topic runs through the regular pipeline with the Ollama
     scriptwriter (script -> voice -> render), one after the other; a
     failed video is logged and the batch moves on.
  3. Deliverables land in output/_lote/<fecha>/: numbered videos
     ("01 - Titulo.mp4", hard links to each run's final.mp4), one .txt per
     video and publicar.txt with every title + caption + hashtags, ready to
     paste.

CLI: charla-lote --count 5   (see --help). The UI has the same feature in
its "Lote automático" section; run-lote.ps1 asks interactively.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ValidationError

from .config import (DEFAULT_BATCH_THEME, DEFAULT_LANGUAGE,
                     DEFAULT_OLLAMA_MODEL, DEFAULT_TTS_ENGINE, LANGUAGE_NAMES,
                     PipelineOptions)

BATCH_ROOT = Path("output") / "_lote"
_HISTORY = BATCH_ROOT / "temas_usados.json"
_BANK_FILE = Path(__file__).resolve().parent / "data" / "temas_ciencia.json"
_HISTORY_IN_PROMPT = 80   # recent topics shown to the model to avoid repeats

SOURCES = ("bank", "ollama")
Log = Callable[[str], None]


class BatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Topic:
    tema: str               # the fact, one sentence (also the video's topic)
    detalles: str = ""      # verified supporting facts for the scriptwriter
    area: str = ""

    @property
    def prompt(self) -> str:
        """What the scriptwriter receives as the source text."""
        return f"{self.tema}\n\n{self.detalles}" if self.detalles else self.tema


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _is_repeat(topic: str, seen: list[str]) -> bool:
    n = _normalize(topic)
    return not n or any(n == s or n in s or s in n for s in seen)


# ---------------------------------------------------------------------------
# History of used topics
# ---------------------------------------------------------------------------


def load_history() -> list[dict]:
    try:
        data = json.loads(_HISTORY.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _remember(topic: str, title: str, video: str) -> None:
    history = load_history()
    history.append({"topic": topic, "title": title, "video": video,
                    "date": datetime.now().isoformat(timespec="seconds")})
    BATCH_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = _HISTORY.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(_HISTORY)


def _used_topics(exclude: list[str] | None = None) -> list[str]:
    return [h.get("topic", "") for h in load_history()] + list(exclude or [])


# ---------------------------------------------------------------------------
# Topic sources
# ---------------------------------------------------------------------------


def load_bank() -> list[Topic]:
    try:
        data = json.loads(_BANK_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BatchError(f"Cannot read the topic bank {_BANK_FILE}: {e}") from e
    return [Topic(d["tema"].strip(), d.get("detalles", "").strip(),
                  d.get("area", "").strip()) for d in data if d.get("tema")]


def find_bank_topic(text: str) -> Topic | None:
    """The bank fact whose headline is exactly `text` (ignoring case,
    accents and punctuation), so its verified details can be attached."""
    n = _normalize(text)
    if not n:
        return None
    try:
        return next((t for t in load_bank() if _normalize(t.tema) == n), None)
    except BatchError:
        return None


def bank_areas() -> list[str]:
    try:
        return sorted({t.area for t in load_bank() if t.area})
    except BatchError:
        return []


ALL_AREAS = "(todas)"
AREA_ICONS = {
    "animales": "🐾", "biología": "🧬", "genética": "🧬", "botánica": "🌱",
    "paleontología": "🦈", "cuerpo humano": "🫀", "astronomía": "🔭",
    "espacio": "🚀", "física": "⚡", "química": "⚗️", "geología": "🌋",
    "geografía": "🗺️", "ecología": "🌊", "historia de la ciencia": "📜",
    "tecnología": "💻", "matemáticas": "🔢",
}
IDEAS_PER_ROUND = 8


def idea_choices(source: str, area: str, model: str | None,
                 exclude: list[str]) -> list[tuple[str, str]]:
    """(label, topic) pairs for the idea pickers (Gradio and web): verified
    bank facts, or fresh ideas from Ollama. A round that runs out of unseen
    bank facts starts over instead of coming back empty."""
    from .script_gen import model_for

    area = (area or "").strip()
    theme = DEFAULT_BATCH_THEME if area in ("", ALL_AREAS) else area
    model = model_for("ollama", model)

    def draw(excluded: list[str]):
        return generate_topics(IDEAS_PER_ROUND, source, theme, model,
                               DEFAULT_LANGUAGE, exclude=excluded,
                               log=lambda *_: None)
    try:
        topics = draw(exclude)
    except BatchError:
        if not exclude:
            raise
        topics = draw([])
    unverified = "  (sin verificar)" if source == "ollama" else ""
    return [(f"{AREA_ICONS.get(t.area.lower(), '💡')} {t.tema}{unverified}",
             t.tema) for t in topics]


def bank_topics(count: int, theme: str = DEFAULT_BATCH_THEME,
                exclude: list[str] | None = None,
                log: Log = print) -> list[Topic]:
    """`count` unused facts from the verified bank, spread across areas.
    A theme that names an area (e.g. "astronomía") puts that area first."""
    seen = [_normalize(t) for t in _used_topics(exclude) if t]
    free = [t for t in load_bank() if not _is_repeat(t.tema, seen)]
    if not free:
        raise BatchError(
            "Every topic in the verified bank was already used. Use "
            "--source ollama (review the facts!) or delete "
            f"{_HISTORY} to start over.")
    random.shuffle(free)
    theme_n = _normalize(theme)
    preferred = [t for t in free
                 if t.area and _normalize(t.area) in theme_n]
    # round-robin over areas so one batch mixes disciplines
    by_area: dict[str, list[Topic]] = {}
    for t in free:
        if t not in preferred:
            by_area.setdefault(t.area, []).append(t)
    mixed: list[Topic] = []
    while any(by_area.values()):
        for area in list(by_area):
            if by_area[area]:
                mixed.append(by_area[area].pop())
    picked = (preferred + mixed)[:count]
    if len(picked) < count:
        log(f"  temas: quedan solo {len(picked)} sin usar en el banco")
    return picked


class _OllamaTopic(BaseModel):
    topic: str     # the fact itself, one sentence
    area: str      # discipline, used to keep the batch varied


class _OllamaTopicList(BaseModel):
    topics: list[_OllamaTopic]


_TOPICS_SYSTEM = """\
Eres editor de un canal de divulgación científica en video corto
(TikTok/Reels/Shorts). Propones temas para conversaciones cómicas entre un
científico genio y su ayudante.

Cada tema es UN dato real, concreto y sorprendente, escrito como una frase
de 8 a 20 palabras con un detalle específico (un número, un nombre, una
comparación). Reglas:
- Solo hechos establecidos y verificables (libros de texto, enciclopedias,
  NASA, OMS...). Nada de mitos populares, curiosidades dudosas, récords
  discutidos ni "se dice que". Si no estás seguro de una cifra, no la uses.
- Variedad: cada tema de un área distinta cuando sea posible (biología,
  astronomía, física, química, cuerpo humano, geología, tecnología,
  matemáticas, animales, historia de la ciencia...).
- Nada repetido ni parafraseado de la lista de temas ya usados.
- El campo area es el área del tema en una o dos palabras.
- Todo en {language}.
"""


def ollama_topics(count: int, theme: str = DEFAULT_BATCH_THEME,
                  model: str = DEFAULT_OLLAMA_MODEL,
                  language: str = DEFAULT_LANGUAGE,
                  exclude: list[str] | None = None,
                  log: Log = print) -> list[Topic]:
    """`count` new topics proposed by an Ollama model. Small local models
    invent figures: these need a human check before publishing."""
    from .script_gen import ScriptGenError, _ollama_chat, resolve_text_backend

    try:
        _, model = resolve_text_backend("ollama", model)
    except ScriptGenError as e:
        raise BatchError(str(e)) from e
    used = _used_topics(exclude)
    seen = [_normalize(t) for t in used if t]
    system = _TOPICS_SYSTEM.format(
        language=LANGUAGE_NAMES.get(language, language))
    topics: list[Topic] = []
    for attempt in range(3):          # top up if dedupe left us short
        missing = count - len(topics)
        if missing <= 0:
            break
        recent = (used + [t.tema for t in topics])[-_HISTORY_IN_PROMPT:]
        user = (f"Tema general: {theme.strip() or DEFAULT_BATCH_THEME}\n"
                f"Propón {missing + 2} temas distintos.")
        if recent:
            user += "\n\nYa usados (no repetir):\n" + "\n".join(
                f"- {t}" for t in recent)
        log(f"  temas: pidiendo {missing + 2} a {model}...")
        try:
            data = _OllamaTopicList.model_validate_json(
                _ollama_chat(model, system, user, _OllamaTopicList))
        except ValidationError as e:
            if attempt == 2:
                raise BatchError(f"{model} returned an invalid topic list: "
                                 f"{str(e).splitlines()[0]}") from e
            continue
        except ScriptGenError as e:
            raise BatchError(str(e)) from e
        for item in data.topics:
            tema = " ".join(item.topic.split()).strip(" -•")
            if len(tema.split()) < 4 or _is_repeat(tema, seen):
                continue
            topics.append(Topic(tema, area=item.area.strip()))
            seen.append(_normalize(tema))
            if len(topics) == count:
                break
    if not topics:
        raise BatchError(f"{model} did not propose any usable new topic")
    if len(topics) < count:
        log(f"  temas: solo {len(topics)} nuevos (sin repetir) de {count}")
    log("  aviso: temas inventados por un modelo local — revisa que los "
        "datos sean ciertos antes de publicar")
    return topics


def generate_topics(count: int, source: str = "bank",
                    theme: str = DEFAULT_BATCH_THEME,
                    model: str = DEFAULT_OLLAMA_MODEL,
                    language: str = DEFAULT_LANGUAGE,
                    exclude: list[str] | None = None,
                    log: Log = print) -> list[Topic]:
    if count < 1:
        raise BatchError("count must be at least 1")
    if source == "bank":
        return bank_topics(count, theme, exclude, log=log)
    if source == "ollama":
        return ollama_topics(count, theme, model, language, exclude, log=log)
    raise BatchError(f"Unknown topic source '{source}' (bank or ollama)")


def topics_from_lines(lines: list[str]) -> list[Topic]:
    """User-edited topics (one per line, optional "01." numbering). Lines
    that match a bank fact get its verified details attached."""
    bank = {_normalize(t.tema): t for t in load_bank()}
    topics = []
    for line in lines:
        line = re.sub(r"^\s*\d+[.)]\s*", "", line).strip(" -•\t")
        if not line or line.startswith("#"):
            continue
        topics.append(bank.get(_normalize(line), Topic(line)))
    return topics


# ---------------------------------------------------------------------------
# Batch run
# ---------------------------------------------------------------------------


@dataclass
class BatchItem:
    index: int
    topic: str
    ok: bool = False
    title: str = ""
    social: str = ""
    video: str = ""            # deliverable in the batch folder
    output_dir: str = ""       # the regular run folder (script, audio, clips)
    seconds: float = 0.0
    error: str = ""


@dataclass
class BatchResult:
    folder: Path
    items: list[BatchItem] = field(default_factory=list)
    publish_text: str = ""

    @property
    def ok_count(self) -> int:
        return sum(1 for i in self.items if i.ok)


def _error_summary(error: Exception) -> str:
    """The informative part of an error: ffmpeg failures put the real
    cause on the lines after "ffmpeg failed (exit N):", and end with the
    (huge) command line, which is dropped."""
    text = str(error).split("\ncommand:", 1)[0].strip() or repr(error)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return " | ".join(lines[:3])[:500]


def _safe_filename(text: str, limit: int = 60) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text)
    text = " ".join(text.split()).strip(" .")
    return text[:limit].rstrip(" .") or "video"


def _publish_block(item: BatchItem) -> str:
    return (f"{item.index:02d} · {item.title}\n"
            f"Video: {Path(item.video).name}\n\n"
            f"TÍTULO\n{item.title}\n\n"
            f"DESCRIPCIÓN\n{item.social.strip()}\n")


def _link_or_copy(src: Path, dst: Path) -> None:
    """Hard link (free, same disk) with a copy fallback."""
    dst.unlink(missing_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _write_outputs(result: BatchResult, topics: list[Topic]) -> None:
    folder = result.folder
    (folder / "temas.txt").write_text(
        "\n".join(f"{i:02d}. {t.tema}" for i, t in enumerate(topics, 1))
        + "\n", encoding="utf-8")
    ok = [i for i in result.items if i.ok]
    sep = "\n" + "─" * 40 + "\n\n"
    result.publish_text = sep.join(_publish_block(i) for i in ok)
    (folder / "publicar.txt").write_text(result.publish_text,
                                          encoding="utf-8")
    (folder / "lote.json").write_text(json.dumps(
        {"folder": str(folder), "items": [asdict(i) for i in result.items]},
        ensure_ascii=False, indent=2), encoding="utf-8")


def run_batch(count: int = 3, theme: str = DEFAULT_BATCH_THEME,
              model: str = DEFAULT_OLLAMA_MODEL,
              tts_engine: str = DEFAULT_TTS_ENGINE,
              language: str = DEFAULT_LANGUAGE, source: str = "bank",
              topics: list[Topic] | None = None, dry_run: bool = False,
              log: Log = print,
              should_stop: Callable[[], bool] = lambda: False
              ) -> BatchResult:
    """Topics (given, or drawn from `source`) -> one video each, in order.

    Scripts are always written by the Ollama `model`. `should_stop` is
    polled before each video (UI "stop" button). Outputs are rewritten
    after every video, so an interrupted batch still leaves publicar.txt
    with what was finished.
    """
    from .pipeline import run_pipeline
    from .script_gen import ScriptGenError, resolve_text_backend

    try:
        _, model = resolve_text_backend("ollama", model)
    except ScriptGenError as e:
        raise BatchError(str(e)) from e
    if not topics:
        origin = ("banco verificado" if source == "bank"
                  else f"generados por {model}")
        log(f"[temas] {count} temas ({origin})")
        topics = generate_topics(count, source, theme, model, language,
                                 log=log)
    folder = BATCH_ROOT / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    log(f"lote: {folder}")
    for i, t in enumerate(topics, 1):
        log(f"  {i:02d}. {t.tema}")

    result = BatchResult(folder)
    _write_outputs(result, topics)
    for index, topic in enumerate(topics, 1):
        if should_stop():
            log("lote: detenido por el usuario")
            break
        item = BatchItem(index, topic.tema)
        result.items.append(item)
        log(f"\n[video {index}/{len(topics)}] {topic.tema}")
        started = time.monotonic()
        # Just the headline: the pipeline attaches a bank fact's verified
        # details itself, so simple mode and batches share folder and cache.
        options = PipelineOptions(
            input_text=topic.tema, language=language,
            tts_engine=tts_engine, text_provider="ollama", text_model=model,
            dry_run=dry_run)
        try:
            run = run_pipeline(options, on_progress=lambda m: log(f"  {m}"))
        except Exception as e:  # one bad topic must not sink the batch
            item.error = _error_summary(e)
            item.seconds = round(time.monotonic() - started, 1)
            log(f"  ✗ falló: {item.error}")
            _write_outputs(result, topics)
            continue
        item.title = run.title.strip() or topic.tema
        item.social = run.social or ""
        item.output_dir = str(run.output_dir)
        name = f"{index:02d} - {_safe_filename(item.title)}"
        if run.final_video:
            target = folder / f"{name}.mp4"
            _link_or_copy(Path(run.final_video), target)
            item.video = str(target)
        else:                                  # dry run: no media
            item.video = str(run.output_dir / "manifest.json")
        (folder / f"{name}.txt").write_text(
            f"{item.title}\n\n{item.social.strip()}\n", encoding="utf-8")
        item.ok = True
        item.seconds = round(time.monotonic() - started, 1)
        if not dry_run:
            _remember(topic.tema, item.title, item.video)
        log(f"  ✓ {name} ({item.seconds:.0f}s)")
        _write_outputs(result, topics)

    failed = [i for i in result.items if not i.ok]
    log(f"\nlote terminado: {result.ok_count}/{len(result.items)} videos"
        + (f", {len(failed)} con error" if failed else "")
        + f" — {folder / 'publicar.txt'}")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="charla-lote",
        description="Automatic batch: science topics -> one video per topic "
                    "(scripts by a local Ollama model), plus publicar.txt "
                    "with titles/captions/hashtags to paste.")
    p.add_argument("--count", "-n", type=int, default=3,
                   help="How many videos (default 3)")
    p.add_argument("--source", choices=SOURCES, default="bank",
                   help="Where topics come from: bank (default: verified "
                        "facts shipped with charla, never repeated) or "
                        "ollama (proposed by the model — small local models "
                        "often invent figures, review them)")
    p.add_argument("--theme", default=DEFAULT_BATCH_THEME,
                   help="General theme (ollama source; with the bank, an "
                        "area name such as 'astronomía' goes first)")
    p.add_argument("--model", default=DEFAULT_OLLAMA_MODEL,
                   help=f"Ollama model for the scripts (and ollama topics); "
                        f"default {DEFAULT_OLLAMA_MODEL}")
    p.add_argument("--tts", dest="tts_engine",
                   choices=["edge", "xtts", "chatterbox"], default=None,
                   help=f"Voice engine (default {DEFAULT_TTS_ENGINE})")
    p.add_argument("--language", default=DEFAULT_LANGUAGE,
                   help=f"Language (default '{DEFAULT_LANGUAGE}')")
    p.add_argument("--topics-file", type=Path, default=None,
                   help="Use these topics (one per line) instead of "
                        "drawing them")
    p.add_argument("--only-topics", action="store_true",
                   help="Only pick topics: print them and save "
                        "output/_lote/temas_propuestos.txt (edit it and pass "
                        "it back with --topics-file)")
    p.add_argument("--dry-run", action="store_true",
                   help="Scripts only, no audio/video")
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be at least 1")

    topics = None
    if args.topics_file:
        try:
            lines = args.topics_file.read_text(encoding="utf-8-sig").splitlines()
        except OSError as e:
            parser.error(f"cannot read {args.topics_file}: {e}")
        topics = topics_from_lines(lines)
        if not topics:
            parser.error(f"{args.topics_file} has no topics")

    try:
        if args.only_topics:
            found = generate_topics(args.count, args.source, args.theme,
                                    args.model, args.language)
            text = "\n".join(f"{i:02d}. {t.tema}"
                             for i, t in enumerate(found, 1))
            BATCH_ROOT.mkdir(parents=True, exist_ok=True)
            out = BATCH_ROOT / "temas_propuestos.txt"
            out.write_text(text + "\n", encoding="utf-8")
            print(text)
            print(f"\n(guardado en {out}; edítalo y úsalo con --topics-file)")
            return 0
        result = run_batch(
            count=args.count, theme=args.theme, model=args.model,
            tts_engine=args.tts_engine or DEFAULT_TTS_ENGINE,
            language=args.language, source=args.source, topics=topics,
            dry_run=args.dry_run)
    except BatchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nlote interrumpido", file=sys.stderr)
        return 130
    if result.publish_text:
        print("\n--- publicar.txt ---\n" + result.publish_text)
    return 0 if result.ok_count == len(result.items) else 2


if __name__ == "__main__":
    sys.exit(main())
