"""The story itself: title, protagonist, N scenes (narration + image prompt),
caption and hashtags, from Ollama, Claude or Gemini as one JSON object.

Same backends and cache discipline as escalator.text_gen, with the story
schema instead of the rewrite ladder.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import BaseModel

from escalator.config import LANGUAGE_NAMES, OLLAMA_HOST
from escalator.text_gen import (TextGenError, UnparseableRewrites, _format_social,
                                resolve_text_backend)

from .config import TONES
from .sources import MAX_WORDS

PROMPT_VERSION = "story-v3"


class StoryScene(BaseModel):
    index: int
    narration: str
    # the picture, taken from the narration: filled as separate fields so a
    # small model covers each one instead of writing a loose sentence
    action: str       # what the protagonist does at this exact moment
    setting: str      # where, time of day
    key_object: str   # the one object or detail the narration hinges on ("" if none)
    shot: str         # camera distance, light, mood

    def visual(self) -> str:
        """The scene's picture in one line (subject added by the caller)."""
        parts = [self.action, self.setting, self.key_object]
        return ", ".join(p.strip() for p in parts if p and p.strip())


class Story(BaseModel):
    # First in the schema on purpose: the model settles the whole arc before
    # writing scenes, so they build to the ending instead of wandering.
    outline: str
    title: str
    protagonist: str
    scenes: list[StoryScene]
    caption: str
    hashtags: list[str]


SYSTEM_TEMPLATE = """\
You write a very short illustrated story for a vertical social video, told in exactly {count} scenes.
First fill "outline": one sentence with the protagonist, what they want, the obstacle and how it ends{outline_tail}.
{tone_rules}
Narration rules: every scene's "narration" is written in {language}, {max_words} words at most, one or two \
sentences read aloud by a narrator: no quotes, emojis, markdown or stage directions. Keep one tense. Every \
scene moves the story forward; the last one closes it.
Protagonist: {protagonist_rule} The protagonist appears in EVERY scene's picture; in a first-person story \
the narrator IS the protagonist.
Each scene's picture, in English, taken literally from that scene's narration (no new events): "action" \
= what the protagonist is doing at that exact moment, present tense, 12 words at most, say "the protagonist"; \
"setting" = place and time of day, 8 words at most; "key_object" = the one object, creature or detail the \
narration hinges on, 5 words at most, or "" if none; "shot" = camera distance (wide, medium, close-up), \
light and mood, 8 words at most. Never names, never text, letters, signs or speech bubbles.
Also fill "title" (in {language}, 6 words at most), "caption" (one hook line in {language} for the video \
description) and "hashtags" (6 to 8, without #).
Answer only with the JSON object.\
"""

INFANTIL_RULES = (
    "Audience: children aged 4 to 9. Warm, simple words. One protagonist with one small problem: they try, "
    "stumble and solve it kindly. Nothing frightening, no violence, no death. The LAST scene states the "
    "moral in one plain sentence.")
GENRE_RULES = {
    "misterio": ("Genre: mystery. Scene 1 raises a question; the middle scenes drop clues; the last scene "
                 "reveals the answer. Adult vocabulary allowed, no explicit content."),
    "terror": ("Genre: horror. Dread builds scene by scene; suggest, never show gore; the last scene lands "
               "a final chill. No explicit content."),
    "humor": "Genre: comedy. A situation escalates scene by scene; the last scene is the punchline.",
    "scifi": ("Genre: science fiction. One speculative idea, its consequence for the protagonist, and a "
              "twist in the last scene."),
}
ADAPT_RULE = (
    "This is an adaptation of a real story given by the user: keep its events, characters, point of "
    "view and ending; compress it into the scenes, do not invent a different plot and do not add a "
    "moral unless the tone asks for one. Never mention Reddit, the author or that it is a post.")
PROTAGONIST_RULES = {
    False: ('fill "protagonist" in English with a short noun phrase (8 words at most) that fits inside a '
            'sentence: article + age or species + gender + one distinctive garment or trait, like "a tired '
            'man in a grey hoodie" or "a small green turtle with a red scarf"; no name, no facial details; '
            'it is reused in every image.'),
    True: ('a real person\'s photo plays the protagonist: fill "protagonist" with their role and outfit '
           'only (12 words at most, in English), never their face, age, hair or body.'),
}


def system_prompt(tone: str, genre: str, count: int, language: str, has_photo: bool,
                  adapted: bool = False) -> str:
    if tone == "infantil":
        rules, tail, max_words = INFANTIL_RULES, ", and the moral", 30
    else:
        rules, max_words = GENRE_RULES[genre], 35
        tail = ", and the reveal" if genre == "misterio" else ", and the twist"
    if adapted:
        rules = f"{ADAPT_RULE}\n{rules}"
    return SYSTEM_TEMPLATE.format(
        count=count, outline_tail=tail, tone_rules=rules, max_words=max_words,
        language=LANGUAGE_NAMES.get(language, language),
        protagonist_rule=PROTAGONIST_RULES[has_photo])


def user_prompt(premise: str, tone: str, genre: str, count: int,
                source: dict | None = None) -> str:
    tone_en, genre_en = TONES[tone][1], TONES[tone][2][genre][1]
    prompt = (f'Premise: "{premise.strip()}"\nTone: {tone_en}. Genre: {genre_en}.\n'
              f'Write exactly {count} scenes, "index" 1 to {count}.')
    if source:
        text = " ".join(source["text"].split()[:MAX_WORDS])
        prompt += (f'\n\nTitle of the real story: "{source["title"]}"\n'
                   f'Real story to adapt (keep its events and ending):\n"""\n{text}\n"""')
    return prompt


