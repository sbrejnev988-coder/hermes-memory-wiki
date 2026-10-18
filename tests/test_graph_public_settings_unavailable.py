"""Public opt-in availability SOURCE regressions, not SDK/provider acceptance.

The ACTUAL source-extracted public reader, settings/auto consumer and _run_job
execute. Public path/open/iteration and graph-YAML results are explicitly authored
nonsecret I/O actors: NO real .env/config/auth file is created or read. Reuse the
shipped F1 readonly actors and suite binder; no SDK or writer authority substitute.
Only generic JobStore cases open the explicitly supplied tiny scratch SQLite DB.
"""
from __future__ import annotations

import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest

AUTO = "MEMORY_WIKI_GRAPH_AUTO_EXTRACT"
GRAPH = "MEMORY_WIKI_GRAPH_EXTRACT_ENABLED"
STAMP = 4_000_000


class PublicPath:
    """A label, never a filesystem Path or host identity attestation."""
    def __init__(self, io, label):
        self.io, self.label = io, str(label)

    def __str__(self):
        return self.label

    def expanduser(self):
        return self

    def resolve(self):
        # Constructing a Path is lexical only; never call its resolve/stat/open.
        return Path(self.label)

    def __truediv__(self, leaf):
        if leaf != ".env":
            raise AssertionError("unexpected SOURCE public reader path shape")
        self.io.home_labels.append(self.label)
        return self.io


class PublicIO:
    """Synthetic nonsecret file-I/O actor. It performs ZERO real file I/O."""
    def __init__(self):
        self.lines = [AUTO + "=1\n", GRAPH + "=1\n"]
        self.exists = True
        self.outcomes, self.active = [], None
        self.primary = PermissionError("authored nonsecret public read unavailable")
        self.stats, self.opens, self.iterations, self.exits = 0, 0, 0, 0
        self.home_labels = []

    def path(self, label):
        return PublicPath(self, label)

    def is_file(self):
        self.stats += 1
        return self.exists

    def open(self, mode, *, encoding):
        if (mode, encoding) != ("r", "utf-8-sig"):
            raise AssertionError("unexpected SOURCE public open contract")
        self.opens += 1
        self.active = self.outcomes.pop(0) if self.outcomes else None
        if self.active == "open":
            raise self.primary
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.exits += 1
        return False

    def __iter__(self):
        self.iterations += 1
        for index, line in enumerate(self.lines):
            if self.active == "iteration" and index == 1:
                raise self.primary
            yield line


def reset_fixture(test):
    test.actor = test.actor_cls(test.synthetic_home)
    test.io = PublicIO()
    test.namespace["Path"] = test.io.path
    token = test.scope.set({})
    test.addCleanup(test.scope.reset, token)
    test.clock.values = []
    previous = os.environ.get(AUTO)
    os.environ[AUTO] = "0"
    def restore_environment():
        if previous is None:
            os.environ.pop(AUTO, None)
        else:
            os.environ[AUTO] = previous
    test.addCleanup(restore_environment)


