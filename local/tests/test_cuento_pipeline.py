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
    protagonist="a small green turtle with a red scarf",
    scenes=[StoryScene(index=i + 1, narration=t, action=f"the protagonist {a}", setting="a sunny riverbank, morning",
                       key_object=k, shot="wide shot, soft light, hopeful")
            for i, (t, a, k) in enumerate([("Tula miraba a los pájaros.", "looks up at birds", "three swallows"),
                                           ("Subió a una roca y saltó.", "jumps off a rock", ""),
                                           ("Cayó al río y se asustó.", "splashes into the river", "river"),
                                           ("Descubrió que nadar es su forma de volar.", "glides underwater", "")])],
    caption="¿Y si tu forma de volar fuera otra?", hashtags=["cuento", "tortuga"])


def test_scene_prompts_are_built_from_the_narration_fields():
    from cuento.images import story_prompt
    from cuento.config import default_style, negative_for
    sc = STORY.scenes[0]
    assert sc.visual() == "the protagonist looks up at birds, a sunny riverbank, morning, three swallows"
    assert STORY.scenes[1].visual().endswith("morning")  # empty key_object dropped
    assert story_prompt(sc, STORY.protagonist, "soft watercolor") == (
        "wide shot, soft light, hopeful, a small green turtle with a red scarf looks up at birds, "
        "a sunny riverbank, morning, three swallows, soft watercolor")
    # an action without "the protagonist" is a thing seen: drawn without the character
    thing = sc.model_copy(update={"action": "a huge shadow glides under the water"})
    assert story_prompt(thing, "a turtle", "x") == ("wide shot, soft light, hopeful, a huge shadow glides under the "
                                                   "water, a sunny riverbank, morning, three swallows, x")
    watcher = sc.model_copy(update={"action": "the protagonist stares as a faceless creature gazes at the lens"})
    assert story_prompt(watcher, "a turtle", "x").startswith("wide shot, soft light, hopeful, a faceless creature gazes")
    spanish = sc.model_copy(update={"action": "El protagonista mira a los pájaros"})
    assert "a turtle mira a los pájaros" in story_prompt(spanish, "a turtle", "x")
    assert default_style("general", "terror", real_story=True) == "real" and default_style("general", "terror") == "oscuro"
    assert "cartoon" in negative_for("real") and "cartoon" not in negative_for("cine")


SOURCE = {"url": "https://www.reddit.com/r/shortscarystories/comments/abc/my_story/",
          "title": "My wife and I switched places", "author": "ForgottenWell",
          "subreddit": "shortscarystories", "words": 120,
          "text": "Being married can be difficult. " * 20, "excerpt": "Being married"}


def test_spanish_protagonist_gets_one_retry(tmp_path, monkeypatch):
    from cuento import story_gen
    monkeypatch.setattr(story_gen, "resolve_text_backend", lambda p, m: ("ollama", "fake"))
    monkeypatch.setattr(story_gen, "_pictures", lambda story, *a: story)
    spanish = STORY.model_copy(update={"protagonist": "un joven con una linterna"})
    answers, asked = [spanish, STORY], []
    monkeypatch.setattr(story_gen, "_story_via_ollama",
                        lambda system, user, model, seed=None, **k: asked.append(user) or answers.pop(0))
    story, _ = story_gen.generate_story("x", "general", "terror", 4, "fake", tmp_path / "a")
    assert story.protagonist == STORY.protagonist and len(asked) == 2
    assert "REMINDER" not in asked[0] and "REMINDER" in asked[1]
    # still Spanish after the retry: kept, the run goes on
    answers[:] = [spanish, spanish]
    story, _ = story_gen.generate_story("y", "general", "terror", 4, "fake", tmp_path / "b")
    assert story.protagonist == "un joven con una linterna" and len(asked) == 4


def test_pictures_pass_rewrites_the_scene_fields_in_english(monkeypatch):
    from cuento import story_gen
    from cuento.story_gen import Picture, Pictures
    pic = dict(action="a huge shadow glides under the water", setting="river bed, noon",
               key_object="shadow", shot="wide shot, murky light")
    spanish = Pictures(pictures=[Picture(index=i, **{**pic, "key_object": "una sombra"}) for i in (1, 2, 3, 4)])
    good = Pictures(pictures=[Picture(index=i, **pic) for i in (4, 3, 2, 1)])
    answers, asked = [spanish, good], []
    monkeypatch.setattr(story_gen, "_ask", lambda prov, system, user, model, seed, schema: (
        asked.append((user, schema)) or answers.pop(0)))
    story = story_gen._pictures(STORY, "ollama", "fake", 3)
    assert [s.action for s in story.scenes] == [pic["action"]] * 4 and story.scenes[0].narration == STORY.scenes[0].narration
    assert len(asked) == 2 and asked[0][1] is Pictures and "REMINDER" in asked[1][0] and STORY.protagonist in asked[0][0]
    # an incomplete answer twice: the story's own fields stay
    answers[:] = [Pictures(pictures=[]), Pictures(pictures=[])]
    assert story_gen._pictures(STORY, "ollama", "fake", None) == STORY


