from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError, create_model

from .config import (DEFAULT_GEMINI_TEXT_MODEL, DEFAULT_LANGUAGE,
                     DEFAULT_MAX_TURNS, DEFAULT_MIN_TURNS,
                     DEFAULT_OLLAMA_MODEL, DEFAULT_TEXT_MODEL, OLLAMA_HOST,
                     OLLAMA_KEEP_ALIVE, OLLAMA_NUM_CTX, OLLAMA_NUM_PREDICT,
                     OLLAMA_THINK, OLLAMA_TIMEOUT, SCRIPT_USER_TEMPLATE,
                     build_script_system_prompt, has_secret)

PROVIDERS = ("claude", "gemini", "ollama")

# Spoken-word budget of the whole dialogue (the prompt asks for 110-140,
# which keeps the video under a minute); above WORD_WARN we warn, and the
# Ollama path retries once asking for a shorter script.
WORD_BUDGET = (110, 140)
WORD_WARN = 160


class ScriptGenError(RuntimeError):
    pass


class ScriptFileError(ScriptGenError, ValueError):
    """A malformed manual --script-file (a usage error, not an API one)."""


class _SchemaMismatch(ScriptGenError):
    pass


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
    return has_secret("ANTHROPIC_API_KEY")


def _have_google_key() -> bool:
    return has_secret("GOOGLE_API_KEY", "GEMINI_API_KEY")


# ---------------------------------------------------------------------------
# Ollama (local models, no key)
# ---------------------------------------------------------------------------


