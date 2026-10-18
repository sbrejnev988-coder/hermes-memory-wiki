"""Native offline episode/owner regression; also collectible by real pytest.

Uses stdlib unittest so the selected PM interpreter need not be modified to
install a test runner. The packet records missing pytest separately. Every
case imports the real plugin into its own synthetic home BEFORE initialize;
SDK/registry/trust/ACL/SQL/lifecycle callables are never replaced. Only authored
input, owned SQL race writers and exact code-bound diagnostic hooks are used.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[1]
TEXT = "Контрольный узел Кедр хранит cedar_episode_probe в локальном каталоге."
QUERY = "cedar_episode_probe"
CLAIM = "Пользователь предпочитает овальные керамические этикетки для Лазурного маяка."


def unwrapped(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


@contextmanager
def exact_hook(function, event, action):
    """Finite, exact own-process seam, not a callable/authority replacement."""
    prior = sys.getprofile()
    if prior is not None:
        raise RuntimeError("existing_profile_not_replaced")
    code = function.__code__
    hits = []
    def profile(frame, observed, arg):
        if frame.f_code is code and observed == event:
            hits.append(True)
            action(frame, arg)
    sys.setprofile(profile)
    try:
        yield hits
    finally:
        sys.setprofile(prior)


class NativeEpisodeOwner(unittest.TestCase):
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
                "claim_owner_retired": p._claim_tx_connection is None and p._claim_tx_thread is None,
                "quarantined": p._transaction_quarantine is not None,
                "retained_readers": len(getattr(p, "_graph_reader_connections", {})),
                "background_worker": p._background_worker is not None,
                "primary_type": type(p._transaction_primary).__name__ if p._transaction_primary is not None else None,
                "cleanup_codes": list(p._transaction_cleanup_notes)}

    def setUp(self):
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        from agent.memory_provider import MemoryProvider
        import tools.registry as registry
        import hermes_trust_core as trust
        # Normal pytest may supply TMPDIR; the bounded packet supplies an exact
        # non-package test root. No synthetic files go into the repository.
        base = Path(os.environ.get("MW_EP_TEST_ROOT") or os.environ["TMPDIR"])
        label = self._testMethodName
        self.root = base / ("episode-owner-" + label)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=False)
        self.original_environment = dict(os.environ)
        self.original_sys_path = list(sys.path)
        settings = {
            "HERMES_HOME": str(self.home),
            "HERMES_SECURITY_STRICT": "0" if "strict0" in label else "1",
            "MEMORY_WIKI_STRICT_RECALL": "1", "MEMORY_WIKI_SEMANTIC": "0",
            "MEMORY_WIKI_EMBED_PROVIDER": "stub", "MEMORY_WIKI_EMBED_MODEL": "hash-ngram-8",
            "MEMORY_WIKI_EMBED_DIMENSIONS": "8", "MEMORY_WIKI_VECTOR_SIZE": "8",
            "MEMORY_WIKI_RERANK_ENABLED": "0", "MEMORY_WIKI_LLM_PACK": "0",
            "MEMORY_WIKI_GRAPH_AUTO_EXTRACT": "0", "MEMORY_WIKI_GRAPH_EXTRACT_ENABLED": "0",
            "MEMORY_WIKI_EPISODIC_ENABLED": "1", "MEMORY_WIKI_EPISODIC_SCOPE": "chat",
            "MEMORY_WIKI_EPISODIC_SEMANTIC": "0", "MEMORY_WIKI_EPISODIC_PREFETCH": "0",
            "MEMORY_WIKI_EPISODIC_QUERY_MODE": "fast",
            "MEMORY_WIKI_EVENT_LEDGER_ENABLED": "1" if "channels" in label else "0",
            "MEMORY_WIKI_EVENT_SCOPE": "chat", "MEMORY_WIKI_OBSERVATIONS_ENABLED": "1" if "channels" in label else "0",
            "MEMORY_WIKI_BACKGROUND_JOBS_ENABLED": "0", "MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK": "0",
            "MEMORY_WIKI_DOCUMENT_PREFETCH": "0", "MEMORY_WIKI_CODE_GRAPH_PREFETCH": "0",
            "MEMORY_WIKI_ONLINE_METRICS_ENABLED": "1",
        }
        os.environ.update(settings)
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
        self.namespace = "_native_episode_owner_" + label
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
        self.p.initialize("synthetic-episode-chat", hermes_home=str(self.home),
                          agent_context="primary", bot_id="synthetic-episode-bot",
                          project_id="synthetic-episode-project", visibility_scope="chat")
        self.conn = self.p._conn
        self.addCleanup(self.close_owned_fixture)
        self.assertIs(self.conn, self.p._owned_conn)
        self.assertTrue(isinstance(self.conn, sqlite3.Connection))
        self.assertFalse(self.m.SEMANTIC_ENABLED)
        self.assertIsNone(self.p._background_worker)
        with self.m._native_profile_scope(self.home), self.m._profile_qdrant_scope(self.home):
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
        # Observe production outcome BEFORE any reviewer-only safety cleanup.
        self.record("before_shutdown", state=self.state())
        retained = list(getattr(self.p, "_graph_reader_connections", {}))
        if self.p._transaction_quarantine is None and not retained:
            self.p.shutdown()
            self.assertIsNone(self.p._conn)
            self.assertIsNone(self.p._owned_conn)
            self.assertEqual(self.p._lifecycle_state, "idle")
            self.assertIsNone(self.p._background_worker)
            with self.assertRaises(sqlite3.ProgrammingError):
                self.conn.execute("SELECT 1")
            self.record("shutdown", outcome="natural_closed", owner_retired=True)
        else:
            with self.assertRaisesRegex(RuntimeError, "provider_transaction_cleanup_required"):
                self.p.shutdown()
            self.record("shutdown", outcome="refused_retained_UNKNOWN",
                        quarantine_preserved=self.p._transaction_quarantine is not None)
            # Test-owned physical handles only. No owner/quarantine/primary is
            # cleared, no provider retry/reconnect, no production recovery claim.
            for conn in [*retained, self.conn]:
                conn.set_authorizer(None)
                sqlite3.Connection.close(conn)
                with self.assertRaises(sqlite3.ProgrammingError):
                    conn.execute("SELECT 1")
            self.record("fixture_safety_close", outcome="test_owned_only_not_recovery")
        self.assertEqual([t.name for t in threading.enumerate() if t is not threading.main_thread()], [])

    def assert_ready(self):
        self.assertEqual(self.p._lifecycle_state, "ready")
        self.assertFalse(self.p._degraded)
        self.assertIsNone(self.p._transaction_quarantine)
        self.assertIsNone(self.p._transaction_primary)
        self.assertFalse(self.conn.in_transaction)
        self.assertIsNone(self.p._claim_tx_connection)
        self.assertIsNone(self.p._claim_tx_thread)
        self.assertEqual(getattr(self.p, "_graph_reader_connections", {}), {})
        self.assertEqual(getattr(self.p, "_graph_writer_connections", {}), {})

    def capture(self):
        self.p.sync_turn(TEXT, "")
        rows = self.conn.execute("SELECT * FROM episodic_turns").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], TEXT)
        self.assertEqual(rows[0]["owner_bot_id"], self.p.bot_id)
        self.assertEqual(rows[0]["owner_chat_hash"], self.p._chat_hash())
        self.assertGreater(rows[0]["expires_at"], self.m.now())
        self.assertEqual(self.conn.execute("SELECT count(*) FROM claims").fetchone()[0], 0)
        self.assert_ready()
        return rows[0]["id"]

    def public(self, query=QUERY, *, mode="fast", name="memory_wiki_recall"):
        args = {"query": query, "limit": 10}
        if name == "memory_wiki_recall":
            args.update(mode=mode, max_chars=4000)
        return json.loads(self.p.handle_tool_call(name, args))

    def assert_match(self):
        eid = self.capture()
        result = self.public()
        self.assertNotIn("error", result)
        self.assertNotEqual(result.get("disclosure_status"), "withheld")
        self.assertEqual(result["evidence_count"], 1)
        self.assertEqual([(i["kind"], i["id"], i["content"]) for i in result["items"]],
                         [("episode", eid, TEXT)])
        self.assertEqual(result["answer_policy"]["allowed_citations"], ["[M:E:" + eid + "]"])
        self.assertEqual(result["recall_tracking"]["status"], "not_needed")
        self.assert_ready()
        self.record("public_matching_episode", evidence_count=1, episode_id=eid,
                    untraced=sys.gettrace() is None and sys.getprofile() is None, state=self.state())

    def test_01_sync_turn_matching_fast_untraced_strict1(self):
        self.assertIsNone(sys.gettrace())
        self.assertIsNone(sys.getprofile())
        self.assert_match()

    def test_02_sync_turn_matching_fast_untraced_strict0(self):
        self.assertIsNone(sys.gettrace())
        self.assertIsNone(sys.getprofile())
        self.assert_match()

    def test_03_enabled_empty_fast(self):
        self.assertEqual(self.conn.execute("SELECT count(*) FROM episodic_turns").fetchone()[0], 0)
        result = self.public()
        self.assertNotIn("error", result)
        self.assertEqual(result["evidence_count"], 0)
        self.assert_ready()

    def test_04_captured_episode_no_match_fast(self):
        eid = self.capture()
        result = self.public("obsidian_never_present")
        self.assertNotIn("error", result)
        self.assertEqual(result["evidence_count"], 0)
        self.assertEqual(self.conn.execute("SELECT content FROM episodic_turns WHERE id=?", (eid,)).fetchone()[0], TEXT)
        self.assert_ready()

    def test_05_direct_episode_positive(self):
        eid = self.capture()
        result = self.public(name="memory_wiki_query_episodes")
        self.assertNotIn("error", result)
        self.assertEqual([(r["id"], r["content"]) for r in result["episodes"]], [(eid, TEXT)])
        self.assert_ready()

    def test_06_claim_only_positive_tracking(self):
        result = json.loads(self.p.handle_tool_call("memory_wiki_add_claim", {
            "claim": CLAIM, "topic": "preferences", "evidence": CLAIM,
            "confidence": .8, "salience": .75}))
        self.assertEqual(result.get("state"), "stored", result)
        self.assertTrue(result["immediately_recallable"])
        cid = result["id"]
        before = self.conn.execute("SELECT access_count,recall_count FROM claims WHERE id=?", (cid,)).fetchone()
        recalled = self.public("керамические этикетки")
        self.assertEqual([(r["kind"], r["id"]) for r in recalled["items"]], [("claim", cid)])
        self.assertEqual(recalled["recall_tracking"]["status"], "ok")
        event_id = recalled["items"][0]["recall_event_id"]
        self.assertEqual(recalled["recall_tracking"]["answer_linkage"]["recall_event_ids"], [event_id])
        self.assertEqual(tuple(self.conn.execute("SELECT claim_id,used,outcome FROM recall_events WHERE id=?", (event_id,)).fetchone()), (cid, -1, "pending"))
        after = self.conn.execute("SELECT access_count,recall_count FROM claims WHERE id=?", (cid,)).fetchone()
        self.assertEqual(tuple(after), (before[0] + 1, before[1] + 1))
        self.assert_ready()

    def test_07_channels_episode_events_observation_positive(self):
        self.p.sync_turn(TEXT, "")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM episodic_turns").fetchone()[0], 1)
        event_ids = [self.m._memory_events.capture_event(
            self.p, self.m, TEXT, role="observer", event_type="observation", scope="chat",
            turn_id="synthetic-observer-" + str(i)) for i in (1, 2)]
        self.assertTrue(all(event_ids))
        consolidated = self.m._memory_observations.consolidate_events(self.p, self.m, scope="chat")
        self.assertGreaterEqual(consolidated["versions_created"], 1)
        result = self.public(mode="auto")
        self.assertNotIn("error", result)
        kinds = {row["kind"] for row in result["items"]}
        self.assertTrue({"episode", "event", "observation"} <= kinds, result)
        self.assertTrue(all(QUERY in row["content"] for row in result["items"]))
        self.assert_ready()
        self.record("healthy_channels", kinds=sorted(kinds), state=self.state())

    def test_08_private_snapshot_is_not_writer_authority(self):
        self.capture()
        helper = self.m._recall_orchestrator._final_visible_nonclaims_on_connection
        readers, sql = [], []
        def observe(frame, _arg):
            reader = frame.f_locals["conn"]
            graph = sys.modules[self.namespace + ".code_knowledge_graph"]
            self.assertTrue(graph._owns_graph_reader(self.p, reader))
            self.assertIsNot(reader, self.conn)
            self.assertEqual(reader.execute("PRAGMA query_only").fetchone()[0], 1)
            self.assertFalse(self.conn.in_transaction)
            self.assertIsNone(self.p._claim_tx_connection)
            with self.assertRaisesRegex(RuntimeError, "claim_mutation_transaction_not_owned"):
                with self.p._claim_transaction(reader):
                    self.fail("read-only lifetime became a writer")
            with self.assertRaises(sqlite3.OperationalError):
                reader.execute("INSERT INTO meta(key,value) VALUES('forbidden_reader_write','1')")
            readers.append(reader)
            reader.set_trace_callback(sql.append)
        with exact_hook(helper, "call", observe) as hits:
            result = self.public()
        self.assertEqual(len(hits), 1)
        self.assertEqual(result["evidence_count"], 1)
        self.assertEqual(sum(s.startswith("SAVEPOINT memory_wiki_unified_final_") for s in sql), 1)
        self.assertEqual(sum(s.startswith("RELEASE memory_wiki_unified_final_") for s in sql), 1)
        self.assertTrue(any("FROM episodic_turns" in s for s in sql))
        self.assertFalse(any(s.startswith("BEGIN IMMEDIATE") for s in sql))
        for reader in readers:
            with self.assertRaises(sqlite3.ProgrammingError):
                reader.execute("SELECT 1")
        self.assertIsNone(self.conn.execute("SELECT value FROM meta WHERE key='forbidden_reader_write'").fetchone())
        self.assert_ready()
        self.record("private_snapshot", snapshots=1, query_only=True, writer_denied=True,
                    exact_reader_closed=True, state=self.state())

    def edit_episode(self, eid, *, expired=False):
        writer = sqlite3.connect(str(self.p.db_path))
        try:
            if expired:
                self.assertEqual(writer.execute("UPDATE episodic_turns SET expires_at=0 WHERE id=?", (eid,)).rowcount, 1)
            else:
                self.assertEqual(writer.execute("DELETE FROM episodic_turns WHERE id=?", (eid,)).rowcount, 1)
            writer.commit()
        finally:
            writer.close()

    def assert_withheld(self, result):
        self.assertFalse(result.get("items"), result)
        self.assertNotIn(TEXT, json.dumps(result, ensure_ascii=False))
        self.assertTrue(result.get("disclosure_status") == "withheld" or result.get("evidence_count") == 0, result)

    def test_09_late_expiry_after_candidates_is_withheld(self):
        eid = self.capture()
        with exact_hook(self.m._recall_orchestrator._final_visible_nonclaims, "call",
                        lambda *_: self.edit_episode(eid, expired=True)) as hits:
            result = self.public()
        self.assertEqual(len(hits), 1)
        self.assert_withheld(result)
        self.assertEqual(self.conn.execute("SELECT expires_at FROM episodic_turns WHERE id=?", (eid,)).fetchone()[0], 0)
        self.assert_ready()

    def test_10_late_session_change_does_not_rebase_original_identity(self):
        self.capture()
        with exact_hook(self.m._recall_orchestrator._final_visible_nonclaims, "call",
                        lambda *_: setattr(self.p, "session_id", "synthetic-late-chat")) as hits:
            result = self.public()
        self.assertEqual(len(hits), 1)
        self.assert_withheld(result)
        self.assert_ready()

    def test_11_foreign_original_request_home_is_withheld(self):
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        self.capture()
        foreign = self.root / "foreign-request"
        foreign.mkdir()
        token = set_hermes_home_override(foreign)
        try:
            result = self.public()
        finally:
            reset_hermes_home_override(token)
        self.assert_withheld(result)
        self.assert_ready()

    def test_12_foreign_pending_public_recall_remains_quarantined(self):
        self.capture()
        self.conn.execute("BEGIN IMMEDIATE")
        self.assertIsNone(self.p._claim_tx_connection)
        result = self.public()
        self.assertIn("UNKNOWN", result["error"])
        self.assertIn("provider_transaction_owner_pending", result["error"])
        self.assertNotIn("items", result)
        self.assertIs(self.p._transaction_quarantine, self.conn)
        self.assertTrue(self.conn.in_transaction)
        self.assertIsNone(self.p._transaction_primary)
        with self.assertRaisesRegex(RuntimeError, "provider_lifecycle_not_ready"):
            self.p._connect()
        self.record("foreign_pending_retained", state=self.state())

    def test_13_meta_identity_does_not_swallow_first_owner_refusal(self):
        self.conn.execute("BEGIN IMMEDIATE")
        with self.assertRaisesRegex(RuntimeError, "^provider_transaction_owner_pending$"):
            self.p._meta_text("database_instance_id", "uninitialized")
        self.assertIs(self.p._transaction_quarantine, self.conn)
        self.assertTrue(self.conn.in_transaction)
        self.assertEqual(self.p._lifecycle_state, "quarantined")
        self.record("first_identity_refusal_preserved", state=self.state())

    def test_14_native_rollback_denial_preserves_primary_UNKNOWN(self):
        self.capture()
        primary = RuntimeError("synthetic-private-primary-not-public")
        denied = []
        def deny(action, first, second, database, trigger):
            if action == sqlite3.SQLITE_TRANSACTION and first == "ROLLBACK":
                denied.append(first)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.conn.set_authorizer(deny)
        with self.assertRaises(RuntimeError) as caught:
            with self.p._claim_transaction(self.conn):
                raise primary
        self.assertIs(caught.exception, primary)
        self.assertEqual(denied, ["ROLLBACK"])
        self.assertIs(self.p._transaction_primary, primary)
        self.assertIs(self.p._transaction_quarantine, self.conn)
        self.assertIs(self.p._claim_tx_connection, self.conn)
        self.assertEqual(self.p._claim_tx_thread, threading.get_ident())
        self.assertTrue(self.conn.in_transaction)
        result = self.public()
        self.assertIn("UNKNOWN", result["error"])
        self.assertNotIn("synthetic-private-primary", json.dumps(result))
        self.assertNotIn("items", result)
        self.assertIs(self.p._transaction_primary, primary)
        self.record("native_rollback_denied", state=self.state())

    def test_15_reader_release_and_rollback_denial_remains_UNKNOWN(self):
        self.capture()
        readers, denied = [], []
        def prepare(frame, _arg):
            reader = frame.f_locals["conn"]
            def deny(action, first, second, database, trigger):
                if ((action == sqlite3.SQLITE_SAVEPOINT and first == "RELEASE")
                        or (action == sqlite3.SQLITE_TRANSACTION and first == "ROLLBACK")):
                    denied.append((action, first))
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            reader.set_authorizer(deny)
            readers.append(reader)
        with exact_hook(self.m._recall_orchestrator._final_visible_nonclaims_on_connection,
                        "call", prepare) as hits:
            result = self.public()
        self.assertEqual(len(hits), 1)
        self.assertEqual(len(readers), 1)
        reader = readers[0]
        self.assertIn("UNKNOWN", result["error"])
        self.assertNotIn("items", result)
        self.assertNotIn(TEXT, json.dumps(result, ensure_ascii=False))
        self.assertTrue(any(first == "RELEASE" for _, first in denied))
        self.assertTrue(any(first == "ROLLBACK" for _, first in denied))
        self.assertIs(self.p._transaction_quarantine, reader)
        self.assertIs(self.p._transaction_primary, reader._graph_read_primary)
        self.assertIsInstance(self.p._transaction_primary, sqlite3.DatabaseError)
        self.assertEqual(reader._graph_read_state, "quarantined")
        self.assertIn(reader, self.p._graph_reader_connections)
        self.assertTrue(reader.in_transaction)
        self.assertFalse(self.conn.in_transaction)
        self.assertIsNone(self.p._claim_tx_connection)
        self.record("private_cleanup_UNKNOWN", release_denied=True, rollback_denied=True,
                    exact_primary_retained=True, state=self.state())

    def test_16_reader_read_error_with_known_cleanup_is_empty_not_quarantine(self):
        self.capture()
        denied = []
        def prepare(frame, _arg):
            reader = frame.f_locals["conn"]
            def deny(action, first, second, database, trigger):
                if action == sqlite3.SQLITE_READ and first == "episodic_turns":
                    denied.append(first)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            reader.set_authorizer(deny)
        with exact_hook(self.m._recall_orchestrator._final_visible_nonclaims_on_connection,
                        "call", prepare) as hits:
            result = self.public()
        self.assertEqual(len(hits), 1)
        self.assertTrue(denied)
        self.assertNotIn("error", result)
        self.assert_withheld(result)
        self.assert_ready()

    def test_17_database_identity_drift_during_snapshot_is_not_adopted(self):
        self.capture()
        identity = self.m._episodic_memory._identity
        hits = []
        def change(frame, _arg):
            # Target only identity inside the actual private final snapshot,
            # not the genuine earlier retrieval identity call.
            parent = frame.f_back
            if parent.f_code is self.m._recall_orchestrator._final_visible_nonclaims_on_connection.__code__:
                hits.append(True)
                writer = sqlite3.connect(str(self.p.db_path))
                try:
                    writer.execute("UPDATE meta SET value='synthetic-replaced-db' WHERE key='database_instance_id'")
                    writer.commit()
                finally:
                    writer.close()
        with exact_hook(identity, "call", change):
            result = self.public()
        self.assertEqual(len(hits), 1)
        self.assert_withheld(result)
        self.assert_ready()


if __name__ == "__main__":
    unittest.main()
