"""Дополнение SOURCE: реальные тела parser/worker, авторские records/transport.

Не импортирует PDF/OCR engines и native suite. У caller исполняется точный AST
суффикс ПОСЛЕ optional imports; fitz/open и alternate reader — авторские records,
не SDK/authority stand-ins. Capture interleavings детерминированы, без процессов
и потоков. Whole-module helpers/старые SOURCE controls поставляются этим tree.
"""
from __future__ import annotations

import ast
import builtins
import dis
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import types
import unittest

ROOT = Path(__file__).absolute().parents[1]
INPUTS = globals().get("DEVTOOLS_INPUTS", {})
PEER_PATH = Path(INPUTS.get("test_document_parser_pdf_ocr.py", Path(__file__).with_name("test_document_parser_pdf_ocr.py")))
NATIVE_PATH = Path(INPUTS.get("test_p2_g3_native.py", Path(__file__).with_name("test_p2_g3_native.py")))
COMPONENT_PATH = Path(INPUTS.get("test_document_parser_components.py", Path(__file__).with_name("test_document_parser_components.py")))


def read_source(path):
    return devtools_read_bound(str(path)) if "devtools_read_bound" in globals() else path.read_bytes()


# Exact whole-module load; no ancestor __init__, native test import or .pyc probe.
_spec = importlib.util.spec_from_file_location("parser_review_legacy_source", str(PEER_PATH))
peer = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = peer
for _name in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound"):
    if _name in globals():
        peer.__dict__[_name] = globals()[_name]
exec(compile(read_source(PEER_PATH), str(PEER_PATH), "exec", dont_inherit=True), peer.__dict__)


def clone_function(function, **bindings):
    """Own globals for a source seam; never patch the loaded product module."""
    namespace = {**function.__globals__, **bindings}
    result = types.FunctionType(function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    return result


def caller_body(e, document, alternate=None):
    """Exact parser suffix including real admission, emission and finish calls.

    The first two statements only perform optional pymupdf/fitz imports. They
    remain NOT_RUN, not an import success. No AST expressions in the executable
    suffix are changed. Document/alternate contain primitive authored records.
    """
    tree = ast.parse(read_source(peer.EXTRACTOR))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_extract_pdf_pymupdf")
    start = next(i for i, n in enumerate(function.body) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "o" for t in n.targets))
    assert start == 1 and isinstance(function.body[0], ast.Try)
    selected = ast.FunctionDef(name=function.name, args=function.args, body=function.body[start:],
                               decorator_list=[], returns=function.returns, type_params=function.type_params)
    selected = ast.fix_missing_locations(ast.copy_location(selected, function))
    namespace = {**e.__dict__, "fitz": types.SimpleNamespace(open=lambda path: document, VersionBind="AUTHORED_RECORDS_NOT_ENGINE")}
    if alternate is not None:
        namespace["_open_pypdf"] = alternate
    exec(compile(ast.Module(body=[selected], type_ignores=[]), str(peer.EXTRACTOR), "exec", dont_inherit=True), namespace)
    return namespace[function.name]


class TableRecord:
    """Author of documented table.rows/cells/extract records, no native methods."""
    def __init__(self, record):
        self.bbox = record["bbox"]
        self.rows = [types.SimpleNamespace(bbox=r["bbox"], cells=[c["bbox"] for c in r["cells"]]) for r in record["rows"]]
        self.values = [[c["text"] for c in r["cells"]] for r in record["rows"]]
        self.extractions = 0

    def extract(self):
        self.extractions += 1
        return self.values


class PageRecords:
    def __init__(self, text, blocks=(), tables=(), blocks_error=False, tables_error=False):
        self.text, self.blocks, self.tables = text, list(blocks), list(tables)
        self.blocks_error, self.tables_error = blocks_error, tables_error
        self.calls = []

    def get_text(self, mode, *, sort):
        self.calls.append((mode, sort))
        if mode == "blocks" and self.blocks_error:
            raise ValueError("authored block-read refusal")
        return self.text if mode == "text" else self.blocks

    def find_tables(self, *, strategy):
        self.calls.append(("tables", strategy))
        if self.tables_error:
            raise ValueError("authored table-read refusal")
        return types.SimpleNamespace(tables=self.tables)


class DocumentRecords:
    needs_pass = False
    metadata = {"title": "Authored SOURCE records"}

    def __init__(self, pages):
        self.pages, self.closed = pages, False

    def __len__(self):
        return len(self.pages)

    def __getitem__(self, number):
        return self.pages[number]

    def close(self):
        self.closed = True


def secret_table():
    record = peer.sample_table()
    record["rows"][0]["cells"][1]["text"] = "Password"
    record["rows"][1]["cells"][1]["text"] = "OrdinaryFixtureValue9988"
    return record


def split_blocks():
    return [(60, 30, 110, 50, "Password", 1, 0),
            (60, 50, 110, 70, "OrdinaryFixtureValue9988", 2, 0),
            (0, 20, 140, 90, "overlap OrdinaryFixtureValue9988", 3, 0)]


