#!/usr/bin/env python3
"""Regression: journal checkpoints include durable code and document graph state."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
EXPECTED_TABLES = {
    "code_claim_metadata",
    "code_graph_repositories",
    "code_graph_files",
    "code_graph_symbols",
    "code_graph_chunks",
    "code_graph_lines",
    "code_graph_edges",
    "code_graph_events",
    "code_graph_identity_provenance",
    "code_graph_identity_migrations",
    "integration_events",
    "patch_outcomes",
    "document_graph_meta",
    "document_sources",
    "document_revisions",
    "document_units",
    "document_chunks",
    "document_edges",
    "document_events",
}


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_checkpoint_includes_durable_code_and_document_graph_tables() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-checkpoint-graphs-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_checkpoint_graphs_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("checkpoint-graphs-test", hermes_home=tmp, agent_context="test")
            try:
                content_hash = "b" * 64
                with provider._connect() as conn:
                    conn.execute(
                        """INSERT INTO claims(
                            id,claim,topic,status,confidence,salience,source,evidence,
                            created_at,updated_at,freshness_at,access_count,last_accessed,hash
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        ("c_checkpoint_hash", "Verified checkpoint hash fixture.", "tests", "active",
                         0.9, 0.9, "test", "", 1, 1, 1, 0, 0, "checkpoint-hash-fixture"),
                    )
                    conn.execute(
                        """INSERT INTO code_claim_metadata(
                            claim_id,repository_id,commit_sha,file_path,symbol_id,symbol_revision,content_hash,claim_type
                        ) VALUES(?,?,?,?,?,?,?,?)""",
                        ("c_checkpoint_hash", "repo-checkpoint", "", "src/checkpoint.py", "fixture", "", content_hash, "code_claim"),
                    )
                checkpoint = provider._journal_checkpoint("graph-coverage")
                payload = json.loads(Path(checkpoint["path"]).read_text(encoding="utf-8"))
                missing = EXPECTED_TABLES - set(payload["tables"])
                assert not missing, f"checkpoint omits durable graph tables: {sorted(missing)}"
                metadata = next(
                    row for row in payload["tables"]["code_claim_metadata"]
                    if row["claim_id"] == "c_checkpoint_hash"
                )
                assert metadata["content_hash"] == content_hash
            finally:
                if provider._conn is not None:
                    provider._conn.close()
                    provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_ordinary_claim_journal_redacts_imitated_opaque_graph_id() -> None:
    """A caller cannot opt out of redaction by copying the graph-ID format."""
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-opaque-id-claim-journal-") as tmp:
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
            })
            module = load_provider("memory_wiki_opaque_id_claim_journal_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("opaque-id-claim-journal", hermes_home=tmp, agent_context="test")
            try:
                imitation = "redacted-graph-id-" + "a" * 64
                assert provider._code_graph_identity(imitation) != imitation
                result = json.loads(provider.handle_tool_call("memory_wiki_add_claim", {
                    "claim": f"Ordinary journal regression fixture: {imitation}",
                    "topic": "tests",
                }))
                assert result["success"] is True, result
                journal = provider.journal_path.read_text(encoding="utf-8")
                assert imitation not in journal
                assert "<POSSIBLE_SECRET_REDACTED>" in journal
            finally:
                if provider._conn is not None:
                    provider._conn.close()
                    provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_checkpoint_restore_preserves_distinct_opaque_graph_identities() -> None:
    """Opaque graph keys must survive generic checkpoint redaction unchanged."""
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
        "MEMORY_WIKI_CODE_GRAPH_EMBED",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-checkpoint-opaque-graphs-") as tmp:
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_CODE_GRAPH_EMBED": "0",
            })
            module = load_provider("memory_wiki_checkpoint_opaque_graphs_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("checkpoint-opaque-graphs-test", hermes_home=tmp, agent_context="test")
            try:
                raw_repositories = [
                    "repo-ghp_" + "a" * 36,
                    "repo-ghp_" + "b" * 36,
                ]
                for index, raw_repository_id in enumerate(raw_repositories, start=1):
                    token = raw_repository_id.rsplit("-", 1)[-1]
                    module._ingest_code_graph_event(provider, {
                        "event_version": 2,
                        "type": "code_graph_snapshot",
                        "graph_schema_version": 1,
                        "producer": "code-shrinker",
                        "repository_id": raw_repository_id,
                        "event_id": f"event-{token}",
                        "snapshot_mode": "full",
                        "files": [{"file_path": f"src/{token}.py", "line_count": index}],
                    })

                checkpoint = provider._journal_checkpoint("opaque-graph-identities")
                # Creating a checkpoint is the durable v1->v2 provenance
                # boundary.  Source-side lookup must follow the aliases that
                # were just persisted, rather than retain syntax-only v1 IDs.
                opaque_repositories = {
                    provider._code_graph_identity(raw_repository_id)
                    for raw_repository_id in raw_repositories
                }
                payload = json.loads(Path(checkpoint["path"]).read_text(encoding="utf-8"))
                checkpoint_repositories = {
                    str(row["repository_id"])
                    for row in payload["tables"]["code_graph_repositories"]
                }
                assert checkpoint_repositories == opaque_repositories
                for event_row in payload["tables"]["code_graph_events"]:
                    durable_result = json.loads(event_row["stats_json"])
                    assert durable_result["repository_id"] == event_row["repository_id"]
                    assert durable_result["event_id"] == event_row["event_id"]
                assert all(
                    "<POSSIBLE_SECRET_REDACTED>" not in repository_id
                    for repository_id in checkpoint_repositories
                )

                rebuilt = provider._rebuild_from_journal(
                    apply=True, checkpoint=checkpoint["path"]
                )
                assert rebuilt["failed"] == 0, rebuilt
                for raw_repository_id in raw_repositories:
                    restored = module._code_graph_status(provider, {
                        "repository_id": raw_repository_id,
                    })
                    assert restored["totals"]["files"] == 1
                    assert restored["repositories"][0]["repository_id"] == (
                        provider._code_graph_identity(raw_repository_id)
                    )
            finally:
                if provider._conn is not None:
                    provider._conn.close()
                    provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_legacy_opaque_imitation_is_rekeyed_before_output_checkpoint_and_restore() -> None:
    """A legacy format match is never accepted as provenance on its own."""
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
        "MEMORY_WIKI_CODE_GRAPH_EMBED",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-legacy-opaque-migration-") as tmp:
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_CODE_GRAPH_EMBED": "0",
            })
            module = load_provider("memory_wiki_legacy_opaque_checkpoint_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("legacy-opaque-checkpoint", hermes_home=tmp, agent_context="test")
            try:
                graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
                raw_repository_id = "repo-ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
                legacy_repository_id = provider._code_graph_identity(raw_repository_id)
                imitation = "redacted-graph-id-" + "c" * 64
                migrated_repository_id = graph_module._opaque_graph_id_v2(legacy_repository_id)
                migrated_imitation = graph_module._opaque_graph_id_v2(imitation)
                assert legacy_repository_id != migrated_repository_id

                # Model a pre-registry database: both a genuine old v1 key and
                # an attacker-shaped opaque key occupy graph identity columns.
                with provider._connect() as conn:
                    conn.execute(
                        "INSERT INTO code_graph_repositories(repository_id,updated_at) VALUES(?,?)",
                        (legacy_repository_id, 1),
                    )
                    conn.execute(
                        "INSERT INTO code_graph_files(repository_id,file_path,updated_at) VALUES(?,?,?)",
                        (legacy_repository_id, "src/legacy.py", 1),
                    )
                    conn.execute(
                        "INSERT INTO code_graph_symbols(repository_id,symbol_id,file_path,updated_at) VALUES(?,?,?,?)",
                        (legacy_repository_id, imitation, "src/legacy.py", 1),
                    )

                # Even before maintenance mutates storage, the public boundary
                # does not return the caller-controlled token verbatim.
                public = graph_module._safe_graph_output(provider, {"symbol_id": imitation})
                assert imitation not in repr(public)
                assert public["symbol_id"] == migrated_imitation

                checkpoint = provider._journal_checkpoint("legacy-opaque-migration")
                payload = json.loads(Path(checkpoint["path"]).read_text(encoding="utf-8"))
                serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                assert legacy_repository_id not in serialized
                assert imitation not in serialized
                assert migrated_repository_id in serialized
                assert migrated_imitation in serialized

                status = module._code_graph_status(provider, {
                    "repository_id": raw_repository_id,
                })
                assert status["totals"]["files"] == 1
                assert status["repositories"][0]["repository_id"] == migrated_repository_id

                rebuilt = provider._rebuild_from_journal(
                    apply=True, checkpoint=checkpoint["path"],
                )
                assert rebuilt["failed"] == 0, rebuilt
                restored = module._code_graph_status(provider, {
                    "repository_id": raw_repository_id,
                })
                assert restored["totals"]["files"] == 1
                assert restored["repositories"][0]["repository_id"] == migrated_repository_id
            finally:
                if provider._conn is not None:
                    provider._conn.close()
                    provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_checkpoint_preserves_verified_patch_identity_json_aliases() -> None:
    """Verified v2 IDs nested in patch relation arrays survive checkpointing."""
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
        "MEMORY_WIKI_CODE_GRAPH_EMBED",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-patch-identity-checkpoint-") as tmp:
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_CODE_GRAPH_EMBED": "0",
            })
            module = load_provider("memory_wiki_patch_identity_checkpoint_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("patch-identity-checkpoint", hermes_home=tmp, agent_context="test")
            try:
                token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
                raw_repository_id = f"repo-{token}"
                raw_patch_id = f"patch-{token}"
                raw_event_id = f"event-{token}"
                raw_file_path = f"src/{token}.py"
                raw_symbol_id = f"symbol-{token}"
                graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
                v1_values = [
                    provider._code_graph_identity(value)
                    for value in (
                        raw_repository_id, raw_patch_id, raw_event_id,
                        raw_file_path, raw_symbol_id,
                    )
                ]
                v2_values = [graph_module._opaque_graph_id_v2(value) for value in v1_values]
                repository_id, patch_id, event_id, file_path, symbol_id = v2_values
                with provider._connect() as conn:
                    # Model the durable post-migration shape independently of
                    # claim-quality review policy: every value was derived
                    # from a source-side secret, then exact v2-proven.
                    module._register_code_graph_identity_provenance(
                        conn, v2_values, version=2,
                    )
                    conn.execute(
                        "INSERT INTO code_graph_identity_migrations(migration_version,completed_at) VALUES(?,?)",
                        (2, 1),
                    )
                    conn.execute(
                        "INSERT INTO claims(id,claim,topic,created_at,updated_at,freshness_at,hash) "
                        "VALUES(?,?,?,?,?,?,?)",
                        ("patch-checkpoint-claim", "Patch checkpoint fixture.", "tests", 1, 1, 1, "patch-checkpoint"),
                    )
                    conn.execute(
                        "INSERT INTO patch_outcomes("
                        "repository_id,patch_id,claim_id,outcome,new_content_hash,"
                        "changed_files_json,changed_symbols_json,source_event_id,created_at,updated_at"
                        ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            repository_id, patch_id, "patch-checkpoint-claim", "applied", "a" * 64,
                            json.dumps([file_path]), json.dumps([symbol_id]), event_id, 1, 1,
                        ),
                    )

                checkpoint = provider._journal_checkpoint("patch-identity-json")
                stored = provider._connect().execute(
                    "SELECT repository_id,patch_id,source_event_id,changed_files_json,changed_symbols_json "
                    "FROM patch_outcomes"
                ).fetchone()
                assert stored is not None
                stored_values = dict(stored)
                payload = json.loads(Path(checkpoint["path"]).read_text(encoding="utf-8"))
                saved = payload["tables"]["patch_outcomes"][0]
                assert json.loads(saved["changed_files_json"]) == json.loads(stored_values["changed_files_json"])
                assert json.loads(saved["changed_symbols_json"]) == json.loads(stored_values["changed_symbols_json"])
                assert "<POSSIBLE_SECRET_REDACTED>" not in saved["changed_files_json"]
                assert "<POSSIBLE_SECRET_REDACTED>" not in saved["changed_symbols_json"]
                assert token not in json.dumps(saved, ensure_ascii=False)
                imitation = "redacted-graph-id-" + "f" * 64
                unverified = module._checkpoint_safe_graph_identity_json(
                    "patch_outcomes", "changed_files_json", json.dumps([imitation]), provider._connect(),
                )
                assert unverified is not None
                assert imitation not in unverified
                assert "<POSSIBLE_SECRET_REDACTED>" in unverified

                rebuilt = provider._rebuild_from_journal(
                    apply=True, checkpoint=checkpoint["path"],
                )
                assert rebuilt["failed"] == 0, rebuilt
                restored = provider._connect().execute(
                    "SELECT repository_id,patch_id,source_event_id,changed_files_json,changed_symbols_json "
                    "FROM patch_outcomes"
                ).fetchone()
                assert restored is not None
                assert dict(restored) == stored_values
            finally:
                if provider._conn is not None:
                    provider._conn.close()
                    provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_checkpoint_includes_durable_code_and_document_graph_tables()
    test_ordinary_claim_journal_redacts_imitated_opaque_graph_id()
    test_checkpoint_restore_preserves_distinct_opaque_graph_identities()
    test_legacy_opaque_imitation_is_rekeyed_before_output_checkpoint_and_restore()
    test_checkpoint_preserves_verified_patch_identity_json_aliases()
    print("PASS test_checkpoint_includes_durable_code_and_document_graph_tables")
