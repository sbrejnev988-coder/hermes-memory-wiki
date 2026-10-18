"""Offline SOURCE regression for temporary extraction guard completion.

Run from a COMPLETE candidate tree with stdlib only:
    python -I -B -S tests/test_extraction_guard_completion.py
No package/SDK bootstrap, database, provider or model is executed. The genuine
background module and complete source secret scanner are compiled directly.
Guard statuses, receiver, extraction input/transport and SELECT-only observer
are explicitly synthetic. They cannot grant quality, SQL/TX or owner authority.
Late persistence is STATIC source-order evidence, not a runtime SQL test.
All helpers live here; no evidence-directory test peer is required.
"""
from __future__ import annotations

import ast
import builtins
import dis
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import types
from typing import Any, Dict, List, Optional
import unittest

SCANNER_FUNCTIONS = (
    "short", "clamp", "_sensitive_secret_field", "_quoted_secret_assignment_is_raw",
    "_redact_quoted_secret_assignment", "_balanced_secret_container_end",
    "_redact_quoted_secret_containers", "redact_secrets", "secret_scan",
)
SCANNER_CONSTANTS = (
    "SECRET_PATTERNS", "SECRET_FIELD_RE", "SECRET_ASSIGN_RE",
    "QUOTED_SECRET_ASSIGN_RE", "QUOTED_SECRET_CONTAINER_RE", "REDaction_MARKER_RE",
)
TRANSIENT = ("guard_unavailable_quarantined", "runtime_failure_quarantined")
# Exact qualified unchanged nodes from the registered accepted source tree.
UNCHANGED_NODES = {
    "run_once": "af74e0ab1e310cbcf8798840d2a9c949f6f7d605b3cf1099339a714875b9c4f8",
    "JobStore.finish": "73ae869217ae61a0ccc4d605d06cf8777ed707b8e4f66fdc4e9606db3d72b301",
    "JobStore.defer": "476e3185328a9f36afe80f8f1cec7386428a0693e612d3fd2dc63cc56ec24ee5",
    "_event_source": "d5f2ec80f381bd61eae54e833325d41beabae2d6f2a5f93173b1d087dca6fe46",
    "_event_job_obligation": "ce4daab30de995db9783b64657a05f7dfe81686cd97fdd0de6cfb2d716b98555",
    "_close_job_worker": "eaa1a8fb0d935f2f09372447d5f1cc662031e0ecf7c8562f3f062ac4e0ef3aa1",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def ast_digest(node):
    return digest(ast.dump(node, include_attributes=False).encode("utf-8"))


def qualified(tree, name):
    scope = tree
    for part in name.split("."):
        pending, matches = list(scope.body), []
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if node.name == part:
                    matches.append(node)
                # Never cross a different lexical function/class scope.
            else:
                pending.extend(ast.iter_child_nodes(node))
        if len(matches) != 1:
            raise ValueError("unique_qualified_node_required:" + name)
        scope = matches[0]
    return scope


def dependency_names(code):
    names = {i.argval for i in dis.get_instructions(code) if i.opname == "LOAD_GLOBAL"}
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            names |= dependency_names(value)
    return names


def scanner_ast(raw):
    tree = ast.parse(raw)
    nodes = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
    origins = []
    for name in SCANNER_CONSTANTS + SCANNER_FUNCTIONS:
        matches = [n for n in tree.body if
                   (isinstance(n, ast.FunctionDef) and n.name == name) or
                   (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))]
        if len(matches) != 1:
            raise ValueError("unique_scanner_binding_required:" + name)
        node = matches[0]
        if isinstance(node, ast.FunctionDef) and node.decorator_list:
            raise ValueError("undecorated_scanner_required")
        nodes.append(node)
        origins.append({"qualified_AST": name, "type": type(node).__name__,
                        "lines": [node.lineno, node.end_lineno], "ast_sha256": ast_digest(node)})
    return ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), origins


def calls(node, attr):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and
            ((isinstance(n.func, ast.Attribute) and n.func.attr == attr) or
             (isinstance(n.func, ast.Name) and n.func.id == attr))]


def field_guard(node, variable, value):
    return isinstance(node, ast.If) and ast.unparse(node.test) == variable + ".get('status') in transient_guard_statuses" and value in ast.unparse(node)


class ReadResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return dict(self.rows[0]) if self.rows else None

    def fetchall(self):
        return [dict(row) for row in self.rows]

    def __iter__(self):
        return iter(self.fetchall())


class ReadObserver:
    """Synthetic exact SELECT receiver, NOT a database or SQL admission."""
    def __init__(self, receiver):
        self.receiver = receiver

    def execute(self, statement, parameters=()):
        receiver, sink = self.receiver, self.receiver.sink
        normalized = " ".join(statement.split())
        sink["selects"].append(normalized)
        if normalized.startswith("SELECT e.*,d.docid AS event_sequence FROM memory_events e JOIN memory_event_fts_docids d ON d.event_id=e.event_id WHERE e.event_id=?"):
            if parameters[0] != receiver.pointer["event_id"]:
                raise AssertionError("unexpected_pointer")
            return ReadResult([] if sink["missing_pointer"] else [receiver.pointer])
        if normalized.startswith("SELECT e.*,d.docid AS event_sequence FROM memory_events e JOIN memory_event_fts_docids d ON d.event_id=e.event_id WHERE e.owner_bot_id=?"):
            expected = (receiver.pointer["owner_bot_id"], receiver.pointer["owner_chat_hash"],
                        receiver.pointer["owner_session_hash"], "chat", "")
            if parameters[:5] != expected or parameters[-1] != 32:
                raise AssertionError("unexpected_partition_read")
            return ReadResult(sorted(receiver.rows, key=lambda row: row["event_sequence"], reverse=True))
        if normalized == "SELECT id FROM claims WHERE visibility_scope='chat' AND origin_bot_id=? AND origin_chat_hash=?":
            if tuple(parameters) != (receiver.bot_id, receiver._job_chat_hash):
                raise AssertionError("unexpected_preexisting_read")
            return ReadResult([])
        raise AssertionError("non_declared_SELECT_or_SQL_authority_forbidden")

    def close(self):
        self.receiver.sink["close_calls"] += 1
        failure = self.receiver.sink["close_failure"]
        if failure is not None:
            raise failure
        self.receiver.sink["closed"] += 1


class Receiver:
    """Synthetic owner INPUT. Original mapper/partition/obligation validate it.

    No _prepare_claim/_claim_transaction/_add_claim_tx or permitting authority
    method exists. Reaching one is a fixture error, not a successful late test.
    """
    def __init__(self, root, rows, statuses, sink):
        self.home, self.db_path = root, root / "NOT_A_DATABASE"
        self.bot_id, self.project_scope, self.session_id = "fixture-owner", "", "fixture-session"
        self._lock, self._conn, self._owned_conn = threading.RLock(), None, None
        self._transaction_quarantine, self._transaction_primary = None, None
        self.pointer, self.rows, self.statuses, self.sink = dict(rows[-1]), rows, statuses, sink

    def _connect(self):
        if self._conn is None:
            self._conn = ReadObserver(self)
            self._owned_conn = self._conn
            if self.session_id.startswith("job_"):
                self.sink["worker"] = self
        return self._conn

    def _inspect_recall_text(self, raw, **kwargs):
        self.sink["inspected"].append(raw)
        if kwargs != {"source": "host:background_event", "mem_type": "event", "audit": False,
                      "max_len": max(4000, len(raw))}:
            raise AssertionError("guard_arguments_changed")
        status = self.statuses.get(raw, "safe")
        if isinstance(status, BaseException):
            raise status
        if status == "safe_mismatch":
            return {"status": "safe", "content": raw + " changed"}
        return {"status": status, "content": raw if status == "safe" else ""}

    def relevant_graph_extraction_settings(self):
        self.sink["graph_settings_calls"] += 1
        # Denial-only input. No graph producer/SQL authority is replaced by True.
        return False, False

    def _quarantine_claim_connection(self, connection, label, primary):
        self._transaction_quarantine = connection
        if self._transaction_primary is None:
            self._transaction_primary = primary
        self.sink["quarantines"].append(label)


