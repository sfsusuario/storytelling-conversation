"""Scene images for a story.

Without a photo: text-to-image with the SDXL base weights Escalera already
downloads, on the Intel iGPU (XPU). With a photo the pipeline calls Escalera's
identity engines instead (escalator.image_gen.generate_scene_images).
Test mode draws flat colored placeholders with ffmpeg.
"""
from __future__ import annotations

import gc
import re
import subprocess
import traceback
from pathlib import Path
from typing import Callable

from escalator.image_gen import ImageGenError, generate_test_images, resolve_image_provider
from escalator.image_local import (DRIVER_HINT, INSTALL_HINT, SDXL_REPO, _device,
                                   local_available, scene_seed)
from escalator.models import Scene
from escalator.renderer import _drawtext_escape

from .config import CREDITS_TITLE, NEGATIVE, negative_for

SIZE = (832, 1216)    # SDXL 9:16 bucket; the renderer crops it to the frame
STEPS, CFG = 30, 7.0
PLACEHOLDER_COLORS = ["3b5bdb", "2b8a3e", "e67700", "862e9c", "c92a2a", "0b7285", "5f3dc4", "a61e4d"]
REDDIT_ICON = Path(__file__).resolve().parents[2] / "assets" / "reddit-icon.png"
_FONT = "fontfile='C\\:/Windows/Fonts/arialbd.ttf'"   # the renderer's font
# "the protagonist watches the creature bend": SDXL draws the watcher and
# drops the creature, so the watcher goes and the thing seen stays
_WATCHER = re.compile(r"^the protagonista? (watches|sees|stares (at|as)|looks at|notices|hears|"
                      r"listens to|realizes|discovers|finds)( that| as| how)?\s+", re.I)


def resolve_story_image_provider(provider: str, has_photo: bool) -> str:
    if has_photo:
        if provider == "sdxl":
            raise ImageGenError("sdxl draws invented characters; with a photo use auto or flux-kontext")
        if provider == "auto" and not local_available():
            raise ImageGenError("With a photo the protagonist is drawn locally with FLUX Kontext.\n"
                                + INSTALL_HINT)
        return resolve_image_provider(provider)
    if provider == "flux-kontext":
        raise ImageGenError("flux-kontext needs a protagonist photo; without one use auto or sdxl")
    if not local_available():
        raise ImageGenError("Without a photo the images are generated locally with SDXL.\n"
                            + INSTALL_HINT + "\nOr add a photo, or use test mode.")
    return "sdxl"


def story_prompt(scene, protagonist: str, style: str) -> str:
    """One caption of the moment for both SDXL text encoders: shot, the
    protagonist doing the action, place, key object, then the style. A
    leading description of the character makes SDXL paint a portrait and
    drop the scene; and the scene must reach the second encoder (OpenCLIP
    bigG), which carries most of the weight: given only the character and
    the style, it painted the same figure in the fog for every scene."""
    # no "the protagonist" in the action: the scene is about something seen
    # (a creature, a photo, a door), drawn without the character
    action = _WATCHER.sub("", scene.action.strip())
    subject = re.sub(r"\b(the|el|la) protagonista?\b", protagonist, action, count=1, flags=re.I)
    parts = [scene.shot, subject, scene.setting, scene.key_object, style]
    return ", ".join(p.strip() for p in parts if p and p.strip())


def _load_sdxl_txt2img(torch, device: str):
    from diffusers import StableDiffusionXLPipeline
    from diffusers.models.attention_processor import AttnProcessor

    # bf16, not fp16: the fp16 SDXL VAE overflows into NaN (black images).
    pipe = StableDiffusionXLPipeline.from_pretrained(
        SDXL_REPO, torch_dtype=torch.bfloat16, variant="fp16")
    # SDPA attention returns NaN (black images) on XPU; the classic processor works.
    pipe.unet.set_attn_processor(AttnProcessor())
    return pipe.to(device)


