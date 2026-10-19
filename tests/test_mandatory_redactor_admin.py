"""Self-contained stdlib SOURCE regressions; never import the provider package.

Run the standard unittest text runner directly, NOT pytest ancestor collection:
  python -I -B -S -X utf8 tests/test_mandatory_redactor_admin.py --scratch <new-owned-dir>
--source/--graph optionally select historical full source files; --case selects
one main unittest ID. No evidence-only peer, SDK, database or network is needed.
The selector follows test_restore_erasure_namespace.py's exact-AST pattern.

Roles: original complete method/function bodies, regex assignments and required
class literal are SOURCE-extracted. Receiver, graph-stage resolver-only adapter,
SQL/transaction-context observers and fault injectors are synthetic, not
authority/SDK stand-ins; the real owning-TX API is NOT executed by this suite.
The atomic writer and terminal sinks use real stdlib files in explicit scratch.
This does not qualify full provider imports, SQLite, native/CLI or OS isolation.
"""
from __future__ import annotations

import argparse
import ast
import builtins
from contextlib import contextmanager
import dis
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import types
from typing import Any, Callable, Dict, List, Optional, Tuple
import unittest
import urllib.error

ENTRY_FUNCTIONS = (
    "now", "short", "clamp", "atomic_write", "_safe_exception_label",
    "_sensitive_secret_field", "_quoted_secret_assignment_is_raw",
    "_redact_quoted_secret_assignment", "_balanced_secret_container_end",
    "_redact_quoted_secret_containers", "redact_secrets",
    "scrub_memory_artifacts", "secret_scan", "is_ephemeral_fragment",
)
ENTRY_CONSTANTS = (
    "_CODE_SHRINKER_TERMINAL_NAME_RE", "SYSTEM_NOTE_RE", "MEMORY_CONTEXT_RE",
    "MODEL_SWITCH_ARTIFACT_RE", "TRANSIENT_API_ARTIFACT_RE",
    "TOOL_ARTIFACT_HINT_RE", "PATH_ONLY_RE", "RAW_BLOB_HINT_RE",
    "SECRET_PATTERNS", "SECRET_FIELD_RE", "SECRET_ASSIGN_RE",
    "QUOTED_SECRET_ASSIGN_RE", "QUOTED_SECRET_CONTAINER_RE",
    "REDaction_MARKER_RE", "REDACTION_TOKEN_RE",
)
METHODS = (
    "_redact_code_graph_text", "_code_shrinker_terminal_filename",
    "_scrub_code_graph_terminal_artifacts", "_scrub_secrets",
)
GRAPH_FUNCTIONS = (
    "_sha", "_json", "_opaque_graph_id_v1", "_clean_text", "_redact_graph_text",
    "_redact_graph_identity", "_is_graph_integrity_digest",
    "_provider_graph_redactor", "sanitize_code_graph_event_for_recovery",
    "_sanitize_graph_event_for_storage", "_redact_graph_storage_value",
)
GRAPH_CONSTANTS = (
    "_PEM_BLOCK_RE", "_SENSITIVE_EVENT_KEY_RE", "_OPAQUE_GRAPH_ID_RE",
    "_OPAQUE_GRAPH_ID_PREFIX", "_GRAPH_INTEGRITY_FIELDS", "_GRAPH_IDENTITY_FIELDS",
)
REQUIREMENT = "_requires_full_code_graph_redactor"
# Invented fixture strings only, never user credentials. Witnesses contain hashes
# and boolean recognition results, not the synthetic source text.
BARE = "ghp_" + "SYNTHETIC0123456789ABCD"
ASSIGNMENT = "OWNED_FIXTURE_0123456789"
MIXED = "ordinary note " + BARE + " password=" + ASSIGNMENT
SECRET_REF = "sec_001122334455"
SAFE_NAME = "event-" + "a" * 64 + ".json.error.json"
ACTIVE_SINK = None


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def dependency_names(code):
    names = {i.argval for i in dis.get_instructions(code) if i.opname == "LOAD_GLOBAL"}
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            names |= dependency_names(value)
    return names


