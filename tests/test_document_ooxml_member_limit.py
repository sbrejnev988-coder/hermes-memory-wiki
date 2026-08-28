#!/usr/bin/env python3
"""Regression: configured ZIP member cap applies to OOXML XML parts."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import zipfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_extractors.py"


def load_module():
    spec = importlib.util.spec_from_file_location("memory_wiki_ooxml_member_limit_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_docx_xml_part_over_configured_member_cap_is_rejected() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory(prefix="mw-ooxml-member-") as tmp:
        path = Path(tmp) / "oversized.docx"
        body = "<w:document xmlns:w=\"w\"><w:body><w:p><w:r><w:t>" + ("x" * 1_126_487) + "</w:t></w:r></w:p></w:body></w:document>"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", body)
        try:
            module.extract_document(path, {
                "max_bytes": 2 * 1024 * 1024,
                "zip_max_member": 1_024 * 1024,
                "zip_max_entries": 10,
                "zip_expansion_factor": 8,
                "zip_max_ratio": 10_000,
            })
        except ValueError as exc:
            assert "member" in str(exc).lower() or "xml part" in str(exc).lower()
        else:
            raise AssertionError("oversized OOXML XML member was accepted")


if __name__ == "__main__":
    test_docx_xml_part_over_configured_member_cap_is_rejected()
    print("PASS test_docx_xml_part_over_configured_member_cap_is_rejected")
