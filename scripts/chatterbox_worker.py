"""Chatterbox synthesis worker. Runs inside the dedicated venv
(.chatterbox-venv — or .chatterbox-xpu-venv for Intel Arc GPUs — Python 3.10
+ chatterbox-tts), NOT the main charla env.

Usage: python scripts/chatterbox_worker.py jobs.json

jobs.json:
{
  "language": "es",
  "device": "auto",              # auto | cpu | cuda | xpu
  "threads": 4,                  # torch CPU threads (0 = torch default)
  "jobs": [
    {"speaker": "rick",
     "ref": "clip.wav",          # single reference clip for the voice
     "exaggeration": 0.7,        # 0.25..2: emotional intensity
     "cfg_weight": 0.5,
     "files": [["texto a decir", "out.wav"], ...]},
    ...
  ]
}

Zero-shot voice cloning with Resemble AI's Chatterbox multilingual model
(MIT license). The model (~2 GB) downloads from Hugging Face on first use;
later runs load it from the local cache without any network round-trip.
Prints "synthesized: <out.wav>" (flushed) after each line.
"""
import json
import os
import sys

# Same files ChatterboxMultilingualTTS.from_pretrained downloads.
_ALLOW = ["ve.pt", "t3_mtl23ls_v2.safetensors", "s3gen.pt",
          "grapheme_mtl_merged_expanded_v1.json", "conds.pt",
          "Cangjie5_TC.json"]


def pick_device(torch, requested: str = "auto") -> str:
    """auto = cuda -> xpu (Intel Arc; needs an XPU build of torch) -> cpu.
    An explicitly requested device that is missing is an error."""
    requested = (requested or "auto").lower()
    has = {
        "cuda": torch.cuda.is_available(),
        "xpu": hasattr(torch, "xpu") and torch.xpu.is_available(),
        "cpu": True,
    }
    if requested == "auto":
        return next(d for d in ("cuda", "xpu", "cpu") if has[d])
    if requested not in has:
        raise SystemExit(f"unknown device '{requested}' (auto|cpu|cuda|xpu)")
    if not has[requested]:
        raise SystemExit(
            f"device '{requested}' not available in this venv "
            f"(torch {torch.__version__}); for Intel Arc run "
            "install-chatterbox.ps1 -Xpu")
    return requested


def load_model(device: str):
    """ChatterboxMultilingualTTS on `device`.

    Tries the local Hugging Face cache first (no network check on every
    run), downloading only when the files are missing. For devices other
    than cpu/cuda/mps, chatterbox's from_local uses map_location=None, so
    the model is loaded on CPU and then moved (e.g. to "xpu").
    """
    from huggingface_hub import snapshot_download
    from chatterbox.mtl_tts import REPO_ID, ChatterboxMultilingualTTS

    try:
        ckpt = snapshot_download(repo_id=REPO_ID, repo_type="model",
                                 allow_patterns=_ALLOW,
                                 local_files_only=True)
        print("model: local cache", flush=True)
    except Exception:  # not cached yet (LocalEntryNotFoundError & co.)
        print("model: downloading from Hugging Face (~2 GB, first run "
              "only)...", flush=True)
        ckpt = snapshot_download(repo_id=REPO_ID, repo_type="model",
                                 revision="main", allow_patterns=_ALLOW,
                                 token=os.getenv("HF_TOKEN"))

    load_on = device if device in ("cpu", "cuda", "mps") else "cpu"
    model = ChatterboxMultilingualTTS.from_local(ckpt, load_on)
    if load_on != device:
        model.t3.to(device)
        model.s3gen.to(device)
        model.ve.to(device)
        if model.conds is not None:
            model.conds = model.conds.to(device)
        model.device = device
    return model


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as f:
        spec = json.load(f)

    import torch
    import torchaudio

    threads = int(spec.get("threads") or 0)
    if threads > 0:
        torch.set_num_threads(threads)
    language = spec.get("language", "es")
    device = pick_device(torch, spec.get("device", "auto"))
    print(f"device: {device} · threads: {torch.get_num_threads()} · "
          f"torch {torch.__version__}", flush=True)
    model = load_model(device)

    with torch.inference_mode():
        for job in spec["jobs"]:
            exaggeration = float(job.get("exaggeration", 0.5))
            print(f"[{job['speaker']}] ref: {job['ref']}", flush=True)
            # The reference clip is processed ONCE per speaker; generate()
            # without audio_prompt_path reuses it (passing the path re-ran
            # this on every line).
            model.prepare_conditionals(job["ref"], exaggeration=exaggeration)
            for text, out_path in job["files"]:
                wav = model.generate(
                    text,
                    language_id=language,
                    exaggeration=exaggeration,
                    cfg_weight=float(job.get("cfg_weight", 0.5)))
                torchaudio.save(out_path, wav.cpu(), model.sr)
                print(f"synthesized: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
