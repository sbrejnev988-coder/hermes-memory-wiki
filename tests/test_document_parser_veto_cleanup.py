"""Additive SOURCE regressions: established PDF veto across actual owning exit.

Reuse the shipped reader-suffix loader, clone seam and bounded reporter. The
ExitStack/subclass, emitter, finish, dispatcher and worker error serializer are
actual source bodies. Documents/pages/open/cleanup faults are authored records;
no genuine PDF API, native owner, SDK, SQL or process admission is asserted.
"""
from __future__ import annotations

import ast
import builtins
import dis
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest

INPUTS = globals().get("DEVTOOLS_INPUTS", {})
TERMINAL_PATH = Path(INPUTS.get("test_document_parser_terminal_veto.py",
                               Path(__file__).with_name("test_document_parser_terminal_veto.py")))


def read_source(path):
    return devtools_read_bound(str(path)) if "devtools_read_bound" in globals() else path.read_bytes()


_spec = importlib.util.spec_from_file_location("parser_cleanup_terminal_source", str(TERMINAL_PATH))
terminal = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = terminal
for _name in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound"):
    if _name in globals():
        terminal.__dict__[_name] = globals()[_name]
exec(compile(read_source(TERMINAL_PATH), str(TERMINAL_PATH), "exec", dont_inherit=True), terminal.__dict__)
review = terminal.review
OBSERVATIONS = []


class UnprintableError(Exception):
    def __str__(self):
        raise AssertionError("foreign exception str must not run")

    def __repr__(self):
        raise AssertionError("foreign exception repr must not run")


class Cancellation(BaseException):
    def __str__(self):
        raise AssertionError("fatal str must not run")

    def __repr__(self):
        raise AssertionError("fatal repr must not run")


def healthy_page():
    return review.PageRecords(terminal.HEALTHY_TEXT, [(0, 0, 140, 20, terminal.HEALTHY_TEXT, 0, 0)])


def reader_seam(e, pages, changes=None, *, cleanup=None, finish_error=None,
                finish_after=False, read_error=None, emit_error=None,
                read_stage="document",
                raw_metadata=None, alternate=terminal.CONTEXT_TEXT,
                pypdf_cleanup=None, extra_cleanup=None):
    """Exact SOURCE reader/owner/dispatcher with local record/transport bindings."""
    state = types.SimpleNamespace(options=e.effective_extraction_options(changes), calls=[], events=[],
        emissions=[], finished=[], reader_errors=[], dispatch_errors=[], inner_opens=[], output=None,
        close_attempts=0, extra_close_attempts=0, alternate_close_attempts=0)

    class Document(review.DocumentRecords):
        def __getitem__(self, number):
            if number == 1 and read_error is not None and read_stage == "document":
                state.events.append("late_read_error")
                raise read_error
            return super().__getitem__(number)

        def close(self):
            state.close_attempts += 1
            if cleanup is not None:
                state.events.append("close_refused")
                raise cleanup
            super().close()
            state.events.append("close_complete")

    class LatePage(review.PageRecords):
        def get_text(self, mode, *, sort):
            if mode == read_stage:
                state.events.append("late_read_error")
                raise read_error
            return super().get_text(mode, sort=sort)

        def find_tables(self, *, strategy):
            if read_stage == "tables":
                state.events.append("late_read_error")
                raise read_error
            return super().find_tables(strategy=strategy)

    state.document = Document(list(pages))
    if read_error is not None and read_stage != "document":
        page = pages[1]
        state.document.pages[1] = LatePage(page.text, page.blocks, page.tables)
    if raw_metadata is not None:
        state.document.metadata = raw_metadata

    def extra_close():
        state.extra_close_attempts += 1
        state.events.append("extra_close_refused")
        raise extra_cleanup

    def native_open(path, stack):
        state.inner_opens.append(str(path))
        if extra_cleanup is not None:
            stack.callback(extra_close)
        return None  # authored optional native reader absence, not an engine

    def emit(output, *args, **kwargs):
        state.output = output
        diagnostic = e._pdf_emit_page(output, *args, **kwargs)
        state.emissions.append(diagnostic)
        if diagnostic.get("table_context") == "withheld_structural_refusal":
            state.events.append("emit_veto")
            if emit_error is not None:
                state.events.append("emit_handoff_error")
                raise emit_error
        return diagnostic

    def finish(*args, **kwargs):
        state.events.append("finish_enter")
        if finish_error is not None and not finish_after:
            state.events.append("finish_error")
            raise finish_error
        value = e._pdf_finish(*args, **kwargs)
        state.finished.append(value)
        state.events.append("finish_return")
        if finish_error is not None:
            state.events.append("finish_error")
            raise finish_error
        return value

    body = review.clone_function(review.caller_body(e, state.document, native_open),
                                 _pdf_emit_page=emit, _pdf_finish=finish)

    def pymupdf(*args, **kwargs):
        state.calls.append("pymupdf")
        try:
            return body(*args, **kwargs)
        except BaseException as error:
            state.reader_errors.append(error)
            state.events.append("reader_error")
            raise

    def alternate_close():
        state.alternate_close_attempts += 1
        state.events.append("pypdf_close_refused")
        raise pypdf_cleanup

    def open_pypdf(path, stack):
        state.calls.append("pypdf_open_records")
        if pypdf_cleanup is not None:
            stack.callback(alternate_close)
        return types.SimpleNamespace(pages=[types.SimpleNamespace(extract_text=lambda: alternate)], metadata={})

    pypdf_body = review.clone_function(e._extract_pdf_pypdf, _open_pypdf=open_pypdf)

    def pypdf(*args, **kwargs):
        state.calls.append("pypdf")
        return pypdf_body(*args, **kwargs)

    def tika(path, **kwargs):
        state.calls.append("tika_authored_transport")
        return e.ExtractedDocument("authored-tika-transport", "application/pdf", "Fixture", [
            e._unit("document_text", "document:1", terminal.TIKA_TEXT)])

    dispatch = review.clone_function(e.extract_pdf, _extract_pdf_pymupdf=pymupdf,
                                    _extract_pdf_pypdf=pypdf, extract_tika=tika)

    def run():
        try:
            return dispatch(Path("fixture.pdf"), state.options)
        except BaseException as error:
            state.dispatch_errors.append(error)
            state.events.append("dispatcher_error")
            raise

    state.run = run
    return state


