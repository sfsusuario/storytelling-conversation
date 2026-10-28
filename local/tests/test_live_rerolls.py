"""Rerolls asked while a run works: done right after the scene in progress,
with the user's own image prompt when given."""
import threading

from escalator import image_gen, motion
from escalator.models import Persona, Scene
from studio.runs import Run


def _scenes(tmp_path, n=3):
    out = []
    for i in range(1, n + 1):
        img = tmp_path / f"s{i}.png"
        img.write_bytes(b"png")
        s = Scene(index=i, scene_id=f"scene_{i:02d}", persona=Persona(i + 1, f"P{i}", "r", f"detail {i}"))
        s.image_path, s.scene_duration = img, 4.0
        out.append(s)
    return out


def test_motion_reroll_jumps_the_queue(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(motion, "_rotate3d_clip", lambda image, out, *a, **k: (
        calls.append(image.name), out.write_bytes(b"mp4")))
    monkeypatch.setattr("escalator.ffutil.video_encoder_args", lambda f: ("-c:v", "x"))
    scenes = _scenes(tmp_path)
    asks = [["scene_01"], []]  # asked while scene_01 was being made
    motion.generate_motion("rotate3d", scenes, tmp_path / "m", 30, "ffmpeg",
                           more=lambda: asks.pop(0) if asks else [])
    assert calls == ["s1.png", "s1.png", "s2.png", "s3.png"]
    # keep=True (regenerate from render) still redoes what was rerolled
    motion.generate_motion("rotate3d", scenes, tmp_path / "m", 30, "ffmpeg", keep=True, redo={"scene_02"})
    assert calls[4:] == ["s2.png"]


def test_image_reroll_with_prompt_goes_next(tmp_path, monkeypatch):
    made = []

    def fake_local(provider, pending, base, seed, log, on_image, on_step, variants):
        while pending:  # the real loop's contract: pop, so rerolls can jump in
            scene, out = pending.pop(0)
            made.append((scene.scene_id, scene.visual_style_prompt))
            out.write_bytes(b"img")
            scene.image_path = out
            on_image(scene)

    monkeypatch.setattr("escalator.image_local.generate_local_images", fake_local)
    monkeypatch.setattr(image_gen, "_prepare_upload_image", lambda *a: (b"", "image/jpeg"))
    scenes, base = _scenes(tmp_path), tmp_path / "base.png"
    base.write_bytes(b"png")
    variants, prompts = {}, {}

    def more():  # scene_01 rerolled with a new prompt during scene_01
        if len(made) == 1:
            variants["scene_01"], prompts["scene_01"] = 1, "a red dragon"
            return ["scene_01"]
        return []

    events = []
    image_gen.generate_scene_images(scenes, base, "m", tmp_path / "img", provider="sdxl-face",
                                    on_image=lambda s, cached: events.append((s.scene_id, cached)),
                                    variants=variants, prompts=prompts, more=more)
    assert [m[0] for m in made] == ["scene_01", "scene_01", "scene_02", "scene_03"]
    assert made[0][1] == "portrait photo, detail 1" and made[1][1] == "a red dragon"
    # the next run keeps the chosen prompt and variant: all cached
    image_gen.generate_scene_images(scenes, base, "m", tmp_path / "img", provider="sdxl-face",
                                    on_image=lambda s, cached: events.append((s.scene_id, cached)),
                                    variants=variants, prompts=prompts)
    assert len(made) == 4 and events[-3:] == [("scene_01", True), ("scene_02", True), ("scene_03", True)]


def test_run_hands_rerolls_to_the_pipeline_and_chains_the_rest():
    gate, taken = threading.Event(), {}

    def pipeline(options, on_progress, on_event, cancel, rerolls=None):
        gate.wait(5)
        taken.update(rerolls.take("image"))
        on_event({"type": "done", "video": None, "social": "", "duration": 0})

    import dataclasses

    @dataclasses.dataclass
    class Opts:
        force: bool = False
        force_from: str | None = None
        reroll_images: list = dataclasses.field(default_factory=list)
        reroll_motion: list = dataclasses.field(default_factory=list)
        image_prompts: dict = dataclasses.field(default_factory=dict)

    registry = {}
    run = Run(Opts(), "u", registry=registry, pipeline=pipeline, cancelled=RuntimeError, url=lambda p: None)
    registry[run.id] = run
    run.start()
    run.queue_reroll("scene_02", "image", "a red dragon")
    run.queue_reroll("scene_03", "motion")  # this pipeline never takes motion
    gate.set()
    for _ in range(100):
        if run.status != "running":
            break
        threading.Event().wait(0.05)
    assert taken == {"scene_02": "a red dragon"}
    kinds = [e["type"] for e in run.events]
    assert "rerolling" in kinds and kinds.index("next") < kinds.index("done")
    follow = registry[next(e for e in run.events if e["type"] == "next")["run_id"]]
    assert follow.options.reroll_motion == ["scene_03"] and follow.options.reroll_images == []
