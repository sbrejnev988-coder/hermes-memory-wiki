"""PDF-COMP01: SOURCE composition, not genuine PDF/OCR/native qualification.

Полный прежний54 roster/setup/cleanup + различающие authored record controls.
Настоящие owner/ExitStack/emitter/selection/finish/dispatcher/redactor/serializer.
Без SDK/SQL/authority stand-ins; native optional imports и engines NOT_RUN.
Два b464 witnesses используют exact lossless Git blob в том же child; их PASS
означает ожидаемое старое нарушение, не healthy baseline.
"""
from __future__ import annotations

import ast
import base64
import builtins
import dis
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
import zlib

INPUTS = globals().get("DEVTOOLS_INPUTS", {})
CLEANUP_PATH = Path(INPUTS.get("test_document_parser_veto_cleanup.py",
                             Path(__file__).with_name("test_document_parser_veto_cleanup.py")))


def read_source(path):
    return devtools_read_bound(str(path)) if "devtools_read_bound" in globals() else path.read_bytes()


_spec = importlib.util.spec_from_file_location("parser_composition_cleanup_source", str(CLEANUP_PATH))
cleanup = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cleanup
for _name in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound"):
    if _name in globals():
        cleanup.__dict__[_name] = globals()[_name]
exec(compile(read_source(CLEANUP_PATH), str(CLEANUP_PATH), "exec", dont_inherit=True), cleanup.__dict__)
terminal, review = cleanup.terminal, cleanup.review
OBSERVATIONS = []
BASELINE_COMMIT = "b464b6284886eb8c841c2129c62a276071eb5238"
BASELINE_BLOB = "1817a98b9e1e0c5ae7535828c585b68046b33bd8"
BASELINE_SHA256 = "70a0ee38fb23bf8cb4e62dca7c48ed79e72e69279f116eb2a3fd47c492edc87e"
BASELINE_MODULES = {}


def baseline_raw():
    raw = zlib.decompress(base64.b85decode(B464_SOURCE))
    assert len(raw) == 95837 and hashlib.sha256(raw).hexdigest() == BASELINE_SHA256
    return raw


def baseline_module():
    # Reuse the exact shipped loader with an explicitly embedded source producer;
    # no writes/import-path injection, filesystem baseline or new loader framework.
    raw = baseline_raw()
    loader = review.clone_function(review.peer.load_source,
        read_source=lambda path: raw, MODULES=BASELINE_MODULES)
    return loader(review.peer.EXTRACTOR, "document_extractors_exact_b464")


class OcrPage(review.PageRecords):
    """Authored OCR API records; no engine/process/native ownership claim."""
    rect = [0, 0, 144, 144]

    def __init__(self, native, recognized, tables=()):
        super().__init__(native, [(0, 0, 140, 20, native, 0, 0)] if native else [], tables)
        self.recognized = recognized
        self.ocr_calls = []
        self.textpage = object()

    def get_textpage_ocr(self, *, language, dpi, full):
        self.ocr_calls.append((language, dpi, full))
        return self.textpage

    def get_text(self, mode, *, sort, textpage=None):
        if textpage is not None:
            assert textpage is self.textpage
            self.calls.append(("ocr_" + mode, sort))
            return self.recognized if mode == "text" else [(0, 100, 140, 120, self.recognized, 1, 0)]
        return super().get_text(mode, sort=sort)


def reader_records(e, pages, changes=None, *, alternates=None, faults=(None, None, None),
                   body_error=None, baseline=False):
    """Existing caller/clone seam; supported actual LIFO registration shapes."""
    reader_error, stream_error, doc_error = faults
    values = alternates if alternates is not None else [terminal.ALTERNATE_TEXT] * len(pages)
    assert len(values) == len(pages)
    state = types.SimpleNamespace(options=e.effective_extraction_options(changes), calls=[], events=[],
        reads=[], opens=0, cleanups=[], closed={"reader": False, "stream": False, "doc": False},
        emissions=[], finished=[], errors=[], stack=None, output=None, stream_received=[])

    class Document(review.DocumentRecords):
        def close(self):
            state.cleanups.append("doc")
            state.events.append("close_doc")
            if doc_error is not None:
                raise doc_error
            super().close()
            state.closed["doc"] = True

    class Stream:
        def __enter__(self):
            state.events.append("enter_stream")
            return self

        def __exit__(self, exc_type, error, traceback):
            state.stream_received.append(error)
            state.cleanups.append("stream")
            state.events.append("close_stream")
            if stream_error is not None:
                raise stream_error
            state.closed["stream"] = True
            return False  # same nonsuppressing contract as an owned binary file

    class AlternatePage:
        def __init__(self, number, value):
            self.number, self.value = number, value

        def extract_text(self):
            state.reads.append(self.number)
            state.events.append("inner_read_" + str(self.number))
            return self.value

    class Reader:
        def __init__(self):
            self.pages = [AlternatePage(i + 1, value) for i, value in enumerate(values)]

        def close(self):
            state.cleanups.append("reader")
            state.events.append("close_reader")
            if reader_error is not None:
                raise reader_error
            state.closed["reader"] = True

    state.document, state.stream, state.reader = Document(list(pages)), Stream(), Reader()

    def open_inner(path, stack):
        state.opens += 1
        state.stack = stack
        state.events.append("inner_open")
        # Actual supported registrations from _open_pypdf, without optional import.
        stack.enter_context(state.stream)
        stack.callback(state.reader.close)
        return state.reader

    def emit(output, number, *args, **kwargs):
        state.output = output
        diagnostic = e._pdf_emit_page(output, number, *args, **kwargs)
        state.emissions.append(diagnostic)
        state.events.append(("veto_" if diagnostic.get("table_context") == "withheld_structural_refusal" else "emit_") + str(number))
        return diagnostic

    def finish(*args, **kwargs):
        value = e._pdf_finish(*args, **kwargs)
        state.finished.append(value)
        state.events.append("finish")
        if body_error is not None:
            raise body_error
        return value

    loader = review.caller_body
    if baseline:
        raw = baseline_raw()
        loader = review.clone_function(loader, read_source=lambda path: raw)
    body = review.clone_function(loader(e, state.document, open_inner), _pdf_emit_page=emit, _pdf_finish=finish)

    def pymupdf(*args, **kwargs):
        state.calls.append("pymupdf")
        return body(*args, **kwargs)

    def outer_pypdf(*args, **kwargs):
        state.calls.append("outer_pypdf")
        raise AssertionError("unexpected outer pypdf")

    def tika(*args, **kwargs):
        state.calls.append("tika")
        raise AssertionError("unexpected Tika transport")

    dispatch = review.clone_function(e.extract_pdf, _extract_pdf_pymupdf=pymupdf,
                                    _extract_pdf_pypdf=outer_pypdf, extract_tika=tika)

    def run():
        try:
            return dispatch(Path("fixture.pdf"), state.options)
        except BaseException as error:
            state.errors.append(error)
            raise

    state.run = run
    return state


def context_nodes(error):
    """Bounded identity observer; never stringify foreign exceptions."""
    result, seen = [], set()
    while error is not None:
        assert id(error) not in seen and len(result) < 24, "exception context cycle/overflow"
        seen.add(id(error))
        result.append(error)
        error = error.__context__
    return result


