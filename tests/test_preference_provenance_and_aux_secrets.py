"""Model-facing preference provenance and auxiliary-table secret boundaries."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    spec = importlib.util.spec_from_file_location(
        "memory_wiki_preference_provenance_test", PLUGIN,
        submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize("owner-chat", hermes_home=str(tmp_path), bot_id="owner-bot", agent_context="test")
    return provider


def _call(provider, tool_name, **kwargs):
    return json.loads(provider.handle_tool_call(tool_name, kwargs))


def test_model_preference_source_and_global_scope_are_untrusted(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        result = _call(
            provider, "memory_wiki_add_preference_rule",
            rule="Always use violet headings", source="system",
            visibility_scope="global", status="active", priority=999,
        )
        assert result["success"], result
        row = provider._connect().execute(
            "SELECT * FROM preference_rules WHERE id=?", (result["id"],)
        ).fetchone()
        assert row["visibility_scope"] == "chat"
        assert row["status"] == "pending"
        assert row["source"] == "model_candidate"
        assert "violet headings" not in provider.system_prompt_block()
        assert result["id"] not in {
            rule["id"] for rule in _call(provider, "memory_wiki_preference_layer")["rules"]
        }
        assert not result.get("claim_id")
        assert not provider._connect().execute(
            "SELECT 1 FROM claims WHERE claim LIKE '%violet headings%'"
        ).fetchone()
        bad_scope = _call(
            provider, "memory_wiki_add_preference_rule",
            rule="Use lavender headings", scope="password=scope-private-25731",
        )
        assert not bad_scope.get("success", False)
        assert not provider._connect().execute(
            "SELECT 1 FROM preference_rules WHERE rule='Use lavender headings'"
        ).fetchone()
        assert "scope-private-25731" not in provider.journal_path.read_text(encoding="utf-8")
    finally:
        provider._conn.close()


def test_model_cannot_overwrite_host_attested_preference(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        created = _call(provider, "memory_wiki_add_preference_rule", rule="Use aubergine headings")
        assert created["success"], created
        with provider._connect() as conn:
            row = conn.execute("SELECT * FROM preference_rules WHERE id=?", (created["id"],)).fetchone()
            module = sys.modules[provider.__class__.__module__]
            conn.execute(
                "UPDATE preference_rules SET source='host_attested:user',status='active' WHERE id=?",
                (created["id"],),
            )
            assert "aubergine headings" not in provider.system_prompt_block()
            conn.execute(
                "INSERT INTO preference_attestations(rule_id,rule_digest,attested_at,attested_by) VALUES(?,?,?,?)",
                (created["id"], module.preference_attestation_digest(row), 1, "host_test"),
            )
        assert "aubergine headings" in provider.system_prompt_block()
        retry = _call(
            provider, "memory_wiki_add_preference_rule", rule="Use aubergine headings",
            source="model_candidate", status="retired", priority=1,
        )
        assert not retry.get("success", False)
        row = provider._connect().execute(
            "SELECT source,status,priority FROM preference_rules WHERE id=?", (created["id"],)
        ).fetchone()
        assert row["source"] == "host_attested:user"
        assert row["status"] == "active"
        assert row["priority"] == 100
    finally:
        provider._conn.close()


def test_auxiliary_arrays_and_sources_reject_secrets_before_insert(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        secret = "password=obviously-private-74921"
        cases = [
            ("memory_wiki_post_task", {"summary": "Update service", "changed_files": [secret]}),
            ("memory_wiki_post_task", {"summary": "Update service", "backups": [secret]}),
            ("memory_wiki_post_task", {"summary": "Update service", "services": [secret]}),
            ("memory_wiki_post_task", {"summary": "Update service", "source": secret}),
            ("memory_wiki_post_task", {"summary": "Update service", "topic": secret}),
            ("memory_wiki_add_decision", {"decision": "Use local cache", "alternatives": [secret]}),
            ("memory_wiki_add_decision", {"decision": "Use local cache", "source": secret}),
            ("memory_wiki_add_decision", {"decision": "Use local cache", "topic": secret}),
        ]
        for tool_name, args in cases:
            result = _call(provider, tool_name, **args)
            assert not result.get("success", False), (tool_name, args, result)
        excessive = _call(
            provider, "memory_wiki_post_task", summary="Update service",
            changed_files=["safe.txt"] * 65,
        )
        assert not excessive.get("success", False)
        conn = provider._connect()
        assert conn.execute("SELECT COUNT(*) FROM post_task_log").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
        assert not conn.execute(
            "SELECT 1 FROM claims WHERE claim LIKE '%obviously-private-74921%'"
        ).fetchone()
        assert secret not in provider.journal_path.read_text(encoding="utf-8")
    finally:
        provider._conn.close()


def test_quoted_json_secret_fields_are_scanned_and_redacted(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        # The standalone test environment has no installed Hermes secret core.
        monkeypatch.setattr(provider, "_quarantine_secret", lambda *_args: "synthetic-quarantine")
        monkeypatch.setattr(provider, "_make_secret_index_from_raw", lambda *_args: "")
        module = sys.modules[provider.__class__.__module__]
        synthetic = "synthetic-value-271828"
        for field in (
            "password", "api_key", "token", "db_password", "auth_token",
            "openai_api_key", "dbPassword", "authToken", "jwtSecret", r"pass\u0077ord",
        ):
            raw = json.dumps({field: synthetic, "framework": "FastAPI"})
            scan = module.secret_scan(raw)
            assert scan["raw_secret"]
            assert synthetic not in scan["redacted"]
            assert json.loads(scan["redacted"])["framework"] == "FastAPI"
        for raw in (
            "{'password': 'synthetic-value-271828'}",
            r'{\"token\":\"synthetic-value-271828\"}',
            '{"api_key": 271828}',
            '{"password": "escaped\\\"synthetic-value-271828"}',
            'Project configuration contains {"token":["synthetic-value-271828"]}',
        ):
            assert module.secret_scan(raw)["raw_secret"]
            assert synthetic not in module.redact_secrets(raw)
        escaped_container = r'{\"password\":[\"synthetic-value-271828\"],\"framework\":\"FastAPI\"}'
        assert "FastAPI" in module.redact_secrets(escaped_container)
        assert module.redact_secrets(escaped_container).endswith("}")
        nested_json = json.dumps({"note": json.dumps({
            "token": ["synthetic-value-271828"], "framework": "FastAPI",
        })})
        nested_redacted = json.loads(module.redact_secrets(nested_json))
        assert json.loads(nested_redacted["note"])["framework"] == "FastAPI"
        assert synthetic not in nested_redacted["note"]
        assert not module.secret_scan('{"framework":"FastAPI","tokenizer":"qwen"}')["raw_secret"]

        result = _call(
            provider, "memory_wiki_add_claim",
            claim='Project configuration contains {"password":"synthetic-value-271828"}',
            topic="projects", evidence="Configuration was reviewed",
        )
        assert result.get("success"), result
        rows = provider._connect().execute("SELECT claim,evidence FROM claims").fetchall()
        assert rows
        assert all(synthetic not in str(value) for row in rows for value in row)
    finally:
        provider._conn.close()


def test_project_profile_stack_is_sanitized_before_persistence(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(provider, "_quarantine_secret", lambda *_args: "synthetic-quarantine")
        monkeypatch.setattr(provider, "_make_secret_index_from_raw", lambda *_args: "")
        project_id = provider.project_scope
        stack = {
            "framework": "FastAPI",
            "config": {"api_key": "synthetic-value-314159", "region": "eu"},
            "items": [{"token": "synthetic-value-271828"}, {"note": "password=synthetic-value-161803"}],
            "credential": {"unquoted_secret": 12345678},
            "dbPassword": "synthetic-value-141421",
        }
        for supplied in ({"stack": stack}, {"stack_json": json.dumps(stack)}):
            result = _call(
                provider, "memory_wiki_add_project_profile",
                project_id=project_id, purpose="Synthetic profile test", **supplied,
            )
            assert result.get("success") and result["secret_quarantined"], result
            row = provider._connect().execute(
                "SELECT stack_json FROM project_profiles WHERE project_id=?", (project_id,)
            ).fetchone()
            stored = json.loads(row["stack_json"])
            assert stored["framework"] == "FastAPI"
            assert stored["config"]["region"] == "eu"
            assert stored["config"]["api_key"] == "<SECRET_ASSIGNMENT_REDACTED>"
            assert stored["credential"] == "<SECRET_ASSIGNMENT_REDACTED>"
            assert all(synthetic not in row["stack_json"] for synthetic in (
                "synthetic-value-314159", "synthetic-value-271828", "synthetic-value-161803",
                "synthetic-value-141421",
            ))
        stored_rows = provider._connect().execute(
            "SELECT after_json FROM memory_mutations WHERE target_table='project_profiles'"
        ).fetchall()
        assert all("synthetic-value-314159" not in str(row[0]) for row in stored_rows)
        safe_stack = {"framework": "FastAPI", "tokenizer": "qwen", "nested": ["safe"]}
        safe = _call(
            provider, "memory_wiki_add_project_profile", project_id=project_id,
            purpose="Synthetic profile test", stack_json=json.dumps(safe_stack),
        )
        assert safe.get("success") and not safe["secret_quarantined"], safe
        row = provider._connect().execute(
            "SELECT stack_json FROM project_profiles WHERE project_id=?", (project_id,)
        ).fetchone()
        assert json.loads(row["stack_json"]) == safe_stack
    finally:
        provider._conn.close()


def test_secret_scrub_repairs_legacy_quoted_project_stack(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(provider, "_quarantine_secret", lambda *_args: "synthetic-quarantine")
        monkeypatch.setattr(provider, "_make_secret_index_from_raw", lambda *_args: "")
        project_id = provider.project_scope
        result = _call(
            provider, "memory_wiki_add_project_profile", project_id=project_id,
            purpose="Synthetic migration test", stack={"framework": "FastAPI"},
        )
        assert result.get("success"), result
        legacy = json.dumps({
            "framework": "FastAPI", "db_password": "synthetic-value-271828",
            "authToken": ["synthetic-value-314159"],
        })
        with provider._connect() as conn:
            conn.execute(
                "UPDATE project_profiles SET stack_json=? WHERE project_id=?", (legacy, project_id),
            )
        assert provider._scrub_secrets(apply=True, limit=200)["updated_rows"] >= 1
        row = provider._connect().execute(
            "SELECT stack_json FROM project_profiles WHERE project_id=?", (project_id,)
        ).fetchone()
        stored = json.loads(row["stack_json"])
        assert stored["framework"] == "FastAPI"
        assert "synthetic-value-271828" not in row["stack_json"]
        assert "synthetic-value-314159" not in row["stack_json"]
    finally:
        provider._conn.close()


def test_auxiliary_row_rolls_back_when_claim_write_fails(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        def fail_claim(*_args, **_kwargs):
            raise RuntimeError("injected claim write failure")

        monkeypatch.setattr(provider, "_add_claim_tx", fail_claim)
        for tool_name, args in (
            ("memory_wiki_post_task", {"summary": "Updated service configuration and verified restart"}),
            ("memory_wiki_add_decision", {
                "decision": "Use a local cache for repeatable integration tests",
                "rationale": "Avoid unnecessary external requests during the test suite",
                "source": "decision",
            }),
        ):
            result = _call(provider, tool_name, **args)
            assert not result.get("success", False), result
        conn = provider._connect()
        assert conn.execute("SELECT COUNT(*) FROM post_task_log").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
    finally:
        provider._conn.close()


def test_model_cannot_claim_curated_post_task_or_decision_source(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        operations = (
            ("memory_wiki_post_task", {
                "summary": "Updated the test service configuration and verified the restart",
                "source": "post_task",
            }, "model_tool:post_task"),
            ("memory_wiki_add_decision", {
                "decision": "Use a local cache for repeatable integration tests",
                "rationale": "Avoid external requests during the test suite",
                "source": "decision",
            }, "model_tool:decision"),
        )
        for tool_name, args, expected_source in operations:
            result = _call(provider, tool_name, **args)
            assert result.get("success"), result
            row = provider._connect().execute(
                "SELECT source,verification_status,visibility_scope FROM claims WHERE id=?",
                (result["claim_id"],),
            ).fetchone()
            assert row is not None
            assert tuple(row) == (expected_source, "unverified", "chat")
    finally:
        provider._conn.close()


def test_public_claim_routes_cannot_forge_verified_global_provenance(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        claim = "Use the local cache for repeatable integration tests because external requests vary"
        direct = _call(
            provider, "memory_wiki_add_claim", claim=claim, topic="decisions",
            source="decision", visibility_scope="global",
        )
        assert direct.get("success") and direct.get("state") == "stored", direct
        via_firewall = _call(
            provider, "memory_wiki_write_firewall",
            claim="Use local fixtures for deterministic service checks and record their outcomes",
            topic="operations", source="post_task", visibility_scope="global", mode="apply",
        )
        assert via_firewall.get("success") and via_firewall.get("claim_id", "").startswith("c_"), via_firewall
        for claim_id in (direct["id"], via_firewall["claim_id"]):
            row = provider._connect().execute(
                "SELECT source,verification_status,visibility_scope FROM claims WHERE id=?",
                (claim_id,),
            ).fetchone()
            assert tuple(row) == ("model_tool:claim", "unverified", "chat")
    finally:
        provider._conn.close()


def test_structured_model_tools_do_not_auto_verify_claims(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        project_id = provider.project_scope
        calls = (
            ("memory_wiki_add_mistake", {
                "trigger": "integration service stopped",
                "mistake": "disabled the service while running tests",
                "fix": "restored the service and reran the tests",
            }, "chat"),
            ("memory_wiki_add_task_capsule", {
                "intent": "Completed routine backup and verified the restored test database",
                "verification": "SQLite integrity check passed",
            }, "chat"),
            ("memory_wiki_add_project_profile", {
                "project_id": project_id,
                "purpose": "Provide a local workspace for repeatable integration tests",
                "verified": True,
                "last_verified_at": 9999999999,
            }, "project"),
        )
        for tool_name, args, expected_scope in calls:
            result = _call(provider, tool_name, **args)
            assert result.get("success"), result
            row = provider._connect().execute(
                "SELECT source,verification_status,visibility_scope FROM claims WHERE id=?",
                (result["claim_id"],),
            ).fetchone()
            assert row and str(row["source"]).startswith("model_tool:")
            assert row["verification_status"] == "unverified"
            assert row["visibility_scope"] == expected_scope
        profile = provider._connect().execute(
            "SELECT last_verified_at,source FROM project_profiles WHERE project_id=?", (project_id,)
        ).fetchone()
        assert tuple(profile) == (0, "model_tool:project_profile")
        foreign = _call(provider, "memory_wiki_add_project_profile", project_id="foreign-project", purpose="Leak")
        assert not foreign.get("success", False)
    finally:
        provider._conn.close()


def test_legacy_curated_source_without_host_proof_is_downgraded(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    legacy_id = provider._add_claim(
        "Decision: retain a local archive of deterministic integration results",
        "decisions", "Historical model-produced decision", "decision", .9, .9,
        visibility_scope="chat",
    )
    assert provider._connect().execute(
        "SELECT verification_status FROM claims WHERE id=?", (legacy_id,)
    ).fetchone()[0] == "verified"
    with provider._connect() as conn:
        conn.execute("DELETE FROM meta WHERE key='model_curated_provenance_downgrade_v1'")
    provider._conn.close()
    reopened = provider.__class__()
    reopened.initialize("owner-chat", hermes_home=str(tmp_path), bot_id="owner-bot", agent_context="test")
    try:
        row = reopened._connect().execute(
            "SELECT verification_status,last_verified_at FROM claims WHERE id=?", (legacy_id,)
        ).fetchone()
        assert tuple(row) == ("unverified", 0)
    finally:
        reopened._conn.close()


def test_approving_old_global_review_item_does_not_verify_or_publish_it(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        review_id = provider._enqueue_review(
            "Use a local archive for deterministic integration results",
            "decisions", "Historical candidate", "decision", "manual review",
            visibility_scope="global",
        )
        approved = _call(provider, "memory_wiki_review_queue", mode="approve", item_id=review_id)
        assert approved.get("success"), approved
        row = provider._connect().execute(
            "SELECT source,verification_status,visibility_scope FROM claims WHERE id=?",
            (approved["claim_id"],),
        ).fetchone()
        assert row and tuple(row) == ("model_tool:review_approval", "unverified", "chat")
    finally:
        provider._conn.close()


def test_import_update_revokes_old_verified_provenance(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        claim_id = provider._add_claim(
            "Decision: keep a local archive of repeatable service test results",
            "decisions", "Historical evidence", "decision", .9, .9,
            visibility_scope="chat",
        )
        assert provider._connect().execute(
            "SELECT verification_status FROM claims WHERE id=?", (claim_id,)
        ).fetchone()[0] == "verified"
        imported = _call(provider, "memory_wiki_import", payload={"claims": [{
            "id": claim_id,
            "claim": "Decision: keep a second archive of service test results",
            "topic": "decisions",
            "visibility_scope": "chat",
        }]})
        assert imported.get("success"), imported
        row = provider._connect().execute(
            "SELECT source,verification_status,last_verified_at,visibility_scope FROM claims WHERE id=?",
            (claim_id,),
        ).fetchone()
        assert tuple(row) == ("model_tool:import", "unverified", 0, "chat")
    finally:
        provider._conn.close()