def capture_seam(e, *, stdout=b"abcdefgh", stderr=b"", read_error=False,
                 wait_error=False, live_reader=False, primary=None, faults=None):
    """Actual _run_ocr_command + authored terminal-turn producer/observer.

    poll releases final read after the loop's first ledger check. Trace observes
    decisions/ownership records only; it is NOT OS/thread/engine cleanup proof.
    faults selects an exact stage (or stage, occurrence), never a real process.
    """
    trace, workers, retained = [], [], []
    faults, counts = dict(faults or {}), {}

    def refuse(stage):
        counts[stage] = counts.get(stage, 0) + 1
        error = faults.get((stage, counts[stage]), faults.get(stage))
        if error is not None:
            raise error

    class Stream:
        def __init__(self, name, data):
            self.name, self.data, self.closed, self.reads = name, data, False, 0

        def read(self, count):
            self.reads += 1
            trace.append("read_" + self.name)
            refuse("read_" + self.name)
            if self.data:
                result, self.data = self.data, b""
                return result
            if read_error and self.name == "stdout":
                raise OSError("authored final read refusal")
            return b""

        def close(self):
            trace.append("close_" + self.name)
            refuse("close_" + self.name)
            self.closed = True
            refuse("close_after_" + self.name)

    class ThreadRecord:
        def __init__(self, *, target, args, daemon, name):
            self.role = "stdout" if args[0] == 0 else "stderr"
            trace.append("thread_" + self.role)
            refuse("thread_" + self.role)
            self.target, self.args, self.ident, self.done = target, args, None, False
            workers.append(self)

        def start(self):
            trace.append("start_" + self.role)
            refuse("start_" + self.role)
            self.ident = 1
            refuse("start_after_" + self.role)

        def finish(self):
            if self.ident is not None and not self.done:
                self.target(*self.args)
                self.done = True

        def is_alive(self):
            trace.append("alive_" + self.role)
            refuse("alive_" + self.role)
            return self.ident is not None and (not self.done or live_reader)

        def join(self, *, timeout):
            trace.append("join")
            trace.append("join_" + self.role)
            refuse("join_" + self.role)
            self.finish()

    class ProcessRecord:
        returncode = 0

        def __init__(self):
            self.stdout, self.stderr = Stream("stdout", stdout), Stream("stderr", stderr)
            self.polls = self.waits = self.kills = 0

        def poll(self):
            self.polls += 1
            trace.append("poll")
            refuse("poll")
            for worker in workers:
                worker.finish()
            if primary is not None and self.polls == 1:
                raise primary
            # A retained-live negative is stopped by the authored clock below.
            return self.returncode

        def kill(self):
            self.kills += 1
            trace.append("kill")
            refuse("kill")

        def wait(self, *, timeout):
            self.waits += 1
            trace.append("wait")
            refuse("wait")
            if wait_error:
                raise OSError("authored reap unknown")
            return self.returncode

    process = ProcessRecord()
    launches = []

    def popen(cmd, **kwargs):
        launches.append((cmd, kwargs))
        trace.append("popen")
        return process

    def event():
        trace.append("event")
        refuse("event")
        return threading.Event()

    ticks = [0]

    def monotonic():
        ticks[0] += 1
        refuse("clock")
        return 100 if live_reader and ticks[0] >= 3 else 0

    transport = types.SimpleNamespace(Popen=popen, PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired)
    threads = types.SimpleNamespace(Event=event, Thread=ThreadRecord)
    clock = types.SimpleNamespace(monotonic=monotonic, sleep=lambda seconds: None)
    function = clone_function(e._run_ocr_command, subprocess=transport, threading=threads, time=clock, _OCR_RETAINED=retained)
    return types.SimpleNamespace(call=function, trace=trace, process=process, workers=workers, retained=retained,
                                 launches=launches, counts=counts)