def _ollama_get(path: str, timeout: float = 1.5) -> dict | None:
    import requests
    try:
        r = requests.get(f"{OLLAMA_HOST}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def ollama_reachable(timeout: float = 1.5) -> bool:
    return _ollama_get("/api/version", timeout) is not None


def _ollama_tags(timeout: float = 1.5) -> list[dict] | None:
    data = _ollama_get("/api/tags", timeout)
    return None if data is None else list(data.get("models") or [])


def list_ollama_models(timeout: float = 1.5) -> list[str] | None:
    """Installed models that can write text (embedding models filtered
    out), or None when the Ollama server is unreachable."""
    tags = _ollama_tags(timeout)
    if tags is None:
        return None
    names = []
    for m in tags:
        name = m.get("name") or m.get("model") or ""
        caps = m.get("capabilities")
        if not name:
            continue
        if caps is not None and "completion" not in caps:
            continue
        if caps is None and "embed" in name.lower():
            continue
        names.append(name)
    return sorted(names)


def _tag(name: str) -> str:
    return name if ":" in name else f"{name}:latest"


# ---------------------------------------------------------------------------
# Provider / model resolution
# ---------------------------------------------------------------------------


def _is_ollama_name(model: str | None) -> bool:
    model = (model or "").strip()
    return bool(model) and not model.startswith(("claude", "gemini"))


def model_for(provider: str, model: str | None) -> str:
    """The model to use with `provider`: the requested one when it belongs
    to that provider, else the provider's default."""
    model = (model or "").strip()
    if provider == "claude":
        return model if model.startswith("claude") else DEFAULT_TEXT_MODEL
    if provider == "gemini":
        return model if model.startswith("gemini") else DEFAULT_GEMINI_TEXT_MODEL
    if provider == "ollama":
        return model if _is_ollama_name(model) else DEFAULT_OLLAMA_MODEL
    raise ScriptGenError(f"Unknown text provider '{provider}' "
                         "(expected auto, claude, gemini or ollama)")


def candidate_backends(provider: str, model: str | None
                       ) -> list[tuple[str, str]]:
    """Every (provider, model) a request could resolve to — no network, no
    keys — so a cached script is found before any key/server is required.
    In auto mode a model name that is not claude*/gemini* means Ollama."""
    if provider == "auto":
        if _is_ollama_name(model):
            return [("ollama", model_for("ollama", model))]
        return [(p, model_for(p, model)) for p in PROVIDERS]
    return [(provider, model_for(provider, model))]


def resolve_text_backend(provider: str, model: str | None) -> tuple[str, str]:
    """Return (provider, model) actually used for script generation.

    provider: "auto" | "claude" | "gemini" | "ollama". Auto order: Claude
    key -> Google key -> a running Ollama server. Placeholder keys copied
    from .env.example don't count.
    """
    if provider == "auto":
        if _is_ollama_name(model):
            provider = "ollama"
        elif _have_claude_key():
            provider = "claude"
        elif _have_google_key():
            provider = "gemini"
        elif ollama_reachable():
            provider = "ollama"
        else:
            raise ScriptGenError(
                "No text provider available. Set one of:\n"
                "  ANTHROPIC_API_KEY   (Claude)\n"
                "  GOOGLE_API_KEY / GEMINI_API_KEY   (Gemini)\n"
                "in your environment or .env file, or start Ollama for a "
                f"free local model (default {DEFAULT_OLLAMA_MODEL}).")
    model = model_for(provider, model)
    if provider == "claude":
        if not _have_claude_key():
            raise ScriptGenError(
                "ANTHROPIC_API_KEY missing or invalid. Set it with:\n"
                "  $env:ANTHROPIC_API_KEY = 'sk-ant-...'\n"
                "or use --text-provider gemini / ollama instead.")
    elif provider == "gemini":
        if not _have_google_key():
            raise ScriptGenError(
                "GOOGLE_API_KEY / GEMINI_API_KEY not set (needed for Gemini "
                "script generation). Get a key at https://aistudio.google.com/apikey")
    elif provider == "ollama":
        tags = _ollama_tags()
        if tags is None:
            raise ScriptGenError(
                f"Could not connect to Ollama at {OLLAMA_HOST}: start it (the "
                "Ollama app or `ollama serve`) or install it with "
                "`winget install Ollama.Ollama`.")
        installed = {_tag(m.get("name") or m.get("model") or "") for m in tags}
        if _tag(model) not in installed:
            raise ScriptGenError(
                f"Ollama model '{model}' is not installed: run "
                f"`ollama pull {model}`.")
    return provider, model


def _inputs_key(source_text: str, emotions: list[str], provider: str,
                model: str, language: str, system_prompt: str) -> str:
    payload = json.dumps(["v2", provider, source_text, model, language,
                          system_prompt, emotions], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _legacy_key(source_text: str, emotions: list[str], model: str,
                language: str, system_prompt: str) -> str:
    """Cache key before the provider was part of it (keeps old caches)."""
    payload = json.dumps([source_text, model, language, system_prompt,
                          emotions], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


def _script_via_claude(source_text: str, model: str, system_prompt: str,
                       schema: type[BaseModel]) -> BaseModel:
    import anthropic

    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=model,
            max_tokens=8000,
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
    except ValidationError as e:
        # the SDK validates inside parse(): truncated or non-JSON output
        raise ScriptGenError(
            "Claude returned a script that does not match the schema "
            "(truncated or malformed output); try again.") from e

    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise ScriptGenError("The model declined to write a script for this input.")
    return response.parsed_output


def _retry_transient(fn, log=print, attempts: int = 3):
    """Retry Gemini calls on rate limits / transient server errors (the
    google-genai client does not retry by default)."""
    from google.genai import errors as genai_errors

    for attempt in range(attempts):
        try:
            return fn()
        except genai_errors.APIError as e:
            code = getattr(e, "code", None)
            if code not in (429, 500, 503, 504) or attempt == attempts - 1:
                raise
            delay = 2 * 2 ** attempt
            log(f"  gemini: HTTP {code}, reintento en {delay}s")
            time.sleep(delay)


def _script_via_gemini(source_text: str, model: str, system_prompt: str,
                       schema: type[BaseModel], log=print) -> BaseModel:
    from google import genai
    from google.genai import types

    try:
        client = genai.Client()
        response = _retry_transient(lambda: client.models.generate_content(
            model=model,
            contents=SCRIPT_USER_TEMPLATE.format(source_text=source_text),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        ), log=log)
    except Exception as e:
        hint = (" (quota/rate limit: wait, or use --text-provider ollama)"
                if "429" in str(e) else "")
        raise ScriptGenError(f"Gemini text API error: {e}{hint}") from e

    parsed = response.parsed
    if parsed is None:
        try:
            parsed = schema.model_validate_json(response.text or "")
        except Exception as e:
            raise ScriptGenError(
                "Gemini returned no parseable script for this input.") from e
    return parsed


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def _strip_model_text(content: str) -> str:
    """Drop reasoning blocks and markdown fences some local models add."""
    content = _THINK_RE.sub("", content).strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        content = content.rsplit("```", 1)[0]
    return content.strip()


def _ollama_chat(model: str, system_prompt: str, user: str,
                 schema: type[BaseModel]) -> str:
    """One /api/chat call constrained to the script's JSON schema."""
    import requests

    body: dict = {
        "model": model,
        "stream": False,
        "format": schema.model_json_schema(),
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user}],
        "options": {"temperature": 0.8, "num_ctx": OLLAMA_NUM_CTX,
                    "num_predict": OLLAMA_NUM_PREDICT},
    }
    if OLLAMA_KEEP_ALIVE is not None:
        body["keep_alive"] = OLLAMA_KEEP_ALIVE
    if OLLAMA_THINK is not None:
        body["think"] = OLLAMA_THINK
    try:
        r = requests.post(f"{OLLAMA_HOST}/api/chat", json=body,
                          timeout=(3.05, OLLAMA_TIMEOUT))
    except requests.ConnectionError as e:
        raise ScriptGenError(
            f"Could not connect to Ollama at {OLLAMA_HOST}: start it (the "
            "Ollama app or `ollama serve`).") from e
    except requests.Timeout as e:
        raise ScriptGenError(
            f"Ollama did not answer within {OLLAMA_TIMEOUT}s with {model}: try "
            "a smaller model (gemma3:4b) or raise CHARLA_OLLAMA_TIMEOUT.") from e
    try:
        data = r.json()
    except ValueError:
        data = {}
    error = str(data.get("error") or "")
    if r.status_code != 200 or error:
        low = error.lower()
        if r.status_code == 404 or "not found" in low:
            raise ScriptGenError(f"Ollama model '{model}' is not installed: "
                                 f"run `ollama pull {model}`.")
        if "repeat limit" in low or "prediction aborted" in low:
            raise ScriptGenError(
                f"Ollama model '{model}' got stuck in a repetition loop on this "
                "long prompt (seen with qwen3:8b and llama3.1:8b on Intel "
                "iGPUs). Use gemma3:4b or gpt-oss:20b (--text-model).")
        if "does not support thinking" in low:
            raise ScriptGenError(f"'{model}' does not support thinking: unset "
                                 "CHARLA_OLLAMA_THINK.")
        if "memory" in low:
            raise ScriptGenError(
                f"Not enough memory to run '{model}': use a smaller model or "
                "lower CHARLA_OLLAMA_NUM_CTX.")
        raise ScriptGenError(
            f"Ollama error ({r.status_code}): {error or r.text[:300]}")
    if data.get("done_reason") == "length":
        raise ScriptGenError(
            f"Ollama ({model}) hit the token limit before finishing the "
            "script: raise CHARLA_OLLAMA_NUM_PREDICT / CHARLA_OLLAMA_NUM_CTX.")
    content = _strip_model_text((data.get("message") or {}).get("content") or "")
    if len(content) < 20:
        # Same failure as the 500 "repeat limit" above, reported as a 200
        # with a cut-off body like '{"': retrying the same model won't help.
        raise ScriptGenError(
            f"Ollama model '{model}' aborted after {len(content)} characters "
            "(it loops on this long prompt; seen with qwen3:8b and "
            "llama3.1:8b on Intel iGPUs). Use gemma3:4b or gpt-oss:20b "
            "(--text-model).")
    return content


def _spoken_words(script: BaseModel) -> int:
    return sum(len(str(t.line).split()) for t in script.turns)


def _script_via_ollama(source_text: str, model: str, system_prompt: str,
                       schema: type[BaseModel], log=print) -> BaseModel:
    """Local script with one retry on schema mismatch and one length retry:
    small local models tend to overshoot the word budget."""
    user = SCRIPT_USER_TEMPLATE.format(source_text=source_text)

    def attempt(message: str) -> BaseModel:
        content = _ollama_chat(model, system_prompt, message, schema)
        try:
            return schema.model_validate_json(content)
        except ValidationError as e:
            raise _SchemaMismatch(
                f"Ollama ({model}) returned JSON that does not match the "
                f"script schema: {str(e).splitlines()[0]}") from e

    log(f"  ollama: generando con {model} (local, puede tardar 1-2 min)...")
    try:
        result = attempt(user)
    except _SchemaMismatch:
        log("  ollama: JSON fuera de esquema — reintento")
        result = attempt(user)

    words = _spoken_words(result)
    if words > WORD_WARN:
        lo, hi = WORD_BUDGET
        log(f"  ollama: guion largo ({words} palabras) — reintento para "
            "acortarlo")
        retry = (f"{user}\n\nTu guion anterior tenía {words} palabras "
                 f"habladas; reescríbelo con {lo}-{hi} palabras en total, "
                 "con las mismas reglas.")
        try:
            shorter = attempt(retry)
            if _spoken_words(shorter) < words:
                result = shorter
        except ScriptGenError as e:
            log(f"  ollama: el reintento falló ({e}); se usa el primer guion")
    return result


# ---------------------------------------------------------------------------
# Script stage
# ---------------------------------------------------------------------------


def _format_social(caption: str, hashtags: list[str]) -> str:
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in hashtags if t)
    return f"{caption.strip()}\n\n{tags}".strip()


