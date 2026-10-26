"""DP01 PREPARED / NOT_RUN: pure publication-status SOURCE + separate STATIC.

No product import, ingest, SQL, snapshot, worker, SDK, network or model execution.
Only the two exact readiness declarations execute after genuine source_bootstrap
admission. The owning ingest, extractor producer and connector are AST/read-only.
Reuse the existing AST-Module extraction recipe and shipped PacketResult; no new
loader/controller or authority stand-in. build_suite() preserves unittest fixtures
and never reports starts: the parent/shared result owns that callback exactly once.
Ordinary import/collection is inert; both module and class opt out of pytest.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import types
import unittest

__test__ = False

CASE_IDS = (
    "DP01_SOURCE_active_ok_rejects_non_ok",
    "DP01_SOURCE_active_ok_rejects_missing_and_invalid_status",
    "DP01_SOURCE_active_ok_accepts_normalized_ok",
    "DP01_SOURCE_initial_and_inactive_keep_legacy_statuses",
    "DP01_SOURCE_legacy_partial_can_rematerialize",
    "DP01_SOURCE_explicit_ok_empty_units_remain_lawful",
    "DP01_SOURCE_index_only_falsey_row_is_supported",
    "DP01_SOURCE_constant_safe_failure_and_no_input_mutation",
    "DP01_STATIC_raw_status_and_guard_dominate_all_ingest_paths",
    "DP01_STATIC_original_authority_and_transactions_are_preserved",
    "DP01_STATIC_producer_emits_status_and_distinguishes_partial",
    "DP01_STATIC_connector_requires_real_commit_and_propagates_failure",
    "DP01_STATIC_collection_factory_and_reporter_ownership",
)
BASELINE_DOCUMENT_LF_SHA256 = "8835f2df870a6aee67a99634d7c5b4681e30bf91174fa0bffbe95fe3918fa8ee"
BASELINE_EXTRACTOR_LF_SHA256 = "a0c92be439d1db95cc9b2cccaa65dbb6562a2385df18cae00e9c9916080b159c"
BASELINE_CONNECTOR_LF_SHA256 = "a669ae7c28e949b7b9b56b6a9e02821c92d5af4770074487e2d7df1d61af1a5b"
REQUIRED_INPUTS = (
    "source_bootstrap.py", "document_knowledge_graph.py", "document_extractors.py",
    "source_connectors.py", "test_document_publication_readiness_source.py",
    "test_document_parser_pdf_ocr.py",
)


def _require_bootstrap():
    """Fail closed before reads; no standalone path or injected allowing reader."""
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        raise RuntimeError("original isolated source_bootstrap required")
    required = ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound", "devtools_case_started")
    if any(key not in globals() for key in required):
        raise RuntimeError("genuine finite SOURCE bootstrap required")
    inputs = globals()["DEVTOOLS_INPUTS"]
    if not isinstance(inputs, dict) or any(key not in inputs for key in REQUIRED_INPUTS):
        raise RuntimeError("complete bound SOURCE inputs required")
    bootstrap = Path(inputs["source_bootstrap.py"])
    reader = globals()["devtools_read_bound"]
    started = globals()["devtools_case_started"]
    for function, qualified in ((reader, "main.<locals>.read_bound"),
                                (started, "main.<locals>.case_started")):
        if (not isinstance(function, types.FunctionType)
                or function.__qualname__ != qualified
                or Path(function.__code__.co_filename) != bootstrap
                or function.__globals__.get("__name__") != "__main__"
                or Path(function.__globals__.get("__file__", "")) != bootstrap):
            raise RuntimeError("original source_bootstrap reader and reporter required")
    if reader.__globals__ is not started.__globals__ or "site" in sys.modules:
        raise RuntimeError("original no-site SOURCE envelope required")
    scratch = Path(globals()["DEVTOOLS_SCRATCH"])
    if not scratch.is_absolute() or not scratch.is_dir():
        raise RuntimeError("own absolute synthetic scratch required")
    for key in ("HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HERMES_HOME", "TEMP", "TMP", "TMPDIR"):
        value = Path(os.environ.get(key, ""))
        if not value.is_absolute() or not value.is_relative_to(scratch):
            raise RuntimeError("sterile SOURCE child environment required")
    return inputs, reader


def _node(tree, name):
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name]
    if len(nodes) != 1:
        raise AssertionError("unique reviewed declaration required: " + name)
    return nodes[0]


def _call_name(node):
    if not isinstance(node, ast.Call):
        return ""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


class DocumentPublicationReadinessSourceTests(unittest.TestCase):
    __test__ = False

    @classmethod
    def setUpClass(cls):
        inputs, reader = _require_bootstrap()
        names = ("document_knowledge_graph.py", "document_extractors.py", "source_connectors.py",
                 "test_document_publication_readiness_source.py")
        cls.text = {name: reader(inputs[name]).decode("utf-8").replace("\r\n", "\n") for name in names}
        cls.trees = {name: ast.parse(text, filename=inputs[name]) for name, text in cls.text.items()}
        for attribute in ("text", "trees"):
            cls.addClassCleanup(delattr, cls, attribute)
        tree = cls.trees["document_knowledge_graph.py"]
        selected = [_node(tree, name) for name in ("_DocumentPublicationNotReady", "_document_publication_status")]
        # Same shipped _compile_bodies / AST-Module recipe. Exact original
        # nodes, bodies, annotations and source positions; no dedent or rewrites.
        future = ast.parse("from __future__ import annotations\n").body[0]
        namespace = {"__name__": "dp01_readiness_exact_source"}
        body = ast.Module(body=[future, *selected], type_ignores=[])
        exec(compile(ast.fix_missing_locations(body), inputs["document_knowledge_graph.py"],
                     "exec", dont_inherit=True), namespace)
        cls.validate = staticmethod(namespace["_document_publication_status"])
        cls.rejected = namespace["_DocumentPublicationNotReady"]
        cls.addClassCleanup(delattr, cls, "validate")
        cls.addClassCleanup(delattr, cls, "rejected")
        if namespace["_document_publication_status"].__globals__ is not namespace:
            raise AssertionError("one exact SOURCE namespace required")

    def DP01_SOURCE_active_ok_rejects_non_ok(self):
        previous = {"active": 1, "status": "ok"}
        for status in ("partial", "empty", "failed", "unknown", "unsupported", "metadata_only", "error", " PARTIAL "):
            for units in ([], [{"text": "retained candidate fragment"}]):
                # Authored policy inputs, not parser/SQL/native fixtures.
                candidate = {"status": status, "units": units}
                with self.assertRaises(self.rejected):
                    self.validate(previous, candidate.get("status"))

    def DP01_SOURCE_active_ok_rejects_missing_and_invalid_status(self):
        previous = {"active": 1, "status": "ok"}
        candidates = ({}, {"status": None}, {"status": ""}, {"status": " \t\n"},
                      {"status": False}, {"status": 0}, {"status": True}, {"status": 1},
                      {"status": []}, {"status": {}}, {"status": ["ok"]},
                      {"status": {"value": "ok"}}, {"status": b"ok"})
        for candidate in candidates:
            with self.assertRaises(self.rejected):
                self.validate(previous, candidate.get("status"))

    def DP01_SOURCE_active_ok_accepts_normalized_ok(self):
        for old_status in ("ok", " OK "):
            for status in ("ok", " OK ", "Ok", "\tok\n"):
                previous = {"active": 1, "status": old_status}
                self.assertEqual(self.validate(previous, status), "ok")

    def DP01_SOURCE_initial_and_inactive_keep_legacy_statuses(self):
        for previous in (None, {"active": 0, "status": "ok"}, {"active": None, "status": "ok"}):
            for status, expected in (("partial", "partial"), ("empty", "empty"),
                                     ("ok", "ok"), (" FAILED ", "failed"),
                                     (None, "ok"), ("", "ok"), (False, "ok")):
                self.assertEqual(self.validate(previous, status), expected)

    def DP01_SOURCE_legacy_partial_can_rematerialize(self):
        # E.g. the real XLSX 1/0 producer lawfully emits partial on both passes.
        # This is its status-policy control, NOT a workbook or ingest execution.
        candidate = {"status": "partial", "units": [{"text": "usable partial prose"}],
                     "metadata": {"coverage": {"partial": True}}}
        for old_status in ("partial", "empty", "failed", "unknown", ""):
            previous = {"active": 1, "status": old_status}
            self.assertEqual(self.validate(previous, candidate.get("status")), "partial")
            self.assertEqual(self.validate(previous, "ok"), "ok")

    def DP01_SOURCE_explicit_ok_empty_units_remain_lawful(self):
        previous = {"active": 1, "status": "ok"}
        candidate = {"status": "ok", "units": [], "metadata": {}}
        before = copy.deepcopy(candidate)
        self.assertEqual(self.validate(previous, candidate.get("status")), "ok")
        self.assertEqual(candidate, before)  # no invented coverage, units or status
        candidate["status"] = "empty"
        with self.assertRaises(self.rejected):
            self.validate(previous, candidate.get("status"))

    def DP01_SOURCE_index_only_falsey_row_is_supported(self):
        class IndexOnlyRow:
            # sqlite3.Row-compatible indexed fields, without opening SQLite.
            # False truthiness additionally distinguishes `is not None` from `if row`.
            def __init__(self):
                self.values = {"active": 1, "status": "ok"}
                self.reads = []

            def __getitem__(self, key):
                self.reads.append(key)
                return self.values[key]

            def __bool__(self):
                return False

        previous = IndexOnlyRow()
        self.assertFalse(hasattr(previous, "get"))
        with self.assertRaises(self.rejected):
            self.validate(previous, "partial")
        self.assertEqual(self.validate(previous, "ok"), "ok")
        self.assertEqual(previous.reads, ["active", "status", "active", "status"])
        self.assertEqual(previous.values, {"active": 1, "status": "ok"})

    def DP01_SOURCE_constant_safe_failure_and_no_input_mutation(self):
        class NotAStatus:
            def __str__(self):
                raise AssertionError("invalid replacement status must not be stringified")

        previous = {"active": 1, "status": "ok", "revision_id": "old-usable-revision"}
        candidate = {"status": "synthetic-private-status-canary", "units": [{"text": "private-body-canary"}]}
        before = copy.deepcopy((previous, candidate))
        for status in (candidate["status"], None, False, {}, NotAStatus()):
            with self.assertRaises(self.rejected) as caught:
                self.validate(previous, status)
            error = caught.exception
            self.assertIs(type(error), self.rejected)
            self.assertIsInstance(error, RuntimeError)
            self.assertEqual(str(error), "document_publication_incomplete")
            self.assertEqual(error.args, ("document_publication_incomplete",))
            self.assertIsNone(error.__cause__)
            self.assertIsNone(error.__context__)
        self.assertEqual((previous, candidate), before)

    def DP01_STATIC_raw_status_and_guard_dominate_all_ingest_paths(self):
        ingest = _node(self.trees["document_knowledge_graph.py"], "ingest_document")
        assignments = [n for n in ingest.body if isinstance(n, ast.Assign)]
        def assigned(name):
            found = [n for n in assignments if any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
            self.assertEqual(len(found), 1, name)
            return found[0]
        raw = assigned("candidate_status")
        self.assertEqual(ast.dump(raw.value), ast.dump(ast.parse('payload.get("status")', mode="eval").body))
        transformed = next(n for n in assignments if _call_name(n.value) == "_document_extraction_payload")
        self.assertLess(raw.lineno, transformed.lineno)
        guard = assigned("extractor_status")
        self.assertEqual(ast.dump(guard.value), ast.dump(ast.parse(
            "_document_publication_status(existing, candidate_status)", mode="eval").body))
        calls = [n for n in ast.walk(ingest) if isinstance(n, ast.Call)]
        self.assertEqual(sum(_call_name(n) == "_document_publication_status" for n in calls), 1)
        source_reads = [n for n in assignments if any(isinstance(t, ast.Name) and t.id == "existing" for t in n.targets)]
        self.assertEqual(len(source_reads), 2)
        self.assertLess(transformed.lineno, source_reads[-1].lineno)
        self.assertLess(source_reads[-1].lineno, guard.lineno)
        self.assertIn("SELECT * FROM document_sources WHERE source_id=?", ast.unparse(source_reads[-1]))
        scope = assigned("same_identity")
        alias = [n for n in ingest.body if isinstance(n, ast.Expr) and _call_name(n.value) == "_assert_ingest_path_alias_owner"][-1]
        self.assertLess(source_reads[-1].lineno, scope.lineno)
        self.assertLess(scope.lineno, alias.lineno)
        self.assertLess(alias.end_lineno, guard.lineno)
        self.assertLess(guard.lineno, assigned("representation_current").lineno)
        early = [n for n in ingest.body if isinstance(n, ast.If) and any(
            isinstance(w, ast.With) and any(_call_name(i.context_expr) == "_ingest_transaction" for i in w.items)
            for w in n.body)]
        self.assertEqual(len(early), 2)
        transactions = [n for n in calls if _call_name(n) == "_ingest_transaction"]
        self.assertEqual(len(transactions), 3)
        self.assertTrue(all(guard.end_lineno < n.lineno for n in early + transactions))
        protected = {"_remember_file_identity", "_archive_visible_claims", "_embed_ingest_result",
                     "_guard_document_output", "_make_chunks", "_record_result"}
        mutations = [n for n in calls if _call_name(n) in protected or (
            isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "_commit_hook" and n.func.attr == "apply")]
        self.assertTrue(mutations)
        self.assertTrue(all(guard.end_lineno < n.lineno for n in mutations))
        writes = [n for n in calls if _call_name(n) == "execute" and n.args and any(
            isinstance(c, ast.Constant) and isinstance(c.value, str)
            and c.value.lstrip().startswith(("UPDATE ", "DELETE ", "INSERT ")) for c in ast.walk(n.args[0]))]
        self.assertTrue(writes)
        self.assertTrue(all(guard.end_lineno < n.lineno for n in writes))
        returns = [n for n in ast.walk(ingest) if isinstance(n, ast.Return)]
        self.assertTrue(all(guard.end_lineno < n.lineno for n in returns))
        # Guard is an unconditional owning-body statement, outside all handlers;
        # no success-shaped refusal or catch can make the hook look committed.
        self.assertIn(guard, ingest.body)

    def DP01_STATIC_original_authority_and_transactions_are_preserved(self):
        text = self.text["document_knowledge_graph.py"]
        tree = self.trees["document_knowledge_graph.py"]
        restored = text
        for name in ("_DocumentPublicationNotReady", "_document_publication_status"):
            segment = ast.get_source_segment(text, _node(tree, name)) + "\n\n\n"
            self.assertEqual(restored.count(segment), 1)
            restored = restored.replace(segment, "", 1)
        capture = '    candidate_status = payload.get("status")\n'
        guard = '    extractor_status = _document_publication_status(existing, candidate_status)\n'
        for addition in (capture, guard):
            self.assertEqual(restored.count(addition), 1)
            restored = restored.replace(addition, "", 1)
        anchor = '    same_identity = _assert_ingest_source_scope(provider, existing, scope_id, repository_id)\n'
        old_status = '    extractor_status = str(payload.get("status") or "ok").strip().lower()\n'
        self.assertEqual(restored.count(anchor), 1)
        restored = restored.replace(anchor, old_status + anchor, 1)
        # Exact normalized bytes, not a Python-version-dependent AST fingerprint.
        # Covers ALL original owner/path/managed/lease/SQL/replay/retirement code.
        self.assertEqual(hashlib.sha256(restored.encode("utf-8")).hexdigest(), BASELINE_DOCUMENT_LF_SHA256)
        validator = _node(tree, "_document_publication_status")
        self.assertFalse(any(isinstance(n, (ast.Import, ast.ImportFrom, ast.With, ast.Try)) for n in ast.walk(validator)))
        self.assertEqual({_call_name(n) for n in ast.walk(validator) if isinstance(n, ast.Call)},
                         {"int", "str", "isinstance", "strip", "lower", "_DocumentPublicationNotReady"})

    def DP01_STATIC_producer_emits_status_and_distinguishes_partial(self):
        text = self.text["document_extractors.py"]
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), BASELINE_EXTRACTOR_LF_SHA256)
        tree = self.trees["document_extractors.py"]
        document = _node(tree, "ExtractedDocument")
        status = [n for n in document.body if isinstance(n, ast.AnnAssign)
                  and isinstance(n.target, ast.Name) and n.target.id == "status"]
        self.assertEqual(len(status), 1)
        self.assertEqual(ast.literal_eval(status[0].value), "ok")
        to_dict = _node(document, "to_dict")
        emitted = [value for n in ast.walk(to_dict) if isinstance(n, ast.Dict)
                   for key, value in zip(n.keys, n.values) if isinstance(key, ast.Constant) and key.value == "status"]
        self.assertEqual(len(emitted), 1)
        self.assertEqual(ast.dump(emitted[0]), ast.dump(ast.parse("self.status", mode="eval").body))
        producer = _node(tree, "extract_document")
        self.assertTrue(any(isinstance(n, ast.Assign) and _call_name(n.value) == "to_dict"
                            and any(isinstance(t, ast.Name) and t.id == "payload" for t in n.targets)
                            for n in producer.body))
        self.assertTrue(any(isinstance(n, ast.Return) and isinstance(n.value, ast.Name)
                            and n.value.id == "payload" for n in producer.body))
        xlsx = _node(tree, "extract_xlsx")
        emitted_status = [keyword.value for n in ast.walk(xlsx) if isinstance(n, ast.Call)
                          and _call_name(n) == "ExtractedDocument" for keyword in n.keywords if keyword.arg == "status"]
        self.assertEqual(len(emitted_status), 1)
        expected = ast.parse('( "partial" if partial else "ok") if output_cells else "empty"', mode="eval").body
        self.assertEqual(ast.dump(emitted_status[0]), ast.dump(expected))

    def DP01_STATIC_connector_requires_real_commit_and_propagates_failure(self):
        text = self.text["source_connectors.py"]
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), BASELINE_CONNECTOR_LF_SHA256)
        tree = self.trees["source_connectors.py"]
        expected = ast.parse("hook.outcome() != 'committed' or hook.expected is None", mode="eval").body
        for name in ("sync_local_file", "upsert_record"):
            owner = _node(tree, name)
            ingests = [n for n in ast.walk(owner) if isinstance(n, ast.Call) and _call_name(n) == "ingest_document"]
            self.assertEqual(len(ingests), 1)
            self.assertEqual([(k.arg, ast.dump(k.value)) for k in ingests[0].keywords],
                             [("_commit_hook", ast.dump(ast.Name(id="hook", ctx=ast.Load())))])
            checks = [n for n in ast.walk(owner) if isinstance(n, ast.If) and ast.dump(n.test) == ast.dump(expected)]
            self.assertEqual(len(checks), 1)
            self.assertLess(ingests[0].lineno, checks[0].lineno)
            self.assertIsInstance(checks[0].body[0], ast.Raise)
            self.assertEqual(ast.literal_eval(checks[0].body[0].exc.args[0]), "connector_transaction_commit_outcome_unknown")
        upsert = _node(tree, "upsert_record")
        handlers = [n for n in ast.walk(upsert) if isinstance(n, ast.ExceptHandler)
                    and isinstance(n.type, ast.Name) and n.type.id == "BaseException"]
        self.assertTrue(any(any(isinstance(s, ast.Raise) and s.exc is None for s in n.body) for n in handlers))
        local = _node(tree, "sync_local_file")
        self.assertFalse(any(isinstance(n, ast.Try) for n in local.body))

    def DP01_STATIC_collection_factory_and_reporter_ownership(self):
        tree = self.trees["test_document_publication_readiness_source.py"]
        owner = _node(tree, "DocumentPublicationReadinessSourceTests")
        for body in (tree.body, owner.body):
            opts = [n for n in body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "__test__" for t in n.targets)]
            self.assertEqual(len(opts), 1)
            self.assertIs(ast.literal_eval(opts[0].value), False)
        roster = [n for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "CASE_IDS" for t in n.targets)]
        self.assertEqual(len(roster), 1)
        cases = ast.literal_eval(roster[0].value)
        self.assertIsInstance(cases, tuple)
        self.assertEqual(cases, CASE_IDS)
        self.assertEqual(len(cases), len(set(cases)))
        self.assertTrue(all(n.startswith(("DP01_SOURCE_", "DP01_STATIC_")) for n in cases))
        methods = [n.name for n in owner.body if isinstance(n, ast.FunctionDef) and n.name.startswith("DP01_")]
        self.assertEqual(methods, list(cases))
        # Only imports, literal metadata and definitions run on ordinary import.
        for node in tree.body:
            if isinstance(node, ast.Assign):
                ast.literal_eval(node.value)
            elif isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant)
            elif isinstance(node, ast.If):
                self.assertEqual(ast.dump(node.test), ast.dump(ast.parse('__name__ == "__main__"', mode="eval").body))
            else:
                self.assertIsInstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
        factory = _node(tree, "build_suite")
        statements = [n for n in factory.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        self.assertEqual(_call_name(statements[0].value), "_require_bootstrap")
        self.assertIsInstance(statements[-1], ast.Return)
        self.assertEqual(_call_name(statements[-1].value), "TestSuite")
        self.assertFalse(any(isinstance(n, ast.Call) and _call_name(n) in {"exec", "compile", "devtools_read_bound"}
                             for n in ast.walk(factory)))
        setup = _node(owner, "setUpClass")
        self.assertEqual(_call_name(setup.body[0].value), "_require_bootstrap")
        main = _node(tree, "main")
        self.assertEqual(_call_name(main.body[0].value), "_require_bootstrap")
        gate = _node(tree, "_require_bootstrap")
        strings = {n.value for n in ast.walk(gate) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertTrue({"source_bootstrap.py", "main.<locals>.read_bound", "main.<locals>.case_started"}.issubset(strings))
        self.assertFalse(any(isinstance(n, ast.Call) and _call_name(n) == "devtools_case_started" for n in ast.walk(tree)))
        self.assertEqual(sum(isinstance(n, ast.Call) and _call_name(n) == "run" for n in ast.walk(main)), 1)


def build_suite() -> unittest.TestSuite:
    """The complete planned SOURCE/STATIC cohort; no reads, execution or starts."""
    _require_bootstrap()
    return unittest.TestSuite(DocumentPublicationReadinessSourceTests(name) for name in CASE_IDS)


def main():
    inputs, reader = _require_bootstrap()
    # Reuse only the exact existing reporter, NOT peer imports or peer tests.
    path = inputs["test_document_parser_pdf_ocr.py"]
    peer = ast.parse(reader(path), filename=path)
    reporters = [n for n in ast.walk(peer) if isinstance(n, ast.ClassDef) and n.name == "PacketResult"]
    if len(reporters) != 1:
        raise RuntimeError("unique shipped PacketResult required")
    namespace = {"__name__": "dp01_original_packet_reporter", "unittest": unittest,
                 "devtools_case_started": globals()["devtools_case_started"]}
    exec(compile(ast.Module(body=reporters, type_ignores=[]), path, "exec", dont_inherit=True), namespace)
    result = namespace["PacketResult"]()
    build_suite().run(result)
    rows = result.rows
    complete = [row["id"] for row in rows] == list(CASE_IDS)
    report = {"schema": "memory-stack.cases/v1", "cases": rows,
              "scope": "DP01_PURE_READINESS_SOURCE_PLUS_STATIC_ONLY",
              "source_case_ids": [name for name in CASE_IDS if name.startswith("DP01_SOURCE_")],
              "static_case_ids": [name for name in CASE_IDS if name.startswith("DP01_STATIC_")],
              "ingest_SQL_SDK_snapshot_worker_network_model": "NOT_RUN",
              "connector_compensation_native_E2E": "NOT_RUN", "roster_complete": complete}
    sys.stdout.write(json.dumps(report, ensure_ascii=True, separators=(",", ":")) + "\n")
    return 0 if complete and result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
