"""Local identity-preserving image generation on the Intel iGPU (PyTorch XPU).

Two backends, both fed the downscaled base photo and a fixed per-scene seed:
  flux-kontext — FLUX.1 Kontext [dev] instruction editing, GGUF Q4 transformer.
                 FLUX_STRENGTH < 1 starts from the photo (img2img) instead of
                 noise. Closest to Gemini in quality; ~12 min per image here.
  sdxl-face    — SDXL img2img + IP-Adapter plus-face. About a minute per
                 image; keeps composition, weaker on the face.
Pipelines load once per run, generate serially (one GPU) and are freed after.
"""
from __future__ import annotations

import gc
import hashlib
import traceback
from pathlib import Path
from typing import Callable

from .models import Scene

FLUX_REPO = "black-forest-labs/FLUX.1-Kontext-dev"
FLUX_GGUF = ("https://huggingface.co/QuantStack/FLUX.1-Kontext-dev-GGUF/"
             "blob/main/flux1-kontext-dev-Q4_K_M.gguf")
SDXL_REPO = "stabilityai/stable-diffusion-xl-base-1.0"
SDXL_NEGATIVE = ("deformed face, distorted features, extra limbs, blurry, "
                 "low quality, watermark, text")
LOCAL_MAX_EDGE = 1024
# Kontext from pure noise re-poses the subject to fit the new setting; starting
# from the photo's latents keeps pose and framing. Lower = closer to the photo.
FLUX_STRENGTH = 1.0  # tested: 0.8 returns the photo unchanged, 0.92 keeps the old clothes
# Part of the image cache stamp: bump when generation settings change.
LOCAL_STAMP = f"img2img-{FLUX_STRENGTH}"

INSTALL_HINT = (
    "Local image generation needs PyTorch XPU + diffusers. Install with:\n"
    "  python -m pip install torch --index-url https://download.pytorch.org/whl/xpu\n"
    "  python -m pip install -e \".[image-local]\"")


# Seen with driver 32.0.101.7026 (Aug 2025) + torch 2.14 XPU: intermittent
# OUT_OF_DEVICE_MEMORY with <1 GB allocated, then DEVICE_LOST on retry.
DRIVER_HINT = (
    "The Intel GPU driver failed while loading the image model ({error}).\n"
    "This is a driver problem, not real lack of memory. Update the Intel Arc "
    "driver (Intel Driver & Support Assistant, or intel.com/arc-drivers), "
    "reboot, and retry; meanwhile use --image-provider gemini or --test-mode.")


def scene_seed(seed: int | None, scene_id: str, variant: int = 0) -> int:
    """Stable per-scene seed: same run seed + scene (+ variant) -> same image."""
    key = f"{scene_id}#{variant}" if variant else scene_id
    digest = hashlib.sha256(f"{seed or 0}|{key}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def local_available() -> bool:
    try:
        import diffusers  # noqa: F401
        import torch
        return torch.xpu.is_available()
    except Exception:
        return False


def _device(torch) -> str:
    return "xpu" if torch.xpu.is_available() else "cpu"


def _load_flux(torch, device: str):
    from diffusers import (FluxKontextInpaintPipeline, FluxTransformer2DModel,
                           GGUFQuantizationConfig)

    transformer = FluxTransformer2DModel.from_single_file(
        FLUX_GGUF,
        quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16),
        config=FLUX_REPO, subfolder="transformer", torch_dtype=torch.bfloat16)
    # The inpaint variant is the Kontext pipeline with img2img `strength`.
    pipe = FluxKontextInpaintPipeline.from_pretrained(
        FLUX_REPO, transformer=transformer, torch_dtype=torch.bfloat16)
    # Transformer + T5 exceed the iGPU's 16 GB share; offload swaps them in turn.
    pipe.enable_model_cpu_offload(device=device)
    return pipe


