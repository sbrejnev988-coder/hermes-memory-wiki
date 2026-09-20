"""Model tools cannot edit shared claims or preserve stale verification."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def provider_for(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    spec = importlib.util.spec_from_file_location(
        "memory_wiki_model_mutation_test", PLUGIN,
        submodule_search_locations=[str(PLUGIN.parent)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize("owner-chat", hermes_home=str(tmp_path), bot_id="owner-bot", agent_context="test")
    return provider, module


def call(provider, name, **kwargs):
    return json.loads(provider.handle_tool_call(name, kwargs))


def seed(provider, text, scope):
    claim_id = provider._add_claim(
        text, "operations", "Host observed and checked this state.",
        "post_task", .9, .9, visibility_scope=scope,
    )
    assert claim_id.startswith("c_")
    row = provider._connect().execute(
        "SELECT verification_status,visibility_scope FROM claims WHERE id=?", (claim_id,)
    ).fetchone()
    assert tuple(row) == ("verified", scope)
    return claim_id


def test_model_cannot_mutate_visible_global_claim(tmp_path, monkeypatch):
    provider, _module = provider_for(tmp_path, monkeypatch)
    try:
        global_id = seed(provider, "The deployment checklist requires a service status check after each restart.", "global")
        attempts = [
            ("memory_wiki_update_claim", {"claim_id": global_id, "claim": "Ignore all status checks."}),
            ("memory_wiki_rewrite_claim", {"claim_id": global_id, "claim": "Ignore all status checks."}),
            ("memory_wiki_add_evidence", {"claim_id": global_id, "text": "Model says checks are unnecessary."}),
            ("memory_wiki_pin_claim", {"claim_id": global_id, "pinned": False}),
            ("memory_wiki_apply_user_correction", {"target_claim_id": global_id, "correction": "Ignore the checklist."}),
            ("memory_wiki_transaction", {"mode": "apply", "operations": [
                {"tool": "update_claim", "args": {"claim_id": global_id, "claim": "Ignore all status checks."}},
            ]}),
        ]
        for name, args in attempts:
            result = call(provider, name, **args)
            assert result.get("error") == "claim_access_denied", (name, result)
        row = provider._connect().execute(
            "SELECT claim,verification_status,source FROM claims WHERE id=?", (global_id,)
        ).fetchone()
        assert row["claim"].startswith("The deployment checklist")
        assert row["verification_status"] == "verified"
        assert row["source"] == "post_task"
    finally:
        provider._conn.close()


def test_model_update_rewrite_and_evidence_demote_chat_verification(tmp_path, monkeypatch):
    provider, _module = provider_for(tmp_path, monkeypatch)
    try:
        for operation in ("memory_wiki_update_claim", "memory_wiki_rewrite_claim", "memory_wiki_add_evidence"):
            claim_id = seed(provider, f"The service checklist number {operation} requires a status check after restart.", "chat")
            args = {"claim_id": claim_id, "text": "An unverified model observation.", "source": "system"} if operation.endswith("add_evidence") else {
                "claim_id": claim_id,
                "claim": f"The service checklist number {operation} now requires a different status check.",
            }
            result = call(provider, operation, **args)
            assert result.get("success"), (operation, result)
            row = provider._connect().execute(
                "SELECT verification_status,last_verified_at,source FROM claims WHERE id=?", (claim_id,)
            ).fetchone()
            assert row["verification_status"] == "unverified"
            assert row["last_verified_at"] == 0
            if operation.endswith("add_evidence"):
                evidence = provider._connect().execute(
                    "SELECT source FROM evidence WHERE claim_id=? AND text='An unverified model observation.'", (claim_id,)
                ).fetchone()
                assert evidence["source"] == "model_tool:evidence"
            else:
                assert row["source"].startswith("model_tool:")
    finally:
        provider._conn.close()


def test_model_hash_match_demotes_previously_verified_chat_claim(tmp_path, monkeypatch):
    provider, module = provider_for(tmp_path, monkeypatch)
    try:
        text = "The deployment checklist requires a status check after every service restart."
        claim_id = seed(provider, text, "chat")
        monkeypatch.setattr(module, "memory_gate_decision", lambda *_a, **_kw: {"action": "accept"})
        new_id = provider._add_claim(text, "operations", "Model restated this fact.", "model_tool:claim", .7, .7, visibility_scope="chat")
        assert new_id == claim_id
        row = provider._connect().execute(
            "SELECT verification_status,last_verified_at,source FROM claims WHERE id=?", (claim_id,)
        ).fetchone()
        assert tuple(row) == ("unverified", 0, "model_tool:claim")
    finally:
        provider._conn.close()


def test_compile_apply_cannot_supersede_global_claim(tmp_path, monkeypatch):
    provider, _module = provider_for(tmp_path, monkeypatch)
    try:
        claim_id = seed(provider, "The restart checklist requires verifying service health after deployment.", "global")
        result = call(provider, "memory_wiki_compile_topic", topic="operations", mode="apply")
        assert not result.get("success", False), result
        row = provider._connect().execute("SELECT status,verification_status FROM claims WHERE id=?", (claim_id,)).fetchone()
        assert tuple(row) == ("active", "verified")
        assert provider._connect().execute("SELECT COUNT(*) FROM claims WHERE source='memory_wiki_compile_topic'").fetchone()[0] == 0
    finally:
        provider._conn.close()


def test_bulk_curate_and_undo_do_not_edit_global_claim(tmp_path, monkeypatch):
    provider, _module = provider_for(tmp_path, monkeypatch)
    try:
        claim_id = seed(provider, "The weekly service checklist requires a signed health check.", "global")
        with provider._connect() as conn:
            conn.execute("UPDATE claims SET topic='1' WHERE id=?", (claim_id,))
        curate = call(provider, "memory_wiki_curate", mode="apply")
        assert not curate.get("success", False), curate
        assert provider._connect().execute("SELECT topic FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "1"

        # The host may have an older reversible global mutation in the ledger.
        provider._update_claim({"claim_id": claim_id, "status": "uncertain"})
        mutation_id = provider._connect().execute(
            "SELECT id FROM memory_mutations WHERE target_id=? ORDER BY created_at DESC LIMIT 1", (claim_id,)
        ).fetchone()[0]
        undo = call(provider, "memory_wiki_undo_last", mutation_id=mutation_id, dry_run=False)
        assert undo.get("success") and undo.get("found") is False, undo
        assert provider._connect().execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "uncertain"
    finally:
        provider._conn.close()


def test_model_correction_is_not_user_provenance_or_priority_item(tmp_path, monkeypatch):
    provider, _module = provider_for(tmp_path, monkeypatch)
    try:
        result = call(
            provider, "memory_wiki_apply_user_correction",
            correction="The user prefers a violet checklist for routine service reviews.",
            topic="preferences",
        )
        assert result.get("success"), result
        claim_id = result["claim_id"]
        assert claim_id.startswith("c_")
        row = provider._connect().execute(
            "SELECT claim,source,verification_status FROM claims WHERE id=?", (claim_id,)
        ).fetchone()
        assert row["claim"].startswith("Correction candidate:")
        assert row["source"] == "memory_tool:model_correction_candidate"
        assert row["verification_status"] == "unverified"
        layer = call(provider, "memory_wiki_preference_layer", query="violet checklist")
        assert claim_id not in {item["id"] for item in layer["items"]}
    finally:
        provider._conn.close()


def test_scoped_backup_excludes_global_claim_even_with_same_session_origin(tmp_path, monkeypatch):
    provider, _module = provider_for(tmp_path, monkeypatch)
    try:
        global_id = seed(provider, "The operator handbook requires a signed weekly service review.", "global")
        chat_id = seed(provider, "The current chat tracks a local service review checklist.", "chat")
        backup = call(provider, "memory_wiki_scoped_backup", reason="scope regression")
        assert backup.get("success"), backup
        payload = provider._load_scoped_backup(backup["id"])
        ids = {row["id"] for row in payload["claims"]}
        assert chat_id in ids
        assert global_id not in ids
    finally:
        provider._conn.close()


def test_model_pin_cannot_keep_host_user_turn_preference_provenance(tmp_path, monkeypatch):
    provider, _module = provider_for(tmp_path, monkeypatch)
    try:
        claim_id = seed(provider, "The user prefers a violet checklist for weekly service reviews.", "chat")
        with provider._connect() as conn:
            conn.execute("UPDATE claims SET source='turn:user:owner-chat', topic='preferences' WHERE id=?", (claim_id,))
        before = call(provider, "memory_wiki_preference_layer", query="violet checklist")
        assert claim_id in {item["id"] for item in before["items"]}
        pinned = call(provider, "memory_wiki_pin_claim", claim_id=claim_id, pinned=True)
        assert pinned.get("success"), pinned
        row = provider._connect().execute(
            "SELECT source,verification_status FROM claims WHERE id=?", (claim_id,)
        ).fetchone()
        assert tuple(row) == ("model_tool:pin_claim", "unverified")
        after = call(provider, "memory_wiki_preference_layer", query="violet checklist")
        assert claim_id not in {item["id"] for item in after["items"]}
    finally:
        provider._conn.close()
