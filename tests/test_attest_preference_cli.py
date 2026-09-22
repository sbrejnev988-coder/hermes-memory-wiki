"""Host-only preference attestation keeps model candidates inert until review."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
CLI = PLUGIN.parent / "tools" / "attest_preference.py"
PHRASE = "I reviewed this exact preference rule"
OWNER_FIELDS = (
    "visibility_scope", "origin_bot_id", "origin_session_id",
    "origin_chat_hash", "project_id",
)


def _provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    spec = importlib.util.spec_from_file_location(
        "memory_wiki_attest_preference_cli_test", PLUGIN,
        submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize("owner-chat", hermes_home=str(tmp_path), bot_id="owner-bot", agent_context="test")
    return module, provider


def _candidate(provider, rule: str) -> str:
    result = json.loads(provider.handle_tool_call("memory_wiki_add_preference_rule", {"rule": rule}))
    assert result["success"], result
    return result["id"]


def _run(provider, row_id: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), "--database", str(provider.db_path), "--id", row_id, *extra],
        capture_output=True, text=True, timeout=30, check=False,
    )


def test_cli_dry_run_apply_and_digest_binding(tmp_path, monkeypatch):
    module, provider = _provider(tmp_path, monkeypatch)
    rule = "Use chartreuse headings in quarterly reports"
    row_id = _candidate(provider, rule)
    try:
        before = provider._connect().execute(
            "SELECT * FROM preference_rules WHERE id=?", (row_id,),
        ).fetchone()
        original_owner = tuple(before[field] for field in OWNER_FIELDS)
        assert before["status"] == "pending"
        assert rule not in provider.system_prompt_block()

        dry_run = _run(provider, row_id)
        assert dry_run.returncode == 0, dry_run.stderr
        preview = json.loads(dry_run.stdout)
        assert preview["applied"] is False and preview["backup"] is None
        assert preview["attestation_digest"] == module.preference_attestation_digest(before)
        assert provider._connect().execute(
            "SELECT COUNT(*) FROM preference_attestations WHERE rule_id=?", (row_id,),
        ).fetchone()[0] == 0
        assert tuple(provider._connect().execute(
            "SELECT source,status,updated_at FROM preference_rules WHERE id=?", (row_id,),
        ).fetchone()) == (before["source"], before["status"], before["updated_at"])
        assert not list(provider.db_path.parent.glob("*.pre-preference-attestation-*.sqlite3"))

        wrong = _run(provider, row_id, "--apply", "--attest", "wrong phrase",
                     "--expected-digest", preview["attestation_digest"])
        assert wrong.returncode != 0
        assert provider._connect().execute(
            "SELECT COUNT(*) FROM preference_attestations WHERE rule_id=?", (row_id,),
        ).fetchone()[0] == 0

        applied = _run(provider, row_id, "--apply", "--attest", PHRASE,
                       "--expected-digest", preview["attestation_digest"])
        assert applied.returncode == 0, applied.stderr
        result = json.loads(applied.stdout)
        backup = Path(result["backup"])
        assert backup.is_file()
        assert result["attestation_digest"] == preview["attestation_digest"]
        with closing(sqlite3.connect(backup)) as backup_conn:
            assert backup_conn.execute(
                "SELECT source,status FROM preference_rules WHERE id=?", (row_id,),
            ).fetchone() == ("model_candidate", "pending")
            assert backup_conn.execute(
                "SELECT COUNT(*) FROM preference_attestations WHERE rule_id=?", (row_id,),
            ).fetchone()[0] == 0
        after = provider._connect().execute(
            "SELECT * FROM preference_rules WHERE id=?", (row_id,),
        ).fetchone()
        assert (after["source"], after["status"]) == ("host_attested:user", "active")
        assert tuple(after[field] for field in OWNER_FIELDS) == original_owner
        attestation = provider._connect().execute(
            "SELECT * FROM preference_attestations WHERE rule_id=?", (row_id,),
        ).fetchone()
        assert attestation["rule_digest"] == module.preference_attestation_digest(after)
        assert rule in provider.system_prompt_block()

        changed_rule = "Use magenta headings in quarterly reports"
        with provider._connect() as conn:
            conn.execute("UPDATE preference_rules SET rule=? WHERE id=?", (changed_rule, row_id))
        prompt = provider.system_prompt_block()
        assert rule not in prompt and changed_rule not in prompt
    finally:
        provider._conn.close()


def test_cli_rejects_legacy_and_missing_owner(tmp_path, monkeypatch):
    _, provider = _provider(tmp_path, monkeypatch)
    try:
        legacy_id = _candidate(provider, "Use indigo tables")
        unowned_id = _candidate(provider, "Use umber tables")
        with provider._connect() as conn:
            conn.execute(
                "UPDATE preference_rules SET visibility_scope='legacy' WHERE id=?", (legacy_id,),
            )
            conn.execute(
                "UPDATE preference_rules SET origin_chat_hash='' WHERE id=?", (unowned_id,),
            )
        for row_id in (legacy_id, unowned_id):
            result = _run(provider, row_id, "--apply", "--attest", PHRASE,
                          "--expected-digest", "0" * 64)
            assert result.returncode != 0
            assert provider._connect().execute(
                "SELECT COUNT(*) FROM preference_attestations WHERE rule_id=?", (row_id,),
            ).fetchone()[0] == 0
        assert not list(provider.db_path.parent.glob("*.pre-preference-attestation-*.sqlite3"))
    finally:
        provider._conn.close()


def test_cli_rejects_stale_review_after_model_changes_priority(tmp_path, monkeypatch):
    _, provider = _provider(tmp_path, monkeypatch)
    rule = "Use cerulean headings in status reports"
    row_id = _candidate(provider, rule)
    try:
        preview = _run(provider, row_id)
        assert preview.returncode == 0, preview.stderr
        digest = json.loads(preview.stdout)["attestation_digest"]
        revised = json.loads(provider.handle_tool_call(
            "memory_wiki_add_preference_rule", {"rule": rule, "priority": 240},
        ))
        # The current model tool blocks edits to existing candidates. Emulate
        # a historical/concurrent row change to verify the CLI's independent
        # review token still catches it.
        assert not revised.get("success", False), revised
        with provider._connect() as conn:
            conn.execute("UPDATE preference_rules SET priority=240 WHERE id=?", (row_id,))
        assert provider._connect().execute(
            "SELECT priority FROM preference_rules WHERE id=?", (row_id,),
        ).fetchone()[0] == 240

        stale = _run(provider, row_id, "--apply", "--attest", PHRASE,
                     "--expected-digest", digest)
        assert stale.returncode != 0
        assert "review it again" in stale.stderr
        assert provider._connect().execute(
            "SELECT COUNT(*) FROM preference_attestations WHERE rule_id=?", (row_id,),
        ).fetchone()[0] == 0
        assert provider._connect().execute(
            "SELECT status FROM preference_rules WHERE id=?", (row_id,),
        ).fetchone()[0] == "pending"
        assert rule not in provider.system_prompt_block()
        assert not list(provider.db_path.parent.glob("*.pre-preference-attestation-*.sqlite3"))
    finally:
        provider._conn.close()
