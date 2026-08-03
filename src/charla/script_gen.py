from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, create_model

from .config import (DEFAULT_GEMINI_TEXT_MODEL, DEFAULT_LANGUAGE,
                     DEFAULT_TEXT_MODEL, SCRIPT_USER_TEMPLATE,
                     build_script_system_prompt)


class ScriptGenError(RuntimeError):
    pass


class DialogueScript(BaseModel):
    """Validated dialogue; `turns[].emotion` is narrowed dynamically."""
    title: str
    turns: list  # replaced by build_script_model with typed turns
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)


def build_script_model(emotions: list[str]) -> type[BaseModel]:
    """DialogueScript whose emotion field only admits clips that exist on
    disk — the structured-output schema itself rejects anything else."""
    EmotionT = Literal[tuple(emotions)]  # type: ignore[valid-type]
    TurnModel = create_model(
        "DialogueTurn",
        speaker=(Literal["rick", "morty"], ...),
        emotion=(EmotionT, ...),
        line=(str, ...),
    )
    return create_model(
        "DialogueScript",
        title=(str, ...),
        turns=(list[TurnModel], ...),
        caption=(str, ...),
        hashtags=(list[str], ...),
    )


def _have_claude_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _have_google_key() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))


def resolve_text_backend(provider: str, model: str) -> tuple[str, str]:
    """Return (provider, model) actually used for script generation.

    provider: "auto" | "claude" | "gemini". In auto mode Claude is preferred
    when its key is present; otherwise Gemini. The model is swapped to the
    provider's default when it clearly belongs to the other provider.
    """
    if provider == "auto":
        if _have_claude_key():
            provider = "claude"
        elif _have_google_key():
            provider = "gemini"
        else:
            raise ScriptGenError(
                "No text API key found. Set at least one of:\n"
                "  ANTHROPIC_API_KEY   (Claude)\n"
                "  GOOGLE_API_KEY / GEMINI_API_KEY   (Gemini)\n"
                "in your environment or .env file.")
    if provider == "claude":
        if not _have_claude_key():
            raise ScriptGenError(
                "ANTHROPIC_API_KEY missing or invalid. Set it with:\n"
                "  $env:ANTHROPIC_API_KEY = 'sk-ant-...'\n"
                "or use --text-provider gemini to write the script with the "
                "Google API instead.")
        if model.startswith("gemini"):
            model = DEFAULT_TEXT_MODEL
    elif provider == "gemini":
        if not _have_google_key():
            raise ScriptGenError(
                "GOOGLE_API_KEY / GEMINI_API_KEY not set (needed for Gemini "
                "script generation). Get a key at https://aistudio.google.com/apikey")
        if model.startswith("claude"):
            model = DEFAULT_GEMINI_TEXT_MODEL
    else:
        raise ScriptGenError(f"Unknown text provider '{provider}' "
                             "(expected auto, claude or gemini)")
    return provider, model


def _inputs_key(source_text: str, emotions: list[str], model: str,
                language: str, system_prompt: str) -> str:
    payload = json.dumps([source_text, model, language, system_prompt,
                          emotions], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _script_via_claude(source_text: str, model: str, system_prompt: str,
                       schema: type[BaseModel]) -> BaseModel:
    import anthropic

    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=model,
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user",
                       "content": SCRIPT_USER_TEMPLATE.format(
                           source_text=source_text)}],
            output_format=schema,
        )
    except anthropic.AuthenticationError as e:
        raise ScriptGenError(
            "ANTHROPIC_API_KEY missing or invalid. Set it with:\n"
            "  $env:ANTHROPIC_API_KEY = 'sk-ant-...'") from e
    except anthropic.APIStatusError as e:
        raise ScriptGenError(f"Claude API error ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ScriptGenError("Could not reach the Claude API; check connectivity.") from e

    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise ScriptGenError("The model declined to write a script for this input.")
    return response.parsed_output


def _script_via_gemini(source_text: str, model: str, system_prompt: str,
                       schema: type[BaseModel]) -> BaseModel:
    from google import genai
    from google.genai import types

    try:
        client = genai.Client()
        response = client.models.generate_content(
            model=model,
            contents=SCRIPT_USER_TEMPLATE.format(source_text=source_text),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
    except Exception as e:
        raise ScriptGenError(f"Gemini text API error: {e}") from e

    parsed = response.parsed
    if parsed is None:
        try:
            parsed = schema.model_validate_json(response.text or "")
        except Exception as e:
            raise ScriptGenError(
                "Gemini returned no parseable script for this input.") from e
    return parsed


def _format_social(caption: str, hashtags: list[str]) -> str:
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in hashtags if t)
    return f"{caption.strip()}\n\n{tags}".strip()


def _validate_script(data: dict, emotions: list[str],
                     min_turns: int) -> None:
    turns = data.get("turns") or []
    if len(turns) < max(2, min_turns // 2):
        raise ScriptGenError(f"Script came back with only {len(turns)} turns.")
    for i, t in enumerate(turns, 1):
        if t["speaker"] not in ("rick", "morty"):
            raise ScriptGenError(f"Turn {i}: unknown speaker {t['speaker']!r}")
        if t["emotion"] not in emotions:
            raise ScriptGenError(
                f"Turn {i}: emotion {t['emotion']!r} has no clip on disk "
                f"(available: {', '.join(emotions)})")
        if not str(t["line"]).strip():
            raise ScriptGenError(f"Turn {i}: empty line")


def generate_script(source_text: str, emotions: list[str], model: str,
                    cache_dir: Path, provider: str = "auto",
                    language: str = DEFAULT_LANGUAGE,
                    min_turns: int = 8, max_turns: int = 12,
                    log=print) -> tuple[dict, str]:
    """Return (script dict with title/turns, social caption+hashtags text).

    Cached in cache_dir/script.json; a single API call produces both.
    """
    provider, model = resolve_text_backend(provider, model)
    system_prompt = build_script_system_prompt(language, emotions,
                                               min_turns, max_turns)
    schema = build_script_model(emotions)

    cache_file = cache_dir / "script.json"
    key = _inputs_key(source_text, emotions, model, language, system_prompt)
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("key") == key:
                log("  script: script.json (cached)")
                return cached["script"], cached.get("social", "")
        except (json.JSONDecodeError, KeyError):
            pass

    if provider == "claude":
        result = _script_via_claude(source_text, model, system_prompt, schema)
    else:
        result = _script_via_gemini(source_text, model, system_prompt, schema)

    data = result.model_dump()
    _validate_script(data, emotions, min_turns)
    script = {"title": data["title"], "turns": data["turns"]}
    social = _format_social(data.get("caption", ""), data.get("hashtags", []))

    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(
        {"key": key, "provider": provider, "model": model,
         "language": language, "script": script, "social": social},
        ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(cache_file)
    return script, social


def load_script_file(path: Path, emotions: list[str]) -> tuple[dict, str]:
    """Manual DialogueScript JSON (no-LLM mode): validate and return it."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ScriptGenError(f"Could not read script file {path}: {e}") from e
    if "turns" not in data:
        raise ScriptGenError(f"{path} has no 'turns' list")
    _validate_script(data, emotions, min_turns=2)
    script = {"title": data.get("title", path.stem), "turns": data["turns"]}
    social = _format_social(data.get("caption", ""), data.get("hashtags", []))
    return script, social
