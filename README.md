# Charla — conversaciones en video

Generador de videos verticales (9:16) para TikTok/Reels/Shorts: a partir de un
**tema libre** o una **URL de noticia**, dos personajes mantienen una
conversación cómica — un **genio mayor** (arrogante, sarcástico) y su
**ayudante niño** (ansioso, ingenuo) — con voz TTS distinta por personaje,
emociones por turno y subtítulos progresivos.

Derivado de [storytelling / escalator](../storytelling): mismo estilo de
pipeline (LLM → edge-tts → ffmpeg) pero con clips de personaje pregenerados en
chroma verde en lugar de imágenes por escena.

## Cómo funciona

```
tema o URL ──► [scraper]  requests + trafilatura (solo URLs)
           ──► [guion]    Claude/Gemini con salida estructurada:
                          turnos {speaker, emotion, line} + caption + hashtags.
                          Solo puede elegir emociones con clip en disco.
           ──► [tts]      edge-tts, una voz por personaje (word timings)
           ──► [render]   ffmpeg: personaje a pantalla completa con colorkey
                          sobre background.mp4 (el fondo avanza continuo entre
                          cortes), subtítulos por palabra, concat y ambiente
```

## Requisitos

- Python 3.11+ y ffmpeg (el instalador lo resuelve)
- Clave de API para el guion: `ANTHROPIC_API_KEY` (Claude) o
  `GOOGLE_API_KEY` (Gemini). El modo `--script-file` no necesita ninguna.

## Instalación

```powershell
.\install.ps1     # paquete + ffmpeg + .env
```

o a mano: `pip install -e ".[ui]"` y copia `.env.example` → `.env` con tus
claves.

## Uso

```powershell
# prueba gratis, sin LLM (guion manual de ejemplo)
charla --script-file examples\demo_script.json

# tema libre
charla "los pulpos tienen tres corazones y sangre azul"

# URL de noticia (se extrae el artículo y se guioniza)
charla https://ejemplo.com/noticia

# solo el guion, sin generar media
charla "tema" --dry-run

# asistente guiado / interfaz web
.\run-cli.ps1
.\run-ui.ps1      # o: charla-ui
```

Flags útiles: `--language`, `--max-turns`, `--rick-voice/-rate/-pitch`,
`--morty-*`, `--resolution`, `--fps`, `--bg-volume` / `--no-bg-audio`,
`--chroma-similarity/-blend`, `--no-subtitles`, `--no-watermark`,
`--force` / `--force-from {script,tts,render}`, `--text-provider`,
`--list-emotions`. Ver `charla --help`.

## Assets

- `characters/<personaje>/<emocion>_<personaje>.mp4` — loops de 10 s en verde
  chroma (720x1280, 24 fps), uno por emoción. El guionista solo puede usar
  emociones cuyo clip exista para **ambos** personajes: al añadir un clip
  nuevo (p. ej. `sorpresa_shock`) entra solo, sin tocar código.
- `background.mp4` — fondo común; avanza de forma continua a lo largo de la
  conversación y su audio se mezcla a bajo volumen como ambiente.

Dinamismo de los clips: cada turno corto reproduce la **cola** del loop de
emoción (arranca en `dur_clip − dur_turno`, terminando con el clip), así dos
turnos con la misma emoción nunca empiezan con el mismo gesto. Un diálogo más
largo que el clip usa una versión **ping-pong** (adelante + espejo, cacheada
en `output/_cache/`) para loopear sin corte visible.

Nota de chroma: el verde de los clips es poco saturado, por eso el render usa
`colorkey` (distancia RGB) y no `chromakey` (UV). El color se define por
personaje en `src/charla/config.py`; el nivel de recorte se ajusta con
`--chroma-similarity` / `--chroma-blend` en el CLI, con los sliders "Chroma"
de la UI, o con `CHARLA_CHROMA_SIMILARITY` / `CHARLA_CHROMA_BLEND` en `.env`.

## Voces

Las voces del doblaje original de la serie son, en latino, **Juan Guzmán**
(Rick) y **Eder La Barrera** (Morty), y en castellano **Txema Moscoso** y
**Rodri Martín**.

### Voces del doblaje real (RVC, gratis y local)