class ExtractionInput:
    """Synthetic extractor INPUT/transport; no provider/model/persisted IDs."""
    def __init__(self, scanner, sink, *, error=False, failure=None, invalid_callback=False):
        self.secret_scan, self.redact_secrets = scanner["secret_scan"], scanner["redact_secrets"]
        self.sink, self.error, self.failure, self.invalid_callback = sink, error, failure, invalid_callback

    def read_extraction_settings(self, home):
        self.sink["settings_home"] = str(home)
        return None  # Passed through only; no real settings/provider is invoked.

    def extract_session_claims(self, messages, **kwargs):
        self.sink["dispatch"].append([dict(m) for m in messages])
        if self.failure is not None:
            raise self.failure
        if self.invalid_callback:
            returned = kwargs["add_claim_callback"](None)
            if returned != "":
                raise AssertionError("invalid_callback_not_refused")
            self.sink["invalid_callback_refused"] = True
        return {"persisted_ids": [], "errors": ["fixture_input_error"] if self.error else [], "error": ""}


def event(index, text):
    return {"event_id": "evt_" + format(index, "032x"), "event_sequence": index,
            "owner_bot_id": "fixture-owner", "owner_chat_hash": "a" * 32,
            "owner_session_hash": "b" * 32, "visibility_scope": "chat", "project_id": "",
            "content": text, "content_hash": digest(text.encode("utf-8")),
            "event_type": "dialogue_turn", "role": "user", "expires_at": 2**62}


