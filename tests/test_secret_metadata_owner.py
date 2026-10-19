"""Offline SOURCE regressions for the two secret SQL metadata owners.

Run directly with stdlib unittest, never import the provider package:
  python -I -B -S -X utf8 tests/test_secret_metadata_owner.py

Complete current methods (including the existing transaction, rollback, connect
and audit bodies) are AST-extracted. SQL, identity/receiver, store, journal and
postcommit consumers are explicitly synthetic. No SQLite connection, SDK,
authority, secret-core/crypto or native/provider bootstrap is exercised. Core
policy callbacks are forbidden, NOT permissive substitutes. The optional-core
branch is false; the healthy store is an explicit fixture-only receiver seam.
A successful packet establishes SOURCE control flow, not cross-store atomicity.
"""
from __future__ import annotations

import argparse
import ast
import builtins
from contextlib import contextmanager
from contextvars import ContextVar
import dis
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
import types
from typing import Any, Callable, Dict, List, Optional, Tuple
import unittest
import urllib.error

ENTRY_FUNCTIONS = (
    "now", "sha", "short", "slug", "clamp", "normalize_claim",
    "_safe_exception_label", "_sensitive_secret_field",
    "_quoted_secret_assignment_is_raw", "_redact_quoted_secret_assignment",
    "_balanced_secret_container_end", "_redact_quoted_secret_containers",
    "redact_secrets",
)
ENTRY_CONSTANTS = (
    "SECRET_PATTERNS", "QUOTED_SECRET_ASSIGN_RE",
    "QUOTED_SECRET_CONTAINER_RE", "REDaction_MARKER_RE",
)
METHODS = (
    "_quarantine_secret", "_add_secret", "_get_secret_store", "_connect",
    "_require_claim_writer", "_quarantine_claim_connection",
    "_rollback_claim_transaction", "_claim_transaction", "_audit",
)
SYNTHETIC_GLOBALS = (
    "_owns_private_graph_writer", "_current_delivery", "_TerminalDelivery",
    "_DeliveryWithheld", "_GraphCommitConnection", "_AUDIT_PREPARATION",
    "_CLAIM_JOURNAL_CAPTURE", "_GRAPH_EXTRACTION", "_SECRET_CORE_AVAILABLE",
    "_SECRET_CORE_ERROR", "_BrokerVaultStore", "_secret_safe_locator",
    "_safe_secret_aliases", "_secret_redact_text", "_debug_log", "claim_search_text",
)
BARE = "ghp_" + "SYNTHETIC0123456789ABCD"
RAW = "ordinary fixture " + BARE
VALUE = "invented-store-value-only"
OWNER = {
    "identity": "synthetic-bot\0synthetic-session\0synthetic-project",
    "visibility_scope": "private", "origin_bot_id": "synthetic-bot",
    "origin_session_id": "synthetic-session", "origin_chat_hash": "synthetic-chat",
    "project_id": "synthetic-project",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def dependency_names(code):
    names = {i.argval for i in dis.get_instructions(code) if i.opname == "LOAD_GLOBAL"}
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            names |= dependency_names(value)
    return names


def selected_ast(raw):
    """Reuse the shipped exact named-AST selector, with a narrow new roster."""
    tree = ast.parse(raw)
    nodes, origins = [], []

    def take(matches, qualified):
        if len(matches) != 1:
            raise ValueError("unique_source_binding_required:" + qualified)
        node = matches[0]
        origins.append({"qualified_AST": qualified, "node": type(node).__name__,
                        "lines": [node.lineno, node.end_lineno],
                        "ast_sha256": digest(ast.dump(node, include_attributes=False).encode())})
        return node

    for name in ENTRY_CONSTANTS:
        nodes.append(take([n for n in tree.body if isinstance(n, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)], name))
    for name in ENTRY_FUNCTIONS:
        node = take([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name], name)
        if node.decorator_list:
            raise ValueError("undecorated_source_function_required:" + name)
        nodes.append(node)
    # Exact existing fallback body, not a reconstructed fingerprint or core loader.
    nodes.append(take([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                       and n.name == "_secret_fingerprint"],
                      "secret_core_import_fallback._secret_fingerprint"))
    cls = take([n for n in tree.body if isinstance(n, ast.ClassDef)
                and n.name == "MemoryWikiProvider"], "MemoryWikiProvider_scaffold_only")
    body = [take([n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name],
                 "MemoryWikiProvider." + name) for name in METHODS]
    # The class scaffold has no SDK base, constructor or authority.
    scaffold = ast.ClassDef(name="SourceMethods", bases=[], keywords=[], body=body,
                            decorator_list=[], type_params=[])
    nodes.append(ast.copy_location(scaffold, cls))
    future = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
    return ast.fix_missing_locations(ast.Module(body=future + nodes, type_ignores=[])), origins


def forbidden_core(*args, **kwargs):
    raise AssertionError("secret_core_or_native_factory_NOT_RUN")


class SyntheticWithheld(RuntimeError):
    pass


class SyntheticUnsupportedTerminal:
    """Never instantiated; critical terminal/native branches are NOT_RUN."""


def load_functions(raw, source):
    namespace = {
        "__builtins__": builtins.__dict__, "__name__": "secret_metadata_source_methods",
        "contextmanager": contextmanager, "hashlib": hashlib, "json": json,
        "re": re, "sqlite3": sqlite3, "threading": threading, "time": time,
        "urllib": urllib, "Path": Path, "Any": Any, "Callable": Callable,
        "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple,
        "_owns_private_graph_writer": lambda provider, conn: False,
        "_current_delivery": lambda provider: None,
        "_TerminalDelivery": SyntheticUnsupportedTerminal,
        "_DeliveryWithheld": SyntheticWithheld,
        "_GraphCommitConnection": forbidden_core, "claim_search_text": forbidden_core,
        "_AUDIT_PREPARATION": ContextVar("synthetic_audit_preparation", default=None),
        "_CLAIM_JOURNAL_CAPTURE": ContextVar("synthetic_claim_capture", default=None),
        "_GRAPH_EXTRACTION": ContextVar("synthetic_graph_extraction", default=None),
        "_SECRET_CORE_AVAILABLE": False, "_SECRET_CORE_ERROR": "SOURCE_core_NOT_LOADED",
        "_BrokerVaultStore": forbidden_core, "_secret_safe_locator": forbidden_core,
        "_safe_secret_aliases": forbidden_core, "_secret_redact_text": forbidden_core,
        "_debug_log": forbidden_core,
    }
    selected, origins = selected_ast(raw)
    code = compile(selected, str(source), "exec", dont_inherit=True)
    defined = set(ENTRY_FUNCTIONS + ENTRY_CONSTANTS + ("_secret_fingerprint", "SourceMethods"))
    missing = dependency_names(code) - set(namespace) - defined - set(dir(builtins))
    if missing:
        raise ValueError("unbound_source_dependencies:" + ",".join(sorted(missing)))
    exec(code, namespace)
    return namespace, {"entry": origins}


class Rows:
    def fetchone(self):
        return (1,)


class SyntheticSQL:
    """Exact-shape observer, not SQLite, its transaction engine or authority."""
    def __init__(self, provider):
        self.p = provider
        self.in_transaction = False
        self.autocommit = False
        self.total_changes = 0
        self._prefetch_terminal = None
        self._document_commit_image = None
        self._graph_commit_image = None
        self._event_job_commit_image = None
        self._graph_extraction_stage = None
        self.pending, self.committed, self.events = [], [], []
        self.insert_primary = None
        self.insert_table = "secret_index"
        self.rollback_primary = None
        self.commit_primary = None
        self.commit_then_raise = False
        self.writer_witnesses = []
        self.commits = self.rollbacks = self.bare_contexts = 0

    def owned(self):
        assert self.in_transaction
        assert self.p._claim_tx_connection is self
        assert self.p._claim_tx_thread == threading.get_ident()
        assert self.p._transaction_quarantine is None
        assert self.p._connect() is self  # Actual extracted public-owner guard.

    def execute(self, sql, params=()):
        shape = " ".join(sql.split())
        if shape == "SELECT 1":
            return Rows()
        if shape == "BEGIN IMMEDIATE":
            assert not self.in_transaction
            self.in_transaction = True
            self.events.append("begin")
            return Rows()
        if shape.startswith("INSERT OR IGNORE INTO secret_quarantine("):
            table, count = "secret_quarantine", 9
        elif shape.startswith("INSERT INTO secret_index("):
            table, count = "secret_index", 22
            assert "VALUES(?,?,?,?,?,''," in shape and "value=''" in shape
        elif shape.startswith("INSERT OR IGNORE INTO audit_log("):
            table, count = "audit_log", 10
        elif shape == "INSERT synthetic_caller":
            table, count = "synthetic_caller", 1
        else:
            raise AssertionError("unexpected_synthetic_SQL_shape")
        self.owned()
        assert len(params) == count
        self.events.append("insert:" + table)
        self.pending.append((table, tuple(params)))
        self.total_changes += 1
        if table in {"secret_quarantine", "secret_index"}:
            self.writer_witnesses.append((table, self.p._claim_tx_connection is self,
                                           self.p._transaction_quarantine is None))
        if self.insert_primary is not None and table == self.insert_table:
            raise self.insert_primary
        return Rows()

    def commit(self):
        self.events.append("commit")
        self.commits += 1
        if self.commit_primary is not None and not self.commit_then_raise:
            raise self.commit_primary
        self.committed.extend(self.pending)
        self.pending.clear()
        self.in_transaction = False
        if self.commit_primary is not None:
            raise self.commit_primary

    def rollback(self):
        self.events.append("rollback")
        self.rollbacks += 1
        if self.rollback_primary is not None:
            raise self.rollback_primary
        self.pending.clear()
        self.in_transaction = False

    def __enter__(self):
        self.bare_contexts += 1
        raise AssertionError("bare_SQL_context_is_not_an_owner")

    def rows(self, table):
        return [row for name, row in self.committed if name == table]


class SyntheticStore:
    """In-memory effect/compensation observer; no encryption or Vault API proof."""
    def __init__(self, provider):
        self.p = provider
        self.values, self.events = {}, []
        self.snapshot_primary = self.put_primary = self.restore_primary = None

    def wrapped_snapshot(self, sid):
        self.p.sql.owned()
        self.events.append("snapshot")
        if self.snapshot_primary is not None:
            raise self.snapshot_primary
        return self.values.get(sid)

    def put_secret(self, sid, value):
        self.p.sql.owned()
        self.events.append("put")
        # A synthetic opaque marker, NOT ciphertext or a fabricated core result.
        self.values[sid] = "synthetic-wrapped:" + digest(value.encode())
        if self.put_primary is not None:
            raise self.put_primary
        return "vaultref:v1:" + sid

    def restore_wrapped(self, sid, previous):
        self.p.assert_idle()
        assert self.p._lock._is_owned()  # Compensation remains serialized.
        self.events.append("restore")
        if self.restore_primary is not None:
            raise self.restore_primary
        if previous is None:
            self.values.pop(sid, None)
        else:
            self.values[sid] = previous

    def has_secret(self, sid):
        self.p.assert_idle()
        self.events.append("has")
        return sid in self.values


def receiver_class(namespace):
    base = namespace["SourceMethods"]

    class Receiver(base):
        """Synthetic identity/journal/callback receiver; not a MemoryProvider."""
        def __init__(self):
            self._lock = threading.RLock()
            self._lifecycle_state = "ready"
            self._transaction_quarantine = self._transaction_primary = None
            self._transaction_cleanup_notes = ()
            self._claim_tx_connection = self._claim_tx_thread = None
            self._claim_tx_document_stage = self._claim_tx_graph_stage = None
            self._claim_tx_event_job_stage = None
            self._degraded = False
            self._background_worker = None
            self.sql = SyntheticSQL(self)
            self._conn = self._owned_conn = self.sql
            self.store = SyntheticStore(self)
            self.store_open = 0
            self.core_unavailable = False
            self.callbacks, self.diagnostics = [], []
            self.callback_errors = {}
            self.journal_primary = self.debug_primary = None
            namespace["_debug_log"] = self.debug

        def _runtime_identity(self):
            return {"conn_path_matches": True}  # Synthetic path observer only.

        def _aux_owner(self, args, **kwargs):
            return dict(OWNER)  # Synthetic identity, not an ACL/gate assertion.

        def _claim_journal_pending_commit(self, conn):
            return None  # No journal capture is admitted by this fixture.

        def _claim_journal_committed(self, image):
            if self.journal_primary is not None:
                raise self.journal_primary

        def _get_secret_store(self):
            if self.core_unavailable:
                return base._get_secret_store(self)  # Actual missing-core refusal.
            self.sql.owned()
            self.store_open += 1
            return self.store

        def assert_idle(self):
            assert not self.sql.in_transaction
            assert self._claim_tx_connection is self._claim_tx_thread is None
            assert self._transaction_quarantine is None
            assert self._connect() is self.sql

        def callback(self, name):
            self.assert_idle()
            assert self.sql.rows("secret_index")
            self.callbacks.append(name)
            if name in self.callback_errors:
                raise self.callback_errors[name]

        def _add_claim(self, *args, **kwargs):
            self.claim_args, self.claim_kwargs = args, kwargs
            self.callback("safe_claim")
            return "synthetic-safe-claim"

        def _add_change(self, *args, **kwargs):
            self.callback("change_log")

        def _render_active_dashboard(self):
            self.callback("dashboard")

        def debug(self, message):
            self.diagnostics.append(message)
            if self.debug_primary is not None:
                raise self.debug_primary

    return Receiver


class SyntheticCancel(BaseException):
    pass


# Primitive SOURCE witnesses only. Test-local manager/primary references in the
# observer below are intentional identity oracles, not a GC/lifetime proof.
F1_WITNESSES = []


def f1_observe(p, callback, *, label, primary, seam=None, injected=None, mutate=None):
    """Observe real extracted owner/stdlib exit; never replace either callable.

    A throwing profile disables itself. A separate passive trace observes the
    actual rollback, consumer unwind and compensation after that injection.
    The optional mutator only invalidates the test-local observation list.
    """
    base = type(p).__mro__[1]
    owner_code = base._claim_transaction.__wrapped__.__code__
    add_code = base._add_secret.__code__
    rollback_code = base._rollback_claim_transaction.__code__
    restore_code = SyntheticStore.restore_wrapped.__code__
    pending_code = type(p)._claim_journal_pending_commit.__code__
    manager_type = contextmanager.__globals__["_GeneratorContextManager"]
    enter_code, exit_code = manager_type.__enter__.__code__, manager_type.__exit__.__code__
    instructions = list(dis.get_instructions(owner_code))
    # The first return AFTER the document-postcommit tail is the owning normal
    # fallthrough. Neither the earlier join return nor the RLock exception-
    # suppression handler's later return is this boundary.
    tail = next(i.offset for i in instructions if i.argval == "_after_document_claims_commit")
    owner_return = next(i.offset for i in instructions if i.offset > tail and i.opname == "RETURN_VALUE")
    exit_return = next(i.offset for i in dis.get_instructions(exit_code) if i.opname == "RETURN_VALUE")
    proof_offset = next(i.offset for i in dis.get_instructions(add_code)
                        if i.opname.startswith("LOAD_FAST") and i.argval == "vault_write_attempted")
    opnames = {i.offset: i.opname for i in instructions}
    thread = threading.get_ident()
    binding, events, injections = {}, [], []
    old_profile, old_trace = sys.getprofile(), sys.gettrace()

    def record(event, **fields):
        row = {"case": label, "event": event, **fields}
        F1_WITNESSES.append(row)
        return row

    def retired():
        return (p._claim_tx_connection is None and p._claim_tx_thread is None
                and p._claim_tx_document_stage is None and p._claim_tx_graph_stage is None
                and p._claim_tx_event_job_stage is None)

    def positive(receipt):
        return (type(receipt) is list and len(receipt) == 1
                and type(receipt[0]) is tuple and len(receipt[0]) == 3
                and receipt[0][0] is p.sql and receipt[0][1] == thread
                and receipt[0][2] is primary)

    def observe(frame, event, arg):
        if threading.get_ident() != thread:
            return None
        code = frame.f_code
        if code is restore_code and event == "call" and frame.f_locals.get("self") is p.store:
            caller = frame.f_back
            events.append("restore")
            record("restore_after_proof", rollback_true_seen="rollback_true" in events,
                   receipt_matches=caller.f_code is add_code and positive(caller.f_locals.get("rollback_receipt")),
                   retired=retired(), idle=not p.sql.in_transaction,
                   quarantine_absent=p._transaction_quarantine is None)
            return None
        if code is rollback_code and frame.f_locals.get("self") is p:
            if event == "return" and arg is True:
                events.append("rollback_true")
                record("actual_rollback_return_true", connection_matches=frame.f_locals.get("conn") is p.sql,
                       primary_matches=frame.f_locals.get("primary") is primary,
                       idle=not p.sql.in_transaction)
            return observe
        if code is add_code and frame.f_locals.get("self") is p:
            if event == "call" and mutate is not None:
                frame.f_trace_opcodes = True
            if event == "exception" and arg[1] is primary:
                events.append("consumer_primary")
                record("consumer_original_primary", retired=retired(), idle=not p.sql.in_transaction)
            if (event == "opcode" and frame.f_lasti == proof_offset and mutate is not None
                    and "mutated" not in events):
                receipt = frame.f_locals["rollback_receipt"]
                assert positive(receipt) and retired() and not p.sql.in_transaction
                record("invalidate_observation_before_read", original_receipt_matches=True,
                       rollback_true_seen="rollback_true" in events)
                mutate(receipt)
                events.append("mutated")
            return observe
        return None

    def profile(frame, event, arg):
        if threading.get_ident() != thread:
            return
        code, local = frame.f_code, frame.f_locals
        if code is owner_code and local.get("self") is p:
            if event == "call" and frame.f_back.f_code is enter_code:
                manager = frame.f_back.f_locals["self"]
                assert type(manager) is manager_type and manager.gen.gi_code is owner_code
                assert manager.gen.gi_frame is frame and "manager" not in binding
                binding["manager"] = manager
            if event == "return" and frame.f_lasti == owner_return:
                assert arg is None and opnames[frame.f_lasti] == "RETURN_VALUE"
                assert binding["manager"].gen.gi_frame is frame
                events.append("owner_normal_return")
                if seam == "owner_return":
                    inject(frame, "owner_return", normal_return=True, exact_manager=True,
                           return_opcode="RETURN_VALUE", return_offset=owner_return,
                           completed=local.get("completed") is True,
                           commit_attempted=local.get("commit_attempted") is True,
                           connection_matches=local.get("c") is p.sql,
                           receipt_empty=local.get("_rollback_receipt") == [])
            receipt = local.get("_rollback_receipt")
            if (seam in {"publish_call", "publish_return"} and event ==
                    ("c_call" if seam == "publish_call" else "c_return")
                    and getattr(arg, "__self__", None) is receipt
                    and getattr(arg, "__name__", None) == "append"):
                assert local.get("primary") is primary and local.get("rolled_back") is True
                inject(frame, seam, rollback_returned_true="rollback_true" in events,
                       receipt_matches=positive(receipt), publication_before_retirement=not retired())
        elif (code is exit_code and event == "return" and frame.f_lasti == exit_return
              and local.get("self") is binding.get("manager") and seam == "context_exit"):
            assert local.get("typ") is None and arg is False
            assert local["self"].gen.gi_frame is None and "owner_normal_return" in events
            inject(frame, "context_exit", normal_return=True, generator_completed=True,
                   return_opcode="RETURN_VALUE", return_offset=exit_return,
                   same_manager=True, owner_normal_return_seen=True)
        elif (code is pending_code and event == "return" and local.get("self") is p
              and seam == "pending"):
            assert p.sql.pending and p._claim_tx_connection is p.sql and p.sql.in_transaction
            inject(frame, "pending_after_body", body_finished=True, commit_not_attempted=p.sql.commits == 0)
        elif (code is add_code and event == "c_call" and arg is builtins.len and seam == "read"
              and local.get("self") is p and local.get("primary") is primary):
            assert positive(local["rollback_receipt"]) and retired()
            inject(frame, "proof_read", positive_before_fault=True)

    def inject(frame, event, **fields):
        assert not injections
        rows = p.sql.rows("secret_index")
        row = record("BEFORE_" + event, exact_thread=threading.get_ident() == thread,
                     exact_code=frame.f_code in {owner_code, exit_code, pending_code, add_code},
                     commit_events=p.sql.events.count("commit"), commits=p.sql.commits,
                     rollbacks=p.sql.rollbacks, idle=not p.sql.in_transaction,
                     retired=retired(), quarantine_absent=p._transaction_quarantine is None,
                     metadata_rows=len(rows), value_present=bool(p.store.values), **fields)
        if event in {"owner_return", "context_exit"}:
            assert row["commits"] == 1 and row["rollbacks"] == 0
            assert row["idle"] and row["retired"] and row["quarantine_absent"]
            assert len(rows) == 1 and rows[0][14] == "vaultref:v1:" + rows[0][0]
        injections.append(event)  # Witness is saved BEFORE raising the fault.
        raise injected if injected is not None else primary

    result, error = None, None
    try:
        sys.settrace(observe)
        sys.setprofile(profile)
        try:
            result = callback()
        except BaseException as escaped:
            error = escaped
    finally:
        sys.setprofile(old_profile)
        sys.settrace(old_trace)
    assert sys.getprofile() is old_profile and sys.gettrace() is old_trace
    if seam is not None:
        assert len(injections) == 1, "required_exact_fault_boundary_not_observed"
    return result, error, events


class SecretMetadataOwnerTests(unittest.TestCase):
    namespace = None

    def setUp(self):
        self.p = receiver_class(self.namespace)()

    def arguments(self, **updates):
        result = {"_trusted_local_write": True, "subject": "amber fixture",
                  "scope": "operations", "locator": "fixture://amber",
                  "purpose": "safe fixture metadata", "value": VALUE}
        result.update(updates)
        return result

    def sid(self):
        material = "\0".join(["secret", OWNER["identity"], "amber fixture", "operations",
                              "credential", "fixture://amber"])
        return "sec_" + digest(material.encode())[:12]

    def quarantine(self):
        return self.p._quarantine_secret("entities", "fixture-row", "notes", RAW)

    def test_01_quarantine_owned_insert_redacted_fields_and_postcommit_audit(self):
        p = self.p
        qid = self.quarantine()
        fingerprint = digest(("entities:fixture-row:notes\0" + RAW).encode())
        self.assertEqual(qid, "sq_" + digest(("entities:fixture-row:notes:" + fingerprint).encode())[:12])
        row = p.sql.rows("secret_quarantine")[0]
        self.assertEqual(row[:4], (qid, "entities", "fixture-row", "notes"))
        self.assertNotIn(BARE, row[4])
        self.assertEqual(row[4], self.namespace["redact_secrets"](RAW))
        self.assertEqual(row[5:8], (fingerprint, "secret_scan", "active"))
        self.assertIs(type(row[8]), int)
        self.assertEqual(p.sql.writer_witnesses, [("secret_quarantine", True, True)])
        self.assertEqual(p.sql.events, ["begin", "insert:secret_quarantine", "commit",
                                        "begin", "insert:audit_log", "commit"])
        self.assertEqual(p.sql.rows("audit_log")[0][1:4],
                         ("secret_quarantine", "ok", "entities.notes:fixture-row:secret_scan"))
        self.assertEqual(p.sql.bare_contexts, 0)
        self.assertEqual(p.store.events, [])
        p.assert_idle()
        self.assertIs(p._connect(), p.sql)

    def test_02_quarantine_refuses_caller_TX_without_commit_rollback_or_audit(self):
        p = self.p
        original = SyntheticCancel("caller rollback fixture")
        with self.assertRaises(SyntheticCancel) as caught:
            with p._claim_transaction() as c:
                c.execute("INSERT synthetic_caller", ("untouched",))
                before = list(c.pending)
                with self.assertRaisesRegex(RuntimeError, "^claim_transaction_requires_idle_owner$"):
                    self.quarantine()
                self.assertEqual(c.pending, before)
                self.assertEqual((c.commits, c.rollbacks), (0, 0))
                self.assertIs(p._claim_tx_connection, c)
                self.assertTrue(c.in_transaction)
                raise original
        self.assertIs(caught.exception, original)
        self.assertEqual(p.sql.committed, [])
        self.assertEqual((p.sql.commits, p.sql.rollbacks), (0, 1))
        self.quarantine()
        p.assert_idle()

    def test_03_quarantine_SQL_failure_exact_primary_and_next_healthy(self):
        p = self.p
        primary = SyntheticCancel("quarantine SQL fixture")
        p.sql.insert_table, p.sql.insert_primary = "secret_quarantine", primary
        with self.assertRaises(SyntheticCancel) as caught:
            self.quarantine()
        self.assertIs(caught.exception, primary)
        self.assertEqual(p.sql.committed, [])
        self.assertEqual(p.sql.pending, [])
        self.assertEqual(p.sql.events, ["begin", "insert:secret_quarantine", "rollback"])
        p.assert_idle()
        p.sql.insert_primary = None
        self.quarantine()
        p.assert_idle()

    def test_04_quarantine_best_effort_audit_failure_keeps_metadata_commit(self):
        p = self.p
        p.sql.insert_table, p.sql.insert_primary = "audit_log", RuntimeError("audit fixture")
        qid = self.quarantine()
        self.assertEqual(p.sql.rows("secret_quarantine")[0][0], qid)
        self.assertEqual(p.sql.rows("audit_log"), [])
        self.assertEqual((p.sql.commits, p.sql.rollbacks), (1, 1))
        p.assert_idle()

    def test_05_secret_owned_store_SQL_and_postcommit_lifetimes_stable_ID(self):
        p = self.p
        args = self.arguments(subject="amber fixture " + BARE)
        result = p._add_secret(args)
        self.assertNotIn("_trusted_local_write", args)
        self.assertNotIn("_trusted_scrub_write", args)
        row = p.sql.rows("secret_index")[0]
        self.assertNotIn(BARE, row[1])
        self.assertNotIn(VALUE, json.dumps(row))
        self.assertEqual(row[5], "safe fixture metadata")
        self.assertEqual(row[7:10], (.85, .85, "active"))
        self.assertEqual(row[14], "vaultref:v1:" + result["id"])
        self.assertEqual(row[15:17], ("[]", "{}"))
        self.assertEqual(row[17:], tuple(OWNER[key] for key in
                         ("visibility_scope", "origin_bot_id", "origin_session_id", "origin_chat_hash", "project_id")))
        self.assertEqual(result, {"id": row[0], "claim_id": "synthetic-safe-claim",
                                 "redacted": True, "vault_ref": row[14], "has_value": True,
                                 "post_commit_errors": []})
        self.assertEqual(p.callbacks, ["safe_claim", "change_log", "dashboard"])
        self.assertEqual(p.store.events, ["snapshot", "put", "has"])
        self.assertEqual(p.sql.writer_witnesses, [("secret_index", True, True)])
        self.assertEqual(p.sql.events, ["begin", "insert:secret_index", "commit"])
        self.assertEqual(p.claim_kwargs, {"visibility_scope": "private", "project_id": "synthetic-project"})
        self.assertNotIn(VALUE, p.claim_args[0])
        self.assertEqual(p.sql.bare_contexts, 0)
        rotated = p._add_secret(self.arguments(subject="amber fixture " + BARE, value="invented-rotation"))
        self.assertEqual(rotated["id"], result["id"])
        p.assert_idle()

    def test_06_scrub_metadata_only_no_put_and_preserves_existing_reference(self):
        p = self.p
        sid = self.sid()
        p.store.values[sid] = "synthetic-old-wrapped"
        result = p._add_secret(self.arguments(_trusted_local_write=False,
                                _trusted_scrub_write=True, value=""))
        self.assertEqual(result["id"], sid)
        self.assertEqual(result["vault_ref"], "vaultref:v1:" + sid)
        self.assertTrue(result["has_value"])
        self.assertEqual(p.store.values[sid], "synthetic-old-wrapped")
        self.assertEqual(p.store.events, ["snapshot", "has"])
        self.assertEqual(p.sql.commits, 1)
        p.store.values.clear()
        empty = p._add_secret(self.arguments(_trusted_local_write=False,
                               _trusted_scrub_write=True, value=""))
        self.assertEqual(empty["id"], sid)
        self.assertEqual(empty["vault_ref"], "")
        self.assertFalse(empty["has_value"])
        self.assertNotIn("put", p.store.events)
        self.assertNotIn("restore", p.store.events)
        p.assert_idle()

    def test_07_trust_and_scrub_plaintext_refusals_before_any_effect(self):
        p = self.p
        variants = [({"_trusted_local_write": False}, "secret_write_admin_only"),
                    ({"_trusted_scrub_write": True}, "scrub_write_cannot_store_plaintext")]
        for updates, message in variants:
            with self.assertRaisesRegex(PermissionError, "^" + message + "$"):
                p._add_secret(self.arguments(**updates))
        with self.assertRaisesRegex(ValueError, "^subject and scope required$"):
            p._add_secret(self.arguments(subject=""))
        self.assertEqual(p.sql.events, [])
        self.assertEqual(p.store_open, 0)
        self.assertEqual(p.store.events, [])
        self.assertEqual(p.callbacks, [])

    def test_08_secret_caller_TX_refusal_precedes_store_and_preserves_outer(self):
        p = self.p
        with p._claim_transaction() as c:
            c.execute("INSERT synthetic_caller", ("caller-owned",))
            before = list(c.pending)
            for value in (VALUE, ""):
                with self.assertRaisesRegex(RuntimeError, "^claim_transaction_requires_idle_owner$"):
                    p._add_secret(self.arguments(value=value))
                self.assertEqual(c.pending, before)
                self.assertIs(p._claim_tx_connection, c)
                self.assertTrue(c.in_transaction)
                self.assertEqual((c.commits, c.rollbacks), (0, 0))
                self.assertEqual(p.store_open, 0)
                self.assertEqual(p.store.events, [])
                self.assertEqual(p.callbacks, [])
        self.assertEqual(p.sql.committed, [("synthetic_caller", ("caller-owned",))])
        self.assertEqual(p.sql.commits, 1)
        p._add_secret(self.arguments())
        p.assert_idle()

    def test_09_foreign_or_unregistered_pending_TX_retained_without_effects(self):
        for helper in ("quarantine", "add"):
            for registered_foreign in (False, True):
                p = receiver_class(self.namespace)()
                p.sql.in_transaction = True
                p.sql.pending = [("synthetic_caller", ("foreign",))]
                if registered_foreign:
                    p._claim_tx_connection = p.sql
                    p._claim_tx_thread = threading.get_ident() + 1  # Synthetic foreign identity.
                with self.assertRaisesRegex(RuntimeError, "^provider_transaction_owner_pending$"):
                    if helper == "quarantine":
                        p._quarantine_secret("entities", "fixture-row", "notes", RAW)
                    else:
                        p._add_secret(self.arguments())
                self.assertIs(p._transaction_quarantine, p.sql)
                self.assertEqual(p._lifecycle_state, "quarantined")
                self.assertEqual(p.sql.pending, [("synthetic_caller", ("foreign",))])
                self.assertEqual((p.sql.commits, p.sql.rollbacks), (0, 0))
                self.assertEqual(p.sql.committed, [])
                self.assertEqual(p.store_open, 0)
                self.assertEqual(p.store.events, [])
                with self.assertRaisesRegex(RuntimeError, "^provider_lifecycle_not_ready$"):
                    p._connect()

    def test_10_secret_SQL_failure_compensates_exact_snapshot_and_primary(self):
        p = self.p
        sid, previous = self.sid(), "synthetic-old-wrapped"
        p.store.values[sid] = previous
        primary = RuntimeError("SQL fixture primary")
        p.sql.insert_primary = primary
        with self.assertRaises(RuntimeError) as caught:
            p._add_secret(self.arguments())
        self.assertIs(caught.exception, primary)
        self.assertEqual(p.store.values[sid], previous)
        self.assertEqual(p.store.events, ["snapshot", "put", "restore"])
        self.assertEqual(p.sql.committed, [])
        self.assertEqual(p.sql.pending, [])
        self.assertEqual((p.sql.commits, p.sql.rollbacks), (0, 1))
        self.assertEqual(p.callbacks, [])
        p.assert_idle()
        p.sql.insert_primary = None
        p._add_secret(self.arguments())
        p.assert_idle()

    def test_11_cancel_compensation_and_diagnostic_failure_preserve_primary(self):
        p = self.p
        primary = SyntheticCancel("original cancellation fixture")
        p.sql.insert_primary = primary
        p.store.restore_primary = SyntheticCancel("secondary restore fixture")
        p.debug_primary = RuntimeError("secondary diagnostic fixture")
        with self.assertRaises(SyntheticCancel) as caught:
            p._add_secret(self.arguments())
        self.assertIs(caught.exception, primary)
        self.assertEqual(p.store.events, ["snapshot", "put", "restore"])
        self.assertEqual(p.sql.committed, [])
        self.assertEqual(p.callbacks, [])
        self.assertEqual(p.diagnostics, ["secret vault compensation failed: SyntheticCancel"])
        p.assert_idle()

    def test_12_store_partial_put_or_snapshot_failure_has_safe_cleanup(self):
        for phase in ("put", "snapshot"):
            p = receiver_class(self.namespace)()
            primary = SyntheticCancel("store fixture failure")
            setattr(p.store, phase + "_primary", primary)
            with self.assertRaises(SyntheticCancel) as caught:
                p._add_secret(self.arguments())
            self.assertIs(caught.exception, primary)
            self.assertEqual(p.store.values, {})
            self.assertEqual(p.store.events, ["snapshot", "put", "restore"] if phase == "put" else ["snapshot"])
            self.assertEqual(p.sql.committed, [])
            self.assertEqual(p.callbacks, [])
            self.assertEqual((p.sql.commits, p.sql.rollbacks), (0, 1))
            p.assert_idle()

    def test_13_rollback_UNKNOWN_retains_owner_primary_no_compensation_or_retry(self):
        p = self.p
        primary = SyntheticCancel("original SQL fixture")
        p.sql.insert_primary = primary
        p.sql.rollback_primary = RuntimeError("rollback denial fixture")
        with self.assertRaises(SyntheticCancel) as caught:
            p._add_secret(self.arguments())
        self.assertIs(caught.exception, primary)
        self.assertIs(p._transaction_primary, primary)
        self.assertIs(p._transaction_quarantine, p.sql)
        self.assertIs(p._claim_tx_connection, p.sql)
        self.assertTrue(p.sql.in_transaction)
        self.assertTrue(p.sql.pending)
        self.assertEqual(p.sql.committed, [])
        self.assertEqual(p.store.events, ["snapshot", "put"])
        self.assertTrue(p.store.values)
        self.assertEqual(p.callbacks, [])
        self.assertTrue(any("outcome=UNKNOWN" in note for note in primary.__notes__))
        with self.assertRaisesRegex(RuntimeError, "^provider_lifecycle_not_ready$"):
            p._add_secret(self.arguments())
        self.assertEqual(p.store_open, 1)

    def test_14_committed_or_journal_UNKNOWN_never_compensates_committed_value(self):
        for phase in ("commit_return", "journal"):
            p = receiver_class(self.namespace)()
            primary = SyntheticCancel("postcommit fixture primary")
            if phase == "commit_return":
                p.sql.commit_then_raise, p.sql.commit_primary = True, primary
            else:
                p.journal_primary = primary
            with self.assertRaises(SyntheticCancel) as caught:
                p._add_secret(self.arguments())
            self.assertIs(caught.exception, primary)
            self.assertIs(p._transaction_primary, primary)
            self.assertIs(p._transaction_quarantine, p.sql)
            self.assertIs(p._claim_tx_connection, p.sql)
            self.assertFalse(p.sql.in_transaction)
            self.assertEqual(len(p.sql.rows("secret_index")), 1)
            self.assertEqual(p.store.events, ["snapshot", "put"])
            self.assertTrue(p.store.values)
            self.assertEqual(p.callbacks, [])
            with self.assertRaisesRegex(RuntimeError, "^provider_lifecycle_not_ready$"):
                p._connect()

    def test_15_postcommit_callback_errors_reported_without_compensation(self):
        p = self.p
        p.callback_errors = {name: RuntimeError("private callback fixture") for name in
                             ("safe_claim", "change_log", "dashboard")}
        result = p._add_secret(self.arguments())
        self.assertEqual(result["claim_id"], "")
        self.assertEqual(result["post_commit_errors"], [
            {"operation": name, "error": "RuntimeError"} for name in
            ("safe_claim", "change_log", "dashboard")])
        self.assertEqual(p.callbacks, ["safe_claim", "change_log", "dashboard"])
        self.assertEqual(p.store.events, ["snapshot", "put", "has"])
        self.assertTrue(result["has_value"])
        self.assertEqual(len(p.sql.rows("secret_index")), 1)
        self.assertEqual((p.sql.commits, p.sql.rollbacks), (1, 0))
        self.assertNotIn("private callback fixture", json.dumps(result))
        p.assert_idle()

    def test_16_actual_missing_core_refusal_is_not_a_store_fallback(self):
        p = self.p
        p.core_unavailable = True
        with self.assertRaisesRegex(RuntimeError, "^hermes_secret_core_unavailable: SOURCE_core_NOT_LOADED$"):
            p._add_secret(self.arguments())
        self.assertEqual(p.store_open, 0)
        self.assertEqual(p.store.events, [])
        self.assertEqual(p.sql.committed, [])
        self.assertEqual(p.callbacks, [])
        self.assertEqual((p.sql.commits, p.sql.rollbacks), (0, 1))
        p.assert_idle()


    def assert_f1_committed(self, p, error, primary):
        self.assertIs(error, primary)
        sid = self.sid()
        self.assertEqual(p.store.values[sid], "synthetic-wrapped:" + digest(VALUE.encode()))
        self.assertEqual(p.store.events, ["snapshot", "put"])
        self.assertNotIn("restore", p.store.events)
        self.assertEqual(len(p.sql.rows("secret_index")), 1)
        self.assertEqual(p.sql.rows("secret_index")[0][0], sid)
        self.assertEqual(p.sql.rows("secret_index")[0][14], "vaultref:v1:" + sid)
        self.assertEqual(p.sql.pending, [])
        self.assertEqual((p.sql.commits, p.sql.rollbacks), (1, 0))
        self.assertEqual(p.callbacks, [])
        p.assert_idle()

    def test_17_F1_actual_owner_normal_final_return_keeps_new_and_rotated_value(self):
        for previous in (None, "synthetic-old-wrapped"):
            p = receiver_class(self.namespace)()
            if previous is not None:
                p.store.values[self.sid()] = previous
            primary = SyntheticCancel("actual owner normal final return")
            result, error, events = f1_observe(p, lambda: p._add_secret(self.arguments()),
                label=self._testMethodName + (".rotation" if previous else ".new"),
                primary=primary, seam="owner_return")
            self.assertIsNone(result)
            self.assert_f1_committed(p, error, primary)
            self.assertIn("consumer_primary", events)  # Separate trace survived the profile fault.
            self.assertNotIn("rollback_true", events)
            healthy = p._add_secret(self.arguments(value="invented-next-value"))
            self.assertEqual(healthy["id"], self.sid())
            p.assert_idle()

    def test_18_F1_actual_contextlib_normal_exit_keeps_new_and_rotated_value(self):
        for previous in (None, "synthetic-old-wrapped"):
            p = receiver_class(self.namespace)()
            if previous is not None:
                p.store.values[self.sid()] = previous
            primary = SyntheticCancel("actual contextlib normal exit return")
            result, error, events = f1_observe(p, lambda: p._add_secret(self.arguments()),
                label=self._testMethodName + (".rotation" if previous else ".new"),
                primary=primary, seam="context_exit")
            self.assertIsNone(result)
            self.assert_f1_committed(p, error, primary)
            self.assertIn("owner_normal_return", events)
            self.assertIn("consumer_primary", events)
            self.assertNotIn("rollback_true", events)

    def test_19_F1_body_finished_precommit_and_commit_before_effect_still_compensate(self):
        for phase in ("pending", "commit_before_effect"):
            p = receiver_class(self.namespace)()
            previous = "synthetic-old-wrapped"
            p.store.values[self.sid()] = previous
            primary = SyntheticCancel("body finished but owner not committed")
            if phase == "commit_before_effect":
                p.sql.commit_primary = primary
            result, error, events = f1_observe(p, lambda: p._add_secret(self.arguments()),
                label=self._testMethodName + "." + phase, primary=primary,
                seam="pending" if phase == "pending" else None)
            self.assertIsNone(result)
            self.assertIs(error, primary)
            self.assertEqual(p.store.values[self.sid()], previous)
            self.assertEqual(p.store.events, ["snapshot", "put", "restore"])
            self.assertEqual(p.sql.committed, [])
            self.assertEqual(p.sql.pending, [])
            self.assertEqual(p.sql.events, ["begin", "insert:secret_index"] +
                             (["commit"] if phase == "commit_before_effect" else []) + ["rollback"])
            self.assertLess(events.index("rollback_true"), events.index("restore"))
            self.assertEqual(p.callbacks, [])
            p.assert_idle()
            p.sql.commit_primary = None
            p._add_secret(self.arguments())
            p.assert_idle()

    def test_20_F1_receipt_refusals_before_effects_and_default_None_join_compatibility(self):
        class NotPlainList(list):
            pass

        variants = [(value, {}) for value in ({}, (), [None], NotPlainList())]
        variants += [([], {key: True}) for key in ("join", "adopt")]
        variants += [([], {"begin": "EXCLUSIVE"}), ([], {"_terminal": object()})]
        for receipt, options in variants:
            p = receiver_class(self.namespace)()
            with self.assertRaisesRegex(ValueError, "^invalid_claim_rollback_receipt_mode$"):
                with p._claim_transaction(_rollback_receipt=receipt, **options):
                    self.fail("receipt_refusal_entered_body")
            self.assertEqual(p.sql.events, [])
            self.assertEqual(p.store_open, 0)
            self.assertEqual(p.store.events, [])
            p.assert_idle()
        p = self.p
        with p._claim_transaction() as c:
            c.execute("INSERT synthetic_caller", ("default-owner",))
            with p._claim_transaction(c, join=True, _rollback_receipt=None) as joined:
                self.assertIs(joined, c)
                self.assertEqual((c.commits, c.rollbacks), (0, 0))
            with self.assertRaisesRegex(RuntimeError, "^claim_transaction_requires_idle_owner$"):
                with p._claim_transaction(_rollback_receipt=[]):
                    self.fail("receipt_adopted_caller")
            self.assertIs(p._claim_tx_connection, c)
            self.assertEqual(c.pending, [("synthetic_caller", ("default-owner",))])
        self.assertEqual((p.sql.commits, p.sql.rollbacks), (1, 0))
        p.assert_idle()

    def test_21_F1_receipt_positive_exact_owner_only_never_COMMITTED_or_UNKNOWN(self):
        for phase in ("rollback", "commit", "rollback_unknown", "commit_unknown", "journal_unknown"):
            p = receiver_class(self.namespace)()
            receipt, primary = [], SyntheticCancel("receipt owner primary")
            if phase == "rollback_unknown":
                p.sql.rollback_primary = RuntimeError("synthetic rollback refusal")
            if phase == "commit_unknown":
                p.sql.commit_primary, p.sql.commit_then_raise = primary, True
            if phase == "journal_unknown":
                p.journal_primary = primary
            error = None
            try:
                with p._claim_transaction(_rollback_receipt=receipt) as c:
                    c.execute("INSERT synthetic_caller", (phase,))
                    if phase in {"rollback", "rollback_unknown"}:
                        raise primary
            except BaseException as escaped:
                error = escaped
            if phase == "rollback":
                self.assertIs(error, primary)
                self.assertEqual(len(receipt), 1)
                self.assertIs(type(receipt[0]), tuple)
                self.assertIs(receipt[0][0], p.sql)
                self.assertEqual(receipt[0][1], threading.get_ident())
                self.assertIs(receipt[0][2], primary)
                self.assertEqual(p.sql.committed, [])
                p.assert_idle()
                with self.assertRaisesRegex(ValueError, "^invalid_claim_rollback_receipt_mode$"):
                    with p._claim_transaction(_rollback_receipt=receipt):
                        self.fail("nonempty_receipt_reused")
                self.assertEqual((p.sql.commits, p.sql.rollbacks), (0, 1))
            else:
                self.assertEqual(receipt, [])
                if phase == "commit":
                    self.assertIsNone(error)
                    self.assertEqual(p.sql.committed, [("synthetic_caller", (phase,))])
                    p.assert_idle()
                else:
                    self.assertIs(error, primary)
                    self.assertIs(p._transaction_quarantine, p.sql)
                    self.assertIs(p._transaction_primary, primary)
                    self.assertIs(p._claim_tx_connection, p.sql)
                    before = list(p.sql.events)
                    with self.assertRaisesRegex(RuntimeError, "^provider_lifecycle_not_ready$"):
                        with p._claim_transaction(_rollback_receipt=[]):
                            self.fail("UNKNOWN_retried")
                    self.assertEqual(p.sql.events, before)

    def test_22_F1_receipt_publication_fault_preserves_primary_and_observed_effect(self):
        for seam in ("publish_call", "publish_return"):
            p = receiver_class(self.namespace)()
            primary, secondary = SyntheticCancel("original SQL failure"), SyntheticCancel("publication fault")
            p.sql.insert_primary = primary
            result, error, events = f1_observe(p, lambda: p._add_secret(self.arguments()),
                label=self._testMethodName + "." + seam, primary=primary, seam=seam, injected=secondary)
            self.assertIsNone(result)
            self.assertIs(error, primary)
            self.assertIsNot(error, secondary)
            self.assertIn("consumer_primary", events)
            self.assertIn("rollback_true", events)
            self.assertEqual(p.sql.committed, [])
            self.assertEqual(p.sql.pending, [])
            self.assertEqual((p.sql.commits, p.sql.rollbacks), (0, 1))
            if seam == "publish_call":
                self.assertEqual(p.store.events, ["snapshot", "put"])
                self.assertIn(self.sid(), p.store.values)  # No invented proof/unsafe deletion.
                self.assertNotIn("restore", events)
            else:
                self.assertEqual(p.store.events, ["snapshot", "put", "restore"])
                self.assertEqual(p.store.values, {})  # Actual appended positive proof remains valid.
            p.assert_idle()

    def test_23_F1_receipt_read_fault_keeps_original_primary_without_compensation(self):
        p = self.p
        primary, secondary = SyntheticCancel("original SQL failure"), SyntheticCancel("proof read fault")
        p.sql.insert_primary = primary
        result, error, events = f1_observe(p, lambda: p._add_secret(self.arguments()),
            label=self._testMethodName, primary=primary, seam="read", injected=secondary)
        self.assertIsNone(result)
        self.assertIs(error, primary)
        self.assertIsNot(error, secondary)
        self.assertIn("rollback_true", events)
        self.assertNotIn("restore", events)
        self.assertEqual(p.store.events, ["snapshot", "put"])
        self.assertIn(self.sid(), p.store.values)
        self.assertEqual(p.sql.committed, [])
        self.assertEqual(p.sql.pending, [])
        p.assert_idle()

    def test_24_F1_nonmatching_or_missing_observation_never_authorizes_compensation(self):
        for mismatch in ("connection", "thread", "primary", "shape", "missing"):
            p = receiver_class(self.namespace)()
            primary = SyntheticCancel("original SQL failure")
            p.sql.insert_primary = primary

            def invalidate(receipt):
                connection, thread, error = receipt[0]
                if mismatch == "connection": connection = object()
                elif mismatch == "thread": thread += 1
                elif mismatch == "primary": error = SyntheticCancel("foreign primary")
                receipt[:] = ([] if mismatch == "missing" else
                              [[connection, thread, error]] if mismatch == "shape" else
                              [(connection, thread, error)])

            result, error, events = f1_observe(p, lambda: p._add_secret(self.arguments()),
                label=self._testMethodName + "." + mismatch, primary=primary, mutate=invalidate)
            self.assertIsNone(result)
            self.assertIs(error, primary)
            self.assertIn("mutated", events)
            self.assertIn("rollback_true", events)
            self.assertNotIn("restore", events)
            self.assertEqual(p.store.events, ["snapshot", "put"])
            self.assertIn(self.sid(), p.store.values)
            self.assertEqual(p.sql.committed, [])
            self.assertEqual(p.sql.pending, [])
            self.assertEqual((p.sql.commits, p.sql.rollbacks), (0, 1))
            p.assert_idle()


def make_suite(raw, source, scratch, case_names):
    namespace, bindings = load_functions(raw, source)
    SecretMetadataOwnerTests.namespace = namespace
    names = sorted(n for n in vars(SecretMetadataOwnerTests) if n.startswith("test_"))
    selected = list(case_names)
    if len(selected) != len(set(selected)) or any(name not in names for name in selected):
        raise ValueError("invalid_focused_roster")
    return unittest.TestSuite(SecretMetadataOwnerTests(name) for name in selected), bindings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).absolute().parents[1] / "__init__.py")
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    names = args.case or sorted(n for n in vars(SecretMetadataOwnerTests) if n.startswith("test_"))
    suite, _ = make_suite(args.source.read_bytes(), args.source, None, names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