def selected_ast(raw, kind):
    """Same bounded named-definition selection as the shipped restore regression."""
    tree = ast.parse(raw)
    functions = ENTRY_FUNCTIONS if kind == "entry" else GRAPH_FUNCTIONS
    constants = ENTRY_CONSTANTS if kind == "entry" else GRAPH_CONSTANTS
    nodes, origins = [], []

    def take(matches, qualified):
        if len(matches) != 1:
            raise ValueError("unique_source_binding_required:" + qualified)
        node = matches[0]
        origins.append({"qualified_AST": qualified, "node": type(node).__name__,
                        "lines": [node.lineno, node.end_lineno],
                        "ast_sha256": digest(ast.dump(node, include_attributes=False).encode())})
        return node

    for name in constants:
        nodes.append(take([n for n in tree.body if isinstance(n, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)], name))
    for name in functions:
        node = take([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name], name)
        if node.decorator_list:
            raise ValueError("undecorated_source_function_required:" + name)
        nodes.append(node)
    if kind == "entry":
        # The original fallback function is selected, not the ImportError branch
        # or any SDK/module bootstrap. Its safe import-error label is synthetic.
        fallback = take([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                         and n.name == "_code_graph_unavailable"],
                        "code_graph_import_fallback._code_graph_unavailable")
        nodes.append(fallback)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MemoryWikiProvider")
        body = [take([n for n in cls.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == REQUIREMENT for t in n.targets)],
                     "MemoryWikiProvider." + REQUIREMENT)]
        for name in METHODS:
            body.append(take([n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name],
                             "MemoryWikiProvider." + name))
        # Only the scaffold is synthetic: no MemoryProvider base or constructor.
        scaffold = ast.ClassDef(name="SourceMethods", bases=[], keywords=[], body=body,
                                decorator_list=[], type_params=[])
        nodes.append(ast.copy_location(scaffold, cls))
    future = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
    return ast.fix_missing_locations(ast.Module(body=future + nodes, type_ignores=[])), origins


def load_functions(raw, source, graph_raw, graph_source):
    common = {"__builtins__": builtins.__dict__, "Path": Path, "Any": Any,
              "Callable": Callable, "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple,
              "hashlib": hashlib, "json": json, "os": os, "re": re,
              "tempfile": tempfile, "time": time, "urllib": urllib}
    graph = {**common, "__name__": "mandatory_redactor_source_graph"}
    entry = {**common, "__name__": "mandatory_redactor_source_methods",
             "_CODE_GRAPH_IMPORT_ERROR": "ImportError"}
    bindings = {}
    for kind, content, path, namespace in (("graph", graph_raw, graph_source, graph),
                                           ("entry", raw, source, entry)):
        selected, bindings[kind] = selected_ast(content, kind)
        code = compile(selected, str(path), "exec", dont_inherit=True)
        defined = set(GRAPH_FUNCTIONS + GRAPH_CONSTANTS if kind == "graph"
                      else ENTRY_FUNCTIONS + ENTRY_CONSTANTS + ("SourceMethods", "_code_graph_unavailable"))
        external = {"_resolve_code_graph_redactor", "_sanitize_code_graph_event_for_recovery",
                    "_scrub_code_graph_storage", "_debug_log"} if kind == "entry" else set()
        missing = dependency_names(code) - set(namespace) - defined - external - set(dir(builtins))
        if missing:
            raise ValueError("unbound_source_dependencies:" + ",".join(sorted(missing)))
        exec(code, namespace)
    entry["_resolve_code_graph_redactor"] = graph["_provider_graph_redactor"]
    entry["_sanitize_code_graph_event_for_recovery"] = graph["sanitize_code_graph_event_for_recovery"]
    return entry, graph, bindings


def observe_sink(event, args):
    """Passive primitive observer, separate from every fault injector."""
    active = ACTIVE_SINK
    if active is None or not args or isinstance(args[0], int):
        return
    code = None
    if event == "open":
        _, mode, flags = args
        if bool((flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)) or any(c in (mode or "") for c in "wax+"):
            code = "write_open"
    elif event in ("os.rename", "os.remove"):
        code = {"os.rename": "rename", "os.remove": "remove"}[event]
    if code is not None and Path(args[0]).is_relative_to(active["root"]):
        active["counts"][code] += 1


