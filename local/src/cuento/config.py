"""Options, tones and visual styles of the story modality.

Defaults come from Escalera's config (same .env: voice, language, watermark,
providers), except motion: an illustrated story moves by default.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

from escalator.config import (AUDIO_TRIGGER_DELAY, DEFAULT_FPS, DEFAULT_HEIGHT,  # noqa: F401
                              DEFAULT_IMAGE_MODEL, DEFAULT_LANGUAGE,
                              DEFAULT_TEXT_MODEL, DEFAULT_TEXT_PROVIDER,
                              DEFAULT_TTS_PROVIDER, DEFAULT_VOICE,
                              DEFAULT_VOICE_PITCH, DEFAULT_VOICE_RATE,
                              DEFAULT_WATERMARK, DEFAULT_WIDTH, SCENE_END_DELAY)
from escalator.image_local import SDXL_NEGATIVE

# Must stay under output/: the studio's first "/media" mount (Conversación,
# over output/) is what serves these files at /media/cuento/...
OUTPUT_ROOT = Path("output/cuento")
MIN_SCENES, MAX_SCENES, DEFAULT_SCENES = 4, 8, 6

# tone id -> (Spanish label, English name, {genre id: (Spanish label, English name)})
TONES = {
    "infantil": ("Infantil con moraleja", "children's story with a moral", {
        "aventura": ("Aventura", "adventure"),
        "amistad": ("Amistad", "friendship"),
        "animales": ("Animales", "animals"),
        "fantasia": ("Fantasía", "fantasy"),
    }),
    "general": ("Historia corta para todos", "short story for everyone", {
        "misterio": ("Misterio", "mystery"),
        "terror": ("Terror", "horror"),
        "humor": ("Humor", "comedy"),
        "scifi": ("Ciencia ficción", "science fiction"),
    }),
}

# style id -> (Spanish label, English prompt fragment shared by every scene)
STYLE_PRESETS = {
    "acuarela": ("Acuarela infantil",
                 "children's picture book illustration, soft watercolor, warm colors, gentle outlines"),
    "comic": ("Cómic", "bold comic book illustration, clean ink lines, flat vivid colors"),
    "3d": ("Animación 3D", "3D animated film still, Pixar style, soft global illumination"),
    "cine": ("Cinematográfico",
             "cinematic photorealistic still, dramatic lighting, shallow depth of field"),
    "oscuro": ("Ilustración oscura", "dark moody digital painting, muted palette, chiaroscuro"),
    "real": ("Foto realista", "color photograph, natural light, realistic textures, sharp focus, 35mm lens"),
}
IMAGE_PROVIDERS = ["auto", "sdxl", "flux-kontext"]   # sdxl: no photo; flux-kontext: with photo
NEGATIVE = SDXL_NEGATIVE + ", text, letters, caption, signature"
NEGATIVE_REAL = NEGATIVE + ", cartoon, illustration, painting, 3d render, anime, black and white, monochrome, grayscale"
CREDITS_TITLE = "Historias de Reddit"   # end card of a story taken from Reddit


def default_style(tone: str, genre: str, real_story: bool = False) -> str:
    if real_story:
        return "real"      # a Reddit story happened: show it like a photo
    if tone == "infantil":
        return "acuarela"
    return "oscuro" if genre == "terror" else "cine"


def negative_for(style: str) -> str:
    return NEGATIVE_REAL if style == "real" else NEGATIVE


def style_fragment(style: str) -> str:
    return STYLE_PRESETS[style][1]


@dataclass
class StoryOptions:
    premise: str = ""                    # required unless source is set
    source: str = ""                     # Reddit post URL the story adapts (optional)
    preview: bool = False                # stop after the text: review the script first
    tone: str = "infantil"               # infantil | general
    genre: str = "aventura"              # one of TONES[tone]
    style: str = "auto"                  # auto | STYLE_PRESETS id
    scenes: int = DEFAULT_SCENES
    base_image: Path | None = None       # optional protagonist photo (server-only)
    seed: int | None = None
    voice: str = DEFAULT_VOICE
    voice_rate: str = DEFAULT_VOICE_RATE
    voice_pitch: str = DEFAULT_VOICE_PITCH
    language: str = DEFAULT_LANGUAGE
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    fit: str = "crop"
    watermark: str = DEFAULT_WATERMARK
    subtitles: bool = True
    output_dir: Path | None = None       # server-only
    test_mode: bool = False              # placeholder images: quick check of story + voice
    force: bool = False
    force_from: str | None = None        # text | images | tts | motion | render
    text_provider: str = DEFAULT_TEXT_PROVIDER
    text_model: str = DEFAULT_TEXT_MODEL
    image_provider: str = "auto"
    image_model: str = DEFAULT_IMAGE_MODEL
    tts_provider: str = DEFAULT_TTS_PROVIDER
    motion: str = "rotate3d"             # the same 3D parallax as Escalera, on by default
    # Scene ids whose image / motion clip should be redone as a new variation.
    reroll_images: list[str] = field(default_factory=list)
    reroll_motion: list[str] = field(default_factory=list)
    # Prompts the user wrote for a scene's image reroll, by scene id.
    image_prompts: dict[str, str] = field(default_factory=dict)
    # The user's review of the script (title, protagonist, scenes by id with
    # narration / action / setting / key_object / shot / character).
    story_edits: dict = field(default_factory=dict)


CLIENT_OPTIONS = {f.name for f in dataclasses.fields(StoryOptions)} - {
    "base_image", "output_dir"}


def validate(options: StoryOptions) -> None:
    """ValueError for anything the form (or a hand-made request) got wrong."""
    from .sources import valid_url  # sources imports this module
    if not isinstance(options.image_prompts, dict) or not all(
            isinstance(v, str) and len(v) <= 2000 for v in options.image_prompts.values()):
        raise ValueError("image_prompts must map scene ids to text")
    edits = options.story_edits
    scenes = edits.get("scenes", {}) if isinstance(edits, dict) else None
    texts = ([v for k, v in edits.items() if k != "scenes"]
             + [v for sc in scenes.values() for v in sc.values()]
             if isinstance(scenes, dict) and all(isinstance(sc, dict) for sc in scenes.values()) else None)
    if texts is None or not all(isinstance(v, str) and len(v) <= 2000 for v in texts):
        raise ValueError("story_edits must be text fields, up to 2000 characters each")
    if options.source and not valid_url(options.source):
        raise ValueError("source must be a reddit.com post URL")
    if not options.premise.strip() and not options.source:
        raise ValueError("premise must not be empty")
    if options.tone not in TONES:
        raise ValueError(f"tone must be one of {sorted(TONES)}")
    if options.genre not in TONES[options.tone][2]:
        raise ValueError(f"genre must be one of {sorted(TONES[options.tone][2])} for tone {options.tone}")
    if options.style != "auto" and options.style not in STYLE_PRESETS:
        raise ValueError(f"style must be auto or one of {sorted(STYLE_PRESETS)}")
    if not MIN_SCENES <= int(options.scenes) <= MAX_SCENES:
        raise ValueError(f"scenes must be between {MIN_SCENES} and {MAX_SCENES}")
    if options.image_provider not in IMAGE_PROVIDERS:
        raise ValueError(f"image_provider must be one of {IMAGE_PROVIDERS}")
