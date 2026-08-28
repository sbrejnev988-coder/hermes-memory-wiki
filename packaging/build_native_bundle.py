#!/usr/bin/env python3
"""Build a tagged native Hermes plugin ZIP from an immutable Git tree."""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree-ish", default="HEAD")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    output = Path(args.output) if args.output else ROOT / "dist" / f"memory-wiki-v{version}-native.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"memory-wiki-v{version}/"
    archive = subprocess.run(
        ["git", "archive", "--format=zip", f"--prefix={prefix}", args.tree_ish],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if archive.returncode:
        raise RuntimeError(archive.stderr.decode("utf-8", "replace")[-2000:])
    output.write_bytes(archive.stdout)
    with zipfile.ZipFile(output) as bundle:
        manifest_name = prefix + "plugin.yaml"
        if manifest_name not in bundle.namelist():
            raise RuntimeError("native archive omitted plugin.yaml")
        if f"version: {version}" not in bundle.read(manifest_name).decode("utf-8"):
            raise RuntimeError("native archive version differs from pyproject release version")
    print(f"NATIVE_BUNDLE_OK output={output} sha256={hashlib.sha256(output.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
