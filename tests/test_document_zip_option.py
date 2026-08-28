#!/usr/bin/env python3
"""Regression: worker passes a bounded per-member ZIP limit to every archive parser."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_zip_option_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_options_expose_per_member_zip_ceiling() -> None:
    before = os.environ.get("MEMORY_WIKI_DOCUMENT_ZIP_MAX_MEMBER_BYTES")
    try:
        os.environ["MEMORY_WIKI_DOCUMENT_ZIP_MAX_MEMBER_BYTES"] = "2097152"
        module = load_module()
        assert module._worker_options({})["zip_max_member"] == 2_097_152
    finally:
        if before is None:
            os.environ.pop("MEMORY_WIKI_DOCUMENT_ZIP_MAX_MEMBER_BYTES", None)
        else:
            os.environ["MEMORY_WIKI_DOCUMENT_ZIP_MAX_MEMBER_BYTES"] = before


if __name__ == "__main__":
    test_worker_options_expose_per_member_zip_ceiling()
    print("PASS test_worker_options_expose_per_member_zip_ceiling")
