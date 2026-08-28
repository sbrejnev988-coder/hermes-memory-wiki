#!/usr/bin/env python3
"""Fail the release if two clean wheel builds differ byte-for-byte."""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest_wheel(directory: Path) -> tuple[str, Path]:
    wheels = sorted(directory.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one wheel in {directory}, found {len(wheels)}")
    return hashlib.sha256(wheels[0].read_bytes()).hexdigest(), wheels[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-date-epoch", default=os.environ.get("SOURCE_DATE_EPOCH", ""))
    args = parser.parse_args()
    env = dict(os.environ)
    if args.source_date_epoch:
        env["SOURCE_DATE_EPOCH"] = str(args.source_date_epoch)
    with tempfile.TemporaryDirectory(prefix="memory-wiki-repro-") as tmp:
        first = Path(tmp) / "first"
        second = Path(tmp) / "second"
        for target in (first, second):
            result = subprocess.run(
                ["uv", "build", "--wheel", "--out-dir", str(target)],
                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
            )
            if result.returncode:
                raise RuntimeError(result.stdout.decode("utf-8", "replace")[-4000:])
        first_hash, first_wheel = digest_wheel(first)
        second_hash, second_wheel = digest_wheel(second)
        if first_hash != second_hash:
            raise RuntimeError(f"wheel is not reproducible: {first_wheel.name} {first_hash} != {second_hash}")
    print(f"REPRODUCIBLE_WHEEL_OK sha256={first_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