def test_prompts_follow_tone_and_photo():
    kids = system_prompt("infantil", "aventura", 6, "es", False)
    assert "exactly 6 scenes" in kids and "moral" in kids and "español" in kids
    horror = system_prompt("general", "terror", 5, "es", True)
    assert "horror" in horror and "never their face" in horror and "twist" in horror
    assert "real story" not in horror and "real story" in system_prompt("general", "terror", 5, "es", False, adapted=True)
    assert '"key_object"' in kids and "narrator IS the protagonist" in kids and "THAT thing itself" in kids
    from cuento.story_gen import user_prompt
    prompt = user_prompt("x", "general", "terror", 5, SOURCE)
    assert SOURCE["title"] in prompt and "Being married" in prompt


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg missing")
def test_preview_then_continue_with_reddit_source(tmp_path, monkeypatch):
    import json

    from cuento import story_gen
    from cuento.manifest import regenerate_options
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pipeline, "resolve_text_backend", lambda p, m: ("ollama", "fake"))
    llm_calls = []
    monkeypatch.setattr(story_gen, "_story_via_ollama", lambda *a, **k: llm_calls.append(1) or STORY)
    monkeypatch.setattr(story_gen, "_pictures", lambda story, *a: story)
    monkeypatch.setattr(pipeline, "fetch_story", lambda url: {**SOURCE, "url": url})
    out = tmp_path / "output" / "cuento" / "switched-1"
    opts = dict(source=SOURCE["url"], scenes=4, test_mode=True, tts_provider="edge",
                voice="es-ES-AlvaroNeural", width=540, height=960, watermark="", motion="none",
                output_dir=out)
    events = []
    # 1. the script only
    assert pipeline.run_story(StoryOptions(preview=True, **opts), on_progress=lambda *_: None,
                              on_event=events.append) is None
    types = [e["type"] for e in events]
    assert types[-1] == "done" and events[-1]["video"] is None and "images" not in [e.get("name") for e in events]
    story_ev = next(e for e in events if e["type"] == "story")
    assert story_ev["title"] == STORY.title and story_ev["source"]["author"] == "ForgottenWell"
    assert not (out / "final.mp4").exists() and (out / "01_text" / "story.json").exists()
    assert llm_calls == [1]
    # 2. continue: the text comes from the cache, the video ends with the credits card
    events.clear()
    final = pipeline.run_story(StoryOptions(**opts), on_progress=lambda *_: None, on_event=events.append)
    assert llm_calls == [1] and final.exists() and (out / "04_clips" / "credits.mp4").exists()
    assert (out / "02_images" / "credits.png").stat().st_size > 0
    assert len([e for e in events if e["type"] == "scene" and e["kind"] == "clip"]) == 5  # 4 + credits
    m = json.loads((out / "pipeline.json").read_text(encoding="utf-8"))
    assert (m["Source"], m["Source_Author"], len(m["Scenes"])) == (SOURCE["url"], "ForgottenWell", 4)
    assert "Historia original: u/ForgottenWell en r/shortscarystories" in (out / "social.txt").read_text(encoding="utf-8")
    assert regenerate_options("switched-1", tmp_path / "output" / "cuento")["source"] == SOURCE["url"]
    runs = read_cuento("cuento", tmp_path / "output" / "cuento", "/media/cuento")
    assert runs[0]["meta"]["fuente"] == "r/shortscarystories · u/ForgottenWell"


def test_generate_story_images_with_a_fake_sdxl(tmp_path, monkeypatch):
    """The SDXL path without a model: prompts, stamps, cache and callbacks."""
    pytest.importorskip("torch")
    from PIL import Image

    from cuento import images
    from escalator.models import Persona, Scene

    calls = []

    class FakePipe:
        def __call__(self, **kw):
            calls.append(kw)
            kw["callback_on_step_end"](type("P", (), {"num_timesteps": 2})(), 0, 0, {})
            return type("R", (), {"images": [Image.new("RGB", (8, 8), "red")]})()

    monkeypatch.setattr(images, "_load_sdxl_txt2img", lambda torch, device: FakePipe())
    scenes = [Scene(index=1, scene_id="scene_01", persona=Persona(2, "x", "", "", "story"))]
    prompts = {"scene_01": "wide shot, turtle looks up, soft watercolor"}
    got = []
    images.generate_story_images(scenes, prompts, tmp_path, 7, style="real", log=lambda *_: None,
                                 on_image=lambda sc, cached: got.append(cached))
    assert calls[0]["prompt"] == "wide shot, turtle looks up, soft watercolor" and "prompt_2" not in calls[0]
    assert "cartoon" in calls[0]["negative_prompt"] and (calls[0]["width"], calls[0]["height"]) == images.SIZE
    assert scenes[0].image_path == tmp_path / "scene_01.png" and got == [False]
    images.generate_story_images(scenes, prompts, tmp_path, 7, style="real", log=lambda *_: None,
                                 on_image=lambda sc, cached: got.append(cached))
    assert len(calls) == 1 and got == [False, True]  # same prompt and seed: cached
    images.generate_story_images(scenes, prompts, tmp_path, 7, style="real", log=lambda *_: None,
                                 variants={"scene_01": 1})
    assert len(calls) == 2  # a reroll regenerates


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
