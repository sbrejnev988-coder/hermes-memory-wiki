"""Offline SOURCE regression for observation guard dependency outages.

From a COMPLETE candidate tree, with an explicitly owned TMPDIR:
    python -I -B -S tests/test_observation_guard_unavailable.py
The shipped sibling test supplies readonly AST/scanner helpers, not its suite.
Genuine complete _safe_event, helpers, class and scanner nodes execute against
synthetic guard replies/rows. All three SQL-owning callers are STATIC ONLY.
No package/provider/SDK bootstrap, database, model or authority stand-in runs.
"""
from __future__ import annotations

import ast
import builtins
import hashlib
import json
import os
from pathlib import Path
import re
import types
import unicodedata
from typing import Any, Dict, List, Optional
import unittest

RUNTIME_NODES = (
    "_TOKEN_RE", "_SAFE_TOPIC_RE", "_SAFE_EVENT_ID_RE", "_SOFT_TOKENS",
    "_RAW_EXACT_ONLY_TOPICS", "_RetryableEventGuard", "_bounded_int", "_sha",
    "_normalize_content", "_cluster_key", "_topic", "_safe_event",
)
UNCHANGED_NODES = {
    "_RetryableEventGuard": "9b99b457bfa776f74804b239407d23d83918d8616238d12c38c7963b4dce65b3",
    "_defer_event": "598ecc34cb78d4ef7da69b4e71318387a4ae3cf0e5673621d38bd6c2ffcbe3ca",
    "_consolidate_events": "2fa2f43b5007b92b3c06c14245060aff78d168fa47456e2d9f908132ba9ee3fd",
    "_validated_current_version": "76e8bdfc1115aaac4380c09ea795ae6e40bb1621f77f8511df7dac1c5e9917b5",
    "_invalidate_linked_observation": "d8b877b5f12b92a52ed836cc9ba648151058ae158bbddcdcd672303ebf876011",
}
# Historical peer before graph-intent/settings oracle correspondence repair:
# 45316361785ed197cdd096774a481a1609b760a22490b6590a725d23d48a8eb2
PEER_SHA256 = "4fcf391415f2b1f3bb98900f9c9e9e307468f9ca86e9b58e3aebb4c2bb368bc7"
PRODUCER_SHA256 = "f1492a666c9d648738c01009cfdba976e1610a8beec1e06c2b8b072279619fd9"
SAFE_TEXT = "The observatory owns the violet telescope."


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def ast_digest(node):
    return digest(ast.dump(node, include_attributes=False).encode("utf-8"))


def same_expr(node, expression):
    return ast.dump(node, include_attributes=False) == ast.dump(
        ast.parse(expression, mode="eval").body, include_attributes=False)


def calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and
            ((isinstance(n.func, ast.Name) and n.func.id == name) or
             (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


def literal_strings(node):
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def selected_ast(tree, names, qualified):
    nodes = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
    origins = []
    for name in names:
        matches = [n for n in tree.body if
                   (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name) or
                   (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))]
        if len(matches) != 1:
            raise ValueError("unique_runtime_node_required:" + name)
        node = matches[0]
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.decorator_list:
            raise ValueError("undecorated_runtime_node_required")
        nodes.append(node)
        origins.append({"qualified_AST": name, "type": type(node).__name__,
                        "lines": [node.lineno, node.end_lineno], "ast_sha256": ast_digest(node)})
    return ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), origins


class GuardInput:
    """Explicit synthetic typed reply producer. Not a provider or SDK object."""
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def _inspect_recall_text(self, raw, **kwargs):
        self.calls.append((raw, kwargs))
        if isinstance(self.reply, BaseException):
            raise self.reply
        return dict(self.reply) if isinstance(self.reply, dict) else self.reply


class ScannerInput:
    """Genuine source scanner, with optional explicitly synthetic fault input."""
    def __init__(self, scanner, failure=None, fail_at=1):
        self.scanner, self.failure, self.fail_at, self.calls = scanner, failure, fail_at, 0

    def secret_scan(self, text):
        self.calls += 1
        if self.failure is not None and self.calls == self.fail_at:
            raise self.failure
        return self.scanner(text)


