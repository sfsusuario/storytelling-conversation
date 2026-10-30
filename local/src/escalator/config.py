from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from pathlib import Path

from .models import Persona


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
            # inline comment: "ESCALATE_TTS_PROVIDER=edge   # kokoro|edge" -> "edge"
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

# ---------------------------------------------------------------------------
# Timing constants (seconds) — the core spec of the video format
# ---------------------------------------------------------------------------
AUDIO_TRIGGER_DELAY = 0.3   # silence before speech starts in each scene
SCENE_END_DELAY = 0.5       # silence after speech before the transition
TRANSITION_DURATION = 0.5   # total fade-to-black bridge between scenes
FADE_DURATION = 0.25        # half of the transition lives in each adjacent clip

DEFAULT_TEXT_MODEL = "claude-opus-5"
DEFAULT_GEMINI_TEXT_MODEL = "gemini-2.5-flash"
DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"
# Local backends: Ollama for text, Kokoro for voice, diffusers on the Intel
# iGPU (XPU) for images. "auto" prefers the local backend when available.
# Runs live in output/escalera/ (the Conversación modality owns output/ itself)
OUTPUT_ROOT = Path(os.environ.get("ESCALATE_OUTPUT", "output/escalera"))
DEFAULT_TEXT_PROVIDER = os.environ.get("ESCALATE_TEXT_PROVIDER", "auto")
DEFAULT_OLLAMA_TEXT_MODEL = os.environ.get("ESCALATE_OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_HOST = normalize_ollama_host(os.environ.get("OLLAMA_HOST"))
DEFAULT_IMAGE_PROVIDER = os.environ.get("ESCALATE_IMAGE_PROVIDER", "auto")
IMAGE_PROVIDERS = ["auto", "flux-kontext", "sdxl-face", "gemini"]
DEFAULT_TTS_PROVIDER = os.environ.get("ESCALATE_TTS_PROVIDER", "kokoro")
DEFAULT_KOKORO_VOICE = os.environ.get("ESCALATE_KOKORO_VOICE", "em_alex")
# Scene motion: none | rotate3d | liveportrait (see motion.py)
DEFAULT_MOTION = os.environ.get("ESCALATE_MOTION", "none")
# Narrador por defecto: voz masculina en español, grave y pausada para sonar
# como una persona mayor (edge-tts no trae voces "ancianas"; se simula con
# pitch y rate).
DEFAULT_VOICE = os.environ.get("ESCALATE_VOICE", "es-ES-AlvaroNeural")
DEFAULT_VOICE_RATE = os.environ.get("ESCALATE_VOICE_RATE", "-8%")
DEFAULT_VOICE_PITCH = os.environ.get("ESCALATE_VOICE_PITCH", "-12Hz")
DEFAULT_LANGUAGE = os.environ.get("ESCALATE_LANGUAGE", "es")
DEFAULT_WATERMARK = os.environ.get("ESCALATE_WATERMARK", "@sfsusers")
DEFAULT_MUSIC_VOLUME = float(os.environ.get("ESCALATE_MUSIC_VOLUME", "0.25"))
# "synth" = locally synthesized ambience (unique audio, can never be flagged
# by TikTok/YouTube copyright detection). "track" = CC-BY tracks from
# incompetech (legal with credit, but automated detectors may still block).
DEFAULT_MUSIC_SOURCE = os.environ.get("ESCALATE_MUSIC_SOURCE", "track")

# ---------------------------------------------------------------------------
# Ambient background soundscapes — synthesized with ffmpeg (lavfi), one per
# style set. No downloads, no licensing: calm drones/chords tuned to each
# world. Peak levels are similar across sets; the final loudness is governed
# by music_volume when mixing under the narration.
# ---------------------------------------------------------------------------
_STEREO = ",aformat=sample_fmts=fltp:channel_layouts=stereo"
BACKGROUND_SOUNDS = {
    # warm D-minor pad, candlelit hall
    "medieval": "aevalsrc=0.28*sin(2*PI*146.83*t)+0.2*sin(2*PI*220*t)"
                "+0.16*sin(2*PI*293.66*t)+0.12*sin(2*PI*349.23*t):s=44100"
                ",lowpass=f=900,tremolo=f=0.13:d=0.35" + _STEREO,
    # deep ship hum with a slow shimmer
    "scifi": "aevalsrc=0.3*sin(2*PI*55*t)+0.2*sin(2*PI*110*t)"
             "+0.12*sin(2*PI*164.81*t)+0.05*sin(2*PI*440*t):s=44100"
             ",lowpass=f=1200,tremolo=f=0.2:d=0.25" + _STEREO,
    # soft Cmaj7 office pad
    "corporate": "aevalsrc=0.24*sin(2*PI*130.81*t)+0.18*sin(2*PI*164.81*t)"
                 "+0.16*sin(2*PI*196*t)+0.12*sin(2*PI*246.94*t):s=44100"
                 ",lowpass=f=1000,tremolo=f=0.1:d=0.3" + _STEREO,
    # ethereal open fifths, slow celestial beat
    "mythology": "aevalsrc=0.26*sin(2*PI*98*t)+0.2*sin(2*PI*146.83*t)"
                 "+0.14*sin(2*PI*196*t)+0.1*sin(2*PI*294.5*t):s=44100"
                 ",lowpass=f=1100,tremolo=f=0.1:d=0.4" + _STEREO,
    # low steady pulse, distant drums feel
    "military": "aevalsrc=0.32*sin(2*PI*73.42*t)+0.2*sin(2*PI*110*t)"
                "+0.08*sin(2*PI*146.83*t):s=44100"
                ",lowpass=f=700,tremolo=f=0.45:d=0.6" + _STEREO,
    # ocean waves (filtered brown noise swelling slowly)
    "pirate": "anoisesrc=color=brown:sample_rate=44100:amplitude=0.7"
              ",lowpass=f=450,tremolo=f=0.1:d=0.75" + _STEREO,
    # mysterious detuned pad
    "arcane": "aevalsrc=0.24*sin(2*PI*110*t)+0.16*sin(2*PI*164.81*t)"
              "+0.14*sin(2*PI*220.6*t)+0.1*sin(2*PI*246.94*t):s=44100"
              ",lowpass=f=1200,tremolo=f=0.11:d=0.35" + _STEREO,
    # neutral cinematic drone
    "epochs": "aevalsrc=0.26*sin(2*PI*130.81*t)+0.18*sin(2*PI*196*t)"
              "+0.12*sin(2*PI*261.63*t):s=44100"
              ",lowpass=f=1000,tremolo=f=0.1:d=0.3" + _STEREO,
    # smooth Fmaj7 lounge pad
    "wealth": "aevalsrc=0.24*sin(2*PI*87.31*t)+0.18*sin(2*PI*130.81*t)"
              "+0.14*sin(2*PI*174.61*t)+0.12*sin(2*PI*220*t):s=44100"
              ",lowpass=f=900,tremolo=f=0.1:d=0.3" + _STEREO,
    # clean synth pad with a gentle pulse
    "tech": "aevalsrc=0.26*sin(2*PI*110*t)+0.16*sin(2*PI*220*t)"
            "+0.1*sin(2*PI*330*t):s=44100"
            ",lowpass=f=1400,tremolo=f=0.3:d=0.4" + _STEREO,
    # tense low drone with a slow dissonant beating
    "anger": "aevalsrc=0.3*sin(2*PI*82.41*t)+0.22*sin(2*PI*110*t)"
             "+0.18*sin(2*PI*116.54*t):s=44100"
             ",lowpass=f=600,tremolo=f=0.1:d=0.3" + _STEREO,
}
# descending minor drone with a slow sub pulse and a sour detuned overtone
BACKGROUND_SOUNDS["descenso"] = (
    "aevalsrc=0.32*sin(2*PI*41.2*t)+0.2*sin(2*PI*61.74*t)"
    "+0.12*sin(2*PI*123.47*t)+0.06*sin(2*PI*131*t):s=44100"
    ",lowpass=f=500,tremolo=f=0.07:d=0.45" + _STEREO)
# uneasy dissonant shimmer (tritone + detuned high partial) with a nervous flutter
BACKGROUND_SOUNDS["locura"] = (
    "aevalsrc=0.26*sin(2*PI*110*t)+0.18*sin(2*PI*155.56*t)"
    "+0.08*sin(2*PI*466.16*t)+0.06*sin(2*PI*470*t):s=44100"
    ",lowpass=f=1600,tremolo=f=5.5:d=0.35" + _STEREO)
BACKGROUND_SOUNDS["_default"] = BACKGROUND_SOUNDS["epochs"]


def background_graph(style_set: str) -> str:
    return BACKGROUND_SOUNDS.get(style_set) or BACKGROUND_SOUNDS["_default"]

LANGUAGE_NAMES = {
    "es": "español",
    "en": "English",
    "pt": "português",
    "fr": "français",
    "de": "Deutsch",
    "it": "italiano",
}

# Word shown in the top-of-frame level indicator, per language
LEVEL_WORDS = {
    "es": "NIVEL", "en": "LEVEL", "pt": "NÍVEL",
    "fr": "NIVEAU", "de": "STUFE", "it": "LIVELLO",
}
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30
DEFAULT_STAGES = 5

# Curated edge-tts voices offered in the UI dropdown (any edge-tts voice works via CLI)
CURATED_VOICES = [
    "es-ES-AlvaroNeural",
    "es-MX-JorgeNeural",
    "es-AR-TomasNeural",
    "es-ES-ElviraNeural",
    "es-MX-DaliaNeural",
    "en-US-ChristopherNeural",
    "en-US-GuyNeural",
    "en-US-AriaNeural",
    "en-GB-RyanNeural",
    "en-GB-SoniaNeural",
]

# Kokoro voices (prefix: language + gender). Spanish has only these three.
KOKORO_VOICES = ["em_alex", "ef_dora", "em_santa",
                 "am_michael", "af_heart", "bm_george", "bf_emma"]

# ---------------------------------------------------------------------------
# Style sets — each is an escalation ladder of 5 personas, level 1 -> 5.
# Adding a new set is just a new dict entry; nothing else changes.
# ---------------------------------------------------------------------------
STYLE_SETS: dict[str, list[Persona]] = {
    "medieval": [
        Persona(1, "Everyday Casual Person",
                "Plain modern everyday speech. Contractions, filler-free but relaxed, "
                "the way a friend would blurt it out.",
                "modern casual clothing (hoodie or t-shirt), an ordinary living room or "
                "street background, soft natural daylight, candid smartphone-photo realism"),
        Persona(2, "Contemporary Intellectual",
                "Measured, articulate modern prose of a public intellectual or philosopher. "
                "Precise vocabulary, a hint of abstraction, calmly persuasive.",
                "turtleneck and tweed blazer, a book-lined study with warm lamplight, "
                "shallow depth of field, refined editorial-portrait photography"),
        Persona(3, "Medieval Nobility",
                "Courtly late-medieval English of a noble. Formal address, elegant phrasing, "
                "genteel words such as 'pray' and 'henceforth'.",
                "rich velvet doublet with gold embroidery and a fur-trimmed cloak, a castle "
                "great hall with tapestries and candelabra, warm candlelight, oil-painting style"),
        Persona(4, "Medieval Knight",
                "Commanding chivalric speech of a sworn knight. Oaths, honor, resolve; "
                "forceful archaic English ('thou shalt', 'by my sword').",
                "polished steel plate armor with a heraldic tabard, a castle courtyard with "
                "banners, dramatic overcast light, epic realistic fantasy painting"),
        Persona(5, "Sovereign King",
                "A royal decree. Majestic plural ('We command'), absolute authority, ornate "
                "proclamation language sealed with finality.",
                "ermine-trimmed royal robes, jeweled crown and scepter, a golden throne room "
                "with stained glass, god-rays of golden light, grand renaissance royal portrait"),
    ],
    "scifi": [
        Persona(1, "Everyday Casual Person",
                "Plain modern everyday speech. Contractions, relaxed, offhand.",
                "modern casual clothing, an ordinary apartment background, soft natural "
                "daylight, candid smartphone-photo realism"),
        Persona(2, "Starship Engineer",
                "Pragmatic technical jargon of a ship engineer. Systems, power couplings, "
                "procedure — clipped and competent.",
                "utilitarian engineering jumpsuit with tool harness, a starship engine room "
                "with glowing conduits, cool teal practical lighting, gritty sci-fi realism"),
        Persona(3, "Fleet Officer",
                "Crisp naval-style professionalism of a bridge officer. Protocol, rank, "
                "formal directives.",
                "fitted fleet officer uniform with rank insignia, a starship bridge with "
                "holographic displays, clean white-blue lighting, polished cinematic sci-fi"),
        Persona(4, "Fleet Admiral",
                "Weighty strategic authority of a fleet admiral. Grand-scale vocabulary, "
                "orders that move armadas.",
                "decorated admiral dress uniform with medals and command cape, a flagship "
                "war room overlooking a fleet through a viewport, dramatic rim lighting, "
                "epic sci-fi concept art"),
        Persona(5, "Galactic Emperor",
                "Absolute imperial decree spanning star systems. Cosmic scope, cold majesty, "
                "the voice of an empire.",
                "obsidian-and-gold imperial regalia with a high collar and luminous sigils, "
                "a colossal throne hall aboard a star fortress with a galaxy visible beyond, "
                "otherworldly backlighting, majestic sci-fi splash art"),
    ],
    "corporate": [
        Persona(1, "Intern",
                "Eager, slightly nervous office-newbie speech. Apologetic hedges, "
                "upbeat informality.",
                "wrinkled business-casual shirt with a lanyard ID badge, an open-plan office "
                "cubicle with sticky notes, flat fluorescent lighting, candid office photo"),
        Persona(2, "Middle Manager",
                "Meeting-speak with light corporate jargon: 'align', 'circle back', "
                "'action this'. Polite but directive.",
                "off-the-rack suit without tie, a glass meeting room with a whiteboard, "
                "neutral office lighting, corporate stock-photo realism"),
        Persona(3, "Executive",
                "Polished executive communication. Strategic vocabulary, confident brevity, "
                "boardroom gravitas.",
                "tailored designer suit with a silk tie, a corner office with a city view, "
                "warm late-afternoon window light, premium editorial business portrait"),
        Persona(4, "CEO",
                "Visionary keynote authority. Sweeping declarations about markets and "
                "the future, quotable and absolute.",
                "immaculate black suit, a keynote stage with a giant screen and spotlights, "
                "dramatic stage lighting, high-contrast press-photo style"),
        Persona(5, "Global Tycoon",
                "Olympian pronouncements of someone who owns industries. Detached, "
                "world-shaping language, empire-scale certainty.",
                "bespoke three-piece suit with a gold pocket watch, a penthouse overlooking "
                "the city at night beside a private jet window, moody cinematic low-key "
                "lighting, opulent magazine-cover portrait"),
    ],
    "mythology": [
        Persona(1, "Village Peasant",
                "Humble, earthy rural speech. Simple words, homespun comparisons.",
                "rough-spun linen tunic, a rustic ancient village with clay houses and "
                "chickens, dusty golden-hour light, classical genre-painting realism"),
        Persona(2, "Temple Priest",
                "Reverent liturgical speech. Blessings, omens, invocations of the gods.",
                "white ceremonial robes with a laurel wreath, a marble temple interior with "
                "incense smoke and braziers, soft shafts of light, neoclassical painting"),
        Persona(3, "Demigod Hero",
                "Boastful epic-hero speech in the style of sung legend. Deeds, glory, "
                "destiny.",
                "bronze heroic armor with a lion-skin cloak, a storm-lashed cliff over a "
                "wine-dark sea, dramatic storm light, epic classical mythology painting"),
        Persona(4, "Olympian God",
                "Thunderous divine proclamation. Speaks of mortals from above, "
                "elemental imagery.",
                "flowing god-robes with a radiant aura and golden armbands, the clouded "
                "peak of Olympus with distant earth below, blinding divine light from above, "
                "grand baroque mythological painting"),
        Persona(5, "Supreme Deity",
                "The voice that shaped creation. Absolute cosmic decree, time and fate "
                "as instruments.",
                "robes woven from starlight and cosmos, an abyss of galaxies and nebulae "
                "bending around the figure, luminous celestial radiance, transcendent "
                "cosmic-divine artwork"),
    ],
    "military": [
        Persona(1, "Fresh Recruit",
                "Jumpy, unsure recruit speech. Short sentences, a nervous 'sir' or two.",
                "ill-fitting basic fatigues and a buzz cut, a muddy boot-camp training yard, "
                "flat gray morning light, documentary photo realism"),
        Persona(2, "Drill Sergeant",
                "Barked drill-sergeant cadence. All command, zero patience, "
                "parade-ground volume in text form.",
                "crisp camouflage uniform with a campaign hat, a barracks parade ground "
                "with recruits in the background, harsh midday sun, sharp military photography"),
        Persona(3, "Field Captain",
                "Terse tactical briefing language. Objectives, coordinates, controlled "
                "urgency.",
                "combat gear with captain's bars over a map table, a forward command tent "
                "with radios, warm lantern light at dusk, gritty war-film cinematography"),
        Persona(4, "General",
                "Grave strategic authority of a theater commander. History-aware, "
                "measured, iron certainty.",
                "dress uniform heavy with service ribbons and stars, a war room with maps "
                "and aides, low dramatic lighting, formal command portrait"),
        Persona(5, "Supreme Commander",
                "Address to nations. Doctrine-defining, absolute, the full weight of "
                "every army behind each word.",
                "immaculate supreme-commander regalia with gold braid and a greatcoat over "
                "the shoulders, a monumental headquarters balcony above massed formations, "
                "epic sunset backlighting, heroic propaganda-poster grandeur"),
    ],
    "pirate": [
        Persona(1, "Deckhand",
                "Green deckhand grumbling. Simple sea-slang, informal, a bit whiny.",
                "ragged striped shirt and rope belt, a swabbed ship deck with buckets and "
                "rigging, overcast sea light, weathered maritime realism"),
        Persona(2, "Seasoned Sailor",
                "Salty veteran sailor talk. Nautical slang, superstitions, easy confidence.",
                "worn leather vest, bandana and small gold earring, the ship's rail with open "
                "ocean behind, bright trade-wind sunlight, adventure-novel illustration"),
        Persona(3, "First Mate",
                "Firm quarterdeck authority just below the captain. Orders the crew, "
                "invokes the captain's will.",
                "long navy coat with brass buttons and a tricorn under the arm, the "
                "quarterdeck wheel at golden hour, warm dramatic light, romantic maritime "
                "painting"),
        Persona(4, "Pirate Captain",
                "Flamboyant pirate-captain menace. Theatrical threats, treasure and "
                "gallows imagery, rolling rhetoric.",
                "extravagant captain's coat with gold trim, plumed hat and cutlass, the "
                "captain's cabin with charts and candlelit treasure, moody candlelight, "
                "swashbuckling cinematic painting"),
        Persona(5, "Pirate King",
                "Sovereign of all free seas. Decrees to every ship afloat, myth-scale "
                "swagger and dominion.",
                "obsidian-black regalia crowned with a jeweled skull diadem, a throne of "
                "anchors and figureheads in a grotto of plundered gold, torchlit with "
                "emerald sea-glow, legendary dark-fantasy seascape art"),
    ],
    "epochs": [
        Persona(1, "Caveman",
                "Primitive caveman speech: broken grammar, very few words, "
                "grunts and simple demands.",
                "rough fur pelts and a bone necklace, a firelit cave with wall "
                "paintings, flickering orange firelight, gritty prehistoric realism"),
        Persona(2, "Roman Citizen",
                "Classical orator style: formal, rhetorical, addressing an "
                "assembly, with a Latin-flavored gravitas.",
                "a white toga with a red sash, the Roman forum with marble "
                "columns, bright Mediterranean sunlight, classical painting realism"),
        Persona(3, "Medieval Scholar",
                "Learned medieval speech: pious, ornate, referencing scrolls "
                "and providence.",
                "dark scholar robes with a hood, a candlelit scriptorium with "
                "manuscripts and quills, warm candlelight, illuminated-manuscript "
                "era realism"),
        Persona(4, "Modern Urbanite",
                "Polished contemporary speech: articulate, efficient, a touch "
                "of corporate-casual vocabulary.",
                "smart-casual blazer over a tee, a neon-lit modern city street "
                "at dusk, cinematic urban lighting, sharp editorial photography"),
        Persona(5, "Year 3000 Human",
                "Transcendent far-future speech: serene, cosmic perspective, "
                "technology and mind fused, almost oracular.",
                "a sleek luminous suit with subtle holographic circuitry, an "
                "orbital city with Earth visible through a vast window, cool "
                "radiant sci-fi light, pristine futuristic cinematic style"),
    ],
    "wealth": [
        Persona(1, "Broke Student",
                "Casual broke-student slang: informal, resigned humor about "
                "having no money.",
                "a worn hoodie, a tiny messy room with instant noodles and "
                "hanging laundry, dim lamp light, candid low-budget realism"),
        Persona(2, "Office Worker",
                "Modest middle-class politeness: practical, budget-aware, "
                "unassuming.",
                "an ironed shirt with a lanyard, a beige office cubicle with a "
                "commuter mug, flat fluorescent light, everyday office realism"),
        Persona(3, "Successful Entrepreneur",
                "Confident startup-founder speech: growth, hustle and "
                "opportunity vocabulary.",
                "a fitted blazer over a brand tee, a bright loft office with "
                "glass walls and a standing desk, airy daylight, modern "
                "editorial photography"),
        Persona(4, "Millionaire",
                "Refined luxury speech: understated power, names comforts "
                "casually, impeccable manners.",
                "a tailored suit with a silk pocket square, the deck of a "
                "yacht at golden hour with a marina behind, warm sunset light, "
                "luxury magazine photography"),
        Persona(5, "Trillionaire Magnate",
                "World-shaping grandiosity: speaks of markets, nations and "
                "planets as personal assets, serene absolute power.",
                "an immaculate black bespoke suit with a subtle gold insignia, "
                "a private orbital penthouse overlooking Earth, dramatic "
                "starlit rim lighting, opulent sci-fi cinematic style"),
    ],
    "tech": [
        Persona(1, "Intern Developer",
                "Nervous junior-dev speech: meme-flavored, hedging, afraid of "
                "breaking production.",
                "an oversized hoodie and headphones around the neck, a "
                "cluttered desk with sticker-covered laptop and energy drinks, "
                "cool monitor glow, candid startup-office realism"),
        Persona(2, "Senior Developer",
                "Precise technical speech: calm, exact jargon, speaks in "
                "systems and edge cases.",
                "a plain tee and mechanical keyboard, a tidy battlestation "
                "with triple monitors and code on screen, ambient LED "
                "backlight, sharp tech-workspace photography"),
        Persona(3, "Software Architect",
                "Systems-thinking speech: diagrams in words, tradeoffs, "
                "diplomatic authority.",
                "a smart shirt with rolled sleeves, a whiteboard wall full of "
                "architecture diagrams, bright meeting-room light, clean "
                "corporate-tech photography"),
        Persona(4, "CTO",
                "Strategic executive-tech speech: roadmaps, scale and vision, "
                "boardroom confidence.",
                "a sleek blazer with no tie, a glass corner office with a "
                "city skyline and dashboards on screens, dusk window light, "
                "premium executive portrait"),
        Persona(5, "Tech Visionary",
                "Keynote-prophet speech: sweeping declarations about the "
                "future of humanity and technology, quotable and messianic.",
                "a minimalist black turtleneck, a vast keynote stage with a "
                "glowing product reveal behind, dramatic single-spot stage "
                "lighting, iconic product-launch photography"),
    ],
    "anger": [
        Persona(1, "Totally Chill",
                "Completely relaxed speech: unbothered, easygoing, almost "
                "amused.",
                "a loose tee and relaxed posture vibe, a cozy sunlit living "
                "room with plants, soft warm daylight, mellow lifestyle "
                "photography"),
        Persona(2, "Mildly Annoyed",
                "Passive-aggressive politeness: forced calm, pointed word "
                "choices, a sigh between the lines.",
                "the same casual clothes slightly tense, a tidy room with one "
                "thing conspicuously out of place, slightly dimmed light, "
                "subtle-tension realism"),
        Persona(3, "Visibly Irritated",
                "Clipped stern speech: short sentences, warnings, patience "
                "running out.",
                "a buttoned jacket, an office with scattered papers and a "
                "ticking clock, harsh cold side light, dramatic realism"),
        Persona(4, "Furious",
                "Thunderous fury: loud declarations, ultimatums, controlled "
                "explosion.",
                "a storm-whipped dark coat, a rooftop under a brewing storm "
                "with wind-blown debris, dramatic red-tinged storm light, "
                "intense cinematic style"),
        Persona(5, "Apocalyptic Rage",
                "Wrath of mythological proportions: speaks like a force of "
                "nature ending the world over this, biblical imagery.",
                "a cloak of embers and ash with glowing eyes accent, a "
                "cracked landscape with fire, lightning and ash rain, "
                "hellish orange-and-black light, epic apocalyptic concept art"),
    ],
    "descenso": [
        Persona(1, "Intact",
                "Ordinary everyday speech, calm, a little tired underneath.",
                "exactly as they are, healthy, untouched",
                escalation="despair",
                face="unchanged, exactly as in the photo"),
        Persona(2, "Worn",
                "Flat and weary: says it like it stopped mattering a while ago.",
                "clearly exhausted and unwell, like after weeks without sleep: "
                "noticeably thinner, shoulders slumped, skin pale and greyish, "
                "clothes wrinkled, stained and unwashed, hair messy and greasy",
                escalation="despair",
                face="pale and drawn, heavy dark circles under the eyes, "
                     "chapped lips, no smile, an empty tired expression"),
        Persona(3, "Haggard",
                "Bitter and hopeless: nothing will improve and it says so.",
                "seriously ill and wasting away, like a long terminal "
                "illness: much thinner and bony, skin grey, dull and blotchy "
                "on every visible part of the body, clothes stained, loose "
                "and threadbare, hair thin and falling out",
                escalation="despair",
                face="gaunt and haggard, grey sallow skin, deeply sunken "
                     "cheeks, bloodshot hollow eyes with dark rings, cracked "
                     "lips, a lifeless stare"),
        Persona(4, "Rotting",
                "Cold nihilism: everything decays, everyone forgets, nothing "
                "was ever worth it.",
                "like a corpse a few days dead, with strong horror makeup: "
                "emaciated, skin grey-green, bruised, blistered and peeling "
                "wherever it shows, dark veins under it, clothes torn and "
                "soiled, hair falling out in patches",
                escalation="despair",
                face="decaying skin, blotched, cracked and peeling, deep "
                     "black hollows around glassy clouded dead eyes, "
                     "skull-like cheekbones, lips shrunken back, deeply "
                     "disturbing"),
        Persona(5, "Remains",
                "The last words of something already gone: calm, final, "
                "chilling.",
                "like a decomposing corpse that is still standing in the same "
                "pose, extreme horror prosthetics: skin rotted black, torn "
                "and sloughing off, bone showing through on the hands and "
                "body, clothes reduced to filthy rotten rags",
                escalation="despair",
                face="a decomposing corpse face, rotted skin torn open over "
                     "the bone, sunken clouded dead eyes, teeth bared through "
                     "missing lips, still recognizably the same person, "
                     "horrifying"),
    ],
    "locura": [
        Persona(1, "Composed",
                "Ordinary everyday speech, calm and reasonable.",
                "exactly as they are, calm and composed, untouched",
                escalation="madness",
                face="unchanged, exactly as in the photo"),
        Persona(2, "Twitchy",
                "Slightly off: talks a bit too fast, laughs at the wrong "
                "moment, repeats a word, insists everything is under control.",
                "visibly on edge and sleep-deprived: tense shoulders, hair "
                "starting to stick out in tufts, collar askew, a few buttons "
                "undone, clothes slightly rumpled",
                escalation="madness",
                face="a strained too-wide smile, eyes a little too open and "
                     "bloodshot, one eyebrow raised, faint dark circles, "
                     "slightly sweaty skin"),
        Persona(3, "Unhinged",
                "Erratic and paranoid: jumps between ideas, hears things, "
                "suspects the listener, giggles mid-sentence, whispers then "
                "shouts.",
                "clearly unstable and unkempt: wild uncombed hair standing "
                "up, clothes dishevelled, half untucked and stained, a "
                "scribbled note or ink smudges on the hands",
                escalation="madness",
                face="a manic grin with teeth showing, wide staring bloodshot "
                     "eyes that do not blink, one eye slightly larger than "
                     "the other, twitching brow, sweat on the forehead"),
        Persona(4, "Deranged",
                "Full delusion: talks to someone who is not there, invents a "
                "grand conspiracy or mission, laughs and sobs in the same "
                "breath, frightening intensity.",
                "like a deranged asylum patient, with strong film makeup: "
                "gaunt, wild matted hair in every direction, clothes torn, "
                "filthy and hanging off, scratches on the arms and neck, "
                "fingernails dirty and broken",
                escalation="madness",
                face="a crazed distorted grin stretched far too wide, bulging "
                     "bloodshot eyes with tiny pupils staring in slightly "
                     "different directions, veins standing out on the "
                     "temples, drool at the corner of the mouth, hair "
                     "plastered to a sweaty forehead, deeply unsettling"),
        Persona(5, "Gone",
                "Total madness: an eerily calm, singsong voice saying "
                "something that makes no sense yet feels like a threat, "
                "one chilling line.",
                "like a monster of pure insanity in extreme horror makeup: "
                "emaciated, hair torn out in patches, skin pale and bruised, "
                "clothes shredded rags, nails cracked and bloody from "
                "scratching, body rigid and trembling in the same pose",
                escalation="madness",
                face="a horrifying inhuman grin splitting the face from ear "
                     "to ear, eyes huge, black-ringed and completely wild, "
                     "one pupil blown wide, skin pale with burst capillaries, "
                     "scratches across the cheeks, still recognizably the "
                     "same person, terrifying"),
    ],
    "arcane": [
        Persona(1, "Curious Apprentice",
                "Excitable apprentice chatter. Half-understood terms, wide-eyed wonder.",
                "ink-stained novice robes with an overstuffed satchel of scrolls, a cluttered "
                "wizard's workshop, warm candlelight, cinematic fantasy realism with "
                "storybook charm"),
        Persona(2, "Scholar Mage",
                "Precise academic magical terminology. Cites principles and treatises, "
                "lecture-hall cadence.",
                "neat scholarly robes with a silver amulet, a grand arcane library with "
                "floating books, cool moonlit windows and candle glow, detailed fantasy "
                "illustration"),
        Persona(3, "Archmage",
                "Authoritative high-magic speech. Wields terminology like instruments, "
                "quiet immense power.",
                "layered archmage vestments with glowing runes and an ornate staff, a "
                "sanctum with orbiting crystals and sigils in the air, arcane blue-violet "
                "light, painterly epic fantasy"),
        Persona(4, "Sorcerer Lord",
                "Imperious dark-sovereign proclamation. Dominion over forces and realms, "
                "veiled threat in every clause.",
                "regal sorcerer-lord armor-robes with a floating crown of shards, a citadel "
                "balcony over a storm of raw magic, crackling violet storm light, dramatic "
                "dark-fantasy concept art"),
        Persona(5, "God of Magic",
                "The primal voice of magic itself. Reality-defining decree, laws of nature "
                "as clauses.",
                "a form woven of pure spell-light and constellations, an infinite astral "
                "plane of runic rings and shattered realities, blinding prismatic radiance, "
                "transcendent cosmic fantasy masterpiece"),
    ],
    # Absurdity ladder: same situation, ever more ridiculous excuses told
    # deadpan. Each level pins an excuse category so text and image agree.
    "excuses": [
        Persona(1, "Ordinary Excuse",
                "A believable everyday excuse said casually: traffic, the "
                "alarm, the bus. Completely normal.",
                "everyday casual clothes with a backpack, a busy city street "
                "at morning rush hour with cars and a bus stop, natural "
                "overcast daylight, candid street photography",
                escalation="absurdity"),
        Persona(2, "Suspiciously Specific",
                "An oddly detailed chain of small mishaps told with nervous "
                "sincerity (a pigeon, a broken shoelace, the neighbor's "
                "parrot). Still technically possible.",
                "a slightly disheveled outfit with a coffee stain and an "
                "untied shoelace, a chaotic apartment doorway with spilled "
                "groceries and a curious pigeon on the railing, warm messy "
                "morning light, comedic lifestyle photography",
                escalation="absurdity"),
        Persona(3, "Animal Chaos",
                "An absurd excuse about runaway animals blocking the way "
                "(escaped llamas, a parade of flamingos, a goat that took the "
                "bus), told completely straight-faced.",
                "rumpled commuter clothes covered in feathers and hay, a city "
                "street overrun by escaped llamas, flamingos and goats around "
                "stopped traffic, bright chaotic daylight, comedic cinematic "
                "realism",
                escalation="absurdity"),
        Persona(4, "Mythical Disaster",
                "An epic fantasy excuse (a dragon swallowed the metro, a "
                "kraken in the subway, a wizard's curse) described as if it "
                "were a routine Tuesday.",
                "scorched office clothes trailing smoke, a subway entrance "
                "being devoured by a huge dragon with fire and swirling "
                "smoke, dramatic orange fire light, epic fantasy blockbuster "
                "style",
                escalation="absurdity"),
        Persona(5, "Cosmic Catastrophe",
                "The most absurd excuse imaginable (the multiverse collapsed, "
                "time folded, alternate versions of themself showed up), "
                "delivered with total seriousness as the obvious reason.",
                "a suit flickering between alternate versions with glitching "
                "edges, a shattered reality of floating city fragments, "
                "portals and multiple copies of the same person, prismatic "
                "cosmic light, mind-bending sci-fi concept art",
                escalation="absurdity"),
    ],
}

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------
REWRITE_SYSTEM_TEMPLATE = """\
You rewrite a short phrase into escalating registers for a social-media video.
Rules:
- Stage 1 IS the original phrase, verbatim — do not rewrite, translate or
  clean it up; return it exactly as given.
- First fill "meaning": what the original phrase really means or wants, in one
  plain sentence. Explain sayings and idioms instead of reading them word by
  word. Build every later stage from that meaning, not from the original words.
{escalation_rules}
- The rewrites will be read aloud by a TTS narrator: no stage directions, no
  quotation marks, no emojis, no markdown — just the spoken words.
- Write EVERY rewrite in {language}, translating from the original phrase's
  language if needed.

Also produce a social post for the finished video (TikTok/Reels/Shorts):
- caption: ONE very short, punchy line in {language} — a hook that makes
  people watch to the end (the video shows the same person {caption_hook}).
  No emojis spam: at most one or two.
- hashtags: 6-8 tags, no # symbol, mixing broad viral tags and niche ones,
  in {language} and English where it helps reach.
"""


# What escalates from stage to stage: (rewrite rules, caption hook).
ESCALATION_RULES = {
    "sophistication": ("""\
- Preserve the core meaning and intent of the original phrase — the idea, not
  the wording.
- From stage 2 on, NEVER repeat, quote or start with the original wording, and
  never just append a sentence to it: say the same idea entirely in the
  persona's own words, so each stage sounds like a different speaker.
- Each rewrite must match its persona's tone, vocabulary, and syntactic complexity,
  and sophistication must strictly increase from stage 1 to the last stage.
- Example (phrase "I'm hungry", military ladder):
  1. I'm hungry.
  2. Sir, my stomach is reporting for duty empty, sir!
  3. Rations are critical; I request immediate resupply before we advance.
  4. Gentlemen, an army marches on its stomach, and mine has halted the campaign.
  5. By supreme command, every kitchen in the realm will mobilize at once: your
     commander's hunger is now a matter of strategic consequence.
- Length grows with sophistication: stage 1 is short and plain (roughly 5-10
  words); each stage gets a little longer and more elaborate than the previous
  one; the final stage may reach two sentences (roughly 25-35 words). Keep it
  speakable and punchy — longer and more refined, but never rambling.""",
                       "saying the phrase with increasing sophistication"),
    "absurdity": ("""\
- Every later stage keeps the SAME situation as the original phrase (e.g.
  being late) but gives a NEW excuse or reason for it, in fresh words: never
  repeat the original wording, never start with it, never just append to it.
- Absurdity must strictly increase: each excuse follows its persona's
  category and is more ridiculous than the previous one; the last stage is
  cosmically absurd.
- Deliver every excuse sincerely and deadpan, as if it were completely normal:
  the humor is the contrast. Plain, conversational language at every stage;
  never sophisticated or poetic.
- Length grows a little each stage: stage 1 is roughly 5-10 words; the final
  stage may reach two sentences (roughly 25-35 words). Keep it speakable and
  punchy, never rambling.
- Example (phrase "I'm late", excuses ladder):
  1. I'm late.
  2. The 7:42 bus left at 7:41, and the driver winked at me as it pulled away.
  3. A goose chased me for three blocks and then stole my left shoe.
  4. A dragon was napping across the bridge and nobody dared to wake it up.
  5. The sun briefly forgot to rise, so by the universe's clock I'm actually
     early.""",
                  "giving increasingly absurd excuses"),
    "despair": ("""\
- Preserve the core meaning of the original phrase, but each stage reads it
  through a darker, more pessimistic mind: stage 2 is weary, stage 3 bitter
  and hopeless, stage 4 cold nihilism (everything rots, everyone forgets,
  nothing ever mattered), stage 5 the final words of something already gone.
- Be harsh and bleak, not poetic or melodramatic: plain, blunt, heavy words.
  Every stage must feel worse than the previous one.
- From stage 2 on, never repeat or quote the original wording; say the same
  idea from that stage's despair.
- Length does NOT grow: every stage stays roughly 6-16 words, short blunt
  sentences. Stage 5 may be a single line that lands like a verdict.
- Dread, emptiness and decay only: NEVER mention self-harm, suicide, wanting
  to die or methods, and never give the viewer instructions. This is horror
  atmosphere for social media, not a cry for help.
- Example (phrase "I'm fine", descenso ladder):
  1. I'm fine.
  2. Fine. Same as yesterday. Same as tomorrow.
  3. Nothing gets better. You just get used to it.
  4. Everything rots. People, plans, memories. Even this.
  5. There was never anyone here to be fine.""",
                "decaying a little more at every level"),
    "madness": ("""\
- Preserve the core meaning of the original phrase, but the SPEAKER loses
  their mind a little more at every stage: stage 2 is slightly off (too fast,
  a wrong laugh, a repeated word, insisting all is under control), stage 3
  erratic and paranoid (jumps between ideas, suspects the listener, giggles
  mid-sentence), stage 4 full delusion (talks to someone who is not there,
  a grand conspiracy or mission, laughs and sobs at once), stage 5 total
  madness: eerily calm, singsong, nonsense that feels like a threat.
- From stage 2 on, never repeat or quote the original wording; say the same
  idea the way that stage's mind would say it.
- Make it unsettling, not cartoonish: no "muahaha", no random words for the
  sake of it; every line still follows a twisted logic of its own. Written
  tics are allowed and encouraged: a repeated word, a sentence that stops
  and restarts, a sudden question to nobody.
- Length does NOT grow much: every stage stays roughly 6-18 words. Stage 5
  may be a single calm line that lands like a threat.
- Dread only: NEVER mention self-harm, suicide, hurting specific people,
  weapons or methods, and never give the viewer instructions. This is horror
  atmosphere for social media, not a cry for help.
- Example (phrase "I'm fine", locura ladder):
  1. I'm fine.
  2. Fine, fine, totally fine. Why, who said I wasn't? Ha. Fine.
  3. I'm fine. They keep asking because they know. You know too, don't you.
  4. Shh. He says I'm fine. He's been saying it all night from inside the wall.
  5. We are all fine in here. Come see.""",
                "slipping a little further into madness at every level"),
}


def build_rewrite_system_prompt(language: str,
                                escalation: str = "sophistication") -> str:
    rules, hook = ESCALATION_RULES[escalation]
    return REWRITE_SYSTEM_TEMPLATE.format(
        language=LANGUAGE_NAMES.get(language, language),
        escalation_rules=rules, caption_hook=hook)

REWRITE_USER_TEMPLATE = """\
Original phrase: "{phrase}"

Rewrite it once per stage below — exactly {count} rewrites, stages 1 to {count}:
{stage_lines}
"""

IMAGE_PROMPT_TEMPLATE = """\
Transform this photo into: {name} ({escalation} level {level} of 5).

KEEP EXACTLY AS IN THE REFERENCE PHOTO — non-negotiable:
- The SAME person: face, facial structure, eyes, skin tone, hair and \
recognizable likeness, rendered with photographic fidelity — NEVER \
cartoonify, caricature or redraw the face.
- Their pose and body position: same posture, same gesture, same action they \
are performing, same camera angle and distance.
- The composition: the subject stays centered and framed exactly like the \
original.

CHANGE ONLY — and here be bold and creative:
- Their clothing, wardrobe and accessories: fully reimagined so the SAME pose \
and action now belong to this persona.
- The environment around them: background, setting, props and lighting \
rebuilt as a rich, detailed world of this level, as if the original scene had \
been transported to this persona's world.

The grandeur should match rank {level} of 5 — humble and mundane at low \
levels, epic and magnificent at high levels, always influenced by this \
level's style: {image_detail}.

Cinematic quality, coherent light on the subject matching the new scene.\
"""


# FLUX Kontext follows short edit instructions; a "transform into" prompt makes
# it redraw the whole scene (new pose, older person), so it gets its own one.
KONTEXT_PROMPT_TEMPLATE = """\
Keep the person exactly where they are, in the exact same pose and body \
position (same arms, hands and legs), same face, same age, same camera angle \
and framing. Change only their clothes and the background to a {name} look: \
{image_detail}. Objects from the new setting stay in the background; do not \
put anything in the person's hands and do not move them. Photorealistic, \
lighting matching the new setting.\
"""


# Ladders whose point IS the face changing ("descenso"): same person, same
# pose, but the body and face follow persona.image_detail / persona.face.
# The edit comes FIRST: Kontext obeys the opening instruction, and a prompt
# that opens with "keep everything" returns the photo untouched (tested).
IMAGE_FACE_PROMPT_TEMPLATE = """\
Make the person in this photo look {image_detail} (level {level} of 5). Their face: {face}. The change must be obvious and strong at a glance, \
rendered as realistic film makeup and prosthetics.

While doing so, keep from the reference photo: the same person, still \
recognizable; the exact same pose, head angle, gaze, arms and hands; the \
same camera angle, crop and framing; the same background and lighting. \
Photorealistic.\
"""

KONTEXT_FACE_TEMPLATE = """\
Make this person look {image_detail}. Their face: {face}. The change must be \
obvious, like realistic film makeup. Same person, same pose, same hands, \
same camera angle, same framing, same background.\
"""


def build_image_prompt(persona: Persona, provider: str = "gemini") -> str:
    if persona.face:
        if provider == "flux-kontext":
            return KONTEXT_FACE_TEMPLATE.format(
                face=persona.face, image_detail=persona.image_detail)
        return IMAGE_FACE_PROMPT_TEMPLATE.format(
            level=persona.level, face=persona.face,
            image_detail=persona.image_detail)
    if provider == "flux-kontext":
        return KONTEXT_PROMPT_TEMPLATE.format(name=persona.name,
                                              image_detail=persona.image_detail)
    return IMAGE_PROMPT_TEMPLATE.format(
        name=persona.name, level=persona.level,
        escalation=persona.escalation, image_detail=persona.image_detail)


# ---------------------------------------------------------------------------
# Options shared by CLI and UI — single source of defaults
# ---------------------------------------------------------------------------
@dataclass
class PipelineOptions:
    base_image: Path = None  # required
    phrase: str = ""         # required
    style_set: str = "random"            # set name | "random" | "mix"
    seed: int | None = None
    stages: int = DEFAULT_STAGES
    styles: list[str] | None = None      # manual persona-name override, bypasses sets
    voice: str = DEFAULT_VOICE
    voice_rate: str = DEFAULT_VOICE_RATE     # e.g. "-8%" (slower = older)
    voice_pitch: str = DEFAULT_VOICE_PITCH   # e.g. "-12Hz" (deeper = older)
    language: str = DEFAULT_LANGUAGE         # language of rewrites + narration
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    fit: str = "crop"                    # crop (TikTok fill) | blur | pad
    watermark: str = DEFAULT_WATERMARK   # bottom-left text; "" disables it
    subtitles: bool = True               # burn narration subtitles into the video
    music_volume: float = DEFAULT_MUSIC_VOLUME  # 0 disables background sound
    music_source: str = DEFAULT_MUSIC_SOURCE    # synth | track
    output_dir: Path | None = None       # default derived from input hash
    dry_run: bool = False
    test_mode: bool = False              # skip Gemini images: cheap run (Claude + free TTS only)
    force: bool = False
    force_from: str | None = None        # text | images | tts | render
    reencode_concat: bool = False
    text_provider: str = DEFAULT_TEXT_PROVIDER  # auto | ollama | claude | gemini
    text_model: str = DEFAULT_TEXT_MODEL
    image_provider: str = DEFAULT_IMAGE_PROVIDER  # auto | flux-kontext | sdxl-face | gemini
    image_model: str = DEFAULT_IMAGE_MODEL
    tts_provider: str = DEFAULT_TTS_PROVIDER    # kokoro | edge
    motion: str = DEFAULT_MOTION              # none | rotate3d | liveportrait
    # Scene ids whose image / motion clip should be redone as a new variation.
    reroll_images: list[str] = field(default_factory=list)
    reroll_motion: list[str] = field(default_factory=list)
    # Prompts the user wrote for a scene's image reroll, by scene id.
    image_prompts: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Persona resolution: set / random / mix / manual, with even-spacing for N<5
# ---------------------------------------------------------------------------
def _spaced_indices(total: int, count: int) -> list[int]:
    if count >= total:
        return list(range(total))
    if count == 1:
        return [total - 1]
    return [round(i * (total - 1) / (count - 1)) for i in range(count)]


def resolve_personas(options: PipelineOptions) -> tuple[str, list[Persona]]:
    """Return (set_label, personas) for this run. Deterministic given options.seed."""
    known = {}
    for ladder in STYLE_SETS.values():
        for p in ladder:
            known.setdefault(p.name, p)
    if options.styles and all(n.strip() in known for n in options.styles):
        # Built-in personas pinned by name (e.g. regenerating a past run):
        # keep their real prompts, and the set label when they all share one.
        own = {p.name: p for p in STYLE_SETS.get(options.style_set, [])}
        names = [n.strip() for n in options.styles]
        personas = [own.get(n) or known[n] for n in names]
        return (options.style_set if all(n in own for n in names) else "mix"), personas
    if options.styles:
        personas = [
            Persona(level=i + 1, name=name.strip(),
                    register=f"Speak fully in character as: {name.strip()}. "
                             f"Sophistication level {i + 1} of {len(options.styles)}.",
                    image_detail=f"clothing, background, lighting and art style that fully "
                                 f"embody: {name.strip()}")
            for i, name in enumerate(options.styles)
        ]
        return "custom", personas

    rng = random.Random(options.seed)
    if options.style_set == "mix":
        levels = _spaced_indices(5, min(options.stages, 5))
        # mixing kinds of escalation (sophistication vs absurdity) reads as noise
        pool = [s for s in STYLE_SETS.values() if s[0].escalation == "sophistication"]
        personas = [rng.choice([s[lv] for s in pool]) for lv in levels]
        return "mix", personas

    if options.style_set == "random":
        set_name = rng.choice(sorted(STYLE_SETS))
    else:
        set_name = options.style_set
        if set_name not in STYLE_SETS:
            raise ValueError(
                f"Unknown style set '{set_name}'. "
                f"Available: {', '.join(sorted(STYLE_SETS))}, random, mix")
    ladder = STYLE_SETS[set_name]
    if options.stages > len(ladder):
        raise ValueError(
            f"--stages {options.stages} exceeds the {len(ladder)} levels of set "
            f"'{set_name}'; pass an explicit --styles list instead")
    personas = [ladder[i] for i in _spaced_indices(len(ladder), options.stages)]
    return set_name, personas
