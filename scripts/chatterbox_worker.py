"""Chatterbox synthesis worker. Runs inside the dedicated venv
(.chatterbox-venv, Python 3.10 + chatterbox-tts), NOT the main charla env.

Usage: python scripts/chatterbox_worker.py jobs.json

jobs.json:
{
  "language": "es",
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
(MIT license). The model (~2 GB) downloads from Hugging Face on first use.
"""
import json
import sys


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as f:
        spec = json.load(f)

    import torch
    import torchaudio
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    language = spec.get("language", "es")
    device = spec.get("device") or (
        "cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}", flush=True)
    model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    for job in spec["jobs"]:
        print(f"[{job['speaker']}] ref: {job['ref']}", flush=True)
        for text, out_path in job["files"]:
            wav = model.generate(
                text,
                language_id=language,
                audio_prompt_path=job["ref"],
                exaggeration=float(job.get("exaggeration", 0.5)),
                cfg_weight=float(job.get("cfg_weight", 0.5)))
            torchaudio.save(out_path, wav, model.sr)
            print(f"synthesized: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
