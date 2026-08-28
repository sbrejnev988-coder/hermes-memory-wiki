#!/usr/bin/env python3
"""Fail closed when a release's public version contract diverges."""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"RELEASE_CONTRACT_FAIL: {message}", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    pyproject = ROOT / "pyproject.toml"
    lock = ROOT / "uv.lock"
    license_file = ROOT / "LICENSE"
    for required in (
        pyproject, lock, license_file,
        ROOT / "packaging" / "generate_sbom.py",
        ROOT / "packaging" / "build_native_bundle.py",
        ROOT / "packaging" / "check_reproducible.py",
    ):
        if not required.is_file():
            fail(f"required release file is missing: {required.relative_to(ROOT)}")
    version = str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])
    manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    runtime = (ROOT / "__init__.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checks = {
        "plugin.yaml": re.search(rf"^version:\s*{re.escape(version)}\s*$", manifest, re.M),
        "runtime": re.search(rf'PLUGIN_VERSION\s*=\s*"{re.escape(version)}"', runtime),
        "README": re.search(rf"^# Hermes Memory Wiki v{re.escape(version)}\s*$", readme, re.M),
    }
    for label, matched in checks.items():
        if not matched:
            fail(f"{label} does not declare {version}")
    if args.tag and args.tag != f"v{version}":
        fail(f"tag {args.tag} does not equal v{version}")
    print(f"RELEASE_CONTRACT_OK version={version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
