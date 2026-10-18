"""Queued settings SOURCE contract; no plugin, SDK, YAML or native authority.

Execute genuine relevant-settings/auto-consumer/_run_job bodies on declared
synthetic own settings faults and read-only row actors. The host import actor
REFUSES hermes_constants; it supplies no SDK/module or writer authority. Extractor
outcomes are authored observations, not real parser/model/claim/graph effects.
The two SQLite cases use genuine generic JobStore only, never a claims table.
Existing shipped helper layout is required beside this file in the Git tree.
"""
from __future__ import annotations

import ast
import builtins
from contextlib import closing
from contextvars import ContextVar
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import types
import unittest

AUTO = "MEMORY_WIKI_GRAPH_AUTO_EXTRACT"
GRAPH = "MEMORY_WIKI_GRAPH_EXTRACT_ENABLED"
CHAT = "a1" * 16
SESSION = "job_" + "b2" * 16
STAMP = 4_000_000


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def helper(raw, path):
    module = types.ModuleType("settings_shipped_helper")
    module.__file__, module.__package__ = str(path), ""
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module


def no_host_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "hermes_constants":
        raise ModuleNotFoundError("synthetic standalone host absent", name="hermes_constants")
    return builtins.__import__(name, globals, locals, fromlist, level)


class ReadRows:
    """Read-only scripted source data, NOT SQLite/provider/writer admission."""
    def __init__(self, actor, rows=()):
        self.actor, self.rows = actor, list(rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)

    def execute(self, sql, args):
        self.actor.reads.append(sql.split()[0:4])
        if sql.startswith("SELECT rowid AS _graph_rowid") or sql.startswith("SELECT * FROM claims"):
            rows = [] if self.actor.missing else [self.actor.row]
        elif sql.startswith("SELECT 1 FROM relations"):
            rows = [(1,)] if self.actor.existing else []
        elif "SELECT text,source FROM evidence" in sql:
            rows = [{"source": "extractor:llm", "text": json.dumps({
                "schema": "memory-wiki-extraction-evidence-v1", "session_id": SESSION,
                "speaker": "user", "message_index": 0, "evidence_quote": "synthetic quote",
                "extractor": "extractor:llm"})}]
        else:
            raise AssertionError("unexpected or non-read SOURCE SQL shape")
        return ReadRows(self.actor, rows)


class SettingsActor:
    """Synthetic settings/readonly rows only; intentionally no writer methods."""
    def __init__(self, home):
        self.home, self.db_path = Path(home), "synthetic-label-not-a-db"
        self.bot_id, self.session_id, self.project_scope = "source-only-bot", SESSION, ""
        self._lock, self._conn, self._owned_conn = threading.RLock(), None, None
        self._transaction_quarantine, self._transaction_primary = None, None
        self.row = {"id": "c_settings", "origin_bot_id": self.bot_id,
            "origin_chat_hash": CHAT, "origin_session_id": SESSION, "project_id": "",
            "status": "active", "temporal_status": "current", "visibility_scope": "chat",
            "secrecy_level": "public", "risk": "", "quarantined_at": 0,
            "source": "extractor:llm", "type": "fact", "claim": "Alpha depends on Beta project"}
        self.settings, self.faults = types.SimpleNamespace(enabled=True), []
        self.reads, self.settings_reads, self.deliveries, self.audits = [], [], [], []
        self.missing = self.existing = False
        self.outcome = {"applied": 0, "errors": [], "proposals": [], "relation_ids": []}
        self.provider_fault = None

    def _graph_extraction_settings(self):
        self.settings_reads.append("own synthetic settings read")
        if self.faults:
            raise self.faults.pop(0)
        return self.settings

    def _connect(self):
        return ReadRows(self)

    def _chat_hash(self, session_id=""):
        return CHAT

    def _graph_effect_actor(self):
        return ("synthetic observation; NOT authority",)

    def _claim_visible(self, row):
        return row["visibility_scope"] == "chat"

    def _graph_extract_claim(self, request):
        self.deliveries.append(dict(request))
        if self.provider_fault is not None:
            raise self.provider_fault
        return dict(self.outcome)

    def _audit(self, *args):
        self.audits.append(args)