class PublicSourceTests(unittest.TestCase):
    def setUp(self):
        reset_fixture(self)

    def run_claim(self, **changes):
        return self.shared.run_source(self.actor, self.source_api, **changes)

    def settings(self, strict=True):
        return self.actor.relevant_graph_extraction_settings(_raise_unavailable=strict)

    def reader(self, strict=False):
        return self.namespace["_profile_public_env"](self.actor.home, (AUTO, GRAPH), _raise_unavailable=strict)

    def test_public_queued_open_unavailable_retains_dependency(self):
        self.io.outcomes = ["open"]
        outcome = self.run_claim()
        witness = {"schema": "graph-public-settings-unavailable-source/v1",
            "level": "SOURCE_SYNTHETIC_NONSECRET_FILE_IO_ONLY",
            "source_sha256": self.source_sha, "entry_sha256": self.entry_sha, "test_sha256": self.test_sha,
            "actual_public_function_ast_sha256": self.public_ast_sha,
            "own_authored_AUTO": "1", "ambient_authored_AUTO": os.environ[AUTO],
            "public_is_file_true": self.io.exists, "public_stats": self.io.stats,
            "public_opens": self.io.opens, "public_iterations": self.io.iterations,
            "settings_reads": len(self.actor.settings_reads), "authored_extractor_calls": len(self.actor.deliveries),
            "outcome": outcome, "decision": "defer" if isinstance(outcome, tuple) else "finish_success" if outcome == "" else "failure",
            "actual_public_reader_SOURCE_executed": True,
            "genuine_public_file_YAML_native_SQL_claim_model": False}
        witness["outcome_sha256"] = hashlib.sha256(json.dumps(witness, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if self.witness_root is not None:
            with (self.witness_root / "public-witness.json").open("xb") as stream:
                stream.write((json.dumps(witness, sort_keys=True) + "\n").encode())
                stream.flush()
        self.assertIsInstance(outcome, tuple, "queued_public_unavailable_consumed_as_success")
        self.assertEqual(outcome, ("defer", STAMP + 60))
        self.assertEqual((self.io.stats, self.io.opens, len(self.actor.settings_reads)), (1, 1, 1))
        self.assertEqual(self.actor.deliveries, [])
        self.assertEqual(self.actor.audits, [])

    def test_public_queued_iteration_failure_discards_partial_flag(self):
        self.io.lines[0] = AUTO + "=0\n"
        self.io.outcomes = ["iteration"]
        self.assertEqual(self.run_claim(), ("defer", STAMP + 60))
        self.assertEqual((self.io.opens, self.io.iterations, self.io.exits), (1, 1, 1))
        self.assertEqual(self.actor.deliveries, [])

    def test_public_same_intent_recovers_without_double_reads(self):
        self.io.outcomes = ["open", None]
        self.assertEqual(self.run_claim(), ("defer", STAMP + 60))
        self.assertEqual(self.actor.deliveries, [])
        self.assertEqual(self.run_claim(), "")
        self.assertEqual((self.io.opens, len(self.actor.settings_reads)), (2, 2))
        self.assertEqual(len(self.actor.deliveries), 1)
        self.assertEqual(self.actor.deliveries[0]["claim_id"], "c_settings")

    def test_public_reader_default_dict_and_strict_original_error(self):
        self.io.outcomes = ["open", "open"]
        self.assertEqual(self.reader(), {})
        with self.assertRaises(PermissionError) as raised:
            self.reader(True)
        self.assertIs(raised.exception, self.io.primary)
        self.assertEqual(self.io.opens, 2)

    def test_public_reader_healthy_allowlist_quotes_export_and_duplicates(self):
        self.io.lines = ["IGNORED_PUBLIC_COLOR=blue\n", "not an assignment\n",
            " export " + AUTO + " = 'off'\n", AUTO + '= "yes"\n', GRAPH + "=on\n"]
        self.assertEqual(self.reader(True), {AUTO: "yes", GRAPH: "on"})
        self.assertEqual((self.io.opens, self.io.iterations, self.io.exits), (1, 1, 1))

    def test_public_default_tuple_and_auto_remain_nonstrict(self):
        self.io.outcomes = ["open", "iteration"]
        self.assertEqual(self.settings(False), (False, True))
        stats = self.actor._auto_graph_enrich_extracted_claims(["c_settings"])
        self.assertEqual((stats["received"], stats["attempted"], stats["errors"]), (1, 0, 0))
        self.assertEqual((self.io.opens, len(self.actor.settings_reads)), (2, 2))
        self.assertEqual(self.actor.deliveries, [])

    def test_public_known_off_beats_ambient_on_and_yaml_unavailable(self):
        self.io.lines[0] = AUTO + "=0\n"
        os.environ[AUTO] = "1"
        self.actor.faults = [OSError("authored unnecessary graph YAML read")]
        self.assertEqual(self.run_claim(), "")
        self.assertEqual((self.io.opens, len(self.actor.settings_reads)), (1, 1))
        self.assertEqual(self.actor.deliveries, [])

    def test_public_unavailable_independent_healthy_yaml_off_is_noop(self):
        os.environ[AUTO] = "1"
        self.io.outcomes = ["open"]
        self.actor.settings.enabled = False
        self.assertEqual(self.settings(), (False, False))
        self.assertEqual((self.io.opens, len(self.actor.settings_reads)), (1, 1))
        self.assertEqual(self.actor.deliveries, [])

    def test_public_unavailable_scope_or_ambient_off_is_not_known_off(self):
        self.scope.set({AUTO: "0", GRAPH: "0"})
        self.io.outcomes = ["open"]
        self.assertEqual(self.run_claim(), ("defer", STAMP + 60))
        self.assertEqual(self.actor.deliveries, [])

    def test_public_unavailable_absent_yaml_is_not_independent_off(self):
        self.actor.settings = None
        self.scope.set({GRAPH: "0"})
        self.io.outcomes = ["open"]
        self.assertEqual(self.run_claim(), ("defer", STAMP + 60))
        self.assertEqual((self.io.opens, len(self.actor.settings_reads)), (1, 1))

    def test_public_unavailable_does_not_borrow_ambient_on(self):
        os.environ[AUTO] = "1"
        self.io.outcomes = ["iteration"]
        self.assertEqual(self.run_claim(), ("defer", STAMP + 60))
        self.assertEqual(self.actor.deliveries, [])

    def test_public_typed_cause_preserved_with_two_unavailable_inputs(self):
        self.io.outcomes = ["open"]
        self.actor.faults = [OSError("independent authored YAML unavailable")]
        with self.assertRaises(self.source_api.GraphSettingsUnavailable) as raised:
            self.settings()
        self.assertIs(raised.exception.__cause__, self.io.primary)
        self.assertEqual((self.io.opens, len(self.actor.settings_reads)), (1, 1))

    def test_public_iteration_error_preserves_direct_cause(self):
        self.io.outcomes = ["iteration"]
        with self.assertRaises(self.source_api.GraphSettingsUnavailable) as raised:
            self.settings()
        self.assertIs(raised.exception.__cause__, self.io.primary)
        self.assertEqual(self.io.exits, 1)

    def test_public_genuine_absence_reader_and_legacy_environment(self):
        self.io.exists = False
        self.assertEqual(self.reader(True), {})
        os.environ[AUTO] = "1"
        self.assertEqual(self.settings(), (True, True))
        self.assertEqual(self.io.opens, 0)
        self.assertEqual(len(self.actor.settings_reads), 1)

    def test_public_absence_default_off_and_legacy_graph_gate(self):
        self.io.exists = False
        self.actor.settings = None
        self.scope.set({GRAPH: "1"})
        self.assertEqual(self.settings(), (False, True))
        self.scope.set({AUTO: "1", GRAPH: "0"})
        self.assertEqual(self.settings(), (True, False))
        self.scope.set({AUTO: "1", GRAPH: "1"})
        self.assertEqual(self.settings(), (True, True))
        self.assertEqual(self.io.opens, 0)

    def test_public_permanent_unicode_is_not_transient_dependency(self):
        self.io.primary = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "authored invalid encoding")
        self.io.outcomes = ["iteration", "iteration"]
        self.assertEqual(self.reader(True), {})
        self.assertEqual(self.run_claim(), "")
        self.assertEqual(self.actor.deliveries, [])
        self.assertEqual(self.io.exits, 2)

    def test_public_permanent_yaml_invalid_and_unsupported_not_blanket_retry(self):
        for fault in (ValueError("authored invalid YAML"), ImportError("authored unsupported dependency")):
            self.io.outcomes = ["open"]
            self.actor.faults = [fault]
            self.assertEqual(self.run_claim(), "")
        self.assertEqual(self.actor.deliveries, [])
        self.assertEqual((self.io.opens, len(self.actor.settings_reads)), (2, 2))

    def test_public_unrelated_read_failure_not_reclassified(self):
        primary = RuntimeError("authored permanent public actor failure")
        self.io.primary, self.io.outcomes = primary, ["open"]
        with self.assertRaises(RuntimeError) as raised:
            self.run_claim()
        self.assertIs(raised.exception, primary)
        self.assertEqual(self.actor.settings_reads, [])
        self.assertEqual(self.actor.deliveries, [])

    def test_public_baseexception_keeps_primary_and_no_completion(self):
        primary = KeyboardInterrupt("authored public read cancellation")
        self.io.primary, self.io.outcomes = primary, ["iteration"]
        with self.assertRaises(KeyboardInterrupt) as raised:
            self.run_claim()
        self.assertIs(raised.exception, primary)
        self.assertEqual(self.io.exits, 1)
        self.assertEqual(self.actor.settings_reads, [])
        self.assertEqual(self.actor.deliveries, [])
        self.assertIsNone(self.actor._transaction_quarantine)

    def test_public_foreign_own_flags_do_not_borrow_importer(self):
        self.actor.home = self.synthetic_home / "foreign-label-no-files"
        self.assertEqual(self.settings(), (True, True))
        self.io.exists = False
        os.environ[AUTO] = "1"
        self.assertEqual(self.settings(), (False, True))
        self.assertEqual(set(self.io.home_labels), {str(self.actor.home)})

    def test_public_foreign_unavailable_is_not_foreign_ambient_off(self):
        self.actor.home = self.synthetic_home / "foreign-label-no-files"
        self.io.outcomes = ["open"]
        self.assertEqual(self.run_claim(), ("defer", STAMP + 60))
        self.assertEqual(self.actor.deliveries, [])

    def test_public_healthy_precedence_public_scope_then_own_environment(self):
        os.environ[AUTO] = "1"
        self.io.lines[0] = AUTO + "=off\n"
        self.scope.set({AUTO: "1"})
        self.assertEqual(self.settings(), (False, True))
        self.io.lines = [GRAPH + "=1\n"]
        self.scope.set({AUTO: "0"})
        self.assertEqual(self.settings(), (False, True))
        self.scope.set({})
        self.assertEqual(self.settings(), (True, True))
        self.assertEqual((self.io.opens, len(self.actor.settings_reads)), (3, 3))

    def test_public_original_owner_and_lease_refuse_before_public_read(self):
        self.assertEqual(self.run_claim(owner_key="f" * 64), "owner_mismatch")
        job = {"job_type": "enrich_claim_graph", "payload_json": '{"claim_id":"c_settings"}'}
        self.assertEqual(self.source_api._run_job(self.actor, None, job, lease_valid=lambda: False), "timeout")
        self.assertEqual((self.io.opens, self.io.stats), (0, 0))
        self.assertEqual(self.actor.settings_reads, [])


class PublicSQLiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with closing(sqlite3.connect(str(cls.db_path))) as conn:
            conn.execute("PRAGMA page_size=1024")
            cls.sql_api.install_schema(conn)
            conn.commit()
        cls.opened = cls.closed = 0

    def setUp(self):
        reset_fixture(self)
        self.conn = sqlite3.connect(str(self.db_path))
        type(self).opened += 1
        self.addCleanup(self.close_fixture)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("DELETE FROM memory_jobs")
        self.conn.execute("DELETE FROM memory_job_budgets")
        self.conn.commit()
        self.store = self.sql_api.JobStore(self.db_path, self.source_api.profile_key(self.actor), self.source_api.owner_key(self.actor))

    def close_fixture(self):
        self.conn.close()
        type(self).closed += 1

    def row(self, identifier):
        return dict(self.conn.execute("SELECT * FROM memory_jobs WHERE job_id=?", (identifier,)).fetchone())

    def enqueue(self):
        partition = self.source_api._digest(self.actor.bot_id, self.shared.CHAT, "c_settings")
        return self.store.enqueue("enrich_claim_graph", {"claim_id": "c_settings"}, partition, now=STAMP)

    def test_public_sql_dependency_pending_same_intent_then_healthy_retry(self):
        identifier = self.enqueue()
        leased = self.store.lease("d" * 32, now=STAMP)
        self.io.outcomes = ["open", None]
        outcome = self.source_api._run_job(self.actor, None, leased)
        self.assertEqual(outcome, ("defer", STAMP + 60))
        self.assertEqual(self.actor.deliveries, [])
        self.assertTrue(self.store.defer(leased, "d" * 32, until=outcome[1], now=STAMP))
        pending = self.row(identifier)
        self.assertEqual((pending["status"], pending["attempts"], pending["last_error_code"]), ("pending", 0, "dependency"))
        self.assertEqual((pending["job_id"], pending["generation"], pending["payload_json"]), (identifier, 1, leased["payload_json"]))
        self.assertEqual((pending["lease_owner"], pending["lease_expires_at"]), ("", 0))
        self.assertIsNone(self.store.lease("e" * 32, now=STAMP + 59))
        retry = self.store.lease("e" * 32, now=STAMP + 60)
        self.assertEqual(retry["job_id"], identifier)
        self.assertEqual(self.source_api._run_job(self.actor, None, retry), "")
        self.assertTrue(self.store.finish(retry, "e" * 32, now=STAMP + 60))
        self.assertEqual(self.row(identifier)["status"], "done")
        self.assertEqual((self.io.opens, len(self.actor.settings_reads), len(self.actor.deliveries)), (2, 2, 1))

    def test_public_sql_stale_token_cannot_defer_or_ack_new_lease(self):
        identifier = self.enqueue()
        stale = self.store.lease("d" * 32, now=STAMP)
        current = self.store.lease("e" * 32, now=STAMP + 1801)
        self.assertIsNotNone(current)
        self.io.outcomes = ["iteration"]
        outcome = self.source_api._run_job(self.actor, None, stale)
        self.assertEqual(outcome, ("defer", STAMP + 60))
        before = self.row(identifier)
        self.assertFalse(self.store.defer(stale, "d" * 32, until=outcome[1], now=STAMP + 1801))
        self.assertFalse(self.store.finish(stale, "d" * 32, now=STAMP + 1801))
        self.assertEqual(self.row(identifier), before)
        self.assertTrue(self.store.finish(current, "e" * 32, now=STAMP + 1801))
        self.assertEqual(self.actor.deliveries, [])


class PublicStaticTests(unittest.TestCase):
    def test_public_static_auto_not_added_to_cached_routing_scope(self):
        names = {"_QDRANT_PROFILE_DEFAULTS", "_PROFILE_RERANK_DEFAULTS", "_PROFILE_RERANK_ENV", "_PROFILE_SECRET_KEYS"}
        declarations = [node for node in self.entry_tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)]
        self.assertEqual(len(declarations), 4)
        self.assertFalse(any(isinstance(node, ast.Constant) and node.value == AUTO
            for declaration in declarations for node in ast.walk(declaration)))