class VetoCompositionSourceTests(unittest.TestCase):
    def setUp(self):
        self.e = review.peer.load_source(review.peer.EXTRACTOR, "document_extractors")

    def safe_result(self, seam, result, *, veto=True):
        payload = result.to_dict()
        raw = json.dumps(self.e.asdict(result))
        self.assertNotIn(terminal.CANARY, raw)
        self.assertNotIn(terminal.CANARY, json.dumps(payload))
        self.assertEqual(seam.calls, ["pymupdf"])
        self.assertTrue(seam.document.closed)
        self.assertEqual(payload["metadata"]["pdf_fallback_veto"], "incomplete_table_context" if veto else None)
        OBSERVATIONS.append({"case": self._testMethodName, "role": "candidate_SOURCE",
            "events": list(seam.events), "inner_reads": list(seam.reads), "status": result.status,
            "raw_and_serialized_canary_absent": True})
        return payload

    def test_comp_inner_new_reader_withheld_after_veto(self):
        self.assertIn(terminal.CANARY, self.e.clean_text(terminal.CONTEXT_TEXT))
        for reason in ("cell_cap", "table_cap", "table_failure"):
            for text in ("", "Books"):
                seam = reader_records(self.e, [terminal.withheld_page(reason), review.PageRecords(text)],
                    {**terminal.fault_options(reason), "tika_url": "http://127.0.0.1:9998/tika"},
                    alternates=["", text + "\n" + terminal.CONTEXT_TEXT])
                payload = self.safe_result(seam, seam.run())
                self.assertEqual((seam.opens, seam.reads, seam.cleanups), (0, [], ["doc"]))
                self.assertLess(seam.events.index("veto_1"), seam.events.index("finish"))
                page = payload["metadata"]["pages"][1]
                self.assertEqual((page["origin"], page["native_fallback"]), ("native", "withheld_incomplete_table_context"))
                self.assertTrue(page["partial"])
                coverage = payload["metadata"]["coverage"]
                self.assertEqual((coverage["total_pages"], coverage["examined_pages"], coverage["usable_pages"]), (2, 2, int(bool(text))))
                self.assertEqual(coverage["missing_pages"], 2 - int(bool(text)))

    def test_comp_inner_preopened_reader_is_not_reused_after_veto(self):
        for reason in ("cell_cap", "table_cap", "table_failure"):
            seam = reader_records(self.e, [review.PageRecords(""), terminal.withheld_page(reason), review.PageRecords("Books")],
                {**terminal.fault_options(reason), "tika_url": "http://127.0.0.1:9998/tika"},
                alternates=[terminal.ALTERNATE_TEXT, "", "Books\n" + terminal.CONTEXT_TEXT])
            payload = self.safe_result(seam, seam.run())
            self.assertEqual((seam.opens, seam.reads), (1, [1]))
            self.assertLess(seam.events.index("inner_read_1"), seam.events.index("veto_2"))
            self.assertEqual(seam.cleanups, ["reader", "stream", "doc"])
            self.assertTrue(all(seam.closed.values()))
            self.assertEqual(payload["metadata"]["pages"][2]["native_fallback"], "withheld_incomplete_table_context")
            self.assertIn(terminal.ALTERNATE_TEXT, "\n".join(u["text"] for u in payload["units"]))
            self.assertEqual(payload["status"], "partial")

    def test_comp_ocr_after_veto_is_not_attempted_or_selected(self):
        for enabled in (False, True):
            page = OcrPage("", terminal.CONTEXT_TEXT)
            seam = reader_records(self.e, [terminal.withheld_page("table_failure"), page],
                {"ocr": True, "pdf_native_fallback": enabled, "tika_url": "http://127.0.0.1:9998/tika"})
            payload = self.safe_result(seam, seam.run())
            self.assertEqual((seam.opens, seam.reads, page.ocr_calls), (0, [], []))
            diag = payload["metadata"]["pages"][1]
            self.assertEqual(diag["origin"], "native")
            self.assertEqual((diag["ocr"]["attempted"], diag["ocr"]["status"]), (False, "withheld_incomplete_table_context"))
            self.assertEqual((payload["metadata"]["coverage"]["usable_pages"], payload["metadata"]["coverage"]["missing_pages"]), (0, 2))
            self.assertTrue(diag["partial"])

    def test_comp_safe_native_table_after_veto_is_preserved(self):
        first = terminal.withheld_page("table_failure")
        first.text += "\n" + terminal.HEALTHY_TEXT * 5  # no pre-veto OCR needed on this page
        page = review.PageRecords(terminal.CONTEXT_TEXT, review.split_blocks(), [review.TableRecord(review.secret_table())])
        page.rect = [0, 0, 144, 144]
        seam = reader_records(self.e, [first, page],
            {"ocr": True, "ocr_min_native_chars": 200, "tika_url": "http://127.0.0.1:9998/tika"})
        payload = self.safe_result(seam, seam.run())
        diag = payload["metadata"]["pages"][1]
        self.assertEqual((diag["origin"], diag["tables_status"], diag["structure"]), ("native", "available_native_only", "blocks_and_native_tables"))
        self.assertEqual(diag["ocr"]["status"], "withheld_incomplete_table_context")
        row = next(u for u in payload["units"] if u["anchor"] == "page:2/table:1/row:2")
        self.assertEqual(row["metadata"]["cells"][1]["text"], "<REDACTED>")
        self.assertIn("Books", row["text"])
        self.assertEqual((payload["metadata"]["coverage"]["usable_pages"], payload["metadata"]["coverage"]["missing_pages"]), (1, 1))
        self.assertEqual(seam.opens, 0)

    def test_comp_pre_veto_inner_ocr_and_native_table_mixed_inverses(self):
        seam = reader_records(self.e, [review.PageRecords("Books")], alternates=["Books " + terminal.ALTERNATE_TEXT])
        payload = self.safe_result(seam, seam.run(), veto=False)
        self.assertEqual((seam.opens, seam.reads, payload["metadata"]["pages"][0]["origin"]), (1, [1], "pypdf"))
        self.assertEqual(payload["status"], "ok")
        for native in ("", "Native 73"):
            page = OcrPage(native, terminal.CONTEXT_TEXT if native else terminal.ALTERNATE_TEXT,
                           [review.TableRecord(review.secret_table())] if native else [])
            seam = reader_records(self.e, [page], {"ocr": True, "pdf_native_fallback": False})
            payload = self.safe_result(seam, seam.run(), veto=False)
            self.assertEqual(page.ocr_calls, [(seam.options["ocr_language"], seam.options["ocr_dpi"], True)])
            diag = payload["metadata"]["pages"][0]
            self.assertEqual((diag["ocr"]["attempted"], diag["ocr"]["status"], diag["origin"]), (True, "accepted", "mixed" if native else "ocr"))
            self.assertEqual(payload["status"], "ok")
            if native:
                self.assertIn("Native 73", "\n".join(u["text"] for u in payload["units"]))
                self.assertIn("<REDACTED>", json.dumps(payload))
                self.assertTrue(any(u["locator"].get("text_origin") == "ocr" for u in payload["units"]))

    def test_comp_emitter_rechecks_alternate_origin_before_publication(self):
        options = self.e.effective_extraction_options({})
        for origin in ("pypdf", "ocr", "mixed", "native"):
            output = self.e._PdfOutput(options)
            first = self.e._pdf_emit_page(output, 1, terminal.CONTEXT_TEXT, [], [], options, tables_status="failed_fixture")
            self.assertEqual(first["table_context"], "withheld_structural_refusal")
            self.assertFalse(output.context_alternates_allowed)
            diag = self.e._pdf_emit_page(output, 2, terminal.CONTEXT_TEXT, review.split_blocks(),
                                        [review.secret_table()], options, origin=origin)
            self.assertNotIn(terminal.CANARY, json.dumps(self.e.asdict(self.e.ExtractedDocument("records", "application/pdf", "Fixture", output.units))))
            if origin == "native":
                self.assertGreater(diag["text_units"], 0)
                self.assertIn("<REDACTED>", json.dumps([u.to_dict() for u in output.units]))
            else:
                self.assertEqual((diag["units"], diag["table_context"], output.units), (0, "withheld_structural_refusal", []))
        OBSERVATIONS.append({"case": self._testMethodName, "role": "candidate_SOURCE", "alternate_origins_refused": ["pypdf", "ocr", "mixed"], "native_table_redaction_preserved": True})

    def check_fatal(self, faults, primary=None, *, veto=True):
        pages = [review.PageRecords(""), terminal.withheld_page("table_failure") if veto else cleanup.healthy_page()]
        seam = reader_records(self.e, pages, {"tika_url": "http://127.0.0.1:9998/tika"},
                              faults=faults, body_error=primary)
        selected = primary if primary is not None and not isinstance(primary, Exception) else next(error for error in faults if error is not None and not isinstance(error, Exception))
        with self.assertRaises(cleanup.Cancellation) as caught:
            seam.run()
        error = caught.exception
        self.assertTrue(error is selected and seam.errors[0] is selected)
        self.assertFalse(isinstance(error, Exception))
        self.assertEqual((seam.opens, seam.reads, seam.cleanups), (1, [1], ["reader", "stream", "doc"]))
        self.assertEqual(seam.calls, ["pymupdf"])
        self.assertIs(type(seam.stack), self.e._PdfReaderOwner)
        self.assertIsInstance(seam.stack, self.e.ExitStack)
        expected_errors = [cause for cause in faults if cause is not None]
        self.assertEqual([id(cause) for cause in seam.stack.cleanup_errors], [id(cause) for cause in expected_errors])
        self.assertEqual(seam.stack.diagnostics, {"cleanup": "unknown", "ownership": "unknown"})
        self.assertEqual(len(seam.stack._exit_callbacks), 0)
        chain = context_nodes(error)
        for cause in [*expected_errors, *([primary] if primary is not None else [])]:
            self.assertTrue(any(node is cause for node in chain))
        for cause in expected_errors:
            if hasattr(cause, "original_cause"):
                self.assertTrue(cause.__cause__ is cause.original_cause)
        if primary is not None and hasattr(primary, "original_cause"):
            self.assertTrue(primary.__cause__ is primary.original_cause)
        self.assertEqual(seam.closed, {name: fault is None for name, fault in zip(("reader", "stream", "doc"), faults)})
        self.assertNotIn(terminal.CANARY, json.dumps([value.to_dict() for value in seam.finished]))
        OBSERVATIONS.append({"case": self._testMethodName, "role": "candidate_SOURCE", "events": list(seam.events),
            "exact_fatal_identity": True, "body_fatal_priority": primary is selected,
            "context_nodes": len(chain), "all_callbacks_drained": True, "cleanup_ownership": "unknown"})
        return seam

    def test_comp_fatal_then_ordinary_all_body_priorities(self):
        for kind in ("absent", "ordinary", "fatal"):
            primary = None if kind == "absent" else (cleanup.UnprintableError(terminal.CANARY) if kind == "ordinary" else cleanup.Cancellation(terminal.CANARY))
            fatal = cleanup.Cancellation(terminal.CANARY)
            for cause in (fatal, primary):
                if cause is not None:
                    cause.__cause__ = cause.original_cause = ValueError("authored prior cause")
            self.check_fatal((fatal, cleanup.UnprintableError(terminal.CANARY), cleanup.UnprintableError(terminal.CANARY)), primary)

    def test_comp_stream_fatal_is_observed_through_enter_context(self):
        for primary in (None, cleanup.UnprintableError(terminal.CANARY), cleanup.Cancellation(terminal.CANARY)):
            self.check_fatal((cleanup.UnprintableError(terminal.CANARY), cleanup.Cancellation(terminal.CANARY), cleanup.UnprintableError(terminal.CANARY)), primary)

    def test_comp_multiple_fatals_keep_body_then_first_cleanup_identity(self):
        for last_fatal in (False, True):
            faults = (cleanup.Cancellation(terminal.CANARY),
                      cleanup.UnprintableError(terminal.CANARY) if last_fatal else cleanup.Cancellation(terminal.CANARY),
                      cleanup.Cancellation(terminal.CANARY) if last_fatal else cleanup.UnprintableError(terminal.CANARY))
            self.check_fatal(faults)
        self.check_fatal((cleanup.Cancellation(terminal.CANARY), cleanup.UnprintableError(terminal.CANARY), cleanup.UnprintableError(terminal.CANARY)), veto=False)

    def test_comp_healthy_cleanup_and_ordinary_chain_inverse(self):
        seam = reader_records(self.e, [review.PageRecords(""), terminal.withheld_page("table_failure")])
        self.safe_result(seam, seam.run())
        self.assertEqual(seam.cleanups, ["reader", "stream", "doc"])
        self.assertTrue(all(seam.closed.values()))
        self.assertEqual(seam.stack.cleanup_errors, [])
        self.assertEqual(seam.stack.diagnostics, {"cleanup": "complete", "ownership": "complete"})
        primary, first, second, last = (cleanup.UnprintableError(terminal.CANARY) for _ in range(4))
        seam = reader_records(self.e, [review.PageRecords(""), terminal.withheld_page("table_failure")],
                              faults=(first, second, last), body_error=primary)
        with self.assertRaises(self.e._PdfPrivacyVetoError) as caught:
            seam.run()
        error = caught.exception
        self.assertTrue(error.primary_error is primary and error.cleanup_error is last and error.__cause__ is last)
        self.assertTrue(last.__context__ is second and second.__context__ is first and first.__context__ is primary)
        self.assertEqual(seam.cleanups, ["reader", "stream", "doc"])
        self.assertEqual(error.diagnostics["ownership"], "unknown")
        self.assertEqual(seam.calls, ["pymupdf"])
        self.assertEqual(len(context_nodes(error)), 5)
        self.assertNotIn(terminal.CANARY, json.dumps({"args": error.args, "diagnostics": error.diagnostics}))
        OBSERVATIONS.append({"case": self._testMethodName, "role": "candidate_SOURCE", "ordinary_primary_secondary_chain": True, "all_callbacks_drained": True, "cleanup_ownership": "unknown"})

    def test_comp_identity_invalidates_previous_3_1_3(self):
        path = Path("fixture.pdf")
        previous = review.clone_function(self.e.extraction_options_fingerprint, EXTRACTOR_VERSION="3.1.3")
        self.assertEqual(self.e.EXTRACTOR_VERSION, "3.1.8")
        self.assertEqual(self.e.SECRET_POLICY_VERSION, "3.0.0")
        for options in ({}, {"ocr": True}, {"pdf_parser": "pypdf"}):
            current = self.e.extraction_options_fingerprint(path, options)
            self.assertNotEqual(current, previous(path, options))
            self.assertEqual(current, self.e.extraction_options_fingerprint(path, self.e.effective_extraction_options(options)))
        self.assertEqual(self.e.ExtractedDocument("none", "application/pdf", "Fixture", []).to_dict()["extractor_version"], "3.1.8")

    def test_comp_b464_expected_inner_alternate_violation(self):
        e = baseline_module()
        for preopened in (False, True):
            pages = ([review.PageRecords("")] if preopened else []) + [terminal.withheld_page("table_failure"), review.PageRecords("Books")]
            alternates = ([terminal.ALTERNATE_TEXT] if preopened else []) + ["", "Books\n" + terminal.CONTEXT_TEXT]
            seam = reader_records(e, pages, {"tika_url": "http://127.0.0.1:9998/tika"}, alternates=alternates, baseline=True)
            result = seam.run()
            self.assertEqual(seam.calls, ["pymupdf"])
            self.assertEqual(result.metadata["pdf_fallback_veto"], "incomplete_table_context")
            self.assertEqual(result.metadata["pages"][-1]["origin"], "pypdf")
            self.assertIn(terminal.CANARY, json.dumps(e.asdict(result)))
            self.assertIn(terminal.CANARY, json.dumps(result.to_dict()))
            self.assertIn(len(pages), seam.reads)
            self.assertLess(seam.events.index("veto_" + str(len(pages) - 1)), seam.events.index("inner_read_" + str(len(pages))))
            OBSERVATIONS.append({"case": self._testMethodName, "role": "exact_b464_expected_defect", "preopened": preopened,
                "events": list(seam.events), "veto_present_but_raw_and_serialized_canary_present": True})

    def test_comp_b464_expected_intermediate_fatal_violation(self):
        e = baseline_module()
        for primary in (None, cleanup.UnprintableError(terminal.CANARY)):
            fatal, stream, doc = cleanup.Cancellation(terminal.CANARY), cleanup.UnprintableError(terminal.CANARY), cleanup.UnprintableError(terminal.CANARY)
            seam = reader_records(e, [review.PageRecords(""), terminal.withheld_page("table_failure")],
                {"tika_url": "http://127.0.0.1:9998/tika"}, faults=(fatal, stream, doc), body_error=primary, baseline=True)
            with self.assertRaises(e._PdfPrivacyVetoError) as caught:
                seam.run()
            error = caught.exception
            self.assertTrue(error.cleanup_error is doc and error.primary_error is (primary if primary is not None else doc))
            self.assertTrue(error is not fatal and isinstance(error, Exception))
            self.assertTrue(type(error) is e._PdfPrivacyVetoError and error.__cause__ is doc)
            self.assertEqual((seam.calls, seam.cleanups), (["pymupdf"], ["reader", "stream", "doc"]))
            self.assertEqual(error.diagnostics["ownership"], "unknown")
            OBSERVATIONS.append({"case": self._testMethodName, "role": "exact_b464_expected_defect",
                "events": list(seam.events), "intermediate_fatal_replaced_by_ordinary_carrier": True, "all_callbacks_drained": True})


def packet_suite():
    return unittest.TestSuite([cleanup.packet_suite(),
                              unittest.defaultTestLoader.loadTestsFromTestCase(VetoCompositionSourceTests)])


def metadata_preflight():
    """Full old setup/loader + new globals/fixtures/constructors; no case calls."""
    old_ids = cleanup.metadata_preflight()
    cases = unittest.defaultTestLoader.loadTestsFromTestCase(VetoCompositionSourceTests)
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

    for module in (sys.modules[__name__], baseline_module()):
        for value in list(module.__dict__.values()):
            if isinstance(value, types.FunctionType) and value.__globals__ is module.__dict__:
                check(value.__code__, value.__globals__)
            elif isinstance(value, type) and value.__module__ == module.__name__:
                for method in value.__dict__.values():
                    if isinstance(method, types.FunctionType):
                        check(method.__code__, method.__globals__)
    # Compile the exact baseline suffix with the same supported loader, no call.
    raw = baseline_raw()
    loader = review.clone_function(review.caller_body, read_source=lambda path: raw)
    baseline_body = loader(baseline_module(), review.DocumentRecords([]), lambda path, stack: None)
    check(baseline_body.__code__, baseline_body.__globals__)
    assert OBSERVATIONS == cleanup.OBSERVATIONS == terminal.OBSERVATIONS == []
    return ids