def run_source(actor, api, **changes):
    job = {"job_type": "enrich_claim_graph", "payload_json": '{"claim_id":"c_settings"}',
        "partition_key": api._digest(actor.bot_id, CHAT, "c_settings"),
        "profile_key": api.profile_key(actor), "owner_key": api.owner_key(actor)}
    job.update(changes)
    return api._run_job(actor, None, job)


class SettingsSourceTests(unittest.TestCase):
    def setUp(self):
        self.actor = self.actor_cls(self.synthetic_home)
        self.public.clear()
        self.public.update({AUTO: "1", GRAPH: "1"})
        self.scope.set({})
        self.clock.values = []

    def test_queued_unavailable_retains_dependency_intent(self):
        self.actor.faults = [OSError("synthetic one-shot settings read")]
        outcome = run_source(self.actor, self.api)
        witness = {"schema": "graph-settings-unavailable-source/v1", "level": "SOURCE_SYNTHETIC_SETTINGS_ONLY",
            "source_sha256": self.source_sha, "entry_sha256": self.entry_sha, "test_sha256": self.test_sha,
            "outcome": outcome, "decision": "defer" if isinstance(outcome, tuple) else "finish_success" if outcome == "" else "failure",
            "settings_reads": len(self.actor.settings_reads), "authored_extractor_calls": len(self.actor.deliveries),
            "genuine_YAML_native_SQL_claim_model": False}
        witness["outcome_sha256"] = digest(json.dumps(witness, sort_keys=True, separators=(",", ":")).encode())
        if self.witness_root is not None:
            with (self.witness_root / "settings-witness.json").open("xb") as stream:
                stream.write((json.dumps(witness, sort_keys=True) + "\n").encode())
                stream.flush()
        self.assertIsInstance(outcome, tuple, "queued_settings_unavailable_consumed_as_success")
        self.assertEqual(outcome, ("defer", STAMP + 60))
        self.assertEqual(len(self.actor.settings_reads), 1)
        self.assertEqual(self.actor.deliveries, [])
        self.assertEqual(self.actor.audits, [])
        self.assertEqual(self.actor.session_id, SESSION)

    def test_source_same_intent_recovers_once_without_preread(self):
        self.actor.faults = [PermissionError("synthetic own read permission")]
        self.assertEqual(run_source(self.actor, self.api), ("defer", STAMP + 60))
        self.assertEqual(self.actor.deliveries, [])
        self.assertEqual(run_source(self.actor, self.api), "")
        self.assertEqual(len(self.actor.settings_reads), 2)
        self.assertEqual(len(self.actor.deliveries), 1)
        self.assertEqual(self.actor.deliveries[0]["claim_id"], "c_settings")

    def test_source_default_tuple_and_auto_callers_stay_fail_closed(self):
        self.actor.faults = [OSError("default"), OSError("default auto")]
        self.assertEqual(self.actor.relevant_graph_extraction_settings(), (False, False))
        stats = self.actor._auto_graph_enrich_extracted_claims(["c_settings"])
        self.assertEqual((stats["received"], stats["attempted"], stats["errors"]), (1, 0, 0))
        self.assertEqual(self.actor.deliveries, [])

    def test_source_known_auto_off_read_failure_is_noop(self):
        self.public[AUTO] = "0"
        self.actor.faults = [OSError("unnecessary YAML failure")]
        self.assertEqual(run_source(self.actor, self.api), "")
        self.assertEqual(self.actor.deliveries, [])

    def test_source_graph_off_is_noop(self):
        self.actor.settings = types.SimpleNamespace(enabled=False)
        self.assertEqual(run_source(self.actor, self.api), "")
        self.assertEqual(self.actor.deliveries, [])

    def test_source_legacy_absent_keeps_explicit_gates(self):
        self.actor.settings = None
        self.public[GRAPH] = "0"
        self.assertEqual(run_source(self.actor, self.api), "")
        self.assertEqual(self.actor.deliveries, [])
        self.public[GRAPH] = "1"
        self.assertEqual(run_source(self.actor, self.api), "")
        self.assertEqual(len(self.actor.deliveries), 1)

    def test_source_invalid_and_unsupported_are_not_dependencies(self):
        for failure in (ValueError("invalid authored settings"), ImportError("unsupported authored dependency")):
            self.actor.faults = [failure]
            self.assertEqual(run_source(self.actor, self.api), "")
        self.assertEqual(self.actor.deliveries, [])

    def test_source_valid_empty_outcome_is_lawful_success(self):
        self.assertEqual(run_source(self.actor, self.api), "")
        self.assertEqual(len(self.actor.deliveries), 1)
        self.assertEqual(json.loads(self.actor.audits[-1][2])["errors"], 0)

    def test_source_existing_ineligible_unrelated_remain_noops(self):
        for mode in ("existing", "ineligible", "unrelated"):
            actor = self.actor_cls(self.synthetic_home)
            if mode == "existing": actor.existing = True
            elif mode == "ineligible": actor.row["secrecy_level"] = "private"
            else: actor.row["claim"] = "short"
            self.assertEqual(run_source(actor, self.api), "")
            self.assertEqual(actor.deliveries, [])
            stats = json.loads(actor.audits[-1][2])
            self.assertEqual(stats["skipped_" + mode], 1)

    def test_source_provider_and_parser_errors_keep_provider_retry(self):
        for fault in (RuntimeError("authored provider failure"), ValueError("authored parser failure")):
            self.actor.provider_fault = fault
            self.assertEqual(run_source(self.actor, self.api), "provider")
        self.actor.provider_fault = None
        self.actor.outcome["errors"] = ["authored returned error"]
        self.assertEqual(run_source(self.actor, self.api), "provider")

    def test_source_deadline_keeps_timeout_without_delivery(self):
        self.clock.values = [0.0, 12.0, 12.0]
        self.assertEqual(run_source(self.actor, self.api), "timeout")
        self.assertEqual(self.actor.deliveries, [])

    def test_source_owner_and_lease_refuse_before_settings(self):
        self.assertEqual(run_source(self.actor, self.api, owner_key="f" * 64), "owner_mismatch")
        job = {"job_type": "enrich_claim_graph", "payload_json": '{"claim_id":"c_settings"}'}
        self.assertEqual(self.api._run_job(self.actor, None, job, lease_valid=lambda: False), "timeout")
        self.assertEqual(self.actor.settings_reads, [])
        self.assertEqual(self.actor.deliveries, [])

    def test_source_cancel_keeps_original_primary_and_no_completion(self):
        primary = KeyboardInterrupt("synthetic cancel before graph attempt")
        self.actor.faults = [primary]
        with self.assertRaises(KeyboardInterrupt) as raised:
            run_source(self.actor, self.api)
        self.assertIs(raised.exception, primary)
        self.assertEqual(self.actor.deliveries, [])
        self.assertIsNone(self.actor._transaction_quarantine)

    def test_source_typed_cause_and_no_blanket_retry(self):
        failure = PermissionError("synthetic settings")
        self.actor.faults = [failure]
        with self.assertRaises(self.api.GraphSettingsUnavailable) as raised:
            self.actor.relevant_graph_extraction_settings(_raise_unavailable=True)
        self.assertIs(raised.exception.__cause__, failure)
        self.actor.faults = [RuntimeError("permanent authored failure")]
        self.assertEqual(self.actor.relevant_graph_extraction_settings(_raise_unavailable=True), (False, False))

    def test_source_public_scope_and_standalone_environment_precedence(self):
        self.public[AUTO] = "0"
        self.scope.set({AUTO: "1", GRAPH: "1"})
        self.assertEqual(self.actor.relevant_graph_extraction_settings(), (False, True))
        self.public.clear()
        self.assertEqual(self.actor.relevant_graph_extraction_settings(), (True, True))
        self.scope.set({})
        previous = os.environ.get(AUTO)
        try:
            os.environ[AUTO] = "1"
            self.assertEqual(self.actor.relevant_graph_extraction_settings(), (True, True))
            self.actor.home = self.synthetic_home / "foreign-no-settings-files"
            self.assertEqual(self.actor.relevant_graph_extraction_settings(), (False, True))
        finally:
            if previous is None: os.environ.pop(AUTO, None)
            else: os.environ[AUTO] = previous


class SettingsSQLiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with closing(sqlite3.connect(str(cls.db_path))) as conn:
            conn.execute("PRAGMA page_size=1024")
            cls.api.install_schema(conn)
            conn.commit()
        cls.opened = cls.closed = 0

    def setUp(self):
        self.public.clear()
        self.public.update({AUTO: "1", GRAPH: "1"})
        self.scope.set({})
        self.clock.values = []
        self.conn = sqlite3.connect(str(self.db_path))
        type(self).opened += 1
        self.addCleanup(self.close_fixture)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("DELETE FROM memory_jobs")
        self.conn.execute("DELETE FROM memory_job_budgets")
        self.conn.commit()
        self.store = self.api.JobStore(self.db_path, "a" * 64, "b" * 64)

    def close_fixture(self):
        self.conn.close()
        type(self).closed += 1

    def row(self, identifier):
        return dict(self.conn.execute("SELECT * FROM memory_jobs WHERE job_id=?", (identifier,)).fetchone())

    def test_sql_dependency_defer_and_healthy_retry_keep_same_intent(self):
        identifier = self.store.enqueue("enrich_claim_graph", {"claim_id": "c_settings"}, "c" * 64, now=STAMP)
        job = self.store.lease("d" * 32, now=STAMP)
        actor = self.actor_cls(self.synthetic_home)
        actor.faults = [OSError("authored unavailable")]
        outcome = run_source(actor, self.source_api)
        self.assertEqual(outcome, ("defer", STAMP + 60))
        self.assertTrue(self.store.defer(job, "d" * 32, until=outcome[1], now=STAMP))
        row = self.row(identifier)
        self.assertEqual((row["status"], row["attempts"], row["last_error_code"]), ("pending", 0, "dependency"))
        self.assertEqual((row["job_id"], row["generation"], row["payload_json"]), (identifier, 1, '{"claim_id":"c_settings"}'))
        self.assertIsNone(self.store.lease("e" * 32, now=STAMP + 59))
        retry = self.store.lease("e" * 32, now=STAMP + 60)
        self.assertEqual(retry["job_id"], identifier)
        self.assertEqual(run_source(actor, self.source_api), "")
        self.assertTrue(self.store.finish(retry, "e" * 32, now=STAMP + 60))
        self.assertEqual(self.row(identifier)["status"], "done")
        self.assertEqual(len(actor.deliveries), 1)

    def test_sql_stale_defer_cannot_ack_new_owner(self):
        identifier = self.store.enqueue("enrich_claim_graph", {"claim_id": "c_settings"}, "c" * 64, now=STAMP)
        old = self.store.lease("d" * 32, now=STAMP)
        current = self.store.lease("e" * 32, now=STAMP + 1801)
        before = self.row(identifier)
        self.assertIsNotNone(current)
        self.assertFalse(self.store.defer(old, "d" * 32, until=STAMP + 1900, now=STAMP + 1801))
        self.assertEqual(self.row(identifier), before)
        self.assertTrue(self.store.finish(current, "e" * 32, now=STAMP + 1801))


