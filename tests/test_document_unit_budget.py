#!/usr/bin/env python3
"""Regression: OOXML parsers never exceed their declared unit budget."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import zipfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_extractors.py"


def load_module():
    spec = importlib.util.spec_from_file_location("memory_wiki_document_unit_budget_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_docx_and_pptx_enforce_max_units_inside_composite_structures() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory(prefix="mw-unit-budget-") as tmp:
        root = Path(tmp)
        docx = root / "table.docx"
        pptx = root / "slides.pptx"
        xlsx = root / "sheet.xlsx"
        doc_xml = """<w:document xmlns:w="w"><w:body><w:tbl>
            <w:tr><w:tc><w:p><w:r><w:t>Header</w:t></w:r></w:p></w:tc></w:tr>
            <w:tr><w:tc><w:p><w:r><w:t>Row one</w:t></w:r></w:p></w:tc></w:tr>
            <w:tr><w:tc><w:p><w:r><w:t>Row two</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl></w:body></w:document>"""
        slide_xml = """<p:sld xmlns:p="p" xmlns:a="a"><p:spTree>
            <p:sp><a:t>First shape</a:t></p:sp>
            <p:sp><a:t>Second shape</a:t></p:sp>
            <p:sp><a:t>Third shape</a:t></p:sp>
        </p:spTree></p:sld>"""
        with zipfile.ZipFile(docx, "w") as zf:
            zf.writestr("word/document.xml", doc_xml)
        with zipfile.ZipFile(pptx, "w") as zf:
            zf.writestr("ppt/slides/slide1.xml", slide_xml)
        with zipfile.ZipFile(xlsx, "w") as zf:
            zf.writestr("xl/worksheets/sheet1.xml", """<worksheet xmlns=\"x\"><sheetData><row r=\"1\"><c r=\"A1\"><v>value</v></c></row></sheetData></worksheet>""")

        limits = {"max_entries": 100, "max_uncompressed": 1_000_000, "max_ratio": 200}
        assert len(module.extract_docx(docx, 1, limits).units) <= 1
        assert len(module.extract_pptx(pptx, 1, limits).units) <= 1
        assert len(module.extract_xlsx(xlsx, 1, 100, limits).units) <= 1


if __name__ == "__main__":
    test_docx_and_pptx_enforce_max_units_inside_composite_structures()
    print("PASS test_docx_and_pptx_enforce_max_units_inside_composite_structures")
