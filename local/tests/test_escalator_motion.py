import pytest

from escalator import motion
from escalator.config import STYLE_SETS, build_image_prompt, build_rewrite_system_prompt
from escalator.models import Persona, Scene


def test_orbit_path_is_eased_and_bounded():
    for direction in (1, -1):
        path = motion.orbit_path(60, direction)
        assert len(path) == 60
        yaws = [y for y, _, _ in path]
        assert yaws[0] == pytest.approx(-direction * motion.ROTATE_DEGREES)
        assert yaws[-1] == pytest.approx(direction * motion.ROTATE_DEGREES)
        assert all(abs(y) <= motion.ROTATE_DEGREES + 1e-9 for y in yaws)
        # ease in-out: the first step is much smaller than the middle one
        assert abs(yaws[1] - yaws[0]) < abs(yaws[31] - yaws[30])


def test_layers_rotate_subject_over_a_complete_background():
    import torch
    H = W = 64
    bg = torch.zeros(3, H, W)
    bg[0] = 200                                   # red background, far
    bg_layer = motion.Layer(bg, torch.full((H, W), 2.0), 64.0, 1.0)
    fg = torch.zeros(4, H, W)
    fg[2, 24:40, 24:40] = 200                     # a blue square, near, opaque
    fg[3, 24:40, 24:40] = 255
    fg_layer = motion.Layer(fg, torch.full((H, W), 1.0), 64.0, 1.0, keep=fg[3] > 0)
    still = motion.render_frame((bg_layer, fg_layer), (W, H), 0.0, 0.0, 0.0)
    turned = motion.render_frame((bg_layer, fg_layer), (W, H), 12.0, 0.0, 0.0)
    expected = bg.clone(); expected[:, 24:40, 24:40] = fg[:3, 24:40, 24:40]
    assert (still - expected).abs().amax(0).gt(1).float().mean() < 0.05

    def blue_center_x(img):
        cols = (img[2] > 100).float().sum(0)
        return float((cols * torch.arange(W)).sum() / cols.sum())

    # the subject sits at the pivot and stays put; the far background slides
    assert abs(blue_center_x(turned) - blue_center_x(still)) < 1.0
    # ...and nothing is left black: the background layer is complete
    assert float(turned.sum(0).min()) > 100


def _scene(tmp_path, i=1):
    img = tmp_path / f"s{i}.png"
    img.write_bytes(b"png")
    s = Scene(index=i, scene_id=f"scene_{i:02d}", persona=Persona(i, "P", "r", "d"))
    s.image_path, s.scene_duration = img, 4.0
    return s


def test_generate_motion_none_is_noop(tmp_path):
    scene = _scene(tmp_path)
    motion.generate_motion("none", [scene], tmp_path / "m", 30, "ffmpeg")
    assert scene.motion_path is None and not (tmp_path / "m").exists()


def test_generate_motion_caches_by_stamp(tmp_path, monkeypatch):
    calls = []

    def fake_clip(image, out, duration, fps, ffmpeg, encoder, seed, estimator,
                  on_progress=None):
        calls.append(image)
        out.write_bytes(b"mp4")

    monkeypatch.setattr(motion, "_rotate3d_clip", fake_clip)
    monkeypatch.setattr("escalator.ffutil.video_encoder_args", lambda f: ("-c:v", "x"))
    scenes = [_scene(tmp_path, 1), _scene(tmp_path, 2)]
    events = []
    motion.generate_motion("rotate3d", scenes, tmp_path / "m", 30, "ffmpeg", seed=3,
                           on_scene=lambda s, cached: events.append(cached))
    assert len(calls) == 2 and events == [False, False]
    assert scenes[0].motion_path.name == "scene_01.rotate3d.mp4"
    motion.generate_motion("rotate3d", scenes, tmp_path / "m", 30, "ffmpeg", seed=3,
                           on_scene=lambda s, cached: events.append(cached))
    assert len(calls) == 2 and events[2:] == [True, True]  # cached
    scenes[0].scene_duration = 5.0                         # new narration length
    motion.generate_motion("rotate3d", scenes, tmp_path / "m", 30, "ffmpeg", seed=3)
    assert len(calls) == 3


def test_liveportrait_missing_gives_setup_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(motion, "LIVEPORTRAIT_DIR", tmp_path / "nope")
    with pytest.raises(motion.MotionError, match="setup-liveportrait"):
        motion._liveportrait_clip(tmp_path / "a.png", tmp_path / "o.mp4", tmp_path / "w",
                                  "ffmpeg", ())


def test_read_progress_parses_rich_bars():
    import io
    raw = (b"\rMaking motion templates... \x1b[38;5;197m----\x1b[0m   0% -:--:--"
           b"\r\x1b[2K\xf0\x9f\x9a\x80Animating... ------  12% 0:01:10"
           b"\r\xf0\x9f\x9a\x80Animating... ------ 100% 0:00:00\n"
           b"Animated video: out.mp4\nTraceback: boom")
    seen = []
    text = motion.read_progress(io.BytesIO(raw), lambda *a: seen.append(a))
    assert seen == [(0, 0, "preparando"), (12, 100, "frames"), (100, 100, "frames")]
    assert "Animated video: out.mp4" in text and "Traceback: boom" in text
    assert "Animating" not in text


def test_liveportrait_env_survives_rich_emoji_bar(monkeypatch):
    """Real subprocess, same env as _liveportrait_clip: rich + emoji over a pipe."""
    import os
    import subprocess
    import sys
    pytest.importorskip("rich")
    code = ("from rich.progress import track\n"
            "for i in track(range(3), description='\\U0001f680Animating...', total=3): pass\n")
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            env={**os.environ, "FORCE_COLOR": "1", "PYTHONUTF8": "1"})
    seen = []
    out = motion.read_progress(proc.stdout, lambda *a: seen.append(a))
    assert proc.wait() == 0, out
    assert seen[-1] == (100, 100, "frames")


def test_excuses_set_uses_absurdity_rules():
    ladder = STYLE_SETS["excuses"]
    assert [p.escalation for p in ladder] == ["absurdity"] * 5
    prompt = build_rewrite_system_prompt("es", "absurdity")
    assert "Absurdity must strictly increase" in prompt
    assert "sophistication must strictly increase" not in prompt
    assert "increasingly absurd excuses" in prompt
    assert "absurdity level 4 of 5" in build_image_prompt(ladder[3])
    assert "sophistication must strictly increase" in build_rewrite_system_prompt("es")


def test_kontext_gets_short_edit_prompt():
    persona = STYLE_SETS["military"][1]
    prompt = build_image_prompt(persona, "flux-kontext")
    assert "same age" in prompt and "same pose" in prompt
    assert persona.image_detail in prompt and "Transform" not in prompt
    assert build_image_prompt(persona).startswith("Transform")




def test_removed_motion_modes_map_to_rotate3d(tmp_path, monkeypatch):
    made = []
    monkeypatch.setattr(motion, "_rotate3d_clip",
                        lambda image, out, *a, **k: (made.append(out.name), out.write_bytes(b"x")))
    monkeypatch.setattr("escalator.ffutil.video_encoder_args", lambda f: ("-c:v", "x"))
    for old in ("parallax", "ltx"):
        motion.generate_motion(old, [_scene(tmp_path)], tmp_path / old, 30, "ffmpeg")
    assert made == ["scene_01.rotate3d.mp4"] * 2
