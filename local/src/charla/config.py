from __future__ import annotations

import hashlib
import os
import random
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env (cwd by default) into os.environ.

    Existing environment variables are never overridden. No dependency needed.
    """
    p = path or Path(".env")
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value[:1] in ('"', "'"):
            value = value[1:].split(value[0], 1)[0]   # quoted: keep as-is
        else:
            # inline comment: "CHARLA_TTS=edge   # edge | xtts" -> "edge"
            value = value.split(" #", 1)[0].split("\t#", 1)[0].strip()
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()


def has_secret(*names: str) -> bool:
    """True when any of the env vars holds a plausible secret.

    Placeholders copied verbatim from .env.example ("sk-ant-...", "...",
    "<tu-clave>") or too-short values count as missing, so auto mode never
    picks a provider whose key is obviously fake.
    """
    for name in names:
        value = os.environ.get(name, "").strip()
        if (len(value) >= 20 and "..." not in value and "…" not in value
                and not (value.startswith("<") and value.endswith(">"))):
            return True
    return False


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _cpu_count() -> int:
    return os.cpu_count() or 2

# ---------------------------------------------------------------------------
# Timing constants (seconds) — the core spec of the video format
# ---------------------------------------------------------------------------
AUDIO_TRIGGER_DELAY = 0.3   # silence before the line starts in each turn
TURN_END_DELAY = 0.4        # silence after the line before the hard cut

DEFAULT_TEXT_MODEL = "claude-opus-5"
DEFAULT_GEMINI_TEXT_MODEL = "gemini-2.5-flash"


def normalize_ollama_host(raw: str | None) -> str:
    """OLLAMA_HOST as a base URL: adds the scheme and default port, and maps
    the server-side bind-all addresses (0.0.0.0, ::) to loopback."""
    value = (raw or "").strip() or "127.0.0.1:11434"
    scheme = "http"
    if "://" in value:
        scheme, value = value.split("://", 1)
    value = value.rstrip("/")
    if value.startswith("["):              # [::1]:11434
        host, _, port = value[1:].partition("]")
        port = port.lstrip(":")
    elif value.count(":") > 1:             # bare IPv6, no port
        host, port = value, ""
    else:
        host, _, port = value.partition(":")
    if host in ("", "0.0.0.0", "::"):
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"{scheme}://{host}:{port or '11434'}"


# Local scriptwriter via Ollama (no API key). gemma3:4b is the default: it
# is the model verified to return valid structured scripts on an Intel Arc
# iGPU (qwen3:8b / llama3.1:8b abort with "token repeat limit" on the long
# prompt there).
DEFAULT_OLLAMA_MODEL = os.environ.get("CHARLA_OLLAMA_MODEL", "gemma3:4b")
OLLAMA_HOST = normalize_ollama_host(os.environ.get("OLLAMA_HOST"))
OLLAMA_NUM_CTX = _env_int("CHARLA_OLLAMA_NUM_CTX", 8192)
OLLAMA_NUM_PREDICT = _env_int("CHARLA_OLLAMA_NUM_PREDICT", 4096)
OLLAMA_TIMEOUT = _env_int("CHARLA_OLLAMA_TIMEOUT", 600)
OLLAMA_KEEP_ALIVE = os.environ.get("CHARLA_OLLAMA_KEEP_ALIVE") or None
# Automatic batch (charla-lote): general theme the topic generator works on.
DEFAULT_BATCH_THEME = os.environ.get("CHARLA_BATCH_THEME",
                                     "ciencia y datos curiosos")
_think = os.environ.get("CHARLA_OLLAMA_THINK", "").strip().lower()
OLLAMA_THINK: bool | str | None = (
    {"true": True, "false": False}.get(_think, _think) if _think else None)

DEFAULT_LANGUAGE = os.environ.get("CHARLA_LANGUAGE", "es")
DEFAULT_WATERMARK = os.environ.get("CHARLA_WATERMARK", "@sfsusers")
DEFAULT_BG_VOLUME = float(os.environ.get("CHARLA_BG_VOLUME", "0.0"))

# Native character-clip resolution; the 576x1024 background upscales cleanly
# (same 9:16 aspect) while the on-screen character needs no rescaling at all.
DEFAULT_WIDTH = 720
DEFAULT_HEIGHT = 1280
# Background video is native 30 fps (dominates perceived motion); the 24 fps
# character loops are retimed with the fps filter.
DEFAULT_FPS = 30

# 7-10 turnos con líneas cortas ≈ 50-60 s de video (tope: 1 minuto)
DEFAULT_MIN_TURNS = 7
DEFAULT_MAX_TURNS = 10

# colorkey (RGB distance) — NOT chromakey: the Veo green is desaturated, so
# in UV space it sits too close to whites/skin and chromakey eats the
# character at any usable similarity. In RGB the margin is wide.
DEFAULT_CHROMA_SIMILARITY = float(
    os.environ.get("CHARLA_CHROMA_SIMILARITY", "0.18"))
DEFAULT_CHROMA_BLEND = float(os.environ.get("CHARLA_CHROMA_BLEND", "0.05"))

CHARACTERS_DIR = Path("characters")

# Shared cross-run cache: ping-pong loops, background proxies, clip probes.
CACHE_DIR = Path("output") / "_cache"

# Background videos live in backgrounds/; each topic gets one of them
# (deterministic per topic, so re-runs reuse their cache). Their own
# soundtrack is only mixed in when bg_volume > 0 (default 0).
BACKGROUNDS_DIR = Path(os.environ.get("CHARLA_BACKGROUNDS", "backgrounds"))
# Early layouts kept a single background.mp4 at the repo root.
_LEGACY_BACKGROUND = Path("background.mp4")


def resolve_background(path: Path | None = None,
                       seed: str | None = None) -> Path:
    """Concrete background video for a run: the given file as-is, or one of
    the .mp4 files inside the given directory (BACKGROUNDS_DIR by default,
    subfolders included).

    With a seed (the run identity) the pick is a stable hash of it, so the
    same topic always lands on the same background; without one it is
    random. Falls back to a legacy root background.mp4 when no backgrounds/
    folder exists.
    """
    p = Path(path) if path else BACKGROUNDS_DIR
    if p.is_file():
        return p
    if p.is_dir():
        # Sorted case-insensitively on posix paths: same order on Windows
        # and Colab, so a seed picks the same file everywhere.
        candidates = sorted((f for f in p.rglob("*.mp4") if f.is_file()),
                            key=lambda f: f.as_posix().lower())
        if candidates:
            if seed is None:
                return random.choice(candidates)
            digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
            return candidates[int(digest, 16) % len(candidates)]
        if path is None and _LEGACY_BACKGROUND.is_file():
            return _LEGACY_BACKGROUND
        raise FileNotFoundError(f"No .mp4 backgrounds in {p}/")
    if path is None and _LEGACY_BACKGROUND.is_file():
        return _LEGACY_BACKGROUND
    raise FileNotFoundError(
        f"Background not found: {p} (put .mp4 files in {BACKGROUNDS_DIR}/ "
        "or pass --background)")

# ---------------------------------------------------------------------------
# Render performance
# ---------------------------------------------------------------------------
# Video encoder: auto probes h264_qsv (Intel Quick Sync) -> h264_nvenc
# (NVIDIA, e.g. Colab T4) -> libx264 and keeps the first that works.
VIDEO_ENCODER = os.environ.get("CHARLA_VIDEO_ENCODER", "auto").strip().lower()
X264_PRESET = os.environ.get("CHARLA_X264_PRESET", "veryfast")
# Turns rendered in parallel (each one its own ffmpeg process).
_jobs = os.environ.get("CHARLA_RENDER_JOBS", "auto").strip().lower()
RENDER_JOBS = (max(1, min(3, _cpu_count() // 2)) if _jobs in ("", "auto")
               else max(1, _env_int("CHARLA_RENDER_JOBS", 1)))
# One-time transcode of the background to the output size/fps with short
# GOPs: turns then seek cheaply and skip the per-frame scale.
BG_PROXY = os.environ.get("CHARLA_BG_PROXY", "1").strip() != "0"
# Concurrent edge-tts requests for uncached turns.
EDGE_TTS_CONCURRENCY = max(1, _env_int("CHARLA_EDGE_CONCURRENCY", 4))

# Character overlay size as a fraction of the frame height; each character
# sits in its own bottom corner (see CharacterSpec.anchor) instead of
# filling the frame.
DEFAULT_CHAR_SCALE = float(os.environ.get("CHARLA_CHAR_SCALE", "0.72"))

# RVC voice conversion (optional): dedicated Python 3.10 venv + models
# downloaded by install-rvc.ps1. The main charla env never imports rvc-python.
RVC_PYTHON = Path(os.environ.get("CHARLA_RVC_PYTHON",
                                 ".rvc-venv/Scripts/python.exe"))
RVC_MODELS_DIR = Path(os.environ.get("CHARLA_RVC_MODELS", "models/rvc"))
RVC_F0_METHOD = os.environ.get("CHARLA_RVC_METHOD", "rmvpe")

# XTTS v2 voice engine (optional): dedicated venv + per-character models
# fine-tuned in the "IA XTTS" Colab (models/xtts/<char>/), with zero-shot
# fallback from the reference clips. Set up with install-xtts.ps1.
XTTS_PYTHON = Path(os.environ.get("CHARLA_XTTS_PYTHON",
                                  ".xtts-venv/Scripts/python.exe"))
XTTS_MODELS_DIR = Path(os.environ.get("CHARLA_XTTS_MODELS", "models/xtts"))
XTTS_REFS_DIR = Path(os.environ.get("CHARLA_XTTS_REFS",
                                    "voices_preview/reales"))
DEFAULT_TTS_ENGINE = os.environ.get("CHARLA_TTS", "edge")  # edge|xtts|chatterbox

# Chatterbox voice engine (optional, MIT license): zero-shot cloning with an
# exaggeration control (0.25..2) — Rick theatrical, Morty nervous-high.
CHATTERBOX_PYTHON = Path(os.environ.get(
    "CHARLA_CHATTERBOX_PYTHON", ".chatterbox-venv/Scripts/python.exe"))
CHATTERBOX_EXAGGERATION = {
    "rick": float(os.environ.get("CHARLA_RICK_EXAGGERATION", "0.7")),
    "morty": float(os.environ.get("CHARLA_MORTY_EXAGGERATION", "0.6")),
}
# Torch device for the cloned-voice workers: auto = cuda -> xpu (Intel Arc,
# only inside an XPU venv) -> cpu.
TTS_DEVICE = os.environ.get("CHARLA_TTS_DEVICE", "auto").strip().lower()
# Torch CPU threads: auto = half the logical cores, which on hybrid Intel
# chips (P + LP E-cores) keeps the work on the fast cores.
_threads = os.environ.get("CHARLA_TORCH_THREADS", "auto").strip().lower()
TORCH_THREADS = (max(1, min(8, _cpu_count() // 2)) if _threads in ("", "auto")
                 else max(1, _env_int("CHARLA_TORCH_THREADS", 4)))

# Caption font. Default: Comic Sans Bold (ships with Windows, comic look,
# full Spanish glyphs). Alternative in the repo: assets/fonts/get_schwifty.ttf
# (the show-logo fan font) — stylish but it only has letters/digits, so with
# it captions are normalized (no accents/punctuation). Falls back to Arial
# Bold when the configured file is missing.
SUBTITLE_FONT = Path(os.environ.get("CHARLA_SUB_FONT",
                                    "C:/Windows/Fonts/comicbd.ttf"))

# ---------------------------------------------------------------------------
# Characters: voice, chroma green (sampled per clip set — Veo greens are not
# pure 0x00FF00) and subtitle color to tell speakers apart.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CharacterSpec:
    name: str            # directory name under characters/
    voice: str           # edge-tts voice
    voice_rate: str      # e.g. "-10%"
    voice_pitch: str     # e.g. "-15Hz"
    chroma_color: str    # 0xRRGGBB green of this character's clips
    sub_color: str       # drawtext fontcolor for this speaker's captions
    anchor: str          # "left" | "right": bottom corner the overlay sits in
    rvc_pitch: int       # RVC f0 transpose in semitones (0 = keep source)
    rvc_source_voice: str  # edge-tts voice fed INTO the converter
    persona: str         # who they are, for the scriptwriter prompt


# edge-tts has no elderly/child Spanish voices and cannot clone the dub
# actors, so these approximate the Latin American dub of the show (Rick:
# Juan Guzmán — deep, gravelly; Morty: Eder La Barrera — light, cracking
# teen). Castilian dub references: Txema Moscoso / Rodri Martín — for that
# flavor use es-ES-AlvaroNeural for rick. Audition candidates with the
# samples in voices_preview/ (see README).
CHARACTERS: dict[str, CharacterSpec] = {
    "rick": CharacterSpec(
        name="rick",
        voice=os.environ.get("CHARLA_RICK_VOICE", "es-MX-JorgeNeural"),
        voice_rate=os.environ.get("CHARLA_RICK_RATE", "-5%"),
        voice_pitch=os.environ.get("CHARLA_RICK_PITCH", "-20Hz"),
        chroma_color="0x358943",
        sub_color="white",
        anchor="right",
        # Measured on the user's real dub clips (voices_preview/reales):
        # Rick latino median f0 ≈ 217 Hz — a strained HIGH voice, not deep.
        # Dalia (≈194 Hz) + 2 semitones lands there with minimal artifacts;
        # a male ~104 Hz source would need +13.
        rvc_pitch=int(os.environ.get("CHARLA_RICK_RVC_PITCH", "2")),
        rvc_source_voice=os.environ.get("CHARLA_RICK_RVC_SOURCE",
                                        "es-MX-DaliaNeural"),
        persona=("científico genio, viejo, nihilista y condescendiente; le "
                 "aburre la estupidez ajena y lo demuestra. Habla con "
                 "seguridad absoluta, desprecia lo obvio y remata con púas "
                 "secas. Explica el tema como si el otro fuera idiota, pero "
                 "lo explica BIEN (el espectador aprende sin darse cuenta)."),
    ),
    "morty": CharacterSpec(
        name="morty",
        voice=os.environ.get("CHARLA_MORTY_VOICE", "es-US-AlonsoNeural"),
        voice_rate=os.environ.get("CHARLA_MORTY_RATE", "+14%"),
        voice_pitch=os.environ.get("CHARLA_MORTY_PITCH", "+30Hz"),
        chroma_color="0x41984D",
        sub_color="0xFFD54A",
        anchor="left",
        # Morty latino median f0 ≈ 336 Hz; from Dalia that's +9.5 semis.
        rvc_pitch=int(os.environ.get("CHARLA_MORTY_RVC_PITCH", "10")),
        rvc_source_voice=os.environ.get("CHARLA_MORTY_RVC_SOURCE",
                                        "es-MX-DaliaNeural"),
        persona=("su ayudante adolescente, ansioso e ingenuo; tartamudea "
                 "cuando se pone nervioso (casi siempre). Hace las preguntas "
                 "que haría el espectador, se espanta por el detalle "
                 "equivocado y a veces da en el clavo sin querer."),
    ),
}

LANGUAGE_NAMES = {
    "es": "español",
    "en": "English",
    "pt": "português",
    "fr": "français",
    "de": "Deutsch",
    "it": "italiano",
}

# ---------------------------------------------------------------------------
# Emotion tone guides — transcribed from the design doc (EMOTIONS.md of the
# original storytelling repo; Plutchik wheel adapted to a comic duo). Keyed
# by the clip-file slug. Only emotions with clips on disk for BOTH
# characters are offered to the scriptwriter.
# ---------------------------------------------------------------------------
EMOTION_PROMPTS: dict[str, str] = {
    "enojo_ira": (
        "Habla con enojo creciente: frases cortas y cortantes, interrupciones, "
        "preguntas retóricas acusatorias («¿en serio me estás diciendo esto?»). "
        "Volumen implícito alto — usa mayúsculas puntuales o signos de "
        "exclamación dobles con moderación. Vocabulario directo, sin rodeos, "
        "algo de sarcasmo hiriente. El personaje busca imponerse o descargar "
        "frustración, no razonar."),
    "miedo_panico": (
        "Habla con miedo o pánico creciente: frases entrecortadas, repeticiones "
        "nerviosas («no, no, no esto no está pasando»), preguntas apresuradas, "
        "muletillas de duda («¿y si...?», «espera, espera»). El ritmo se "
        "acelera, las oraciones se acortan a medida que sube la tensión. Puede "
        "haber negación inicial seguida de aceptación aterrada."),
    "alegria_euforia": (
        "Habla con entusiasmo desbordante: frases exclamativas, superlativos "
        "(«¡esto es lo mejor que me ha pasado en la vida!»), ritmo rápido y "
        "atropellado por la emoción, tendencia a interrumpirse a sí mismo con "
        "nuevas ideas. Optimismo contagioso, poca autocrítica, celebra en voz "
        "alta hasta los detalles pequeños."),
    "tristeza_decepcion": (
        "Habla con desánimo: frases más cortas de lo normal, pausas implícitas "
        "(puntos suspensivos), tono resignado más que dramático. Poco volumen "
        "verbal — el personaje minimiza lo que siente («no importa», «da "
        "igual, ya qué»). Puede haber autocompasión leve o nostalgia por algo "
        "perdido."),
    "sorpresa_shock": (
        "Habla con incredulidad inmediata: la primera reacción es una "
        "interjección corta («¿QUÉ?», «no puede ser»), seguida de preguntas "
        "para confirmar lo que acaba de pasar («espera, ¿estás diciendo "
        "que...?»). El personaje necesita reprocesar la información en voz "
        "alta antes de reaccionar del todo — frases fragmentadas mientras "
        "conecta ideas."),
    "asco_desprecio": (
        "Habla con desdén: comentarios cortos y despectivos, comparaciones "
        "degradantes, tono de superioridad. Usa distancia verbal («eso que tú "
        "haces», en vez de dirigirse directo) y una calma fría más que gritos "
        "— el desprecio se siente en la elección de palabras, no en el "
        "volumen. Ideal para condescendencia del genio hacia su ayudante."),
    "anticipacion_ansiedad": (
        "Habla proyectando hacia adelante: hipótesis encadenadas («y si pasa "
        "esto, entonces...»), preguntas sobre qué va a pasar, urgencia por "
        "decidir o actuar ya. Mezcla de expectativa (cuando es positiva) o "
        "nerviosismo anticipatorio (cuando es negativa) — el personaje está "
        "mentalmente un paso adelante de lo que ocurre en la escena."),
    "confianza_orgullo": (
        "Habla con seguridad absoluta: afirmaciones categóricas sin matices "
        "(«obviamente», «por supuesto que sí»), poca o ninguna pregunta — el "
        "personaje ya tiene todas las respuestas —, tono paternalista o de "
        "autoridad. Puede rayar en la arrogancia; buena base para el genio "
        "condescendiente."),
}

# ---------------------------------------------------------------------------
# Scriptwriter prompts
# ---------------------------------------------------------------------------
SCRIPT_SYSTEM_TEMPLATE = """\
Escribes el guion de un video corto vertical (TikTok/Reels/Shorts): una
CONVERSACIÓN entre dos personajes animados sobre un tema o noticia dada, con
el humor ácido y el ritmo de una caricatura adulta de ciencia ficción
(estilo Rick and Morty en su doblaje latino).

