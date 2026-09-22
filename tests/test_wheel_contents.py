#!/usr/bin/env python3
"""Regression: release wheel contains source/package data, never local bytecode caches."""
from __future__ import annotations

import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wheel_contains_runtime_provider_and_excludes_local_build_caches() -> None:
    with tempfile.TemporaryDirectory(prefix="mw-wheel-content-") as tmp:
        result = subprocess.run(
            ["uv", "build", "--out-dir", tmp], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        assert result.returncode == 0, result.stdout.decode("utf-8", "replace")[-4000:]
        wheel = next(Path(tmp).glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
        required = {
            "memory_wiki/__init__.py",
            "memory_wiki/extractor.py",
            "memory_wiki/migrations.py",
            "memory_wiki/plugin.yaml",
            "memory_wiki/mcp-wrapper/server.py",
            "memory_wiki/context-coordination/manifest_protocol.py",
        }
        assert required.issubset(names), sorted(required.difference(names))
        assert not any("/__pycache__/" in name or name.endswith(".pyc") for name in names)


if __name__ == "__main__":
    test_wheel_contains_runtime_provider_and_excludes_local_build_caches()
    print("PASS test_wheel_contains_runtime_provider_and_excludes_local_build_caches")
