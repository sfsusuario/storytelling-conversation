"""XTTS synthesis worker. Runs inside the dedicated XTTS venv
(.xtts-venv, Python 3.10 + coqui-tts), NOT the main charla environment.

Usage: python scripts/xtts_worker.py jobs.json

jobs.json:
{
  "language": "es",
  "jobs": [
    {"speaker": "rick",
     "model_dir": "models/xtts/rick",   # fine-tuned checkpoint dir, or ""
     "refs": ["clip1.wav", ...],        # reference audio for the voice
     "files": [["texto a decir", "out.wav"], ...]},
    ...
  ]
}

With a model_dir containing config.json + vocab.json + a .pth checkpoint
(the output of the XTTS fine-tuning Colab), that model is used. Otherwise
the base XTTS v2 model is downloaded/cached and the voice is zero-shot
cloned from the reference clips. Mirrors the inference code of the
xtts_ft_demo notebook (Xtts.load_checkpoint + get_conditioning_latents).
"""
import glob
import json
import os
import sys

os.environ.setdefault("COQUI_TOS_AGREED", "1")


def _find_checkpoint(model_dir: str) -> tuple[str, str, str] | None:
    if not model_dir or not os.path.isdir(model_dir):
        return None
    config = os.path.join(model_dir, "config.json")
    vocab = os.path.join(model_dir, "vocab.json")
    ckpts = (glob.glob(os.path.join(model_dir, "best_model.pth"))
             or glob.glob(os.path.join(model_dir, "model.pth"))
             or glob.glob(os.path.join(model_dir, "*.pth")))
    if os.path.isfile(config) and os.path.isfile(vocab) and ckpts:
        return ckpts[0], config, vocab
    return None


def _base_model_dir() -> str:
    from TTS.utils.manage import ModelManager
    manager = ModelManager()
    model_path, _, _ = manager.download_model(
        "tts_models/multilingual/multi-dataset/xtts_v2")
    return model_path


def _load(checkpoint: str, config_path: str, vocab: str):
    import torch
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.models.xtts import Xtts

    config = XttsConfig()
    config.load_json(config_path)
    model = Xtts.init_from_config(config)
    model.load_checkpoint(config, checkpoint_path=checkpoint,
                          vocab_path=vocab, use_deepspeed=False)
    if torch.cuda.is_available():
        model.cuda()
    return model, config


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as f:
        spec = json.load(f)

    import torch
    import torchaudio

    language = spec.get("language", "es")
    base_dir = None
    for job in spec["jobs"]:
        found = _find_checkpoint(job.get("model_dir", ""))
        if found is None:
            if base_dir is None:
                base_dir = _base_model_dir()
            found = (os.path.join(base_dir, "model.pth"),
                     os.path.join(base_dir, "config.json"),
                     os.path.join(base_dir, "vocab.json"))
            print(f"[{job['speaker']}] base XTTS v2 + zero-shot refs",
                  flush=True)
        else:
            print(f"[{job['speaker']}] fine-tuned: {found[0]}", flush=True)

        model, config = _load(*found)
        gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(
            audio_path=job["refs"],
            gpt_cond_len=config.gpt_cond_len,
            max_ref_length=config.max_ref_len,
            sound_norm_refs=config.sound_norm_refs)

        for text, out_path in job["files"]:
            out = model.inference(
                text=text, language=language,
                gpt_cond_latent=gpt_cond_latent,
                speaker_embedding=speaker_embedding,
                temperature=config.temperature,
                length_penalty=config.length_penalty,
                repetition_penalty=config.repetition_penalty,
                top_k=config.top_k, top_p=config.top_p)
            wav = torch.tensor(out["wav"]).unsqueeze(0)
            torchaudio.save(out_path, wav, 24000)
            print(f"synthesized: {out_path}", flush=True)
        del model
    return 0


if __name__ == "__main__":
    sys.exit(main())
