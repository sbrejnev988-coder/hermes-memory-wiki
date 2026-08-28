#!/usr/bin/env python3
"""Regression: per-member budget never bypasses archive path validation."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import zipfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_extractors.py"


def load_module():
    spec = importlib.util.spec_from_file_location("memory_wiki_zip_path_budget_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_large_member_does_not_skip_unsafe_archive_path_validation() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory(prefix="mw-zip-path-") as tmp:
        path = Path(tmp) / "unsafe.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("../unsafe.xhtml", b"x" * 2048)
        with zipfile.ZipFile(path) as archive:
            try:
                module._zip_guard(archive, max_entries=10, max_uncompressed=10_000, max_ratio=1000, max_member=1024)
            except ValueError as exc:
                assert "unsafe archive path" in str(exc)
            else:
                raise AssertionError("oversized unsafe archive path was accepted")


if __name__ == "__main__":
    test_large_member_does_not_skip_unsafe_archive_path_validation()
    print("PASS test_large_member_does_not_skip_unsafe_archive_path_validation")
