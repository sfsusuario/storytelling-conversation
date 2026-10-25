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
           ──► [guion]    Claude / Gemini / Ollama (local) con salida
                          estructurada: turnos {speaker, emotion, line} +
                          caption + hashtags. Solo puede elegir emociones con
                          clip en disco.
           ──► [tts]      edge-tts, una voz por personaje (word timings),
                          varias líneas a la vez — o voz clonada (Chatterbox)
           ──► [render]   ffmpeg: cada personaje en su esquina con colorkey
                          sobre un fondo de backgrounds/ (avanza continuo
                          entre cortes), subtítulos por palabra; turnos en
                          paralelo con Quick Sync/NVENC/x264, concat y ambiente
```

## Requisitos

- Python 3.11+ y ffmpeg (el instalador lo resuelve)
- Para el guion, una de estas opciones:
  - `ANTHROPIC_API_KEY` (Claude) o `GOOGLE_API_KEY` (Gemini) en `.env`.
  - [Ollama](https://ollama.com) corriendo con un modelo local (gratis, sin
    clave): `ollama pull gemma3:4b`.
  - El modo `--script-file` no necesita ninguna.

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

# guion con un modelo local de Ollama (gratis, sin clave)
charla "los pulpos tienen tres corazones" --text-provider ollama
charla "tema" --text-model gpt-oss:20b      # en auto, un modelo no-Claude/Gemini = Ollama

# URL de noticia (se extrae el artículo y se guioniza)
charla https://ejemplo.com/noticia

# solo el guion, sin generar media
charla "tema" --dry-run

# asistente guiado / interfaz web
.\run-cli.ps1     # escribe ? como tema para elegir de una lluvia de ideas
.\run-ui.ps1      # interfaz web (React); Gradio avanzado: .\run-gradio.ps1 o charla-ui
```

**Lluvia de ideas.** En la interfaz, el botón **💡 Lluvia de ideas** (bajo
el campo del tema) abre un panel con 8 temas para elegir:
- **Datos verificados:** salen del banco de ciencia, se pueden filtrar por
  área (astronomía, cuerpo humano...).
- **Ideas nuevas con Ollama:** sin verificar, hay que revisarlas.

**🎲 Otras ideas** trae otra tanda y **Usar este tema** lo pone en el campo.
Cuando el tema es un dato del banco, el guionista recibe además sus
detalles comprobados (vale también si lo escribes tal cual en la línea de
comandos).

Flags útiles: `--language`, `--max-turns` / `--min-turns`,
`--text-provider {auto,claude,gemini,ollama}`, `--text-model`,
`--tts {edge,xtts,chatterbox}`, `--rvc {auto,on,off}`,
`--rick-voice/-rate/-pitch`, `--morty-*`, `--resolution`, `--fps`,
`--background`, `--char-scale`, `--bg-volume` / `--no-bg-audio`,
`--chroma-similarity/-blend`, `--no-subtitles`, `--no-watermark`,
`--force` / `--force-from {script,tts,render}`, `--reencode-concat`,
`--list-emotions`. Ver `charla --help`.

## Interfaz web (recomendada)

```powershell
.\run-ui.ps1       # abre http://127.0.0.1:7870  (o: run-web.ps1 / charla-web)
```

Interfaz React + TypeScript con dos pestañas:

- **Crear video.** Muestra el flujo por pasos (Tema → Guion → Voz → Video →
  Listo).
  - **💡 Ideas** abre el selector de temas.
  - El guion se revisa como chat y se aprueba o regenera.
  - El progreso se ve en vivo, por turno (voz lista / clip listo), con ETA.
  - Al terminar: reproductor, descripción para copiar y descarga.
- **Lote automático.** Muestra una tarjeta por video con su etapa, permite
  detener el lote, y da `publicar.txt` para copiar.

A la vista solo quedan el tema y el motor de voz. Idioma, turnos,
guionista, subtítulos, marca de agua y ambiente están en **⚙ Ajustes**. Todo
lo demás usa los valores por defecto de `.env` / `config.py`.

`.\run-gradio.ps1` (Gradio) sigue disponible como modo avanzado, con todos los
ajustes, el historial y la subida a TikTok.

La primera vez, `run-web.ps1` compila la interfaz con Node.js: `npm install`
y `npm run build` en `web/`. Para desarrollar con recarga en caliente:
`charla-web` en una terminal y `cd web; npm run dev` en otra.