class SettingsStaticTests(unittest.TestCase):
    def test_static_original_model_override_reader_unchanged(self):
        node = self.peer.qualified(self.entry_tree, "MemoryWikiProvider._graph_extraction_settings")
        self.assertEqual(self.peer.ast_digest(node), "ac7d702b54d53a7f182d8f8bd23b467175239f330207dda4da7679e3798ed22d")
        self.assertTrue(self.peer.contains(node, "read_graph_extraction_settings(self.home, model_override=override)"))

    def test_static_original_close_run_once_defer_unknown_protocol(self):
        for name, expected in {"_close_job_worker": "eaa1a8fb0d935f2f09372447d5f1cc662031e0ecf7c8562f3f062ac4e0ef3aa1",
            "run_once": "af74e0ab1e310cbcf8798840d2a9c949f6f7d605b3cf1099339a714875b9c4f8",
            "JobStore.defer": "476e3185328a9f36afe80f8f1cec7386428a0693e612d3fd2dc63cc56ec24ee5"}.items():
            self.assertEqual(self.peer.ast_digest(self.peer.qualified(self.source_tree, name)), expected)
        node = self.peer.qualified(self.source_tree, "run_once")
        self.assertTrue(self.peer.contains(node, 'store.defer(job, worker_id, until=outcome[1])'))
        self.assertTrue(self.peer.contains(node, 'provider._transaction_quarantine is not None or not isinstance(primary, Exception)'))

    def test_static_strict_reader_single_read_and_narrow_failure(self):
        node = self.peer.qualified(self.entry_tree, "MemoryWikiProvider.relevant_graph_extraction_settings")
        reads = [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "_graph_extraction_settings"]
        self.assertEqual(len(reads), 1)
        handler = next(n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)
                       and isinstance(n.type, ast.Name) and n.type.id == "OSError")
        self.assertTrue(self.peer.contains(handler, "_raise_unavailable and enabled(names[0])"))


