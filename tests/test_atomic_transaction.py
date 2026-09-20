"""Multi-operation claim edits commit or roll back as one SQLite unit."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    name = "memory_wiki_atomic_transaction_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize("session-a", hermes_home=str(tmp_path), bot_id="bot-a", agent_context="test")
    with provider._connect() as conn:
        for cid, claim in (("c_atomic_a", "Original amber lantern fact"), ("c_atomic_b", "Original violet compass fact")):
            conn.execute(
                """INSERT INTO claims(id,claim,normalized_claim,topic,status,confidence,salience,source,evidence,
                   created_at,updated_at,freshness_at,access_count,last_accessed,hash,scope,
                   visibility_scope,origin_session_id,origin_bot_id,origin_chat_hash,quality,risk,quarantined_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, claim, claim, "general", "active", .9, .9, "test", "",
                 module.now(), module.now(), module.now(), 0, 0, cid, "global",
                 "chat", "session-a", "bot-a", provider._chat_hash("session-a"), .9, "low", 0),
            )
    return provider


def test_atomic_batch_commits_multiple_edits_and_index(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        outcome = provider._transaction([
            {"tool": "update_claim", "args": {"claim_id": "c_atomic_a", "claim": "Updated amber lantern fact"}},
            {"tool": "rewrite_claim", "args": {"claim_id": "c_atomic_b", "claim": "Rewritten violet compass fact"}},
        ], mode="apply")
        assert outcome["atomic"] is True and outcome["rolled_back"] is False, outcome
        assert len(outcome["results"]) == 2
        conn = provider._connect()
        assert conn.execute("SELECT claim FROM claims WHERE id='c_atomic_a'").fetchone()[0] == "Updated amber lantern fact"
        assert conn.execute("SELECT claim FROM claims WHERE id='c_atomic_b'").fetchone()[0] == "Rewritten violet compass fact"
        assert conn.execute("SELECT count(*) FROM claims_fts WHERE id IN ('c_atomic_a','c_atomic_b')").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM memory_mutations WHERE batch_id=?", (outcome["batch_id"],)).fetchone()[0] >= 2
    finally:
        provider._connect().close()


def test_atomic_batch_rolls_back_claim_and_mutation_on_later_error(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        outcome = provider._transaction([
            {"tool": "update_claim", "args": {"claim_id": "c_atomic_a", "claim": "Should roll back amber lantern"}},
            {"tool": "rewrite_claim", "args": {"claim_id": "c_atomic_b", "claim": ""}},
        ], mode="apply")
        assert outcome["atomic"] is True and outcome["rolled_back"] is True, outcome
        conn = provider._connect()
        assert conn.execute("SELECT claim FROM claims WHERE id='c_atomic_a'").fetchone()[0] == "Original amber lantern fact"
        assert conn.execute("SELECT count(*) FROM memory_mutations WHERE batch_id=?", (outcome["batch_id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM claims_fts WHERE id='c_atomic_a' AND claim MATCH 'roll'").fetchone()[0] == 0
    finally:
        provider._connect().close()


def test_unsupported_multi_batch_is_rejected_before_write(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        outcome = provider._transaction([
            {"tool": "update_claim", "args": {"claim_id": "c_atomic_a", "status": "retired"}},
            {"tool": "repair", "args": {"target": "all"}},
        ], mode="apply")
        assert outcome["errors"][0]["error"] == "unsupported_atomic_transaction_operation"
        assert provider._connect().execute("SELECT status FROM claims WHERE id='c_atomic_a'").fetchone()[0] == "active"
    finally:
        provider._connect().close()


def test_atomic_merge_rolls_back_evidence_move_and_status(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        conn = provider._connect()
        with conn:
            conn.execute("INSERT INTO evidence(id,claim_id,kind,text,source,created_at) VALUES(?,?,?,?,?,?)",
                         ("e_atomic_b", "c_atomic_b", "support", "violet evidence", "test", 1))
        outcome = provider._transaction([
            {"tool": "merge_claims", "args": {"keep_id": "c_atomic_a", "merge_ids": ["c_atomic_b"]}},
            {"tool": "rewrite_claim", "args": {"claim_id": "c_atomic_a", "claim": ""}},
        ], mode="apply")
        assert outcome["rolled_back"] is True, outcome
        assert conn.execute("SELECT status FROM claims WHERE id='c_atomic_b'").fetchone()[0] == "active"
        assert conn.execute("SELECT claim_id FROM evidence WHERE id='e_atomic_b'").fetchone()[0] == "c_atomic_b"
        assert conn.execute("SELECT count(*) FROM memory_mutations WHERE batch_id=?", (outcome["batch_id"],)).fetchone()[0] == 0
    finally:
        provider._connect().close()


def test_model_facing_atomic_batch_rechecks_claim_visibility(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        other = type(provider)()
        other.initialize("session-b", hermes_home=str(tmp_path), bot_id="bot-b", agent_context="test")
        try:
            result = json.loads(other.handle_tool_call("memory_wiki_transaction", {
                "mode": "apply", "operations": [
                    {"tool": "update_claim", "args": {"claim_id": "c_atomic_a", "status": "retired"}},
                    {"tool": "update_claim", "args": {"claim_id": "c_atomic_b", "status": "retired"}},
                ],
            }))
            assert result.get("success") is False, result
            assert provider._connect().execute("SELECT count(*) FROM claims WHERE status='active'").fetchone()[0] == 2
        finally:
            other._connect().close()
    finally:
        provider._connect().close()


def test_model_facing_atomic_batch_journals_one_operation_boundary(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        result = json.loads(provider.handle_tool_call("memory_wiki_transaction", {
            "mode": "apply", "operations": [
                {"tool": "update_claim", "args": {"claim_id": "c_atomic_a", "status": "uncertain"}},
                {"tool": "update_claim", "args": {"claim_id": "c_atomic_b", "status": "retired"}},
            ],
        }))
        assert result.get("success") is True and result.get("atomic") is True, result
        conn = provider._connect()
        assert conn.execute("SELECT status FROM claims WHERE id='c_atomic_a'").fetchone()[0] == "uncertain"
        assert conn.execute("SELECT status FROM claims WHERE id='c_atomic_b'").fetchone()[0] == "retired"
        journal = provider._journal_verify() if hasattr(provider, "_journal_verify") else None
        if journal is not None:
            assert journal.get("ok", journal.get("valid", True)), journal
    finally:
        provider._connect().close()


def test_model_facing_rollback_reports_failure(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        result = json.loads(provider.handle_tool_call("memory_wiki_transaction", {
            "mode": "apply", "operations": [
                {"tool": "update_claim", "args": {"claim_id": "c_atomic_a", "status": "retired"}},
                {"tool": "rewrite_claim", "args": {"claim_id": "c_atomic_b", "claim": ""}},
            ],
        }))
        assert result.get("success") is False and result.get("rolled_back") is True, result
        assert provider._connect().execute("SELECT status FROM claims WHERE id='c_atomic_a'").fetchone()[0] == "active"
    finally:
        provider._connect().close()


def test_unknown_mode_is_rejected_without_write(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        result = json.loads(provider.handle_tool_call("memory_wiki_transaction", {
            "mode": "sugest", "operations": [
                {"tool": "update_claim", "args": {"claim_id": "c_atomic_a", "status": "retired"}},
            ],
        }))
        assert "invalid transaction mode" in str(result.get("error")), result
        assert provider._connect().execute("SELECT status FROM claims WHERE id='c_atomic_a'").fetchone()[0] == "active"
    finally:
        provider._connect().close()


def test_atomic_batch_fails_closed_when_fts_trigger_missing(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        conn = provider._connect()
        with conn:
            conn.execute("DROP TRIGGER trg_claims_active_content_indexes")
        outcome = provider._transaction([
            {"tool": "update_claim", "args": {"claim_id": "c_atomic_a", "claim": "Changed amber lantern"}},
            {"tool": "update_claim", "args": {"claim_id": "c_atomic_b", "claim": "Changed violet compass"}},
        ], mode="apply")
        assert outcome["rolled_back"] is True and outcome["errors"], outcome
        assert conn.execute("SELECT claim FROM claims WHERE id='c_atomic_a'").fetchone()[0] == "Original amber lantern fact"
    finally:
        provider._connect().close()


def test_batch_ids_do_not_repeat_within_one_second(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        ids = {provider._transaction([], mode="suggest")["batch_id"] for _ in range(3)}
        assert len(ids) == 3
    finally:
        provider._connect().close()


def test_merge_rejects_cross_partition_evidence_promotion(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        conn = provider._connect()
        with conn:
            conn.execute("UPDATE claims SET visibility_scope='global' WHERE id='c_atomic_a'")
            conn.execute("INSERT INTO evidence(id,claim_id,kind,text,source,created_at) VALUES(?,?,?,?,?,?)",
                         ("e_private_loser", "c_atomic_b", "support", "private evidence sentinel", "test", 1))
        try:
            provider._merge_claims({"keep_id": "c_atomic_a", "merge_ids": ["c_atomic_b"]})
        except ValueError as exc:
            assert "visibility partition" in str(exc)
        else:
            raise AssertionError("ordinary merge accepted a private-to-global move")
        outcome = provider._transaction([
            {"tool": "merge_claims", "args": {"keep_id": "c_atomic_a", "merge_ids": ["c_atomic_b"]}},
            {"tool": "update_claim", "args": {"claim_id": "c_atomic_a", "status": "uncertain"}},
        ], mode="apply")
        assert outcome["rolled_back"] is True and outcome["errors"], outcome
        assert conn.execute("SELECT claim_id FROM evidence WHERE id='e_private_loser'").fetchone()[0] == "c_atomic_b"
        assert conn.execute("SELECT status FROM claims WHERE id='c_atomic_a'").fetchone()[0] == "active"
    finally:
        provider._connect().close()


def test_merge_redacts_resolution_before_evidence_persistence(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        marker = "password=VerySecretLongString123"
        provider._merge_claims({"keep_id": "c_atomic_a", "merge_ids": ["c_atomic_b"], "resolution": marker})
        note = provider._connect().execute(
            "SELECT text FROM evidence WHERE claim_id='c_atomic_a' AND source='merge' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        assert marker not in note
    finally:
        provider._connect().close()


def test_same_session_name_different_bot_cannot_see_chat_claim(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        other = type(provider)()
        other.initialize("session-a", hermes_home=str(tmp_path), bot_id="bot-b", agent_context="test")
        try:
            row = other._connect().execute("SELECT * FROM claims WHERE id='c_atomic_a'").fetchone()
            assert other._claim_visible(row) is False
            with provider._connect() as conn:
                conn.execute("UPDATE claims SET visibility_scope='private' WHERE id='c_atomic_a'")
            row = other._connect().execute("SELECT * FROM claims WHERE id='c_atomic_a'").fetchone()
            assert other._claim_visible(row) is False
        finally:
            other._connect().close()
    finally:
        provider._connect().close()


def test_compiler_refuses_mixed_visibility_and_preserves_chat_scope(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        conn = provider._connect()
        with conn:
            conn.execute("UPDATE claims SET visibility_scope='global' WHERE id='c_atomic_a'")
            conn.execute("UPDATE claims SET claim=?, normalized_claim=? WHERE id='c_atomic_a'",
                         ("The owner keeps the amber lantern in the northern observatory archive and uses it to mark completed visits each autumn.",
                          "The owner keeps the amber lantern in the northern observatory archive and uses it to mark completed visits each autumn."))
            conn.execute("UPDATE claims SET claim=?, normalized_claim=? WHERE id='c_atomic_b'",
                         ("The owner stores a violet compass in the same archive and checks its bearing before every winter expedition.",
                          "The owner stores a violet compass in the same archive and checks its bearing before every winter expedition."))
        before = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        try:
            provider._compile_topic("general", "apply")
        except ValueError as exc:
            assert "visibility partition" in str(exc)
        else:
            raise AssertionError("compiler combined global and chat claims")
        assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == before
        with conn:
            conn.execute("UPDATE claims SET visibility_scope='chat' WHERE id='c_atomic_a'")
        outcome = provider._compile_topic("general", "apply")
        row = conn.execute("SELECT visibility_scope,origin_bot_id,origin_chat_hash FROM claims WHERE id=?",
                           (outcome["claim_id"],)).fetchone()
        assert row is not None and row["visibility_scope"] == "chat"
        assert row["origin_bot_id"] == "bot-a" and row["origin_chat_hash"] == provider._chat_hash("session-a")
    finally:
        provider._connect().close()


def test_contradiction_rejects_mixed_scope_and_redacts_metadata(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        conn = provider._connect()
        with conn:
            conn.execute("UPDATE claims SET visibility_scope='global' WHERE id='c_atomic_a'")
        try:
            provider._add_contradiction("c_atomic_a", "c_atomic_b", "private reason")
        except ValueError as exc:
            assert "visibility partition" in str(exc)
        else:
            raise AssertionError("cross-scope contradiction accepted")
        with conn:
            conn.execute("UPDATE claims SET visibility_scope='chat' WHERE id='c_atomic_a'")
        marker = "password=VerySecretLongString123"
        kid = provider._add_contradiction("c_atomic_a", "c_atomic_b", marker)
        assert marker not in conn.execute("SELECT reason FROM contradictions WHERE id=?", (kid,)).fetchone()[0]
        provider._resolve_contradiction({"contradiction_id": kid, "resolution": marker})
        assert marker not in conn.execute("SELECT resolution FROM contradictions WHERE id=?", (kid,)).fetchone()[0]
    finally:
        provider._connect().close()


def test_same_session_cross_bot_claim_write_cannot_take_over_owner(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        other = type(provider)()
        other.initialize("session-a", hermes_home=str(tmp_path), bot_id="bot-b", agent_context="test")
        try:
            text = "The amber observatory ledger records the north tower inspection every October and names the violet compass as its reference instrument."
            first = provider._add_claim(text, "general", "Alice's independent observation", "phase6_curated_summary:test", .9, .9,
                                        visibility_scope="chat")
            second = other._add_claim(text, "general", "Bob's independent observation", "phase6_curated_summary:test", .9, .9,
                                      visibility_scope="chat")
            assert first.startswith("c_") and second.startswith("c_") and first != second
            conn = provider._connect()
            assert conn.execute("SELECT origin_bot_id FROM claims WHERE id=?", (first,)).fetchone()[0] == "bot-a"
            assert conn.execute("SELECT origin_bot_id FROM claims WHERE id=?", (second,)).fetchone()[0] == "bot-b"
            evidence = conn.execute("SELECT text FROM evidence WHERE claim_id=?", (first,)).fetchall()
            assert any("Alice" in row[0] for row in evidence)
            assert not other._claim_visible(conn.execute("SELECT * FROM claims WHERE id=?", (first,)).fetchone())
            similar = text.replace("October", "November")
            third = other._add_claim(similar, "general", "Bob's near duplicate", "phase6_curated_summary:test", .9, .9,
                                     visibility_scope="chat")
            assert third != first
            assert conn.execute("SELECT origin_bot_id FROM claims WHERE id=?", (first,)).fetchone()[0] == "bot-a"
        finally:
            other._connect().close()
    finally:
        provider._connect().close()


def test_vacuum_does_not_merge_identical_claims_across_visibility(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        conn = provider._connect()
        with conn:
            conn.execute("UPDATE claims SET visibility_scope='global' WHERE id='c_atomic_a'")
            conn.execute("UPDATE claims SET claim='Shared wording across scopes', normalized_claim='Shared wording across scopes' WHERE id IN ('c_atomic_a','c_atomic_b')")
        outcome = provider._vacuum(mode="apply")
        assert not any(a.get("merge_id") == "c_atomic_b" for a in outcome["actions"])
        assert conn.execute("SELECT status FROM claims WHERE id='c_atomic_b'").fetchone()[0] == "active"
        assert conn.execute("SELECT COUNT(*) FROM evidence WHERE claim_id='c_atomic_a' AND source='memory_wiki_vacuum'").fetchone()[0] == 0
    finally:
        provider._connect().close()


def test_import_rejects_cross_scope_contradiction_and_redacts_metadata(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        conn = provider._connect()
        with conn:
            conn.execute("UPDATE claims SET visibility_scope='global' WHERE id='c_atomic_a'")
        marker = "password=VerySecretLongString123"
        item = {"id": "k_atomic_import", "claim_a": "c_atomic_a", "claim_b": "c_atomic_b",
                "reason": marker, "resolution": marker}
        try:
            provider._import({"contradictions": [item]})
        except ValueError as exc:
            assert "visibility partition" in str(exc)
        else:
            raise AssertionError("cross-scope contradiction import accepted")
        assert conn.execute("SELECT COUNT(*) FROM contradictions WHERE id=?", (item["id"],)).fetchone()[0] == 0
        with conn:
            conn.execute("UPDATE claims SET visibility_scope='chat' WHERE id='c_atomic_a'")
        provider._import({
            "claims": [
                {"id": "c_atomic_a", "claim": "Original amber lantern fact", "visibility_scope": "chat"},
                {"id": "c_atomic_b", "claim": "Original violet compass fact", "visibility_scope": "chat"},
            ],
            "contradictions": [item],
        })
        row = conn.execute("SELECT reason,resolution FROM contradictions WHERE id=?", (item["id"],)).fetchone()
        assert row is not None and marker not in row["reason"] and marker not in row["resolution"]
    finally:
        provider._connect().close()