def event(text=SAFE_TEXT, **changes):
    row = {"event_id": "evt_fixture_1", "content": text, "content_hash": digest(text.encode("utf-8")),
           "event_type": "fact", "turn_id": "turn-fixture", "role": "observer",
           "occurred_at": 11, "observed_at": 12, "created_at": 13, "expires_at": 9999999999}
    row.update(changes)
    return row


class ObservationGuardUnavailableTests(unittest.TestCase):
    def setUp(self):
        # Declare the actual default-dependent argument; never borrow ambient settings.
        self.old_limit = os.environ.get("MEMORY_WIKI_OBSERVATION_EVENT_CONTENT")
        os.environ["MEMORY_WIKI_OBSERVATION_EVENT_CONTENT"] = "1600"

    def tearDown(self):
        if self.old_limit is None:
            os.environ.pop("MEMORY_WIKI_OBSERVATION_EVENT_CONTENT", None)
        else:
            os.environ["MEMORY_WIKI_OBSERVATION_EVENT_CONTENT"] = self.old_limit

    def fixture(self, reply=None, row=None, failure=None, fail_at=1):
        guard = GuardInput({"status": "safe", "content": SAFE_TEXT} if reply is None else reply)
        scanner = ScannerInput(self.scanner["secret_scan"], failure, fail_at)
        return guard, scanner, event() if row is None else row

    def evaluate(self, fixture):
        return self.runtime["_safe_event"](*fixture)

    def retry(self, reply, reason, **options):
        fixture = self.fixture(reply, **options)
        with self.assertRaises(self.runtime["_RetryableEventGuard"]) as caught:
            self.evaluate(fixture)
        self.assertEqual(caught.exception.reason, reason)
        self.assertEqual(caught.exception.args, (reason,))
        return caught.exception, fixture

    def permanent(self, status):
        fixture = self.fixture({"status": status, "content": SAFE_TEXT})
        self.assertIsNone(self.evaluate(fixture))
        self.assertEqual(len(fixture[0].calls), 1)
        self.assertEqual(fixture[1].calls, 1)

    def test_typed_unavailable_retries(self):
        fixture = self.fixture({"status": "guard_unavailable_quarantined", "content": "",
                                "trust_level": "quarantined", "injection_signals": [], "guard_disagreement": True})
        observed, reason, cause = "not_returned", None, None
        try:
            result = self.evaluate(fixture)
            observed = "permanent_none" if result is None else "accepted"
        except self.runtime["_RetryableEventGuard"] as exc:
            observed, reason = "retryable", exc.reason
            cause = None if exc.__cause__ is None else type(exc.__cause__).__name__
        witness = {"source_sha256": self.source_sha256, "test_sha256": self.test_sha256,
                   "guard_input": "guard_unavailable_quarantined", "outcome": observed, "reason": reason,
                   "cause_type": cause, "guard_calls": len(fixture[0].calls), "scanner_calls": fixture[1].calls,
                   "SQLite_connections": 0, "caller_effects_executed": False}
        witness["outcome_sha256"] = digest(json.dumps(witness, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        target = self.scratch / self._testMethodName / "witness.json"
        target.parent.mkdir(parents=True, exist_ok=False)
        with target.open("xb") as stream:
            stream.write((json.dumps(witness, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        # Durable hashed witness precedes the discriminating baseline assertion.
        self.assertEqual(observed, "retryable", "typed_unavailable_was_permanent_none")
        self.assertEqual(reason, "recall_guard_unavailable")
        self.assertIsNone(cause)
        self.assertEqual(fixture[1].calls, 1)

    def test_unavailable_with_content_still_defers(self):
        self.retry({"status": "guard_unavailable_quarantined", "content": SAFE_TEXT}, "recall_guard_unavailable")

    def test_same_event_recovers_after_guard_returns(self):
        _, fixture = self.retry({"status": "guard_unavailable_quarantined", "content": ""}, "recall_guard_unavailable")
        before = dict(fixture[2])
        fixture[0].reply = {"status": "safe", "content": SAFE_TEXT}
        safe = self.evaluate(fixture)
        self.assertEqual(fixture[2], before)
        self.assertEqual(safe["event_id"], before["event_id"])
        self.assertEqual(safe["content"], SAFE_TEXT)

    def test_legacy_runtime_failure_reason(self):
        self.retry({"status": "runtime_failure_quarantined"}, "recall_guard_runtime_failure")

    def test_legacy_runtime_failure_substring(self):
        self.retry({"status": "legacy_runtime_failure_result"}, "recall_guard_runtime_failure")

    def test_legacy_empty_status(self):
        self.retry({"status": "", "content": SAFE_TEXT}, "recall_guard_runtime_failure")

    def test_legacy_missing_status(self):
        self.retry({"content": SAFE_TEXT}, "recall_guard_runtime_failure")

    def test_legacy_invalid_guard_result(self):
        self.retry(["safe", SAFE_TEXT], "recall_guard_invalid_result")

    def test_raised_guard_preserves_cause(self):
        primary = RuntimeError("synthetic guard unavailable")
        caught, _ = self.retry(primary, "recall_guard_unavailable")
        self.assertIs(caught.__cause__, primary)

    def test_raw_scan_exception_preserves_cause(self):
        primary = RuntimeError("synthetic raw scanner failure")
        caught, fixture = self.retry({"status": "safe", "content": SAFE_TEXT}, "secret_scan_unavailable", failure=primary)
        self.assertIs(caught.__cause__, primary)
        self.assertEqual(fixture[0].calls, [])

    def test_projected_scan_exception_preserves_cause(self):
        primary = RuntimeError("synthetic projected scanner failure")
        caught, fixture = self.retry({"status": "safe", "content": SAFE_TEXT}, "secret_scan_unavailable", failure=primary, fail_at=2)
        self.assertIs(caught.__cause__, primary)
        self.assertEqual(fixture[1].calls, 2)

    def test_guard_cancellation_preserves_identity(self):
        primary = KeyboardInterrupt("synthetic cancellation")
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.evaluate(self.fixture(primary))
        self.assertIs(caught.exception, primary)

    def test_raw_scan_baseexception_preserves_identity(self):
        primary = SystemExit(17)
        fixture = self.fixture(failure=primary)
        with self.assertRaises(SystemExit) as caught:
            self.evaluate(fixture)
        self.assertIs(caught.exception, primary)
        self.assertEqual(fixture[0].calls, [])

    def test_projected_scan_baseexception_preserves_identity(self):
        primary = KeyboardInterrupt("synthetic projected cancellation")
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.evaluate(self.fixture(failure=primary, fail_at=2))
        self.assertIs(caught.exception, primary)

    def test_permanent_quarantine(self):
        self.permanent("quarantined")

    def test_permanent_guard_disagreement(self):
        self.permanent("quarantined_guard_disagreement")

    def test_permanent_local_filter(self):
        self.permanent("local_filter_quarantined")

    def test_unknown_and_near_match_statuses_stay_permanent(self):
        for status in ("unknown", "guard_unavailable", "guard_unavailable_quarantined_extra", "GUARD_UNAVAILABLE_QUARANTINED", " guard_unavailable_quarantined"):
            self.permanent(status)

    def test_raw_secret_refused_before_unavailable_guard(self):
        raw = "api_key=synthetic-canary-not-a-real-credential"
        self.assertTrue(self.scanner["secret_scan"](raw)["raw_secret"])
        fixture = self.fixture({"status": "guard_unavailable_quarantined"}, event(raw))
        self.assertIsNone(self.evaluate(fixture))
        self.assertEqual(fixture[0].calls, [])

    def test_projected_secret_refused(self):
        secret = "password=synthetic-canary-not-a-real-credential"
        self.assertTrue(self.scanner["secret_scan"](secret)["raw_secret"])
        fixture = self.fixture({"status": "safe", "content": secret})
        self.assertIsNone(self.evaluate(fixture))
        self.assertEqual(fixture[1].calls, 2)

    def test_hash_refusal_before_guard(self):
        fixture = self.fixture({"status": "guard_unavailable_quarantined"}, event(content_hash="0" * 64))
        self.assertIsNone(self.evaluate(fixture))
        self.assertEqual(fixture[0].calls, [])
        self.assertEqual(fixture[1].calls, 0)

    def test_event_id_refusal_before_guard(self):
        fixture = self.fixture(row=event(event_id="not-an-event"))
        self.assertIsNone(self.evaluate(fixture))
        self.assertEqual(fixture[0].calls, [])
        self.assertEqual(fixture[1].calls, 0)

    def test_malformed_event_refused(self):
        fixture = self.fixture(row={})
        self.assertIsNone(self.evaluate(fixture))
        self.assertEqual(fixture[0].calls, [])

    def test_empty_guard_content_refused(self):
        self.assertIsNone(self.evaluate(self.fixture({"status": "safe", "content": " \t "})))

    def test_noncanonical_guard_content_refused(self):
        self.assertIsNone(self.evaluate(self.fixture({"status": "safe", "content": "... !!!"})))

    def test_invalid_topic_refused(self):
        self.assertIsNone(self.evaluate(self.fixture(row=event(event_type="not a topic"))))

    def test_healthy_normalization_and_metadata(self):
        content = "  The ＶＩＯＬＥＴ telescope, is READY!  "
        fixture = self.fixture({"status": "safe", "content": content}, event(role="", occurred_at=-1, event_type=" Fact "))
        original = dict(fixture[2])
        safe = self.evaluate(fixture)
        self.assertEqual(safe, {"event_id": "evt_fixture_1", "content": content.strip(),
            "normalized": "the violet telescope is ready", "cluster_key": "violet telescope is ready",
            "exact_only": False, "topic": "fact", "turn_id": "turn-fixture", "role": "observer",
            "content_hash": digest(content.strip().encode("utf-8")), "occurred_at": 0,
            "observed_at": 12, "created_at": 13, "expires_at": 9999999999})
        self.assertEqual(fixture[2], original)
        self.assertEqual(fixture[0].calls, [(SAFE_TEXT, {"source": "observation:event_evidence", "mem_type": "event",
            "item_id": "evt_fixture_1", "audit": False, "max_len": 1600})])
        self.assertEqual(fixture[1].calls, 2)

    def test_exact_only_topics_keep_article(self):
        for topic in ("dialogue_turn", "visual_ocr"):
            safe = self.evaluate(self.fixture(row=event(event_type=topic)))
            self.assertTrue(safe["exact_only"])
            self.assertEqual(safe["cluster_key"], safe["normalized"])
            self.assertEqual(safe["normalized"], "the observatory owns the violet telescope")

    def guard_try(self, function, target):
        matches = [n for n in ast.walk(function) if isinstance(n, ast.Try) and any(
            isinstance(s, ast.Assign) and any(isinstance(t, ast.Name) and t.id == target for t in s.targets)
            and isinstance(s.value, ast.Call) and isinstance(s.value.func, ast.Name) and s.value.func.id == "_safe_event"
            for s in n.body)]
        self.assertEqual(len(matches), 1)
        node = matches[0]
        self.assertEqual(len(node.handlers), 1)
        handler = node.handlers[0]
        self.assertIsInstance(handler.type, ast.Name)
        self.assertEqual(handler.type.id, "_RetryableEventGuard")
        self.assertEqual(handler.name, "exc")
        self.assertFalse(calls(handler, "_invalidate_linked_observation"))
        self.assertFalse(calls(handler, "execute"))
        self.assertEqual(len(calls(handler, "_defer_event")), 1)
        reason = next(k.value for k in calls(handler, "_defer_event")[0].keywords if k.arg == "reason")
        self.assertTrue(same_expr(reason, "exc.reason"))
        return node, handler

    def test_static_producer_typed_empty_unavailable(self):
        producer = self.peer.qualified(self.entry_tree, "MemoryWikiProvider._inspect_recall_text")
        self.assertEqual(ast_digest(producer), PRODUCER_SHA256)
        branches = [n for n in ast.walk(producer) if isinstance(n, ast.If) and
                    same_expr(n.test, "strict and not (_INJECTION_GUARD_AVAILABLE and _sanitize_recalled)")]
        self.assertEqual(len(branches), 1)
        returned = branches[0].body[0]
        self.assertIsInstance(returned, ast.Return)
        self.assertIsInstance(returned.value, ast.Dict)
        values = {k.value: v for k, v in zip(returned.value.keys, returned.value.values) if isinstance(k, ast.Constant)}
        self.assertEqual(values["status"].value, "guard_unavailable_quarantined")
        self.assertEqual(values["content"].value, "")

    def test_static_initial_retry_vs_permanent_rejection(self):
        function = self.peer.qualified(self.source_tree, "_consolidate_events")
        node, handler = self.guard_try(function, "event")
        self.assertIsInstance(handler.body[-1], ast.Continue)
        self.assertEqual(len(calls(handler, "check_lease")), 1)
        self.assertTrue(any(same_expr(n, "deferred_ids.add(raw_event_id)") for n in calls(handler, "add")))
        rejected = next(n for n in ast.walk(function) if isinstance(n, ast.If) and same_expr(n.test, "event is None"))
        self.assertLess(node.end_lineno, rejected.lineno)
        self.assertEqual(len(calls(rejected, "_invalidate_linked_observation")), 1)
        self.assertTrue(any("VALUES(?,'rejected','',?)" in s for s in literal_strings(rejected)))
        self.assertIn("DELETE FROM memory_observation_event_retries WHERE event_id=?", literal_strings(rejected))

    def test_static_support_retry_preserves_support_pass(self):
        function = self.peer.qualified(self.source_tree, "_consolidate_events")
        node, handler = self.guard_try(function, "safe")
        self.assertIsInstance(handler.body[-1], ast.Continue)
        self.assertTrue(any(isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and n.value.value is True
            and any(isinstance(t, ast.Name) and t.id == "support_deferred" for t in n.targets) for n in handler.body))
        self.assertTrue(any(same_expr(n, "support_deferred_ids.add(support_event_id)") for n in calls(handler, "add")))
        safe = next(n for n in ast.walk(function) if isinstance(n, ast.If) and same_expr(n.test, "safe is not None"))
        self.assertLess(node.end_lineno, safe.lineno)
        self.assertEqual(len(calls(ast.Module(body=safe.orelse, type_ignores=[]), "_invalidate_linked_observation")), 1)
        hold = next(n for n in ast.walk(function) if isinstance(n, ast.If) and same_expr(n.test, "support_deferred"))
        self.assertIsInstance(hold.body[0], ast.Continue)
        self.assertLess(hold.lineno, calls(function, "_write_version")[0].lineno)

    def test_static_validation_retry_vs_invalidation(self):
        function = self.peer.qualified(self.source_tree, "_validated_current_version")
        node, handler = self.guard_try(function, "safe_event")
        self.assertIsInstance(handler.body[-1], ast.Return)
        self.assertIsNone(handler.body[-1].value.value)
        rejected = next(n for n in ast.walk(function) if isinstance(n, ast.If) and same_expr(n.test, "safe_event is None"))
        self.assertLess(node.end_lineno, rejected.lineno)
        self.assertEqual(len(calls(rejected, "_invalidate_linked_observation")), 1)
        self.assertTrue(any("VALUES(?,'rejected','',?)" in s for s in literal_strings(rejected)))
        self.assertIn("DELETE FROM memory_observation_event_retries WHERE event_id=?", literal_strings(rejected))

    def test_static_retry_schema_backoff_and_invalidation_unchanged(self):
        for name in ("_RetryableEventGuard", "_defer_event", "_invalidate_linked_observation"):
            self.assertEqual(ast_digest(self.peer.qualified(self.source_tree, name)), UNCHANGED_NODES[name])
        defer = self.peer.qualified(self.source_tree, "_defer_event")
        self.assertIn("memory_observation_event_retries", " ".join(literal_strings(defer)))
        self.assertEqual(len(calls(defer, "execute")), 2)
        self.assertIsInstance(defer.body[-1], ast.Return)
        self.assertTrue(same_expr(defer.body[-1].value, "retry_after"))

    def test_static_three_actual_callers_and_guards_unchanged(self):
        self.assertEqual(len(calls(self.source_tree, "_safe_event")), 3)
        for name, count in (("_consolidate_events", 2), ("_validated_current_version", 1)):
            node = self.peer.qualified(self.source_tree, name)
            self.assertEqual(ast_digest(node), UNCHANGED_NODES[name])
            self.assertEqual(len(calls(node, "_safe_event")), count)


def make_suite(source_raw, source, entry_raw, entry, scratch, selected=None, test_raw=None, peer_raw=None, peer_path=None):
    """Shipped stdlib-only entry; no helper outside the candidate is required."""
    peer_path = Path(__file__).with_name("test_extraction_guard_completion.py") if peer_path is None else Path(peer_path)
    peer_raw = peer_path.read_bytes() if peer_raw is None else peer_raw
    if peer_path.name != "test_extraction_guard_completion.py" or digest(peer_raw) != PEER_SHA256:
        raise ValueError("exact_shipped_readonly_peer_required")
    peer = types.ModuleType("observation_readonly_shipped_helpers")
    peer.__file__ = str(peer_path)
    exec(compile(peer_raw, str(peer_path), "exec", dont_inherit=True), peer.__dict__)
    source_tree, entry_tree = ast.parse(source_raw), ast.parse(entry_raw)
    scanner_ast, scanner_bindings = peer.scanner_ast(entry_raw)
    scanner = {"__builtins__": builtins.__dict__, "__name__": "observation_genuine_scanner",
               "re": re, "json": json, "Any": Any, "Dict": Dict, "List": List, "Optional": Optional}
    scanner_code = compile(scanner_ast, str(entry), "exec", dont_inherit=True)
    missing = peer.dependency_names(scanner_code) - set(scanner) - set(peer.SCANNER_FUNCTIONS + peer.SCANNER_CONSTANTS) - set(dir(builtins))
    if missing:
        raise ValueError("unbound_scanner_globals:" + ",".join(sorted(missing)))
    exec(scanner_code, scanner)
    runtime_ast, runtime_bindings = selected_ast(source_tree, RUNTIME_NODES, peer.qualified)
    runtime = {"__builtins__": builtins.__dict__, "__name__": "observation_genuine_classifier",
               "re": re, "os": os, "hashlib": hashlib, "unicodedata": unicodedata, "Any": Any}
    code = compile(runtime_ast, str(source), "exec", dont_inherit=True)
    missing = peer.dependency_names(code) - set(runtime) - set(RUNTIME_NODES) - set(dir(builtins))
    if missing:
        raise ValueError("unbound_classifier_globals:" + ",".join(sorted(missing)))
    exec(code, runtime)
    cls = ObservationGuardUnavailableTests
    cls.runtime, cls.scanner, cls.peer = runtime, scanner, peer
    cls.source_tree, cls.entry_tree, cls.scratch = source_tree, entry_tree, Path(scratch)
    cls.source_sha256 = digest(source_raw)
    cls.test_sha256 = digest(Path(__file__).read_bytes() if test_raw is None else test_raw)
    ids = unittest.defaultTestLoader.getTestCaseNames(cls)
    chosen = ids if selected is None else list(selected)
    if not chosen or len(chosen) != len(set(chosen)) or not set(chosen).issubset(ids):
        raise ValueError("exact_known_case_roster_required")
    static_bindings = []
    for tree, name in [(source_tree, name) for name in UNCHANGED_NODES] + [(entry_tree, "MemoryWikiProvider._inspect_recall_text")]:
        node = peer.qualified(tree, name)
        static_bindings.append({"qualified_AST": name, "type": type(node).__name__,
                                "lines": [node.lineno, node.end_lineno], "ast_sha256": ast_digest(node)})
    return unittest.TestSuite(cls(name) for name in chosen), {"classifier": runtime_bindings,
        "scanner": scanner_bindings, "static_only": static_bindings}


if __name__ == "__main__":
    root = Path(__file__).absolute().parents[1]
    source, entry = root / "memory_observations.py", root / "__init__.py"
    scratch = Path(os.environ["TMPDIR"]) / "observation-guard-unavailable-unittest"
    suite, _ = make_suite(source.read_bytes(), source, entry.read_bytes(), entry, scratch)
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
