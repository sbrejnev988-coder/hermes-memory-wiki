"""Self-contained stdlib graph-intent regressions, without package/SDK import.

Owning provider, extractor dispatch, source/lease/UNKNOWN and consumer claims are
STATIC only. Component tests execute the complete genuine background_jobs module
and JobStore on ONE tiny file-backed stdlib SQLite fixture, not a provider/claim
transaction stand-in. fixture_marks is generic transactional data, NOT claims.
Run from a complete checkout: python -I -B -S tests/test_extraction_graph_intent.py
"""
from __future__ import annotations

import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest

ENTRY_SHA256 = "57385a9fd9e7d94658a49d1eb90106346aea0c3e052a4d7110f1a8f0f8f91cc9"
CLOSE_AST = "eaa1a8fb0d935f2f09372447d5f1cc662031e0ecf7c8562f3f062ac4e0ef3aa1"
RUN_ONCE_AST = "af74e0ab1e310cbcf8798840d2a9c949f6f7d605b3cf1099339a714875b9c4f8"
PROFILE, OWNER, PARTITION = "a" * 64, "b" * 64, "c" * 64
EVENT_ID = "evt_" + "d" * 32
STAMP = 4_000_000
connection_paths = []


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def qualified(tree, name):
    scope = tree
    for part in name.split("."):
        pending, matches = list(scope.body), []
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if node.name == part:
                    matches.append(node)
            else:
                pending.extend(ast.iter_child_nodes(node))
        if len(matches) != 1:
            raise AssertionError("qualified AST not unique: " + name)
        scope = matches[0]
    return scope


def ast_digest(node):
    return digest(ast.dump(node, include_attributes=False).encode("utf-8"))


def contains(node, expression):
    try:
        wanted = ast.parse(expression, mode="eval").body
    except SyntaxError:
        wanted = ast.parse(expression).body[0]
    return any(ast.dump(n, include_attributes=False) == ast.dump(wanted, include_attributes=False)
               for n in ast.walk(node))


def calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Name) and n.func.id == name)
                 or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


def connection_observer(event, args):
    # Passive primitive-only observer, not writer/SQL admission or a mock.
    if event == "sqlite3.connect":
        connection_paths.append(str(args[0]))


