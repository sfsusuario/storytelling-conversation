"""Voice-conversion worker. Runs inside the dedicated RVC venv
(.rvc-venv, Python 3.10 + rvc-python), NOT the main charla environment.

Usage: python scripts/rvc_worker.py jobs.json

jobs.json:
{
  "device": "cpu",
  "f0method": "rmvpe",
  "jobs": [
    {"model": "models/rvc/rick/rick.pth",
     "index": "models/rvc/rick/rick.index",
     "pitch": 0,
     "files": [["in1.mp3", "out1.wav"], ...]},
    ...
  ]
}

Loads each model once and converts every file assigned to it.
"""
import json
import sys


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as f:
        spec = json.load(f)

    from rvc_python.infer import RVCInference

    rvc = RVCInference(device=spec.get("device", "cpu"))
    for job in spec["jobs"]:
        rvc.load_model(job["model"], index_path=job.get("index") or "")
        rvc.set_params(f0method=spec.get("f0method", "rmvpe"),
                       f0up_key=int(job.get("pitch", 0)))
        for src, dst in job["files"]:
            rvc.infer_file(src, dst)
            print(f"converted: {dst}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