def _story_via_claude(system: str, user: str, model: str) -> Story:
    import anthropic

    try:
        response = anthropic.Anthropic().messages.parse(
            model=model, max_tokens=3000, system=system,
            messages=[{"role": "user", "content": user}], output_format=Story)
    except anthropic.AuthenticationError as e:
        raise TextGenError("ANTHROPIC_API_KEY missing or invalid. Set it with:\n"
                           "  $env:ANTHROPIC_API_KEY = 'sk-ant-...'") from e
    except anthropic.APIStatusError as e:
        raise TextGenError(f"Claude API error ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise TextGenError("Could not reach the Claude API; check connectivity.") from e
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise TextGenError("The model declined to write a story for this premise.")
    return response.parsed_output


def _story_via_gemini(system: str, user: str, model: str) -> Story:
    from google import genai
    from google.genai import types

    try:
        response = genai.Client().models.generate_content(
            model=model, contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system, response_mime_type="application/json",
                response_schema=Story))
    except Exception as e:
        raise TextGenError(f"Gemini text API error: {e}") from e
    parsed = response.parsed
    if parsed is None:
        try:
            parsed = Story.model_validate_json(response.text or "")
        except Exception as e:
            raise TextGenError("Gemini returned no parseable story for this premise.") from e
    return parsed


def _story_via_ollama(system: str, user: str, model: str, seed: int | None = None) -> Story:
    """Local generation through Ollama's /api/chat with a JSON-schema format.
    keep_alive=0 unloads the model right after, freeing RAM for the image model."""
    options = {"temperature": 0.8, "num_ctx": 16384}
    if seed is not None:
        options["seed"] = seed
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "format": Story.model_json_schema(),
        "think": "low" if model.startswith("gpt-oss") else False,
        "stream": False,
        "keep_alive": 0,
        "options": options,
    }).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise TextGenError(f"Ollama model '{model}' not found. Pull it with:\n"
                               f"  ollama pull {model}") from e
        detail = e.read().decode("utf-8", "replace")
        raise TextGenError(f"Ollama error ({e.code}): {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise TextGenError(f"Could not reach Ollama at {OLLAMA_HOST}; is it "
                           "running? (ollama serve)") from e
    try:
        return Story.model_validate_json(data["message"]["content"])
    except Exception as e:
        raise UnparseableRewrites("Ollama returned no parseable story; try again "
                                  "or use another model.") from e


def _normalize(story: Story, count: int) -> Story | None:
    """Scenes in order, exactly count of them with text; None when too few."""
    scenes = [s for s in sorted(story.scenes, key=lambda s: s.index)
              if s.narration.strip() and s.action.strip()]
    if len(scenes) < count:
        return None
    scenes = [s.model_copy(update={"index": i + 1, "narration": s.narration.strip()})
              for i, s in enumerate(scenes[:count])]
    return story.model_copy(update={"scenes": scenes})


def generate_story(premise: str, tone: str, genre: str, count: int, model: str,
                   cache_dir: Path, provider: str = "auto", language: str = "es",
                   seed: int | None = None, has_photo: bool = False,
                   keep: bool = False, source: dict | None = None) -> tuple[Story, str]:
    """Return (story, social text). Cached in cache_dir/story.json.
    keep: reuse the cached story even if made with an older prompt or model.
    source: a real story (sources.fetch_story) the LLM adapts instead of
    inventing one; the social text then credits it."""
    provider, model = resolve_text_backend(provider, model)
    system = system_prompt(tone, genre, count, language, has_photo, adapted=source is not None)
    user = user_prompt(premise, tone, genre, count, source)
    key = hashlib.sha256(json.dumps(
        [premise, tone, genre, count, language, has_photo, model, PROMPT_VERSION, system,
         source and source["url"], source and hashlib.sha256(source["text"].encode()).hexdigest()],
        ensure_ascii=False).encode("utf-8")).hexdigest()

    cache_file = cache_dir / "story.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            story = Story.model_validate(cached["story"])
            if cached.get("key") == key or (keep and len(story.scenes) == count):
                return story, cached.get("social", "")
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    story = unparseable = None
    for attempt in range(2 if provider == "ollama" else 1):
        if provider == "ollama":
            try:
                raw = _story_via_ollama(system, user, model,
                                        None if seed is None else seed + attempt)
            except UnparseableRewrites as e:
                unparseable = e
                continue
        elif provider == "claude":
            raw = _story_via_claude(system, user, model)
        else:
            raw = _story_via_gemini(system, user, model)
        story = _normalize(raw, count)
        if story is not None:
            break
    if story is None:
        if unparseable is not None:
            raise unparseable
        raise TextGenError(f"Expected {count} scenes, the model returned fewer; "
                           "try again or pick another text model.")
    social = _format_social(story.caption, story.hashtags, story.title)
    if source:
        social += (f"\n\nHistoria original: u/{source['author']} en r/{source['subreddit']}"
                   f" · {source['url']}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(
        {"key": key, "provider": provider, "model": model, "language": language,
         "story": story.model_dump(), "social": social},
        ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(cache_file)
    return story, social
