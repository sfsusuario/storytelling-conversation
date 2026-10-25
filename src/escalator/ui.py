from __future__ import annotations

import queue
import threading
from pathlib import Path

from .config import (CURATED_VOICES, DEFAULT_FPS, DEFAULT_HEIGHT,
                     DEFAULT_IMAGE_MODEL, DEFAULT_IMAGE_PROVIDER,
                     DEFAULT_KOKORO_VOICE, DEFAULT_LANGUAGE,
                     DEFAULT_TTS_PROVIDER, IMAGE_PROVIDERS, KOKORO_VOICES,
                     DEFAULT_MUSIC_VOLUME, DEFAULT_STAGES, DEFAULT_TEXT_MODEL,
                     DEFAULT_VOICE, DEFAULT_VOICE_PITCH, DEFAULT_VOICE_RATE,
                     DEFAULT_WATERMARK, LANGUAGE_NAMES, STYLE_SETS,
                     DEFAULT_WIDTH, PipelineOptions)

_SET_LABELS_ES = {
    "medieval": "medieval", "scifi": "ciencia ficción", "corporate": "corporativo",
    "mythology": "mitología", "military": "militar", "pirate": "piratas",
    "arcane": "magia arcana", "epochs": "épocas de la historia",
    "wealth": "escalada de riqueza", "tech": "profesiones tech",
    "anger": "escalada de enfado", "excuses": "excusas absurdas",
}


def _style_set_choices() -> list[str]:
    return (["random (un set al azar)", "mix (mezcla por niveles)"]
            + sorted(STYLE_SETS))


def _style_set_info() -> str:
    lines = [f"**{name}** ({_SET_LABELS_ES.get(name, name)}): "
             + " → ".join(p.name for p in STYLE_SETS[name])
             for name in sorted(STYLE_SETS)]
    return ("*random* elige un set completo al azar; *mix* elige un personaje "
            "aleatorio por nivel (siempre ascendente).\n\n" + "\n\n".join(lines))


def _language_choices() -> list[str]:
    return [f"{code} — {name}" for code, name in LANGUAGE_NAMES.items()]


def _preview_music(style_set_label: str, source_label: str) -> str:
    """Return a listenable sample of what the video's background will use."""
    from .music import preview_file

    return str(preview_file(str(style_set_label).split(" ")[0],
                            str(source_label).split(" ")[0]))


def _history_runs() -> list[tuple[str, str]]:
    """(label, video_path) for every finished run under output/, newest first."""
    from datetime import datetime

    from .history import list_runs

    return [(f'{datetime.fromtimestamp(r["mtime"]):%d/%m %H:%M} — "{r["phrase"]}" '
             f'({r["style_set"]}{", prueba" if r["test_mode"] else ""})'
             f' [{r["name"]}]', str(r["video"]))
            for r in list_runs()]