sys.addaudithook(observe_sink)


class Rows:
    def __init__(self, values):
        self.values = values

    def fetchall(self):
        return self.values


class SQLObserver:
    """Synthetic exact-query observer, deliberately not SQLite or an authority."""
    TABLES = ("claims", "evidence", "review_queue", "secret_index", "task_capsules",
              "entities", "relations", "project_profiles", "post_task_log", "preference_rules")

    def __init__(self):
        self.row = None
        self.selects = 0
        self.updates = 0
        self.pending = 0
        self.committed_updates = 0
        self.context_errors = []
        self.in_transaction = False  # Synthetic context observation, not SQLite.

    def execute(self, sql, params=()):
        if sql in ["SELECT * FROM " + table + " LIMIT 5000" for table in self.TABLES]:
            self.selects += 1
            return Rows([dict(self.row)] if "FROM entities " in sql and self.row is not None else [])
        if sql == "UPDATE entities SET notes=? WHERE id=?" and self.row is not None and params[-1] == self.row["id"]:
            self.row["notes"] = params[0]
            self.updates += 1
            self.pending += 1
            return Rows([])
        raise AssertionError("unexpected_synthetic_SQL_shape")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.committed_updates += self.pending
        else:
            self.context_errors.append(exc)
        self.pending = 0
        return False


def receiver_class(methods):
    base = methods["SourceMethods"]

    class Receiver(base):
        """Authored receiver; no native provider base, grant or bootstrapping."""
        def __init__(self, home):
            self.home = home
            self.sql = SQLObserver()
            self._lock = threading.RLock()
            self.transaction_calls = []
            self.callback_mode = "healthy"
            self.terminal_calls = 0
            self.terminal_primary = None
            self.graph_primary = None
            self.audits = []
            self.rebuilds = 0
            self.renders = 0
            self.quarantines = 0

        def __getattribute__(self, name):
            if name == "_redact_code_graph_text" and object.__getattribute__(self, "callback_mode") == "missing":
                raise AttributeError("synthetic_missing_callback")
            return super().__getattribute__(name)

        def _connect(self):
            return self.sql

        @contextmanager
        def _claim_transaction(self, conn):
            # Only observe the new call/grain role. This is NOT the product
            # owning API or a grant of SQL/SDK authority; native is NOT_RUN.
            if conn is not self.sql or conn.in_transaction:
                raise AssertionError("unexpected_synthetic_transaction_context")
            self.transaction_calls.append(("enter", conn.updates, conn.committed_updates))
            conn.in_transaction = True
            try:
                with conn:
                    yield conn
            finally:
                conn.in_transaction = False
                self.transaction_calls.append(("exit", conn.updates, conn.committed_updates))

        def _make_secret_index_from_raw(self, *args):
            return SECRET_REF

        def _quarantine_secret(self, *args):
            self.quarantines += 1

        def _upsert_fts(self, *args):
            raise AssertionError("claims_path_not_in_this_SOURCE_packet")

        def _rebuild_fts(self):
            self.rebuilds += 1

        def _render_active_dashboard(self):
            self.renders += 1

        def _audit(self, *args):
            self.audits.append(args)

        def _scrub_code_graph_terminal_artifacts(self, **kwargs):
            self.terminal_calls += 1
            try:
                return base._scrub_code_graph_terminal_artifacts(self, **kwargs)
            except BaseException as exc:
                self.terminal_primary = exc
                raise

    return Receiver