def _validate_script(data: dict, emotions: list[str],
                     min_turns: int) -> None:
    if not isinstance(data, dict):
        raise ScriptGenError("Script must be a JSON object with a 'turns' list")
    turns = data.get("turns")
    if not isinstance(turns, list):
        raise ScriptGenError("Script has no 'turns' list")
    if len(turns) < max(2, min_turns // 2):
        raise ScriptGenError(f"Script came back with only {len(turns)} turns.")
    for i, t in enumerate(turns, 1):
        if not isinstance(t, dict):
            raise ScriptGenError(
                f"Turn {i}: expected an object with speaker/emotion/line")
        missing = [k for k in ("speaker", "emotion", "line") if k not in t]
        if missing:
            raise ScriptGenError(f"Turn {i}: missing {', '.join(missing)}")
        if t["speaker"] not in ("rick", "morty"):
            raise ScriptGenError(f"Turn {i}: unknown speaker {t['speaker']!r}")
        if t["emotion"] not in emotions:
            raise ScriptGenError(
                f"Turn {i}: emotion {t['emotion']!r} has no clip on disk "
                f"(available: {', '.join(emotions)})")
        if not str(t["line"]).strip():
            raise ScriptGenError(f"Turn {i}: empty line")


@dataclass
class ScriptResult:
    script: dict          # {"title", "turns"}
    social: str           # caption + hashtags
    provider: str         # backend that wrote it
    model: str
    cached: bool = False


def _read_cache(cache_file: Path) -> dict | None:
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def generate_script(source_text: str, emotions: list[str], model: str,
                    cache_dir: Path, provider: str = "auto",
                    language: str = DEFAULT_LANGUAGE,
                    min_turns: int = DEFAULT_MIN_TURNS,
                    max_turns: int = DEFAULT_MAX_TURNS,
                    log=print) -> ScriptResult:
    """Script + social caption from one LLM call, cached in
    cache_dir/script.json.

    The cache is checked BEFORE resolving the backend, so re-rendering a
    cached script needs no API key or running Ollama.
    """
    # Who speaks first: derived from the source text so it varies between
    # topics (roughly 50/50) but stays stable for the same topic — a true
    # random pick would invalidate the script cache on every re-run.
    starter_seed = hashlib.sha256(source_text.encode("utf-8")).digest()[0]
    starter = "rick" if starter_seed % 2 == 0 else "morty"
    system_prompt = build_script_system_prompt(language, emotions,
                                               min_turns, max_turns,
                                               starter=starter)
    schema = build_script_model(emotions)

    cache_file = cache_dir / "script.json"
    cached = _read_cache(cache_file)
    if cached and isinstance(cached.get("script"), dict):
        for p, m in candidate_backends(provider, model):
            keys = {_inputs_key(source_text, emotions, p, m, language,
                                system_prompt)}
            if cached.get("provider") == p:
                keys.add(_legacy_key(source_text, emotions, m, language,
                                     system_prompt))
            if cached.get("key") in keys:
                log(f"  script: script.json (cached, {p}: {m})")
                return ScriptResult(cached["script"], cached.get("social", ""),
                                    p, m, cached=True)

    provider, model = resolve_text_backend(provider, model)
    key = _inputs_key(source_text, emotions, provider, model, language,
                      system_prompt)
    if provider == "claude":
        log(f"  script: generando con claude ({model})...")
        result = _script_via_claude(source_text, model, system_prompt, schema)
    elif provider == "gemini":
        log(f"  script: generando con gemini ({model})...")
        result = _script_via_gemini(source_text, model, system_prompt, schema,
                                    log=log)
    elif provider == "ollama":
        result = _script_via_ollama(source_text, model, system_prompt, schema,
                                    log=log)
    else:
        raise ScriptGenError(f"Unknown text provider '{provider}'")

    data = result.model_dump()
    _validate_script(data, emotions, min_turns)
    total_words = sum(len(str(t["line"]).split()) for t in data["turns"])
    if total_words > WORD_WARN:
        lo, hi = WORD_BUDGET
        log(f"  aviso: guion largo ({total_words} palabras habladas, "
            f"objetivo {lo}-{hi}) — el video puede pasar del minuto")
    script = {"title": data["title"], "turns": data["turns"]}
    social = _format_social(data.get("caption", ""), data.get("hashtags", []))

    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(
        {"key": key, "provider": provider, "model": model,
         "language": language, "script": script, "social": social},
        ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(cache_file)
    return ScriptResult(script, social, provider, model)


def load_script_file(path: Path, emotions: list[str]) -> tuple[dict, str]:
    """Manual DialogueScript JSON (no-LLM mode): validate and return it."""
    try:
        # utf-8-sig: Notepad / PowerShell 5.1 save UTF-8 with a BOM
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise ScriptFileError(f"Could not read script file {path}: {e}") from e
    try:
        _validate_script(data, emotions, min_turns=2)
    except ScriptFileError:
        raise
    except ScriptGenError as e:
        raise ScriptFileError(f"{path}: {e}") from e
    script = {"title": data.get("title", path.stem), "turns": data["turns"]}
    social = _format_social(data.get("caption", ""), data.get("hashtags", []))
    return script, social