`.\install-rvc.ps1` monta la conversión de voz RVC: un venv dedicado con
Python 3.10 (`.rvc-venv/`, rvc-python + torch CPU) y los modelos comunitarios
entrenados con los actores del doblaje latino
([Rick](https://huggingface.co/Matius54/Rick_Sanchez_Latino) /
[Morty](https://huggingface.co/Matius54/Morty_Smith_Latino), ~1.5 GB en
total). Con eso instalado, el pipeline convierte automáticamente el audio TTS
al timbre de los actores reales (`--rvc auto`; forzar con `on`, desactivar
con `off`). La conversión corre en CPU y se cachea por turno. Los word
timings de edge-tts se conservan, así que los subtítulos siguen sincronizados.

Con RVC activo la fuente TTS se genera SIN pitch/rate artificiales (el audio
distorsionado produce artefactos en la conversión); el tono del personaje se
ajusta con la transposición del propio RVC en semitonos:
`CHARLA_RICK_RVC_PITCH` (0 por defecto) y `CHARLA_MORTY_RVC_PITCH` (+8).
En `voices_preview/rvc/` hay muestras comparando pitches y checkpoints —
escúchalas para calibrar. Ten en cuenta el límite de la técnica: RVC clona el
timbre, no la actuación; la entonación sigue siendo la del TTS.

### Voz clonada XTTS (entrenable en Colab)

`.\install-xtts.ps1` monta el motor `--tts xtts` (XTTS v2, venv dedicado
`.xtts-venv/`): genera cada línea directamente con la voz clonada — timbre
Y prosodia, no solo timbre como RVC. Dos modos automáticos por personaje:

- **Fine-tuned**: entrena el modelo en Colab con GPU gratis siguiendo
  [COLAB_XTTS.md](COLAB_XTTS.md) (los datasets ya están preparados en
  `voices_preview/reales/dataset_*.zip`) y deja el resultado en
  `models/xtts/<personaje>/`.
- **Zero-shot**: sin entrenar nada, clona la voz al vuelo desde los clips
  de `voices_preview/reales/<personaje>/`.

CPU lento (~1-2 min por línea, cacheado por turno) y sin subtítulos
progresivos (caption por línea completa). Licencia XTTS: no comercial.

### Voz clonada Chatterbox (MIT, expresiva)

`.\install-chatterbox.ps1` monta `--tts chatterbox` (Resemble AI, licencia
MIT — apta para uso comercial): clonación zero-shot desde un clip de
referencia por personaje, con control de **exageración emocional**
(`CHARLA_RICK_EXAGGERATION=0.7`, `CHARLA_MORTY_EXAGGERATION=0.6`). Igual que
XTTS: CPU lento, cacheado por turno, subtítulo por línea.

### Base TTS (edge-tts, sin instalación extra)

- Rick: `es-MX-JorgeNeural` con `-20Hz` / `-5%` (grave, seco)
- Morty: `es-US-AlonsoNeural` con `+30Hz` / `+14%` (agudo, acelerado)

Para sabor castellano usa `--rick-voice es-ES-AlvaroNeural`. En
`voices_preview/` hay muestras mp3 de 6 candidatos por personaje ya
procesadas con el pitch/rate de cada rol — escúchalas y fija tu favorita vía
flags o `.env`.

## Estilo visual

Cada personaje aparece en su esquina inferior (rick derecha, morty
izquierda, mirándose) a `--char-scale` de la altura del frame (0.72 por
defecto), dejando libre la parte superior, donde van los subtítulos con la
fuente **Get Schwifty** (recreación fan del logo de la serie, freeware no
comercial, en `assets/fonts/`). La fuente solo trae letras y números, así
que el texto del subtítulo se normaliza para display (sin tildes ni signos);
si borras el ttf se vuelve a Arial Bold con el texto íntegro.

## Modo Colab (GPU gratis para todo el pipeline)

[colab/charla_colab.ipynb](colab/charla_colab.ipynb) corre el generador
completo en Google Colab con GPU. El código se **clona de este repo** en cada
sesión; tu Drive (`MyDrive/charla/`) solo aporta lo que no viaja por git:
`characters/`, `background.mp4`, `voices_preview/reales/` y tu `.env`.

Abrir el cuaderno (siempre la última versión del repo):
`https://colab.research.google.com/github/sfsusuario/storytelling-conversation/blob/main/colab/charla_colab.ipynb`

Con runtime T4: celda 1 (clona + instala, ~3-5 min; el modelo Chatterbox se
cachea en tu Drive) y celda 2 (interfaz Gradio con enlace público). La voz
clonada pasa de ~1-2 min/línea en CPU a segundos, y la celda 4 guarda los
videos en tu Drive. Para actualizar Colab tras cambiar código: commit + push
y re-ejecutar la celda 1. El modo local sigue funcionando igual.
(`gen-code-zip.ps1` queda como alternativa offline si algún día no quieres
pasar por GitHub: genera `charla_code.zip` para subirlo a Drive a mano.)

## Salida

```
output/<slug>-<hash>/
├── 01_script/  script.json (+ article.json si hubo URL)
├── 02_audio/   turn_NN.mp3 + word timings
├── 03_clips/   turn_NN.mp4 + concat + premix
├── final.mp4   720x1280 @ 30fps, H.264 + AAC
├── social.txt  caption + hashtags listos para publicar
└── manifest.json
```

Todo está cacheado por etapa: repetir un comando no regenera lo que no cambió.
