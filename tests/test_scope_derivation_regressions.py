"""Bulk writes and retrieval accounting must preserve caller visibility."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _provider(tmp_path, monkeypatch, *, bot="bot-a", session="session-a"):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    name = "memory_wiki_scope_derivation_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize(session, hermes_home=str(tmp_path), bot_id=bot, agent_context="test")
    return provider, module


def _seed(provider, module, cid, text, scope="chat", *, bot=None, session=None, digest=None):
    bot = bot or provider.bot_id
    session = session or provider.session_id
    with provider._connect() as conn:
        conn.execute(
            """INSERT INTO claims(id,claim,normalized_claim,topic,status,confidence,salience,source,evidence,
               created_at,updated_at,freshness_at,hash,scope,visibility_scope,origin_bot_id,
               origin_session_id,origin_chat_hash,quality,risk,quarantined_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, text, text, "general", "active", .8, .8, "test", "", module.now(),
             module.now(), module.now(), digest or cid, "global", scope, bot, session,
             provider._chat_hash(session), .9, "low", 0),
        )


def test_curate_does_not_merge_global_and_chat_duplicates(tmp_path, monkeypatch):
    provider, module = _provider(tmp_path, monkeypatch)
    sentence = "Amber lantern calibration records require signed weekly checks by operators"
    _seed(provider, module, "c_global", sentence, "global")
    _seed(provider, module, "c_chat", sentence, "chat")
    outcome = provider._curate(mode="apply")
    assert not any(a["action"] == "merge_duplicate" for a in outcome["actions"])
    assert provider._connect().execute("SELECT status FROM claims WHERE id='c_chat'").fetchone()[0] == "active"


def test_federation_cannot_update_foreign_hash_match(tmp_path, monkeypatch):
    provider, module = _provider(tmp_path, monkeypatch, bot="bot-b")
    sentence = "Amber lantern calibration records require signed weekly checks by operators"
    digest = module.sha(f"visibility:chat:bot-b:{provider._chat_hash('session-a')}\0{sentence.lower()}")
    _seed(provider, module, "c_foreign", sentence, "chat", bot="bot-a", digest=digest)
    before = dict(provider._connect().execute("SELECT * FROM claims WHERE id='c_foreign'").fetchone())
    outcome = provider._federate_merge(json.dumps({"claims": [{"claim": sentence, "evidence": "private incoming note", "confidence": .99, "updated_at": module.now() + 200}]}))
    after = dict(provider._connect().execute("SELECT * FROM claims WHERE id='c_foreign'").fetchone())
    assert outcome["merged"] == 0 and outcome["conflicts"] == 1
    assert after == before
    created = provider._federate_merge(json.dumps({"claims": [{"claim": "A new federated amber lantern fact belongs to this chat", "evidence": "source note"}]}))
    assert created["merged"] == 1 and created["conflicts"] == 0, created
    new_id = created["details"][0]["id"]
    row = provider._connect().execute("SELECT visibility_scope,origin_bot_id,origin_session_id FROM claims WHERE id=?", (new_id,)).fetchone()
    assert tuple(row) == ("chat", "bot-b", "session-a")


def test_federation_rolls_back_row_if_mutation_log_fails(tmp_path, monkeypatch):
    provider, _ = _provider(tmp_path, monkeypatch)
    text = "Federated amber lantern maintenance requires a signed backup record"
    def fail_log(*args, **kwargs):
        raise RuntimeError("simulated mutation failure")
    monkeypatch.setattr(provider, "_record_mutation", fail_log)
    outcome = provider._federate_merge(json.dumps({"claims": [{"claim": text}]}))
    assert outcome["merged"] == 0 and outcome["conflicts"] == 1
    assert provider._connect().execute("SELECT count(*) FROM claims WHERE claim=?", (text,)).fetchone()[0] == 0


def test_private_correction_keeps_target_partition(tmp_path, monkeypatch):
    provider, module = _provider(tmp_path, monkeypatch)
    _seed(provider, module, "c_private", "Amber lantern calibration occurs weekly", "private")
    outcome = provider._apply_user_correction({
        "target_claim_id": "c_private",
        "correction": "Amber lantern calibration occurs every two weeks instead of weekly",
        "topic": "equipment",
    })
    assert outcome["updated_old_claims"] == ["c_private"]
    conn = provider._connect()
    corrected = conn.execute("SELECT visibility_scope,origin_bot_id,origin_session_id FROM claims WHERE id=?", (outcome["claim_id"],)).fetchone()
    assert tuple(corrected) == ("private", "bot-a", "session-a")
    assert conn.execute("SELECT status FROM claims WHERE id='c_private'").fetchone()[0] == "superseded"


def test_untargeted_correction_cannot_widen_to_similar_global_claim(tmp_path, monkeypatch):
    provider, module = _provider(tmp_path, monkeypatch)
    _seed(provider, module, "c_global", "Original amber lantern fact", "global")
    outcome = provider._apply_user_correction({
        "correction": "Original amber lantern fact is linked to my private willowcrest cabin",
    })
    assert outcome["updated_old_claims"] == []
    conn = provider._connect()
    assert conn.execute("SELECT status FROM claims WHERE id='c_global'").fetchone()[0] == "active"
    row = conn.execute("SELECT visibility_scope,origin_bot_id,origin_session_id FROM claims WHERE id=?", (outcome["claim_id"],)).fetchone()
    assert tuple(row) == ("chat", "bot-a", "session-a")