class MandatoryRedactorAdminTests(unittest.TestCase):
    def setUp(self):
        self.root = self.scratch / self._testMethodName
        self.root.mkdir(parents=True, exist_ok=False)
        self.provider = self.Receiver(self.root / "owned-home")
        self.terminal_root = self.provider.home / "context-coordination"
        self.done = self.terminal_root / "done" / "code-shrinker"
        self.dead = self.terminal_root / "dead-letter" / "code-shrinker"
        self.done.mkdir(parents=True)
        self.dead.mkdir(parents=True)
        self.graph_calls = 0
        self.graph_fault = None
        self.graph_counts = {"rows": 0, "fields": 0, "scanned_rows": 0, "batches": 0}
        self.debug = []
        self.sink_counts = {"write_open": 0, "rename": 0, "remove": 0}
        self.methods["atomic_write"] = self.original_atomic
        self.methods["_resolve_code_graph_redactor"] = self.graph["_provider_graph_redactor"]
        self.methods["_scrub_code_graph_storage"] = self.graph_stage
        self.methods["_debug_log"] = self.debug.append

    def graph_stage(self, provider, conn, *, apply, limit):
        # Resolver is genuine SOURCE. All remaining graph storage behavior is
        # NOT_RUN: this adapter has no SQL engine and returns synthetic zero counts.
        self.graph_calls += 1
        self.assertIs(provider, self.provider)
        self.assertIs(conn, provider.sql)
        self.assertIs(apply, True)
        self.assertEqual(limit, 5000)
        try:
            self.graph["_provider_graph_redactor"](provider)
            if self.graph_fault is not None:
                raise self.graph_fault
        except BaseException as exc:
            provider.graph_primary = exc
            raise
        return dict(self.graph_counts)

    def fixture(self, name="legacy.json", *, root=None, raw=None):
        path = (root or self.done) / name
        content = raw if raw is not None else (json.dumps({"notes": MIXED}) + "\n").encode("utf-8")
        with path.open("xb") as out:
            out.write(content)
        return path

    def table_fixture(self):
        self.provider.sql.row = {"id": "owned-entity", "name": "ordinary entity", "aliases": "", "notes": MIXED}

    def snapshot(self):
        return [{"path": p.relative_to(self.terminal_root).as_posix(), "bytes": len(raw), "sha256": digest(raw)}
                for p in sorted(self.terminal_root.rglob("*.json")) for raw in [p.read_bytes()]]

    def call(self, callback, **kwargs):
        global ACTIVE_SINK
        if ACTIVE_SINK is not None:
            raise AssertionError("overlapping_sink_observer")
        ACTIVE_SINK = {"root": self.terminal_root, "counts": self.sink_counts}
        try:
            try:
                return callback(**kwargs), None
            except BaseException as exc:
                return None, exc
        finally:
            ACTIVE_SINK = None

    def admin(self, apply=True):
        return self.call(self.provider._scrub_secrets, apply=apply, limit=200)

    def terminal(self, apply=True):
        return self.call(self.provider._scrub_code_graph_terminal_artifacts, apply=apply, limit=200)

    def assert_no_success(self):
        self.assertEqual(self.provider.audits, [])
        self.assertEqual((self.provider.rebuilds, self.provider.renders), (0, 0))

    def witness(self, value):
        raw = (json.dumps(value, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
        with (self.root / "witness.json").open("xb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())

    def refuse_terminal(self, callback, *, missing=False):
        self.fixture()
        # Malformed data must not escape required admission via digest-only stub
        # or benign filename migration either.
        self.fixture("malformed.error.json", root=self.dead, raw=b"{owned malformed")
        before = self.snapshot()
        if missing:
            self.provider.callback_mode = "missing"
        else:
            self.provider._redact_code_graph_text = callback
        result, error = self.terminal()
        self.assertIsNone(result)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(str(error), "code graph redaction failed")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sink_counts, {"write_open": 0, "rename": 0, "remove": 0})
        self.assert_no_success()

    def test_graph_scalar_integrity_digests_preserved_exact(self):
        redact = self.graph["_redact_graph_storage_value"]
        full = self.provider._redact_code_graph_text
        # The native counterexample is this exact b*64 scalar, not JSON text.
        self.assertNotEqual(full("b" * 64), "b" * 64)
        for key in sorted(self.graph["_GRAPH_INTEGRITY_FIELDS"]):
            values = ("b" * 64, "A1" * 32, "1" * 64)
            if key == "commit_sha":
                values += ("abc1234", "A1" * 20)
            else:
                values += ("sha256:" + "b" * 64,)
            for value in values:
                self.assertTrue(self.graph["_is_graph_integrity_digest"](key, value))
                self.assertEqual(redact(value, full, key=key), value)
        self.assertEqual(redact("b" * 64, full, key="SNAPSHOT_HASH"), "b" * 64)
        self.assertEqual(redact("ordinary note exact", full, key="notes"), "ordinary note exact")

    def test_graph_scalar_integrity_names_do_not_exempt_invalid_or_secret_values(self):
        redact = self.graph["_redact_graph_storage_value"]
        full = self.provider._redact_code_graph_text
        for key in sorted(self.graph["_GRAPH_INTEGRITY_FIELDS"]):
            for value in (BARE, MIXED, "b" * 65, "g" * 64, "sha256:" + "b" * 63):
                self.assertFalse(self.graph["_is_graph_integrity_digest"](key, value))
                safe = redact(value, full, key=key)
                self.assertEqual(safe, self.graph["_redact_graph_text"](value, 40_000, full))
                self.assertNotEqual(safe, value)
                self.assertFalse(BARE in safe or ASSIGNMENT in safe)
        for value in ("abc123", "b" * 65, "sha256:" + "b" * 64):
            self.assertFalse(self.graph["_is_graph_integrity_digest"]("commit_sha", value))
            self.assertEqual(redact(value, full, key="commit_sha"),
                             self.graph["_redact_graph_text"](value, 40_000, full))

    def test_graph_scalar_digest_unknown_key_padding_type_and_size_keep_policy(self):
        redact = self.graph["_redact_graph_storage_value"]
        full = self.provider._redact_code_graph_text

        class NonTextDigest:
            def __str__(self):
                return "b" * 64

        controls = [(key, "b" * 64) for key in
                    ("value", "notes", "snapshot_hash_extra", "_is_graph_integrity_digest")]
        controls += [("snapshot_hash", value) for value in
                     (" " + "b" * 64 + "\n", " " * 40_001 + "b" * 64,
                      "b" * 40_001, NonTextDigest())]
        for key, value in controls:
            original = str(value)
            safe = redact(value, full, key=key)
            self.assertEqual(safe, self.graph["_redact_graph_text"](original, 40_000, full))
            self.assertNotEqual(safe, original)
            self.assertLessEqual(len(safe), 40_000)
        for value, expected in ((None, ""), (False, ""), (17, "17")):
            self.assertEqual(redact(value, full, key="snapshot_hash"), expected)
        benign = "ordinary " * 5_000
        self.assertEqual(redact(benign, full, key="snapshot_hash"), benign[:40_000])

    def test_graph_storage_nested_json_keeps_digest_and_redacts_other_values(self):
        redact = self.graph["_redact_graph_storage_value"]
        full = self.provider._redact_code_graph_text
        data = {"snapshot_hash": "b" * 64, "commit_sha": "abc1234",
                "content_hash": "sha256:" + "A1" * 32, "unknown_hash": "b" * 64,
                "notes": [MIXED, {"snapshot_hash": BARE, "api_key": "tiny"}]}
        original = json.dumps(data, indent=2)
        safe = redact(original, full, key="snapshot_hash")
        parsed = json.loads(safe)
        self.assertNotEqual(safe, original)
        for key in ("snapshot_hash", "commit_sha", "content_hash"):
            self.assertEqual(parsed[key], data[key])
        self.assertNotEqual(parsed["unknown_hash"], data["unknown_hash"])
        self.assertFalse(BARE in safe or ASSIGNMENT in safe)
        self.assertEqual(parsed["notes"][1]["api_key"], "<REDACTED_KEYED_VALUE>")
        self.assertNotEqual(parsed["notes"][1]["snapshot_hash"], BARE)
        self.assertEqual(json.loads(original), data)
        for raw in (json.dumps({"snapshot_hash": "b" * 64}, indent=2),
                    json.dumps("b" * 64), '{ "notes": ["ordinary", 17, null] }'):
            self.assertEqual(redact(raw, full, key="snapshot_hash"), raw)

    def test_admin_required_none_stops_before_terminal(self):
        self.fixture()
        before = self.snapshot()
        self.provider._redact_code_graph_text = None
        result, error = self.admin()
        after = self.snapshot()
        payloads = [p.read_bytes() for p in self.terminal_root.rglob("*.json")]
        # Persist the differentiating, hashed real-file witness BEFORE the
        # intended regression assertion. This is also the only baseline case.
        self.witness({"before": before, "after": after, "files_changed": before != after,
                      "bare_canary_retained": any(BARE.encode() in raw for raw in payloads),
                      "assignment_canary_retained": any(ASSIGNMENT.encode() in raw for raw in payloads),
                      "graph_calls": self.graph_calls, "graph_refused": self.provider.graph_primary is not None,
                      "terminal_calls": self.provider.terminal_calls,
                      "raised_type": type(error).__name__ if error is not None else None,
                      "exact_graph_primary_propagated": error is not None and error is self.provider.graph_primary,
                      "returned_applied": result.get("applied") if result is not None else None,
                      "returned_terminal_counts": result.get("code_graph_terminal") if result is not None else None,
                      "success_audit_count": len(self.provider.audits), "sink_counts": self.sink_counts,
                      "actual_SQLite_SDK_network": 0})
        self.assertIsNotNone(error, "mandatory_admin_refusal_was_swallowed")
        self.assertIs(error, self.provider.graph_primary)
        self.assertIsNone(result)
        self.assertEqual(self.provider.terminal_calls, 0)
        self.assertEqual(after, before)
        self.assertEqual(self.sink_counts, {"write_open": 0, "rename": 0, "remove": 0})
        self.assert_no_success()

    def test_admin_graph_primary_stops_terminal_after_earlier_table_effect(self):
        self.table_fixture()
        self.fixture()
        before = self.snapshot()
        self.graph_fault = ValueError("owned graph fault " + BARE)
        result, error = self.admin()
        self.assertIs(error, self.graph_fault)
        self.assertIs(error, self.provider.graph_primary)
        self.assertIs(self.provider.sql.context_errors[-1], error)
        self.assertIsNone(result)
        self.assertEqual(self.provider.terminal_calls, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.provider.sql.committed_updates, 1)
        self.assertFalse(BARE in self.provider.sql.row["notes"])
        self.assert_no_success()
        self.assertEqual(self.debug, [])

    def test_admin_terminal_primary_prevents_success_audit(self):
        self.fixture()
        before = self.snapshot()
        fault = OSError("owned terminal fault " + BARE)
        attempted = []

        def refuse_write(path, text):
            attempted.append(True)
            raise fault

        self.methods["atomic_write"] = refuse_write
        result, error = self.admin()
        self.assertIs(error, fault)
        self.assertIs(error, self.provider.terminal_primary)
        self.assertIsNone(result)
        self.assertEqual((self.graph_calls, self.provider.terminal_calls, len(attempted)), (1, 1, 1))
        self.assertEqual(self.snapshot(), before)
        self.assert_no_success()
        self.assertEqual(self.debug, [])

    def healthy_files(self):
        mixed = {"notes": [MIXED, {"memo_" + BARE: "ordinary"}], "snapshot_hash": "b" * 64}
        self.fixture(raw=(json.dumps(mixed) + "\n").encode("utf-8"))
        safe = self.fixture(SAFE_NAME, raw=b'{"notes":"ordinary"}\n')
        self.fixture("broken.error.json", root=self.dead, raw=b"{owned malformed")
        return safe, safe.read_bytes()

    def test_healthy_admin_apply_counts_full_callback_and_terminal_names(self):
        self.table_fixture()
        safe, safe_raw = self.healthy_files()
        result, error = self.admin()
        self.assertIsNone(error)
        self.assertIs(result["applied"], True)
        self.assertEqual((result["hit_count"], result["updated_rows"], result["secret_refs"]), (1, 1, [SECRET_REF]))
        self.assertEqual(result["code_graph"], self.graph_counts)
        self.assertEqual(result["code_graph_terminal"], {"scanned": 3, "redacted": 2, "stubs": 1, "renamed": 2})
        files = sorted(self.terminal_root.rglob("*.json"))
        self.assertEqual(len(files), 3)
        self.assertTrue(all(self.methods["_CODE_SHRINKER_TERMINAL_NAME_RE"].fullmatch(p.name) for p in files))
        self.assertEqual(safe.read_bytes(), safe_raw)
        for path in files:
            raw = path.read_bytes()
            self.assertFalse(BARE.encode() in raw or ASSIGNMENT.encode() in raw)
        self.assertFalse(BARE in json.dumps(result) or ASSIGNMENT in json.dumps(result))
        self.assertEqual((self.provider.sql.committed_updates, self.provider.quarantines), (1, 1))
        self.assertEqual((self.graph_calls, self.provider.terminal_calls), (1, 1))
        self.assertEqual(self.provider.audits, [("scrub_secrets", "ok", "hits=1 updated=1")])
        self.assertEqual((self.provider.rebuilds, self.provider.renders), (1, 1))
        self.assertGreater(self.sink_counts["write_open"], 0)
        self.assertGreater(self.sink_counts["rename"], 0)
        self.assertGreater(self.sink_counts["remove"], 0)

    def test_admin_dry_run_preserves_legacy_counts_and_no_effects(self):
        self.table_fixture()
        self.fixture()
        before = self.snapshot()
        result, error = self.admin(apply=False)
        self.assertIsNone(error)
        self.assertIs(result["applied"], False)
        self.assertEqual((result["hit_count"], result["updated_rows"], result["secret_refs"]), (1, 0, []))
        self.assertEqual(result["code_graph"], {"rows": 0, "fields": 0})
        self.assertEqual(result["code_graph_terminal"], {"scanned": 0, "redacted": 0, "stubs": 0})
        self.assertEqual((self.graph_calls, self.provider.terminal_calls, self.provider.sql.committed_updates), (0, 0, 0))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sink_counts, {"write_open": 0, "rename": 0, "remove": 0})
        self.assert_no_success()

    def test_required_none_terminal_refuses_before_effect(self):
        self.refuse_terminal(None)

    def test_missing_callback_terminal_refuses_before_effect(self):
        self.refuse_terminal(None, missing=True)

    def test_noncallable_terminal_refuses_before_effect(self):
        self.refuse_terminal(17)

    def test_throwing_callback_terminal_refuses_before_effect(self):
        def throws(text):
            raise ValueError("owned callback fault " + BARE)
        self.refuse_terminal(throws)

    def test_nontext_callback_terminal_refuses_before_effect(self):
        self.refuse_terminal(lambda text: {"owned": "not text"})

    def test_inherited_requirement_cannot_be_waived(self):
        weaker = type("SyntheticWeakerReceiver", (self.Receiver,), {REQUIREMENT: False})
        self.provider = weaker(self.provider.home)
        setattr(self.provider, REQUIREMENT, False)
        self.refuse_terminal(None)

    def test_healthy_terminal_dry_run_counts_without_effect(self):
        self.healthy_files()
        before = self.snapshot()
        result, error = self.terminal(apply=False)
        self.assertIsNone(error)
        self.assertEqual(result, {"scanned": 3, "redacted": 2, "stubs": 1, "renamed": 2})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sink_counts, {"write_open": 0, "rename": 0, "remove": 0})
        self.assert_no_success()

    def test_standalone_none_remains_truthful_partial_mode(self):
        parsed = {"notes": MIXED}
        safe = self.graph["sanitize_code_graph_event_for_recovery"](parsed, None)
        self.assertTrue(BARE in safe["notes"])
        self.assertFalse(ASSIGNMENT in safe["notes"])
        self.assertEqual(parsed, {"notes": MIXED})
        self.assertFalse(BARE in self.provider._redact_code_graph_text(MIXED))
        self.assertIsNone(self.graph["_provider_graph_redactor"](object()))
        self.assertEqual(self.snapshot(), [])

    def test_unavailable_graph_resolver_terminal_fails_closed(self):
        self.fixture(raw=b"{owned malformed")
        before = self.snapshot()
        self.methods["_resolve_code_graph_redactor"] = self.methods["_code_graph_unavailable"]
        result, error = self.terminal()
        self.assertIsNone(result)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(str(error), "code_knowledge_graph unavailable: ImportError")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sink_counts, {"write_open": 0, "rename": 0, "remove": 0})


    def test_admin_owner_contexts_keep_row_then_graph_grain(self):
        self.table_fixture()
        result, error = self.admin()
        self.assertIsNone(error)
        self.assertEqual(result["updated_rows"], 1)
        self.assertEqual(self.provider.transaction_calls,
                         [("enter", 0, 0), ("exit", 1, 1),
                          ("enter", 1, 1), ("exit", 1, 1)])
        self.assertFalse(self.provider.sql.in_transaction)
        self.assertEqual((self.graph_calls, self.provider.terminal_calls), (1, 1))

    def test_admin_active_apply_refuses_before_effect_but_dry_remains_readonly(self):
        self.table_fixture()
        self.fixture()
        before = self.snapshot()
        # Explicit synthetic active context, not an actual native owner claim.
        self.provider.sql.in_transaction = True
        result, error = self.admin()
        self.assertIsNone(result)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(str(error), "claim_transaction_requires_idle_owner")
        self.assertTrue(self.provider.sql.in_transaction)
        self.assertEqual((self.provider.sql.selects, self.provider.sql.updates), (0, 0))
        self.assertEqual(self.provider.transaction_calls, [])
        self.assertEqual((self.provider.quarantines, self.graph_calls, self.provider.terminal_calls), (0, 0, 0))
        self.assert_no_success()
        dry, error = self.admin(apply=False)
        self.assertIsNone(error)
        self.assertEqual((dry["hit_count"], dry["updated_rows"]), (1, 0))
        self.assertTrue(self.provider.sql.in_transaction)
        self.assertEqual(self.provider.transaction_calls, [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sink_counts, {"write_open": 0, "rename": 0, "remove": 0})

    def test_admin_owner_context_source_is_existing_nonjoining_per_stage_api(self):
        # Static SOURCE control, not execution of native _claim_transaction.
        method = self.methods["SourceMethods"]._scrub_secrets
        tree, _ = selected_ast(Path(method.__code__.co_filename).read_bytes(), "entry")
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SourceMethods")
        scrub = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_scrub_secrets")
        contexts = [item.context_expr for n in ast.walk(scrub) if isinstance(n, ast.With) for item in n.items]
        owners = [n for n in contexts if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "_claim_transaction"]
        self.assertEqual(len(owners), 2)
        self.assertTrue(all(ast.dump(n, include_attributes=False) == ast.dump(owners[0], include_attributes=False)
                            for n in owners))
        self.assertEqual(ast.unparse(owners[0]), "self._claim_transaction(c)")
        self.assertFalse(any(isinstance(n, ast.Name) and n.id == "c" for n in contexts))


def make_suite(raw, source, graph_raw, graph_source, scratch, cases=None):
    methods, graph, bindings = load_functions(raw, source, graph_raw, graph_source)
    receiver = receiver_class(methods)
    ids = sorted(n for n in MandatoryRedactorAdminTests.__dict__ if n.startswith("test_"))
    selected = ids if cases is None else list(cases)
    if not selected or len(set(selected)) != len(selected) or not set(selected).issubset(ids):
        raise ValueError("invalid_case_roster")
    suite = unittest.TestSuite()
    for name in selected:
        case = MandatoryRedactorAdminTests(name)
        case.methods, case.graph, case.bindings = methods, graph, bindings
        case.original_atomic, case.Receiver, case.scratch = methods["atomic_write"], receiver, Path(scratch)
        suite.addTest(case)
    return suite, bindings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).absolute().parents[1] / "__init__.py")
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=False)
    graph = args.graph or args.source.parent / "code_knowledge_graph.py"
    suite, _ = make_suite(args.source.read_bytes(), args.source, graph.read_bytes(), graph, args.scratch, args.case)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