# Lossless exact Git blob, not reconstructed old implementation.
B464_SOURCE = (
    b"c-rl~YjYb}mKgXQzal$pA_}PjKvMPSYDkcpB~jIMt3+C4RaXy$L4iP$L=i-ykbp!M3CGMh!uw$zwj;dX_b04l){dQ>S&#pM>M!`0"
    b"?0Ma1-b{c}S9g!?nrRW4dEfWkbI<$4aeOp5O&d|Zm@kKm<veW;-VEkxG|Gm{%XGSk(yPUMFkFnYX>^*+qu-?S%QTO^N-wkdb@aRO"
    b"#kf_g9iOMsWj0z)pk6u|pQQ7_BAr}E=Yu>NM9VxqT~45f5qxT9Q}}Q)$f4XcZAAw&Y<e(>;M;sKAE$Y3d^wwEuhZysjEyaz^l}m5"
    b"n5OCLbRNyqAC}{JI-=n`J$Ul%*0;}(zTG-JJpOj;;OVoiZ@+rJwSZCM_shW|Z`GcsXM^E&bZ~k)9;VS?I)X`Mi}6sEz!Ac0csrYn"
    b"hvNkdaF|U`$7f6IW|9qIc)PQ~5N3Hiz8KW<bdCd|$(>}&=?Diim`qLv!wXoAJ@|MX%?9(FMhlBNg_5JuJk9gL39Qj~-z}%(MgHA)"
    b"t!OvGpV1hbnhnliBcR^kY(AKsH==p=rcoQFlL>6k1Qw$aO|u2=RZ9EOh|bf&XgocOU?H-_IrOG>5eA%2Qry2*w0C)uj<8sci&z`Z"
    b"Q`j7s7W_M>HO$k?!4#Kcc)pxoK&c$wz&K%2^XxK$hGBVV#0}X3tc5?WYdN$FGr~dQC}>Y>aU9pEYQKNFM40OLBiPhz4%;||DGYG*"
    b"d95bzhWTst6Gk$gs0V<abASr{xVY4x#+m*#la<vkU|NeTo9Gwc=h;;Kz8qhsi|bjcKf?B(tKXS^3(F+G^5qEt<Irk<aX#l&*Ds(="
    b"o-P0l0v?Q6O?U5Vyf|6_Sg69w`2;?<()m1_d+!KfymtueX}(Zze;m(F#}nyoG=PRDxLLXCPQPlv;YlZ>2JGc%JX~-ET3l6hmI0_="
    b"^9NknmcXlg{>|}M&kyMh7n#92S@Sx?Wn<{Lo*@Lv``zhvBYFxwHlpX_9R5|uyAd7XRHj1!-{a*>&EX0<P8ahu)eFW@dyKE(eC-{>"
    b"ar*Z7<?fT?gO~kp_Ff+CAH0Y<QT%ahr}c4MJKB5la__i*c<_Ax$?x6o+pX;wFcZ}7!~gbP;Flx#bW@AqzqqxyTEq?bdpY7igZafM"
    b"do!hndCuP^*%|#EPsj9kc*@U+9pZ*+D7&1{+v|b)A%79_^bdYD9qE@>SW4Q!9iW%+gFoswa60JkLjLAI@ca1!hp?(0900=erWm&X"
    b"eP2;A_;D#e7X0RFlItJR*+f3gX66Tfnqe*I<mt0Q7ukpxDI4YTcP4*%k+Ow+U&!~x3|cx2v@{!?!k4|TcK3@DNnsh_+ZP81zb$^7"
    b"El=R%{#UzS?iCxI@-V)islO@zSd35AU;c4&$pe3rp5O?d?|r!oz;y8J+5VHgFzmphsufhrMSoxC3`{sKYH^n9ExydTd&KfwYq|u?"
    b"Jm=pR={4=<mj?%5KHmd?-hXkt_p&glGu881ex9Za`H6P}H*+?c58l8Wj=nxTJa~D$_tb5nPGj-U#BEf7A$aBP({1E!+$}X#*t6TH"
    b"uvNEFVS~7G=|bN|rOQxDYPG(c`sce}>^<+l+=GeDQ#g~CGr)~J#d%zRJibc)>Q#QP{<s~>yBT1{H`#o2OF#I}FdL<}GkAFW-`@VG"
    b"pZ@yoKfV1&sPWUkz5VIm-@g6(+qeJa?f;iNzJ2=-@ZmpqqkgmZ`0amw`%gdp%};;()4#?lx2o~MY|P(bD{luwyfVx)+}J<}nCIbS"
    b"3|Nkz`I~NMkzJ(I+n@dxI{XLd{lDJ+^f&P5A7E(z<)^>B9V{2;*?jyXU7@#c|I^#Q!;<jv@8AAEF#dl7V}JYiH1xNBpXfGc^YLrA"
    b"?oI!1{~J~LJE-!vZ~rS!_<w)<|K38E|M%N}N@SY<@b({n`gcG5Z?}1Vt}Chr6Ij@8yYs5~-~akQ{`bHBKYEYh`7dJF9JM#QM@Rc#"
    b"zNp-s`s2fglfg+kdGzY!e{IswvPmZl|FBcHz1yzZtVfS;U*$JDjZap%jY+IGrEPv5KKx+`wC1DktN6oSqMt{Px_^alZa!(O@NI|Q"
    b">LzZXjgu6p%=xSQqvSDGJAo&xl;1WU=$d+j1Tu#&55C!d3ddaC=DWvm=m}wUsbD?MX6bZ*cd!LZILwE?=<YWEa?t#7yZNhL(#?Ap"
    b"O&9`DY~MGN$L13(%+1bcja8f^4QcUgyf`N;UD+Zuc6Q#KWy^ft>sudg?r%3%x7<b_Xd~-epFbv6UxPP!pMkAUcs|^x>TvhB`@6Th"
    b"NBg^pdJAJ;)gPNe_B65#=<hzjbyd@9I=lNn4!ZD*U*W2JyzQ(?J^@;FT`O1FRrh2to9Dfzd0kxL@82w{TY~<R^!i`8+w^&3^{TbW"
    b"E9$9-(6j%|?(ts#w|l=YLpM$Q?~A=J_g_S?zAuk<quaeF(e1$@Tq;MuiEf|5o8+-H6hT8&p>^+ZY&Wp?;^|$g%f%0)0YrH4a_`CR"
    b"(H`7v@ci`Pc=!4927><AFQ4}T=AZ7pINska-erU-;TYG?7mHc`xV^QN)bT8B{kq-zC~3=Y`1$J?8hdu|@~f|(??Nljf-N~~PoVZ8"
    b"wD2KR|M0eMeTv{s^7t2zU;V{ndJQ|<_!w{nJiZ!z1khKj)kf)Q)F0=4#*2Nz<Mr2r$ueyt6OcsBN5C3qlQt~^vEv=&PPq)SigBE@"
    b";Kg`WPh_ExQKm|DDvx~nB%RVj5<TohpKsGU|N3u%aA5*`-0+->s^J0e4sr`MLi}V6umP;<<#^GK##0>G{q61k_VzXno7j^s42^l1"
    b"F0wQH2=#is9#08)+?Uir#2w_(NeXN+$`P)kqks8)jEwrT<0G7EsyOgy2J{}ZiF^<U3WyjxN14e2IC>}uyLAE_bRN-qA_oqa-}r2b"
    b"ED`W@Z{S_?VhUVJgc1^<`sNYcL{WY|0H&594qz&R5sjeEcreLn%?|gzisXK20-lIYK&Ww%x1wl&p`|J!r-*=plsUoTP>ZMIDaj8W"
    b"L?pZ!LMvw|{lS)pApc<L3`kG1T*NY?@!)Kl<sei5@rx{1B_zz#8K9oD9>2QU-bPY3PVDmd$0{>_MJyEjYuB8scg~>O!Cl0=rN=vf"
    b"u!3@xx|&xThex3BBAceX-FAzu!3?gWQT--XHR85jlvQF{m7(>`Ce{f~+jug+!e2O|9(4sjOi#4^FhnZdI-6(9Sv{tgGCBN@#vCh1"
    b"5jeNL%YizLZ>Y@bA>bL{qxYUZifi`TdKk0?B9HoHaCtHsME%QlROfyKdgzu(XxDUmb_0*%q(Kck+gHSMb}yzAkb3kj(B+O`0++G|"
    b"JBc-mUx&N$2~g^(xD$3&gjltID1cjl2x$tyAC;0OW~-!IspKwRL$}&7uvK?p&0EUw@*z;SzR$+fI?31Of;MT~_y&hcCnN{?<pSU2"
    b"^~7lb;Ek36T0#Ph4+{QYY<DLRgD<*m0KTjGb^{S)op5E6^cwmM2#(DMAQl||nD!Sa*zBViFt5|UZ7uNW;(=pXC1Ag{772Bo0(c_v"
    b"xLGKe&Mh90b%^*0%iTnB&3IqQtDhWwv-LY*C${#kU|c9t%?0!R2GG|8aP0|*PGxjWpxOa80Ey9j@~HmZcZb4{eD@vTy2<i#nh@TD"
    b"bFjr244Y(<=ezIT{-26J`RU)nWlsgZ`z`@Q`x3A!J(3hwp@xyVHBOe}3EdDR4yIiL0U@>u0?Pr)^+4>Kp)B@VBWw^z%T2Qd7tPkc"
    b"1l}Lyy$-rXTn?BH(Jd6a6l_ZiL(c#>v|BwYor5Mo&?PQA<H${MDVF0^?8`jYbX*sRz;E4NB17QYnpYZ|xEYVGxZ3Edq3fm~J0T@Q"
    b"-RUxk#sRVfD<!L%Myz*e9oBDcn}gB!u#;0wX?U%F6z!-Uux)n)(6lP^kcb`Za8=V-sbW|L1z{st1i`W{-FRa${g;f^YED6dy5=10"
    b"<dmws5Mx0Jd^Qo|a98k2ro3`n!;<6aGPN!+Jjf|Xu~`Mv36XR-^M<D1YM}|Jc9P;v4lU5Y@7;qXLF8W?Br7}cD{UW+#KD$1sn0CD"
    b"$cXWLaR1ZK`X|>5z{Plc+Y$YC?|NxM6df(DM8%WVd3rS(gQ##(Puw<915ihKe4E7Z4JPIkCA+hI|C8t*{c-y`hmT%IJdZcP#gcr#"
    b"g<N($o}a)$1=;)Qxq*o{=g?_%JYS|RoRG!{8a_R5p;n|$LvgotOw<*ZbSvY3Cs6Ied3)Yk&PE92RKr>7^T47EC+T2%2kPEm`!X&;"
    b"nn=3aJ^!vl3BJ?Wy#|nbGu#mF4{lAkJp0bO&l`ogM^p*{I5)e81Lf*?%TLeD9P|{RPm2ekSq!3oadhya$*`zYl86s@UQKlb;E>I("
    b"<^J1a#V%fUc-_1~b>;+j@!C3hsCpI6kh+L~kw{;UK_oK4f{Ou=8zX($<TGr6gww1PWW?Nvz9d0Ka|Tol=^ar$CA`VgXS!{;D38WK"
    b"5;!*>YDamu@V>k@s%cX5A%2W5mpSw|&+;6vNZ6`Niw>a1Xi)~pwB*t2aXv;pEYVEPeF?xyyB0m_SX=0m)bYcwcE9aE-8($~%_Cip"
    b"i2)cYQZa;ZK{uK&1~3~1QFUZ)iJ}68G06r%QWe^!qN>ee6Udnq>iB2ChM%OotvX?(1|g=wd_Dk3z9hB&>v8%fFtpS7;TQWac3=L!"
    b"eS=pOwUVqDubFiy_JbNotF>$i2h$}X@UC1L?2L;C5DZse9mp)c02B8Hq^4VRcIt_DdEp?iy4plOVTI!d<LJf@k6(WM;>j*uZa54x"
    b"v8ZV(Z-BP&=pl0iZCKku!~fL2m{iZIJa+10mO^KI#StiW7&_rzvQSJ%|0?1bJ%x_`WkW~D{B-LU*hm<21td*K*}Fip9nBLQz|PYj"
    b"aABc@tgH<QTE=VE@y~cIG;|6@22<;{bz?nUu4mI`2vSfmi5`_fBdmj>RZcC4<YPuvEm&MVic2?VBYeQO*(gP&3K#O}6H5Yyd_Y^H"
    b"M#Rvt^YcZHL__@qq&26f@V}Hf_2Bmu%fuEu0Lz!LISTB3yj+|%cRoY%5PyB%1pZt<5Yaf>x&P@7{sM!Q@wB-U^WvtHJgsW8swMh$"
    b"zt|>IdPBxE(xAoZ&#&EWlhvkK^K#aq8ZhwiuNfJzowG&s^>mB{o>H+rwEk$96Tg9m%`}8_L_vW}RK0<n{k66LsnNgK?}B@}0GvpY"
    b"EoNG#Lr_tfXM_Xm38V-qJ)-o1Q9Dop$TnCN%{O3=$H38R`iFTfAe9$bw1DgB@~;CF4wjQe|8#(|&+86d6VAnd$EsTHw#fSU29D0;"
    b"lmOao#^Rjt9CyS>hKoDjx-s!CJr}9lUkc@M<w`2>Ct_B%{d&Bt;fm^8xTdo&;Rd`S;dW%Z;^Kvb-&<$tqOQx(X}?+dO{jgVY(p0+"
    b"G$LS+MMI#h>D8w~|Fsod0(EL&7frnSXyX+EXL=-4HW6ju`RKh5&=Geum`^S7h{#UDweTL~TImQFnNo?$y4rwd7t36q!|Wn{2l$s2"
    b"zj07eEEb;`NL5f>ks&u+Fv4=L$e4El3SysPOXd~P8>33;7hXX=C~X^#sXV<G;PtA|mO_>8vZW@^!lor((@>j=^!za?U~GHv$^(?I"
    b"es5~O!?n~`hqm}6FlYjRa2xb#Z37GgYB~AI6ag`koSgnQ%<!O5U)@;t$(>B9ygrz?E&6=}GOp?)UxMbUp0sp1xUT>>Kzwu#oI`q="
    b"cThH9iC<_y7vq_}4fI=9Jqg@<l!hfr)a8fEIbyG%T+%NDV(2qG4YSz&Ops%)EBzj3(^ub~fx;m*XXu=y!+oM=pjBEJpl}CgbmYLW"
    b"a<Q1_ftBJBz`tNT_y*U^CI#^$z~fDv4?%)YLa}^t4ZsdRKwV~Dz9!OTIGDa3<nhXr&FQuM2m}TJip1_w7jCa9NaOD4!&mIlUMt+}"
    b";JnC?ZZsxK#R=I=E=VhPPIT8f(Ol;r)4!k4zn{{-ME{9ZGya4%9}jt12wcd@1fM{<5L}M_>13Io*OTHG4>H7JI+jt})M|VVR}zwy"
    b"V7tJwOOWix&f3glE&wk~S74)Vt-uM-cOD$33`R><wX(9<&Vnon7w7Rx<T%z*Sl=+{9^#|`%<!oQ%70=Q?kGKzdDV<|l0OMpGYa^#"
    b"glm5*@mi9NWTGX!lN&D;ORqX?3cdsd;t&i9SQ1@mOfOkrz`T@zn2a2&3`j*7VD2EEYsn4dD>A#$t3~f4T)T+O1z107_mjBxC2C8N"
    b"(J78w3?gJ`bsu$zmNW@YXruc`PZKl+<ML^GyUuntU@6`w#Y5dWw7w`C5A2*&!1WkaygNy^xuc}leefOVpDhRTQT@l$w(=xs{pEP}"
    b"Y>ZUZJ*GBL(J@Y09?fr-Q?wyM4~ulfuWJFh${cMSty-68^D<|K@RmiQmVVdFc|1MMkZJ$%w1q!ON~A@WDE^=VN_L_~X9(EA7|`)I"
    b"2uZ|LgZyMLAD)lFdkB4xZcGcSNGd;I!G7n)YH+2jO~5y0qDdB(L!M@c0;myJ<pytBpcWjB0YSE_HCfy)oC;K?Q$<|-ehx&R3!GH$"
    b"QE}bfqgy^{u)zWRfVN228QdB-enTRywXH}{RNjg7pzztUsd<HmYb$m}Nk#07b4x5jTCJ@Z7wa_My1_!Lc<sQKQxt?oYW%F$lFCk}"
    b"2B=WRjv6HbD!dy5iz;g<P`K&pN&6_WNnsIfA20-&sD5J_m6c3jw9eYu!#3+K*W6CS3|4*Q0VghKg(hTa_DZL{W%v2WI+^R1AYbM)"
    b"aD4-<j&1=hD5x?WgyJj(ub{q%kPBd`FlxaHLN()nXx)^k=;QmS*3zo2z2la602%ba*a2h*_)y2jj84OuzD$_guR;;v?0{keQXqjs"
    b"etwpEFh?p;=#&(q*hxVlN_r`y_tgEOINHHqbcNo1WC{jvbUgt$Z=`rNEaB2ZAppq>>A|4Tllb8;z(?}<_lJ9QG);NfQ~Zb)S;xP3"
    b"zf}w|etP_L3(d2@EfYkOuz2ju$NrgcD!~mBXhwuiqo;#e#f~Buwi(^On6(uu!v`lmW_N@rwmUV;ycT}SFvt3>@{mRuD6vnaaIe&="
    b"#lO1u&3dRSQ^OPWVuK@)LKeEPR*B#<sGw&nf(<lX`Z7cC4lDfad(2zOyQATCN5HW~&?KBSFlAY+h(s=^A&$gQfZ{Bh3YWY(TM|BP"
    b"M14f#%7e5;uStGIHCqO<v`OGO5Ub#HeC6;_;MzQ&qsNwZC=&;<5n0VZ<t@h<kzD!U3rq}LHtD!+y`GK;OyJ0h4|6jk?`C!8T4=H+"
    b"o~v-ifT&kr;)c~H`2ya#ZA-}y4T~q5)hf9W-nmu0bl@))M}Ji7(P<t14nvI(z_OaU&@C#%BXUvPtco=?uhZFvEx6;3#7ohui|;-H"
    b"wC41Iu8wV#NrIdBS-Lep9e#fQzLZ$mkgOqyB<e89hJsNd!|aYS5STBT0Ltm$(%ji73$1H~P{Y;+HAEGp3|l-^P($=U_8VXO(@?6P"
    b"4w7gMEm`kq`rl}!WJX`B0d?>nHJ}dv;URS_aWFAsGPaJ0g&ieFho6c%U>R#i{+gkZ%vc^oF=36IzG{0E{;XD0#N~Y;nE|=jhFO+g"
    b"Rq;}!c~BQsiAG~VJE}C0c(HrB+D)*Gl4<aFRH+12ALcF^(@a?0QRa_qi73P<sN)KklLzvlbqctf_sP6s&evdVGe-JOkBVo<MWz?7"
    b"SqPeh5QH#(ca1`%9p>d(F)vboxb)mBh~BHa!kh=N%VEh(`(}(RH2qe9Mi1Tg&i(Bkt`?Rj*^-til5EgA5uI^T&~6p>9GtE=FovwT"
    b"dmkw%Z>RtaH?aZ?z!mD}Dk*MZx%2tT;bRGmI?7w!U8RD`n~u=Q_poPJ8UPM(W!)H%+yCLwcr%z>IF@o^{$;R7Km_8^5=dpx+!JNb"
    b"!$2G?ACPSMmO<;xll=b>?8uA<h?5D?wT|skc}3O?!U9l5J$InMfMJGz(KZ?ywmew=74Fi%+P0lqw&>MPoFu`1NM>A|5~&HRr$m;;"
    b"dP<&Q)jQ1!xqfKXC(F!G^R&F#z<G=j#MrPq#&d~}?Hkn}OyR?=4_EZXe~E+@)mvF-(ZJD1JB`ZedH<;!;)Vw#eZlFodWC&j1-6J5"
    b"3eHRM%UW!pj<0>0%e&1Hf@g%XM}MHD;y$34wU23)Yl#7lf|E%#lEu@D4l9Dvi@lcaI##2t#UFx;@u!7a8`j29aky7kcfq$BFWO6d"
    b")zlF>-VyKG@j5I_i=m7z$(LslJ7^cn$<5J-t<j@f0~&MWuUq_3A7`y2;+Xdj6a_@BV#J#c{j%-fFJ}{yJCR6L2gL!2CCn8(2&hSm"
    b"D)AUYh$A!|Qk)>>^Q65*3n!t987z3fki`d;v0*|NIal)`myp-2oPSMjAXvN0S1L6`YoQ%Nlz`cIRct$OI`0!EgPNX;1T<BINH9@m"
    b"C#BFxpi0l>D6yom?YE6uY=0-+sB&_mso=O!YRB^-(zoVI&CR4xI%vIV(4teL9$HbZfu!PNeijg*MH}-Fy5k-jo~}AKuU7<dV{tLz"
    b"0_?@)jq<fR`mf!^3=Jf7c8%H;&o2CJ-%t;9d~x9B{PMolHpac!Xq(5ovIui<Il-}^wFvJ(ESCIg)8LExX=4Xvq(SzA<`9rmRXTcr"
    b"Zet9MKvAdWG{gj^=5PqCu17k);RazKK^4UE!_qbL6oY?3wI*B5mm&(P!L=PM<@6H7Sg6KSI0IhOZ!{`|srJceIz=f2c_P89L_5Ub"
    b"I@<8*Zd_~@sBKmU_DL;sM;pb|T&r4pf*8@r9M=ybaO=ZJYk-(RDD?99nTfGRVc52wL&UgLg1XHyxD}iv;J!}*X3@I;lpU%8C0$|d"
    b"mcfm99nA=}8NbL^A7WsHLGyIC`3xdBtdwTaC2qr2yWlvFe)1nRAHN#iiyo`Gs&ufv`e|sr8?I+je=>^1*MhoQ+7g|p?wzaCjjdd%"
    b"?K_;sloeJs%u@HKnWGuQ+VCz!CQ!pJ^0g*zlLXHFz|1ZM0Dvj6NB=zjtNI5Jf8etfL=?HjXasNnL-Xzb_4aRi-M?!6;&Jb0y8-;z"
    b"s{I#9amE5)s%i384_Q!{`4tRmLP$;r=p!VjpV~LN9r3SK;zm(N8{DT0-U0uSzO65Wj;uXcO3*c-JAe~EDwf&tNz<U-+N{)jt&U=b"
    b"acxw4?#ifLQf#$82ona1_=6~Z&&6_=z@9!aOsdCrXjRmFu(DV0pD*;hA6#t2f*VDFSt%XELux+^RW4b;pLy{TS0Po(C5R09U8FK("
    b"D>OwHSO}3Jw<@8=WaY~aQO56x4qa(s165#sy0&xMJ{dmssw9bFao>XygJs!tRztZeH=Z@Bqd*_0x5%+60cr6)GfImO%QA|~;OU8B"
    b"aZp9ErRC-r4$;&)$wuf(HARZH&UbmrG<vo`(F=$<$uHZO#-uH@$|FhwD<cZQ!ig=h9PlN^WU6(a=^zkF9zskLHWT1zH<d@JMb<`n"
    b"1u`=rDJiPkl<%`ORT^f?F+x;><HBTeR2-2CCn2YU6(sDMPtzwBmKzT)@q(9_?GuS|9Z;M@uz6f1Wxe@g`@+><X`JP6UIE7%0^`~@"
    b"@%2Ssz&CmGE0;%kur)EjH9I0}$7%_g8qHLkFy`0<nhb;UHPiOswP>Q;l>JwP2K65cpIv)a>QpHKT+3D|MN;+hVi=tcgUh}BNBH00"
    b"DQj2@>((|D-6>JJg`s5wS3**2<qgFe+4*dpNPSa*T~OL*U4&*XZ3R;<JIS`JZC)k+f+Q-yoUz5pBy`FYb_v2NuvI?haVs)=UTW@c"
    b"1N34}0u&29RvcanKZ5OQ@`sbRzZ0HY58<*<r3c;-<@8Dq{bJ~^5#e?;p)6mYVO)V4bjQZpx)Px-hLzZqIyAA+!b^2`Nt6vtB3i@c"
    b"tPn_9Fra`G*1miloE~5gie9HEe`4_(`^Hbr+VwU?C7w))p4vC+jIFj<$VB61Zdr@PSZK8|=3tF+r`W~&>JSX_p(as6B2Ba41;tuC"
    b"{*9Y_Z}HckfR;fxAY)T>$bwMcpdRK3O%!Ph%%1Qg+y4>>8VLZ=i6XYVJq4N$q?Ztg@D-Abe*wEQ^#cF|)s|PKgs3sxsU~06ob#)4"
    b"+SEPjYe}Gu*rqaS0OWeuPQ0Zbro8TamGb)C@g~Rm>fYYqhDBzFEVPnpH5Bp_@NPZ0frOjd1IsV6w}MLOi-zy|eOuuewt5J{1Q<un"
    b"@-SlpJjo$`-5Nq@E{`#>dlBxWrLs-%{Xz||zk|skg_BXVY<rfZwwcyWYwXstu*h6Cv+QaU^MZoF);J-6saPKZ2hB0oAgQ79kZ~rl"
    b"qndWnp#$Qp$re{;6;@8mN`{C2=`Xma%I#jxNCw*$W4om#&Y)x$W1k+_h^5TOu^YlfW5P<DkdHS)2sJO3gS+Hli`K_ewPwA2UrH-R"
    b"P@YXdgbsN00;H=K5r^l&6~}Nn5Lxl;9D1LyCGR<SVC_FuLGmavJXrFkY;%vyJ_MPA<P3}R!NRl%NFkkXaf^hu1;tYv-+f0N?%=k3"
    b"_gzCh-{<E@*_2~AQjCV00SgY1M8}dB<`Nbf#kU|unQ(hKR=^}J9L*7eA5nWB=4_R{pfGvSn|TJc2=fh2QB6;UM4>ZJX~ZCObi)5A"
    b"1q0God`0OkC&OXq605qh03va1xXUg2<J?$y<5;8#n1OU8Y9yOBqhT_N^;5Ko#o)aZcvmXwV3^W^7<}0XPH#-vc~J#C>;_Pfm)7ay"
    b"SEptR-?-I*9t9(4S4<^bj2Gf(&iptw5oE{R6Ejyl_%GnhytIHdz=0L~Z`9bvqIjX!gdL}#1p6a#Vev6NO{S#MF@4k(tGs3`J8KyS"
    b"0unrN2OCa-JQA_I?|oCOKSdkc3GfFal6O%hC13XkCXT0thGEM$Y`V7I(8sAoO@qaOH?WpJG7Fx%ylx0brYT#tx7f_5obCX^e{>Ci"
    b"vx&%tIHHe+?(l^GrK~%Ftc1N45`QWt4Rn~}#F&w3UWlqIfD&sm5`v`HEx1`^6R^EFBrDSJ{0Hl5HI`FAVXR<+^ESR|l%EP~f9Oc?"
    b"n2HrNd{tcb&Q@wiOj=GD5=zDE+(tr#T|-)Qb$tv6p(s7{rB+Q=`6N{r2+t#2x*JlBuM`5dBb2Gzz-T|!C4vgjo+szW8@*D_Pdavv"
    b"pZhb&{i{Qc{IN9yOtX<_J4jpFB{dCX6}Rakzbum?FmmVGMi&ls9Js1M47BPH2NI&G`)YxlZH(%sX)-tGpPmh})ppn*?vJcKD5aXs"
    b"1lH;-Rj#2^{?)$8l~IqqBBIT;-n^68#8P=vw{52re#xdP_=yJcrxk1%pxZ!nON0;Gs@<6fL0M4%VUqA@c^R>HF+4d$iUe!g4w#@S"
    b"S=_p)&i?o*u4hQ73Vl}$zf`DdoxD<MFY1&{u}2o3yqjE_CC2X~mmX#S)+iW)mb{fNSLh5;Y!RxosHlW~Qp?G}7c>|aGga}s%NPAL"
    b"u23_npbzif{OhXb$5S#5G787?9@dLX;!<I?tSu5`EKd>pd<g0W33}>@c9s_Mh^-*`wy6^H1I(m+KXKWvX`@$ejBiH6(+816yiq4y"
    b"e3OPxHfu13K$3g02~CStca%o$+3xeBz4#pr^{ozc0*{KJ7nCI+vCjBjSWt{Fd;kz)Gyk@3zJZcT0)LcX^Dk65bNDb?i&ZH^Ncn09"
    b"2o_Udk_R_$PK)H_2#(Us8fOSFIAmG`^Xu6OJ9Y^1+HdZ&{#9RR<$_?p1BG-j7lzf~$H~fh{v=t&m2D9LXtpBHmUGOC!GQtW)&;M}"
    b"xZ1+)Yv0faRuZdbgy!<N5o(iwyf}^T;#Cnd^&aS2uczu+&!2ivG3^bwx)`ung|9Y~gn)w+GKBS<_^lP{D2mUkf>&>%cT;6;Qh>Db"
    b"_H%{mO~eCEaWc`?ZHM8|sc;819JkpEk`vP3Ivq4lzK^=7yHXIsI|UOP@RF7sI<qUZ6?%)h)M9VVHChOasZb2q%73!Gy&XP>qcK>^"
    b"4$vA2*ul<?g1V^lD7rC2U>kdDe6-beg*dTr6Mr_vOI6@JKT8opBmdAK(GPoI;xA(?^S#m=Rf2_iHLO=X3niODZhFA0P`AWF#fRQ1"
    b"cnT~44EDz;gOFhWTN!=u@^Tfwla^U|9b39&Gp3|rG{qh_^oO!h3GzLbq8KLjzM5hJhC6ACs~M|E*n&;z^CEfuhiTiiyH+cPLWFXy"
    b"m{uSLT`Q`VnPvXY_Mu+h(bLmRg6<J~LwD%kf`d7PRrnv&NR(0-Q)ZLg=w3Fp4}f*q;vC5Q$FmJsvvs!ar9$yyX<d?#aHuE;wC42Z"
    b"EeR?Lfhe6|$V`prgg0ow?22nugcvZcJ)n{V&mLeNfIp;+SEMn;%pKT4a{?KzCMdmM4&fAo5-?w0LQItFR-nI=<%osR5=YW3PSalE"
    b"LQqLo1V9USmc?-NO9}}|riA0+vpGuXR{^3$#s4=;L%VGceNzmnj8bUjOVrKS>;@WVP8DUhp;?h$8DUCYmk4k|$|?trf^waJg^jk{"
    b"r`{?oWh_8c$08htz*>1<s!2`Icb0A9v%1Z<=sl7aJOgdFx;c+y$OOCLpfwq&!U|CGQFQ+fomtca_NGLmBrqLt$Za)~4g5H{jl!Zh"
    b"z7^IEtT(b_*|1#)JbsPcuZ>oOZa%_Sk?J^ke_^t{Ea5efWMK9#xT?KuLD$nM-8l4g#Mh4bEdwUCdO-UN^$VBTU5vegmTfe)a_o-1"
    b"hS`E?<p~U8nCbf)xvAACH})?D%NgLr6uoyahGp^0s`t}7p42;?RgYG$0;@aOyoK%F7-n+&FswC#`y<mAYbkA{TYnZxn+~5iR$0_m"
    b"vZ}CSQ^a&OI{lx{;fiuG7F?~!J*_ZH*IuVO)>I(|2F6>XxND0-<nIrnUABL2q8dykoWqfk|2F8(!6`k543#6WGh^)op5_NEGlDhr"
    b"TBGc(<f%{oy`<h5EjgeErnWn`?A~PlKuw-tyd2CiJn?AC!4S_WiMPdGyUColBO!><eZ+EgjVU;s@hw@oexvrn%w%EY@94~5AZG+K"
    b"2n2^ss|)!q9s5#zr{Oj2G@`P}yEa_PY{t43+Uva6v=L3%c}+}0)o3>~jjFWPw(})Z<1_?{iGn5RB4eX#UAE-@vS{HA2gawXOLL>-"
    b"JoHS;KYG^y)hxzdal3(_938jnI+{(bmlUV4NZz|u`$lfHjqb;ggO=AKL$w7)45zD&-L^v4Yx3uNlfk9Y-1Hh-e+5Cj$3H~4z{?!N"
    b"CSd%FNlRi!_A$Dym3$V%bOA=Z?(m<Mq!n@_1)>ERw8eU9K#|`=-U2or&~r=H1rby!odLyMw4D|&5<3U<1u@+*4wG<AMyVo(lx1PS"
    b"DG_8U%`qjy(BoOvtbpLWwU46hcBR`mt&ONi=wh;dYI+yW%LUR_7%hi}C{b{vtZg>;+K)Y{z*xa9+t#@8GAOJww1*2qalzaS&Uf^&"
    b"x9r_82tCNy7h`-_8;V{H&Ed$Ec>*<eMp>chrsU|hcHU$*)wYYOcP=fU-mZ<h7=twgoJ@{P3rNd6lF#TucyHC-JMw|H7~GngQYE9d"
    b"SvnvQxaup$kkCS4>Iu&V*BJM(&QUoz@exPU2Ix%I<g_j@aEc}=E`EJ;PY@cA-9*J0L%nloV>`^KG~n#1u|S~sLlm#l9m)AD5D@fy"
    b"#=$@l8%TeNyq18V53E&y18G=LIyn6XU)oTCBYWDUtEy&Q{Hl*o_7C~C9x54SP#^(uWOm_EFWk=ojw{!w^^T}v?JY)gvrw##H0=2T"
    b"=}`&_EZkoZ#Q1+u9tvSwt0THqdWfm^q}PVjbrmjG0_d7Zx=G?1qEpy;^aCww56lRP%7dU32(xc@Lh<vJ`yQ$`%v>cIqt0i+H$4T8"
    b"|4e0>P|@Q}Efp)xWSM{zm`T`qvWQe*h{d9nI70#mTeu=<Pe6Eq7P2Bbu*M(71>GQ&0VKMcVdUBy*|XJ_#0ge?n{dIK3ZC4k!k=v%"
    b"Rro!<kSzyIm4^x*^)!;?4;C4qsKfaAJwWd|*1O<M4CLM@3*`PT9KczYodGmSAlWizV53;!rD4JyWKj{jxtzw}N)Uo^fU*E)2+>@o"
    b"$F%rzJ`wH#3Nl)OSBy{e8}LExk3A<Vp(LG}?Cw&+bReSO>lwoRfnc<+f(PlKyeP@gKTqQ?X?;y15*>b;f$7!s>zB{r0fxI$w_k_O"
    b"MXloe;N;pkYd3I+i3<#qS*?pM#XH}$#vKUs%SW_}Q|@gp7Ih<0QO0OmEJbOUFpre)Zk;WO2I8(-P8Ii<??(~cfn3C_Gtx~DFc}pn"
    b"@^LQ*OOV3>CCoB8s4-13zbuIpAV29C+4CQkWAw+2*UgmEoOX2T);>h>y*8;05Ip-oEWtl)ab4G0txL1ug6HSK2}PO2kdY)s0>nGP"
    b"6G+)?rqRKZmpD#PLl3XFC?yoxA4X}u7=r~u+EUJ=B(A}1(i67E7k5BhkesABkZUZP<PKAa=~F32h$B!!LKQv$W0%j+p>Q2f$2~h7"
    b"9S;ItNkjBpw>>qj!AUW?c3y#a_jD9HBsL8j3c&?b$AYM&`uIL>?9TmPMi1Q&aFOwW&1p#`pd$|vMQl7W^J`0n4`_P3b^p^^$lz<_"
    b"j#pKAh*fsBS@NsK>3rP2?;OM%lQK8v@sZV@3{`S}0zIbyC}y4ko8wzJy__vDw3r*t6{n8pd#;ob;?Ez`4ExS!dgax(CdcWz$kJ;G"
    b"*IsDaV5^vT<ARC$L*nJ|n)4TFqo&}Xoo6~XO`nek{8`R{2p*Hn#vBVMhUTp+bsT4-)Bedxc4cJ&ptE=|WB2YZ(ekHo87+DyT7Vd;"
    b"=3Zt1*+qO=yxO$AFVW_bT+*Wm#Douhh(95`G`+6d(eoPwtX4>9sSxxi)WhI-bttjri8w)}eKT8;AcN)sjm6L5Xd-2cf%jPxJUGem"
    b"CqVDcwn~j=T7zyj7!2n9%C5TidvF}_2T+zsB*U+d)vKM}`esz#r0mKj5b7ppQzJSCT1<W(KvEi*{u_Es!kcCRh1{og)Nly9h;Sk)"
    b"WA5Ff{O5To-d34fEF}s4F*TVs;cYQci2s<}Xz<a>C1{2$jYBRq6h=~|4*ahX84KBdevPzAC!SqjF0uI~XvP<Kz4aFva7*c_5GA>r"
    b"`AnKNskskFr-$?LYq(s#Nf#NX!g>j(5yZ>(O2Q>`oX#(i{#UW#Pl1bv<b?X7BHU!|U<B_8ARQcSQ>vU{@CJ$O@Y^(<K_T#w!8TJx"
    b"_F)KR7|tS{fCKRq?6Al#Ydq(>5w9xHr~%Onv`UoX09k*wOT&T7eeY_#I9gx~g`o<jprc2?l?jLz*f<c^WI2pI${;K`V74j8c!rEu"
    b">D-OTP)JVR!119iSU+XBBgxNl#*axw%JLYuX~t^}ne8D@Jg-V$7Bcp-yE^@#aLs=9(!JVaP|_&%>=qr32WOBb84xE)$*l{C7m!F;"
    b"7^w0hrjg?3@sxvEFSP4HHs#=?mGn|9W1%Z=dNIYUVubRYA=@c6`KD8yt!tk4jN>r8V+SkeFubHaIlxxy8kWo<cmnC>uL;@}EMd~C"
    b"<zfbLUT~#!JQD;{xOCwjw?GmU$ct75XmLYTK;*%Q^xTn}Rx;y0_N5z!<JD(Dvp^AW8$c7JCuVX%!4C9qGKiYNNZXaI`oiNc26^i6"
    b"-LgRi_54%>4Y1BqM4_7Ka+xn!0gAY6h?nMsBXJ-G&!U0X)(|apiMG-`x4`z3_ytnjXQb816<*O;2<g%BwB>X4GR;B;Skf7rdt9%E"
    b"?lo+gsirs1Rm<%XC$@2(mSixLiXknrH6rP$dPK!;RK{(Fu9kxn#K*7%DU>B#4Bj_-S;H$#=T*-@egKIB$~*N`E1w56S})tT>OHH4"
    b"7=d?Ok0g`<w`wsOlC7F%>2I=J=H_%dDC~enr%~1yNP1%xfM__!Bpce|3=U+iG8oRYoGo8qaw*CQh?dDKF%@6diI+Kijqx>=F^bcU"
    b"YQ{=|5eG^m15+qXFN38eD5qPR+#mcb>6$S@>_%^-E;pt)e5c&D+lHN}hU6LUXAeXe^Z+xV(7?VUQjl(=Oaq(^fg8k~SYT`{0N4rQ"
    b"Fh=aZ#?WqHG;(c{xi5i^r&R6*f|rca^q#QQx4ZmkfbK1WU5FOg+$e+5NcP@Nktn$lQ9OL_-UY~N&T?0;%&P#y3?#j`*A7*LA&$UZ"
    b"(+^kxw*|x#rcHw+>p->*qWjz17ZI#XlcaQzl%f^w4w<QB!~OxiMTrp5jUZ;Ttga~kcOgtPc`fSH(1tRnJlq}9Q{3l|4IfUM{;Hbl"
    b"I)h_}vcA=M!CJEnf)A;0u{!yj<<Vy$ak!WTiALhCscNAc+xcPwOIyA8vLN`U+oo=MfkPhBQYetXs;;`g21GD6TCX+G@<jE+g0H0X"
    b"6o1q)Yvi8?nxn-4;)&}co~tu9Z(Fz%IFBV|ZfC|&i}6ImlDCP;56*(nzAB(_P@A@!@|iNn(}|hoh$T=icw~uKaqt>w9gfdRB}BYf"
    b"AwR@4HNbMwB{9Y-umR*(-Bi37?D66CSIfhv&v^V>)F&(q#FreYNPADv)KS<&z&gkeaZakpY{6uFkw)J>Kl=6oid)Ci*W5TLxXvJH"
    b"5E)B?#BiGP>3YJFS=<;przoLSmXRc)ZAG(d*orO6Txx>fG1rGdo#1FA^Xsx?mj5L&?>D?x;%s@6!ii5MYna^AmMuM+f9k6cll6?R"
    b"kO_1a1PMzd69C&T;5sBU4cF{~3L^K3y-I5XP?zL6Mu?3ppJ~LdEJK2(^jfO)N~9`fKx#!#GbBl*HK0aj*dyRt6@HL!q?7bIo3b^j"
    b"_#2^yV#&<xaw;Q*Dd`kNH51u{(=9Ote_5B@N?q{??1@<-EdY|i1deu`7<$vC6irzAk?<PUUE5Tz=uwF`^!<yc?GiLYh>SX-@sm&)"
    b"P8seRN|AR^F%z1e2xk95DJPYu5jkDKxa3g5l|V;4cFh;neATJr=r*ZDBamL=LNO;e9dpb5IB~;r2FSt+s?e`lij%ecm}#UoCOKwt"
    b"sQp4YtdYqs4)Yu&QT;nG?xdRqt7NE;-8bCCTI!VvJfPRA?e0*ZWsg0u#%J8@`a=DPk*^5BQGiy^s%RmayzDALMvnqCig3OCJ_|U_"
    b"`rJ%k<?*%`gLPNyV4dh_f~306ai43JQ2@9AKuBt_RM91~l#1{)K7@~vMts4G$X2+Md{Rm~N<+SlP-jR#V2(=j&{iuOY&@Q`bwHoO"
    b"nD&i`o>L(6e$h8vw`@4qU9ib6zCi<^F)9LAtE7CN3TPa#4deI_kl7oG$c}VB%NFMx6U%DCZA%=7-ENl~ZTAu%4siKoLU<L2y0zfK"
    b"Kglb;T`vdu1v3`Pu8!P!EiYElW764|SAmn}a2XnLlj(^@;a0v>0<dm-J%04Er&7!XNvqinWzlr)h&X<HAPc5*cT}gtwC|*lHH8Vy"
    b"vHl7wON!wy<vO%mZb)MHrpQh+!dlTVs*7K`1fg-y@@iAT%t}JRFe$x3{1+$p=h|Eg>vAmUjfR$s7jZbO9H(Xk6DTYr!9P6{C@@s9"
    b"b3_oG9=3*(cx!sWbX+Y&@Aj9l#Egy`;ZeJ6QKIAWbIi_(AGZx+!q=%+MY%wEunJj*Aj7ul?eE7+qrU~-%m$e*Zw7ju_f&;iNw*;}"
    b"hd{Ka#dLtcgmRG^eWMU9u@!JhvZk%JDwAsH_)j>Y^-)e@x%Z$4N6*K%UxTB)k*N=I7U<YZ-F7q{y^GtX7c8fv@E{Mi!++L#C&M)e"
    b"fyCi5Jxep#jQO>YQ}!^GGTIASqw%y3SZkqTcbbezyhJWZ;%ShLs*)DOZo&~o=#C3vC9oZbz;Ur|*lmd}J~aoeBUS(LRcQbYr48CE"
    b"4Cx5oTsN}`4Z0nX-jpw(wi)$Gaf81DyC5dZlu;Zh6LQpp19Q7YekznJl5W?0sV#<tLnNMXpcpt&B*J?@yKhj*k-erc@6i#7R*8dC"
    b"<Tx>sO0NmpTri<mtf(}{aylj*Gjj7mE3In`M^C{j(0~o5(-g8=s0?9&SxHLTk(Nn6Kmm8G94J(!!BI$3z}|CYzH>3zZ~KW~iI7rp"
    b"#<?w6-G?vtp6)(5-h28e)^xc??uuCCy(!&tvbI)jmG-Wb?z_>vYg*FurB<_IJG@*#zZw}3!?P)#k(hY2wu66W6nCwBg+dhg8a~y("
    b"PD{Db;<|EstD0ljO@=SDHvvjoHqD}>?G(}?c56rVtL?`1cH?TNalO+Z2-h~_`~&r<U};V+E<1#PVB;<k_$hID%a;R-h55timysH0"
    b"_cLOCw^eL^OS{G2Kj}5t7*PtSw`!x-nE4fqS=e&?lU`B_;D5AjIziK)haF`Egs)G)^hdqgkym0X1TXQgdiAlq`nXrC2%~vIAzalJ"
    b"vTh0@+g1~|c8cY2u(X2<Oz6RAQYrIcFA$GUBozoDLk0~_?P23!!1jELwA?UF?}&IkiTno0x9Y}ZYkT{~<fZtu=iit@)DhKCD@8L3"
    b"sS<keK=ToRChaBl@JkkmP&r~sxb8|{7`kRyqE|R)?;-_kZzOP&+l$xm&+5tw-y23yC8E`L#O{AGY+fxtkyU}q7G<eIBaesu>z)49"
    b"c3hCYIk&Wk;UF|6v>TgzqIh46xR=WX1$h-s*+~8?)X;*=933A?f%qZs!-owz>*D<=CMF`{w^TAbj+TFRv1;844tEBZ$XS;UX%CQM"
    b"BQj6hJu;)!FT|9X4Lql($kXyKA>t+Dic6B2HC6--A0ITGSCB<CZU)NI!T1u1RWcoD?jG(dl@l#hgvRv14x&MBZQap%-$PS*U`j|f"
    b"{!u|hZAw7lQJ}UPylt+ygLl#ua9AqfwF9OP)OhtoR`&f%opu@HTM8G?B8Q0%A}u0D%S|puhk&Pzb$Pmk$E9HzvyaZDmynQ*ww(^V"
    b"x_&I)|Hc{#1c=~HKIF}Y(6Vtu^~)k09sN|`r?$r3EGPqz7Wu4*PPZd3<znnHQtykp)|-1dOK+g@-aVr?H5=_UWMS%Jz!WP@xHq_3"
    b"F?JLO=Pr||RP2lJ(A>(;vAnK)<<3htN>Q~5NSUrW)`=@YiRA^bN<w)qNEC2F6irb6f#+3*%QEVAS@^-in(36VH@sw3sbEFWDQhcB"
    b"UAyzb@<cp&l_hv8S=*9@y-ViSO=3hM;t&OB!Q5vP31`6*^6o6@&q2Vr#EX!jfDe^@hG?xLeWTj=FpmqaHdPnWUHI4%J#65uc7_3L"
    b"-DeX&I8JpQzu2{aox*60-Ujjv0&y05oA583*9;f5!DYN~>+MRVt?pnm%`H;*x<J8=3B5?n2x}pev4%KH!AkdSkE(`hRt>`)CND~2"
    b"4XR@e3a`QHQI)h-EL%Ei1y<M&L{>RT7wn*E58E<nLN6}~iqyCLqX1|1mD`|I+cJO>k9OPXmkB=sfsk1g>9dt_(*hh$CTt>A>OZZ@"
    b"Y8=G2Z57cMl-nMjUO>xg-+C2WGLu|3=I~QgD~QX(k#8s~?%*udHbCTiLI&S#cKM-roeZxn157d2Ap=}(k<LyoB-MomThiVh7(#If"
    b"2)M0f2Gk+axgfYj5dmlc#S2Evi_qE#4V}OhWf6(=pk?cQ`IWLFso&k`xK<VTiUc%j<y>23YPHHf!(UcjS5ae#?G=9kM9u5Ld;p8t"
    b"Ot54EAqkXhHzo2t<-Ms|MrvD{z@Pr5A`$`V`H^_Ad2>~w!z4TjWf2sak}A*<4v2AkcEQOMY{yOU&9o&5@|i#syAZF_i5d#IrW6Na"
    b"so~XNlygqain|2Eu@bKOk;jm;v^5$UMjmJ@Gc=eb6@&t3@pNTYjun=k`&iMFoKc47KMv?6rc0t;*ZdBfvkJUX@@db_zTsTQjarC&"
    b"@tbQX6Pva=Z?T#Tyt?r&Oa!*RDo;;%OI!^uQFN$37!YbGG^4-qqwk<9>N{0Po{{WlVAWsb*{d%YUlk(6$Ll0)f`t6mCZjQ#O+uJE"
    b"4{*G8@w#8zsLR%_Y0-$?<=5RP7R&dnZ&wQ(TCe8GARp(h@W{I7(yQ|Ucn0AjlE@tJ)ER(bUxUKRpU0gX+%#$DqGWAa;WaKdR$q@f"
    b"=(bD)$1C7$N~WIXvJU5E5c^>MqoWOgJHWJ0(BRzTIeMG5Bj10`aqnWs608b(1`3p*z2ERkLq!DK?XX|-)ONq!r?TX#QtlZ2L3FfK"
    b"ib|B7zd^GmKnLjnJnvs;;}Kf+GUjMfEC;l7T~4_ihIIgg;pu21_p4Ow@U&WJb39jDLDO#GGC)v{6O+nZ%vbc3>fDGXKG8W8x3msN"
    b"0`uY3xeDSBxQ|n1gzw^F=v+CKO8FL*)~(7*AlpFnHNU24r%D$t-ylc|et^8~w#x>&0~yEWdaUasspjHfZb(yd;{VIMN1dIJJ+t#U"
    b"M%+R;vQoQRBt27T7|*J0-(F$cT)cNHjU5Y6(M8<?BnZM5M$Y|M*aRMZjC`l+vA7X-v$n2uFdIu2b&N1V9<xZIS&bnO0LnSL?iA<N"
    b"SKpMGkTM3>woa86c!)B&-_{+B?yO0%tsNU(;DZ-j!?E3Ni5;9}q>WX)NOKg_qOkY1g89=rZk!jxX(eh(bl76_1D=6U9uT4oy)eZ="
    b"LF^I~MeOemQXXjYk0uXilk8+L$*um`RY5DXL|5gTtB`-avG?dYQwr3=#Z+~aJfvG7n*$Z4j?$8;<kyfUyw@FyeP6N)r!Q@==f9J8"
    b"OmAv$Rg_}|3@d5BmH1F?<1JI(4jkUWJYM4$TI)v0Bp&s2(is!IVRsdUoOI?O^n7PTwKn^-u$c4=#7UbtfO1hi5;>E>6awm<*|G~6"
    b"jS*q6^9?VAVM28nkOE=b3tX9UPs&Wthxv58`0>uSWx>l@+AVEtU4x-37+J>j^b}=1unvY3=*t?^k(!p@hL|>Pm~FE;@?Mj->bKbx"
    b"r7juH+1gw02*1>i^3~rUqM6-S0@>QX-3TG-nPL&oQVTmPO3A#@{zM(KDw^m6QJ{y)abR!>As1)dJc+0G!vctxKJGsgT6!J8;R@yO"
    b"u#ZfV<O_+<oRpCfP{XDn1bO4zDa0RyBZ^MFiiE(|b|@>Ch^P+uB|sYoIW;SET(_rbO+$oinp@6_)ny1E;6%w?Y^EHg&~14#rqGS%"
    b"OpqXe@fS?9++`Biz+(byMF&XHU_#WqIfl$Y%L>#W^d#JyqBn4-U_rj&&tIU*tYM-^c!{<sZW)_uPr+*tO@@Vs)F&b-X4xtgiQmQW"
    b"w`hOPDgjE{i=*-bxD%V?gz#571j}Z_@RQcb(}AM4%l2FjJH+DyH7~fuG3Q4|U(SzlkU{=>3f-m52Z5_PcF=r19yB#Tt~KZ_#U+KX"
    b"PixyU(M~i$s>$7<q({Y^Cw)A9q~~29_>@E_9Xy<6SwKs(<}6fRi!-vcmBaz!ZbY^N*;-2k32FF#iC-*0eV-T))d4H48OLGSB!g{N"
    b"!6VDZ@X!`xZr0Y+b>#9L9TiP0fr@90ja7p=V{v)P{1{7iwrtCtuDp#`Dx;0JKAb=ME*t+dY<@KW*jpvaG$YrKv|A-$v<>#$Z&1mn"
    b"dS!_819;7G7nlbj1IY=-jS|akksN%n2T8g2h;so1Ge<cF#9?fO0HdxFa_BT4$}r8*IX*0qI9M*=*cjG_ad0*P328;!fb~ibHIB`t"
    b"c`A~U`?OJT1vdh4kNon*R3e}%Pdk2R5dN9Kcs(cwFpt@mcLQk5UZB=47#{A<TcP8yA#ti4#ED>$8%y!)eaS}?zEOO@cY#-TQlUIu"
    b"yV&)O4@6`IHY;z=IhUB#N3Vp+dZ*u*qxz_Le3K+u4=HQ~s*$^Hxe>Zj%7Dn2S1B?7yThJRZN&fUpamz7R*;3pR01gOtX+Gj!B}$1"
    b";^H%BhxBIW4}VbvX_p~~rO+L>OA^fw&V(o-NF4f>W_H1DJOX(uPBx>WeR>RsFGFRc?KnVW555iG05i}<k&`JKunyDl1pL~dIC=*("
    b"sX4NEz2|fdF=c;wA6~A3Gr!4?b(1?KO-j1w;lgNqDpo~>Wd^}LO@o$*e^y=6WukCJ9MYz+uFjW-hsR+PRY56v@H99=kVkrNjrfN|"
    b"o3cUTlBm2%wgGhI%R{%OEW}-gTo65$j5)8k7oEujGXT5&8}7CD-qg<r(KF!qS-n0V0Fyi)|Hy#~Gl=Dq6A22cpb3})j-scB`&+a~"
    b"6p>~!K09ALSkt;tx=nTw!WiKgX@(>4gC^|+W4@uzjjgh|)Cgj_PEpX2x7M`&f{9^b*3gSlrAcJUkR#`rFggG?H~^Glq4d7G@x{#N"
    b"dlYEb6=&aZ*?c&P9s5)^DC!wo)mL}5Zj(s8qU_R2`EWJH&SLi7OnHGa6Vol!(G4KzJ{W2dz3dq3F<qet+R$f9S-^!n+e09(0t)L`"
    b"Q__2Er`8i8h-)*)qwDBF@`uh3>-)7@Zf_(+oThL3YZ>Hs+mk9bo~OM5p(ZDUVpNGUmNN92+Q$YZ$Aiey@N*bCvi4ecNUX)HzW9Ah"
    b"IEUU9LdKYOZtU8gr(n+p!ow5GIna39$?hnhEeb6tu3qSZ2xHn_ZQK=c9w>D=F&$VSP}PY%SwoZ=<M4YMj{uAn*x-ph`u3mZqV9yT"
    b"0Z;URGcb@ne69ixYU@BGFDXevYvcYjaLbR6qHg`(Nw@vWo`lM=mYP<F^72UGyFjVuw+$U(wn6x#A)>Z<e(EB3!X`r-HBo&}ui>LC"
    b"#Ag8Gy+)3UTrIo6z=e|yZV!+r!C=XE>3oormV-l+lTN1|@cIH@sr8^jmt-lS`OlAW3tc`oQJQfObc#MMS51+JE6oe#QIE(B>6@+n"
    b"{xU<cPAC%$7XZw&)f3CQcMubE$KvpzL)Dd;{4~}DMM~B#g%j<L<?dG3Rq|tZh#~sD8jLnog#Gi9Zx`3|=az4mBif2F*(VWhp1z6#"
    b"-47d)tCqB7eno)3Vm*Zhf-zVdT1{!+0S$c;G95qFKXrEt+vCPuEm;~*N3=26{Q<#^?E>MJnNZkJpl!EOvM$c1ZcKd2F3oz4H>iQ9"
    b"Oap6nfV67?JZs2%cUNPKB18ruo$ZEVKm%+T#|{@uE$*`5kM295kWI5PP{?d&lZG<XHm0yj&7XwLjP7b=^iFm`e+2WIyPLq=%~+*y"
    b"_h_rxwfY)43&vnIco;BD6iBiVxad-LZCW?UKTu`P@*c)4rFJT@8_Gl$q>u-yEMbvt#3JUtmfO*vr5%aLe6^W~HYaf`Mf7UBD6(A?"
    b"Er#)M*knXR%<Jq%)*E&>CL&$e0Ihd-JCQg%Jv?4~C}NQ$(C|fGqU}jGF&PoA%!ZLWY2ujTz3T;RQ{g4oueJSr1LFz8|CyUtfFT_5"
    b"P%ny7ulc$SOLXN}0QTAyGWANb=TCMoSFZ0L<#NRigO+kPh<7iN)`V9+-ii~ICR&V@S;lbD;IwWETlvmfK)GM$b<2*q>iVv@ysM5|"
    b"m#b>UblVDxhsMNYJIG<{DOM_KkaTG7tsEpZXbl;O;7<aOP=FE&IqMS(7Omh=369G|m4hmTp=a@U6NlJ59nW)+5sA;&7C8Z`sDX08"
    b"bBSnw0<yr%R9r|UlAzA9Vws-Gb$)^&=PfaSYK&YHjWwqn$3pNLHh~lwAy|!OBI2wEOEpY96O{{G`m3^AK9wB09YekauJtsB)j%9o"
    b"W)9v6=7I6vivG!Z%eO~3qN-KKxeJ^RMJ!}UL6zX9ww}Ezo8Ws*FFXJRCB_j#Hc;o&)^`_=swF%*Q8P45zOHNq^{PPFg%T6_dAg3z"
    b"Ne9F^4@5tte1-v&QOq*s)g0|Fa$-rg7-@J-DON^B)x<=D%;aD~HOjYUJ5giKBRGx&H^^EMFK=`+++jtn40$Z1LNC%{GVr821fAK5"
    b"QsW*u`CQCTkET4;n|iSsp_oP&DpBJi%i5A+<9K{AAmO#w9N<<-f=s#VQt@U|!R#b+&Jq*AEqKGp1Ki15VOm2UJIXD}W7;wVDUUA4"
    b"Ex=1RC8h{yrr`h$!Vy;ZX7lk&UBFnOaq;0U_-`if;0ceeHO?Us^}&s}ayRT92Z#o<bqd`VhvK1l<J2bT3ciSVQ4fLI;(DWZ+(zdM"
    b"*t|Zb{dQtY?nyEuP$^|IvKE61O^j+X#oU=3nb0w7gmfbU2P~>~e7`Y>7o0ImkzrZzX{r>e3r<sm>I8;~UoTT21<Xfif!sX%@`dhZ"
    b"6<fO#%IuXC24bK<s4Q=dJL*S6PpeO+{2gK{0u2`2=4pNO#ATtNsqralzLm%PmWhd=dx`_i8~=SfmH-ALa6{6Vh%~yY#JMSi7O<d2"
    b"mDTxV5p5KhRY4{J9(oGp?!rR5Zq9Nv)Px3}R#JV&nGMMFPWC3zH;_3{jao@WH+LH??l8zuZa^4#%widt;BlWNETIkqhiiP7qfg}v"
    b"u=gVK6v-IF0l|b-kdmUFBE#w-SSiiGJCHa~iXjCUm}lU)4r9MS2lt`5{>#1N-TfDPPnqBpNgCj5GClw_3UoC@&%Ye$XfJ$jMQ8@u"
    b")O<H$&Y^q_ULHL!_aLR(oQ-D^0pkr`5ZK%U6}t@Ff-aD1=P<66J{ZiXpcHI+4puGs5EcmNe3h$8g0(_uFcf<ZsIgHKMyCi81iBH1"
    b"_8-`p+oLz<=v%H+#^PZSXCKCTMAN|kkH%>4)f__ck;yzsd5$r*H{O>`xa-LD>EH-+GK`Qb0r0^D$7$*&tU@imz2d&#x1Dae&QTj6"
    b"80<J(f~}q!YF|4gNkYECXad`dDjKNTy3Am3*>pUtV}3Q+DwYxQaLIxAL>^j)<edhai)VX;c-sEBf4E2Qfrkye2a;pL_;jtzos^*c"
    b"(^1~xNJS^h(;QM)bR?l3Jf1Q`(?zg>%({c?dcrUy4?XQniS9T!+jC*`S{QRj<x(MT+hU!#l)TUx3`els(>jSb8WL2X!S1Y8DR3EP"
    b"a010kU)XJKtA%~mKi~P){iH029G2fClv=^<n$pT6JaecVSvipz1$<eY?<i9uaRDNywnX01O((t5+!e$(+dky&QiU9DPs=2?Da-ro"
    b"Ho)7a@gHIcGT>3l;G`xX%-LHlUf7Lfp@gd5u99Q}=c*u>VV#f{fLVRV`2vH1NS&YcKmPm^U;N78<Urps{Q|FZ$b7fx5M%+#1=$HZ"
    b"VE_X&wm}M~R89i23Y}Qx=WAm4O`N^w(Ia527Kk51ML08=wf1E|J3ckL1yL$!!w`w_PLw6>Eg~pbK?*}mlSB2r-ZnRpxl#}NI0}q;"
    b"6bdWr)WST+jL(4J1-v|Byd^j;DW+)VI<pMoEG5BA%}A~+aQXwx%qP^B<d&xe50Ll8^GS2cClE=jzTMj1NorNOt{t}1z%#tA6?xZ!"
    b"^@)?p+_OYb->Pqfk1K^Z#Wf2%oTzdaV=Pw-eR?y1Y@mwxCsYG#(<qLzSr}z<7tG<Vh{hmvVIwU1_oa^2!6(^lb$h+A9^scy8R`%g"
    b">wR*hG)4Y&mg27Ku-RHvtOrv=eH=+(K`1X}XM^KV^R6*0*Di#qkT5-nbbW;DqS?UlDz$@=t5wXY%A8!+tWL!W(VfF|N^yZG+Qn<4"
    b"^4#if7Y=c!6Y<EL8+sL!ifr;>U@FDFGMF;z@Pp{3$cirq*KD%LK|RoTo6!p-xQ9AhDJySDRDjYS6eWC!VJ$$YElt5ie1^37c?w)<"
    b"bfEH9&%lngiGZaG09!)Zj8iTkSA@#4szN31PDPP~EQ&^vOzkhHZ{YI8+&dX&u|<6S^^4!WIQZQQI&@-k3zG+NRI7HE`|N%0G2xvQ"
    b"4D%z}*$cO$sWI?LQG67KA;TUP`D;hd03ysb*R$jw!c@6&OhRCM&x*|2`J7w8P%xdHZIiu>Wy$81mcoe`q*}Rgti1H2<D+k)x|KtC"
    b"0vj-a<Rolx#!sIj?>0)b8bfI|2X9*Jj8Ko4i__-k&3t?oa|Q#@uV^^ME=0)k1b+Uo%oa#pMNiq0LAfzdbR=fV0Q{_ENw5&e=AKD&"
    b"!~8Ww6r!M&m?Dp<K*g|eOd+UWXXgu2(!lP153Pc;%g+7JFK9A((vqk;Q?jlYXRV_Jx&ZGVSc+BZ20u?xQA=eT81tt!7oFRyIT+g}"
    b"tsK~MkhQ#8XlNoXo?|o68paaDun)FR_*)Xg@B=W&>L>Q0e&aa#cQM(*Bt7M9rP+*%jz^1g{BfS5V@WLf@K{AJ(m71=@bIk2Ttg33"
    b"+?lOUY~R42E2Ee}hG;+tXh<e7g~y@K$pvHAhUJFG!47XK{E9`{)9fWzmK6ty7T(P`&pPZ!9ep_bJAR`W)GWKl{B1cgU()-!?X|ck"
    b"sjXK`7O-8^SZuIn7;HSTqlKw>D40@_TUKf3?3;$+Dx)|d3r_p2LCv*wQ6(S30ng_85#uou8oB$hXRc7x>cjG|%(bO}3IN%$47A>L"
    b"<0K>ps}umP<*?Uf01Z5P2skK0Tsa0JeTY<s!B1M-?rTB}RZ&rbqDBcDCNjig`e2I|BW!AI6Qc%ekKhb|R3Gzvq6S!%yO8|dl%%S@"
    b"?(Dlc{Lu2qw2Ial@36}{XJL6J!7g`#b|ui!HT*d*ri=<3S-sl;=m64s7LuDH1n4X&l!dBT3(o7O%Bhj|f>Tdym?eus9Chr9PFOy|"
    b"ZyyoF)6I#-HgL)eDG(U00UWZ)z5@c|-a2k~`ZHvg!S+ykTLw^TFQdffC#LGub>)2Z?9&I`p*|t8@T)ps7?@y^4FvY-e(Dw24o+f|"
    b"qY4=?zp1SAnKgIN^VDh;o_5{^by)^uUQk8dG~lW2&|Z0{q=&0--c?s%B-3+!RdFE|Q$btEVbUoxq?QC&k#(&AXt*q5PfZxnBp+kU"
    b"DCRvDM4x0M1PSyLV*WK&DJ+;WqBiNLLf~enIRIikDO`luD2fs9hi($-5&v}CQlj_nXP_+o0F5CGcylB&>m|FlRk}-!=zgLuwcsum"
    b"y~TBG`(o;YyJQ)7)G<sz&Gtl6gu59GT(4kP!K$Dr2Nn>iRPi^**l4(d@D>T{DQXFTRz4Y=jG^nXt&Dd;-<PS`2M#vb-CsRt6KOAG"
    b"cdEma1;T|9zA;KWD*)IADLh@{PxIhj?>biVC2-cXgMA)IpBBx_rckT07?n*7Mu#sZqi~3V0;D^MowzwKfGcN+39cmZpzva6RSUQ*"
    b"=}WLuoF(lmeLGg^*tL=7<lG2ga*<!7%DBTF_kjfIBRQhn|6TD1;V*^O$Rw&BYo?jf>d;erXA8S)TZzH&B&)PxMo+ztD&s*;Fx6sR"
    b"RO@8rs`Bl~Un@}s8CNC_zzT*fnqQi91x_*oQu$bzStTMUiD;u^uUmEAB`E=24F$u2a$9=)pn*-?C3yjH+)Bq3pfoOj$>~%c4c2rj"
    b"<MRh2@!M-rjK^=bvk{6;@5TSOj+zNk@8kt=?F?2{+<41n0G095!xo%og?p^T3LI@g4?OM_cFQuWa6`H)OB;O{3cf7m5+hefUveZs"
    b"gp^*T!zHH(!+Ln(+b}T8FZKJ6V?P%Vy#2haZOw5@!J<^k`%)!~0yPiPGG?%xQ9|G{X4x{L&?bsdEVyenVFo-8+}-@Okl>DxnFV-g"
    b"P}m8YJ?O=x`PV@)xNS|Q{@EvHVoYV<i#|^hk6Ik1n}%oI^bFb_Ey_5pR*^&WPS+_~X!dc`bW@H}>$G|YqdehHr)zqOc!Uqcm;kpP"
    b"L)T`c-eOZv^p*yb0w)%%GBPg;QE9`hMYp%z$VK%pOFpW8*aA}HZe#22p23h`WQ%7=6?%rRyzt6JnO!F>BPK<>^b66Sr0G(XW>pu)"
    b"1W{Se*-h4MnRWw=QRIi=ZyM3ppjU$3q^G2yjjZUg#6$HD3dPcW?R{aFLZ%qoXO2^{9(+BtZtdKb0$vbUNfeJC(~%VuN4c0=Qh!Lf"
    b"CbpRU^TlF@#*iErzRh{J0oh?R^FU~EG8sdB2UUPFZ_#rL9$3Jr1I$Zgc~7i{bz3>8Xuud>8?oXDNcIDNAt$gRNTl>RTur#AK?LQ}"
    b">R6QcdZ(h6gtm-xi9IT=h2dAw91Wl1U|$aVChx{G$g?=da{{_8`B}#%l9si`&N;9F{utnvp*@^sP3;#MtcnF;pOm}EDta3Rf3<Gp"
    b"U^allkt!-GWi+B?tK;bFm(L?ImOi=G`ZTg6J^cDuY}XFadVLNmIcN!#f0E!8tkhB>8$n0{hY>8^2FhFx+5_#wX+|!bl%tc37+6OE"
    b">36}GL^;6#cKM!z2DLExOODDEGX}JXW3&1tMru+U8G+DiY8*&acMsU$dxW;y#4)06cS^>G5P}@JW{8<6ad2iBKs#U1lwk=Pk_iyz"
    b"*T8zTT(IzwESGkiRR)+O%6>qG%hK!k49!+$84BifI3C_6e}9!4$_d-g6~;M5dj)onx46MuEb0w<g;EMM;Hs7w*$pE-4_jEr`zAqo"
    b")5rHC&Iv59Py~7Zmz?+kUf|K>t~Tt0DHN&#nQttOT2bKuMb!k<VXr_*n+_n1khqB!<t+f&!#5~EL-4@u%?YTcqgjTuo@D(Pf~97<"
    b"1s4A^%$D79&aOVM75CN#Y9<5eWW_B98vznS>R`Gf%a@9vB|jhB|Masyt8sDp05gE=7zjf8FS3^@YaD+=sfgxvSqN#i^_%14L$64p"
    b"5yeZ=Dnd8>Jy)y1ZIG^<oLJCP23Qd^V2+fgm9@j9QPrl4sv(7~>JX#h6tTt+z$(ugLaklqkaUc-YdHnWf$qTJkK8<d7__6^7caKA"
    b"cf5s^X_3a9CdG^Dq3R#V^BAE=b#@xdD)Y$LGXzK(Na9T$Bd@N<ayrxP`HYTsDNsDlJ>y#tVrx7esEUJ-gRfhwt*67qCVn09Vv!Bx"
    b"NP+g=mQgmMZCV}e6>O31HqFRqxa1;I;}(-&wl$@Jkd*>Mt=1|V+Cf3+OMw;DP9tK$2BrVyjI*5>E+(^4Ky>XAS)<aHZGr7HxPSu{"
    b"@gyVSy@_WPGvT-kB$_M-?V^iVs@4W^Iz*T}A+0T7d398qi1S+t%WzcgHwc#JU=ihrHxV@Zhc6Gl{k;esmtdPsN65K>^(g{>CWOw*"
    b"3|_*$cy(>WnP~k?feyR{J6WRn7=LvSfLHJk+f#UfLOTTTg_S(dGR(v)mV4k7A#{Y5m6$SW#H$|g!wjy*q5)?)URPDnNeZ7sQ9_H@"
    b"Q;soL1=MsYIZp@B)3m8^Dxp#D%6P+GYTPLq#2S7W#A^;;6~;3Kb|he_BbWy3L^n{lg$QU>!0EP5z`73gh-xOb7+s`nR?Su_>~0S="
    b"$Ud6O3r8vzEo5`W#kdV!E>Vg>S1}_(O$CpAi6*IEw0C0VWbX?zwX||4A;}R9!H)c9C%f_X&#b~g6ai;sg=INbQIoou-EKKv9L(_k"
    b"ZXznVo0M=(s`prJ1>h9*vr!_d3nfO>w@Fnj7VX=u!@78>tHrdO?h^Nt@%hf?mq29v$Rv)WJ6jk82VE{ntRdOXjGkpe4zgn~S~K3>"
    b"nKIvSL&UIKgcv;m6b~*>MuUj-rlLeei8Y|>F~y0g<L^uIX@Hi<HPSAdBv?`<=Y{>J8$*l?xOl8z!>)n_6iBglw(ox;f21l}+vKcb"
    b"FdpM=kVTVMxf8lad80QX6K1m=S%Eu6DC}pd55(@oY7)5<rF|4lOgHSM?4z=zh7{E_hA1IJGiBu@F$`2_D`Rj(x^7%F*;27C(#law"
    b"P$G4^P@Ljkn+2ELZ`-cU+N~gbITzhfB^_a$FsLnQ-bC6VNsMF%9oIFML45=irIHZ{Z=gz$9`@7Ew0T2HbloM=<n?)6f86fwHve+a"
    b"{BgVatA6jJt>m%u4BuaUw60Kc&l1OOM7KLr5RFQHS)3+|b+a58q1WR%FuC;QtG%xdUjDxSyZztplO^uq(O0+*AIFJV0&GqRMzGN-"
    b"YqF;%4A0Id$!gQF;y4`JP@~AWcTerQl^xAWpvmd%)TFEr4HASTiC4{!E?=zgmndn74m#&s(P{tM3fI(2i!@Mc4|47u{6P}?K)ZfA"
    b"!9crykp?iz)as7cra?$;gR{KvDukBq#k_17odY(mg!X<9D%Yda0>5lTpIR+^TGoQnKshb&%ZAEfEb|KvK=R(X1E80>j<iAlerjIX"
    b"O@Z|vEic^B5SrU*(Eo&Os1{3B2CINS>41WS14Io$BkDI<_}&0@kW4f*vN`${hsMPp2)<xwYRy7TT&Ae|4YeU(&~MAVxf<?+2Bf5r"
    b"v(P?Hta@f6X|H5IBz1O61hN|H0SCV~qEBGz+o7qu;k^S5sTS1QhZ?|W>0VWQB}@Lx``CZ6R}-+`@78=#$Uxx90oD*;xj6(v?dpTG"
    b"T`?g-By0>DY(;<D01FsnuM>)KW?ePzr|Jvmc<<<F@8#~3<Ng=>FPPd;s*0olLwIkrNiA8kl-^!k1Z!S}Z;j|zJf&ZGlTncu+<B<C"
    b"5=KmFtXu(%MJQuPCvfEezm(}B9306djtlZ}B_tRyH4Y4xqK>c9{DF4)W4Sh--4StNBui#frNIe`xE(rq6VhIBnhPZ%$-yTBoK9@L"
    b"1WMM4inVE8>*`n;j}jsj4i3Kk>Un?f+vB|#NBajaj-uP>;OR5>#oiYO2fwvmwQbwVT$#<>1dwqVGA-aoAK9%EZ=5%A>uQo;VNv{X"
    b"DL)oh5OkP_0U8whhVvUZbY@jH1^bvfx0Q2u3J$e71)CQr;R^%ge<O0KqY&BO2-8SaorGze3Nj^(x(l1I|JCl7d-f^@R?k^5y_C3M"
    b"tLiNQK=a#I>EI~TMcJ15tbu!ZtQ=-#4J?Ek4_s;1HB-DbJbZ5lo+?Dva(nY}vc(S+(f>-ZyqI={%(8ASFf!yt&zLrgAuRTitg2TZ"
    b"{mI~i@DE2{A08gOJl=b17imV%_rBbH^85b5vuFEH_JT_YBFsU~L3-buXA{f2$tWr?0^@M9B&;a<Gg68{zi|Asxh2H>0Lt%gu@ceN"
    b"u~9r=6>v^z=1?32)}1KKC1H|U8q=J5BVl|@^tdwVbY=(qNdoQI5+}+BWWA`lMFp{gb)=oC7Zwq3)`OS*Z}wi|VtTdm6y^=~g&71u"
    b"adZ40?L7g1%>LoQ^L^M8yLL$N^F7!Kv_{LzSzcF-b5fB$LWg+lOU4I~Nq6dT1HrD1(g;YXgZ_hqd^jF+xJIR=OMFF#68wd4)^`<6"
    b"DFM=5?nxYgx+v)i8llp+4!&y;wSDp$WAvl&#0o!2Rt98!4_2O+aED*i6Jt=oA5OtsqF%}GYuP*vfB^L*B`N*c5;7r?yjhx$u(h~E"
    b"bj5SoT!4knfSND>EleFnw&WtHec!OeBhypGEKXw_8rQhNe^=synoHD)8{Nvvnt+lEqu6f8lG^!m@z_|D;TihXG{*t{*Ei?!wAkFI"
    b"f##GK-n!;o2A2j`9GbZBQCn;zS30^P!%HKyAE{lWfoOG!f^%7E!~1fNCH<B0!`=!PL=C7}Li-bvMH^7OSGiVYoU*J~p&P{|W1F9@"
    b"nSjMOb92FgYo?io*_SiXXLh)%`BI)5J2Q;5W+v7X-esCg>&86>T<=lVU+wOD)c2PM2VXwl1FXLP;&|_+{f%@OC&oS`+^Vhrm57}>"
    b"U?<*;Vqz%zQFRuDwU{^rH()X*xZ%g8{2+q6ybG)%Jy@aN4PXcRDJAU7`@t&3el#vv+vRMw;4a|@cR5=(HLP;CsU4J%nT4h^9Yb})"
    b"mVLOXXgj@}Y`W#;d|t6tuxY*9kW1mZqL;HQJ3~8oG_gtN)-;OEA8xwVg?P2awhC;H>&A(qG#jTl0yW?I&+FYacz29^%fj?+>WW(#"
    b"gwoiTTahdsZe#O~fFbEPgGCOdXWJ$h;t#99!<%-YEt=hyZ1(4FjfpKZpg#{?NG5^`7ESNrI~&q$I#A2r#$>z<8P_Pyav#~ISOIXJ"
    b"R)BpdrYT9$Y)CGVrB$Su5tEL>JsTA2sk>DS*tKbakn7jr8#~ewfm@5LPs(EziDF7}6V#EPWk}oDaysb0XK6cCSztXEPM8JUc=qX}"
    b"&Uma$jM9|5JvZQ*v_xLQSWJjIS$?jAA>`?`aB5N~&?0Bzr14*i-cJg11L~VBKey+ZqZHSntE%A&6hBkbst5?;UFYcHa%s0*wMI%h"
    b"VQItwj6?{l{8W%zAnSSZO9J4Ru+kKik2uygf}%yfQ4QoQuqF7T8i7D5)Hw65#BQlhE)kge(_HmoxE%GxR@-rSQpGU0!IbZ&z-zDC"
    b"yvR*vubVePo_b{o+te<DEP|O&9F4Pr4PC};f?Y<xbQ@jHLEd2H9N`YYPmGN!`xNkl9OB&lVi&k692PJPqY45yLb|FTG)E@pHBf>1"
    b")|AX`MrR_DK0{+Iwy2>vNxXbbboGL$z(X$Cl1PQ=YxJOq%Z^o7j#SUNIL-Otc&L5OHW??rgSoUpJ%Y!z4p}a_)}&gS8ti(FVN}~0"
    b"T5IAm<1(uGa$XmVW9T=aYPym_oaDO>4D0&in2KT4#$%9GcE3BJns_|5{~y5YG?x"
)


