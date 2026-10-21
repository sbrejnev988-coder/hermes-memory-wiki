"""SOURCE-композиция terminal PDF veto; не genuine PDF/native qualification.

Повторно использует прежний packet/loader/reporter, не новый test framework.
Исполняются настоящий extract_pdf, whole-function pypdf reader и точный суффикс
PyMuPDF reader после НЕисполненных optional imports. Document/page/table records,
pypdf-open и Tika transport авторские; SDK/authority/SQL stand-ins отсутствуют.
"""
from __future__ import annotations

import ast
import builtins
import dis
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

INPUTS = globals().get("DEVTOOLS_INPUTS", {})
REVIEW_PATH = Path(INPUTS.get("test_document_parser_review_boundaries.py",
                             Path(__file__).with_name("test_document_parser_review_boundaries.py")))


def read_source(path):
    return devtools_read_bound(str(path)) if "devtools_read_bound" in globals() else path.read_bytes()


_spec = importlib.util.spec_from_file_location("parser_terminal_review_source", str(REVIEW_PATH))
review = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = review
for _name in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound"):
    if _name in globals():
        review.__dict__[_name] = globals()[_name]
exec(compile(read_source(REVIEW_PATH), str(REVIEW_PATH), "exec", dont_inherit=True), review.__dict__)

CANARY = "OrdinaryFixtureValue9988"
CONTEXT_TEXT = "Name Password\nBooks OrdinaryFixtureValue9988\nOutsideFact 73"
HEALTHY_TEXT = "Healthy native surrounding document fact number 7319"
ALTERNATE_TEXT = "Healthy alternate document fact number 9127"
TIKA_TEXT = "Healthy authored Tika transport fact number 3719"
OBSERVATIONS = []


def withheld_page(reason, *, blocks=True):
    tables = [review.TableRecord(review.secret_table())]
    if reason == "table_cap":
        tables.insert(0, review.TableRecord(review.peer.sample_table()))
    return review.PageRecords(CONTEXT_TEXT, review.split_blocks() if blocks else [], tables,
                              tables_error=reason == "table_failure")


def fault_options(reason):
    return {"max_cells": 2} if reason == "cell_cap" else (
        {"pdf_max_tables_per_page": 1} if reason == "table_cap" else {})


