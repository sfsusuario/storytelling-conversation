from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import BaseModel

from .config import (DEFAULT_GEMINI_TEXT_MODEL, DEFAULT_LANGUAGE,
                     DEFAULT_OLLAMA_TEXT_MODEL, DEFAULT_TEXT_MODEL,
                     OLLAMA_HOST, REWRITE_USER_TEMPLATE,
                     build_rewrite_system_prompt, has_secret)
from .models import Persona


class TextGenError(RuntimeError):
    pass


class StageRewrite(BaseModel):
    stage: int
    style: str
    rewrite: str


class UnparseableRewrites(TextGenError):
    """The model answered, but not with valid JSON (retryable)."""


class RewriteSet(BaseModel):
    # First in the schema on purpose: the model states what the phrase means
    # before writing, so rewrites follow the idea instead of echoing the words.
    meaning: str
    rewrites: list[StageRewrite]
    caption: str
    hashtags: list[str]


def _have_claude_key() -> bool:
    return has_secret("ANTHROPIC_API_KEY")


def _have_google_key() -> bool:
    return has_secret("GOOGLE_API_KEY", "GEMINI_API_KEY")


def ollama_available() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


def resolve_text_backend(provider: str, model: str) -> tuple[str, str]:
    """Return (provider, model) actually used for text generation.

    provider: "auto" | "ollama" | "claude" | "gemini". In auto mode a running
    local Ollama wins, then Claude when its key is present, then Gemini. The
    model is swapped to the provider's default when it belongs to another one.
    """
    if provider == "auto":
        if ollama_available():
            provider = "ollama"
        elif _have_claude_key():
            provider = "claude"
        elif _have_google_key():
            provider = "gemini"
        else:
            raise TextGenError(
                "No text backend found. Start Ollama (local, free) or set one of:\n"
                "  ANTHROPIC_API_KEY   (Claude)\n"
                "  GOOGLE_API_KEY / GEMINI_API_KEY   (Gemini)\n"
                "in your environment or .env file.")
    if provider == "ollama":
        if model.startswith(("claude", "gemini")):
            model = DEFAULT_OLLAMA_TEXT_MODEL
    elif provider == "claude":
        if not _have_claude_key():
            raise TextGenError(
                "ANTHROPIC_API_KEY missing or invalid. Set it with:\n"
                "  $env:ANTHROPIC_API_KEY = 'sk-ant-...'\n"
                "or use --text-provider gemini to generate texts with the "
                "Google API instead.")
        if not model.startswith("claude"):
            model = DEFAULT_TEXT_MODEL
    elif provider == "gemini":
        if not _have_google_key():
            raise TextGenError(
                "GOOGLE_API_KEY / GEMINI_API_KEY not set (needed for Gemini "
                "text generation). Get a key at https://aistudio.google.com/apikey")
        if not model.startswith("gemini"):
            model = DEFAULT_GEMINI_TEXT_MODEL
    else:
        raise TextGenError(f"Unknown text provider '{provider}' "
                           "(expected auto, ollama, claude or gemini)")
    return provider, model


def _inputs_key(phrase: str, personas: list[Persona], model: str,
                language: str) -> str:
    payload = json.dumps(
        [phrase, model, language, "social-v2",
         build_rewrite_system_prompt(language, personas[-1].escalation)]
        + [[p.name, p.register] for p in personas],
        ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_user_prompt(phrase: str, personas: list[Persona]) -> str:
    stage_lines = "\n".join(
        f"{i + 1}. {p.name} — {p.register}" for i, p in enumerate(personas))
    return REWRITE_USER_TEMPLATE.format(phrase=phrase, stage_lines=stage_lines,
                                        count=len(personas))


def _rewrites_via_claude(phrase: str, personas: list[Persona],
                         model: str, language: str) -> RewriteSet:
    import anthropic

    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=model,
            max_tokens=2000,
            system=build_rewrite_system_prompt(language, personas[-1].escalation),
            messages=[{"role": "user",
                       "content": _build_user_prompt(phrase, personas)}],
            output_format=RewriteSet,
        )
    except anthropic.AuthenticationError as e:
        raise TextGenError(
            "ANTHROPIC_API_KEY missing or invalid. Set it with:\n"
            "  $env:ANTHROPIC_API_KEY = 'sk-ant-...'") from e
    except anthropic.APIStatusError as e:
        raise TextGenError(f"Claude API error ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise TextGenError("Could not reach the Claude API; check connectivity.") from e

    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise TextGenError("The model declined to generate rewrites for this phrase.")
    return response.parsed_output


def _rewrites_via_gemini(phrase: str, personas: list[Persona],
                         model: str, language: str) -> RewriteSet:
    from google import genai
    from google.genai import types

    try:
        client = genai.Client()
        response = client.models.generate_content(
            model=model,
            contents=_build_user_prompt(phrase, personas),
            config=types.GenerateContentConfig(
                system_instruction=build_rewrite_system_prompt(language, personas[-1].escalation),
                response_mime_type="application/json",
                response_schema=RewriteSet,
            ),
        )
    except Exception as e:
        raise TextGenError(f"Gemini text API error: {e}") from e

    parsed = response.parsed
    if parsed is None:
        try:
            parsed = RewriteSet.model_validate_json(response.text or "")
        except Exception as e:
            raise TextGenError(
                "Gemini returned no parseable rewrites for this phrase.") from e
    return parsed


def _rewrites_via_ollama(phrase: str, personas: list[Persona], model: str,
                         language: str, seed: int | None = None) -> RewriteSet:
    """Local generation through Ollama's /api/chat with a JSON-schema format.

    keep_alive=0 unloads the model right after, freeing RAM for the image model.
    """
    options = {"temperature": 0.7, "num_ctx": 16384}
    if seed is not None:
        options["seed"] = seed
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": build_rewrite_system_prompt(language, personas[-1].escalation)},
            {"role": "user", "content": _build_user_prompt(phrase, personas)},
        ],
        "format": RewriteSet.model_json_schema(),
        # gpt-oss can't turn thinking off (it ignores False and can reason until
        # the context is full, leaving no answer); "low" is its lightest level.
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
        return RewriteSet.model_validate_json(data["message"]["content"])
    except Exception as e:
        raise UnparseableRewrites("Ollama returned no parseable rewrites for this "
                                  "phrase; try again or use another model.") from e


