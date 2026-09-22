#!/usr/bin/env python3
"""Recovery regression: Code Shrinker snapshots replay from verified immutable artifacts."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_rebuild_replays_code_graph_inbox_snapshot_from_hashed_artifact() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-graph-artifact-") as tmp:
            home = Path(tmp)
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_graph_artifact_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("code-graph-artifact", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-code-graph-inbox")
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"
                inbox.mkdir(parents=True, exist_ok=True)
                marker = "CODE_GRAPH_SOURCE_SENTINEL_7ad2"
                secret = "ghp_" + "r" * 36
                event = {
                    "event_version": 2,
                    "type": "code_graph_snapshot",
                    "graph_schema_version": 1,
                    "producer": "code-shrinker",
                    "repository_id": "repo-graph-artifact",
                    "event_id": "graph-artifact-regression-event",
                    "snapshot_mode": "full",
                    "snapshot_hash": "graph-artifact-snapshot-hash",
                    "lines": [{
                        "file_path": "src/recovery.py",
                        "line_no": 1,
                        "line_id": "line:repo-graph-artifact:src/recovery.py:1",
                        "line_text": f"TOKEN = '{secret}'  # {marker}",
                    }],
                }
                (inbox / "graph-event.json").write_text(json.dumps(event), encoding="utf-8")
                live = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
                assert live["success"] is True and live["processed"] == 1, live

                journal = provider.journal_path.read_text(encoding="utf-8")
                assert marker not in journal
                assert "code_graph_inbox_artifact/v1" in journal
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] >= 1, rebuilt
                line = provider._connect().execute(
                    "SELECT line_text FROM code_graph_lines WHERE repository_id=? AND file_path=? AND line_no=1",
                    ("repo-graph-artifact", "src/recovery.py"),
                ).fetchone()
                assert line is not None and marker in str(line[0])
                # The replay uses a redacted body, but its immutable envelope
                # binds the original normalized v3 digest.  A raw producer
                # retry therefore deduplicates instead of conflicting.
                retried = module._ingest_code_graph_event(provider, event)
                assert retried["deduplicated"] is True
                changed = json.loads(json.dumps(event))
                changed["lines"][0]["line_text"] = f"TOKEN = '{secret}-changed'  # {marker}"
                with pytest.raises(ValueError, match="event_id reuse with different code graph payload"):
                    module._ingest_code_graph_event(provider, changed)
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


def test_rebuild_replays_secret_identity_inbox_without_mangling_opaque_refs() -> None:
    """Journal serialization must retain the opaque identities used by artifacts."""
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
        "MEMORY_WIKI_CODE_GRAPH_EMBED",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-graph-opaque-replay-") as tmp:
            home = Path(tmp)
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_CODE_GRAPH_EMBED": "0",
            })
            module = load_provider("memory_wiki_code_graph_opaque_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("code-graph-opaque-replay", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-secret-code-graph-inbox")
                token = "ghp_" + "a" * 36
                raw_repository_id = f"repo-{token}"
                raw_event_id = f"event-{token}"
                raw_file_path = f"src/{token}.py"
                raw_line_id = f"line:{raw_repository_id}:{raw_file_path}:1"
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"
                inbox.mkdir(parents=True, exist_ok=True)
                event = {
                    "event_version": 2,
                    "type": "code_graph_snapshot",
                    "graph_schema_version": 1,
                    "producer": "code-shrinker",
                    "repository_id": raw_repository_id,
                    "event_id": raw_event_id,
                    "snapshot_mode": "full",
                    "lines": [{
                        "file_path": raw_file_path,
                        "line_no": 1,
                        "line_id": raw_line_id,
                        "line_text": "def preserved_opaque_identity(): pass",
                    }],
                }
                (inbox / "secret-identity-event.json").write_text(
                    json.dumps(event), encoding="utf-8"
                )
                live = json.loads(provider.handle_tool_call(
                    "memory_wiki_code_graph_ingest_inbox", {"limit": 1}
                ))
                assert live["success"] is True and live["processed"] == 1, live

                opaque_repository_id = provider._code_graph_identity(raw_repository_id)
                opaque_event_id = provider._code_graph_identity(raw_event_id)
                journal_events = [
                    json.loads(line)
                    for line in provider.journal_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                after = next(
                    record for record in journal_events
                    if record.get("phase") == "after"
                    and record.get("op") == "memory_wiki_code_graph_ingest_inbox"
                )
                artifact_ref = after["result"]["recovery"]["artifacts"][0]
                assert artifact_ref["repository_id"] == opaque_repository_id
                assert artifact_ref["event_id"] == opaque_event_id
                assert "<POSSIBLE_SECRET_REDACTED>" not in json.dumps(after)
                assert token not in provider.journal_path.read_text(encoding="utf-8")

                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] >= 1, rebuilt
                context = module._code_line_context(provider, {
                    "repository_id": raw_repository_id,
                    "line_id": raw_line_id,
                    "radius": 0,
                })
                assert len(context["lines"]) == 1
                assert context["repository_id"] == opaque_repository_id
                assert token not in repr(context)
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


def test_code_claim_recovery_replays_mapped_opaque_identity() -> None:
    """A recovery artifact retains generated graph keys without journaling raw ones."""
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
        "MEMORY_WIKI_CODE_GRAPH_EMBED",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-claim-opaque-recovery-") as tmp:
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_CODE_GRAPH_EMBED": "0",
            })
            module = load_provider("memory_wiki_code_claim_opaque_recovery_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("code-claim-opaque-recovery", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-code-claim-opaque-recovery")
                token = "ghp_" + "b" * 36
                repository_id = f"repo-{token}"
                file_path = f"src/{token}.py"
                symbol_id = f"symbol-{token}"
                result = json.loads(provider.handle_tool_call("memory_wiki_code_claim_add", {
                    "claim": "Verified codebase recovery procedure preserves opaque repository identifiers.",
                    "topic": "code-intelligence",
                    "repository_id": repository_id,
                    "file_path": file_path,
                    "symbol_id": symbol_id,
                    "content_hash": "c" * 64,
                    "source_event_id": "opaque-recovery-code-claim",
                }))
                assert result.get("success") is True, result
                assert token not in provider.journal_path.read_text(encoding="utf-8")

                rebuilt = provider._rebuild_from_journal(
                    apply=True, checkpoint=checkpoint["path"],
                )
                assert rebuilt["failed"] == 0, rebuilt
                claims = provider._code_claim_query({
                    "repository_id": repository_id,
                    "file_path": file_path,
                    "symbol_id": symbol_id,
                })["claims"]
                assert len(claims) == 1
                assert claims[0]["repository_id"] == provider._code_graph_identity(repository_id)
                assert token not in repr(claims)
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


def test_legacy_inbox_artifact_rekeys_unverified_opaque_imitation() -> None:
    """A digest-valid old artifact cannot enroll a format-matching fake ID."""
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
        "MEMORY_WIKI_CODE_GRAPH_EMBED",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-legacy-inbox-opaque-") as tmp:
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_CODE_GRAPH_EMBED": "0",
            })
            module = load_provider("memory_wiki_legacy_inbox_opaque_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("legacy-inbox-opaque", hermes_home=tmp, agent_context="test")
            try:
                graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
                fake_repository_id = "redacted-graph-id-" + "c" * 64
                fake_event_id = "redacted-graph-id-" + "d" * 64
                event = {
                    "event_version": 2,
                    "type": "code_graph_snapshot",
                    "graph_schema_version": 1,
                    "producer": "code-shrinker",
                    "repository_id": fake_repository_id,
                    "event_id": fake_event_id,
                    "snapshot_mode": "full",
                    "files": [{"file_path": "src/legacy.py", "file_hash": "a" * 64}],
                }
                raw = json.dumps(event, ensure_ascii=False, sort_keys=True).encode("utf-8")
                digest = hashlib.sha256(raw).hexdigest()
                artifact_path = provider._recovery_artifact_path(
                    Path("code-graph-inbox") / f"{digest}.json"
                )
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_path.write_bytes(raw)
                # This faithfully models an artifact written before the
                # provenance-list envelope existed: byte hash/reference are
                # valid, but no exact source-side minting proof is available.
                reference = {
                    "schema": "code_recovery_reference/v1",
                    "kind": "code_graph_inbox",
                    "artifacts": [{
                        "schema": "code_graph_inbox_artifact/v1",
                        "event_type": "code_graph_snapshot",
                        "event_version": 2,
                        "producer": "code-shrinker",
                        "event_id": fake_event_id,
                        "repository_id": fake_repository_id,
                        "commit_sha": "",
                        "sha256": digest,
                        "size_bytes": len(raw),
                    }],
                }
                replayed = provider._replay_code_recovery_reference(reference)
                expected_repository_id = graph_module._opaque_graph_id_v1(fake_repository_id)
                expected_event_id = graph_module._opaque_graph_id_v1(fake_event_id)
                assert fake_repository_id not in repr(replayed)
                assert fake_event_id not in repr(replayed)
                assert provider._connect().execute(
                    "SELECT repository_id FROM code_graph_repositories"
                ).fetchone()[0] == expected_repository_id
                assert provider._connect().execute(
                    "SELECT event_id FROM code_graph_events"
                ).fetchone()[0] == expected_event_id
                assert provider._connect().execute(
                    "SELECT COUNT(*) FROM code_graph_identity_provenance "
                    "WHERE opaque_id IN (?,?) AND provenance_version=1",
                    (expected_repository_id, expected_event_id),
                ).fetchone()[0] == 2
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


def test_post_migration_legacy_inbox_artifact_uses_live_raw_identity_path() -> None:
    """A no-list legacy artifact cannot fork a raw opaque imitation after v2."""
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
        "MEMORY_WIKI_CODE_GRAPH_EMBED",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-legacy-inbox-v2-") as tmp:
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_CODE_GRAPH_EMBED": "0",
            })
            module = load_provider("memory_wiki_legacy_inbox_v2_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("legacy-inbox-v2", hermes_home=tmp, agent_context="test")
            try:
                graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
                fake_identity = "redacted-graph-id-" + "e" * 64
                # Mark the otherwise empty store as migrated before replaying a
                # pre-provenance artifact.  The artifact must now take exactly
                # the same F -> v1(F) -> v2(v1(F)) route as a live caller.
                with provider._connect() as conn:
                    graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=100)
                event = {
                    "event_version": 2,
                    "type": "code_graph_snapshot",
                    "graph_schema_version": 1,
                    "producer": "code-shrinker",
                    "repository_id": fake_identity,
                    "event_id": fake_identity,
                    "snapshot_mode": "full",
                    "files": [{"file_path": fake_identity, "file_hash": "a" * 64}],
                }
                raw = json.dumps(event, ensure_ascii=False, sort_keys=True).encode("utf-8")
                digest = hashlib.sha256(raw).hexdigest()
                artifact_path = provider._recovery_artifact_path(
                    Path("code-graph-inbox") / f"{digest}.json"
                )
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_path.write_bytes(raw)
                reference = {
                    "schema": "code_recovery_reference/v1",
                    "kind": "code_graph_inbox",
                    "artifacts": [{
                        "schema": "code_graph_inbox_artifact/v1",
                        "event_type": "code_graph_snapshot",
                        "event_version": 2,
                        "producer": "code-shrinker",
                        "event_id": fake_identity,
                        "repository_id": fake_identity,
                        "commit_sha": "",
                        "sha256": digest,
                        "size_bytes": len(raw),
                    }],
                }
                replayed = provider._replay_code_recovery_reference(reference)
                expected = graph_module._opaque_graph_id_v2(
                    graph_module._opaque_graph_id_v1(fake_identity)
                )
                assert replayed["processed"] == 1
                assert provider._code_graph_identity(fake_identity) == expected
                stored = provider._connect().execute(
                    "SELECT repository_id,event_id FROM code_graph_events"
                ).fetchone()
                assert tuple(stored) == (expected, expected)
                file_row = provider._connect().execute(
                    "SELECT file_path FROM code_graph_files WHERE repository_id=?",
                    (expected,),
                ).fetchone()
                assert file_row is not None and file_row[0] == expected
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


def test_v1_artifact_replay_fails_closed_for_later_live_payloads_after_v2_restore() -> None:
    """A genuine v1 artifact must not turn a snapshot hash into a live dedup key.

    Old artifacts contain the safe graph view but not the producer's exact
    source body.  Once a restore has advanced the ID namespace to v2, an exact
    raw retry is indistinguishable from a secret-only changed body.  Recovery
    may replay the safe artifact exactly, but live ingress must fail closed and
    require a new event ID rather than accept producer-controlled snapshot hash
    metadata as a substitute for the missing raw digest.
    """
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
        "MEMORY_WIKI_CODE_GRAPH_EMBED",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-v1-artifact-payload-replay-") as tmp:
            home = Path(tmp)
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_CODE_GRAPH_EMBED": "0",
            })
            module = load_provider("memory_wiki_v1_artifact_payload_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("v1-artifact-payload-replay", hermes_home=tmp, agent_context="test")
            try:
                graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
                secret = "ghp_" + "p" * 36
                raw_repository_id = f"repo-{secret}"
                raw_event_id = f"event-{secret}"
                event = {
                    "event_version": 2,
                    "type": "code_graph_snapshot",
                    "graph_schema_version": 1,
                    "producer": "code-shrinker",
                    "repository_id": raw_repository_id,
                    "event_id": raw_event_id,
                    "snapshot_mode": "full",
                    "snapshot_hash": "a" * 64,
                    "lines": [{
                        "file_path": "src/replay.py",
                        "line_no": 1,
                        "line_id": f"line:{raw_repository_id}:src/replay.py:1",
                        "line_text": f"TOKEN = '{secret}'",
                    }],
                }
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"
                inbox.mkdir(parents=True, exist_ok=True)
                (inbox / "v1-event.json").write_text(json.dumps(event), encoding="utf-8")
                stored = provider._drain_code_shrinker_events(limit=1)
                assert stored["processed"] == 1, stored
                # Flatten the newly captured envelope into the exact old v1
                # on-disk form: a verified redacted event plus its v1 opaque
                # provenance, but no original source-body digest.
                safe_event = provider._load_code_graph_inbox_artifact(
                    stored["recovery_artifacts"][0]
                )
                safe_bytes = json.dumps(
                    safe_event, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")
                artifact = provider._store_code_graph_inbox_artifact(safe_event, safe_bytes)
                assert artifact["opaque_id_provenance_version"] == 1
                _loaded, payload_binding = provider._load_code_graph_inbox_artifact(
                    artifact, include_payload_binding=True,
                )
                assert payload_binding == {}

                # Model a v2 restore into an otherwise empty graph store.  The
                # immutable artifact remains from the v1 writer, while the
                # current store has already crossed the one-way v2 boundary.
                conn = provider._connect()
                with conn:
                    graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=100)
                    for table in (
                        "code_graph_repositories", "code_graph_files", "code_graph_symbols",
                        "code_graph_chunks", "code_graph_lines", "code_graph_edges",
                        "code_graph_events", "code_graph_identity_provenance",
                    ):
                        conn.execute(f"DELETE FROM {table}")

                replayed = provider._replay_code_recovery_reference({
                    "schema": "code_recovery_reference/v1",
                    "kind": "code_graph_inbox",
                    "artifacts": [artifact],
                })
                assert replayed["processed"] == 1, replayed
                row = conn.execute(
                    "SELECT payload_hash,payload_hash_version FROM code_graph_events"
                ).fetchone()
                assert row is not None
                assert tuple(row) == (
                    graph_module.normalized_code_graph_event_payload_hash(safe_event), 4,
                )

                # A live caller cannot manufacture the recovery authority by
                # attaching an artifact digest of its choosing: the graph
                # writer re-opens the immutable artifact and requires its
                # exact safe event body to match before accepting v4.
                with pytest.raises(ValueError, match="requires a verified artifact"):
                    module._ingest_code_graph_event(
                        provider,
                        event,
                        recovery_payload_hash=graph_module.normalized_code_graph_event_payload_hash(safe_event),
                        recovery_payload_hash_version=4,
                        recovery_artifact_reference=artifact,
                    )

                changed = json.loads(json.dumps(event))
                changed["lines"][0]["line_text"] = f"TOKEN = '{secret}-changed'"
                for live_event in (event, changed):
                    with pytest.raises(ValueError, match="legacy recovery artifact lacks the original raw payload digest"):
                        module._ingest_code_graph_event(provider, live_event)
                assert conn.execute("SELECT COUNT(*) FROM code_graph_events").fetchone()[0] == 1
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
    test_rebuild_replays_code_graph_inbox_snapshot_from_hashed_artifact()
    test_rebuild_replays_secret_identity_inbox_without_mangling_opaque_refs()
    test_code_claim_recovery_replays_mapped_opaque_identity()
    test_legacy_inbox_artifact_rekeys_unverified_opaque_imitation()
    print("PASS test_rebuild_replays_code_graph_inbox_snapshot_from_hashed_artifact")