class TerminalVetoSourceTests(unittest.TestCase):
    def setUp(self):
        self.e = review.peer.load_source(review.peer.EXTRACTOR, "document_extractors")

    def dispatch_records(self, pages, changes=None, *, unavailable=False,
                         alternate=ALTERNATE_TEXT, tika_text=TIKA_TEXT):
        """Own transport namespace, actual readers/dispatcher; no module patch."""
        e = self.e
        options = e.effective_extraction_options(changes)
        calls, primary, native_fallback_opens = [], [], []
        document = review.DocumentRecords(pages)

        def native_open_records(path, stack):
            # Optional per-page alternate is explicitly unavailable here; do
            # not import a genuine engine before testing the outer dispatcher.
            native_fallback_opens.append(str(path))
            return None

        caller = review.caller_body(e, document, native_open_records)

        def pymupdf(*args, **kwargs):
            calls.append("pymupdf")
            if unavailable:
                return None  # explicitly authored optional-reader absence seam
            value = caller(*args, **kwargs)
            primary.append(value)
            return value

        def open_pypdf(path, stack):
            calls.append("pypdf_open_records")
            if alternate is None:
                return None
            return types.SimpleNamespace(pages=[types.SimpleNamespace(extract_text=lambda: alternate)], metadata={})

        pypdf_body = review.clone_function(e._extract_pdf_pypdf, _open_pypdf=open_pypdf)

        def pypdf(*args, **kwargs):
            calls.append("pypdf")
            return pypdf_body(*args, **kwargs)

        def tika(path, **kwargs):
            calls.append("tika_authored_transport")
            self.assertEqual(kwargs, {"tika_url": options["tika_url"],
                "timeout": options["external_timeout"], "max_chars": options["max_chars"]})
            return e.ExtractedDocument("authored-tika-transport", "application/pdf", "Fixture", [
                e._unit("document_text", "document:1", tika_text)])

        dispatch = review.clone_function(e.extract_pdf, _extract_pdf_pymupdf=pymupdf,
                                        _extract_pdf_pypdf=pypdf, extract_tika=tika)
        result = dispatch(Path("fixture.pdf"), options)
        if "pymupdf" in calls and not unavailable:
            self.assertTrue(document.closed)
        OBSERVATIONS.append({"case": self._testMethodName, "calls": list(calls),
            "status": result.status, "units": len(result.units),
            "inner_alternate_unavailable_records": len(native_fallback_opens),
            "pdf_fallback_veto": result.metadata.get("pdf_fallback_veto"),
            "raw_canary_present": CANARY in json.dumps(e.asdict(result)),
            "serialized_canary_present": CANARY in json.dumps(result.to_dict()),
            "primary_status": primary[0].status if primary else None})
        return result, calls, primary

    def assert_terminal_veto(self, result, calls, primary, *, selected_pages=1):
        payload = result.to_dict()
        self.assertIs(result, primary[0])
        self.assertEqual(calls, ["pymupdf"])
        self.assertEqual(payload["status"], "empty")
        self.assertEqual(payload["units"], [])
        self.assertEqual(payload["metadata"]["pdf_fallback_veto"], "incomplete_table_context")
        self.assertEqual(payload["metadata"]["parser_attempts"], [{"parser": "pymupdf", "status": "empty"}])
        self.assertEqual(payload["metadata"]["coverage"]["usable_pages"], 0)
        self.assertEqual(payload["metadata"]["coverage"]["examined_pages"], selected_pages)
        self.assertTrue(payload["metadata"]["coverage"]["partial"])
        self.assertTrue(payload["metadata"]["coverage"]["truncated"])
        self.assertTrue(all(p["table_context"] == "withheld_structural_refusal"
                            for p in payload["metadata"]["pages"]))
        self.assertNotIn(CANARY, json.dumps(self.e.asdict(result)))
        self.assertNotIn(CANARY, json.dumps(payload))

    def test_terminal_auto_cell_and_table_caps_withhold_all_selected_pages(self):
        # Row-major alternate retains the contextual canary after generic cleanup:
        # this is an actual redactor precondition, not a presumed secret pattern.
        self.assertIn(CANARY, self.e.clean_text(CONTEXT_TEXT))
        for reason in ("cell_cap", "table_cap"):
            for blocks in (False, True):
                pages = [withheld_page(reason, blocks=blocks) for _ in range(2)]
                result, calls, primary = self.dispatch_records(pages, fault_options(reason), alternate=CONTEXT_TEXT)
                self.assert_terminal_veto(result, calls, primary, selected_pages=2)
                self.assertTrue(all(p["tables_status"] == "resource_limited"
                                    for p in result.metadata["pages"]))

    def test_terminal_veto_prevents_pypdf_and_explicit_tika_for_each_refusal(self):
        for reason in ("cell_cap", "table_cap", "table_failure"):
            for alternate in (CONTEXT_TEXT, "", None):
                result, calls, primary = self.dispatch_records([withheld_page(reason)],
                    {**fault_options(reason), "tika_url": "http://127.0.0.1:9998/tika"},
                    alternate=alternate, tika_text=CONTEXT_TEXT)
                self.assert_terminal_veto(result, calls, primary)
                if reason == "table_failure":
                    self.assertEqual(result.metadata["pages"][0]["tables_status"], "failed_ValueError")

    def test_terminal_ordinary_empty_and_unavailable_keep_healthy_pypdf_fallback(self):
        for unavailable in (False, True):
            result, calls, primary = self.dispatch_records([review.PageRecords("")], unavailable=unavailable)
            payload = result.to_dict()
            self.assertEqual(calls, ["pymupdf", "pypdf", "pypdf_open_records"])
            self.assertEqual(payload["parser"], "pypdf")
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["units"][0]["text"], ALTERNATE_TEXT)
            self.assertIsNone(payload["metadata"]["pdf_fallback_veto"])
            self.assertEqual(payload["metadata"]["parser_attempts"], [
                {"parser": "pymupdf", "status": "unavailable" if unavailable else "empty"},
                {"parser": "pypdf", "status": "ok"}])
            if primary:
                self.assertIsNone(primary[0].metadata["pdf_fallback_veto"])
                self.assertEqual(primary[0].metadata["pages"][0]["native_fallback"], "unavailable")

    def test_terminal_ordinary_empty_keeps_explicit_tika_fallback(self):
        for alternate in ("", None):
            result, calls, primary = self.dispatch_records([review.PageRecords("")],
                {"tika_url": "http://127.0.0.1:9998/tika"}, alternate=alternate)
            payload = result.to_dict()
            self.assertEqual(calls, ["pymupdf", "pypdf", "pypdf_open_records", "tika_authored_transport"])
            self.assertEqual(payload["parser"], "authored-tika-transport")
            self.assertEqual(payload["status"], "partial")
            self.assertEqual(payload["units"][0]["text"], TIKA_TEXT)
            self.assertFalse(payload["metadata"]["coverage_known"])
            self.assertEqual(payload["metadata"]["parser_attempts"], [
                {"parser": "pymupdf", "status": "empty"},
                {"parser": "pypdf", "status": "empty" if alternate == "" else "unavailable"}])
            self.assertIsNone(primary[0].metadata["pdf_fallback_veto"])

    def test_terminal_explicit_pypdf_pages_and_no_tables_remain_healthy(self):
        for changes in ({"pdf_parser": "pypdf"}, {"pdf_mode": "pages"},
                        {"pdf_tables": False}, {"pdf_parser": "pymupdf"}):
            page = review.PageRecords(HEALTHY_TEXT, [(0, 0, 140, 20, HEALTHY_TEXT, 0, 0)],
                                      tables_error=changes.get("pdf_mode") == "pages" or changes.get("pdf_tables") is False)
            result, calls, primary = self.dispatch_records([page], changes)
            payload = result.to_dict()
            self.assertEqual(payload["status"], "ok")
            self.assertIsNone(payload["metadata"]["pdf_fallback_veto"])
            if changes.get("pdf_parser") == "pypdf":
                self.assertEqual(calls, ["pypdf", "pypdf_open_records"])
                self.assertEqual(payload["units"][0]["text"], ALTERNATE_TEXT)
            else:
                self.assertEqual(calls, ["pymupdf"])
                self.assertIs(result, primary[0])
                self.assertIn(HEALTHY_TEXT, "\n".join(u["text"] for u in payload["units"]))
            if changes.get("pdf_mode") == "pages" or changes.get("pdf_tables") is False:
                self.assertFalse(any(call[0] == "tables" for call in page.calls))

    def test_terminal_mixed_healthy_withheld_preserves_safe_partial(self):
        for reason in ("cell_cap", "table_cap", "table_failure"):
            for healthy_first in (False, True):
                healthy = review.PageRecords(HEALTHY_TEXT, [(0, 0, 140, 20, HEALTHY_TEXT, 0, 0)])
                pages = [withheld_page(reason), healthy]
                if healthy_first:
                    pages.reverse()
                result, calls, primary = self.dispatch_records(pages,
                    {**fault_options(reason), "tika_url": "http://127.0.0.1:9998/tika"}, alternate=CONTEXT_TEXT)
                payload = result.to_dict()
                self.assertIs(result, primary[0])
                self.assertEqual(calls, ["pymupdf"])
                self.assertEqual(payload["status"], "partial")
                self.assertEqual(payload["metadata"]["pdf_fallback_veto"], "incomplete_table_context")
                self.assertIn(HEALTHY_TEXT, "\n".join(u["text"] for u in payload["units"]))
                coverage = payload["metadata"]["coverage"]
                self.assertEqual((coverage["usable_pages"], coverage["missing_pages"], coverage["total_pages"]), (1, 1, 2))
                self.assertNotIn(CANARY, json.dumps(self.e.asdict(result)))
                self.assertNotIn(CANARY, json.dumps(payload))

    def test_terminal_healthy_context_redaction_is_not_a_fallback_veto(self):
        result, calls, primary = self.dispatch_records([review.PageRecords(CONTEXT_TEXT,
            review.split_blocks(), [review.TableRecord(review.secret_table())])],
            {"max_cells": 4, "pdf_max_tables_per_page": 1, "tika_url": "http://127.0.0.1:9998/tika"})
        payload = result.to_dict()
        self.assertIs(result, primary[0])
        self.assertEqual(calls, ["pymupdf"])
        self.assertEqual(payload["status"], "ok")
        self.assertIsNone(payload["metadata"]["pdf_fallback_veto"])
        self.assertNotIn(CANARY, json.dumps(self.e.asdict(result)))
        self.assertNotIn(CANARY, json.dumps(payload))
        self.assertIn("<REDACTED>", json.dumps(payload["units"]))
        cell = next(u for u in payload["units"] if u["anchor"].endswith("/row:2"))["metadata"]["cells"][1]
        self.assertEqual(cell["text"], "<REDACTED>")

    def test_terminal_nonprivacy_truncation_does_not_block_empty_fallback(self):
        result, calls, primary = self.dispatch_records([review.PageRecords(HEALTHY_TEXT,
            [(0, 0, 140, 20, HEALTHY_TEXT, 0, 0)])], {"max_units": 1})
        self.assertEqual(primary[0].status, "empty")
        self.assertTrue(primary[0].metadata["coverage"]["truncated"])
        self.assertIsNone(primary[0].metadata["pdf_fallback_veto"])
        self.assertEqual(calls, ["pymupdf", "pypdf", "pypdf_open_records"])
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.units[0].text, ALTERNATE_TEXT)
        self.assertIsNone(result.metadata["pdf_fallback_veto"])

    def test_terminal_policy_version_invalidates_previous_extraction_identity(self):
        e = self.e
        self.assertEqual(e.EXTRACTOR_VERSION, "3.1.8")
        self.assertEqual(e.SECRET_POLICY_VERSION, "3.0.0")
        previous = review.clone_function(e.extraction_options_fingerprint, EXTRACTOR_VERSION="3.1.1")
        options = {"ocr": False}
        current = e.extraction_options_fingerprint(Path("fixture.pdf"), options)
        self.assertNotEqual(current, previous(Path("fixture.pdf"), options))
        self.assertEqual(current, e.extraction_options_fingerprint(Path("fixture.pdf"), e.effective_extraction_options(options)))
        self.assertEqual(e.ExtractedDocument("none", "application/pdf", "Fixture", []).to_dict()["extractor_version"], "3.1.8")