def echoes_phrase(phrase: str, rewrite: str) -> bool:
    """True when a rewrite reuses a run of the original's words (4+, or the
    whole phrase if shorter) instead of saying the idea in its own words."""
    words = lambda t: re.findall(r"\w+", t.lower())
    orig, new = words(phrase), " " + " ".join(words(rewrite)) + " "
    run = min(4, len(orig))
    return any(" " + " ".join(orig[i:i + run]) + " " in new
               for i in range(len(orig) - run + 1))


def _format_social(caption: str, hashtags: list[str], phrase: str) -> str:
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in hashtags if t)
    return f'{caption.strip()}\n«{phrase.strip()}»\n\n{tags}'.strip()


def generate_rewrites(phrase: str, personas: list[Persona], model: str,
                      cache_dir: Path, provider: str = "auto",
                      language: str = DEFAULT_LANGUAGE,
                      seed: int | None = None,
                      keep: bool = False) -> tuple[list[str], str]:
    """Return (one rewrite per persona, social caption+hashtags text).

    Cached in cache_dir/rewrites.json; a single API call produces both.
    keep: reuse the cached texts even if made with an older prompt or model.
    """
    provider, model = resolve_text_backend(provider, model)

    cache_file = cache_dir / "rewrites.json"
    key = _inputs_key(phrase, personas, model, language)
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("key") == key or (keep and len(cached["rewrites"]) == len(personas)):
                return cached["rewrites"], cached.get("social", "")
        except (json.JSONDecodeError, KeyError):
            pass

    n = len(personas)
    # Local models sometimes misnumber stages, add one, return too few or echo
    # the original phrase: use the response order, drop extras, and retry once
    # with another seed, keeping the attempt with the fewest echoes.
    best = unparseable = None
    rows: list[str] = []
    for attempt in range(2 if provider == "ollama" else 1):
        if provider == "ollama":
            try:
                result = _rewrites_via_ollama(phrase, personas, model, language,
                                              None if seed is None else seed + attempt)
            except UnparseableRewrites as e:
                unparseable = e
                continue
        elif provider == "claude":
            result = _rewrites_via_claude(phrase, personas, model, language)
        else:
            result = _rewrites_via_gemini(phrase, personas, model, language)
        rows = [r.rewrite for r in sorted(result.rewrites, key=lambda r: r.stage)
                if r.rewrite.strip()]
        if len(rows) < n:
            continue
        echoes = sum(echoes_phrase(phrase, r) for r in rows[1:n])
        if best is None or echoes < best[0]:
            best = (echoes, rows, result)
        if not echoes:
            break
    if best is None:
        if unparseable and not rows:
            raise unparseable
        raise TextGenError(f"Expected {n} rewrites, the model returned {len(rows)}; "
                           "try again or pick another text model.")
    _, rows, result = best
    # An extra row is usually a repeated low stage; keep the top of the ladder.
    rewrites = rows[:1] + rows[len(rows) - n + 1:] if n > 1 else rows[:1]
    if personas[0].level <= 1:
        # Level 1 is reality: the exact original phrase, never a rewrite.
        rewrites[0] = phrase.strip()
    social = _format_social(result.caption, result.hashtags, phrase)

    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(
        {"key": key, "phrase": phrase,
         "personas": [p.name for p in personas],
         "provider": provider, "model": model, "language": language,
         "rewrites": rewrites, "social": social},
        ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(cache_file)
    return rewrites, social
