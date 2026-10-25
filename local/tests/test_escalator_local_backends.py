import io
import json
import urllib.error

import pytest

from escalator import ffutil, text_gen
from escalator.image_local import scene_seed
from escalator.models import Persona
from escalator.tts import estimate_word_timings, kokoro_speed, resolve_voice

PERSONAS = [Persona(1, "Recruit", "plain", ""), Persona(2, "General", "grand", "")]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_ollama_rewrites_parsed(monkeypatch, tmp_path):
    content = {"meaning": "m", "rewrites": [{"stage": 1, "style": "Recruit", "rewrite": "x"},
                            {"stage": 2, "style": "Extra", "rewrite": "sobra"},  # dropped
                            {"stage": 3, "style": "General", "rewrite": "¡Comamos!"}],
               "caption": "De cero a general", "hashtags": ["humor"]}
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent.update(json.loads(req.data))
        return FakeResponse(json.dumps({"message": {"content": json.dumps(content)}}).encode())

    monkeypatch.setattr(text_gen.urllib.request, "urlopen", fake_urlopen)
    rewrites, social = text_gen.generate_rewrites(
        "Tengo hambre", PERSONAS, "qwen3:8b", tmp_path, provider="ollama", seed=7)
    assert rewrites == ["Tengo hambre", "¡Comamos!"]  # level 1 = original phrase
    assert "#humor" in social
    assert sent["options"]["seed"] == 7 and sent["keep_alive"] == 0
    assert sent["format"]["title"] == "RewriteSet"


def test_ollama_missing_model_hint(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(text_gen.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(text_gen.TextGenError, match="ollama pull qwen3:8b"):
        text_gen._rewrites_via_ollama("hola", PERSONAS, "qwen3:8b", "es")


def test_resolve_text_backend_swaps_models(monkeypatch):
    monkeypatch.setattr(text_gen, "ollama_available", lambda: True)
    assert text_gen.resolve_text_backend("auto", "claude-opus-5") == ("ollama", "gpt-oss:20b")
    assert text_gen.resolve_text_backend("ollama", "gpt-oss:20b") == ("ollama", "gpt-oss:20b")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-" + "x" * 24)  # placeholders like "x" are ignored
    assert text_gen.resolve_text_backend("claude", "qwen3:8b")[1].startswith("claude")


def test_word_timings_cover_segment_in_order():
    words = estimate_word_timings("Hambre es señal de mando", 1.0, 2.5)
    assert [w["w"] for w in words] == ["Hambre", "es", "señal", "de", "mando"]
    assert words[0]["t"] == 1.0
    assert all(a["t"] < b["t"] for a, b in zip(words, words[1:]))
    end = words[-1]["t"] + words[-1]["d"]
    assert end == pytest.approx(3.5, abs=0.01)
    assert estimate_word_timings("", 0, 1) == []


def test_voice_and_speed_mapping():
    assert kokoro_speed("-8%") == pytest.approx(0.92)
    assert kokoro_speed("bad") == 1.0
    assert resolve_voice("kokoro", "es-ES-AlvaroNeural") == "em_alex"
    assert resolve_voice("edge", "em_alex") == "es-ES-AlvaroNeural"
    assert resolve_voice("kokoro", "ef_dora") == "ef_dora"


def test_scene_seed_stable_and_distinct():
    assert scene_seed(7, "scene_02") == scene_seed(7, "scene_02")
    assert scene_seed(7, "scene_02") != scene_seed(7, "scene_03")
    assert scene_seed(None, "scene_02") == scene_seed(0, "scene_02")


def test_encoder_falls_back_to_x264(monkeypatch):
    def failing(ffmpeg, args):
        raise ffutil.FfmpegError("no qsv")

    monkeypatch.setattr(ffutil, "run_ffmpeg", failing)
    ffutil.video_encoder_args.cache_clear()
    try:
        assert ffutil.video_encoder_args("ffmpeg-test")[1] == "libx264"
    finally:
        ffutil.video_encoder_args.cache_clear()


def test_ollama_retries_when_too_few_rewrites(monkeypatch, tmp_path):
    good = {"meaning": "m", "rewrites": [{"stage": 7, "style": "a", "rewrite": "x"},   # misnumbered
                         {"stage": 9, "style": "b", "rewrite": "¡Comamos!"}],
            "caption": "c", "hashtags": []}
    replies = [{"meaning": "m", "rewrites": [], "caption": "c", "hashtags": []}, good]
    seeds = []

    def fake_urlopen(req, timeout=None):
        seeds.append(json.loads(req.data)["options"]["seed"])
        content = json.dumps(replies.pop(0))
        return FakeResponse(json.dumps({"message": {"content": content}}).encode())

    monkeypatch.setattr(text_gen.urllib.request, "urlopen", fake_urlopen)
    rewrites, _ = text_gen.generate_rewrites(
        "Tengo hambre", PERSONAS, "qwen3:8b", tmp_path, provider="ollama", seed=7)
    assert rewrites == ["Tengo hambre", "¡Comamos!"] and seeds == [7, 8]


def test_reroll_bumps_variant_and_changes_seed(tmp_path):
    from escalator.image_local import scene_seed
    from escalator.pipeline import scene_variants
    path = tmp_path / "02_images" / "variants.json"
    assert scene_variants(path, []) == {}
    assert scene_variants(path, ["scene_02"]) == {"scene_02": 1}
    assert scene_variants(path, ["scene_02", "scene_03"]) == {"scene_02": 2, "scene_03": 1}
    assert scene_variants(path, []) == {"scene_02": 2, "scene_03": 1}  # kept
    assert scene_seed(7, "scene_02") == scene_seed(7, "scene_02", 0)
    assert len({scene_seed(7, "scene_02", v) for v in range(3)}) == 3


def test_echoes_phrase():
    phrase = "Casi me matan por una narizz"
    assert text_gen.echoes_phrase(phrase, "casi me matan por una narizz, el tráfico estaba terrible.")
    assert text_gen.echoes_phrase(phrase, "Te juro que casi me matan por una nariz")  # 4-word run
    assert not text_gen.echoes_phrase(phrase, "Un ganso me persiguió y casi pierdo la nariz")
    assert text_gen.echoes_phrase("Tengo hambre", "Tengo hambre, sargento")  # short phrase: whole
    assert not text_gen.echoes_phrase("Tengo hambre", "Mi estómago pide raciones")