def generate_story_images(scenes: list[Scene], prompts: dict[str, str],
                          images_dir: Path, seed: int | None, style: str = "",
                          log: Callable = print, on_image: Callable | None = None,
                          on_step: Callable | None = None,
                          variants: dict[str, int] | None = None,
                          keep: bool = False) -> None:
    """One SDXL image per scene from prompts[scene_id].
    Each image carries a .meta stamp so a new prompt or seed regenerates it;
    a reroll bumps the scene's variant (new seed)."""
    negative = negative_for(style)
    images_dir.mkdir(parents=True, exist_ok=True)
    variants = variants or {}
    pending = []
    for scene in scenes:
        out = images_dir / f"{scene.scene_id}.png"
        prompt = prompts[scene.scene_id]
        scene.visual_style_prompt = prompt
        stamp = f"sdxl|txt2img-v3-{SIZE[0]}x{SIZE[1]}-{STEPS}-{CFG}|{seed}|{prompt}|{negative}"
        if variants.get(scene.scene_id):
            stamp += f"|v{variants[scene.scene_id]}"
        meta = out.with_suffix(".meta")
        if out.exists() and out.stat().st_size > 0 and meta.exists() and (
                keep or meta.read_text(encoding="utf-8") == stamp):
            log(f"  image: {out.name} (cached)")
            scene.image_path = out
            if on_image:
                on_image(scene, True)
            continue
        pending.append((scene, out, meta, stamp, prompt))
    if not pending:
        return

    try:
        import torch
    except ImportError as e:
        raise ImageGenError(INSTALL_HINT) from e
    device = _device(torch)
    if device == "cpu":
        log("  warning: no XPU device found, local images will be very slow")
    log("  loading sdxl on %s (first run downloads the model)..." % device)
    if on_step:
        on_step(None, 0, 0, "cargando sdxl")
    gc.collect()
    if device == "xpu":
        torch.xpu.empty_cache()
    try:
        pipe = _load_sdxl_txt2img(torch, device)
    except ImportError as e:
        raise ImageGenError(INSTALL_HINT) from e
    except RuntimeError as e:
        if "level_zero" in str(e):
            raise ImageGenError(DRIVER_HINT.format(error=e)) from e
        raise
    try:
        for scene, out, meta, stamp, prompt in pending:
            def step_cb(p, i, t, kw, scene=scene):
                if on_step:
                    on_step(scene, i + 1, p.num_timesteps, "pasos")
                return kw
            generator = torch.Generator("cpu").manual_seed(
                scene_seed(seed, scene.scene_id, variants.get(scene.scene_id, 0)))
            image = pipe(prompt=prompt, negative_prompt=negative, width=SIZE[0], height=SIZE[1],
                         num_inference_steps=STEPS, guidance_scale=CFG, generator=generator,
                         callback_on_step_end=step_cb).images[0]
            tmp = out.with_suffix(".tmp.png")
            image.save(tmp)
            tmp.replace(out)
            meta.write_text(stamp, encoding="utf-8")
            scene.image_path = out
            log(f"  image: {out.name}")
            if on_image:
                on_image(scene, False)
    except BaseException as exc:
        # the traceback's diffusers frames hold the pipeline: clear them so it is
        # freed here, not after a retry has already loaded a second copy (XPU OOM)
        traceback.clear_frames(exc.__traceback__)
        raise
    finally:
        del pipe
        gc.collect()
        if device == "xpu":
            torch.xpu.empty_cache()


def credits_card(out: Path, author: str, subreddit: str, ffmpeg: str,
                 width: int, height: int) -> Path:
    """End card of a Reddit story: icon, CREDITS_TITLE, u/author, r/subreddit,
    drawn by ffmpeg at the video size (no PIL). Reused when it exists."""
    if out.exists() and out.stat().st_size > 0:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)

    def line(text: str, y: str, div: int, color: str = "white") -> str:
        return (f"drawtext=text='{_drawtext_escape(text)}':{_FONT}:fontsize=h/{div}:"
                f"fontcolor={color}:x=(w-text_w)/2:y={y}:expansion=none")

    texts = ",".join([line(CREDITS_TITLE, "h*0.50", 18), line(f"u/{author}", "h*0.58", 26, "#ff4500"),
                      line(f"r/{subreddit}", "h*0.63", 34, "#d7dadc")])
    inputs = ["-f", "lavfi", "-i", f"color=c=0x1a1a1b:s={width}x{height}:d=1"]
    if REDDIT_ICON.is_file():
        inputs += ["-i", str(REDDIT_ICON)]
        graph = (f"[1:v]scale={int(height * 0.16)}:-1[icon];"
                 f"[0:v][icon]overlay=(W-w)/2:H*0.30[bg];[bg]{texts}")
    else:
        graph = f"[0:v]{texts}"
    tmp = out.with_suffix(".tmp.png")
    subprocess.run([ffmpeg, "-y", "-nostdin", "-loglevel", "error", *inputs, "-filter_complex", graph,
                    "-frames:v", "1", str(tmp)], check=True, stdin=subprocess.DEVNULL)
    tmp.replace(out)
    return out


def silence_wav(out: Path, seconds: float, ffmpeg: str) -> Path:
    if not (out.exists() and out.stat().st_size > 0):
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=44100:cl=stereo", "-t", f"{seconds:.3f}", str(out)],
                       check=True, stdin=subprocess.DEVNULL)
    return out


def placeholder_images(scenes: list[Scene], images_dir: Path, ffmpeg: str,
                       base_image: Path | None, log: Callable = print) -> None:
    """Test mode: the photo for every scene, or one flat color per scene."""
    if base_image is not None:
        generate_test_images(scenes, base_image, images_dir, ffmpeg, log=log)
        return
    images_dir.mkdir(parents=True, exist_ok=True)
    for scene in scenes:
        out = images_dir / f"{scene.scene_id}.png"
        scene.visual_style_prompt = "[test mode, flat color]"
        if not (out.exists() and out.stat().st_size > 0):
            color = PLACEHOLDER_COLORS[(scene.index - 1) % len(PLACEHOLDER_COLORS)]
            subprocess.run([ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-f", "lavfi",
                            "-i", f"color=c=0x{color}:s=540x960:d=1", "-frames:v", "1",
                            str(out)], check=True, stdin=subprocess.DEVNULL)
        scene.image_path = out
        log(f"  image: {out.name} (test mode)")