class ReviewBoundarySourceTests(unittest.TestCase):
    def setUp(self):
        self.e = peer.load_source(peer.EXTRACTOR, "document_extractors")
        self.o = self.e.effective_extraction_options({"pdf_native_fallback": False})

    def extract_records(self, pages, options=None, alternate=None):
        options = self.e.effective_extraction_options({**self.o, **(options or {})})
        document = DocumentRecords(pages)
        body = caller_body(self.e, document, alternate)
        result = body(Path("fixture.pdf"), options["max_units"], options["max_pages"], options["ocr"],
                      options["ocr_language"], options["ocr_min_native_chars"], options=options)
        self.assertTrue(document.closed)
        return result.to_dict()

    def assert_withheld(self, payload):
        self.assertNotIn("OrdinaryFixtureValue9988", json.dumps(payload))
        self.assertNotEqual(payload["status"], "ok")
        self.assertEqual(payload["metadata"]["pages"][0]["structure"], "withheld_incomplete_table_context")
        self.assertTrue(payload["metadata"]["coverage"]["truncated"])
        self.assertFalse(payload["units"])

    def test_s1_cells_refusal_split_overlap_and_page_fallback(self):
        for blocks in (split_blocks(), []):
            table = TableRecord(secret_table())
            page = PageRecords("Books Password\nOrdinaryFixtureValue9988", blocks, [table])
            result = self.extract_records([page], {"max_cells": 2})
            self.assert_withheld(result)
            self.assertEqual(result["metadata"]["pages"][0]["tables_status"], "resource_limited")
            self.assertEqual(table.extractions, 0)  # no over-budget cell decoding

    def test_s1_tables_refusal_does_not_trust_retained_prefix(self):
        for blocks in (split_blocks(), []):
            safe, omitted = TableRecord(peer.sample_table()), TableRecord(secret_table())
            page = PageRecords("Books Password\nOrdinaryFixtureValue9988", blocks, [safe, omitted])
            result = self.extract_records([page], {"pdf_max_tables_per_page": 1})
            self.assert_withheld(result)
            self.assertEqual((safe.extractions, omitted.extractions), (1, 0))

    def test_s1_direct_emitter_refuses_budgets_before_raw_or_cell_output(self):
        for changes, tables in (({"max_cells": 2}, [secret_table()]),
                                ({"pdf_max_tables_per_page": 1}, [peer.sample_table(), secret_table()])):
            for blocks in (split_blocks(), []):
                options = self.e.effective_extraction_options(changes)
                out = self.e._PdfOutput(options)
                d = self.e._pdf_emit_page(out, 1, "Password\nOrdinaryFixtureValue9988", blocks, tables, options)
                self.assertEqual(d["structure"], "withheld_incomplete_table_context")
                self.assertEqual(out.units, [])
                self.assertEqual((out.cells, out.metadata_characters), (0, 0))
                self.assertTrue(out.truncated)

    def test_s1_healthy_tables_redact_context_but_preserve_nonsecret_content(self):
        secret = self.extract_records([PageRecords("Books Password OrdinaryFixtureValue9988",
                                     split_blocks(), [TableRecord(secret_table())])],
                                      {"max_cells": 4, "pdf_max_tables_per_page": 1})
        self.assertEqual(secret["status"], "ok")
        self.assertNotIn("OrdinaryFixtureValue9988", json.dumps(secret))
        cell = next(u for u in secret["units"] if u["anchor"].endswith("/row:2"))["metadata"]["cells"][1]
        self.assertEqual(cell["text"], "<REDACTED>")
        plain = self.extract_records([PageRecords("Books Count 42 NativeFact 73",
            [(0, 20, 140, 90, "NativeFact 73", 3, 0)], [TableRecord(peer.sample_table())])])
        self.assertEqual(plain["status"], "ok")
        self.assertIn("NativeFact 73", "\n".join(u["text"] for u in plain["units"]))
        self.assertIn("Books | 42", "\n".join(u["text"] for u in plain["units"]))
        self.assertFalse(plain["metadata"]["coverage"]["truncated"])

    def test_s1_table_api_failure_withholds_raw_without_poisoning_healthy_page(self):
        result = self.extract_records([
            PageRecords("Password\nOrdinaryFixtureValue9988", split_blocks(), tables_error=True),
            PageRecords("Healthy other page 73", [(0, 0, 40, 20, "Healthy other page 73", 0, 0)])])
        self.assertEqual(result["status"], "partial")
        self.assertNotIn("OrdinaryFixtureValue9988", json.dumps(result))
        self.assertEqual(result["metadata"]["pages"][0]["tables_status"], "failed_ValueError")
        self.assertEqual(result["metadata"]["pages"][0]["text_units"], 0)
        self.assertIn("Healthy other page 73", "\n".join(u["text"] for u in result["units"]))

    def test_l2_blocks_failure_keeps_native_fact_once_with_context_redaction(self):
        text = "OutsideFact 73\nName Password\nBooks OrdinaryFixtureValue9988\nTailFact 19"
        result = self.extract_records([PageRecords(text, tables=[TableRecord(secret_table())], blocks_error=True)])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["units"]), 1)
        unit = result["units"][0]
        self.assertEqual(unit["kind"], "page")
        self.assertEqual(unit["text"].count("OutsideFact 73"), 1)
        self.assertEqual(unit["text"].count("Name"), 1)
        self.assertIn("TailFact 19", unit["text"])
        self.assertNotIn("OrdinaryFixtureValue9988", json.dumps(result))
        self.assertIn("<REDACTED>", unit["text"])
        self.assertNotIn("bbox", unit["locator"])
        self.assertEqual(unit["metadata"]["structure_fallback"], "blocks_unavailable_table_structure_omitted")
        self.assertEqual(result["metadata"]["pages"][0]["blocks_status"], "failed_ValueError")
        self.assertTrue(result["metadata"]["pages"][0]["table_structure_omitted"])

    def test_l2_plain_fallback_partial_and_compound_structural_refusal(self):
        result = self.extract_records([PageRecords("OutsideFact 73", blocks_error=True)])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["units"][0]["text"], "OutsideFact 73")
        compound = self.extract_records([PageRecords("OutsideFact 73 Password\nOrdinaryFixtureValue9988",
            tables=[TableRecord(secret_table())], blocks_error=True)], {"max_cells": 2})
        self.assert_withheld(compound)
        self.assertEqual(compound["metadata"]["pages"][0]["blocks_status"], "failed_ValueError")

    def test_l1_ocr_false_threshold_changes_fingerprint_and_native_selection(self):
        def one(minimum, native="Short 73", enabled=True):
            observed = []
            def alternate(path, stack):
                observed.append(str(path))
                return types.SimpleNamespace(pages=[types.SimpleNamespace(extract_text=lambda: native + " More complete 91")])
            o = {"ocr": False, "ocr_min_native_chars": minimum, "pdf_native_fallback": enabled}
            result = self.extract_records([PageRecords(native, [(0, 0, 40, 20, native, 0, 0)])], o, alternate)
            return result, observed, self.e.extraction_options_fingerprint(Path("fixture.pdf"), o)
        low, low_calls, low_fp = one(0)
        high, high_calls, high_fp = one(40)
        self.assertNotEqual(low_fp, high_fp)
        self.assertEqual(low_calls, [])
        self.assertEqual(high_calls, ["fixture.pdf"])
        self.assertEqual(low["metadata"]["pages"][0]["origin"], "native")
        self.assertEqual(high["metadata"]["pages"][0]["origin"], "pypdf")
        self.assertIn("More complete 91", high["units"][0]["text"])
        self.assertEqual(one(0, enabled=False)[0]["units"], one(40, enabled=False)[0]["units"])
        long_text = "Long native fact 73 " * 4
        self.assertEqual(one(0, long_text)[0]["units"], one(40, long_text)[0]["units"])
        self.assertEqual(one(40, long_text)[1], [])

    def test_l1_effective_inverse_and_nonextraction_axes_unchanged(self):
        pdf, e = Path("fixture.pdf"), self.e
        options = {"ocr": False, "ocr_min_native_chars": -5}
        fp = e.extraction_options_fingerprint(pdf, options)
        self.assertEqual(fp, e.extraction_options_fingerprint(pdf, e.effective_extraction_options(options)))
        self.assertEqual(fp, e.extraction_options_fingerprint(pdf, {**options, "ocr_min_native_chars": 0}))
        for changes in ({"ocr_dpi": 300, "ocr_language": "rus"}, {"external_timeout": 1},
                        {"chunk_chars": 900, "embedding_model": "not-an-extraction-axis"}):
            self.assertEqual(fp, e.extraction_options_fingerprint(pdf, {**options, **changes}))
        self.assertEqual(e.extraction_options_fingerprint(Path("fixture.txt"), options),
                         e.extraction_options_fingerprint(Path("fixture.txt"), {**options, "ocr_min_native_chars": 40}))

    def test_n1_source_label_matches_tables_then_parser_blocks(self):
        options = {"pdf_reading_order": "source"}
        result = self.extract_records([PageRecords("Before table Books Count 42 After table", [
            (0, 80, 40, 90, "After table", 9, 0), (0, 0, 40, 10, "Before table", 4, 0)],
            [TableRecord(peer.sample_table())])], options)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([u["kind"] for u in result["units"]], ["page", "table", "table_row", "table_row", "text_block", "text_block"])
        self.assertEqual([u["anchor"] for u in result["units"][-2:]], ["page:1/block:9", "page:1/block:4"])
        self.assertEqual({u["metadata"]["reading_order_method"] for u in result["units"]}, {"parser_tables_then_blocks"})

    def test_l3_final_chunk_stdout_and_stderr_overflow_refused(self):
        for kwargs in ({"stdout": b"abcdefghi"}, {"stderr": b"x" * 16_385},
                       {"stdout": b"abcdefghi", "read_error": True}):
            seam = capture_seam(self.e, **kwargs)
            with self.assertRaisesRegex(RuntimeError, "^ocr_capture_limit_or_read_failure$"):
                seam.call(["authored-no-process"], 5, 8)
            self.assertEqual(seam.process.waits, 1)
            self.assertTrue(seam.process.stdout.closed and seam.process.stderr.closed)
            self.assertEqual(seam.trace.count("join"), 2)
            self.assertEqual(seam.retained, [])
            self.assertEqual(len(seam.launches), 1)

    def test_l3_final_read_error_rejects_otherwise_valid_prefix(self):
        seam = capture_seam(self.e, read_error=True)
        with self.assertRaisesRegex(RuntimeError, "^ocr_capture_limit_or_read_failure$"):
            seam.call(["authored-no-process"], 5, 8)
        self.assertEqual(seam.process.stdout.reads, 2)
        self.assertEqual(seam.retained, [])
        self.assertTrue(seam.process.stdout.closed and seam.process.stderr.closed)

    def test_l3_healthy_exact_bounds_return_after_join_and_close(self):
        seam = capture_seam(self.e, stderr=b"x" * 16_384)
        self.assertEqual(seam.call(["authored-no-process"], 5, 8), (0, b"abcdefgh"))
        self.assertEqual(seam.process.waits, 1)
        self.assertEqual(seam.trace[-2:], ["close_stdout", "close_stderr"])
        self.assertEqual(seam.trace.count("join"), 2)
        self.assertTrue(all(t.done for t in seam.workers))
        self.assertEqual(seam.retained, [])
        self.assertEqual(seam.launches[0][1]["shell"], False)

    def test_l3_primary_identity_survives_capture_and_cleanup_unknown(self):
        class Primary(BaseException):
            pass
        primary = Primary("authored cancellation")
        seam = capture_seam(self.e, stdout=b"abcdefghi", read_error=True, wait_error=True, primary=primary)
        with self.assertRaises(Primary) as caught:
            seam.call(["authored-no-process"], 5, 8)
        self.assertIs(caught.exception, primary)
        self.assertEqual(len(seam.retained), 1)
        self.assertIs(seam.retained[0][0], seam.process)
        with self.assertRaisesRegex(RuntimeError, "^ocr_previous_ownership_unknown$"):
            seam.call(["authored-no-process"], 5, 8)
        self.assertEqual(len(seam.launches), 1)

    def test_l3_unknown_or_live_reader_never_releases_or_admits_replacement(self):
        for kwargs in ({"wait_error": True}, {"live_reader": True}):
            seam = capture_seam(self.e, **kwargs)
            expected = subprocess.TimeoutExpired if kwargs.get("live_reader") else RuntimeError
            with self.assertRaises(expected):
                seam.call(["authored-no-process"], 5, 8)
            self.assertEqual(len(seam.retained), 1)
            if kwargs.get("live_reader"):
                self.assertFalse(seam.process.stdout.closed)
            with self.assertRaisesRegex(RuntimeError, "^ocr_previous_ownership_unknown$"):
                seam.call(["authored-no-process"], 5, 8)
            self.assertEqual(len(seam.launches), 1)

    def test_ocr01_absent_body_cleanup_fatal_exact_and_full_drain(self):
        class Cancel(BaseException):
            def __str__(self):
                raise AssertionError("foreign exception text must not be formatted")
            __repr__ = __str__
        for stage in ("wait", "join_stdout", "close_stdout"):
            for kind in (Cancel, SystemExit, KeyboardInterrupt):
                fatal = kind("PrivateFixtureCanary9988")
                cause = ValueError("authored explicit cause")
                fatal.__cause__ = cause
                seam = capture_seam(self.e, faults={stage: fatal})
                with self.assertRaises(BaseException) as caught:
                    seam.call(["authored-no-process"], 5, 8)
                self.assertIs(caught.exception, fatal)
                self.assertIs(fatal.__cause__, cause)
                self.assertIsNone(fatal._ocr_primary_error)
                self.assertIs(fatal._ocr_cleanup_errors[0], fatal)
                self.assertEqual(fatal._ocr_diagnostics, {"cleanup": "unknown", "ownership": "unknown"})
                self.assertNotIn("PrivateFixtureCanary9988", json.dumps(fatal._ocr_diagnostics))
                self.assertEqual(seam.process.waits, 1)
                self.assertEqual(seam.trace.count("join"), 2)
                self.assertIn("close_stdout", seam.trace)
                self.assertIn("close_stderr", seam.trace)
                self.assertTrue(seam.process.stderr.closed)
                self.assertEqual(len(seam.retained), 1)
                self.assertIs(seam.retained[0][0], seam.process)
                self.assertEqual([id(t) for t in seam.retained[0][1]], [id(t) for t in seam.workers])
                with self.assertRaisesRegex(RuntimeError, "^ocr_previous_ownership_unknown$"):
                    seam.call(["authored-no-process"], 5, 8)
                self.assertEqual(len(seam.launches), 1)

    def test_ocr01_body_priority_private_ledger_context_and_explicit_causes(self):
        class Cancel(BaseException):
            pass
        for body_kind in (OSError, Cancel):
            for cleanup_kind in (OSError, SystemExit):
                body, cleanup = body_kind("authored body"), cleanup_kind("authored wait")
                tail = OSError("authored final close")
                body_cause, cleanup_cause = ValueError("body cause"), ValueError("cleanup cause")
                body.__cause__, cleanup.__cause__ = body_cause, cleanup_cause
                seam = capture_seam(self.e, primary=body, faults={"wait": cleanup, "close_stderr": tail})
                selected = body if not isinstance(body, Exception) or isinstance(cleanup, Exception) else cleanup
                with self.assertRaises(BaseException) as caught:
                    seam.call(["authored-no-process"], 5, 8)
                self.assertIs(caught.exception, selected)
                self.assertIs(selected._ocr_primary_error, body)
                self.assertEqual([id(e) for e in selected._ocr_cleanup_errors], [id(cleanup), id(tail)])
                self.assertEqual([stage for stage, _ in selected._ocr_observed_errors],
                                 ["child_reap_unknown", "pipe_close_unknown"])
                expected = [selected, tail, cleanup if selected is body else body]
                actual, current = [], selected
                while current is not None and len(actual) <= len(expected):
                    actual.append(id(current))
                    current = current.__context__
                self.assertEqual(actual, [id(e) for e in expected])
                self.assertIsNone(current)
                self.assertIs(body.__cause__, body_cause)
                self.assertIs(cleanup.__cause__, cleanup_cause)
                self.assertEqual(seam.trace.count("join"), 2)
                self.assertEqual(seam.trace[-2:], ["close_stdout", "close_stderr"])
                self.assertEqual(len(seam.retained), 1)

    def test_ocr01_reader_fatal_not_a_string_and_body_fatal_still_wins(self):
        class Cancel(BaseException):
            pass
        for body in (None, OSError("authored body"), Cancel("authored body fatal")):
            reader, cleanup = SystemExit("authored pipe fatal"), KeyboardInterrupt("authored wait fatal")
            seam = capture_seam(self.e, primary=body,
                                faults={("read_stdout", 2): reader, "wait": cleanup})
            with self.assertRaises(BaseException) as caught:
                seam.call(["authored-no-process"], 5, 8)
            selected = body if body is not None and not isinstance(body, Exception) else reader
            self.assertIs(caught.exception, selected)
            self.assertIs(selected._ocr_reader_errors[0], reader)
            self.assertIs(selected._ocr_cleanup_errors[0], cleanup)
            self.assertEqual([stage for stage, _ in selected._ocr_observed_errors],
                             ["pipe_read_failed", "child_reap_unknown"])
            self.assertEqual(seam.trace.count("join"), 2)
            self.assertTrue(seam.process.stdout.closed and seam.process.stderr.closed)
            self.assertEqual(len(seam.retained), 1)
            with self.assertRaisesRegex(RuntimeError, "^ocr_previous_ownership_unknown$"):
                seam.call(["authored-no-process"], 5, 8)
            self.assertEqual(len(seam.launches), 1)

    def test_ocr01_image_caller_rethrows_reader_fatal_but_keeps_ordinary_failure(self):
        for error in (SystemExit("authored pipe fatal"), OSError("authored read failure")):
            seam = capture_seam(self.e, faults={("read_stdout", 2): error})
            image = clone_function(self.e.extract_image_ocr, _run_ocr_command=seam.call)
            if not isinstance(error, Exception):
                with self.assertRaises(BaseException) as caught:
                    image(Path("authored.png"), 1000, "eng", 5)
                self.assertIs(caught.exception, error)
                self.assertEqual(error._ocr_diagnostics, {"cleanup": "complete", "ownership": "complete"})
                self.assertIs(error._ocr_reader_errors[0], error)
            else:
                result = image(Path("authored.png"), 1000, "eng", 5)
                self.assertEqual(result.status, "failed")
                self.assertFalse(result.units)
                self.assertEqual(result.metadata["ocr_status"], "RuntimeError")
            self.assertTrue(seam.process.stdout.closed and seam.process.stderr.closed)
            self.assertEqual(seam.retained, [])

    def test_ocr02_preacquire_event_or_clock_refusal_launches_zero(self):
        for stage in ("event", ("clock", 1)):
            for kind in (OSError, SystemExit):
                error = kind("authored preparation refusal")
                seam = capture_seam(self.e, faults={stage: error})
                with self.assertRaises(BaseException) as caught:
                    seam.call(["authored-no-process"], 5, 8)
                self.assertIs(caught.exception, error)
                self.assertEqual(seam.launches, [])
                self.assertEqual(seam.workers, [])
                self.assertEqual(seam.retained, [])
                self.assertNotIn("popen", seam.trace)
                self.assertEqual((seam.process.kills, seam.process.waits), (0, 0))

    def test_ocr02_thread_constructor_start_faults_own_child_and_pipes(self):
        for stage in ("thread_stdout", "thread_stderr", "start_stdout", "start_stderr",
                      "start_after_stdout", "start_after_stderr"):
            for unknown in (False, True):
                body = OSError("authored startup refusal")
                faults = {stage: body}
                if unknown:
                    faults[("poll", 1)] = OSError("authored cleanup query refusal")
                seam = capture_seam(self.e, faults=faults)
                with self.assertRaises(BaseException) as caught:
                    seam.call(["authored-no-process"], 5, 8)
                self.assertIs(caught.exception, body)
                self.assertEqual(len(seam.launches), 1)
                self.assertEqual(seam.process.waits, 1)
                self.assertEqual(seam.process.kills, 1 if unknown else 0)
                self.assertEqual(seam.trace.count("join"), sum(t.ident is not None for t in seam.workers))
                self.assertTrue(seam.process.stdout.closed and seam.process.stderr.closed)
                self.assertEqual(body._ocr_diagnostics["ownership"], "unknown" if unknown else "complete")
                if unknown:
                    self.assertIs(seam.retained[0][0], seam.process)
                    with self.assertRaisesRegex(RuntimeError, "^ocr_previous_ownership_unknown$"):
                        seam.call(["authored-no-process"], 5, 8)
                    self.assertEqual(len(seam.launches), 1)
                else:
                    self.assertEqual(seam.retained, [])

    def test_ocr02_cleanup_clock_poll_kill_refusals_do_not_skip_wait_or_drain(self):
        for stage in (("clock", 3), ("clock", 4), ("clock", 5), ("poll", 2), "kill"):
            for kind in (OSError, SystemExit):
                error = kind("authored cleanup refusal")
                faults = {stage: error}
                if stage == "kill":
                    faults[("poll", 2)] = OSError("authored unknown child state")
                seam = capture_seam(self.e, faults=faults)
                with self.assertRaises(BaseException) as caught:
                    seam.call(["authored-no-process"], 5, 8)
                if isinstance(error, Exception):
                    self.assertIs(type(caught.exception), RuntimeError)
                    self.assertEqual(caught.exception.args, ("ocr_cleanup_ownership_unknown",))
                else:
                    self.assertIs(caught.exception, error)
                self.assertTrue(any(e is error for e in caught.exception._ocr_cleanup_errors))
                self.assertEqual(seam.process.waits, 1)
                self.assertEqual(seam.trace.count("join"), 2)
                self.assertTrue(seam.process.stdout.closed and seam.process.stderr.closed)
                if stage in (("poll", 2), "kill"):
                    self.assertEqual(seam.process.kills, 1)
                self.assertEqual(len(seam.retained), 1)
                with self.assertRaisesRegex(RuntimeError, "^ocr_previous_ownership_unknown$"):
                    seam.call(["authored-no-process"], 5, 8)
                self.assertEqual(len(seam.launches), 1)

    def test_ocr02_reader_state_refusal_retains_pipes_but_attempts_other_join(self):
        for kind in (OSError, SystemExit):
            error = kind("authored reader state refusal")
            seam = capture_seam(self.e, faults={("alive_stdout", 2): error})
            with self.assertRaises(BaseException) as caught:
                seam.call(["authored-no-process"], 5, 8)
            if not isinstance(error, Exception):
                self.assertIs(caught.exception, error)
            else:
                self.assertEqual(caught.exception.args, ("ocr_cleanup_ownership_unknown",))
            self.assertIs(caught.exception._ocr_cleanup_errors[0], error)
            self.assertEqual(seam.process.waits, 1)
            self.assertEqual(seam.trace.count("join"), 2)
            self.assertIn("alive_stderr", seam.trace)
            self.assertNotIn("close_stdout", seam.trace)
            self.assertNotIn("close_stderr", seam.trace)
            self.assertFalse(seam.process.stdout.closed or seam.process.stderr.closed)
            self.assertEqual(len(seam.retained), 1)
            self.assertIs(seam.retained[0][0], seam.process)
            with self.assertRaisesRegex(RuntimeError, "^ocr_previous_ownership_unknown$"):
                seam.call(["authored-no-process"], 5, 8)
            self.assertEqual(len(seam.launches), 1)

    def test_ocr02_acquire_lifetime_and_separate_cleanup_guards_STATIC(self):
        tree = ast.parse(read_source(peer.EXTRACTOR))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run_ocr_command")
        owning = [n for n in function.body if isinstance(n, ast.Try) and n.finalbody]
        self.assertEqual(len(owning), 1)
        owning = owning[0]
        acquire = owning.body[0]
        self.assertIsInstance(acquire, ast.Assign)
        self.assertEqual(ast.unparse(acquire.targets[0]), "process")
        self.assertIsInstance(acquire.value, ast.Call)
        self.assertEqual(ast.unparse(acquire.value.func), "subprocess.Popen")
        event = next(n for n in function.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                     and ast.unparse(n.value.func) == "threading.Event")
        drain = next(n for n in function.body if isinstance(n, ast.FunctionDef) and n.name == "drain")
        self.assertLess(event.end_lineno, owning.lineno)
        self.assertLess(drain.end_lineno, owning.lineno)
        parents = {child: node for node in ast.walk(function) for child in ast.iter_child_nodes(node)}
        calls = [n for statement in owning.finalbody for n in ast.walk(statement)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in {"monotonic", "poll", "kill", "wait", "join", "is_alive", "close"}]
        self.assertEqual({n.func.attr for n in calls}, {"monotonic", "poll", "kill", "wait", "join", "is_alive", "close"})
        for call in calls:
            node, protected = call, False
            while node in parents and node is not owning:
                node = parents[node]
                if isinstance(node, ast.Try) and any(isinstance(h.type, ast.Name) and h.type.id == "BaseException"
                                                     for h in node.handlers):
                    protected = True
                    break
            self.assertTrue(protected, call.func.attr)

    def test_load03_both_loaders_have_bound_helper_before_consumer_STATIC(self):
        for path in (PEER_PATH, COMPONENT_PATH):
            tree = ast.parse(read_source(path))
            loader = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_source")
            pin = next(n for n in tree.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "FORMULAS_SHA256" for t in n.targets))
            self.assertEqual(ast.literal_eval(pin.value), "c27cf8175b9561d6028c1c69919196cadf8b2348f52ed88d6a148c3ca39078ac")
            guard = next(n for n in ast.walk(loader) if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                         and isinstance(n.test.left, ast.Call) and isinstance(n.test.left.func, ast.Attribute)
                         and n.test.left.func.attr == "hexdigest")
            self.assertIsInstance(guard.test.ops[0], ast.NotEq)
            self.assertIsInstance(guard.body[0], ast.Raise)
            self.assertEqual(ast.literal_eval(guard.body[0].exc.args[0]), "spreadsheet_helper_source_mismatch")
            execution = sorted((n for n in ast.walk(loader) if isinstance(n, ast.Call)
                                and isinstance(n.func, ast.Name) and n.func.id == "exec"), key=lambda n: n.lineno)
            self.assertEqual(len(execution), 2)
            self.assertLess(guard.end_lineno, execution[0].lineno)
            self.assertEqual(ast.unparse(execution[0].args[0].args[0]), "raw")
            self.assertEqual(ast.unparse(execution[1].args[0].args[0]), "read_source(path)")
            self.assertIn("devtools_read_bound", ast.unparse(next(n for n in tree.body
                          if isinstance(n, ast.FunctionDef) and n.name == "read_source")))
            self.assertNotIn("sys.path", ast.unparse(loader))

    def test_load03_wrong_helper_or_bound_read_refusal_precedes_any_module_exec(self):
        for path in (PEER_PATH, COMPONENT_PATH):
            tree = ast.parse(read_source(path))
            loader = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_source")
            for unreadable in (False, True):
                reads, executed, registry = [], [], {}
                refusal = OSError("authored bound read refusal")
                def read(path):
                    reads.append(path)
                    if unreadable:
                        raise refusal
                    return b"# wrong helper; must never execute\n"
                def forbidden(*args, **kwargs):
                    executed.append("forbidden import/compile/exec")
                    raise AssertionError("helper refusal must precede module execution")
                namespace = {**peer.__dict__, "read_source": read, "MODULES": registry,
                             "sys": types.SimpleNamespace(modules={}), "compile": forbidden, "exec": forbidden,
                             "importlib": types.SimpleNamespace(util=types.SimpleNamespace(spec_from_file_location=forbidden))}
                exec(compile(ast.Module(body=[loader], type_ignores=[]), str(path), "exec", dont_inherit=True), namespace)
                with self.assertRaises(OSError if unreadable else RuntimeError) as caught:
                    namespace["load_source"](peer.EXTRACTOR, "authored-loader-refusal")
                if unreadable:
                    self.assertIs(caught.exception, refusal)
                else:
                    self.assertEqual(caught.exception.args, ("spreadsheet_helper_source_mismatch",))
                self.assertEqual(reads, [peer.FORMULAS])
                self.assertEqual(registry, {})
                self.assertEqual(namespace["sys"].modules, {})
                self.assertEqual(executed, [])

    def test_load03_same_process_healthy_binding_keeps_outer_helper_identity(self):
        # This future SOURCE control is not a fresh-process/cold import proof.
        for number, path in enumerate((PEER_PATH, COMPONENT_PATH)):
            tree = ast.parse(read_source(path))
            loader = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_source")
            reads, before_path = [], list(sys.path)
            helper = sys.modules["spreadsheet_formulas"]
            def restore_helper(module, state):
                module.__dict__.clear()
                module.__dict__.update(state)
            self.addCleanup(restore_helper, helper, dict(helper.__dict__))
            def read(path):
                reads.append(path)
                return peer.read_source(path)
            name = "parser_review_healthy_loader_" + str(number)
            self.addCleanup(sys.modules.pop, name, None)
            namespace = {**peer.__dict__, "read_source": read, "MODULES": {}}
            exec(compile(ast.Module(body=[loader], type_ignores=[]), str(path), "exec", dont_inherit=True), namespace)
            module = namespace["load_source"](peer.EXTRACTOR, name)
            self.assertIs(sys.modules["spreadsheet_formulas"], helper)
            self.assertIs(module.evaluate_cells, helper.evaluate_cells)
            self.assertEqual(reads[:2], [peer.FORMULAS, peer.EXTRACTOR])
            self.assertEqual(sys.path, before_path)
            self.assertEqual(hashlib.sha256(peer.read_source(peer.FORMULAS)).hexdigest(), peer.FORMULAS_SHA256)

    def test_c1_actual_nested_boundary_worker_dispatch_options_keyword(self):
        tree = ast.parse(read_source(NATIVE_PATH))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "G3Tests")
        test = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "test_pdf_options_and_isolation")
        boundary = next(n for n in test.body if isinstance(n, ast.FunctionDef) and n.name == "pdf_boundary")
        namespace = {"self": types.SimpleNamespace(e=self.e, assertEqual=self.assertEqual)}
        exec(compile(ast.Module(body=[boundary], type_ignores=[]), str(NATIVE_PATH), "exec", dont_inherit=True), namespace)
        observed = []
        def transport(*args, **kwargs):
            observed.append((args, kwargs))
            return namespace["pdf_boundary"](*args, **kwargs)
        dispatch = clone_function(self.e.extract_pdf, _extract_pdf_pymupdf=transport)
        extract = clone_function(self.e.extract_document, extract_pdf=dispatch)
        worker = peer.load_source(peer.WORKER, "document_worker_parser_source_test")
        path = peer.fixture_root() / "review-boundary.pdf"
        path.write_bytes(b"%PDF-1.4\n% authored dispatch data, not parsed by an engine\n%%EOF\n")
        for language, minimum in (("eng", 0), ("rus", 40)):
            options = {"ocr": False, "ocr_language": language, "ocr_min_native_chars": minimum}
            sink = types.SimpleNamespace(buffer=io.BytesIO())
            streams = types.SimpleNamespace(stdin=types.SimpleNamespace(buffer=io.BytesIO(json.dumps(
                {"path": str(path), "options": options}).encode("utf-8"))), stdout=sink)
            main = clone_function(worker.main, sys=streams, extract_document=extract)
            self.assertEqual(main(), 0)
            response = json.loads(sink.buffer.getvalue())
            self.assertTrue(response["ok"])
            self.assertEqual(response["document"]["parser"], "pdf-boundary")
            self.assertEqual(response["document"]["units"][0]["text"], "Authored PDF native-dispatch text " + language)
            self.assertEqual(observed[-1][0][4:], (language, minimum))
            self.assertEqual(observed[-1][1], {"options": self.e.effective_extraction_options(options)})
        self.assertEqual(len(observed), 2)


