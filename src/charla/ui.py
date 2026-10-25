from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path

from .config import (BACKGROUNDS_DIR, CHARACTERS, DEFAULT_BATCH_THEME,
                     DEFAULT_BG_VOLUME,
                     DEFAULT_CHAR_SCALE,
                     DEFAULT_CHROMA_BLEND, DEFAULT_CHROMA_SIMILARITY,
                     DEFAULT_FPS, DEFAULT_GEMINI_TEXT_MODEL, DEFAULT_HEIGHT,
                     DEFAULT_LANGUAGE, DEFAULT_MAX_TURNS, DEFAULT_MIN_TURNS,
                     DEFAULT_OLLAMA_MODEL, DEFAULT_TEXT_MODEL,
                     DEFAULT_TTS_ENGINE, DEFAULT_WATERMARK, DEFAULT_WIDTH,
                     LANGUAGE_NAMES, PipelineOptions)

_AUTO_PROVIDER = "auto (Claude → Gemini → Ollama)"
# Families that abort with "token repeat limit" on the long script prompt
# on Intel iGPUs (measured with Ollama 0.40); flagged in the model list.
_OLLAMA_FLAKY = ("llama3.1", "qwen3")

_DEMO_SCRIPT = Path("examples/demo_script.json")

# Any edge-tts voice works; these are sensible picks for each role.
# Defaults approximate the show's Latin American dub (Rick: Juan Guzmán,
# Morty: Eder La Barrera); es-ES-AlvaroNeural leans Castilian (Txema
# Moscoso). Samples to audition: voices_preview/ (README).
_RICK_VOICES = ["es-MX-JorgeNeural", "es-ES-AlvaroNeural",
                "es-VE-SebastianNeural", "es-CO-GonzaloNeural",
                "es-AR-TomasNeural", "en-US-ChristopherNeural"]
_MORTY_VOICES = ["es-US-AlonsoNeural", "es-CR-JuanNeural", "es-PE-AlexNeural",
                 "es-MX-JorgeNeural", "es-SV-RodrigoNeural",
                 "en-US-GuyNeural"]


def _fmt_mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _eta_html(elapsed: float, estimate: float | None,
              done: bool = False) -> str:
    """Global time progress: elapsed counter + remaining estimate bar."""
    if done:
        pct, color = 100.0, "#22c55e"
        label = f"✅ Completado en {_fmt_mmss(elapsed)}"
    elif estimate and estimate > 0:
        pct = min(99.0, 100.0 * elapsed / estimate)
        color = "#3b82f6"
        label = (f"⏱ {_fmt_mmss(elapsed)} transcurridos — "
                 f"~{_fmt_mmss(estimate - elapsed)} restantes "
                 f"(estimado {_fmt_mmss(estimate)})")
    else:
        pct, color = 100.0, "#94a3b8"
        label = (f"⏱ {_fmt_mmss(elapsed)} transcurridos — sin estimación "
                 "aún (primer video con este motor de voz)")
    return (
        '<div style="font-family:sans-serif">'
        f'<div style="margin-bottom:4px;font-size:0.95em">{label}</div>'
        '<div style="background:#e5e7eb;border-radius:6px;height:14px;'
        'overflow:hidden">'
        f'<div style="width:{pct:.1f}%;height:100%;background:{color};'
        'border-radius:6px;transition:width 1s linear"></div>'
        "</div></div>")


def _tiktok_bar_html(label: str, pct: float,
                     color: str = "#3b82f6") -> str:
    """Barra de la subida a TikTok (mismo estilo que la barra global)."""
    return (
        '<div style="font-family:sans-serif">'
        f'<div style="margin-bottom:4px;font-size:0.95em">{label}</div>'
        '<div style="background:#e5e7eb;border-radius:6px;height:14px;'
        'overflow:hidden">'
        f'<div style="width:{pct:.1f}%;height:100%;background:{color};'
        'border-radius:6px;transition:width 0.3s linear"></div>'
        "</div></div>")


_DING_CACHE: dict = {}


def _ding_html() -> str:
    """<audio autoplay> with an embedded two-tone ding (pure stdlib wav)."""
    if "uri" not in _DING_CACHE:
        import base64
        import io
        import math
        import struct
        import wave

        sr = 22050
        frames = bytearray()
        for i in range(int(sr * 0.9)):
            t = i / sr
            env = math.exp(-3.5 * t)
            s = 0.45 * env * (math.sin(2 * math.pi * 880 * t)
                              + 0.6 * math.sin(2 * math.pi * 1318.5 * t))
            frames += struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(bytes(frames))
        _DING_CACHE["uri"] = ("data:audio/wav;base64,"
                              + base64.b64encode(buf.getvalue()).decode())
    return f'<audio autoplay src="{_DING_CACHE["uri"]}"></audio>'


def _language_label(code: str) -> str:
    return f"{code} — {LANGUAGE_NAMES.get(code, code)}"


def _language_choices() -> list[str]:
    codes = list(LANGUAGE_NAMES)
    if DEFAULT_LANGUAGE not in codes:   # e.g. CHARLA_LANGUAGE=ca
        codes.insert(0, DEFAULT_LANGUAGE)
    return [_language_label(code) for code in codes]