class ExtractionGuardCompletionTests(unittest.TestCase):
    def setUp(self):
        self.sink = {"selects": [], "dispatch": [], "inspected": [], "close_calls": 0, "closed": 0,
                     "close_failure": None, "graph_settings_calls": 0, "quarantines": [], "missing_pointer": False}

    def fixture(self, statuses=None, rows=None, **options):
        rows = rows if rows is not None else [event(1, "The observatory owns the violet telescope.")]
        root = self.scratch / self._testMethodName
        self.receiver = Receiver(root, rows, statuses or {}, self.sink)
        self.module_input = ExtractionInput(self.scanner, self.sink, **options)
        self.job = {"job_id": "job_" + "c" * 32, "job_type": "extract_session_events",
                    "profile_key": self.jobs.profile_key(self.receiver), "owner_key": self.jobs.owner_key(self.receiver),
                    "partition_key": self.jobs.partition_key(self.receiver.pointer),
                    "owner_chat_hash": "a" * 32, "owner_session_hash": "b" * 32,
                    "lease_owner": "d" * 32 + ":" + "e" * 32, "lease_generation": 1,
                    "payload_json": self.jobs.validate_payload("extract_session_events", {
                        "event_id": self.receiver.pointer["event_id"], "high_watermark": 32})}
        return self.receiver

    def invoke(self, lease_valid=None):
        return self.jobs._run_job(self.receiver, self.module_input, self.job, lease_valid=lease_valid)

    def assert_deferred(self, outcome, before, after):
        self.assertIsInstance(outcome, tuple, "temporary_guard_failure_was_completed")
        self.assertEqual(outcome[0], "defer")
        self.assertIs(type(outcome[1]), int)
        self.assertGreaterEqual(outcome[1], before + 60)
        self.assertLessEqual(outcome[1], after + 60)
        self.assertEqual(self.sink["dispatch"], [])
        self.assertEqual(self.sink["closed"], 1)
        self.assertEqual(self.sink["quarantines"], [])

    def transient(self, status, texts=None):
        texts = texts or ["The observatory owns the violet telescope."]
        rows = [event(i + 1, text) for i, text in enumerate(texts)]
        blocked = next(text for text in texts if "violet" in text)
        self.fixture({blocked: status}, rows)
        before = int(time.time())
        result = self.invoke()
        after = int(time.time())
        return result, before, after

    def test_initial_unavailable_defers(self):
        outcome, before, after = self.transient(TRANSIENT[0])
        # Durable hashed witness BEFORE the distinguishing baseline assertion.
        witness = {"guard_input": TRANSIENT[0], "outcome": outcome,
                   "source_sha256": self.source_sha256, "test_sha256": self.test_sha256,
                   "synthetic_SELECT_count": len(self.sink["selects"]),
                   "extractor_dispatch_count": len(self.sink["dispatch"]),
                   "worker_close_count": self.sink["closed"],
                   "SQLite_connections": 0, "queue_finish_executed": False,
                   "conditional_empty_string_would_select_finish": outcome == ""}
        directory = self.scratch / self._testMethodName
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "witness.json").write_text(json.dumps(witness, sort_keys=True) + "\n", encoding="utf-8")
        self.assert_deferred(outcome, before, after)

    def test_initial_runtime_failure_defers(self):
        self.assert_deferred(*self.transient(TRANSIENT[1]))

    def test_mixed_safe_then_unavailable_defers_before_dispatch(self):
        self.assert_deferred(*self.transient(TRANSIENT[0], ["The copper telescope is polished.", "The violet telescope is indoors."]))
        self.assertEqual(len(self.sink["inspected"]), 2)

    def test_mixed_unavailable_then_safe_defers_before_dispatch(self):
        self.assert_deferred(*self.transient(TRANSIENT[0], ["The violet telescope is indoors.", "The copper telescope is polished."]))
        self.assertEqual(len(self.sink["inspected"]), 1)

    def test_permanent_quarantine_does_not_defer(self):
        for status in ("quarantined", "quarantined_guard_disagreement", "local_filter_quarantined"):
            self.setUp()
            row = event(1, "The observatory owns the violet telescope.")
            self.fixture({row["content"]: status}, [row])
            self.assertEqual(self.invoke(), "")
            self.assertEqual(self.sink["dispatch"], [])
            self.assertEqual(self.sink["closed"], 1)

    def test_safe_projection_mismatch_is_not_transient(self):
        row = event(1, "The violet telescope is indoors.")
        self.fixture({row["content"]: "safe_mismatch"}, [row])
        self.assertEqual(self.invoke(), "")
        self.assertEqual(self.sink["dispatch"], [])

    def test_healthy_dispatch_preserves_chronological_messages(self):
        rows = [event(1, "The copper telescope is polished."), event(2, "The violet telescope is indoors.")]
        rows[1]["role"] = "assistant"
        self.fixture(rows=rows)
        self.assertEqual(self.invoke(), "")
        self.assertEqual(self.sink["dispatch"], [[{"role": r["role"], "content": r["content"]} for r in rows]])
        self.assertEqual(self.sink["closed"], 1)
        self.assertEqual(self.sink["graph_settings_calls"], 1)

    def test_empty_retained_rows_remain_empty(self):
        self.fixture()
        self.receiver.rows = []
        self.assertEqual(self.invoke(), "")
        self.assertEqual(self.sink["dispatch"], [])
        self.assertEqual(self.sink["closed"], 1)

    def test_missing_pointer_keeps_existing_defer(self):
        self.fixture()
        self.sink["missing_pointer"] = True
        before = int(time.time())
        outcome = self.invoke()
        self.assertEqual(outcome[0], "defer")
        self.assertGreaterEqual(outcome[1], before + 60)
        self.assertEqual(self.sink["close_calls"], 0)
        self.assertEqual(self.sink["dispatch"], [])

    def test_lost_lease_denies_before_worker(self):
        self.fixture()
        self.assertEqual(self.invoke(lease_valid=lambda: False), "timeout")
        self.assertEqual(self.sink["selects"], [])

    def test_invalid_payload_denies_before_receiver(self):
        self.fixture()
        self.job["payload_json"] = '{"not_allowed":"fixture"}'
        self.assertEqual(self.invoke(), "invalid_source")
        self.assertEqual(self.sink["selects"], [])

    def test_original_partition_owner_checks_deny_foreign_row(self):
        self.fixture()
        self.receiver.pointer["owner_bot_id"] = "foreign-fixture-owner"
        outcome = self.invoke()
        self.assertEqual(outcome[0], "defer")
        self.assertEqual(self.sink["dispatch"], [])
        self.assertNotIn("worker", self.sink)

    def test_secret_and_hash_rejection_remain_permanent(self):
        rows = [event(1, "password=OWNED_FIXTURE_0123456789"), event(2, "The copper telescope is polished.")]
        rows[1]["content_hash"] = "0" * 64
        self.fixture(rows=rows)
        self.assertTrue(self.scanner["secret_scan"](rows[0]["content"])["raw_secret"])
        self.assertEqual(self.invoke(), "")
        self.assertEqual(self.sink["inspected"], [])
        self.assertEqual(self.sink["dispatch"], [])

    def test_extractor_error_retains_provider_failure(self):
        self.fixture(error=True)
        self.assertEqual(self.invoke(), "provider")
        self.assertEqual(self.sink["closed"], 1)

    def test_extractor_exception_preserves_primary(self):
        primary = RuntimeError("synthetic extractor fault")
        self.fixture(failure=primary)
        with self.assertRaises(RuntimeError) as caught:
            self.invoke()
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.sink["closed"], 1)

    def test_cancellation_preserves_primary(self):
        primary = KeyboardInterrupt("synthetic cancellation")
        self.fixture(failure=primary)
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.invoke()
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.sink["closed"], 1)

    def test_guard_exception_is_not_typed_defer(self):
        primary = RuntimeError("synthetic guard callback fault")
        row = event(1, "The violet telescope is indoors.")
        self.fixture({row["content"]: primary}, [row])
        with self.assertRaises(RuntimeError) as caught:
            self.invoke()
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.sink["closed"], 1)
        self.assertEqual(self.sink["dispatch"], [])

    def test_cleanup_unknown_retains_exact_worker_and_primary(self):
        primary, cleanup = RuntimeError("synthetic primary"), OSError("synthetic close refusal")
        parent = self.fixture(failure=primary)
        self.sink["close_failure"] = cleanup
        with self.assertRaises(RuntimeError) as caught:
            self.invoke()
        worker = self.sink["worker"]
        self.assertIs(caught.exception, primary)
        self.assertIs(parent._graph_effect_quarantined_worker, worker)
        self.assertIs(parent._transaction_quarantine, worker._owned_conn)
        self.assertIs(parent._transaction_primary, primary)
        self.assertIs(worker._transaction_primary, primary)
        self.assertIsNotNone(worker._conn)
        self.assertEqual(self.sink["closed"], 0)
        self.assertIn("memory_wiki_graph_worker_cleanup:close_UNKNOWN", primary.__notes__)

    def test_cleanup_only_unknown_raises_exact_failure(self):
        cleanup = OSError("synthetic close refusal")
        parent = self.fixture()
        self.sink["close_failure"] = cleanup
        with self.assertRaises(OSError) as caught:
            self.invoke()
        worker = self.sink["worker"]
        self.assertIs(caught.exception, cleanup)
        self.assertIs(parent._graph_effect_quarantined_worker, worker)
        self.assertIs(parent._transaction_primary, cleanup)
        self.assertIs(worker._transaction_quarantine, worker._owned_conn)
        self.assertEqual(self.sink["closed"], 0)

    def test_invalid_callback_never_reaches_quality_or_tx(self):
        self.fixture(invalid_callback=True)
        self.assertEqual(self.invoke(), "")
        self.assertIs(self.sink["invalid_callback_refused"], True)
        self.assertFalse(hasattr(self.module_input, "memory_gate_decision"))
        self.assertFalse(hasattr(self.receiver, "_claim_transaction"))
        self.assertFalse(hasattr(self.receiver, "_prepare_claim"))
        self.assertFalse(hasattr(self.receiver, "_add_claim_tx"))

    def test_static_typed_producer_and_extractor_empty_id_contract(self):
        producer = qualified(self.entry_tree, "MemoryWikiProvider._inspect_recall_text")
        self.assertEqual(ast_digest(producer), "f1492a666c9d648738c01009cfdba976e1610a8beec1e06c2b8b072279619fd9")
        for status in TRANSIENT:
            returns = [n for n in ast.walk(producer) if isinstance(n, ast.Dict) and
                       any(isinstance(k, ast.Constant) and k.value == "status" and isinstance(v, ast.Constant) and v.value == status for k, v in zip(n.keys, n.values))]
            self.assertEqual(len(returns), 1)
            self.assertIn("'content': ''", ast.unparse(returns[0]))
        extractor = qualified(self.extractor_tree, "extract_session_claims")
        self.assertEqual(ast_digest(extractor), "c6aef3d307512422d60d82ec1ffa78b596744610a0a07909a2cbb1635478cc06")
        self.assertTrue(any(isinstance(n, ast.If) and ast.unparse(n.test) == "claim_id" and calls(n, "append") for n in ast.walk(extractor)))
        self.assertTrue(any(isinstance(n, ast.ExceptHandler) and ast.unparse(n.type) == "Exception" and "errors.append(type(exc).__name__)" in ast.unparse(n) for n in ast.walk(extractor)))

    def test_static_late_transient_latches_before_claim_write(self):
        callback = qualified(self.jobs_tree, "_run_job.persist_if_current")
        guards = [n for n in ast.walk(callback) if field_guard(n, "inspected", "guard_deferred = True")]
        self.assertEqual(len(guards), 1)
        guard = guards[0]
        self.assertEqual([ast.unparse(n) for n in guard.body], ["guard_deferred = True", "return ''"])
        self.assertLess(guard.lineno, calls(callback, "_add_claim_tx")[0].lineno)
        tx = next(n for n in ast.walk(callback) if isinstance(n, ast.With) and calls(n.items[0].context_expr, "_claim_transaction"))
        self.assertLess(tx.lineno, guard.lineno)
        self.assertIn("_event_job=event_obligation", ast.unparse(tx.items[0].context_expr))
        # Actual SQL/quality/lease callbacks were deliberately not executed.
        self.assertEqual(len(calls(callback, "_add_claim_tx")), 1)

    def test_static_late_latch_stops_later_callbacks_after_primary(self):
        callback = qualified(self.jobs_tree, "_run_job.persist_if_current")
        self.assertEqual(ast.unparse(callback.body[0]), "nonlocal persistence_primary, guard_deferred")
        self.assertEqual(ast.unparse(callback.body[1]), "if persistence_primary is not None:\n    raise persistence_primary")
        self.assertEqual(ast.unparse(callback.body[2]), "if guard_deferred:\n    return ''")
        late = next(n for n in ast.walk(callback) if field_guard(n, "inspected", "guard_deferred = True"))
        parent_for = next(n for n in ast.walk(callback) if isinstance(n, ast.For) and n.target.id == "original")
        self.assertIn(late, parent_for.body)
        self.assertIn("inspected.get('status') != 'safe'", ast.unparse(parent_for.body[-1].test))

    def test_static_graph_and_projection_precede_defer(self):
        run, callback = qualified(self.jobs_tree, "_run_job"), qualified(self.jobs_tree, "_run_job.persist_if_current")
        outer = next(n for n in run.body if isinstance(n, ast.Try) and calls(n, "extract_session_claims"))
        graph = calls(outer, "enqueue_claim")[0]
        extract = calls(outer, "extract_session_claims")[0]
        guards = [n for n in outer.body if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "guard_deferred"]
        self.assertEqual(len(guards), 1)
        defer = guards[0]
        self.assertLess(extract.lineno, graph.lineno)
        self.assertLess(graph.lineno, defer.lineno)
        self.assertIn("for claim_id in result.get('persisted_ids', [])[:4]", ast.unparse(outer))
        self.assertEqual(ast.unparse(outer.body[-3].test), "result.get('error') or result.get('errors')")
        self.assertIn("return 'provider'", ast.unparse(outer.body[-3]))
        self.assertIn("return ('defer', int(time.time()) + 60)", ast.unparse(defer))
        post_commit = calls(callback, "_after_claim_commit")[0]
        tx_try = next(n for n in callback.body if isinstance(n, ast.Try))
        self.assertGreater(post_commit.lineno, tx_try.end_lineno)
        primary = next(n for n in outer.body if isinstance(n, ast.If) and ast.unparse(n.test) == "persistence_primary is not None")
        self.assertLess(primary.lineno, graph.lineno)
        self.assertEqual(ast.unparse(primary.body[0]), "raise persistence_primary")

    def test_static_existing_lease_owner_cleanup_guards_unchanged(self):
        for name, expected in UNCHANGED_NODES.items():
            self.assertEqual(ast_digest(qualified(self.jobs_tree, name)), expected, name)
        callback = qualified(self.jobs_tree, "_run_job.persist_if_current")
        self.assertEqual(len(calls(callback, "lease_valid_in_transaction")), 2)
        self.assertEqual(len(calls(callback, "lease_valid")), 3)
        self.assertEqual(len(calls(callback, "memory_gate_decision")), 1)
        self.assertIn("_no_side_effects=True", ast.unparse(callback))
        self.assertIn("persistence_primary = exc", ast.unparse(callback))
        lost_handlers = [n for n in ast.walk(callback) if isinstance(n, ast.ExceptHandler)
                         and isinstance(n.type, ast.Name) and n.type.id == "_EventClaimLeaseLost"]
        self.assertEqual(len(lost_handlers), 1)
        self.assertEqual([ast.unparse(n) for n in lost_handlers[0].body], ["return ''"])

    def test_static_caller_routes_existing_defer_and_fenced_finish(self):
        once = qualified(self.jobs_tree, "run_once")
        route = once.body[-2]
        self.assertIsInstance(route, ast.If)
        self.assertIn("outcome[0] == 'defer'", ast.unparse(route.test))
        self.assertEqual(ast.unparse(route.body[0]), "store.defer(job, worker_id, until=outcome[1])")
        self.assertEqual(ast.unparse(route.orelse[0]), "store.finish(job, worker_id, error_code=error_code)")
        for name in ("JobStore.defer", "JobStore.finish"):
            text = ast.unparse(qualified(self.jobs_tree, name))
            for field in ("lease_owner", "lease_generation", "generation", "lease_expires_at", "status"):
                self.assertIn(field, text)