PERSONAJES:
- rick: {rick_persona}
- morty: {morty_persona}

ESTILO — lo más importante; si dudas, elige SIEMPRE la opción más cruel:
- Sarcasmo seco, cinismo, nihilismo y humor negro ligero (muerte,
  insignificancia cósmica, lo absurdo de la existencia — apto para redes,
  sin gore ni groserías fuertes). CERO cursilería, CERO ternura, CERO
  entusiasmo. Este guion NO es tierno; es una caricatura adulta.
- REGLA DURA: cada línea de rick debe contener al menos UNA púa, burla,
  comparación cruel o comentario nihilista. Rick NUNCA valida a morty,
  nunca lo anima, nunca dice nada amable. Sus insultos son creativos y
  específicos del tema, no genéricos. Muletillas: "Morty" al final de frases,
  "escucha", "por el amor de la ciencia".
- rick explica el dato real con desgano, como si le doliera compartir
  oxígeno con alguien tan lento; el universo le parece un chiste malo y lo
  dice.
- morty tartamudea nervioso ("a-ay", "e-eso", "o-o sea"), pregunta lo que
  preguntaría el espectador, se espanta por el detalle equivocado y a veces
  suelta una verdad incómoda que a rick le arruina el argumento.
- LISTA NEGRA (si aparece algo de esto, el guion está mal): "increíble",
  "fascinante", "qué curioso", "¿sabías que?", "amiguitos", "la naturaleza
  es sabia", diminutivos cariñosos, moralejas, cierres tipo "y por eso...",
  celebrar lo aprendido, tono de profesor o documental, emojis,
  exclamaciones encadenadas.
