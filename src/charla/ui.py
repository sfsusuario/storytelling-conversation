from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path

from .config import (CHARACTERS, DEFAULT_BACKGROUND, DEFAULT_BG_VOLUME,
                     DEFAULT_CHAR_SCALE,
                     DEFAULT_CHROMA_BLEND, DEFAULT_CHROMA_SIMILARITY,
                     DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_LANGUAGE,
                     DEFAULT_MAX_TURNS, DEFAULT_MIN_TURNS,
                     DEFAULT_TEXT_MODEL, DEFAULT_WATERMARK, DEFAULT_WIDTH,
                     LANGUAGE_NAMES, PipelineOptions)

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


def _language_choices() -> list[str]:
    return [f"{code} — {name}" for code, name in LANGUAGE_NAMES.items()]


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
        provider = str(text_provider).split(" ")[0]
        if not use_demo:
            have_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
            have_google = bool(os.environ.get("GOOGLE_API_KEY")
                               or os.environ.get("GEMINI_API_KEY"))
            if provider == "claude" and not have_claude:
                raise gr.Error("ANTHROPIC_API_KEY no está configurada. Ponla "
                               "en .env (o cambia el proveedor a auto/gemini) "
                               "y reinicia.")
            if provider == "gemini" and not have_google:
                raise gr.Error("GOOGLE_API_KEY / GEMINI_API_KEY no está "
                               "configurada. Ponla en .env y reinicia.")
            if provider == "auto" and not (have_claude or have_google):
                raise gr.Error("No hay ninguna clave de API: pon "
                               "ANTHROPIC_API_KEY (Claude) o GOOGLE_API_KEY "
                               "(Gemini) en .env y reinicia, o marca 'Guion "
                               "de ejemplo'.")
        try:
            width, height = (int(x) for x in str(resolution).lower().split("x"))
        except ValueError:
            raise gr.Error(f"Resolución inválida '{resolution}', formato AnchoxAlto")

        return PipelineOptions(
            input_text="" if use_demo else topic,
            script_file=_DEMO_SCRIPT if use_demo else None,
            script_feedback="" if use_demo else (feedback or "").strip(),
            language=str(language).split(" ")[0],
            max_turns=int(max_turns),
            min_turns=min(DEFAULT_MIN_TURNS, int(max_turns)),
            width=width, height=height, fps=int(fps),
            watermark=(watermark or "").strip(),
            subtitles=bool(subtitles),
            bg_volume=float(bg_volume or 0.0) if bg_enabled else 0.0,
            tts_engine=str(tts_engine),
            rvc="on" if use_rvc else "off",
            chroma_similarity=float(chroma_similarity),
            chroma_blend=float(chroma_blend),
            char_scale=float(char_scale),
            output_dir=Path(output_dir) if output_dir else None,
            force=bool(force),
            text_provider=provider,
            text_model=text_model,
            rick_voice=rick_voice or None,
            rick_rate=(rick_rate or "").strip() or None,
            rick_pitch=(rick_pitch or "").strip() or None,
            morty_voice=morty_voice or None,
            morty_rate=(morty_rate or "").strip() or None,
            morty_pitch=(morty_pitch or "").strip() or None,
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

    def approve_and_render(draft, progress=gr.Progress()):
        """Stages 2-4 for the script the user already approved in the
        review step."""
        if draft is None:
            raise gr.Error("Primero genera (y revisa) un guion.")

        from .pipeline import continue_pipeline
        from .timings import engine_key, estimate_seconds

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
                       gr.skip())
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
                if re.match(r"^  (tts|rvc|xtts|chatterbox|pingpong):", msg):
                    audio_done += 1
                    frac = max(frac, 0.05 + 0.50
                               * min(1.0, audio_done / turn_total))
                elif re.match(r"^  clip:", msg):
                    clip_done += 1
                    frac = max(frac, 0.60 + 0.38
                               * min(1.0, clip_done / turn_total))
            if msg.startswith("done:"):
                frac = 1.0
            progress(frac, desc=msg.strip()[:70])
            yield ("\n".join(lines), None, gr.skip(), gr.skip(),
                   _eta_html(time.monotonic() - started, estimate),
                   gr.skip())

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
               _ding_html())

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
                            value=f"{DEFAULT_LANGUAGE} — "
                                  f"{LANGUAGE_NAMES[DEFAULT_LANGUAGE]}",
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
                    bg_enabled = gr.Checkbox(
                        value=True, label="Audio ambiente del fondo",
                        info=f"Mezcla el sonido de {DEFAULT_BACKGROUND} bajo "
                             "las voces")
                    bg_volume = gr.Slider(
                        0.0, 0.6, value=DEFAULT_BG_VOLUME, step=0.01,
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
                        _engines, value="edge",
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
                        ["auto (Claude si hay clave, si no Gemini)",
                         "claude", "gemini"],
                        value="auto (Claude si hay clave, si no Gemini)",
                        label="Proveedor de texto",
                        info="Con 'gemini' basta la clave de Google")
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
                    text_model = gr.Textbox(value=DEFAULT_TEXT_MODEL,
                                            label="Modelo de texto")
                    force = gr.Checkbox(
                        label="Forzar regeneración (ignorar caché)")
                    output_dir = gr.Textbox(
                        label="Carpeta de salida (vacío = automática)")

            # ------------------------- salida --------------------------
            with gr.Column(scale=7):
                eta_bar = gr.HTML(label="Progreso global")
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

        go.click(generate_script, inputs=script_inputs, outputs=script_outputs)
        regen.click(generate_script, inputs=script_inputs, outputs=script_outputs)
        approve.click(approve_and_render, inputs=[draft_state],
                      outputs=[log, video, summary, social,
                               eta_bar, ding]).then(
            _refresh_history, outputs=hist_runs)
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