class SourceClock:
    def __init__(self):
        self.values = []

    def time(self):
        return STAMP

    def monotonic(self):
        return self.values.pop(0) if self.values else 0.0


def make_suite(source_raw, source_path, entry_raw, entry_path, peer_raw, peer_path, *,
               test_raw=None, witness_root=None, db_path=None, cases=None):
    peer = helper(peer_raw, peer_path)
    source_tree, entry_tree = ast.parse(source_raw), ast.parse(entry_raw)
    module = types.ModuleType("genuine_settings_background_source")
    module.__file__, module.__package__ = str(source_path), ""
    exec(compile(source_raw, str(source_path), "exec", dont_inherit=True), module.__dict__)
    clock = SourceClock()
    # Only the source outcome lane has an authored clock; generic JobStore keeps
    # genuine time/SQLite. No native/writer guards are substituted in either.
    module.time = clock
    public, scope = {}, ContextVar("synthetic_settings_scope", default={})
    namespace = {"__name__": "genuine_settings_consumer_source", "__builtins__": {**vars(builtins), "__import__": no_host_import},
        "Path": Path, "os": os, "json": json, "time": clock, "_QDRANT_PROFILE_SCOPE": scope,
        "_IMPORT_HERMES_HOME": Path(witness_root or source_path.parent), "_background_jobs": module,
        "_profile_public_env": lambda home, names, **kwargs: dict(public),
        "_env_int": lambda name, default, low, high: default,
        "secret_scan": lambda text: {}, "tokens": lambda text: text.split(),
        "GRAPH_AUTO_RELATION_HINT_RE": re.compile(r"depends on")}
    names = ["relevant_graph_extraction_settings", "_auto_graph_enrich_extracted_claims"]
    nodes = [peer.qualified(entry_tree, "MemoryWikiProvider." + name) for name in names]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    extracted = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
    exec(compile(extracted, str(entry_path), "exec", dont_inherit=True), namespace)
    actor_cls = type("BoundSettingsSourceActor", (SettingsActor,), {name: namespace[name] for name in names})
    for cls in (SettingsSourceTests, SettingsSQLiteTests, SettingsStaticTests):
        cls.source_tree, cls.entry_tree, cls.peer = source_tree, entry_tree, peer
        cls.source_sha, cls.entry_sha, cls.test_sha = digest(source_raw), digest(entry_raw), digest(test_raw or Path(__file__).read_bytes())
        cls.synthetic_home = Path(witness_root or source_path.parent)
        cls.actor_cls, cls.scope, cls.public, cls.clock = actor_cls, scope, public, clock
        cls.witness_root = None if witness_root is None else Path(witness_root)
    SettingsSourceTests.api = module
    SettingsSQLiteTests.source_api = module
    if db_path is not None:
        sql_module = types.ModuleType("genuine_settings_JobStore_component")
        sql_module.__file__, sql_module.__package__ = str(source_path), ""
        exec(compile(source_raw, str(source_path), "exec", dont_inherit=True), sql_module.__dict__)
        SettingsSQLiteTests.api, SettingsSQLiteTests.db_path = sql_module, Path(db_path)
    roster = {name: cls for cls in (SettingsSourceTests, SettingsSQLiteTests, SettingsStaticTests)
              for name in unittest.defaultTestLoader.getTestCaseNames(cls)}
    selected = sorted(roster) if cases is None else list(cases)
    return unittest.TestSuite(roster[name](name) for name in selected)


if __name__ == "__main__":
    root = Path(__file__).absolute().parents[1]
    with tempfile.TemporaryDirectory(prefix="graph-settings-", dir=os.environ.get("TMPDIR")) as temporary:
        own = Path(temporary)
        suite = make_suite((root / "background_jobs.py").read_bytes(), root / "background_jobs.py",
            (root / "__init__.py").read_bytes(), root / "__init__.py",
            Path(__file__).with_name("test_graph_worker_origin_session.py").read_bytes(),
            Path(__file__).with_name("test_graph_worker_origin_session.py"), witness_root=own, db_path=own / "queue.db")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