def _load_history_run(video_path: str | None):
    import json

    if not video_path:
        return None, ""
    run_dir = Path(video_path).parent
    details = [f"Carpeta: {run_dir.resolve()}"]
    try:
        m = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))
        details = [
            f'Frase:     "{m.get("Input_Phrase")}"',
            f"Set:       {m.get('Style_Set')}   Idioma: {m.get('Language')}   "
            f"Duración: {m.get('Total_Duration')}s",
            f"Voz:       {m.get('Scenes', [{}])[0].get('Voice_Config', {}).get('voice', '?')}",
            "Escenas:   " + " | ".join(
                f"N{s.get('Style_Level')} {s.get('Style')}"
                for s in m.get("Scenes", [])),
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

    def generate(image_path, phrase, style_set, stages, language, voice,
                 seed, test_mode, subtitles, music_enabled, music_volume,
                 music_source, watermark, text_provider, fit, resolution,
                 fps, voice_rate, voice_pitch, text_model, image_model,
                 force, output_dir, image_provider, tts_provider, motion):
        if not image_path:
            raise gr.Error("Sube primero una imagen de retrato.")
        if not phrase or not phrase.strip():
            raise gr.Error("Escribe la frase a escalar.")
        # Missing keys / backends are reported by the pipeline's resolvers.
        provider = str(text_provider).split(" ")[0]
        try:
            width, height = (int(x) for x in str(resolution).lower().split("x"))
        except ValueError:
            raise gr.Error(f"Resolución inválida '{resolution}', formato AnchoxAlto")

        options = PipelineOptions(
            base_image=Path(image_path),
            phrase=phrase.strip(),
            style_set=str(style_set).split(" ")[0],
            seed=int(seed) if seed not in (None, "") else None,
            stages=int(stages),
            voice=voice,
            voice_rate=voice_rate or "+0%",
            voice_pitch=voice_pitch or "+0Hz",
            language=str(language).split(" ")[0],
            width=width, height=height, fps=int(fps),
            fit=str(fit).split(" ")[0],
            watermark=(watermark or "").strip(),
            subtitles=bool(subtitles),
            music_volume=float(music_volume or 0.0) if music_enabled else 0.0,
            music_source=str(music_source).split(" ")[0],
            output_dir=Path(output_dir) if output_dir else None,
            test_mode=bool(test_mode),
            text_provider=provider,
            force=bool(force),
            text_model=text_model,
            image_provider=str(image_provider).split(" ")[0],
            image_model=image_model,
            tts_provider=str(tts_provider).split(" ")[0],
            motion=str(motion).split(" ")[0],
        )

        from .pipeline import run_pipeline

        q: queue.Queue = queue.Queue()
        holder: dict = {}

        def worker():
            try:
                holder["result"] = run_pipeline(options, on_progress=q.put)
            except Exception as e:  # surfaced as gr.Error below
                holder["error"] = e
            finally:
                q.put(None)

        threading.Thread(target=worker, daemon=True).start()
        lines: list[str] = []
        while True:
            item = q.get()
            if item is None:
                break
            lines.append(str(item))
            yield "\n".join(lines), None, gr.skip(), gr.skip()

        if "error" in holder:
            raise gr.Error(str(holder["error"]))
        result = holder["result"]
        personas = "\n".join(f"  N{p.level} — {p.name}" for p in result.personas)
        summary = (f"Set de estilos: {result.style_set}\n{personas}\n\n"
                   f"Carpeta:    {result.output_dir.resolve()}\n"
                   f"Manifiesto: {result.manifest_path.resolve()}")
        lines.append("¡listo!")
        yield ("\n".join(lines), str(result.final_video), summary,
               result.social or "")

    with gr.Blocks(title="Escalator — generador de videos") as demo:
        gr.Markdown(
            "# 🎬 Escalator\n"
            "Retrato + frase → video vertical con narración que **escala de "
            "sofisticación** escena a escena. Los valores por defecto "
            "funcionan tal cual: sube una imagen, escribe la frase y pulsa "
            "**Generar**.")
        with gr.Row(equal_height=False):
            # ------------------------- entrada -------------------------
            with gr.Column(scale=5):
                image = gr.Image(label="Retrato", type="filepath", height=260)
                phrase = gr.Textbox(
                    label="Frase", placeholder='p. ej. "Apaga eso"', lines=1)
                test_mode = gr.Checkbox(
                    value=False,
                    label="Modo prueba — ejecución barata (sin imágenes IA)",
                    info="Reutiliza el retrato con una etiqueta por nivel. "
                         "Solo gasta la llamada de texto; ideal para probar "
                         "sin consumir créditos.")
                motion = gr.Dropdown(
                    ["none (imagen fija)", "rotate3d (rotación 3D, segundos)",
                     "liveportrait (anima la cara)"],
                    value="none (imagen fija)", label="Movimiento")
                go = gr.Button("🎬 Generar video", variant="primary", size="lg")

                with gr.Group():
                    gr.Markdown("**Parámetros** *(todos con valores por defecto)*")
                    with gr.Row():
                        style_set = gr.Dropdown(
                            _style_set_choices(),
                            value="random (un set al azar)",
                            label="Set de estilos")
                        stages = gr.Slider(2, DEFAULT_STAGES,
                                           value=DEFAULT_STAGES, step=1,
                                           label="Escenas")
                    with gr.Row():
                        language = gr.Dropdown(
                            _language_choices(),
                            value=f"{DEFAULT_LANGUAGE} — "
                                  f"{LANGUAGE_NAMES[DEFAULT_LANGUAGE]}",
                            label="Idioma (textos y narración)")
                        voice = gr.Dropdown(
                            KOKORO_VOICES + CURATED_VOICES,
                            value=(DEFAULT_KOKORO_VOICE
                                   if DEFAULT_TTS_PROVIDER == "kokoro"
                                   else DEFAULT_VOICE),
                            label="Voz del narrador",
                            info="Kokoro: em_alex/ef_dora/em_santa; "
                                 "*Neural = edge-tts")
                    with gr.Row():
                        watermark = gr.Textbox(
                            value=DEFAULT_WATERMARK,
                            label="Marca de agua (abajo-izquierda)",
                            info="Vacío = sin marca")
                        seed = gr.Number(label="Seed (vacío = aleatorio)",
                                         value=None, precision=0)
                    subtitles = gr.Checkbox(
                        value=True, label="Subtítulos de la narración",
                        info="Incrusta el texto narrado en cada escena")
                    music_enabled = gr.Checkbox(
                        value=True, label="Añadir música de fondo",
                        info="Mezcla una banda sonora acorde al set bajo la "
                             "narración")
                    with gr.Row():
                        music_volume = gr.Slider(
                            0.0, 0.6, value=DEFAULT_MUSIC_VOLUME, step=0.01,
                            label="Volumen de la música", scale=3)
                        music_btn = gr.Button("🔊 Probar música", scale=1)
                    music_source = gr.Dropdown(
                        ["track (pista CC-BY de incompetech)",
                         "synth (ambiente sintetizado, nunca bloqueado)"],
                        value="track (pista CC-BY de incompetech)",
                        label="Fuente de la música",
                        info="Si TikTok bloquea una pista, cambia a synth o "
                             "avísame para elegir otra banda sonora")
                    music_preview = gr.Audio(label="Muestra del ambiente",
                                             visible=True, interactive=False)

                with gr.Accordion("Avanzado", open=False):
                    text_provider = gr.Dropdown(
                        ["auto (Ollama local si está activo, si no Claude/Gemini)",
                         "ollama", "claude", "gemini"],
                        value="auto (Ollama local si está activo, si no Claude/Gemini)",
                        label="Proveedor de texto",
                        info="ollama = local y gratis; con 'gemini' basta la "
                             "clave de Google")
                    image_provider = gr.Dropdown(
                        IMAGE_PROVIDERS, value=DEFAULT_IMAGE_PROVIDER,
                        label="Proveedor de imágenes",
                        info="flux-kontext = local, mejor calidad (minutos); "
                             "sdxl-face = local, rápido; gemini = nube")
                    tts_provider = gr.Dropdown(
                        ["kokoro", "edge"], value=DEFAULT_TTS_PROVIDER,
                        label="Proveedor de voz",
                        info="kokoro = local; edge = edge-tts online")
                    fit = gr.Dropdown(
                        ["crop (llena la pantalla, estilo TikTok)",
                         "blur (fondo difuminado)", "pad (bandas negras)"],
                        value="crop (llena la pantalla, estilo TikTok)",
                        label="Relleno del encuadre")
                    with gr.Row():
                        resolution = gr.Textbox(
                            value=f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}",
                            label="Resolución (AnchoxAlto)")
                        fps = gr.Number(value=DEFAULT_FPS, label="FPS",
                                        precision=0)
                    with gr.Row():
                        voice_rate = gr.Textbox(
                            value=DEFAULT_VOICE_RATE, label="Velocidad de voz",
                            info="p. ej. -8% (más lenta = más mayor)")
                        voice_pitch = gr.Textbox(
                            value=DEFAULT_VOICE_PITCH, label="Tono de voz",
                            info="p. ej. -12Hz (más grave = más mayor)")
                    text_model = gr.Textbox(value=DEFAULT_TEXT_MODEL,
                                            label="Modelo de texto")
                    image_model = gr.Textbox(value=DEFAULT_IMAGE_MODEL,
                                             label="Modelo de imagen (Gemini)")
                    force = gr.Checkbox(
                        label="Forzar regeneración (ignorar caché)")
                    output_dir = gr.Textbox(
                        label="Carpeta de salida (vacío = automática)")

                with gr.Accordion("Sets de estilos disponibles", open=False):
                    gr.Markdown(_style_set_info())

            # ------------------------- salida --------------------------
            with gr.Column(scale=7):
                video = gr.Video(label="Video final", height=560)
                social = gr.Textbox(
                    label="📣 Descripción y hashtags para TikTok/redes",
                    lines=4, interactive=False, buttons=["copy"],
                    info="Copia y pega al publicar (también en social.txt)")
                summary = gr.Textbox(label="Resumen de la ejecución", lines=6,
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

        music_btn.click(_preview_music, inputs=[style_set, music_source],
                        outputs=music_preview)
        hist_refresh.click(_refresh_history, outputs=hist_runs)
        hist_runs.change(_load_history_run, inputs=hist_runs,
                         outputs=[hist_video, hist_info])
        demo.load(_refresh_history, outputs=hist_runs)

        go.click(generate,
                 inputs=[image, phrase, style_set, stages, language, voice,
                         seed, test_mode, subtitles, music_enabled,
                         music_volume, music_source, watermark, text_provider,
                         fit, resolution, fps, voice_rate, voice_pitch,
                         text_model, image_model, force, output_dir,
                         image_provider, tts_provider, motion],
                 outputs=[log, video, summary, social]).then(
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

    from .music import _cache_dir
    build_app().launch(
        inbrowser=True,
        allowed_paths=[str(_cache_dir())],
        theme=gr.themes.Soft(primary_hue="orange", neutral_hue="stone"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