def packet_suite():
    return unittest.TestSuite([review.packet_suite(),
                              unittest.defaultTestLoader.loadTestsFromTestCase(TerminalVetoSourceTests)])


def metadata_preflight():
    """Only imports, collection and recursive global closure; no test bodies."""
    old_ids = review.metadata_preflight()
    cases = unittest.defaultTestLoader.loadTestsFromTestCase(TerminalVetoSourceTests)
    ids = old_ids + [case._testMethodName for case in cases]
    assert len(ids) == len(set(ids))

    def check(code, namespace):
        for instruction in dis.get_instructions(code):
            if instruction.opname == "LOAD_GLOBAL":
                name = instruction.argval
                assert name in namespace or hasattr(builtins, name), (code.co_qualname, name)
        for constant in code.co_consts:
            if isinstance(constant, types.CodeType):
                check(constant, namespace)

    for value in list(globals().values()):
        if isinstance(value, types.FunctionType) and value.__globals__ is globals():
            check(value.__code__, value.__globals__)
        elif isinstance(value, type) and value.__module__ == __name__:
            for method in value.__dict__.values():
                if isinstance(method, types.FunctionType):
                    check(method.__code__, method.__globals__)
    assert OBSERVATIONS == []
    return ids


if __name__ == "__main__" and "devtools_case_started" in globals():
    # Exact unchanged legacy bounded reporter; no traceback source lookup.
    peer_tree = ast.parse(read_source(review.PEER_PATH))
    reporter = next(n for n in ast.walk(peer_tree) if isinstance(n, ast.ClassDef) and n.name == "PacketResult")
    exec(compile(ast.Module(body=[reporter], type_ignores=[]), str(review.PEER_PATH), "exec", dont_inherit=True), globals())
    result = PacketResult()
    packet_suite().run(result)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": result.rows,
        "terminal_compositions": OBSERVATIONS,
        "qualification": "SOURCE: actual dispatcher/readers with authored records/open/Tika transport; old32 retained as fresh cases, including5 capture-transport and1 STATIC; genuine engines/SDK/SQL/native NOT_RUN"}, separators=(",", ":")))
    raise SystemExit(0 if result.wasSuccessful() else 1)
elif __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(packet_suite())
    raise SystemExit(0 if result.wasSuccessful() else 1)
