#!/usr/bin/env python3
"""Regression: EPUB members are rejected before an oversized decompression allocation."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import zipfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_extractors.py"


def load_module():
    spec = importlib.util.spec_from_file_location("memory_wiki_zip_member_budget_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_epub_member_limit_rejects_oversized_chapter() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory(prefix="mw-epub-member-limit-") as tmp:
        path = Path(tmp) / "large.epub"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("chapter.xhtml", b"<p>" + b"x" * 4096 + b"</p>")
        try:
            module.extract_epub(path, 10, {
                "max_entries": 10, "max_uncompressed": 100_000,
                "max_ratio": 1000, "max_member": 1024,
            })
        except ValueError as exc:
            assert "member" in str(exc).lower()
        else:
            raise AssertionError("oversized EPUB chapter was accepted")


if __name__ == "__main__":
    test_epub_member_limit_rejects_oversized_chapter()
    print("PASS test_epub_member_limit_rejects_oversized_chapter")