if __name__ == "__main__" and "devtools_case_started" in globals():
    peer_tree = ast.parse(read_source(review.PEER_PATH))
    reporter = next(n for n in ast.walk(peer_tree) if isinstance(n, ast.ClassDef) and n.name == "PacketResult")
    exec(compile(ast.Module(body=[reporter], type_ignores=[]), str(review.PEER_PATH), "exec", dont_inherit=True), globals())
    result = PacketResult()
    packet_suite().run(result)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": result.rows,
        "terminal_compositions": terminal.OBSERVATIONS, "cleanup_compositions": cleanup.OBSERVATIONS,
        "pdf_compositions": OBSERVATIONS,
        "baseline_binding": {"commit": BASELINE_COMMIT, "blob": BASELINE_BLOB, "sha256": BASELINE_SHA256,
                             "bytes": 95837, "role": "exact_expected_defect_not_healthy_baseline"},
        "qualification": "SOURCE actual owner/ExitStack/emitter/readers/selection/finish/dispatcher/redactor/serializer; authored open/page/OCR/cleanup records; old54 fresh + additive incl2 expected-defect baseline cases; genuine engine/SDK/SQL/native NOT_RUN"}, separators=(",", ":")))
    raise SystemExit(0 if result.wasSuccessful() else 1)
elif __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(packet_suite())
    raise SystemExit(0 if result.wasSuccessful() else 1)