class VetoCleanupSourceTests(unittest.TestCase):
    def setUp(self):
        self.e = review.peer.load_source(review.peer.EXTRACTOR, "document_extractors")

    def observe_failure(self, seam, primary, cleanup, *, finish_reached=True):
        with self.assertRaises(self.e._PdfPrivacyVetoError) as caught:
            seam.run()
        error = caught.exception
        self.assertIs(error, seam.reader_errors[0])
        self.assertIs(error, seam.dispatch_errors[0])
        self.assertTrue(error.primary_error is primary)
        self.assertTrue(error.cleanup_error is cleanup)
        self.assertTrue(error.__cause__ is (cleanup if cleanup is not None else primary))
        self.assertEqual(seam.calls, ["pymupdf"])
        self.assertEqual(seam.output.fallback_veto, "incomplete_table_context")
        self.assertIn("emit_veto", seam.events)
        self.assertLess(seam.events.index("emit_veto"), seam.events.index(
            "close_refused" if cleanup is not None else "close_complete"))
        self.assertEqual(seam.close_attempts, 1)
        self.assertEqual(seam.document.closed, cleanup is None)
        self.assertEqual("finish_enter" in seam.events, finish_reached)
        self.assertEqual(error.diagnostics, {"status": "failed", "pdf_fallback_veto": "incomplete_table_context",
            "cleanup": "unknown" if cleanup is not None else "complete",
            "ownership": "unknown" if cleanup is not None else "complete"})
        # No success document/unsafe metadata is returned on this path. The
        # fixed safe args/diagnostics, not private exceptions, are serializable.
        raw = json.dumps({"args": error.args, "diagnostics": error.diagnostics})
        serialized = json.dumps([value.to_dict() for value in seam.finished])
        self.assertNotIn(terminal.CANARY, raw)
        self.assertNotIn(terminal.CANARY, json.dumps([self.e.asdict(value) for value in seam.finished]))
        self.assertNotIn(terminal.CANARY, serialized)
        OBSERVATIONS.append({"case": self._testMethodName, "calls": list(seam.calls), "events": list(seam.events),
            "finished_status": [value.status for value in seam.finished], "error_identity_preserved": True,
            "primary_identity_preserved": True, "cleanup_identity_preserved": True,
            "cleanup": error.diagnostics["cleanup"], "ownership": error.diagnostics["ownership"],
            "raw_canary_present": terminal.CANARY in raw, "serialized_canary_present": terminal.CANARY in serialized})
        return error

    def test_cleanup_veto_after_actual_finish_all_refusals_auto_and_opt_in(self):
        self.assertIn(terminal.CANARY, self.e.clean_text(terminal.CONTEXT_TEXT))
        for reason in ("cell_cap", "table_cap", "table_failure"):
            for opt_in in (False, True):
                cleanup = UnprintableError(terminal.CANARY)
                seam = reader_seam(self.e, [terminal.withheld_page(reason)],
                    {**terminal.fault_options(reason), "tika_url": "http://127.0.0.1:9998/tika" if opt_in else ""},
                    cleanup=cleanup)
                self.observe_failure(seam, cleanup, cleanup)
                self.assertEqual([value.status for value in seam.finished], ["empty"])
                self.assertLess(seam.events.index("finish_return"), seam.events.index("close_refused"))
                self.assertEqual(seam.finished[0].metadata["pages"][0]["table_context"], "withheld_structural_refusal")

    def test_cleanup_veto_mixed_safe_withheld_both_orders(self):
        for reason in ("cell_cap", "table_cap", "table_failure"):
            for healthy_first in (False, True):
                pages = [terminal.withheld_page(reason), healthy_page()]
                if healthy_first:
                    pages.reverse()
                cleanup = UnprintableError(terminal.CANARY)
                seam = reader_seam(self.e, pages, {**terminal.fault_options(reason),
                    "tika_url": "http://127.0.0.1:9998/tika"}, cleanup=cleanup)
                self.observe_failure(seam, cleanup, cleanup)
                self.assertEqual(seam.finished[0].status, "partial")
                self.assertIn(terminal.HEALTHY_TEXT, "\n".join(u.text for u in seam.finished[0].units))
                self.assertLess(seam.events.index("finish_return"), seam.events.index("close_refused"))

    def test_finish_failure_after_veto_with_and_without_cleanup_failure(self):
        for after in (False, True):
            for close_fails in (False, True):
                primary = UnprintableError(terminal.CANARY)
                prior = ValueError("authored prior cause")
                primary.__cause__ = prior
                cleanup = UnprintableError(terminal.CANARY) if close_fails else None
                seam = reader_seam(self.e, [terminal.withheld_page("cell_cap")],
                    {**terminal.fault_options("cell_cap"), "tika_url": "http://127.0.0.1:9998/tika"},
                    cleanup=cleanup, finish_error=primary, finish_after=after)
                self.observe_failure(seam, primary, cleanup)
                self.assertIs(primary.__cause__, prior)
                self.assertEqual(len(seam.finished), int(after))
                if cleanup is not None:
                    self.assertTrue(cleanup.__context__ is primary)

    def test_late_read_failure_after_veto_is_not_reclassified_empty(self):
        for stage in ("document", "text", "blocks", "tables"):
            for close_fails in (False, True):
                primary = UnprintableError(terminal.CANARY)
                cleanup = UnprintableError(terminal.CANARY) if close_fails else None
                seam = reader_seam(self.e, [terminal.withheld_page("table_failure"), healthy_page()],
                    {"tika_url": "http://127.0.0.1:9998/tika"}, cleanup=cleanup, read_error=primary, read_stage=stage)
                self.observe_failure(seam, primary, cleanup, finish_reached=False)
                self.assertLess(seam.events.index("emit_veto"), seam.events.index("late_read_error"))
                if cleanup is not None:
                    self.assertTrue(cleanup.__context__ is primary)

    def test_emit_handoff_failure_keeps_latch_before_page_update(self):
        for close_fails in (False, True):
            primary = UnprintableError(terminal.CANARY)
            cleanup = UnprintableError(terminal.CANARY) if close_fails else None
            seam = reader_seam(self.e, [terminal.withheld_page("cell_cap")], terminal.fault_options("cell_cap"),
                               cleanup=cleanup, emit_error=primary)
            self.observe_failure(seam, primary, cleanup, finish_reached=False)
            self.assertIn("emit_handoff_error", seam.events)

    def test_multiple_exitstack_callbacks_run_and_preserve_primary_chain(self):
        primary, extra, cleanup = (UnprintableError(terminal.CANARY) for _ in range(3))
        seam = reader_seam(self.e, [review.PageRecords(""), terminal.withheld_page("cell_cap")],
            terminal.fault_options("cell_cap"), cleanup=cleanup, finish_error=primary, extra_cleanup=extra)
        self.observe_failure(seam, primary, cleanup)
        self.assertEqual(seam.extra_close_attempts, 1)
        self.assertEqual(len(seam.inner_opens), 1)
        self.assertLess(seam.events.index("extra_close_refused"), seam.events.index("close_refused"))
        self.assertTrue(cleanup.__context__ is extra)
        self.assertTrue(extra.__context__ is primary)

    def test_primary_cancellation_survives_cleanup_exception(self):
        for close_fails in (False, True):
            primary = Cancellation(terminal.CANARY)
            prior = ValueError("authored prior cause")
            primary.__cause__ = prior
            cleanup = UnprintableError(terminal.CANARY) if close_fails else None
            seam = reader_seam(self.e, [terminal.withheld_page("cell_cap")], terminal.fault_options("cell_cap"),
                               cleanup=cleanup, finish_error=primary)
            with self.assertRaises(Cancellation) as caught:
                seam.run()
            self.assertTrue(caught.exception is primary)
            self.assertTrue(seam.reader_errors[0] is primary and seam.dispatch_errors[0] is primary)
            self.assertTrue(primary.__cause__ is prior)
            if cleanup is not None:
                self.assertTrue(primary.__context__ is cleanup)
            self.assertEqual(seam.calls, ["pymupdf"])
            self.assertEqual(seam.close_attempts, 1)
            self.assertIn("emit_veto", seam.events)

    def test_fatal_cleanup_is_not_hidden_by_veto_carrier(self):
        for body_fails in (False, True):
            fatal = Cancellation(terminal.CANARY)
            primary = UnprintableError(terminal.CANARY) if body_fails else None
            seam = reader_seam(self.e, [terminal.withheld_page("cell_cap")], terminal.fault_options("cell_cap"),
                               cleanup=fatal, finish_error=primary)
            with self.assertRaises(Cancellation) as caught:
                seam.run()
            self.assertTrue(caught.exception is fatal)
            self.assertTrue(seam.reader_errors[0] is fatal and seam.dispatch_errors[0] is fatal)
            if primary is not None:
                self.assertTrue(fatal.__context__ is primary)
            self.assertEqual(seam.calls, ["pymupdf"])
            self.assertEqual(seam.close_attempts, 1)

    def test_ordinary_pre_veto_close_fault_preserves_pypdf_and_tika_fallback(self):
        for text_present in (False, True):
            for tika in (False, True):
                cleanup = UnprintableError(terminal.CANARY)
                seam = reader_seam(self.e, [healthy_page() if text_present else review.PageRecords("")],
                    {"tika_url": "http://127.0.0.1:9998/tika" if tika else ""}, cleanup=cleanup,
                    alternate="" if tika else terminal.ALTERNATE_TEXT)
                result = seam.run()
                self.assertEqual(seam.output.fallback_veto, None)
                self.assertTrue(seam.reader_errors[0] is cleanup)
                self.assertEqual(seam.dispatch_errors, [])
                self.assertEqual(seam.calls, ["pymupdf", "pypdf", "pypdf_open_records"] +
                                 (["tika_authored_transport"] if tika else []))
                self.assertEqual(result.parser, "authored-tika-transport" if tika else "pypdf")
                self.assertEqual(result.status, "partial" if tika else "ok")
                self.assertNotIn(terminal.CANARY, json.dumps(self.e.asdict(result)))
                self.assertNotIn(terminal.CANARY, json.dumps(result.to_dict()))

    def test_untrusted_metadata_is_not_adopted_as_established_veto(self):
        cleanup = UnprintableError(terminal.CANARY)
        seam = reader_seam(self.e, [healthy_page()], cleanup=cleanup,
            raw_metadata={"pdf_fallback_veto": "incomplete_table_context", "ownership": "unknown"},
            alternate=terminal.ALTERNATE_TEXT)
        result = seam.run()
        self.assertIsNone(seam.output.fallback_veto)
        self.assertIsNone(seam.finished[0].metadata["pdf_fallback_veto"])
        self.assertEqual(result.parser, "pypdf")
        self.assertTrue(seam.reader_errors[0] is cleanup)
        self.assertEqual(seam.dispatch_errors, [])

    def test_pypdf_only_close_fault_keeps_opt_in_tika(self):
        cleanup = UnprintableError(terminal.CANARY)
        seam = reader_seam(self.e, [], {"pdf_parser": "pypdf", "tika_url": "http://127.0.0.1:9998/tika"},
                           pypdf_cleanup=cleanup, alternate=terminal.ALTERNATE_TEXT)
        result = seam.run()
        self.assertEqual(seam.calls, ["pypdf", "pypdf_open_records", "tika_authored_transport"])
        self.assertEqual(seam.alternate_close_attempts, 1)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.metadata["parser_attempts"], [{"parser": "pypdf", "status": "failed", "reason": "UnprintableError"}])
        self.assertEqual(seam.dispatch_errors, [])

    @unittest.skipIf(os.name != "nt", "Windows SOURCE no-op OS-limits path; no POSIX/native admission")
    def test_worker_error_serialization_after_actual_dispatcher_veto_exit(self):
        worker = review.peer.load_source(review.peer.WORKER, "document_worker_parser_source_test")
        cleanup = UnprintableError(terminal.CANARY)
        seam = reader_seam(self.e, [terminal.withheld_page("table_failure")],
                           {"tika_url": "http://127.0.0.1:9998/tika"}, cleanup=cleanup)
        sink = types.SimpleNamespace(buffer=io.BytesIO())
        request = json.dumps({"path": "fixture.pdf", "options": {}}).encode()
        own_sys = types.SimpleNamespace(stdin=types.SimpleNamespace(buffer=io.BytesIO(request)), stdout=sink)

        def extract(path, options):
            return seam.run()  # actual dispatcher/readers, not a manufactured failure payload

        run = review.clone_function(worker.main, sys=own_sys, extract_document=extract)
        self.assertEqual(run(), 2)
        payload = json.loads(sink.buffer.getvalue())
        self.assertEqual(payload, {"ok": False, "error": "_PdfPrivacyVetoError"})
        self.assertNotIn(terminal.CANARY, sink.buffer.getvalue().decode())
        self.assertNotIn("document", payload)
        self.assertEqual(seam.calls, ["pymupdf"])
        error = seam.dispatch_errors[0]
        self.assertTrue(error is seam.reader_errors[0])
        self.assertTrue(error.primary_error is cleanup and error.cleanup_error is cleanup)
        self.assertEqual(error.diagnostics["ownership"], "unknown")
        self.assertLess(seam.events.index("finish_return"), seam.events.index("close_refused"))

    def test_new_cleanup_policy_invalidates_previous_3_1_2_identity(self):
        e = self.e
        self.assertEqual(e.EXTRACTOR_VERSION, "3.1.8")
        self.assertEqual(e.SECRET_POLICY_VERSION, "3.0.0")
        previous = review.clone_function(e.extraction_options_fingerprint, EXTRACTOR_VERSION="3.1.2")
        path, options = Path("fixture.pdf"), {"ocr": False}
        current = e.extraction_options_fingerprint(path, options)
        self.assertNotEqual(current, previous(path, options))
        self.assertEqual(current, e.extraction_options_fingerprint(path, e.effective_extraction_options(options)))
        self.assertEqual(e.ExtractedDocument("none", "application/pdf", "Fixture", []).to_dict()["extractor_version"], "3.1.8")