- El dato real del tema debe quedar claro igual: la comedia lo envuelve, no
  lo tapa.
- Nombres: solo rick dice "Morty"; morty se dirige a él como "Rick". Ninguno
  dice su propio nombre.
- Varía las emociones: un mismo personaje no repite la misma emotion en
  turnos consecutivos, y ninguna emotion aparece más de 3 veces en total.

FORMATO Y DURACIÓN (estricto — el video final debe durar MENOS DE 1 MINUTO):
- Entre {min_turns} y {max_turns} turnos, alternando speakers (nunca dos
  seguidos del mismo, salvo el remate final).
- Líneas de 5 a 20 palabras (ideal 10-14). PRESUPUESTO TOTAL: entre 110 y
  140 palabras habladas sumando todos los turnos — ni un guion raquítico ni
  uno que pase del minuto.
- Cada línea es TEXTO HABLADO puro para TTS: sin acotaciones, sin comillas,
  sin markdown.
- Estructura: turno 1 arranca en mitad de la conversación con una reacción
  (nada de presentaciones), desarrollo con 2-3 datos concretos del texto
  fuente, y remate final de rick: seco, cínico, nunca una conclusión bonita.
- El turno 1 lo dice {starter}. Si arranca rick, es él soltando el dato con
  desprecio o quejándose de tener que explicarlo; si arranca morty, es su
  reacción nerviosa o una pregunta a medio susto. En ambos casos suena a
  conversación ya empezada.