def make_suite(source_raw, source, entry_raw, entry, extractor_raw, extractor, scratch, selected=None, test_raw=None):
    """Common exact-byte suite entry used by unittest and the permanent harness."""
    jobs_tree, entry_tree, extractor_tree = ast.parse(source_raw), ast.parse(entry_raw), ast.parse(extractor_raw)
    scanner_module, scanner_bindings = scanner_ast(entry_raw)
    namespace = {"__builtins__": builtins.__dict__, "__name__": "extraction_source_scanner",
                 "Any": Any, "Dict": Dict, "List": List, "Optional": Optional, "re": re, "json": json}
    code = compile(scanner_module, str(entry), "exec", dont_inherit=True)
    missing = dependency_names(code) - set(namespace) - set(SCANNER_FUNCTIONS + SCANNER_CONSTANTS) - set(dir(builtins))
    if missing:
        raise ValueError("unbound_scanner_globals:" + ",".join(sorted(missing)))
    exec(code, namespace)
    jobs = types.ModuleType("extraction_source_background_jobs")
    jobs.__file__ = str(source)
    exec(compile(source_raw, str(source), "exec", dont_inherit=True), jobs.__dict__)
    cls = ExtractionGuardCompletionTests
    cls.jobs, cls.scanner, cls.jobs_tree = jobs, namespace, jobs_tree
    cls.entry_tree, cls.extractor_tree, cls.scratch = entry_tree, extractor_tree, Path(scratch)
    cls.source_sha256 = digest(source_raw)
    cls.test_sha256 = digest(test_raw if test_raw is not None else Path(__file__).read_bytes())
    ids = unittest.defaultTestLoader.getTestCaseNames(cls)
    chosen = ids if selected is None else list(selected)
    if not chosen or len(chosen) != len(set(chosen)) or not set(chosen).issubset(ids):
        raise ValueError("exact_known_case_roster_required")
    bindings = {"scanner": scanner_bindings, "background": [], "readonly": []}
    for name in ("_run_job", "_run_job.persist_if_current", "_worker_provider", *UNCHANGED_NODES):
        n = qualified(jobs_tree, name)
        bindings["background"].append({"qualified_AST": name, "type": type(n).__name__,
                                       "lines": [n.lineno, n.end_lineno], "ast_sha256": ast_digest(n)})
    for tree, name in ((entry_tree, "MemoryWikiProvider._inspect_recall_text"), (extractor_tree, "extract_session_claims")):
        n = qualified(tree, name)
        bindings["readonly"].append({"qualified_AST": name, "type": type(n).__name__,
                                     "lines": [n.lineno, n.end_lineno], "ast_sha256": ast_digest(n)})
    return unittest.TestSuite(cls(name) for name in chosen), bindings


if __name__ == "__main__":
    root = Path(__file__).absolute().parents[1]
    # Caller owns this non-secret scratch; no implicit profile/config/temp path.
    scratch = Path(os.environ["TMPDIR"]) / "extraction-guard-completion-unittest"
    source, entry, extractor = root / "background_jobs.py", root / "__init__.py", root / "extractor.py"
    suite, _ = make_suite(source.read_bytes(), source, entry.read_bytes(), entry,
                          extractor.read_bytes(), extractor, scratch)
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