def packet_suite():
    return unittest.TestSuite([terminal.packet_suite(),
                              unittest.defaultTestLoader.loadTestsFromTestCase(VetoCleanupSourceTests)])


def metadata_preflight():
    """Import/compile/producer-order roster and recursive globals, no case calls."""
    old_ids = terminal.metadata_preflight()
    cases = unittest.defaultTestLoader.loadTestsFromTestCase(VetoCleanupSourceTests)
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
    assert OBSERVATIONS == terminal.OBSERVATIONS == []
    return ids


if __name__ == "__main__" and "devtools_case_started" in globals():
    peer_tree = ast.parse(read_source(review.PEER_PATH))
    reporter = next(n for n in ast.walk(peer_tree) if isinstance(n, ast.ClassDef) and n.name == "PacketResult")
    exec(compile(ast.Module(body=[reporter], type_ignores=[]), str(review.PEER_PATH), "exec", dont_inherit=True), globals())
    result = PacketResult()
    packet_suite().run(result)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": result.rows,
        "terminal_compositions": terminal.OBSERVATIONS, "cleanup_compositions": OBSERVATIONS,
        "qualification": "SOURCE actual owner/emitter/finish/readers/dispatcher and worker error serialization; authored records/open/cleanup/transport; old41 fresh plus additive; genuine engines/SDK/SQL/native NOT_RUN"}, separators=(",", ":")))
    raise SystemExit(0 if result.wasSuccessful() else 1)
elif __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(packet_suite())
    raise SystemExit(0 if result.wasSuccessful() else 1)