def packet_suite():
    return unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(peer.ParserSourceTests),
                              unittest.defaultTestLoader.loadTestsFromTestCase(ReviewBoundarySourceTests)])


def metadata_preflight():
    """Collection/import/code closure only; no test or product body calls."""
    e = peer.load_source(peer.EXTRACTOR, "document_extractors")
    worker = peer.load_source(peer.WORKER, "document_worker_parser_source_test")
    suite = packet_suite()
    cases = [case for group in suite for case in group]
    ids = [case._testMethodName for case in cases]
    assert len(ids) == len(set(ids))
    def check(code, namespace):
        for instruction in dis.get_instructions(code):
            if instruction.opname == "LOAD_GLOBAL":
                name = instruction.argval
                assert name in namespace or hasattr(builtins, name), (code.co_qualname, name)
        for constant in code.co_consts:
            if isinstance(constant, types.CodeType):
                check(constant, namespace)
    for module in (peer, sys.modules[__name__], e, worker):
        for value in list(module.__dict__.values()):
            if isinstance(value, types.FunctionType) and value.__globals__ is module.__dict__:
                check(value.__code__, value.__globals__)
            elif isinstance(value, type) and value.__module__ == module.__name__:
                for method in value.__dict__.values():
                    if isinstance(method, types.FunctionType):
                        check(method.__code__, method.__globals__)
    # Bind the actual dynamically compiled suffix and capture body too, without
    # calling either. LOAD_GLOBAL closure includes nested drain callbacks.
    caller = caller_body(e, DocumentRecords([]))
    check(caller.__code__, caller.__globals__)
    capture = capture_seam(e).call
    check(capture.__code__, capture.__globals__)
    native_tree = ast.parse(read_source(NATIVE_PATH))
    native_class = next(n for n in native_tree.body if isinstance(n, ast.ClassDef) and n.name == "G3Tests")
    native_test = next(n for n in native_class.body if isinstance(n, ast.FunctionDef) and n.name == "test_pdf_options_and_isolation")
    boundary = next(n for n in native_test.body if isinstance(n, ast.FunctionDef) and n.name == "pdf_boundary")
    binding = {"self": types.SimpleNamespace(e=e, assertEqual=unittest.TestCase().assertEqual)}
    exec(compile(ast.Module(body=[boundary], type_ignores=[]), str(NATIVE_PATH), "exec", dont_inherit=True), binding)
    check(binding["pdf_boundary"].__code__, binding)
    return ids


if __name__ == "__main__" and "devtools_case_started" in globals():
    # Reuse the exact existing bounded unittest reporter, not a new framework.
    peer_tree = ast.parse(read_source(PEER_PATH))
    reporter = next(n for n in ast.walk(peer_tree) if isinstance(n, ast.ClassDef) and n.name == "PacketResult")
    exec(compile(ast.Module(body=[reporter], type_ignores=[]), str(PEER_PATH), "exec", dont_inherit=True), globals())
    result = PacketResult()
    packet_suite().run(result)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": result.rows,
        "qualification": "SOURCE: whole-module controls plus exact caller suffix and authored capture transport; one legacy STATIC; engines/native/SDK/SQLite NOT_RUN"}, separators=(",", ":")))
    raise SystemExit(0 if result.wasSuccessful() else 1)
elif __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(packet_suite())
    raise SystemExit(0 if result.wasSuccessful() else 1)
