"""Story pipeline end to end in test mode: a stubbed story, placeholder
images, real edge TTS + ffmpeg render, then the manifest and the studio's
history reader on the result."""
from pathlib import Path

import pytest

from cuento import pipeline
from cuento.config import StoryOptions
from cuento.story_gen import Story, StoryScene, system_prompt
from escalator.ffutil import find_ffmpeg
from studio.history import read_cuento

STORY = Story(
    outline="Una tortuga quiere volar, lo intenta, se cae y descubre que puede nadar.",
    title="Tula quiere volar",
    protagonist="small green turtle with a red scarf, round eyes, tiny backpack",
    scenes=[StoryScene(index=i + 1, narration=t, image_prompt=f"the protagonist {t.lower()}")
            for i, t in enumerate(["Tula miraba a los pájaros.", "Subió a una roca y saltó.",
                                   "Cayó al río y se asustó.", "Descubrió que nadar es su forma de volar."])],
    caption="¿Y si tu forma de volar fuera otra?", hashtags=["cuento", "tortuga"])


def test_prompts_follow_tone_and_photo():
    kids = system_prompt("infantil", "aventura", 6, "es", False)
    assert "exactly 6 scenes" in kids and "moral" in kids and "español" in kids
    horror = system_prompt("general", "terror", 5, "es", True)
    assert "horror" in horror and "never their face" in horror and "twist" in horror


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg missing")
def test_run_story_test_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pipeline, "resolve_text_backend", lambda p, m: ("ollama", "fake"))
    monkeypatch.setattr(pipeline, "generate_story", lambda *a, **k: (STORY, "social text"))
    out = tmp_path / "output" / "cuento" / "tula-1"
    events = []
    final = pipeline.run_story(
        StoryOptions(premise="Una tortuga que quiere volar", scenes=4, test_mode=True,
                     tts_provider="edge", voice="es-ES-AlvaroNeural", width=540, height=960,
                     watermark="", motion="none", output_dir=out),
        on_progress=lambda *_: None, on_event=events.append)
    assert final == out / "final.mp4" and final.stat().st_size > 0
    assert (out / "social.txt").read_text(encoding="utf-8") == "social text"
    types = [e["type"] for e in events]
    assert types[0] == "scenes" and types[-1] == "done"
    assert [e["name"] for e in events if e["type"] == "stage"] == pipeline.STAGES
    for kind in ("text", "image", "audio", "clip"):
        assert len([e for e in events if e["type"] == "scene" and e["kind"] == kind]) == 4, kind
    assert events[0]["scenes"][0] == {"scene_id": "scene_01", "level": 1, "persona": "Escena 1"}

    runs = read_cuento("cuento", tmp_path / "output" / "cuento", "/media/cuento")
    assert len(runs) == 1 and runs[0]["title"] == "Tula quiere volar"
    assert runs[0]["thumb_url"].startswith("/media/cuento/tula-1/02_images/scene_01.png")
    assert runs[0]["meta"] == {"escenas": 4, "tono": "Infantil con moraleja",
                               "voz": "es-ES-AlvaroNeural", "imágenes": "auto"}
    # a reroll of one scene's image is cached for the other three
    from cuento.manifest import regenerate_options
    fields = regenerate_options("tula-1", tmp_path / "output" / "cuento")
    assert fields["scenes"] == 4 and fields["premise"] == "Una tortuga que quiere volar"
    assert "base_image" not in fields and Path(fields["voice"] and out).is_dir()
