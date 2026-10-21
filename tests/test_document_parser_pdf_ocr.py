"""SOURCE controls for PDF record consumers, TSV decoding and worker protocol.

This file does NOT import a PDF/OCR engine or create parser subprocesses.
Run through devtools/harness.py (bound whole modules), or standalone stdlib unittest.
Actual parser qualification is a separate, explicitly admitted component target.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest
import zipfile

ROOT = Path(__file__).absolute().parents[1]
EXTRACTOR = Path(globals().get("DEVTOOLS_INPUTS", {}).get("document_extractors.py", ROOT / "document_extractors.py"))
WORKER = Path(globals().get("DEVTOOLS_INPUTS", {}).get("document_worker.py", ROOT / "document_worker.py"))
FORMULAS = Path(globals().get("DEVTOOLS_INPUTS", {}).get("spreadsheet_formulas.py", ROOT / "spreadsheet_formulas.py"))
FORMULAS_SHA256 = "c27cf8175b9561d6028c1c69919196cadf8b2348f52ed88d6a148c3ca39078ac"
MODULES = {}


def read_source(path):
    if "devtools_read_bound" in globals():
        return devtools_read_bound(str(path))
    return path.read_bytes()


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


def fixture_root():
    root = Path(globals().get("DEVTOOLS_SCRATCH", os.environ.get("TMPDIR", "")))
    if not root.is_absolute() or not root.is_dir():
        raise RuntimeError("own absolute synthetic scratch required; no system-temp fallback")
    return root


def sample_table():
    return {"bbox": [10, 30, 110, 70], "rows": [
        {"bbox": [10, 30, 110, 50], "cells": [
            {"text": "Name", "bbox": [10, 30, 60, 50]}, {"text": "Count", "bbox": [60, 30, 110, 50]}]},
        {"bbox": [10, 50, 110, 70], "cells": [
            {"text": "Books", "bbox": [10, 50, 60, 70]}, {"text": "42", "bbox": [60, 50, 110, 70]}]}]}


TSV_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


def tsv_page(number, text="Recognized document sample", conf=96):
    result = f"1\t{number}\t0\t0\t0\t0\t0\t0\t800\t600\t-1\t\n"
    for index, word in enumerate(text.split(), 1):
        result += f"5\t{number}\t1\t1\t1\t{index}\t{index * 20}\t20\t20\t15\t{conf}\t{word}\n"
    return result


class ParserSourceTests(unittest.TestCase):
    def setUp(self):
        self.e = load_source(EXTRACTOR, "document_extractors")
        self.o = self.e.effective_extraction_options({"pdf_native_fallback": False})

    def test_structural_blocks_tables_cells_and_reading_order(self):
        e, o = self.e, self.o
        out = e._PdfOutput(o)
        blocks = [(10, 80, 110, 90, "After table", 9, 0),
                  (10, 10, 110, 20, "Before table", 4, 0),
                  (10, 30, 110, 70, "Name Count Books 42", 7, 0),
                  (0, 0, 1, 1, "image not text", 0, 1)]
        diag = e._pdf_emit_page(out, 2, "Before table Name Count Books 42 After table", blocks, [sample_table()], o)
        payload = e.ExtractedDocument("pymupdf", "application/pdf", "Fixture", out.units).to_dict()
        units = payload["units"]
        self.assertEqual([u["kind"] for u in units], ["page", "text_block", "table", "table_row", "table_row", "text_block"])
        self.assertEqual([u["anchor"] for u in units if u["kind"] == "text_block"], ["page:2/block:4", "page:2/block:9"])
        self.assertEqual(units[0]["text"], "")
        self.assertEqual(units[3]["parent_anchor"], "page:2/table:1")
        cell = units[4]["metadata"]["cells"][1]
        self.assertEqual(cell["text"], "42")
        self.assertEqual(cell["anchor"], "page:2/table:1/row:2/cell:2")
        self.assertEqual(cell["locator"], {"page": 2, "table": 1, "row": 2, "column": 2,
            "bbox": [60.0, 50.0, 110.0, 70.0], "coordinate_system": "pymupdf_unrotated_top_left_points"})
        self.assertEqual(diag["reading_order_method"], "geometric_y1_x0")
        self.assertEqual(diag["text_units"], 4)
        self.assertEqual(len({u.anchor for u in out.units}), len(out.units))

    def test_table_context_redaction_including_overlapping_blocks(self):
        e, o = self.e, self.o
        table = sample_table()
        table["rows"][0]["cells"][1]["text"] = "Password"
        table["rows"][1]["cells"][1]["text"] = "SyntheticTableCanary9988"
        out = e._PdfOutput(o)
        e._pdf_emit_page(out, 1, "Books Password SyntheticTableCanary9988", [
            (0, 20, 140, 90, "surrounding SyntheticTableCanary9988 prose", 1, 0)], [table], o)
        payload = e.ExtractedDocument("pymupdf", "application/pdf", "Fixture", out.units).to_dict()
        self.assertNotIn("SyntheticTableCanary9988", json.dumps(payload))
        self.assertIn("<REDACTED>", json.dumps(payload))
        row = next(u for u in out.units if u.anchor == "page:1/table:1/row:2")
        self.assertEqual(row.metadata["cells"][1]["text"], "<REDACTED>")

    def test_bbox_validation_and_plain_fallback_never_invents_geometry(self):
        e = self.e
        for value in (None, [1, 2, 0, 4], [0, 0, float("nan"), 4], [False, 0, 2, 4], [0, 0, 1e20, 4]):
            self.assertIsNone(e._pdf_bbox(value))
        out = e._PdfOutput(self.o)
        diag = e._pdf_emit_page(out, 1, "Native fallback body", [], [], self.o, origin="pypdf")
        self.assertEqual(diag["structure"], "page_text_only")
        self.assertEqual(out.units[0].locator, {"page": 1})
        self.assertEqual(out.units[0].text, "Native fallback body")
        self.assertNotIn("bbox", out.units[0].metadata)

    def test_unit_bound_cannot_turn_container_only_into_success(self):
        e = self.e
        o = e.effective_extraction_options({"max_units": 1})
        out = e._PdfOutput(o)
        d = e._pdf_emit_page(out, 1, "Healthy native body", [(0, 0, 10, 10, "Healthy native body", 0, 0)], [], o)
        d.update(page=1, quality=e._text_quality("Healthy native body"), origin="native")
        result = e._pdf_finish(Path("fixture.pdf"), "pymupdf", out, [d], 1, [])
        self.assertEqual(len(out.units), 1)
        self.assertEqual(result.status, "empty")
        self.assertEqual(result.metadata["coverage"]["usable_pages"], 0)
        self.assertTrue(result.metadata["coverage"]["truncated"])

    def test_global_character_cell_and_block_bounds(self):
        e = self.e
        o = e.effective_extraction_options({"max_chars": 1000, "max_cells": 2, "pdf_max_blocks_per_page": 1})
        out = e._PdfOutput(o)
        d = e._pdf_emit_page(out, 1, "x" * 2500,
            [(0, 0, 10, 10, "x" * 2500, 0, 0), (0, 20, 10, 30, "omitted", 1, 0)], [sample_table()], o)
        self.assertLessEqual(sum(len(u.text) for u in out.units), 1000)
        self.assertLessEqual(out.cells, 2)
        self.assertLessEqual(out.metadata_characters, 1000)
        self.assertTrue(out.truncated)
        self.assertTrue(d["table_cells_limited"])
        self.assertNotIn("omitted", "\n".join(u.text for u in out.units))

    def test_text_health_and_ocr_selection_are_not_accuracy_claims(self):
        e = self.e
        self.assertEqual(e._text_quality("")["status"], "empty")
        self.assertEqual(e._text_quality("\ufffd" * 10 + "x")["status"], "low_quality")
        self.assertEqual(e._text_quality("hello\x01\x02")["status"], "low_quality")
        self.assertEqual(e._text_quality("Книги 123 ABC")["status"], "usable")
        accepted, reason, q = e._ocr_selection("Native trustworthy body", "bad", 8)
        self.assertFalse(accepted)
        self.assertIsNone(q["confidence"])
        self.assertEqual(reason, "empty_or_low_quality")
        self.assertEqual(e._ocr_selection("Native trustworthy body", "12345678", 8)[1], "native_text_is_better")
        self.assertTrue(e._ocr_selection("", "Recognized candidate text", 8)[0])

    def test_page_coverage_keeps_empty_middle_partial_and_omissions(self):
        e = self.e
        out = e._PdfOutput(self.o)
        pages = []
        for number, text, origin in ((1, "Native page content", "native"), (2, "", "native"), (3, "OCR page content", "ocr")):
            d = e._pdf_emit_page(out, number, text, [], [], self.o, origin=origin)
            d.update(page=number, origin=origin, quality=e._text_quality(text),
                ocr={"engine": "tesseract-via-pymupdf", "language": "eng+rus", "status": "unavailable" if number == 2 else "not_needed", "confidence": None})
            pages.append(d)
        result = e._pdf_finish(Path("fixture.pdf"), "pymupdf", out, pages, 4, []).to_dict()
        c = result["metadata"]["coverage"]
        self.assertEqual(result["status"], "partial")
        self.assertEqual([p["page"] for p in result["metadata"]["pages"]], [1, 2, 3])
        self.assertEqual((c["usable_pages"], c["missing_pages"], c["omitted_pages"]), (2, 1, 1))
        self.assertTrue(c["partial"])
        self.assertEqual(result["metadata"]["pages"][1]["ocr"]["status"], "unavailable")

    def test_tesseract_tsv_per_page_quality_engine_language_bbox(self):
        e = self.e
        raw = (TSV_HEADER + tsv_page(1) + tsv_page(2, conf=7)).encode("utf-8")
        result = e._image_ocr_tsv(Path("fixture.tiff"), raw, 2000, "rus+eng").to_dict()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["units"]), 1)
        self.assertEqual(result["units"][0]["locator"]["bbox"], [0.0, 0.0, 800.0, 600.0])
        self.assertEqual(result["units"][0]["locator"]["coordinate_system"], "image_top_left_pixels")
        pages = result["metadata"]["pages"]
        self.assertEqual([p["engine"] for p in pages], ["tesseract", "tesseract"])
        self.assertEqual([p["language"] for p in pages], ["rus+eng", "rus+eng"])
        self.assertEqual(pages[0]["confidence"], 96.0)
        self.assertEqual(pages[1]["status"], "empty_or_low_quality")
        self.assertFalse(result["metadata"]["coverage"]["total_pages_known"])

    def test_tsv_empty_low_quality_and_invalid_payloads_never_succeed(self):
        e = self.e
        for data in (TSV_HEADER, TSV_HEADER + tsv_page(1, ""), TSV_HEADER + tsv_page(1, "... !!!!")):
            result = e._image_ocr_tsv(Path("fixture.png"), data.encode(), 1000, "eng")
            self.assertEqual(result.status, "empty")
            self.assertFalse(result.units)
        with self.assertRaises(ValueError):
            e._image_ocr_tsv(Path("fixture.png"), b"not tsv", 1000, "eng")
        for conf in ("nan", "inf", "101", "-2"):
            with self.assertRaises(ValueError):
                e._image_ocr_tsv(Path("fixture.png"), (TSV_HEADER + tsv_page(1, conf=conf)).encode(), 1000, "eng")
        with self.assertRaises(UnicodeError):
            e._image_ocr_tsv(Path("fixture.png"), b"\xff", 1000, "eng")
        with self.assertRaises(ValueError):
            e._image_ocr_tsv(Path("fixture.png"), (TSV_HEADER + tsv_page(0)).encode(), 1000, "eng")

    def test_tsv_rows_pages_chars_and_unit_cap_are_explicit(self):
        e = self.e
        raw = (TSV_HEADER + tsv_page(1) + tsv_page(2)).encode()
        limited = e._image_ocr_tsv(Path("fixture.tiff"), raw, 2000, "eng", max_pages=1)
        self.assertEqual(limited.status, "partial")
        self.assertEqual(len(limited.units), 1)
        self.assertTrue(limited.metadata["coverage"]["truncated"])
        rows = e._image_ocr_tsv(Path("fixture.tiff"), raw, 2000, "eng", max_rows=2)
        self.assertTrue(rows.metadata["coverage"]["truncated"])
        big = (TSV_HEADER + tsv_page(1, "a" * 200_001)).encode()
        csv_limit = e.csv.field_size_limit()
        result = e._image_ocr_tsv(Path("fixture.png"), big, 250_000, "eng")
        self.assertEqual(e.csv.field_size_limit(), csv_limit)
        self.assertEqual(len(result.units[0].text), 200_000)
        self.assertEqual(result.status, "partial")
        self.assertTrue(result.metadata["pages"][0]["truncated"])

    def test_pdf_and_ocr_content_axes_in_fingerprint(self):
        e = self.e
        base = {"ocr": True}
        pdf = Path("fixture.pdf")
        fp = e.extraction_options_fingerprint(pdf, base)
        changes = {"pdf_parser": "pypdf", "pdf_mode": "pages", "pdf_reading_order": "source",
            "pdf_tables": False, "pdf_native_fallback": False, "pdf_table_strategy": "text",
            "pdf_max_blocks_per_page": 1, "pdf_max_tables_per_page": 1, "max_cells": 1,
            "ocr_language": "rus+eng", "ocr_min_native_chars": 20, "ocr_min_chars": 9,
            "ocr_dpi": 300, "ocr_max_pixels": 2_000_000, "ocr_max_pages": 1, "max_chars": 1000}
        for key, value in changes.items():
            self.assertNotEqual(e.extraction_options_fingerprint(pdf, {**base, key: value}), fp, key)
        self.assertEqual(e.extraction_options_fingerprint(pdf, {**base, "external_timeout": 1}), fp)
        self.assertEqual(e.extraction_options_fingerprint(pdf, e.effective_extraction_options(base)), fp)
        self.assertEqual(e.extraction_options_fingerprint(pdf, {"ocr": False}),
            e.extraction_options_fingerprint(pdf, {"ocr": False, "ocr_dpi": 300, "ocr_language": "rus"}))
        image = Path("fixture.png")
        for key, value in {"ocr_psm": "6", "ocr_language": "eng", "tesseract_bin": "other-tesseract",
                           "ocr_min_chars": 12, "ocr_max_tsv_rows": 2}.items():
            self.assertNotEqual(e.extraction_options_fingerprint(image, base), e.extraction_options_fingerprint(image, {**base, key: value}), key)
        self.assertEqual(e.extraction_options_fingerprint(Path("fixture.txt"), {}),
                         e.extraction_options_fingerprint(Path("fixture.txt"), {"pdf_mode": "pages", "ocr": True}))

    def test_effective_options_bounds_and_invalid_values(self):
        e = self.e
        o = e.effective_extraction_options({"ocr_dpi": 9999, "ocr_max_pixels": 1, "ocr_max_pages": -1,
            "pdf_max_blocks_per_page": 0, "external_timeout": 99999})
        self.assertEqual((o["ocr_dpi"], o["ocr_max_pixels"], o["ocr_max_pages"], o["external_timeout"]), (400, 1_000_000, 1, 900))
        self.assertEqual(o["pdf_max_blocks_per_page"], 1)
        self.assertEqual(e.effective_extraction_options(o), o)
        for options in ({"pdf_parser": "imaginary"}, {"pdf_mode": "dict"}, {"pdf_table_strategy": "guess"},
                        {"ocr_language": "../private"}, {"ocr_language": "eng\nrus"}, {"ocr_psm": "14"}):
            with self.assertRaises(ValueError):
                e.effective_extraction_options(options)

    def test_native_before_ocr_and_cleanup_source_contracts_STATIC(self):
        source = read_source(EXTRACTOR)
        tree = ast.parse(source)
        functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        pdf = functions["_extract_pdf_pymupdf"]
        calls = list(ast.walk(pdf))
        fallback = [n.lineno for n in calls if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_open_pypdf"]
        ocr = [n for n in calls if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get_textpage_ocr"]
        self.assertEqual(len(ocr), 1)
        self.assertLess(fallback[0], ocr[0].lineno)
        self.assertTrue(any(k.arg == "full" and isinstance(k.value, ast.Constant) and k.value.value is True for k in ocr[0].keywords))
        self.assertIn("stack.callback(doc.close)", ast.unparse(pdf))
        self.assertIn("stack.enter_context(path.open('rb'))", ast.unparse(functions["_open_pypdf"]))
        command = ast.unparse(functions["_run_ocr_command"])
        self.assertLess(command.index("deadline = time.monotonic()"), command.index("subprocess.Popen"))
        self.assertIn("_OCR_RETAINED.append", command)
        self.assertIn("process.kill()", command)
        self.assertIn("thread.join", command)
        dispatch = ast.unparse(functions["extract_pdf"])
        self.assertIn("result.status not in", dispatch)
        self.assertIn("'empty'", dispatch)
        self.assertNotIn("subprocess.run", command)

    def test_real_stdlib_text_and_csv_redaction_unchanged_original(self):
        e = self.e
        path = fixture_root() / "parser-source-safe.csv"
        raw = b"Name,Password\nBooks,SyntheticCsvCanary9988\n"
        path.write_bytes(raw)
        payload = e.extract_document(path, {})
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["parser"], "stdlib-csv")
        self.assertNotIn("SyntheticCsvCanary9988", json.dumps(payload))
        self.assertEqual(payload["units"][1]["metadata"]["cells"][1], "<REDACTED>")
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(payload["file_hash"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(payload["edges"][0]["predicate"], "next")

    def test_real_stdlib_ooxml_cached_formula_preserves_existing_contract(self):
        path = fixture_root() / "parser-source-cached.xlsx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("xl/worksheets/sheet1.xml", '<worksheet><sheetData><row r="1"><c r="A1"><v>4</v></c><c r="B1"><f>A1+2</f><v>6</v></c></row></sheetData></worksheet>')
        before = path.read_bytes()
        result = self.e.extract_document(path, {})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["units"][1]["metadata"]["cells"][1]["value"], "6")
        self.assertEqual(result["units"][1]["metadata"]["cells"][1]["formula"], "A1+2")
        self.assertTrue(any(edge["predicate"] == "formula_ref" for edge in result["edges"]))
        self.assertEqual(path.read_bytes(), before)

    @unittest.skipIf(os.name != "nt", "Windows SOURCE no-op OS-limits path only; POSIX needs its own child admission")
    def test_real_worker_protocol_with_actual_extractor_and_invalid_options(self):
        worker = load_source(WORKER, "document_worker_parser_source_test")
        root = fixture_root()
        path = root / "parser-source-worker.txt"
        path.write_text("Worker actual stdlib extraction", encoding="utf-8")
        original_in, original_out = sys.stdin, sys.stdout
        try:
            for options, expected in (({}, 0), ({"pdf_mode": "imaginary"}, 2)):
                sink = types.SimpleNamespace(buffer=io.BytesIO())
                sys.stdin = types.SimpleNamespace(buffer=io.BytesIO(json.dumps({"path": str(path), "options": options}).encode()))
                sys.stdout = sink
                exit_code = worker.main()
                response = json.loads(sink.buffer.getvalue())
                self.assertEqual(exit_code, expected)
                self.assertEqual(response["ok"], expected == 0)
                if expected == 0:
                    self.assertEqual(response["document"]["units"][0]["text"], "Worker actual stdlib extraction")
                else:
                    self.assertEqual(response, {"ok": False, "error": "ValueError"})
        finally:
            sys.stdin, sys.stdout = original_in, original_out


if __name__ == "__main__" and "devtools_case_started" in globals():
    class PacketResult(unittest.TestResult):
        def __init__(self):
            super().__init__()
            self.rows = []

        def startTest(self, test):
            super().startTest(test)
            devtools_case_started(test._testMethodName)

        def addSuccess(self, test):
            self.rows.append({"id": test._testMethodName, "outcome": "passed"})

        def failure_row(self, test, err, outcome):
            frames = []
            tb = err[2]
            while tb is not None:
                frames.append({"function": tb.tb_frame.f_code.co_name, "line": tb.tb_lineno})
                tb = tb.tb_next
            self.rows.append({"id": test._testMethodName, "outcome": outcome,
                              "error_type": err[0].__name__, "frames": frames[-6:]})

        def addFailure(self, test, err):
            self.failures.append((test, err[0].__name__))
            self.failure_row(test, err, "failed")

        def addError(self, test, err):
            self.errors.append((test, err[0].__name__))
            self.failure_row(test, err, "error")

        def addSkip(self, test, reason):
            self.skipped.append((test, reason))
            self.rows.append({"id": test._testMethodName, "outcome": "skipped"})

    result = PacketResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(ParserSourceTests).run(result)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": result.rows,
        "qualification": "whole-module SOURCE record/TSV/stdlib execution; one STATIC source-order/cleanup case; no PDF/OCR engine or SDK execution"}, separators=(",", ":")))
    raise SystemExit(0 if result.wasSuccessful() else 1)
elif __name__ == "__main__":
    unittest.main()