- TODO en {language}.
- El campo emotion de cada turno DEBE ser exactamente uno de: {emotion_list}.
  Guía de tono por emoción — aplica la guía a la escritura de esa línea:
{emotion_prompts}

También produce un post social para el video terminado:
- title: título muy corto del tema (3-6 palabras, para archivo/registro).
- caption: UNA línea gancho en {language} con el mismo humor ácido del
  guion, máximo un emoji.
- hashtags: 6-8 tags, sin el símbolo #, mezclando virales amplios y de
  nicho, en {language} e inglés.
"""

SCRIPT_USER_TEMPLATE = """\
Tema / artículo:
\"\"\"{source_text}\"\"\"

Escribe el guion de la conversación.
"""


def build_script_system_prompt(language: str, emotions: list[str],
                               min_turns: int, max_turns: int,
                               starter: str = "morty") -> str:
    lang = LANGUAGE_NAMES.get(language, language)
    prompts = "\n".join(
        f"  - {slug}: {EMOTION_PROMPTS.get(slug, slug.replace('_', ' '))}"
        for slug in emotions)
    return SCRIPT_SYSTEM_TEMPLATE.format(
        rick_persona=CHARACTERS["rick"].persona,
        morty_persona=CHARACTERS["morty"].persona,
        min_turns=min_turns, max_turns=max_turns,
        language=lang, emotion_list=", ".join(emotions),
        emotion_prompts=prompts, starter=starter)


# ---------------------------------------------------------------------------
# Pipeline options
# ---------------------------------------------------------------------------


@dataclass
class PipelineOptions:
    input_text: str = ""                 # free text, or URL when is_url
    script_file: Path | None = None      # manual DialogueScript JSON (no LLM)
    script_feedback: str = ""            # extra instructions when regenerating
    language: str = DEFAULT_LANGUAGE
    min_turns: int = DEFAULT_MIN_TURNS
    max_turns: int = DEFAULT_MAX_TURNS
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    watermark: str = DEFAULT_WATERMARK
    subtitles: bool = True
    bg_volume: float = DEFAULT_BG_VOLUME
    background: Path | None = None       # None = random pick from backgrounds/
    characters_dir: Path = CHARACTERS_DIR
    char_scale: float = DEFAULT_CHAR_SCALE
    chroma_similarity: float = DEFAULT_CHROMA_SIMILARITY
    chroma_blend: float = DEFAULT_CHROMA_BLEND
    tts_engine: str = DEFAULT_TTS_ENGINE  # edge (con rvc opcional) | xtts
    rvc: str = "auto"                    # auto | on | off: dub-voice conversion
    output_dir: Path | None = None
    dry_run: bool = False
    force: bool = False
    force_from: str | None = None        # script | tts | render
    reencode_concat: bool = False
    text_provider: str = "auto"
    text_model: str = DEFAULT_TEXT_MODEL
    # voice overrides (None = CharacterSpec default)
    rick_voice: str | None = None
    rick_rate: str | None = None
    rick_pitch: str | None = None
    morty_voice: str | None = None
    morty_rate: str | None = None
    morty_pitch: str | None = None

    @property
    def is_url(self) -> bool:
        return self.input_text.lower().startswith(("http://", "https://"))
