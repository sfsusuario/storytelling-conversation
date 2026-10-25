"""Chatterbox speed benchmark for one device / thread count.

Runs inside a Chatterbox venv (not the main charla env), from the repo root:

  .chatterbox-venv\\Scripts\\python.exe scripts\\bench_chatterbox.py --threads 4
  .chatterbox-venv\\Scripts\\python.exe scripts\\bench_chatterbox.py --threads 8
  .chatterbox-xpu-venv\\Scripts\\python.exe scripts\\bench_chatterbox.py --device xpu

Measures model load, voice-reference preparation and a warm-up line
separately, then synthesizes fixed Spanish lines with fixed seeds. The
headline metric is the real-time factor (RTF = synthesis seconds / audio
seconds), which stays comparable even when sampling yields slightly
different lengths. Wavs of the first pass land in output/_bench/ so the
result can be checked by ear. Last line: "SUMMARY {json}".
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

LINES = [
    "Claro que no es normal, Morty, son pulpos. Dos corazones bombean "
    "sangre a las branquias y uno al resto del cuerpo.",
    "¿S-sangre azul? ¿Y si un día se les acaba el... el cobre, Rick?",
    "No se les acaba, Morty. Lo único que se acaba aquí es mi paciencia.",
]


def default_ref(speaker: str = "rick") -> str:
    """Same pick as charla.chatterbox.character_ref: largest dataset wav."""
    root = Path("voices_preview/reales")
    cands = sorted((root / f"dataset_{speaker}").glob("*.wav")) or sorted(
        list((root / speaker).glob("*.wav")) + list((root / speaker).glob("*.mp3")))
    if not cands:
        raise SystemExit(f"no reference clip under {root} for {speaker}")
    return str(max(cands, key=lambda p: p.stat().st_size))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--device", default="cpu", help="auto|cpu|xpu|cuda")
    ap.add_argument("--threads", type=int, default=0,
                    help="torch CPU threads (0 = torch default)")
    ap.add_argument("--ref", default=None, help="reference clip")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--exaggeration", type=float, default=0.7)
    ap.add_argument("--out", default="output/_bench")
    args = ap.parse_args()

    os.environ.setdefault("TQDM_DISABLE", "1")
    os.environ.setdefault("PYTORCH_ENABLE_XPU_FALLBACK", "1")
    if args.threads > 0:  # must be set before torch is imported
        os.environ["OMP_NUM_THREADS"] = os.environ["MKL_NUM_THREADS"] = \
            str(args.threads)

    import torch
    import torchaudio
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from chatterbox_worker import load_model, pick_device

    if args.threads > 0:
        torch.set_num_threads(args.threads)
    device = pick_device(torch, args.device)
    sync = (getattr(torch, device).synchronize
            if device in ("cuda", "xpu") else (lambda: None))
    ref = args.ref or default_ref()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{device}_t{torch.get_num_threads()}"
    print(f"device={device} threads={torch.get_num_threads()} "
          f"torch={torch.__version__} ref={ref}", flush=True)

    t0 = time.perf_counter()
    model = load_model(device)
    sync()
    t_load = time.perf_counter() - t0

    with torch.inference_mode():
        t0 = time.perf_counter()
        model.prepare_conditionals(ref, exaggeration=args.exaggeration)
        sync()
        t_cond = time.perf_counter() - t0

        torch.manual_seed(args.seed)
        t0 = time.perf_counter()
        model.generate("Hola, Morty.", language_id="es",
                       exaggeration=args.exaggeration)
        sync()
        t_warm = time.perf_counter() - t0
        print(f"load {t_load:.1f}s · ref {t_cond:.1f}s · warm-up "
              f"{t_warm:.1f}s", flush=True)

        runs = []
        for rep in range(args.reps):
            for i, text in enumerate(LINES):
                torch.manual_seed(args.seed + i)
                t0 = time.perf_counter()
                wav = model.generate(text, language_id="es",
                                     exaggeration=args.exaggeration,
                                     cfg_weight=0.5)
                sync()
                seconds = time.perf_counter() - t0
                audio = wav.shape[-1] / model.sr
                runs.append({"rep": rep, "line": i, "seconds": seconds,
                             "audio": audio, "rtf": seconds / audio})
                print(f"  line {i} rep {rep}: {seconds:6.1f}s for "
                      f"{audio:4.1f}s of audio (RTF {seconds / audio:.2f})",
                      flush=True)
                if rep == 0:
                    torchaudio.save(str(out_dir / f"{tag}_line{i}.wav"),
                                    wav.cpu(), model.sr)

    summary = {
        "device": device, "threads": torch.get_num_threads(),
        "torch": torch.__version__,
        "load_s": round(t_load, 1), "ref_s": round(t_cond, 1),
        "warmup_s": round(t_warm, 1),
        "median_line_s": round(statistics.median(r["seconds"] for r in runs), 1),
        "median_rtf": round(statistics.median(r["rtf"] for r in runs), 2),
        "total_audio_s": round(sum(r["audio"] for r in runs), 1),
        "total_synth_s": round(sum(r["seconds"] for r in runs), 1),
    }
    print("SUMMARY " + json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
