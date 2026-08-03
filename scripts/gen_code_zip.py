"""Regenerate charla_code.zip for the Colab mode.

Includes src/, scripts/, examples/, pyproject.toml and .env. Written with
POSIX entry names (Compress-Archive would use backslashes, which break
extraction on Linux). Run from the repo root: python scripts/gen_code_zip.py
"""
import zipfile
from pathlib import Path

out = Path("charla_code.zip")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for top in ["src", "scripts", "examples"]:
        for p in Path(top).rglob("*"):
            if (p.is_file() and "__pycache__" not in p.parts
                    and not p.name.endswith(".pyc")
                    and "egg-info" not in str(p)):
                z.write(p, p.as_posix())
    z.write("pyproject.toml", "pyproject.toml")
    if Path(".env").is_file():
        z.write(".env", ".env")

names = zipfile.ZipFile(out).namelist()
assert all("\\" not in n for n in names), "backslash paths in zip!"
print(f"charla_code.zip: {out.stat().st_size} bytes, {len(names)} entradas")