def make_suite(source_raw, source_path, entry_raw, entry_path, settings_raw, settings_path, peer_raw, peer_path, *,
               test_raw=None, witness_root=None, db_path=None, cases=None):
    # The existing shipped F1 binder owns all readonly/source actor construction.
    shared = types.ModuleType("public_settings_shipped_F1_helper")
    shared.__file__, shared.__package__ = str(settings_path), ""
    exec(compile(settings_raw, str(settings_path), "exec", dont_inherit=True), shared.__dict__)
    shared.make_suite(source_raw, source_path, entry_raw, entry_path, peer_raw, peer_path,
        test_raw=settings_raw, witness_root=witness_root, cases=[])
    bound = shared.SettingsSourceTests
    namespace = bound.actor_cls.relevant_graph_extraction_settings.__globals__
    entry_tree = ast.parse(entry_raw)
    public = bound.peer.qualified(entry_tree, "_profile_public_env")
    futures = [node for node in entry_tree.body if isinstance(node, ast.ImportFrom) and node.module == "__future__"]
    exec(compile(ast.Module(body=[*futures, public], type_ignores=[]), str(entry_path), "exec", dont_inherit=True), namespace)
    for cls in (PublicSourceTests, PublicSQLiteTests, PublicStaticTests):
        cls.shared, cls.namespace, cls.source_api = shared, namespace, bound.api
        cls.actor_cls, cls.synthetic_home, cls.scope, cls.clock = bound.actor_cls, bound.synthetic_home, bound.scope, bound.clock
        cls.source_sha, cls.entry_sha = bound.source_sha, bound.entry_sha
        cls.test_sha = hashlib.sha256(test_raw if test_raw is not None else Path(__file__).read_bytes()).hexdigest()
        cls.public_ast_sha, cls.entry_tree = bound.peer.ast_digest(public), entry_tree
        cls.witness_root = None if witness_root is None else Path(witness_root)
    if db_path is not None:
        # Genuine generic JobStore uses genuine stdlib time, not the SOURCE clock.
        sql_module = types.ModuleType("public_settings_generic_JobStore")
        sql_module.__file__, sql_module.__package__ = str(source_path), ""
        exec(compile(source_raw, str(source_path), "exec", dont_inherit=True), sql_module.__dict__)
        PublicSQLiteTests.sql_api, PublicSQLiteTests.db_path = sql_module, Path(db_path)
    roster = {name: cls for cls in (PublicSourceTests, PublicSQLiteTests, PublicStaticTests)
        for name in unittest.defaultTestLoader.getTestCaseNames(cls)}
    selected = sorted(roster) if cases is None else list(cases)
    return unittest.TestSuite(roster[name](name) for name in selected)


if __name__ == "__main__":
    root = Path(__file__).absolute().parents[1]
    settings_path = root / "tests/test_graph_settings_unavailable.py"
    peer_path = root / "tests/test_graph_worker_origin_session.py"
    with tempfile.TemporaryDirectory(prefix="graph-public-settings-", dir=os.environ.get("TMPDIR")) as temporary:
        own = Path(temporary)
        suite = make_suite((root / "background_jobs.py").read_bytes(), root / "background_jobs.py",
            (root / "__init__.py").read_bytes(), root / "__init__.py", settings_path.read_bytes(), settings_path,
            peer_path.read_bytes(), peer_path, witness_root=own, db_path=own / "public.db")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