## Lote automático (varios videos de ciencia con Ollama)

Apartado opcional que genera varios videos seguidos sin intervenir, con el
guion escrito por un modelo local de Ollama (sin claves de API):

```powershell
.\run-lote.ps1                          # asistente guiado
charla-lote --count 5                   # 5 videos con temas del banco verificado
charla-lote --count 3 --theme astronomía --tts chatterbox
charla-lote --only-topics --count 5     # solo elegir temas -> output\_lote\temas_propuestos.txt
charla-lote --topics-file mis_temas.txt # usar tus temas (uno por línea)
charla-lote --source ollama --count 3   # temas inventados por el modelo (¡revísalos!)
```

En la interfaz está en **🤖 Lote automático** (abajo): proponer temas
(editables antes de generar), generar, y detener tras el video actual.

- **Temas.** Por defecto salen de un banco de ~60 datos científicos
  verificados (`src/charla/data/temas_ciencia.json`), cada uno con detalles
  que el guionista usa como fuente, así inventa menos. Nunca se repite un
  tema ya usado en lotes anteriores (`output/_lote/temas_usados.json`).
  `--source ollama` pide los temas al modelo, pero medido en este equipo
  gemma3:4b y gpt-oss:20b inventaban la mayoría de las cifras: revísalos
  antes de publicar.
- **Videos.** Cada tema pasa por el pipeline normal: guion con Ollama
  (`--model`, por defecto `gemma3:4b`), voz y render. Si un video falla, el
  lote sigue con el siguiente.
- **Resultado.** Queda en `output/_lote/<fecha>/`:
  - `01 - <título>.mp4`, `02 - ...`: los videos numerados.
  - `01 - <título>.txt`: título, descripción y hashtags de ese video.
  - `publicar.txt`: todos los bloques "TÍTULO / DESCRIPCIÓN" juntos, para
    copiar y pegar al publicar.
  - `temas.txt` y `lote.json`: temas y resumen (tiempos, errores).

El guion de un modelo local chico puede colar algún dato inexacto aunque el
tema sea correcto: mira el video antes de publicarlo.

## Assets

- `characters/<personaje>/<emocion>_<personaje>.mp4` — loops de 10 s en verde
  chroma (720x1280, 24 fps), uno por emoción. El guionista solo puede usar
  emociones cuyo clip exista para **ambos** personajes: al añadir un clip
  nuevo (p. ej. `sorpresa_shock`) entra solo, sin tocar código.
- `backgrounds/*.mp4` — uno o más videos de fondo (cualquier tamaño 9:16).
  Cada tema usa siempre el mismo (elegido por un hash del tema, así repetir
  un comando reutiliza la caché); `--background` fuerza uno. El fondo avanza
  de forma continua a lo largo de la conversación; su audio solo se mezcla
  como ambiente con `--bg-volume` > 0 (apagado por defecto). Un
  `background.mp4` suelto en la raíz sigue funcionando si no hay carpeta.

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
`CHARLA_RICK_RVC_PITCH` (+2 por defecto) y `CHARLA_MORTY_RVC_PITCH` (+10),
calibrados sobre la voz fuente `es-MX-DaliaNeural`.
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
defecto), dejando libre la parte superior, donde van los subtítulos en
**Comic Sans Bold** (viene con Windows; si falta se usa Comic Neue de
`assets/fonts/`, luego Arial Bold o DejaVu). Opcional:
`CHARLA_SUB_FONT=assets/fonts/get_schwifty.ttf` usa **Get Schwifty**
(recreación fan del logo de la serie, freeware no comercial); esa fuente
solo trae letras y números, así que el subtítulo se normaliza (sin tildes
ni signos).

## Modo Colab (GPU gratis para todo el pipeline)