# idea picker helpers live in batch.py (shared with the web UI)
from .batch import ALL_AREAS as _ALL_AREAS  # noqa: E402
from .batch import bank_areas as _bank_areas  # noqa: E402
from .batch import idea_choices as _idea_choices  # noqa: E402


def _model_choices(provider: str, current: str | None):
    """(choices, value) of the text-model dropdown for a provider."""
    provider = str(provider).split(" ")[0]
    current = (current or "").strip()
    if provider == "ollama":
        from .script_gen import list_ollama_models
        models = list_ollama_models() or []
        names = [DEFAULT_OLLAMA_MODEL] + [m for m in models
                                          if m != DEFAULT_OLLAMA_MODEL]
        choices = [(f"{m}  ⚠ puede fallar con prompts largos"
                    if m.startswith(_OLLAMA_FLAKY) else m, m) for m in names]
        value = current if current in names else DEFAULT_OLLAMA_MODEL
        return choices, value, models is not None and bool(models)
    if provider == "gemini":
        value = current if current.startswith("gemini") \
            else DEFAULT_GEMINI_TEXT_MODEL
        return [DEFAULT_GEMINI_TEXT_MODEL], value, True
    if provider == "claude":
        value = current if current.startswith("claude") else DEFAULT_TEXT_MODEL
        return [DEFAULT_TEXT_MODEL], value, True
    # auto: keep whatever is there (a non-claude/gemini name means Ollama)
    return ([DEFAULT_TEXT_MODEL, DEFAULT_GEMINI_TEXT_MODEL,
             DEFAULT_OLLAMA_MODEL], current or DEFAULT_TEXT_MODEL, True)


def _history_runs() -> list[tuple[str, str]]:
    """(label, video_path) for every finished run under output/, newest first."""
    import json
    from datetime import datetime

    runs = []
    for video in Path("output").glob("*/final.mp4"):
        label = video.parent.name
        try:
            manifest = json.loads(
                (video.parent / "manifest.json").read_text(encoding="utf-8"))
            when = datetime.fromtimestamp(video.stat().st_mtime)
            label = (f'{when:%d/%m %H:%M} — "{manifest.get("Title", "?")}" '
                     f'({manifest.get("Total_Duration", "?")}s, '
                     f'{len(manifest.get("Turns", []))} turnos) '
                     f'[{video.parent.name}]')
        except (OSError, json.JSONDecodeError):
            pass
        runs.append((video.stat().st_mtime, label, str(video)))
    runs.sort(reverse=True)
    return [(label, path) for _, label, path in runs]


def _load_history_run(video_path: str | None):
    import json

    if not video_path:
        return None, ""
    run_dir = Path(video_path).parent
    details = [f"Carpeta: {run_dir.resolve()}"]
    try:
        m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        details = [
            f'Título:    "{m.get("Title")}"',
            f"Idioma: {m.get('Language')}   Duración: {m.get('Total_Duration')}s",
            "Diálogo:",
            *(f'  {t.get("Speaker")} [{t.get("Emotion")}]: "{t.get("Line")}"'
              for t in m.get("Turns", [])),
            f"Carpeta:   {run_dir.resolve()}",
        ]
    except (OSError, json.JSONDecodeError):
        pass
    social_file = run_dir / "social.txt"
    if social_file.exists():
        details.append("\n" + social_file.read_text(encoding="utf-8"))
    return video_path, "\n".join(details)