def test_correction_rolls_back_target_status_if_new_claim_fails(tmp_path, monkeypatch):
    provider, module = _provider(tmp_path, monkeypatch)
    _seed(provider, module, "c_private", "Amber lantern calibration occurs weekly", "private")
    def fail_insert(*args, **kwargs):
        raise RuntimeError("simulated claim insert failure")
    monkeypatch.setattr(provider, "_add_claim_tx", fail_insert)
    with pytest.raises(RuntimeError, match="simulated claim insert failure"):
        provider._apply_user_correction({
            "target_claim_id": "c_private",
            "correction": "Amber lantern calibration occurs every two weeks instead of weekly",
        })
    assert provider._connect().execute("SELECT status FROM claims WHERE id='c_private'").fetchone()[0] == "active"


def test_import_rebinds_new_rows_and_rejects_global_id_update(tmp_path, monkeypatch):
    provider, module = _provider(tmp_path, monkeypatch)
    _seed(provider, module, "c_global", "Published amber lantern policy applies to all operators", "global")
    with pytest.raises(ValueError, match="outside the active scope"):
        provider._import({"claims": [{"id": "c_global", "claim": "Secret chat detail replaces global policy"}]})
    assert provider._connect().execute("SELECT claim FROM claims WHERE id='c_global'").fetchone()[0] == "Published amber lantern policy applies to all operators"
    provider._import({"claims": [{"id": "c_new_private", "claim": "Private amber lantern maintenance plan", "visibility_scope": "private", "origin_bot_id": "bot-foreign"}]})
    row = provider._connect().execute("SELECT visibility_scope,origin_bot_id,origin_session_id FROM claims WHERE id='c_new_private'").fetchone()
    assert tuple(row) == ("private", "bot-a", "session-a")


def test_import_cannot_append_evidence_or_contradiction_to_global_claim(tmp_path, monkeypatch):
    provider, module = _provider(tmp_path, monkeypatch)
    _seed(provider, module, "c_global", "Published amber lantern policy applies to all operators", "global")
    with pytest.raises(ValueError, match="evidence must refer"):
        provider._import({
            "claims": [{"id": "c_transient", "claim": "Private willowcrest detail belongs to this chat"}],
            "evidence": [{"claim_id": "c_global", "text": "Private willowcrest detail"}],
        })
    assert provider._connect().execute("SELECT count(*) FROM claims WHERE id='c_transient'").fetchone()[0] == 0
    assert provider._connect().execute("SELECT count(*) FROM evidence WHERE claim_id='c_global'").fetchone()[0] == 0
    with pytest.raises(ValueError, match="visibility partition"):
        provider._import({
            "claims": [{"id": "c_transient", "claim": "Private willowcrest detail belongs to this chat"}],
            "contradictions": [{"id": "k_cross", "claim_a": "c_transient", "claim_b": "c_global", "reason": "Private willowcrest detail"}],
        })
    assert provider._connect().execute("SELECT count(*) FROM contradictions WHERE id='k_cross'").fetchone()[0] == 0


def test_bundle_import_does_not_publish_private_material(tmp_path, monkeypatch):
    provider, _ = _provider(tmp_path, monkeypatch)
    outcome = provider._import_bundle({"mode": "apply", "payload": {
        "format": "memory-wiki-sync-bundle-v1",
        "claims": [{"claim": "User prefers a private amber lantern maintenance backup every Sunday", "visibility_scope": "private"}],
    }})
    assert outcome["counts"]["claims"] == 1
    row = provider._connect().execute("SELECT visibility_scope,origin_bot_id,origin_session_id FROM claims WHERE id=?", (outcome["created_claims"][0],)).fetchone()
    assert tuple(row) == ("private", "bot-a", "session-a")


def test_bundle_import_reports_review_queue_separately(tmp_path, monkeypatch):
    provider, _ = _provider(tmp_path, monkeypatch)
    outcome = provider._import_bundle({"mode": "apply", "payload": {
        "format": "memory-wiki-sync-bundle-v1",
        "claims": [{"claim": "Amber lantern", "visibility_scope": "private"}],
    }})
    assert outcome["counts"].get("claims", 0) == 0
    assert outcome["counts"]["review_queued"] == 1
    assert outcome["created_claims"] == [] and len(outcome["queued_reviews"]) == 1
    row = provider._connect().execute("SELECT visibility_scope,origin_bot_id FROM review_queue WHERE id=?", (outcome["queued_reviews"][0],)).fetchone()
    assert tuple(row) == ("private", "bot-a")


def test_recall_query_is_never_exposed_and_legacy_events_are_scrubbed(tmp_path, monkeypatch):
    provider, module = _provider(tmp_path, monkeypatch)
    _seed(provider, module, "c_global", "Amber lantern calibration records require signed weekly checks by operators", "global")
    marker = "private-willowcrest-query"
    provider._record_prefetch_rows(marker, [{"id": "c_global", "score": 1.0}])
    assert provider._connect().execute("SELECT query FROM recall_events WHERE claim_id='c_global'").fetchone()[0] == ""
    provider._search("amber lantern private-willowcrest-query", limit=5, retrieval_mode="fts")
    assert all(r[0] == "" for r in provider._connect().execute("SELECT query FROM recall_events WHERE claim_id='c_global'"))
    with provider._connect() as conn:
        conn.execute("INSERT INTO recall_events(id,claim_id,query,score,used,created_at) VALUES(?,?,?,?,?,?)",
                     ("re_legacy", "c_global", marker, 1.0, -1, module.now()))
    other, _ = _provider(tmp_path, monkeypatch, bot="bot-b", session="session-b")
    assert marker not in json.dumps(other._why_believe("c_global"))
    assert other._connect().execute("SELECT query FROM recall_events WHERE id='re_legacy'").fetchone()[0] == ""