class IntentStaticTests(unittest.TestCase):
    def callback(self):
        return qualified(self.tree, "_run_job.persist_if_current")

    def owning_with(self):
        matches = [n for n in ast.walk(self.callback()) if isinstance(n, ast.With)
                   and any(isinstance(i.context_expr, ast.Call)
                           and isinstance(i.context_expr.func, ast.Attribute)
                           and i.context_expr.func.attr == "_claim_transaction" for i in n.items)]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_static_intent_in_owning_transaction_before_postcommit(self):
        owner = self.owning_with()
        add, after = calls(self.callback(), "_add_claim_tx"), calls(self.callback(), "_after_claim_commit")
        intent = calls(owner, "enqueue_claim")
        witness = {"schema": "extraction-graph-intent-order/v1", "level": "STATIC_ONLY",
                   "source_sha256": self.source_sha, "test_sha256": self.test_sha,
                   "owning_with_lines": [owner.lineno, owner.end_lineno],
                   "claim_write_lines": [n.lineno for n in add],
                   "intent_call_lines": [n.lineno for n in intent],
                   "postcommit_lines": [n.lineno for n in after],
                   "intent_inside_owner": len(intent) == 1,
                   "provider_claim_SQL_executed": False}
        witness["outcome_sha256"] = digest(json.dumps(witness, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        if self.witness_root is not None:
            self.witness_root.mkdir(parents=True, exist_ok=True)
            with (self.witness_root / "intent-witness.json").open("xb") as stream:
                stream.write((json.dumps(witness, sort_keys=True) + "\n").encode("utf-8"))
                stream.flush()
        self.assertEqual(len(intent), 1, "graph_intent_absent_in_owning_TX_before_postcommit")
        self.assertEqual(len(add), 1)
        self.assertEqual(len(after), 1)
        self.assertLess(add[0].lineno, intent[0].lineno)
        self.assertLess(intent[0].lineno, owner.end_lineno)
        self.assertLess(owner.end_lineno, after[0].lineno)
        self.assertTrue(contains(owner, "worker._claim_transaction(conn, _event_job=event_obligation)"))

    def test_static_exact_owner_stage_and_original_obligation(self):
        node = qualified(self.tree, "_run_job.persist_if_current.enqueue_claim")
        for expression in (
            "provider._require_claim_writer(conn, transaction=True)",
            "provider is not worker", "conn is not provider._conn", "conn is not provider._owned_conn",
            "conn is not provider._claim_tx_connection", "provider._claim_tx_thread != threading.get_ident()",
            "provider._claim_tx_event_job_stage is not claim_stage", "claim_stage[0] is not conn",
            "claim_stage[1] != provider._claim_tx_thread", "claim_stage[3] is not True",
            "any(item is event_obligation for item in claim_stage[2])",
            "provider.bot_id != event_obligation[1]", "provider.home is not event_obligation[2]",
            "provider.db_path is not event_obligation[3]", "dict(event_obligation[0])",
            'JobStore(provider.db_path, original_job["profile_key"], original_job["owner_key"])',
        ):
            self.assertTrue(contains(node, expression), expression)
        self.assertTrue(contains(self.owning_with(), "claim_stage = worker._claim_tx_event_job_stage"))
        self.assertEqual(len(calls(node, "_enqueue_in_transaction")), 1)
        for name in ("_connect", "enqueue", "commit", "rollback", "install_schema", "_event_job_obligation"):
            self.assertEqual(calls(node, name), [], name)
        shared = qualified(self.tree, "JobStore._enqueue_in_transaction")
        for name in ("_connect", "commit", "rollback", "close", "install_schema"):
            self.assertEqual(calls(shared, name), [], name)
        self.assertFalse(any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                             and n.value.strip().upper().startswith(("BEGIN", "DELETE")) for n in ast.walk(shared)))

    def test_static_first_four_return_slots_and_no_aggregate_rescheduling(self):
        callback, owner = self.callback(), self.owning_with()
        self.assertTrue(contains(owner, "returned_slots < 4"))
        self.assertTrue(contains(owner, "claim_id not in preexisting"))
        self.assertTrue(contains(owner, "claim_id not in graph_intents"))
        increments = [n for n in ast.walk(callback) if isinstance(n, ast.AugAssign)
                      and isinstance(n.target, ast.Name) and n.target.id == "returned_slots"]
        self.assertEqual(len(increments), 1)
        increment = increments[0]
        self.assertIsInstance(increment.op, ast.Add)
        self.assertEqual(increment.value.value, 1)
        truthy_slot = [n for n in ast.walk(callback) if isinstance(n, ast.If)
                       and isinstance(n.test, ast.Name) and n.test.id == "claim_id" and increment in n.body]
        self.assertEqual(len(truthy_slot), 1)  # preexisting/invalid/duplicates ALSO consume slots
        self.assertLess(owner.end_lineno, increment.lineno)
        self.assertLess(increment.lineno, calls(callback, "_after_claim_commit")[0].lineno)
        self.assertTrue(contains(callback, "graph_intents.add(claim_id)"))
        run = qualified(self.tree, "_run_job")
        self.assertEqual(len(calls(run, "enqueue_claim")), 1)
        self.assertFalse(any(isinstance(n, ast.Constant) and n.value == "persisted_ids" for n in ast.walk(run)))
        for n in ast.walk(run):
            if isinstance(n, ast.Try):
                for final in n.finalbody:
                    self.assertEqual(calls(final, "enqueue_claim"), [])
                    self.assertEqual(calls(final, "_enqueue_in_transaction"), [])

    def test_static_primary_postcommit_and_unknown_propagation(self):
        callback = self.callback()
        guarded = [n for n in callback.body if isinstance(n, ast.Try)
                   and any(isinstance(h.type, ast.Name) and h.type.id == "BaseException" for h in n.handlers)]
        self.assertEqual(len(guarded), 1)
        node = guarded[0]
        self.assertEqual(len(calls(node, "_after_claim_commit")), 1)
        self.assertTrue(any(contains(n, "worker._after_claim_commit(claim_id, prepared[\"topic\"], prepared[\"claim\"])")
                            for n in node.body))
        handler = next(h for h in node.handlers if isinstance(h.type, ast.Name) and h.type.id == "BaseException")
        self.assertTrue(contains(handler, "persistence_primary = exc"))
        self.assertTrue(any(isinstance(n, ast.Raise) and n.exc is None for n in handler.body))
        self.assertTrue(contains(callback.body[1], "raise persistence_primary"))
        run = qualified(self.tree, "_run_job")
        extractor = [n for n in ast.walk(run) if isinstance(n, ast.Try)
                     and any(calls(b, "extract_session_claims") for b in n.body)]
        # The narrow extractor try must rethrow the retained original before any secondary.
        narrow = min(extractor, key=lambda n: n.end_lineno - n.lineno)
        self.assertTrue(contains(narrow.handlers[0], "raise persistence_primary"))
        self.assertEqual(ast_digest(qualified(self.tree, "_close_job_worker")), CLOSE_AST)
        self.assertEqual(ast_digest(qualified(self.tree, "run_once")), RUN_ONCE_AST)

    def test_static_off_preexisting_invalid_owner_selection(self):
        owner, callback = self.owning_with(), self.callback()
        selected = [n for n in owner.body if isinstance(n, ast.If) and calls(n, "enqueue_claim")]
        self.assertEqual(len(selected), 1)
        for expression in ("graph_allowed", "graph_available", "isinstance(claim_id, str)",
                           "_CLAIM_ID.fullmatch(claim_id)", "claim_id not in preexisting"):
            self.assertTrue(contains(selected[0].test, expression), expression)
        self.assertTrue(contains(callback, "worker.relevant_graph_extraction_settings()"))
        self.assertTrue(contains(callback, "not isinstance(prepared, dict)"))
        self.assertTrue(contains(callback, 'kwargs.get("visibility_scope") != "chat"'))
        self.assertTrue(contains(callback, 'source_label not in {"extractor:llm", "extractor:heuristic"}'))
        helper = qualified(self.tree, "_run_job.persist_if_current.enqueue_claim")
        self.assertTrue(contains(helper, 'str(row["origin_bot_id"]) != str(provider.bot_id)'))
        self.assertTrue(contains(helper, '_digest(str(row["origin_bot_id"]), str(row["origin_chat_hash"]), claim_id)'))
        self.assertTrue(contains(helper, '{"claim_id": claim_id}'))

    def test_static_native_guards_and_nonfatal_derivatives_unchanged(self):
        self.assertEqual(self.entry_sha, ENTRY_SHA256)
        tx = qualified(self.entry_tree, "MemoryWikiProvider._claim_transaction")
        for expression in ("c.commit()", "self._claim_tx_event_job_stage is not event_job_stage",
                           "self._assert_event_job_leases(c, event_job_stage[2], check_callbacks=False, terminal_stage=event_job_stage)",
                           "self._rollback_claim_transaction(c, primary, commit_attempted=commit_attempted)"):
            self.assertTrue(contains(tx, expression), expression)
        after = qualified(self.entry_tree, "MemoryWikiProvider._after_claim_commit")
        self.assertTrue(contains(after, "return failures"))
        self.assertTrue(contains(after, 'failures.append({"operation": name, "error": _safe_exception_label(exc)})'))
        callback = self.callback()
        self.assertFalse(any(isinstance(n, ast.Assign) and calls(n.value, "_after_claim_commit") for n in ast.walk(callback)))
        # No new interpretation of normally collected derivative failures as fatal.
        self.assertEqual(len(calls(callback, "_after_claim_commit")), 1)


class JobStoreSQLiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved_env = {}
        for name, value in {"MEMORY_WIKI_BACKGROUND_HISTORY_DAYS": "30",
                            "MEMORY_WIKI_BACKGROUND_LEASE_SECONDS": "120",
                            "MEMORY_WIKI_BACKGROUND_DAILY_JOBS": "500",
                            "MEMORY_WIKI_BACKGROUND_DAILY_REQUESTS": "100",
                            "MEMORY_WIKI_BACKGROUND_MAX_ATTEMPTS": "5"}.items():
            cls.saved_env[name] = os.environ.get(name)
            os.environ[name] = value
        sys.addaudithook(connection_observer)
        with closing(sqlite3.connect(str(cls.db_path))) as conn:
            conn.execute("PRAGMA page_size=1024")
            cls.api.install_schema(conn)
            conn.execute("CREATE TABLE fixture_marks(id TEXT PRIMARY KEY)")
            conn.commit()
        cls.fixture_handles_opened = cls.fixture_handles_closed = 0

    @classmethod
    def tearDownClass(cls):
        for name, value in cls.saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if cls.fixture_handles_opened != cls.fixture_handles_closed:
            raise AssertionError("fixture_handle_not_closed")

    def setUp(self):
        self.conn = sqlite3.connect(str(self.db_path))
        type(self).fixture_handles_opened += 1
        self.addCleanup(self.close_fixture)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("DELETE FROM memory_jobs")
        self.conn.execute("DELETE FROM memory_job_budgets")
        self.conn.execute("DELETE FROM fixture_marks")
        self.conn.commit()
        self.store = self.api.JobStore(self.db_path, PROFILE, OWNER)

    def close_fixture(self):
        self.conn.close()
        type(self).fixture_handles_closed += 1

    def row(self, identifier):
        with closing(sqlite3.connect(str(self.db_path))) as reader:
            reader.row_factory = sqlite3.Row
            found = reader.execute("SELECT * FROM memory_jobs WHERE job_id=?", (identifier,)).fetchone()
            return None if found is None else dict(found)

    def intent(self, identifier="c_tiny"):
        payload = {"claim_id": identifier}
        return self.store._enqueue_in_transaction(self.conn, "enrich_claim_graph", payload, PARTITION,
            canonical=self.api.validate_payload("enrich_claim_graph", payload), stamp=STAMP, due=STAMP)

    def test_sql_same_connection_commit_and_id_only_readback(self):
        trace = []
        self.conn.set_trace_callback(trace.append)
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("INSERT INTO fixture_marks VALUES('generic')")
        before = len(connection_paths)
        identifier = self.intent()
        self.assertEqual(len(connection_paths), before)
        self.assertTrue(self.conn.in_transaction)
        self.assertFalse(any(s.strip().upper().startswith(("COMMIT", "END", "ROLLBACK")) for s in trace))
        self.assertIsNone(self.row(identifier))  # independent reader cannot see tentative job
        self.conn.commit()
        row = self.row(identifier)
        self.assertEqual(json.loads(row["payload_json"]), {"claim_id": "c_tiny"})
        self.assertEqual((row["profile_key"], row["owner_key"], row["partition_key"]), (PROFILE, OWNER, PARTITION))
        self.assertEqual((row["owner_chat_hash"], row["owner_session_hash"], row["generation"]), ("", "", 1))

    def test_sql_owning_rollback_removes_tentative_intent(self):
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("INSERT INTO fixture_marks VALUES('tentative')")
        identifier = self.intent()
        self.conn.rollback()
        self.assertIsNone(self.row(identifier))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fixture_marks").fetchone()[0], 0)

    def test_sql_later_failed_transaction_keeps_earlier_intent(self):
        self.conn.execute("BEGIN IMMEDIATE")
        earlier = self.intent("c_earlier")
        self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")
        later = self.intent("c_later")
        primary = RuntimeError("generic_later_fault")
        try:
            raise primary
        except RuntimeError as actual:
            self.conn.rollback()
            self.assertIs(actual, primary)
        self.assertEqual(json.loads(self.row(earlier)["payload_json"]), {"claim_id": "c_earlier"})
        self.assertIsNone(self.row(later))

    def test_sql_postcommit_fault_and_cancellation_keep_committed_intent(self):
        self.conn.execute("BEGIN IMMEDIATE")
        identifier = self.intent()
        self.conn.commit()
        for primary in (RuntimeError("generic_postcommit"), KeyboardInterrupt("generic_cancel")):
            try:
                raise primary
            except BaseException as actual:
                self.assertIs(actual, primary)
            self.assertEqual(self.row(identifier)["generation"], 1)
        self.assertFalse(self.conn.in_transaction)

    def test_sql_failed_job_write_rolls_back_generic_transaction(self):
        self.conn.execute("CREATE TEMP TRIGGER fail_intent BEFORE INSERT ON memory_jobs BEGIN SELECT RAISE(ABORT,'fixture_fault'); END")
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("INSERT INTO fixture_marks VALUES('must_rollback')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.intent()
        self.conn.rollback()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM memory_jobs").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fixture_marks").fetchone()[0], 0)

    def test_sql_public_pending_coalesce_preserves_due_and_identity(self):
        identifier = self.store.enqueue("enrich_claim_graph", {"claim_id": "c_tiny"}, PARTITION,
                                        available_at=STAMP + 50, now=STAMP)
        again = self.store.enqueue("enrich_claim_graph", {"claim_id": "c_tiny"}, PARTITION,
                                  available_at=STAMP + 80, now=STAMP + 1)
        self.assertEqual(again, identifier)
        row = self.row(identifier)
        self.assertEqual((row["generation"], row["available_at"], row["status"]), (2, STAMP + 50, "pending"))
        self.assertEqual(row["payload_json"], '{"claim_id":"c_tiny"}')

    def test_sql_public_leased_coalesce_keeps_original_lease(self):
        identifier = self.store.enqueue("enrich_claim_graph", {"claim_id": "c_tiny"}, PARTITION, now=STAMP)
        leased = self.store.lease("e" * 32, now=STAMP)
        self.assertEqual(leased["job_id"], identifier)
        again = self.store.enqueue("enrich_claim_graph", {"claim_id": "c_tiny"}, PARTITION, now=STAMP + 1)
        self.assertEqual(again, identifier)
        row = self.row(identifier)
        self.assertEqual(row["generation"], 2)
        for key in ("status", "lease_owner", "lease_generation", "lease_expires_at", "attempts", "available_at"):
            self.assertEqual(row[key], leased[key], key)

    def test_sql_public_extraction_watermark_never_regresses(self):
        kwargs = {"owner_chat_hash": "1" * 32, "owner_session_hash": "2" * 32, "now": STAMP}
        identifier = self.store.enqueue("extract_session_events", {"event_id": EVENT_ID, "high_watermark": 9}, PARTITION, **kwargs)
        again = self.store.enqueue("extract_session_events", {"event_id": "evt_" + "3" * 32, "high_watermark": 4}, PARTITION, **kwargs)
        self.assertEqual(identifier, again)
        self.assertEqual(json.loads(self.row(identifier)["payload_json"]), {"event_id": EVENT_ID, "high_watermark": 9})
        self.store.enqueue("extract_session_events", {"event_id": EVENT_ID, "high_watermark": 12}, PARTITION, **kwargs)
        self.assertEqual(json.loads(self.row(identifier)["payload_json"])["high_watermark"], 12)

    def test_sql_public_invalid_inputs_refuse_before_connect(self):
        inputs = [("enrich_claim_graph", {"claim_id": "rq_review"}, PARTITION, {}),
                  ("enrich_claim_graph", {"claim_id": "c_ok", "text": "forbidden"}, PARTITION, {}),
                  ("enrich_claim_graph", {"claim_id": "c_ok"}, "invalid", {}),
                  ("enrich_claim_graph", {"claim_id": "c_ok"}, PARTITION, {"owner_chat_hash": "1" * 32}),
                  ("extract_session_events", {"event_id": EVENT_ID, "high_watermark": True}, PARTITION, {}),
                  ("extract_session_events", {"event_id": EVENT_ID, "high_watermark": 1}, PARTITION, {"owner_session_hash": "bad"})]
        for kind, payload, partition, kwargs in inputs:
            before = len(connection_paths)
            with self.assertRaises(ValueError):
                self.store.enqueue(kind, payload, partition, now=STAMP, **kwargs)
            self.assertEqual(len(connection_paths), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM memory_jobs").fetchone()[0], 0)

    def test_sql_history_pruning_only_standalone_not_participation(self):
        old = self.store.enqueue("enrich_claim_graph", {"claim_id": "c_old"}, PARTITION, now=1)
        self.conn.execute("UPDATE memory_jobs SET status='done',updated_at=1 WHERE job_id=?", (old,))
        self.conn.execute("INSERT INTO memory_job_budgets VALUES(?,0,1,1)", (PROFILE,))
        self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")
        self.intent()
        self.conn.commit()
        self.assertIsNotNone(self.row(old))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM memory_job_budgets").fetchone()[0], 1)
        self.store.enqueue("enrich_claim_graph", {"claim_id": "c_public"}, PARTITION, now=STAMP)
        self.assertIsNone(self.row(old))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM memory_job_budgets").fetchone()[0], 0)


def make_suite(source_raw, source_path, entry_raw, *, test_raw=None, witness_root=None, db_path=None, cases=None):
    tree, entry_tree = ast.parse(source_raw), ast.parse(entry_raw)
    cls = IntentStaticTests
    cls.tree, cls.entry_tree = tree, entry_tree
    cls.source_sha, cls.entry_sha = digest(source_raw), digest(entry_raw)
    cls.test_sha = digest(Path(__file__).read_bytes() if test_raw is None else test_raw)
    cls.witness_root = None if witness_root is None else Path(witness_root)
    roster = {name: (test_cls, name) for test_cls in (IntentStaticTests, JobStoreSQLiteTests)
              for name in unittest.defaultTestLoader.getTestCaseNames(test_cls)}
    selected = sorted(roster) if cases is None else list(cases)
    if any(name.startswith("test_sql_") for name in selected):
        if db_path is None:
            raise ValueError("isolated_component_requires_fixture_owned_path")
        module = types.ModuleType("genuine_background_jobs_component")
        module.__file__, module.__package__ = str(source_path), ""
        exec(compile(source_raw, str(source_path), "exec", dont_inherit=True), module.__dict__)
        JobStoreSQLiteTests.api, JobStoreSQLiteTests.db_path = module, Path(db_path)
    return unittest.TestSuite(roster[name][0](name) for name in selected)


if __name__ == "__main__":
    root = Path(__file__).absolute().parents[1]
    with tempfile.TemporaryDirectory(prefix="graph-intent-", dir=os.environ.get("TMPDIR")) as temporary:
        suite = make_suite((root / "background_jobs.py").read_bytes(), root / "background_jobs.py",
                           (root / "__init__.py").read_bytes(), db_path=Path(temporary) / "jobs.db")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
