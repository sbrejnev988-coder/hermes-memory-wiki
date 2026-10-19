"""Genuine-native offline review writer lifetime regressions (stdlib unittest).

Fresh per-case plugin namespace/home before import, real SDK/registry/trust and
SQLite. No Connection/execute/gate replacements. Exact-code profile observers
pause only after the production review INSERT has actually returned. UNKNOWN
is asserted and recorded before fixture-owned physical close, never reset.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[1]
CANDIDATE = "Blue amber ribbons mark the lunar violet shelves."
TURN = "Remember: " + CANDIDATE
CLAIM = "Пользователь предпочитает овальные керамические этикетки для Лазурного маяка."
QUERY = "керамические этикетки"
CASE_NAMES = (
    "test_01_sequential_natural_queue_and_seed_recall",
    "test_02_natural_queue_writer_public_reader_handoff",
    "test_03_direct_firewall_queue_preserves_metadata_and_redaction",
    "test_04_queue_known_rollback_preserves_exact_primary",
    "test_05_joined_claim_queue_outer_rollback_is_atomic",
    "test_06_joined_firewall_queue_outer_commit_keeps_change",
    "test_07_change_insert_denial_rolls_back_review",
    "test_08_foreign_thread_begin_remains_unknown_after_owner_rollback",
    "test_09_queue_rollback_denied_retains_exact_primary_and_owner",
)


def unwrapped(function):
    while hasattr(function, "__wrapped__"):
        function = function.__wrapped__
    return function


@contextmanager
def profile_scope(callback):
    prior = sys.getprofile()
    if prior is not None:
        raise RuntimeError("existing_profile_not_replaced")
    sys.setprofile(callback)
    try:
        yield
    finally:
        # CPython disables a throwing profile. Cleanup assertions below use
        # actual SQL/state, never absence of later profile events as evidence.
        sys.setprofile(prior)


class NativeReviewQueueOwner(unittest.TestCase):
    def record(self, event, **metadata):
        target = os.environ.get("MW_EP_OBSERVATIONS")
        if target:
            with Path(target).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"case": self.id(), "event": event, **metadata},
                                        ensure_ascii=False, separators=(",", ":")) + "\n")

    def state(self):
        p, c = self.p, self.conn
        return {"lifecycle": p._lifecycle_state, "in_transaction": c.in_transaction,
                "owned_shared": c is p._conn is p._owned_conn,
                "owner_exact": p._claim_tx_connection is c,
                "owner_same_thread": p._claim_tx_thread == threading.get_ident(),
                "owner_retired": p._claim_tx_connection is None and p._claim_tx_thread is None,
                "quarantined": p._transaction_quarantine is not None,
                "primary_type": type(p._transaction_primary).__name__ if p._transaction_primary is not None else None,
                "cleanup_codes": list(p._transaction_cleanup_notes)}

    @contextmanager
    def scope(self):
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        token = set_hermes_home_override(self.home)
        try:
            with self.m._native_profile_scope(self.home), self.m._profile_qdrant_scope(self.home):
                yield
        finally:
            reset_hermes_home_override(token)

    def setUp(self):
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        from agent.memory_provider import MemoryProvider
        import tools.registry as registry
        import hermes_trust_core as trust
        base = Path(os.environ.get("MW_EP_TEST_ROOT") or os.environ["TMPDIR"])
        label = self._testMethodName
        self.root = base / ("review-owner-" + label)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=False)
        self.original_environment, self.original_sys_path = dict(os.environ), list(sys.path)
        os.environ.update({
            "HERMES_HOME": str(self.home), "HERMES_SECURITY_STRICT": "1",
            "MEMORY_WIKI_STRICT_RECALL": "1", "MEMORY_WIKI_SEMANTIC": "0",
            "MEMORY_WIKI_EMBED_PROVIDER": "stub", "MEMORY_WIKI_EMBED_MODEL": "hash-ngram-8",
            "MEMORY_WIKI_EMBED_DIMENSIONS": "8", "MEMORY_WIKI_VECTOR_SIZE": "8",
            "MEMORY_WIKI_RERANK_ENABLED": "0", "MEMORY_WIKI_LLM_PACK": "0",
            "MEMORY_WIKI_GRAPH_AUTO_EXTRACT": "0", "MEMORY_WIKI_GRAPH_EXTRACT_ENABLED": "0",
            "MEMORY_WIKI_EPISODIC_ENABLED": "0", "MEMORY_WIKI_EPISODIC_PREFETCH": "0",
            "MEMORY_WIKI_EVENT_LEDGER_ENABLED": "0", "MEMORY_WIKI_OBSERVATIONS_ENABLED": "0",
            "MEMORY_WIKI_BACKGROUND_JOBS_ENABLED": "0", "MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK": "0",
            "MEMORY_WIKI_DOCUMENT_PREFETCH": "0", "MEMORY_WIKI_CODE_GRAPH_PREFETCH": "0",
            "MEMORY_WIKI_ONLINE_METRICS_ENABLED": "1",
        })
        token = set_hermes_home_override(self.home)
        self.addCleanup(reset_hermes_home_override, token)
        self.addCleanup(self.restore_environment)
        import __main__
        sentinel = object()
        previous = getattr(__main__, "_memory_wiki_instance", sentinel)
        def restore_singleton():
            if getattr(__main__, "_memory_wiki_instance", sentinel) is getattr(self, "p", None):
                if previous is sentinel:
                    del __main__._memory_wiki_instance
                else:
                    __main__._memory_wiki_instance = previous
        self.addCleanup(restore_singleton)
        self.namespace = "_native_review_owner_" + label
        spec = importlib.util.spec_from_file_location(
            self.namespace, SOURCE / "__init__.py", submodule_search_locations=[str(SOURCE)])
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        self.m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.m
        spec.loader.exec_module(self.m)
        self.assertEqual(self.m._IMPORT_HERMES_HOME, self.home.resolve())
        self.assertIs(self.m.MemoryProvider, MemoryProvider)
        self.assertEqual(self.m.MemoryWikiProvider.__bases__, (MemoryProvider,))
        self.assertIs(self.m.tool_error, registry.tool_error)
        self.assertIs(self.m.tool_result, registry.tool_result)
        self.assertIs(self.m._sanitize_recalled, trust.sanitize_recalled)
        self.assertTrue(self.m._INJECTION_GUARD_AVAILABLE)
        self.assertNotIn("agent.memory_manager", sys.modules)
        self.p = self.m.MemoryWikiProvider()
        self.p.initialize("synthetic-review-chat", hermes_home=str(self.home),
                          agent_context="primary", bot_id="synthetic-review-bot",
                          project_id="synthetic-review-project", visibility_scope="chat")
        self.conn = self.p._conn
        self.addCleanup(self.close_owned_fixture)
        self.assertIs(self.conn, self.p._owned_conn)
        self.assertIsInstance(self.conn, sqlite3.Connection)
        self.assertFalse(self.m.SEMANTIC_ENABLED)
        self.assertIsNone(self.p._background_worker)
        with self.scope():
            identity = self.p._runtime_identity()
            self.assertTrue(identity["conn_path_matches"])
            self.assertTrue(identity["profile_ready"], identity)
            self.assertEqual(Path(identity["request_home"]), self.home.resolve())
        self.assert_ready()
        self.record("initialized", namespace=self.namespace, module_file=self.m.__file__,
                    import_home=str(self.m._IMPORT_HERMES_HOME), state=self.state())

    def restore_environment(self):
        os.environ.clear()
        os.environ.update(self.original_environment)
        sys.path[:] = self.original_sys_path

    def close_owned_fixture(self):
        self.record("before_shutdown", state=self.state())
        self.assertEqual([t.name for t in threading.enumerate() if t is not threading.main_thread()], [])
        self.assertEqual(getattr(self.p, "_graph_reader_connections", {}), {})
        self.assertEqual(getattr(self.p, "_graph_writer_connections", {}), {})
        if self.p._transaction_quarantine is None:
            self.p.shutdown()
            self.assertIsNone(self.p._conn)
            self.assertIsNone(self.p._owned_conn)
            self.assertEqual(self.p._lifecycle_state, "idle")
            self.record("shutdown", outcome="natural_closed", owner_retired=True)
        else:
            retained = (self.p._transaction_quarantine, self.p._transaction_primary,
                        self.p._claim_tx_connection, self.p._claim_tx_thread)
            self.assertIs(retained[0], self.conn)
            self.assertIs(self.p._conn, self.conn)
            self.assertIs(self.p._owned_conn, self.conn)
            with self.assertRaisesRegex(RuntimeError, "provider_transaction_cleanup_required"):
                self.p.shutdown()
            self.assertIs(self.p._transaction_quarantine, retained[0])
            self.assertIs(self.p._transaction_primary, retained[1])
            self.assertIs(self.p._claim_tx_connection, retained[2])
            self.assertEqual(self.p._claim_tx_thread, retained[3])
            self.record("shutdown", outcome="refused_retained_UNKNOWN", state=self.state())
            # Explicit fixture safety close AFTER snapshots/assertions. Not a
            # production rollback/reconnect; retained markers are never cleared.
            self.conn.set_authorizer(None)
            sqlite3.Connection.close(self.conn)
            self.assertIs(self.p._transaction_quarantine, retained[0])
            self.assertIs(self.p._transaction_primary, retained[1])
            self.record("fixture_safety_close", outcome="test_owned_only_not_recovery")
        with self.assertRaises(sqlite3.ProgrammingError):
            self.conn.execute("SELECT 1")
        self.assertIsNone(self.p._background_worker)

    def assert_ready(self):
        self.assertEqual(self.p._lifecycle_state, "ready")
        self.assertFalse(self.p._degraded)
        self.assertIsNone(self.p._transaction_quarantine)
        self.assertIsNone(self.p._transaction_primary)
        self.assertIs(self.p._conn, self.conn)
        self.assertIs(self.p._owned_conn, self.conn)
        self.assertFalse(self.conn.in_transaction)
        self.assertIsNone(self.p._claim_tx_connection)
        self.assertIsNone(self.p._claim_tx_thread)

    def natural_input(self):
        # Verify the REAL extract/redact/gate before relying on the proposal.
        m = self.m
        candidate = m.extract_memory_directive(m.scrub_memory_artifacts(TURN))
        self.assertEqual(candidate, CANDIDATE)
        self.assertEqual(m.normalize_claim(m.redact_secrets(candidate)), CANDIDATE)
        self.assertFalse(m.secret_scan(candidate)["raw_secret"])
        self.assertFalse(m.is_ephemeral_fragment(candidate))
        topic, source = self.p._infer_topic(candidate), "turn:user:" + self.p.session_id
        gate = m.memory_gate_decision(candidate, topic, source)
        self.assertEqual(gate["action"], "queue", gate)
        self.assertEqual(gate["reason"], "source policy requires review", gate)
        self.assertTrue(gate["policy"]["candidate_only"])
        self.assertEqual(gate["policy"]["source_type"], "conversation")
        return candidate, topic, source, gate

    def natural_queue(self):
        with self.scope():
            self.p.sync_turn(TURN, "", session_id=self.p.session_id)

    def firewall_queue(self, **overrides):
        args = dict(claim=CANDIDATE, topic="ribbons", evidence=CANDIDATE,
                    source="synthetic:manual", mode="queue")
        args.update(overrides)
        with self.scope():
            return self.p._write_firewall(args)

    def queue_rows(self):
        return self.conn.execute("SELECT * FROM review_queue").fetchall()

    def assert_queue(self, *, source, evidence=CANDIDATE, confidence=None, salience=None):
        rows = self.queue_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row["id"].startswith("rq_"))
        self.assertEqual(row["candidate"], CANDIDATE)
        self.assertEqual(row["source"], source)
        self.assertEqual(row["evidence"], evidence)
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["suggested_claim"], CANDIDATE)
        self.assertEqual(row["visibility_scope"], "chat")
        self.assertEqual(row["origin_bot_id"], self.p.bot_id)
        self.assertEqual(row["origin_chat_hash"], self.p._chat_hash(self.p.session_id))
        self.assertEqual(row["origin_session_id"], "")
        self.assertEqual(row["project_id"], "")
        self.assertGreater(row["created_at"], 0)
        self.assertEqual(row["updated_at"], row["created_at"])
        if confidence is not None:
            self.assertEqual(row["confidence"], confidence)
        if salience is not None:
            self.assertEqual(row["salience"], salience)
        changes = self.conn.execute(
            "SELECT action,claim_id,detail FROM memory_changes WHERE action='review_enqueue'").fetchall()
        self.assertEqual([tuple(r) for r in changes], [("review_enqueue", row["id"], row["reason"])])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM claims WHERE claim=?", (CANDIDATE,)).fetchone()[0], 0)
        return row["id"]

    def seed(self):
        with self.scope():
            result = json.loads(self.p.handle_tool_call("memory_wiki_add_claim", {
                "claim": CLAIM, "topic": "preferences", "evidence": CLAIM,
                "confidence": .8, "salience": .75}))
        self.assertEqual(result.get("state"), "stored", result)
        self.assertIs(result["immediately_recallable"], True)
        self.cid = result["id"]
        self.seed_image = tuple(self.conn.execute(
            "SELECT claim,source,visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash,project_id "
            "FROM claims WHERE id=?", (self.cid,)).fetchone())
        self.assert_ready()
        return self.accounting()

    def accounting(self):
        c, cid = self.conn, self.cid
        return {"claim": tuple(c.execute("SELECT access_count,recall_count,last_recalled FROM claims WHERE id=?", (cid,)).fetchone()),
                "events": c.execute("SELECT count(*) FROM recall_events WHERE claim_id=?", (cid,)).fetchone()[0],
                "feedback": c.execute("SELECT count(*) FROM recall_feedback WHERE claim_id=?", (cid,)).fetchone()[0],
                "metrics": c.execute("SELECT coalesce(sum(sample_count),0) FROM memory_online_metrics").fetchone()[0]}

    def recall(self, entry_seen=None):
        deliveries = []
        public_wrapper = self.p.handle_tool_call.__func__.__code__
        terminal = self.m._TerminalDelivery.commit.__code__
        def observe(frame, event, arg):
            if event != "call":
                return
            if (frame.f_code is public_wrapper and frame.f_locals.get("self") is self.p
                    and frame.f_locals.get("tool_name") == "memory_wiki_recall" and entry_seen is not None):
                # Actual outer bounded_scope_dispatch has tool_name, not the
                # inner scoped wrapper's __name; observe before identity SQL.
                entry_seen.set()
            if frame.f_code is terminal and frame.f_locals["self"].provider is self.p:
                deliveries.append(frame.f_locals["self"])
        with self.scope(), profile_scope(observe):
            result = json.loads(self.p.handle_tool_call("memory_wiki_recall", {
                "query": QUERY, "mode": "fast", "limit": 2, "max_chars": 1000}))
        return result, deliveries

    def assert_recalled(self, before, answer):
        result, deliveries = answer
        self.assertNotIn("error", result)
        self.assertNotEqual(result.get("disclosure_status"), "withheld")
        self.assertEqual(result["evidence_count"], 1)
        self.assertEqual([(r["kind"], r["id"], r["content"]) for r in result["items"]],
                         [("claim", self.cid, CLAIM)])
        tracking = result["recall_tracking"]
        self.assertEqual(tracking["status"], "ok")
        self.assertEqual(len(tracking["events"]), 1)
        event_id = tracking["events"][0]["recall_event_id"]
        self.assertEqual(result["items"][0]["recall_event_id"], event_id)
        self.assertEqual(tracking["answer_linkage"]["claim_ids"], [self.cid])
        self.assertEqual(tracking["answer_linkage"]["recall_event_ids"], [event_id])
        after = self.accounting()
        self.assertEqual(after["claim"][:2], (before["claim"][0] + 1, before["claim"][1] + 1))
        for key in ("events", "feedback", "metrics"):
            self.assertEqual(after[key], before[key] + 1)
        self.assertEqual(tuple(self.conn.execute("SELECT claim_id,used,outcome FROM recall_events WHERE id=?", (event_id,)).fetchone()),
                         (self.cid, -1, "pending"))
        self.assertEqual(tuple(self.conn.execute("SELECT claim_id,used,helpful,outcome FROM recall_feedback WHERE recall_event_id=?", (event_id,)).fetchone()),
                         (self.cid, 0, 0.0, "neutral"))
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].phase, "committed")
        self.assertIs(deliveries[0].measurement["commit_returned"], True)
        self.assertIs(deliveries[0].measurement["native_idle"], True)
        self.assertEqual(tuple(self.conn.execute(
            "SELECT claim,source,visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash,project_id "
            "FROM claims WHERE id=?", (self.cid,)).fetchone()), self.seed_image)
        self.assertEqual(result["retrieval_receipt"]["final"]["emitted_claim_count"], 1)
        self.assertTrue(result["retrieval_receipt"]["searches"])
        self.assertTrue(all(r["requested_mode"] == "fts" for r in result["retrieval_receipt"]["searches"]))
        self.assertIsNone(self.m._current_delivery(self.p))
        self.assert_ready()
        self.record("healthy_seed_recall", terminal_calls=1, accounting_once=True, state=self.state())

    @contextmanager
    def review_insert(self, after):
        graph = sys.modules[self.namespace + ".code_knowledge_graph"]
        execute = graph._GraphCommitConnection.execute.__code__
        enqueue = unwrapped(self.p._enqueue_review).__code__
        snapshots = {"before": [], "after": []}
        def observe(frame, event, arg):
            if (frame.f_code is not execute or frame.f_locals.get("self") is not self.conn
                    or frame.f_back is None or frame.f_back.f_code is not enqueue
                    or frame.f_back.f_locals.get("self") is not self.p):
                return
            args = frame.f_locals.get("args", ())
            if not args or not str(args[0]).lstrip().startswith("INSERT OR IGNORE INTO review_queue("):
                return
            if event == "call":
                snapshots["before"].append(self.state())
            elif event == "return" and isinstance(arg, sqlite3.Cursor) and arg.connection is self.conn:
                snapshots["after"].append(self.state())
                self.record("actual_review_insert_return", before=snapshots["before"][-1], after=snapshots["after"][-1])
                after()
        with profile_scope(observe):
            yield snapshots

    def test_01_sequential_natural_queue_and_seed_recall(self):
        self.assertIsNone(sys.getprofile())
        self.assertIsNone(sys.gettrace())
        _, _, source, gate = self.natural_input()
        before = self.seed()
        self.natural_queue()
        self.assert_queue(source=source, confidence=.97, salience=1.0)
        self.assertEqual(self.queue_rows()[0]["reason"], gate["reason"])
        self.assert_ready()
        self.assert_recalled(before, self.recall())

    def test_02_natural_queue_writer_public_reader_handoff(self):
        from agent.memory_provider import spawn_context_thread
        self.natural_input()
        before = self.seed()
        inserted, release, entry_seen, reader_done = [threading.Event() for _ in range(4)]
        errors, answers, observations = [], [], []
        def pause():
            inserted.set()
            if not release.wait(15):
                raise RuntimeError("review_writer_release_timeout")
        def write():
            try:
                with self.scope(), self.review_insert(pause) as snapshots:
                    observations.append(snapshots)
                    self.natural_queue()
            except BaseException as error:
                errors.append(error)
                inserted.set()
        def read():
            try:
                answers.append(self.recall(entry_seen))
            except BaseException as error:
                errors.append(error)
            finally:
                reader_done.set()
        with self.scope():
            writer = spawn_context_thread(write, name="review-natural-writer", daemon=False)
            reader = spawn_context_thread(read, name="review-public-reader", daemon=False)
        writer.start()
        lock_held = reader_early = None
        try:
            self.assertTrue(inserted.wait(5), "actual_review_INSERT_not_reached")
            # Nonblocking cross-thread test of the full owner lock at the
            # native-return seam; never hold it to manufacture serialization.
            acquired = self.p._lock.acquire(blocking=False)
            lock_held = not acquired
            if acquired:
                self.p._lock.release()
            reader.start()
            self.assertTrue(entry_seen.wait(5), "public_reader_entry_not_reached")
            reader_early = reader_done.wait(.08)
        finally:
            release.set()
            writer.join(10)
            if reader.ident is not None:
                reader.join(10)
        self.record("review_writer_reader_schedule", snapshots=observations, full_writer_lock=lock_held,
                    reader_returned_before_release=reader_early, errors=[type(e).__name__ for e in errors],
                    reader_error=answers[0][0].get("error") if answers else None, state=self.state())
        self.assertFalse(writer.is_alive())
        self.assertFalse(reader.is_alive())
        self.assertEqual(len(observations), 1)
        snapshots = observations[0]
        self.assertEqual(len(snapshots["before"]), 1)
        self.assertEqual(len(snapshots["after"]), 1)
        for phase in ("before", "after"):
            self.assertTrue(snapshots[phase][0]["owner_exact"], "review_writer_not_registered_" + phase)
            self.assertTrue(snapshots[phase][0]["owner_same_thread"])
            self.assertTrue(snapshots[phase][0]["in_transaction"])
        self.assertIs(lock_held, True)
        self.assertIs(reader_early, False)
        self.assertEqual(errors, [])
        self.assertEqual(len(answers), 1)
        self.assert_queue(source="turn:user:" + self.p.session_id)
        self.assert_recalled(before, answers[0])

    def test_03_direct_firewall_queue_preserves_metadata_and_redaction(self):
        before = self.seed()
        evidence = "password violetShelf99"
        clean = self.m.redact_secrets(evidence)
        self.assertNotEqual(clean, evidence)
        result = self.firewall_queue(evidence=evidence, confidence=2, salience=-1,
                                     visibility_scope="global", project_id="foreign-project")
        self.assertTrue(result["secret_scan"]["raw_secret"])
        self.assertNotIn("claim_id", result)
        rid = self.assert_queue(source="model_tool:claim", evidence=clean, confidence=1.0, salience=0.0)
        self.assertEqual(result["review_id"], rid)
        self.assertNotIn("violetShelf99", self.queue_rows()[0]["evidence"])
        self.assert_ready()
        self.assert_recalled(before, self.recall())

    def test_04_queue_known_rollback_preserves_exact_primary(self):
        before = self.seed()
        primary = RuntimeError("synthetic-review-known-primary")
        def fail():
            raise primary
        with self.assertRaises(RuntimeError) as caught:
            with self.review_insert(fail) as snapshots:
                self.firewall_queue()
        self.assertIs(caught.exception, primary)
        self.assertEqual(len(snapshots["after"]), 1)
        self.assertEqual(self.queue_rows(), [])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM memory_changes WHERE action='review_enqueue'").fetchone()[0], 0)
        self.assertFalse(any("UNKNOWN" in n for n in getattr(primary, "__notes__", ())))
        self.assert_ready()
        self.assert_recalled(before, self.recall())

    def joined_queue(self, *, rollback):
        self.natural_input()
        before = self.seed()
        primary, statements = ValueError("synthetic-outer-review-rollback"), []
        reader = sqlite3.connect(str(self.p.db_path))
        self.conn.set_trace_callback(statements.append)
        rid = None
        try:
            try:
                with self.p._claim_transaction(self.conn):
                    self.conn.execute("INSERT INTO meta(key,value) VALUES('review_outer_marker','pending')")
                    if rollback:
                        candidate, topic, source, _ = self.natural_input()
                        rid = self.p._add_claim(candidate, topic, candidate, source, .75, .7, conn=self.conn)
                    else:
                        rid = self.firewall_queue()["review_id"]
                        source = "model_tool:claim"
                    self.assertEqual(self.assert_queue(source=source), rid)
                    self.assertTrue(self.conn.in_transaction)
                    self.assertIs(self.p._claim_tx_connection, self.conn)
                    self.assertEqual(self.p._claim_tx_thread, threading.get_ident())
                    self.assertFalse(any(s == "COMMIT" for s in statements))
                    self.assertEqual(reader.execute("SELECT count(*) FROM review_queue").fetchone()[0], 0)
                    self.assertEqual(reader.execute("SELECT count(*) FROM memory_changes WHERE action='review_enqueue'").fetchone()[0], 0)
                    if rollback:
                        raise primary
            except ValueError as caught:
                self.assertIs(caught, primary)
                self.assertTrue(rollback)
            self.assert_ready()
            if rollback:
                self.assertEqual(self.queue_rows(), [])
                self.assertEqual(reader.execute("SELECT count(*) FROM memory_changes WHERE action='review_enqueue'").fetchone()[0], 0)
                self.assertIsNone(self.conn.execute("SELECT value FROM meta WHERE key='review_outer_marker'").fetchone())
                self.assertEqual(statements.count("ROLLBACK"), 1)
                self.assertEqual(statements.count("COMMIT"), 0)
            else:
                self.assertEqual(self.assert_queue(source=source), rid)
                self.assertEqual(reader.execute("SELECT id FROM review_queue").fetchall(), [(rid,)])
                self.assertEqual(reader.execute("SELECT claim_id FROM memory_changes WHERE action='review_enqueue'").fetchall(), [(rid,)])
                self.assertEqual(statements.count("COMMIT"), 1)
            self.record("joined_review_owner", outer_rollback=rollback, no_premature_commit=True,
                        change_atomic=True, state=self.state())
        finally:
            self.conn.set_trace_callback(None)
            reader.close()
        self.assert_recalled(before, self.recall())

    def test_05_joined_claim_queue_outer_rollback_is_atomic(self):
        self.joined_queue(rollback=True)

    def test_06_joined_firewall_queue_outer_commit_keeps_change(self):
        self.joined_queue(rollback=False)

    def test_07_change_insert_denial_rolls_back_review(self):
        before = self.seed()
        denied = []
        def deny(action, first, second, database, trigger):
            if action == sqlite3.SQLITE_INSERT and first == "memory_changes":
                denied.append(first)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.conn.set_authorizer(deny)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                self.firewall_queue()
        finally:
            self.conn.set_authorizer(None)
        self.assertEqual(denied, ["memory_changes"])
        self.assertEqual(self.queue_rows(), [])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM memory_changes WHERE action='review_enqueue'").fetchone()[0], 0)
        self.assert_ready()
        self.assert_recalled(before, self.recall())

    def test_08_foreign_thread_begin_remains_unknown_after_owner_rollback(self):
        from agent.memory_provider import spawn_context_thread
        before = self.seed()
        active, finish = threading.Event(), threading.Event()
        errors = []
        def foreign():
            try:
                with self.scope():
                    self.conn.execute("BEGIN IMMEDIATE")
                    active.set()
                    if not finish.wait(15):
                        raise RuntimeError("foreign_owner_finish_timeout")
                    self.conn.rollback()  # Genuine original owner, NOT recovery.
            except BaseException as error:
                errors.append(error)
                active.set()
        with self.scope():
            thread = spawn_context_thread(foreign, name="review-foreign-owner", daemon=False)
        thread.start()
        try:
            self.assertTrue(active.wait(5))
            self.assertEqual(errors, [])
            self.assertTrue(self.conn.in_transaction)
            self.assertIsNone(self.p._claim_tx_connection)
            answer, deliveries = self.recall()
            self.assertEqual(answer, json.loads(self.m.tool_error("provider_transaction_owner_pending; transaction outcome UNKNOWN")))
            self.assertEqual(deliveries, [])
            self.assertIs(self.p._transaction_quarantine, self.conn)
            self.assertIsNone(self.p._transaction_primary)
            self.assertEqual(self.accounting(), before)
            self.assertIn("tool_pending_transaction", self.p._transaction_cleanup_notes)
            self.record("foreign_pending_retained", state=self.state())
        finally:
            finish.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(self.conn.in_transaction)
        self.assertIs(self.p._transaction_quarantine, self.conn)
        self.assertIs(self.p._conn, self.conn)
        self.assertIs(self.p._owned_conn, self.conn)
        self.assertEqual(self.p._lifecycle_state, "quarantined")
        self.assertIsNone(self.p._claim_tx_connection)
        self.assertIsNone(self.p._claim_tx_thread)
        repeated, deliveries = self.recall()
        self.assertEqual(repeated, json.loads(self.m.tool_error("provider_lifecycle_not_ready; transaction outcome UNKNOWN")))
        self.assertEqual(deliveries, [])
        with self.assertRaisesRegex(RuntimeError, "provider_lifecycle_not_ready"):
            self.p._connect()
        self.assertEqual(self.accounting(), before)
        self.assertEqual(self.queue_rows(), [])
        self.record("foreign_owner_idle_still_UNKNOWN", state=self.state())

    def test_09_queue_rollback_denied_retains_exact_primary_and_owner(self):
        before = self.seed()
        primary = RuntimeError("synthetic-private-review-primary-not-for-public")
        denied = []
        def deny(action, first, second, database, trigger):
            if action == sqlite3.SQLITE_TRANSACTION and first == "ROLLBACK":
                denied.append(first)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        def fail():
            raise primary
        self.conn.set_authorizer(deny)
        with self.assertRaises(RuntimeError) as caught:
            with self.review_insert(fail) as snapshots:
                self.firewall_queue()
        self.assertIs(caught.exception, primary)
        self.assertEqual(len(snapshots["after"]), 1)
        self.assertEqual(denied, ["ROLLBACK"])
        self.assertTrue(self.conn.in_transaction)
        self.assertIs(self.p._transaction_quarantine, self.conn)
        self.assertIs(self.p._transaction_primary, primary)
        self.assertIs(self.p._claim_tx_connection, self.conn)
        owner_thread = self.p._claim_tx_thread
        self.assertEqual(owner_thread, threading.get_ident())
        self.assertIn("rollback_DatabaseError", self.p._transaction_cleanup_notes)
        self.assertTrue(any("outcome=UNKNOWN" in n for n in primary.__notes__))
        self.assertEqual(len(self.queue_rows()), 1)  # Uncommitted effect retained.
        self.assertEqual(self.conn.execute("SELECT count(*) FROM memory_changes WHERE action='review_enqueue'").fetchone()[0], 0)
        for action in (self.p._connect, self.p.shutdown,
                       lambda: self.p.initialize("must-not-replace", hermes_home=str(self.home))):
            with self.assertRaises(RuntimeError):
                action()
        self.assertIs(self.p._release_connection_for_retry(primary), False)
        for _ in range(2):
            answer, deliveries = self.recall()
            self.assertIn("UNKNOWN", answer["error"])
            self.assertIn("RuntimeError", answer["error"])
            self.assertNotIn("synthetic-private-review-primary", json.dumps(answer))
            self.assertNotIn("items", answer)
            self.assertNotIn("recall_tracking", answer)
            self.assertNotIn("retrieval_receipt", answer)
            self.assertEqual(deliveries, [])
            self.assertIs(self.p._transaction_primary, primary)
            self.assertIs(self.p._transaction_quarantine, self.conn)
            self.assertIs(self.p._conn, self.conn)
            self.assertIs(self.p._owned_conn, self.conn)
            self.assertIs(self.p._claim_tx_connection, self.conn)
            self.assertEqual(self.p._claim_tx_thread, owner_thread)
            self.assertTrue(self.conn.in_transaction)
        self.assertEqual(self.accounting(), before)
        self.record("native_review_rollback_denied", exact_primary_retained=True, state=self.state())


if __name__ == "__main__":
    unittest.main()