def _load_sdxl(torch, device: str):
    from diffusers import StableDiffusionXLImg2ImgPipeline

    from diffusers.models.attention_processor import (AttnProcessor,
                                                      IPAdapterAttnProcessor,
                                                      IPAdapterAttnProcessor2_0)

    # bf16, not fp16: the fp16 SDXL VAE overflows into NaN (black images).
    pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
        SDXL_REPO, torch_dtype=torch.bfloat16, variant="fp16")
    pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                         weight_name="ip-adapter-plus-face_sdxl_vit-h.safetensors",
                         image_encoder_folder="models/image_encoder")
    pipe.set_ip_adapter_scale(0.6)
    # SDPA attention returns NaN (black images) on XPU with driver
    # 32.0.101.9150; the classic processors with the same weights work.
    procs = {}
    for name, proc in pipe.unet.attn_processors.items():
        if isinstance(proc, IPAdapterAttnProcessor2_0):
            classic = IPAdapterAttnProcessor(proc.hidden_size, proc.cross_attention_dim,
                                             proc.num_tokens, proc.scale)
            classic.load_state_dict(proc.state_dict())
            procs[name] = classic.to(torch.bfloat16)
        else:
            procs[name] = AttnProcessor()
    pipe.unet.set_attn_processor(procs)
    return pipe.to(device)


def _fit(image, max_edge: int = LOCAL_MAX_EDGE):
    """Resize to <= max_edge with both sides a multiple of 16."""
    scale = min(1.0, max_edge / max(image.size))
    w, h = (max(16, int(d * scale) // 16 * 16) for d in image.size)
    return image.resize((w, h))


def generate_local_images(provider: str, pending: list[tuple[Scene, Path]],
                          base_jpg: Path, seed: int | None,
                          log: Callable = print,
                          on_image: Callable | None = None,
                          on_step: Callable | None = None,
                          variants: dict[str, int] | None = None) -> None:
    try:
        import torch
        from PIL import Image
    except ImportError as e:
        from .image_gen import ImageGenError
        raise ImageGenError(INSTALL_HINT) from e

    device = _device(torch)
    if device == "cpu":
        log("  warning: no XPU device found, local images will be very slow")
    log(f"  loading {provider} on {device} (first run downloads the model)...")
    if on_step:
        on_step(None, 0, 0, f"cargando {provider}")
    from .image_gen import ImageGenError
    # a model a previous failed run left in reference cycles would double the use
    gc.collect()
    if device == "xpu":
        torch.xpu.empty_cache()
    try:
        pipe = (_load_flux if provider == "flux-kontext" else _load_sdxl)(torch, device)
    except ImportError as e:
        raise ImageGenError(INSTALL_HINT) from e
    except RuntimeError as e:
        if "level_zero" in str(e):
            raise ImageGenError(DRIVER_HINT.format(error=e)) from e
        raise

    base = _fit(Image.open(base_jpg).convert("RGB"))
    repaint_all = Image.new("L", base.size, 255)  # white mask = whole frame
    try:
        # on_image may put rerolled scenes at the front: pop, don't iterate
        while pending:
            scene, out = pending.pop(0)

            def step_cb(p, i, t, kw, scene=scene):
                if on_step:  # p.num_timesteps: steps actually run (img2img runs fewer)
                    on_step(scene, i + 1, p.num_timesteps, "pasos")
                return kw
            generator = torch.Generator("cpu").manual_seed(
                scene_seed(seed, scene.scene_id, (variants or {}).get(scene.scene_id, 0)))
            if provider == "flux-kontext":
                image = pipe(image=base, mask_image=repaint_all,
                             strength=FLUX_STRENGTH,
                             prompt=scene.visual_style_prompt,
                             guidance_scale=2.5, num_inference_steps=24,
                             generator=generator, callback_on_step_end=step_cb).images[0]
            else:
                image = pipe(prompt=scene.visual_style_prompt,
                             negative_prompt=SDXL_NEGATIVE, image=base,
                             ip_adapter_image=base, strength=0.55,
                             num_inference_steps=30, guidance_scale=6.0,
                             generator=generator, callback_on_step_end=step_cb).images[0]
            tmp = out.with_suffix(".tmp.png")
            image.save(tmp)
            tmp.replace(out)
            scene.image_path = out
            log(f"  image: {out.name} ({scene.persona.name})")
            if on_image:
                on_image(scene)
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