[colab/charla_colab.ipynb](colab/charla_colab.ipynb) corre el generador
completo en Google Colab con GPU. El código se **clona de este repo** en cada
sesión; tu Drive (`MyDrive/charla/`) solo aporta lo que no viaja por git:
`characters/`, `backgrounds/` (o un `background.mp4` suelto),
`voices_preview/reales/` y tu `.env`. En Colab el render usa NVENC si el
ffmpeg lo trae (si no, libx264).

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
├── 02_audio/   turn_NN.mp3 + word timings (edge) · turn_NN.cbx.wav
│               (chatterbox) · turn_NN.rvc.wav / .xtts.wav
├── 03_clips/   turn_NN.mp4 + concat + premix
├── final.mp4   720x1280 @ 30fps, H.264 + AAC
├── social.txt  caption + hashtags listos para publicar
└── manifest.json  (incluye motor de voz, encoder y frames por turno)
output/_cache/  ping-pong de personajes, fondos pre-escalados, sondeo de clips
output/_timings.json  duración de cada corrida (voz / render), para la ETA
```

Todo está cacheado por etapa: repetir un comando no regenera lo que no
cambió. La carpeta depende solo de lo que define el **guion** (tema, idioma,
proveedor/modelo, turnos): cambiar chroma, subtítulos, voces o motor de voz
reutiliza el guion y el audio ya generados y solo rehace lo necesario.

## Rendimiento

El render elige solo el encoder más rápido disponible (`CHARLA_VIDEO_ENCODER=auto`:
Intel Quick Sync → NVIDIA NVENC → libx264), renderiza varios turnos a la vez
(`CHARLA_RENDER_JOBS`, por defecto núcleos/2 hasta 3) sobre una copia del
fondo ya escalada a 720x1280 (`CHARLA_BG_PROXY`, se crea una vez por fondo),
y pide las líneas de edge-tts en paralelo (`CHARLA_EDGE_CONCURRENCY`). Cada
turno sale con el número exacto de frames y de muestras de audio, así el
concat sin recodificar no se desfasa.

Medido en un Intel Core Ultra 7 258V (Arc 140V, 32 GB), demo de 4 turnos
(38,8 s de video) sobre un fondo HEVC 1080p, con caches calientes:

| Corrida | Antes | Ahora |
|---|---|---|
| edge-tts: voz | 4,8 s | 1,6 s |
| edge-tts: render | 19,2 s | 8,5 s |
| edge-tts: total | 24,8 s | 10,4 s |
| chatterbox: render | 22,2 s | 7,4 s |
| chatterbox: voz | 213,6 s (CPU) | 120 s (GPU Arc, XPU) |
| chatterbox: total | 238,5 s | 127 s |

La primera vez con cada fondo se suma su pre-escalado (~20 s para 3 min de
1080p HEVC).

**Chatterbox en la GPU Intel (XPU).** En CPU la voz clonada va a ~5,7 s de
cómputo por segundo de audio, igual con 4 que con 8 hilos. Con
`.\install-chatterbox.ps1 -Xpu` (venv aparte `.chatterbox-xpu-venv` con
PyTorch 2.6 XPU; el de CPU no se toca) baja a ~3,4 s: ~1,7× más rápido por
línea. La primera línea de cada corrida tarda ~20 s más mientras compila los
kernels de la GPU. Para usarlo, en `.env`:

```
CHARLA_CHATTERBOX_PYTHON=.chatterbox-xpu-venv/Scripts/python.exe
```

Si además usas Ollama, `CHARLA_OLLAMA_KEEP_ALIVE=0` libera el modelo de
texto en cuanto termina el guion, para que no compita por la memoria
compartida de la GPU. `scripts/bench_chatterbox.py` mide cualquier
combinación (`--device cpu|xpu --threads N`) y deja wavs en `output/_bench/`
para comparar a oído.

### Ollama (guion local)

`--text-provider ollama` (o `auto` sin claves de API) escribe el guion con un
modelo local vía `OLLAMA_HOST` (por defecto `127.0.0.1:11434`) y la misma
salida estructurada que Claude/Gemini. Si el guion sale largo (más de 160
palabras) se reintenta una vez pidiéndole acortarlo. Probado en el mismo
equipo (Ollama 0.40, Arc 140V, prompt real):

| Modelo | Tiempo | Resultado |
|---|---|---|
| `gemma3:4b` (por defecto) | ~1 min | JSON válido; tiende a alargarse (reintento automático) |
| `gpt-oss:20b` | ~2,5 min | JSON válido, largo correcto, contenido más flojo |
| `qwen3:8b`, `llama3.1:8b` | — | fallan con el prompt largo ("token repeat limit") |

Variables: `CHARLA_OLLAMA_MODEL`, `CHARLA_OLLAMA_NUM_CTX`,
`CHARLA_OLLAMA_TIMEOUT`, `CHARLA_OLLAMA_KEEP_ALIVE`, `CHARLA_OLLAMA_THINK`
(ver `.env.example`).