def build_app():
    import gradio as gr

    def _render_fields(subtitles, watermark, bg_enabled, bg_volume, use_rvc,
                       tts_engine, rick_voice, rick_rate, rick_pitch,
                       morty_voice, morty_rate, morty_pitch, resolution, fps,
                       chroma_similarity, chroma_blend, char_scale) -> dict:
        """Render/voice controls -> PipelineOptions fields (all of them in
        pipeline.RENDER_FIELDS). The single place that parses them: used
        when writing the script and again on approve, so edits made in
        between are honoured."""
        try:
            width, height = (int(x) for x in str(resolution).lower().split("x"))
        except ValueError:
            raise gr.Error(f"Resolución inválida '{resolution}', formato AnchoxAlto")
        return dict(
            width=width, height=height, fps=int(fps),
            watermark=(watermark or "").strip(),
            subtitles=bool(subtitles),
            bg_volume=float(bg_volume or 0.0) if bg_enabled else 0.0,
            tts_engine=str(tts_engine),
            rvc="on" if use_rvc else "off",
            chroma_similarity=float(chroma_similarity),
            chroma_blend=float(chroma_blend),
            char_scale=float(char_scale),
            rick_voice=rick_voice or None,
            rick_rate=(rick_rate or "").strip() or None,
            rick_pitch=(rick_pitch or "").strip() or None,
            morty_voice=morty_voice or None,
            morty_rate=(morty_rate or "").strip() or None,
            morty_pitch=(morty_pitch or "").strip() or None,
        )

    def _build_options(topic, use_demo, language, max_turns, subtitles,
                       watermark, bg_enabled, bg_volume, use_rvc, tts_engine,
                       text_provider, rick_voice, rick_rate, rick_pitch,
                       morty_voice, morty_rate, morty_pitch,
                       resolution, fps, chroma_similarity, chroma_blend,
                       char_scale, text_model, force, output_dir,
                       feedback=""):
        topic = (topic or "").strip()
        if not use_demo and not topic:
            raise gr.Error("Escribe un tema o URL de noticia (o marca "
                           "'Guion de ejemplo' para probar sin LLM).")
        # No API-key check here: a cached script needs none and Ollama
        # needs none at all; the pipeline raises a clear error otherwise.
        return PipelineOptions(
            input_text="" if use_demo else topic,
            script_file=_DEMO_SCRIPT if use_demo else None,
            script_feedback="" if use_demo else (feedback or "").strip(),
            language=str(language).split(" ")[0],
            max_turns=int(max_turns),
            min_turns=min(DEFAULT_MIN_TURNS, int(max_turns)),
            output_dir=Path(output_dir) if output_dir else None,
            force=bool(force),
            text_provider=str(text_provider).split(" ")[0],
            text_model=(text_model or "").strip() or DEFAULT_TEXT_MODEL,
            **_render_fields(subtitles, watermark, bg_enabled, bg_volume,
                             use_rvc, tts_engine, rick_voice, rick_rate,
                             rick_pitch, morty_voice, morty_rate,
                             morty_pitch, resolution, fps, chroma_similarity,
                             chroma_blend, char_scale),
        )

    def generate_script(topic, use_demo, language, max_turns, subtitles,
                        watermark, bg_enabled, bg_volume, use_rvc, tts_engine,
                        text_provider, rick_voice, rick_rate, rick_pitch,
                        morty_voice, morty_rate, morty_pitch,
                        resolution, fps, chroma_similarity, chroma_blend,
                        char_scale, text_model, force, output_dir, feedback,
                        progress=gr.Progress()):
        """Stage 1 only: write the dialogue and stop for the user to review
        it (approve, or ask for a different one) before any voice/render
        work happens."""
        options = _build_options(
            topic, use_demo, language, max_turns, subtitles, watermark,
            bg_enabled, bg_volume, use_rvc, tts_engine, text_provider,
            rick_voice, rick_rate, rick_pitch, morty_voice, morty_rate,
            morty_pitch, resolution, fps, chroma_similarity, chroma_blend,
            char_scale, text_model, force, output_dir, feedback)

        from .pipeline import generate_script_stage

        lines: list[str] = []
        progress(0.2, desc="Generando guion...")
        try:
            draft = generate_script_stage(options, on_progress=lines.append)
        except Exception as e:
            raise gr.Error(str(e))
        progress(1.0, desc="Guion listo")

        dialogue = "\n".join(
            f'{t.speaker} [{t.emotion}]: "{t.line}"' for t in draft.turns)
        review = f'Título: "{draft.script["title"]}"\n\n{dialogue}'
        return draft, review, "\n".join(lines), gr.update(visible=True)

    def approve_and_render(draft, upload_tiktok, subtitles, watermark,
                           bg_enabled, bg_volume, use_rvc, tts_engine,
                           rick_voice, rick_rate, rick_pitch, morty_voice,
                           morty_rate, morty_pitch, resolution, fps,
                           chroma_similarity, chroma_blend, char_scale,
                           progress=gr.Progress()):
        """Stages 2-4 for the script the user already approved in the
        review step, plus the optional TikTok draft upload at the end.

        Render/voice controls are read again here: changes made after
        "Generar guion" apply to this render (the stored draft itself is
        never mutated)."""
        if draft is None:
            raise gr.Error("Primero genera (y revisa) un guion.")

        from .pipeline import continue_pipeline, with_render_options
        from .timings import engine_key, estimate_seconds

        try:
            draft = with_render_options(draft, **_render_fields(
                subtitles, watermark, bg_enabled, bg_volume, use_rvc,
                tts_engine, rick_voice, rick_rate, rick_pitch, morty_voice,
                morty_rate, morty_pitch, resolution, fps, chroma_similarity,
                chroma_blend, char_scale))
        except gr.Error:
            raise
        except Exception as e:
            raise gr.Error(str(e))

        q: queue.Queue = queue.Queue()
        holder: dict = {}

        def worker():
            try:
                holder["result"] = continue_pipeline(draft, on_progress=q.put)
            except Exception as e:  # surfaced as gr.Error below
                holder["error"] = e
            finally:
                q.put(None)

        threading.Thread(target=worker, daemon=True).start()

        # Two independent progress signals:
        # - gr.Progress: stage/event based (coarse position + per-turn fills)
        # - eta bar: global time counter + remaining estimate from the
        #   recorded duration of past runs (output/_timings.json)
        import re
        turn_total = len(draft.turns)
        # one audio line per turn and engine pass (edge + RVC = two)
        audio_total = turn_total * (2 if draft.use_rvc else 1)
        estimate = estimate_seconds(
            engine_key(draft.options.tts_engine, draft.use_rvc), turn_total)
        started = time.monotonic()
        lines: list[str] = []
        audio_done = clip_done = 0
        frac = 0.0
        progress(0.0, desc="Iniciando...")
        finished = False
        while not finished:
            try:
                item = q.get(timeout=1.0)
            except queue.Empty:
                # No pipeline event this second: refresh only the time bar.
                yield (gr.skip(), gr.skip(), gr.skip(), gr.skip(),
                       _eta_html(time.monotonic() - started, estimate),
                       gr.skip(), gr.skip())
                continue
            if item is None:
                finished = True
                continue
            msg = str(item)
            lines.append(msg)
            if msg.startswith("[2/4]"):
                frac = max(frac, 0.05)
            elif msg.startswith("[3/4]"):
                frac = max(frac, 0.57)
            elif msg.startswith("[4/4]"):
                frac = max(frac, 0.60)
            if turn_total:
                if re.match(r"^  (tts|rvc|xtts|chatterbox): turn_\d+", msg):
                    audio_done += 1
                    frac = max(frac, 0.05 + 0.50
                               * min(1.0, audio_done / audio_total))
                elif re.match(r"^  clip:", msg):
                    clip_done += 1
                    frac = max(frac, 0.60 + 0.38
                               * min(1.0, clip_done / turn_total))
            if msg.startswith("done:"):
                frac = 1.0
            progress(frac, desc=msg.strip()[:70])
            yield ("\n".join(lines), None, gr.skip(), gr.skip(),
                   _eta_html(time.monotonic() - started, estimate),
                   gr.skip(), gr.skip())

        if "error" in holder:
            raise gr.Error(str(holder["error"]))
        result = holder["result"]
        dialogue = "\n".join(
            f'  {t.speaker} [{t.emotion}]: "{t.line}"' for t in result.turns)
        summary = (f'Título: "{result.title}"\n{dialogue}\n\n'
                   f"Carpeta:    {result.output_dir.resolve()}\n"
                   f"Manifiesto: {result.manifest_path.resolve()}")
        lines.append("¡listo!")
        yield ("\n".join(lines), str(result.final_video), summary,
               result.social or "",
               _eta_html(time.monotonic() - started, estimate, done=True),
               _ding_html(), "")

        if not (upload_tiktok and result.final_video):
            return

        # Fase extra: subida a TikTok en modo draft, con su propia barra
        # (bytes reales vía on_bytes; el estado de publish llega por log).
        from . import tiktok as tt

        uq: queue.Queue = queue.Queue()
        upload_holder: dict = {}

        def uploader():
            try:
                token = tt.get_token("video.upload", interactive=False)
                pid = tt.upload_draft(
                    token, Path(result.final_video),
                    log=lambda m: uq.put(("log", str(m))),
                    on_bytes=lambda s, t: uq.put(("bytes", s, t)))
                tt.wait_publish(token, pid,
                                log=lambda m: uq.put(("log", str(m))))
            except Exception as e:  # shown in the red bar below
                upload_holder["error"] = e
            finally:
                uq.put(None)

        threading.Thread(target=uploader, daemon=True).start()
        lines.append("[5/5] subiendo a TikTok (borrador)")
        yield ("\n".join(lines),) + (gr.skip(),) * 5 + (
            _tiktok_bar_html("Conectando con TikTok...", 0.0),)

        mb = 1024 * 1024
        up_done = False
        while not up_done:
            try:
                items = [uq.get(timeout=0.5)]
            except queue.Empty:
                continue
            while True:  # coalesce backlog: one UI update per batch
                try:
                    items.append(uq.get_nowait())
                except queue.Empty:
                    break
            bar, log_dirty = gr.skip(), False
            for item in items:
                if item is None:
                    up_done = True
                elif item[0] == "bytes":
                    _, sent, total = item
                    bar = _tiktok_bar_html(
                        f"Subiendo a TikTok... {sent / mb:.1f} / "
                        f"{total / mb:.1f} MB", 100.0 * sent / max(1, total))
                else:
                    lines.append("  " + item[1].strip())
                    log_dirty = True
                    if "estado:" in item[1]:
                        bar = _tiktok_bar_html("Procesando en TikTok...",
                                               100.0)
            yield ("\n".join(lines) if log_dirty else gr.skip(),
                   gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip(), bar)

        if "error" in upload_holder:
            lines.append(f"tiktok: error — {upload_holder['error']}")
            yield ("\n".join(lines),) + (gr.skip(),) * 5 + (
                _tiktok_bar_html(f"❌ {upload_holder['error']}", 100.0,
                                 "#ef4444"),)
        else:
            lines.append("tiktok: video en tu bandeja — publícalo desde la app")
            yield ("\n".join(lines),) + (gr.skip(),) * 5 + (
                _tiktok_bar_html(
                    "✅ En tu bandeja de TikTok — abre la app en el teléfono "
                    "para publicarlo (caption lista en 📣)", 100.0,
                    "#22c55e"),)

    rick, morty = CHARACTERS["rick"], CHARACTERS["morty"]
    with gr.Blocks(title="Charla — conversaciones en video") as demo:
        draft_state = gr.State(None)
        gr.Markdown(
            "# 🎭 Charla\n"
            "Tema libre o **URL de noticia** → conversación cómica entre dos "
            "personajes (genio mayor / ayudante niño) en video vertical, con "
            "voces TTS y emociones por turno. Los valores por defecto "
            "funcionan tal cual: escribe el tema y pulsa **Generar**.")
        with gr.Row(equal_height=False):
            # ------------------------- entrada -------------------------
            with gr.Column(scale=5):
                topic = gr.Textbox(
                    label="Tema o URL de noticia",
                    placeholder='p. ej. "los pulpos tienen tres corazones" '
                                "o https://ejemplo.com/noticia",
                    lines=2)
                ideas_btn = gr.Button("💡 Lluvia de ideas", size="sm")

                # Inline "modal" (Gradio has no dialog component): a panel
                # that opens under the topic box and closes on pick.
                with gr.Column(visible=False, variant="panel") as ideas_panel:
                    gr.Markdown(
                        "**💡 Lluvia de ideas** — elige un tema y pulsa "
                        "*Usar este tema*. Los datos verificados llevan "
                        "detalles comprobados que recibe el guionista.")
                    with gr.Row():
                        ideas_source = gr.Radio(
                            [("Datos verificados", "bank"),
                             ("Ideas nuevas con Ollama (revísalas)",
                              "ollama")],
                            value="bank", label="Origen", scale=3)
                        ideas_area = gr.Dropdown(
                            [_ALL_AREAS] + _bank_areas(), value=_ALL_AREAS,
                            allow_custom_value=True, label="Área",
                            scale=2)
                    ideas_list = gr.Radio([], label="Ideas",
                                          interactive=True)
                    ideas_shown = gr.State([])
                    with gr.Row():
                        ideas_more = gr.Button("🎲 Otras ideas", size="sm")
                        ideas_use = gr.Button("✅ Usar este tema",
                                              variant="primary", size="sm")
                        ideas_close = gr.Button("Cerrar", size="sm")
                use_demo = gr.Checkbox(
                    value=False,
                    label="Guion de ejemplo — prueba gratis (sin LLM)",
                    info="Usa examples/demo_script.json: solo TTS gratuito y "
                         "render local, sin gastar créditos.")
                go = gr.Button("📝 Generar guion", variant="primary", size="lg")

                with gr.Group(visible=False) as review_group:
                    gr.Markdown("**Revisa el guion antes de generar el "
                                "video** — apruébalo o pide cambios")
                    script_review = gr.Textbox(label="Guion generado",
                                               lines=10, interactive=False)
                    feedback = gr.Textbox(
                        label="Instrucciones para regenerar (opcional)",
                        placeholder='p. ej. "hazlo más gracioso", "cambia '
                                    'el final", "más corto"',
                        lines=2)
                    with gr.Row():
                        regen = gr.Button("🔄 Regenerar guion")
                        approve = gr.Button("✅ Aprobar y generar video",
                                            variant="primary")

                with gr.Group():
                    gr.Markdown("**Parámetros** *(todos con valores por defecto)*")
                    with gr.Row():
                        language = gr.Dropdown(
                            _language_choices(),
                            value=_language_label(DEFAULT_LANGUAGE),
                            label="Idioma del diálogo")
                        max_turns = gr.Slider(
                            4, 16, value=DEFAULT_MAX_TURNS, step=1,
                            label="Máx. turnos")
                    watermark = gr.Textbox(
                        value=DEFAULT_WATERMARK,
                        label="Marca de agua (abajo-izquierda)",
                        info="Vacío = sin marca")
                    subtitles = gr.Checkbox(
                        value=True, label="Subtítulos del diálogo",
                        info="Blanco para el genio, amarillo para el ayudante")
                    _tiktok_ok = bool(os.environ.get("TIKTOK_CLIENT_KEY")
                                      and os.environ.get(
                                          "TIKTOK_CLIENT_SECRET"))
                    upload_tiktok = gr.Checkbox(
                        value=False, interactive=_tiktok_ok,
                        label="Subir a TikTok al terminar (borrador)"
                              + ("" if _tiktok_ok
                                 else " — faltan credenciales en .env"),
                        info="Sube el video terminado a tu bandeja de TikTok "
                             "(modo draft): lo publicas desde la app pegando "
                             "la caption de 📣. Requiere login previo: "
                             "python -m charla.tiktok --login")
                    bg_enabled = gr.Checkbox(
                        value=DEFAULT_BG_VOLUME > 0,
                        label="Audio ambiente del fondo",
                        info="Mezcla el sonido del video de fondo (uno de "
                             f"{BACKGROUNDS_DIR}/, fijo para cada tema) bajo "
                             "las voces; se omite si el fondo no tiene audio")
                    bg_volume = gr.Slider(
                        0.0, 0.6, value=DEFAULT_BG_VOLUME or 0.15, step=0.01,
                        label="Volumen del ambiente")
                    from .chatterbox import chatterbox_available
                    from .rvc import rvc_available
                    from .xtts import xtts_available
                    _rvc_ok = rvc_available()
                    _xtts_ok = xtts_available()
                    _cbx_ok = chatterbox_available()
                    use_rvc = gr.Checkbox(
                        value=_rvc_ok, interactive=_rvc_ok,
                        label="Voces del doblaje latino (RVC)"
                              + ("" if _rvc_ok else " — no instalado"),
                        info="Convierte las voces TTS al timbre de los "
                             "actores reales del doblaje (Juan Guzmán / "
                             "Eder La Barrera). Requiere install-rvc.ps1; "
                             "añade unos minutos de proceso en CPU.")
                    _engines = (["edge"] + (["xtts"] if _xtts_ok else [])
                                + (["chatterbox"] if _cbx_ok else []))
                    tts_engine = gr.Radio(
                        _engines,
                        value=(DEFAULT_TTS_ENGINE
                               if DEFAULT_TTS_ENGINE in _engines else "edge"),
                        label="Motor de voz",
                        info="edge = edge-tts (+RVC si está activo), rápido "
                             "y con subtítulos por palabra. xtts / "
                             "chatterbox = voz clonada de los clips reales; "
                             "más expresivos pero lentos en CPU y con "
                             "subtítulo por línea.",
                        interactive=len(_engines) > 1)
                    gr.Markdown("**Chroma** *(recorte del fondo verde)*")
                    with gr.Row():
                        chroma_similarity = gr.Slider(
                            0.05, 0.5, value=DEFAULT_CHROMA_SIMILARITY,
                            step=0.01, label="Nivel de chroma (similarity)",
                            info="Más alto quita más verde; demasiado alto "
                                 "se come al personaje")
                        chroma_blend = gr.Slider(
                            0.0, 0.3, value=DEFAULT_CHROMA_BLEND, step=0.01,
                            label="Suavizado de bordes (blend)")

                with gr.Accordion("Voces", open=False):
                    gr.Markdown("El **genio** suena mayor (grave y lento) y "
                                "el **ayudante** niño (agudo y rápido); "
                                "ajusta tono y velocidad a gusto.")
                    with gr.Row():
                        rick_voice = gr.Dropdown(
                            _RICK_VOICES, value=rick.voice,
                            label="Voz del genio (rick)",
                            allow_custom_value=True)
                        rick_rate = gr.Textbox(value=rick.voice_rate,
                                               label="Velocidad")
                        rick_pitch = gr.Textbox(value=rick.voice_pitch,
                                                label="Tono")
                    with gr.Row():
                        morty_voice = gr.Dropdown(
                            _MORTY_VOICES, value=morty.voice,
                            label="Voz del ayudante (morty)",
                            allow_custom_value=True)
                        morty_rate = gr.Textbox(value=morty.voice_rate,
                                                label="Velocidad")
                        morty_pitch = gr.Textbox(value=morty.voice_pitch,
                                                 label="Tono")

                with gr.Accordion("Avanzado", open=False):
                    text_provider = gr.Dropdown(
                        [_AUTO_PROVIDER, "claude", "gemini", "ollama"],
                        value=_AUTO_PROVIDER,
                        label="Proveedor de texto",
                        info="auto usa la primera opción disponible; "
                             "'ollama' = modelo local gratis, sin clave "
                             f"(por defecto {DEFAULT_OLLAMA_MODEL})")
                    with gr.Row():
                        resolution = gr.Textbox(
                            value=f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}",
                            label="Resolución (AnchoxAlto)")
                        fps = gr.Number(value=DEFAULT_FPS, label="FPS",
                                        precision=0)
                    char_scale = gr.Slider(
                        0.4, 1.0, value=DEFAULT_CHAR_SCALE, step=0.02,
                        label="Tamaño del personaje",
                        info="Fracción de la altura del video; cada uno en "
                             "su esquina inferior (rick derecha, morty "
                             "izquierda)")
                    _choices, _value, _ = _model_choices(_AUTO_PROVIDER,
                                                         DEFAULT_TEXT_MODEL)
                    text_model = gr.Dropdown(
                        _choices, value=_value, allow_custom_value=True,
                        label="Modelo de texto",
                        info="Con 'ollama' se listan los modelos instalados")
                    force = gr.Checkbox(
                        label="Forzar regeneración (ignorar caché)")
                    output_dir = gr.Textbox(
                        label="Carpeta de salida (vacío = automática)")

            # ------------------------- salida --------------------------
            with gr.Column(scale=7):
                eta_bar = gr.HTML(label="Progreso global")
                tiktok_bar = gr.HTML(label="Subida a TikTok")
                ding = gr.HTML(visible=True, elem_id="charla-ding",
                               container=False)
                video = gr.Video(label="Video final", height=560)
                social = gr.Textbox(
                    label="📣 Descripción y hashtags para TikTok/redes",
                    lines=4, interactive=False, buttons=["copy"],
                    info="Copia y pega al publicar (también en social.txt)")
                summary = gr.Textbox(label="Guion generado", lines=10,
                                     interactive=False)
                with gr.Accordion("Progreso", open=True):
                    log = gr.Textbox(show_label=False, lines=10, max_lines=14,
                                     interactive=False)

        with gr.Accordion("📼 Historial de videos generados", open=False):
            with gr.Row():
                hist_runs = gr.Dropdown(choices=[], label="Ejecuciones",
                                        scale=4,
                                        info="Los videos ya generados en "
                                             "output/; elige uno para verlo")
                hist_refresh = gr.Button("🔄 Actualizar", scale=1)
            with gr.Row():
                hist_video = gr.Video(label="Reproducción", height=480,
                                      scale=6)
                hist_info = gr.Textbox(label="Detalles y texto para redes",
                                       lines=14, interactive=False, scale=6,
                                       buttons=["copy"])

        # ---------------- lote automático (opcional, aparte) ----------------
        with gr.Accordion("🤖 Lote automático — varios videos de ciencia "
                          "con Ollama", open=False):
            gr.Markdown(
                "Genera varios videos seguidos sin intervenir: elige los "
                "temas, escribe cada guion con el modelo local de Ollama, "
                "pone las voces y renderiza. Al final deja en "
                "`output/_lote/<fecha>/` los videos numerados y "
                "**publicar.txt** con título, descripción y hashtags para "
                "pegar. Usa el idioma de arriba.")
            with gr.Row():
                lote_count = gr.Slider(1, 10, value=3, step=1,
                                       label="Cantidad de videos")
                lote_source = gr.Radio(
                    [("Banco de datos verificados (recomendado)", "bank"),
                     ("Propuestos por Ollama (revísalos)", "ollama")],
                    value="bank", label="Origen de los temas",
                    info="Los modelos locales chicos suelen inventar cifras; "
                         "el banco trae datos comprobados que no se repiten "
                         "entre lotes")
            with gr.Row():
                lote_theme = gr.Textbox(
                    value=DEFAULT_BATCH_THEME, label="Tema general",
                    info="Con el banco, un área (astronomía, cuerpo "
                         "humano...) va primero")
                _lchoices, _lvalue, _ = _model_choices("ollama",
                                                       DEFAULT_OLLAMA_MODEL)
                lote_model = gr.Dropdown(
                    _lchoices, value=_lvalue, allow_custom_value=True,
                    label="Modelo de Ollama para los guiones")
                lote_engine = gr.Radio(
                    _engines,
                    value=(DEFAULT_TTS_ENGINE
                           if DEFAULT_TTS_ENGINE in _engines else "edge"),
                    label="Motor de voz")
            lote_topics = gr.Textbox(
                label="Temas (uno por línea; vacío = se eligen solos)",
                lines=6,
                placeholder="Pulsa 'Proponer temas' para verlos y editarlos "
                            "antes de generar")
            with gr.Row():
                lote_suggest = gr.Button("🎲 Proponer temas")
                lote_go = gr.Button("🎬 Generar videos", variant="primary")
                lote_stop = gr.Button("⏹ Detener tras el video actual")
            lote_log = gr.Textbox(label="Progreso del lote", lines=10,
                                  max_lines=16, interactive=False)
            with gr.Row():
                lote_publish = gr.Textbox(
                    label="📣 Títulos y descripciones para pegar "
                          "(publicar.txt)",
                    lines=12, interactive=False, buttons=["copy"], scale=7)
                lote_folder = gr.Textbox(label="Carpeta del lote",
                                         interactive=False, scale=3)

        def _refresh_history():
            return gr.Dropdown(choices=_history_runs())

        hist_refresh.click(_refresh_history, outputs=hist_runs)
        hist_runs.change(_load_history_run, inputs=hist_runs,
                         outputs=[hist_video, hist_info])
        demo.load(_refresh_history, outputs=hist_runs)

        script_inputs = [topic, use_demo, language, max_turns, subtitles,
                        watermark, bg_enabled, bg_volume, use_rvc,
                        tts_engine, text_provider,
                        rick_voice, rick_rate, rick_pitch,
                        morty_voice, morty_rate, morty_pitch,
                        resolution, fps, chroma_similarity, chroma_blend,
                        char_scale, text_model, force, output_dir, feedback]
        script_outputs = [draft_state, script_review, log, review_group]

        # same order as approve_and_render's parameters after upload_tiktok
        render_inputs = [subtitles, watermark, bg_enabled, bg_volume, use_rvc,
                         tts_engine, rick_voice, rick_rate, rick_pitch,
                         morty_voice, morty_rate, morty_pitch, resolution,
                         fps, chroma_similarity, chroma_blend, char_scale]

        def _on_provider(provider, current):
            choices, value, ok = _model_choices(provider, current)
            if str(provider).startswith("ollama") and not ok:
                gr.Warning("Ollama no responde o no tiene modelos: inicia la "
                           f"app de Ollama o ejecuta `ollama pull "
                           f"{DEFAULT_OLLAMA_MODEL}`.")
            return gr.Dropdown(choices=choices, value=value)

        text_provider.change(_on_provider, inputs=[text_provider, text_model],
                             outputs=text_model)

        # ---------------- lluvia de ideas (modo simple) ----------------
        def _ideas_round(source, area, model, shown):
            """A new round of ideas, skipping the ones on screen."""
            try:
                choices = _idea_choices(source, area, model, list(shown or []))
            except Exception as e:
                raise gr.Error(str(e))
            return gr.Radio(choices=choices, value=None), [v for _, v in choices]

        def _ideas_fresh(source, area, model):
            return _ideas_round(source, area, model, [])

        def _open_ideas(source, area, model):
            radio, shown = _ideas_round(source, area, model, [])
            return gr.Column(visible=True), radio, shown

        def _use_idea(choice):
            if not choice:
                gr.Warning("Elige una idea de la lista primero.")
                return gr.skip(), gr.skip(), gr.skip()
            # fill the topic, close the panel, leave demo mode
            return choice, gr.Column(visible=False), False

        ideas_inputs = [ideas_source, ideas_area, text_model]
        ideas_btn.click(_open_ideas, inputs=ideas_inputs,
                        outputs=[ideas_panel, ideas_list, ideas_shown])
        ideas_more.click(_ideas_round, inputs=[*ideas_inputs, ideas_shown],
                         outputs=[ideas_list, ideas_shown])
        ideas_source.change(_ideas_fresh, inputs=ideas_inputs,
                            outputs=[ideas_list, ideas_shown])
        ideas_area.select(_ideas_fresh, inputs=ideas_inputs,
                          outputs=[ideas_list, ideas_shown])
        ideas_use.click(_use_idea, inputs=ideas_list,
                        outputs=[topic, ideas_panel, use_demo])
        ideas_close.click(lambda: gr.Column(visible=False),
                          outputs=ideas_panel)
        go.click(generate_script, inputs=script_inputs, outputs=script_outputs)
        regen.click(generate_script, inputs=script_inputs, outputs=script_outputs)
        approve.click(approve_and_render,
                      inputs=[draft_state, upload_tiktok, *render_inputs],
                      outputs=[log, video, summary, social,
                               eta_bar, ding, tiktok_bar]).then(
            _refresh_history, outputs=hist_runs)

        # ---------------- lote automático ----------------
        batch_stop = threading.Event()

        def _suggest_batch_topics(count, source, theme, model, language):
            from .batch import generate_topics
            try:
                topics = generate_topics(int(count), source, theme, model,
                                         str(language).split(" ")[0],
                                         log=lambda *_: None)
            except Exception as e:
                raise gr.Error(str(e))
            return "\n".join(t.tema for t in topics)

        def _run_batch_ui(count, source, theme, model, engine, topics_text,
                          language):
            """Whole batch in a worker thread; its log streams here. Like
            approve_and_render, a keep-alive yield every second stops the
            browser (or the Colab tunnel) from dropping a long job."""
            from .batch import run_batch, topics_from_lines

            topics = topics_from_lines((topics_text or "").splitlines()) or None
            batch_stop.clear()
            q: queue.Queue = queue.Queue()
            holder: dict = {}

            def worker():
                try:
                    holder["result"] = run_batch(
                        count=int(count), theme=theme, model=model,
                        tts_engine=str(engine),
                        language=str(language).split(" ")[0],
                        source=source, topics=topics, log=q.put,
                        should_stop=batch_stop.is_set)
                except Exception as e:  # surfaced as gr.Error below
                    holder["error"] = e
                finally:
                    q.put(None)

            threading.Thread(target=worker, daemon=True).start()
            lines: list[str] = []
            while True:
                try:
                    item = q.get(timeout=1.0)
                except queue.Empty:
                    yield gr.skip(), gr.skip(), gr.skip()
                    continue
                if item is None:
                    break
                lines.append(str(item))
                del lines[:-400]
                yield "\n".join(lines), gr.skip(), gr.skip()
            if "error" in holder:
                raise gr.Error(str(holder["error"]))
            result = holder["result"]
            yield ("\n".join(lines),
                   result.publish_text or "(ningún video terminado)",
                   str(result.folder.resolve()))

        def _stop_batch():
            batch_stop.set()
            gr.Info("El lote se detendrá al terminar el video actual.")

        lote_suggest.click(
            _suggest_batch_topics,
            inputs=[lote_count, lote_source, lote_theme, lote_model, language],
            outputs=lote_topics)
        lote_go.click(
            _run_batch_ui,
            inputs=[lote_count, lote_source, lote_theme, lote_model,
                    lote_engine, lote_topics, language],
            outputs=[lote_log, lote_publish, lote_folder]).then(
            _refresh_history, outputs=hist_runs)
        lote_stop.click(_stop_batch)
    return demo


def main() -> int:
    try:
        import gradio  # noqa: F401
    except ImportError:
        print("La interfaz necesita gradio. Instálalo con:\n"
              "  pip install -e .[ui]")
        return 1
    import gradio as gr

    build_app().launch(
        inbrowser=True,
        theme=gr.themes.Soft(primary_hue="green", neutral_hue="stone"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
