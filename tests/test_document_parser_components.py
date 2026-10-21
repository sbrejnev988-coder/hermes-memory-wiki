"""Genuine optional parser controls; NOT part of the stdlib SOURCE packet.

A flag is an execution opt-in, not authority. Run only with a separately applicable
finite parser admission, installed compatible libraries and an owned synthetic TMPDIR.
No package installation, model download, network, live home or SDK is used here.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).absolute().parents[1]
INPUTS = globals().get("DEVTOOLS_INPUTS", {})
EXTRACTOR = Path(INPUTS.get("document_extractors.py", ROOT / "document_extractors.py"))
FORMULAS = Path(INPUTS.get("spreadsheet_formulas.py", ROOT / "spreadsheet_formulas.py"))
FORMULAS_SHA256 = "c27cf8175b9561d6028c1c69919196cadf8b2348f52ed88d6a148c3ca39078ac"
MODULES = {}


def read_source(path):
    return devtools_read_bound(str(path)) if "devtools_read_bound" in globals() else path.read_bytes()


def load_source(path, name):
    if name not in MODULES:
        if path == EXTRACTOR:
            raw = read_source(FORMULAS)
            if hashlib.sha256(raw).hexdigest() != FORMULAS_SHA256:
                raise RuntimeError("spreadsheet_helper_source_mismatch")
            helper_spec = importlib.util.spec_from_file_location("spreadsheet_formulas", str(FORMULAS))
            fresh = importlib.util.module_from_spec(helper_spec)
            helper = sys.modules.get(helper_spec.name)
            # Keep a healthy outer XLSX packet's module identity, but execute
            # only the pinned bytes in a fresh, non-ambient namespace.
            if type(helper) is types.ModuleType and helper.__dict__.get("__file__") == str(FORMULAS):
                helper.__dict__.clear()
                helper.__dict__.update(fresh.__dict__)
            else:
                helper = fresh
            sys.modules[helper_spec.name] = helper
            exec(compile(raw, str(FORMULAS), "exec", dont_inherit=True), helper.__dict__)
        spec = importlib.util.spec_from_file_location(name, str(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        exec(compile(read_source(path), str(path), "exec", dont_inherit=True), module.__dict__)
        MODULES[name] = module
    return MODULES[name]


def make_pdf(path, contents):
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for content in contents:
        page_id = len(objects) + 1
        stream_id = page_id + 1
        kids.append(f"{page_id} 0 R")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>".encode())
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    objects[1] = ("<< /Type /Pages /Count " + str(len(kids)) + " /Kids [" + " ".join(kids) + "] >>").encode()
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010} 00000 n \n".encode())
    data.extend(f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(data)


ADMITTED_OPT_IN = os.environ.get("MEMORY_WIKI_PARSER_COMPONENT_OPT_IN") == "1"


@unittest.skipUnless(ADMITTED_OPT_IN, "NOT_RUN without separate finite parser admission and explicit opt-in")
class RealParserComponentTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get("TMPDIR", ""))
        if not root.is_absolute() or not root.is_dir():
            raise RuntimeError("own absolute TMPDIR required")
        self.root = root
        self.e = load_source(EXTRACTOR, "_real_document_parser_component")

    def require(self, name):
        if importlib.util.find_spec(name) is None:
            self.skipTest(f"required genuine {name} is not installed; no stand-in")

    def test_real_pymupdf_grid_and_cell_locators_original_unchanged(self):
        self.require("pymupdf")
        path = self.root / "parser-real-grid.pdf"
        stream = (b"0 0 0 RG 1 w 30 140 m 230 140 l S 30 180 m 230 180 l S 30 220 m 230 220 l S "
                  b"30 140 m 30 220 l S 130 140 m 130 220 l S 230 140 m 230 220 l S "
                  b"BT /F1 12 Tf 40 195 Td (Name) Tj 100 0 Td (Count) Tj ET "
                  b"BT /F1 12 Tf 40 155 Td (Books) Tj 100 0 Td (42) Tj ET")
        make_pdf(path, [stream])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        payload = self.e.extract_document(path, {"pdf_parser": "pymupdf", "pdf_native_fallback": False})
        self.assertEqual(payload["parser"], "pymupdf")
        self.assertEqual(payload["status"], "ok")
        rows = [u for u in payload["units"] if u["kind"] == "table_row"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["metadata"]["cells"][1]["text"], "42")
        self.assertIn("bbox", rows[1]["metadata"]["cells"][1]["locator"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_real_pymupdf_empty_middle_is_partial_not_empty_success(self):
        self.require("pymupdf")
        path = self.root / "parser-real-partial.pdf"
        body = b"BT /F1 12 Tf 30 200 Td (Native document body with known page text) Tj ET"
        make_pdf(path, [body, b"", body])
        payload = self.e.extract_document(path, {"pdf_parser": "pymupdf", "pdf_native_fallback": False})
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["metadata"]["coverage"]["missing_pages"], 1)
        self.assertEqual([p["page"] for p in payload["metadata"]["pages"]], [1, 2, 3])
        self.assertEqual(payload["metadata"]["pages"][1]["quality"]["status"], "empty")

    def test_real_pypdf_native_text_without_fabricated_geometry(self):
        self.require("pypdf")
        path = self.root / "parser-real-pypdf.pdf"
        make_pdf(path, [b"BT /F1 12 Tf 30 200 Td (Native fallback text) Tj ET"])
        payload = self.e.extract_document(path, {"pdf_parser": "pypdf"})
        self.assertEqual(payload["status"], "ok")
        self.assertIn("Native fallback text", payload["units"][0]["text"])
        self.assertEqual(payload["units"][0]["locator"], {"page": 1})


if __name__ == "__main__":
    unittest.main()
