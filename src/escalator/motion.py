"""Optional motion for each scene's still image (stage between timeline and render).

  rotate3d     — layered "3D photo": the subject is matted out (BiRefNet),
                 the background behind it completed once (LaMa), both get
                 depth (Depth Anything V2 Small) and a virtual camera orbits
                 the subject. All CPU, ~1.5 min per scene; the face is never
                 redrawn, so it stays identical.
  liveportrait — animates the face (blinks, head motion, mouth; ~7 min per
                 scene on CPU) with an
                 external LivePortrait install driven by a template video.

Each mode writes a silent mp4 per scene; the renderer plays it under the
captions instead of the still. Clips are cached with a stamp like the others.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .models import Scene

MOTION_MODES = ["none", "rotate3d", "liveportrait"]
# Removed modes still stored in saved settings/CLI scripts map to their replacement.
MOTION_ALIASES = {"parallax": "rotate3d", "ltx": "rotate3d"}
DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"
MATTE_MODEL = "ZhengPeng7/BiRefNet_lite"
ROTATE_MAX_EDGE = 1280
ROTATE_DEGREES = 10.0    # swing to each side
ROTATE_NEAR, ROTATE_FAR = 1.0, 2.2  # scene depth range the relative depth map spans
ROTATE_RELIEF = 0.4      # subject depth variation kept (1 = as measured); less = fewer tears
ROTATE_PAD = 0.15        # background outpainted this much per side, so the swing never shows the frame edge
ROTATE_INPAINT_DILATE = 0.015  # of the width: margin around the subject the inpainting also redoes
ROTATE_BG_BLUR = 2       # px: slight depth of field; also hides inpainting seams
LIVEPORTRAIT_DIR = Path(os.environ.get(
    "ESCALATE_LIVEPORTRAIT_DIR",
    Path(os.environ.get("LOCALAPPDATA", Path.home())) / "escalator" / "LivePortrait"))
# Short talking template (3 s): CPU cost grows with its length, and the clip loops.
LIVEPORTRAIT_DRIVING = os.environ.get("ESCALATE_LIVEPORTRAIT_DRIVING",
                                      "assets/examples/driving/d0.mp4")


class MotionError(RuntimeError):
    pass


def _seed(seed: int | None, scene_id: str) -> int:
    digest = hashlib.sha256(f"motion|{seed or 0}|{scene_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def liveportrait_available() -> bool:
    return (LIVEPORTRAIT_DIR / "inference.py").is_file() and _lp_python().is_file()


def _lp_python() -> Path:
    return LIVEPORTRAIT_DIR / ".venv" / "Scripts" / "python.exe"


# ---------------------------------------------------------------- rotate3d --
def orbit_path(n: int, direction: int) -> list[tuple[float, float, float]]:
    """(yaw deg, pitch deg, dolly) per frame: one eased swing across the
    subject, with a slight rise and push-in. direction is +1 or -1."""
    out = []
    for i in range(n):
        p = i / max(1, n - 1)
        e = 0.5 - 0.5 * math.cos(math.pi * p)          # ease in-out, 0..1
        out.append((direction * ROTATE_DEGREES * (2 * e - 1), 1.5 * (2 * e - 1),
                    0.05 * e))
    return out


class Scene3DModels:
    """Depth, subject matte and background inpainting, loaded on first use
    (all CPU, ~100 + 180 + 200 MB)."""

    def __init__(self):
        self._depth = self._matte = self._lama = None

    def depth(self, image):
        """Relative depth (H, W) in 0..1, 1 = near."""
        import numpy as np

        if self._depth is None:
            from transformers import pipeline as hf_pipeline
            self._depth = hf_pipeline("depth-estimation", model=DEPTH_MODEL, device="cpu")
        depth = np.asarray(self._depth(image)["depth"], dtype="float32")
        lo, hi = np.percentile(depth, 2), np.percentile(depth, 98)
        return np.clip((depth - lo) / max(1e-6, hi - lo), 0.0, 1.0)

    def matte(self, image):
        """Subject alpha (H, W) in 0..1, hair-level edges."""
        import numpy as np
        import torch
        from PIL import Image

        if self._matte is None:
            from transformers import AutoModelForImageSegmentation
            self._matte = AutoModelForImageSegmentation.from_pretrained(
                MATTE_MODEL, trust_remote_code=True).eval()
        x = torch.from_numpy(np.asarray(image.resize((1024, 1024), Image.BILINEAR)).copy())
        x = x.permute(2, 0, 1).float() / 255
        x = (x - torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)) \
            / torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        with torch.no_grad():
            pred = self._matte(x[None])[-1].sigmoid()[0, 0]
        small = Image.fromarray((pred.numpy() * 255).astype("uint8"))
        return np.asarray(small.resize(image.size, Image.BILINEAR), dtype="float32") / 255

    def inpaint(self, image, hole):
        """Fill the white area of hole (PIL L) with plausible background (LaMa)."""
        if self._lama is None:
            from simple_lama_inpainting import SimpleLama
            self._lama = SimpleLama(device="cpu")
        return self._lama(image, hole).convert("RGB").resize(image.size)


def fill_holes(img, weight):
    """Push-pull hole filling: each empty pixel takes a weighted average of
    the nearest filled ones, coarse to fine. img (1,C,H,W), weight (1,1,H,W)
    with 0 = hole."""
    import torch
    import torch.nn.functional as F

    if min(img.shape[-2:]) < 4 or bool((weight > 0).all()):
        return img
    small_w = F.avg_pool2d(weight, 2, ceil_mode=True)
    small = F.avg_pool2d(img * weight, 2, ceil_mode=True) / small_w.clamp_min(1e-8)
    small = fill_holes(small, small_w)
    up = F.interpolate(small, size=img.shape[-2:], mode="bilinear", align_corners=False)
    return torch.where(weight > 0, img, up)


class Layer:
    """One depth layer ready to render: colors (C, N) and 3D points (3, N)
    relative to the pivot, for the pixels selected by `keep`."""

    def __init__(self, colors, z, f: float, pivot: float, keep=None):
        import torch

        C, H, W = colors.shape
        ys, xs = torch.meshgrid(torch.arange(H, dtype=torch.float32) - (H - 1) / 2,
                                torch.arange(W, dtype=torch.float32) - (W - 1) / 2,
                                indexing="ij")
        sel = keep.reshape(-1) if keep is not None else slice(None)
        z = z.reshape(-1)[sel]
        self.colors = colors.reshape(C, -1)[:, sel]
        self.points = torch.stack([xs.reshape(-1)[sel] / f * z,
                                   ys.reshape(-1)[sel] / f * z, z - pivot])
        self.f, self.pivot = f, pivot

    def render(self, size: tuple[int, int], yaw: float, pitch: float, dolly: float,
               fill: bool, scale: float = 1.0):
        """Forward-splat the points into a camera rotated around the pivot,
        (C, h, w) for size (w, h), which is the source size times scale. A
        z-buffer keeps the nearest point per pixel; 2x2 splats plus three
        crack passes close the gaps a stretched surface opens. fill:
        push-pull the remaining holes (background layer); otherwise they stay
        empty (subject layer, alpha 0)."""
        import torch
        import torch.nn.functional as F

        w, h = size
        C = self.colors.shape[0]
        x, y, zc = self.points
        a, b = math.radians(yaw), math.radians(pitch)
        x1, z1 = math.cos(a) * x + math.sin(a) * zc, -math.sin(a) * x + math.cos(a) * zc
        y2, z2 = math.cos(b) * y - math.sin(b) * z1, math.sin(b) * y + math.cos(b) * z1
        zf = z2 + self.pivot * (1 - dolly)
        u0 = (scale * self.f * x1 / zf + (w - 1) / 2).floor().long()
        v0 = (scale * self.f * y2 / zf + (h - 1) / 2).floor().long()
        idx, depth, color = [], [], []
        for du, dv in ((0, 0), (1, 0), (0, 1), (1, 1)):
            u, v = u0 + du, v0 + dv
            ok = (u >= 0) & (u < w) & (v >= 0) & (v < h) & (zf > 0.05)
            idx.append((v * w + u)[ok]); depth.append(zf[ok]); color.append(self.colors[:, ok])
        idx, depth, color = torch.cat(idx), torch.cat(depth), torch.cat(color, dim=1)
        zbuf = torch.full((h * w,), float("inf")).scatter_reduce(0, idx, depth, "amin")
        front = depth <= zbuf[idx] + 1e-6
        out = torch.zeros(C, h * w)
        out[:, idx[front]] = color[:, front]
        img = out.view(1, C, h, w)
        hit = torch.isfinite(zbuf).float().view(1, 1, h, w)
        for _ in range(3):
            count = F.avg_pool2d(hit, 3, 1, 1) * 9
            crack = (hit == 0) & (count >= 4)
            img = torch.where(crack, F.avg_pool2d(img, 3, 1, 1) * 9 / count.clamp_min(1), img)
            hit = torch.where(crack, torch.ones(()), hit)
        if fill:
            img = fill_holes(img, hit)
        return img[0]


def build_layers(image, models: Scene3DModels, log: Callable = print):
    """Split a still into a subject layer and a completed background layer.

    The subject is matted out; the hole it leaves (plus a margin around the
    frame, so the camera can swing without the edges opening up) is inpainted
    once. Each layer gets its own depth, so the subject keeps a slight relief
    while the background slides behind it."""
    import numpy as np
    import torch
    import torch.nn.functional as F
    from PIL import Image, ImageFilter

    W, H = image.size
    f = float(max(W, H))   # ~53 degree field of view on the long side
    depth = torch.from_numpy(models.depth(image))
    alpha = torch.from_numpy(models.matte(image))
    # Depth Anything gives relative inverse depth: interpolate 1/z, not z.
    z = 1.0 / (depth / ROTATE_NEAR + (1 - depth) / ROTATE_FAR)
    subject = alpha > 0.5
    if not bool(subject.any()):
        raise MotionError("no subject found in the image")
    pivot = float(z[subject].median())

    # Background: inpaint the (dilated) subject hole and the outside margin.
    px, py = int(W * ROTATE_PAD), int(H * ROTATE_PAD)
    r = max(2, int(W * ROTATE_INPAINT_DILATE))
    hole = F.max_pool2d(subject.float()[None, None], 2 * r + 1, 1, r)[0, 0]
    hole = F.pad(hole[None, None], (px, px, py, py), value=1.0)[0, 0]
    padded = Image.new("RGB", (W + 2 * px, H + 2 * py))
    padded.paste(image.resize(padded.size), (0, 0))          # rough margin for LaMa
    padded.paste(image, (px, py))
    bg = models.inpaint(padded, Image.fromarray((hole.numpy() * 255).astype("uint8")))
    if ROTATE_BG_BLUR:
        bg = bg.filter(ImageFilter.GaussianBlur(ROTATE_BG_BLUR))
    bg_rgb = torch.from_numpy(np.asarray(bg).copy()).permute(2, 0, 1).float()
    # Background depth: what surrounds the subject, pushed behind the pivot.
    bg_z = F.pad(z[None, None], (px, px, py, py), mode="replicate")
    bg_w = F.pad((~subject).float()[None, None], (px, px, py, py), mode="replicate")
    bg_z = fill_holes(bg_z * bg_w, bg_w)
    k = 2 * r + 1   # smooth depth steps inside the background into slopes
    bg_z = F.avg_pool2d(F.avg_pool2d(bg_z, k, 1, r), k, 1, r)[0, 0].clamp_min(pivot + 0.05)

    # Subject: premultiplied RGBA, with its relief compressed around the pivot.
    # Its edge pixels take the depth of the confident interior: the depth map
    # bleeds background depth into hair and outlines, which would scatter them.
    rgb = torch.from_numpy(np.asarray(image).copy()).permute(2, 0, 1).float()
    fg_rgba = torch.cat([rgb * alpha, alpha[None] * 255])
    e = max(1, r // 2)
    core = -F.max_pool2d(-(alpha > 0.9).float()[None, None], 2 * e + 1, 1, e)
    fg_z = F.avg_pool2d(fill_holes(z[None, None] * core, core), 9, 1, 4)[0, 0]
    fg_z = pivot + (fg_z - pivot) * ROTATE_RELIEF
    return (Layer(bg_rgb, bg_z, f, pivot), Layer(fg_rgba, fg_z, f, pivot, keep=alpha > 0.003))


def render_frame(layers, size, yaw: float, pitch: float, dolly: float):
    import torch.nn.functional as F

    bg_layer, fg_layer = layers
    w, h = size
    # The background is splatted at half size (4x the point density, so near
    # objects left in it, like a chair back, stretch without opening a mesh)
    # and upsampled: it is slightly blurred anyway.
    bg = bg_layer.render((w // 2, h // 2), yaw, pitch, dolly, fill=True, scale=0.5)
    bg = F.interpolate(bg[None], size=(h, w), mode="bilinear", align_corners=False)[0]
    fg = fg_layer.render(size, yaw, pitch, dolly, fill=False)
    a = fg[3:4] / 255
    return fg[:3] + (1 - a) * bg


def _rotate3d_clip(image_path: Path, out: Path, duration: float, fps: int,
                   ffmpeg: str, encoder: tuple[str, ...], seed: int,
                   models: Scene3DModels, on_progress: Callable | None = None) -> None:
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    scale = min(1.0, ROTATE_MAX_EDGE / max(image.size))
    W, H = (max(2, int(d * scale) // 2 * 2) for d in image.size)
    image = image.resize((W, H), Image.LANCZOS)
    if on_progress:
        on_progress(0, 0, "separando fondo")
    layers = build_layers(image, models)
    n = max(1, math.ceil(duration * fps))
    path = orbit_path(n, 1 if seed % 2 else -1)
    tmp = out.with_suffix(".tmp.mp4")
    proc = subprocess.Popen(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
         "-i", "-", *encoder, "-an", str(tmp)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i, (yaw, pitch, dolly) in enumerate(path):
            frame = render_frame(layers, (W, H), yaw, pitch, dolly)
            proc.stdin.write(frame.clamp(0, 255).byte().permute(1, 2, 0)
                             .contiguous().numpy().tobytes())
            if on_progress and (i % 8 == 7 or i == n - 1):
                on_progress(i + 1, n, "frames")
        proc.stdin.close()
        if proc.wait() != 0:
            raise MotionError(f"ffmpeg failed encoding the 3D rotation: "
                              f"{proc.stderr.read().decode(errors='replace')[-400:]}")
    except BaseException:
        proc.kill()
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(out)


# ------------------------------------------------------------ liveportrait --
_PERCENT = re.compile(rb"(\d{1,3})%")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def read_progress(stream, on_progress: Callable | None) -> str:
    """Read a rich/tqdm-style stream, reporting the 'Animating' bar's percent.

    Bars redraw with \\r, so the stream is split on \\r and \\n; returns the
    text without bar redraws, for error messages.
    """
    kept, buf = [], b""
    while chunk := stream.read(256):
        buf += chunk
        *segments, buf = re.split(rb"[\r\n]", buf)
        for seg in segments:
            text = _ANSI.sub("", seg.decode("utf-8", "replace"))
            match = _PERCENT.search(seg)
            if match and "Animating" in text:
                if on_progress:
                    on_progress(int(match.group(1)), 100, "frames")
            elif match and "templates" in text:
                if on_progress:
                    on_progress(0, 0, "preparando")
            elif text.strip():
                kept.append(text)
    return "\n".join(kept + [_ANSI.sub("", buf.decode("utf-8", "replace"))])


def _liveportrait_clip(image_path: Path, out: Path, work: Path, ffmpeg: str,
                       encoder: tuple[str, ...],
                       on_progress: Callable | None = None) -> None:
    if not liveportrait_available():
        raise MotionError(
            f"LivePortrait is not installed in {LIVEPORTRAIT_DIR}. "
            "Run .\\setup-liveportrait.ps1 once, or choose another motion mode.")
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob("*.mp4"):
        old.unlink()
    # FORCE_COLOR makes rich draw its progress bars without a terminal, so the
    # percentage of its "Animating" bar can be read from the output stream.
    # PYTHONUTF8: the bar label has an emoji that cp1252 pipes can't encode.
    proc = subprocess.Popen(
        [str(_lp_python()), "inference.py", "-s", str(image_path.resolve()),
         "-d", LIVEPORTRAIT_DRIVING, "-o", str(work.resolve()),
         "--flag-force-cpu", "--no-flag-use-half-precision"],  # fp16 is GPU-only
        cwd=LIVEPORTRAIT_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={**os.environ, "FORCE_COLOR": "1", "COLUMNS": "120", "PYTHONUTF8": "1"})
    output = read_progress(proc.stdout, on_progress)
    proc.wait()
    result = [p for p in work.glob("*.mp4") if not p.stem.endswith("_concat")]
    if proc.returncode != 0 or not result:
        tail = "\n".join(output.strip().splitlines()[-15:])
        raise MotionError(f"LivePortrait failed for {image_path.name}:\n{tail}")
    shutil.move(str(result[0]), out)


# -------------------------------------------------------------------- run --
def generate_motion(mode: str, scenes: list[Scene], motion_dir: Path, fps: int,
                    ffmpeg: str, seed: int | None = None, log: Callable = print,
                    on_scene: Callable | None = None,
                    on_step: Callable | None = None,
                    variants: dict[str, int] | None = None,
                    keep: bool = False) -> None:
    """Fill scene.motion_path for every scene (cached per mode/image/duration).

    variants: per-scene reroll counter; a bump gives that scene a new seed.
    keep: reuse existing clips of this mode even if their stamp is outdated."""
    mode = MOTION_ALIASES.get(mode, mode)
    if mode == "none":
        return
    if mode not in MOTION_MODES:
        raise MotionError(f"Unknown motion mode '{mode}' (expected {MOTION_MODES})")
    from .ffutil import video_encoder_args

    motion_dir.mkdir(parents=True, exist_ok=True)
    encoder = video_encoder_args(ffmpeg)
    pending = []
    for scene in scenes:
        out = motion_dir / f"{scene.scene_id}.{mode}.mp4"
        meta = out.with_suffix(".meta")
        # LivePortrait clips are stretched to the scene by the renderer, so
        # only the 3D rotation depends on the duration.
        duration = f"{scene.scene_duration:.3f}" if mode == "rotate3d" else ""
        stamp = f"v8|{mode}|{scene.image_path.stat().st_mtime_ns}|{duration}|{fps}|{seed}"
        variant = (variants or {}).get(scene.scene_id, 0)
        if variant:
            stamp += f"|v{variant}"
        if out.exists() and meta.exists() and (keep or meta.read_text(encoding="utf-8") == stamp):
            scene.motion_path = out
            log(f"  motion: {out.name} (cached)")
            if on_scene:
                on_scene(scene, True)
        else:
            pending.append((scene, out, meta, stamp))
    if not pending:
        return

    models = None
    if mode == "rotate3d":
        try:
            import simple_lama_inpainting  # noqa: F401
            import transformers  # noqa: F401
        except ImportError as e:
            raise MotionError(f"{mode} needs the local extras: "
                              "pip install -e \".[image-local]\"") from e
        models = Scene3DModels()

    for scene, out, meta, stamp in pending:
        variant = (variants or {}).get(scene.scene_id, 0)
        s = _seed(seed, f"{scene.scene_id}#{variant}" if variant else scene.scene_id)
        progress = (lambda step, total, label, scene=scene:
                    on_step(scene, step, total, label)) if on_step else None
        if mode == "rotate3d":
            _rotate3d_clip(scene.image_path, out, scene.scene_duration, fps,
                           ffmpeg, encoder, s, models, progress)
        else:
            _liveportrait_clip(scene.image_path, out, motion_dir / "_lp_work",
                               ffmpeg, encoder, progress)
        meta.write_text(stamp, encoding="utf-8")
        scene.motion_path = out
        log(f"  motion: {out.name}")
        if on_scene:
            on_scene(scene, False)
