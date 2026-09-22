#!/usr/bin/env python3
"""Deterministic fault matrix for the journaled Code Shrinker inbox state machine.

The tests deliberately inject one failure at a time across the durable path:

    claim -> journal-before -> mutation -> recovery artifact -> terminal record
          -> journal-after -> checkpoint -> acknowledgement -> retry/rebuild

This is property-style coverage without a random seed or a new dependency: every
case must preserve the producer input until either a safe terminal rejection or a
replayable, acknowledged success exists.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
OP = "memory_wiki_code_graph_ingest_inbox"


def _load_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module_name: str):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "0")
    monkeypatch.setenv("MEMORY_WIKI_JOURNAL_SAFETY_CHECKPOINTS", "1")
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize(module_name, hermes_home=str(tmp_path), agent_context="test")
    # This matrix verifies journal/inbox durability, not the optional secret
    # broker.  Normal fixture IDs contain no secret material.
    provider._make_secret_index_from_raw = lambda *_args, **_kwargs: ""
    return module, provider


def _close(provider: Any) -> None:
    if provider._conn is not None:
        provider._conn.close()
        provider._conn = None


def _snapshot(event_id: str, file_stem: str) -> dict[str, Any]:
    file_path = f"src/{file_stem}.py"
    source = f"def {file_stem}(): return 'durable state machine fixture'"
    return {
        "event_version": 2,
        "type": "code_graph_snapshot",
        "graph_schema_version": 1,
        "producer": "code-shrinker",
        "repository_id": "repo-state-machine-matrix",
        "event_id": event_id,
        "snapshot_mode": "delta",
        "commit_sha": hashlib.sha1(event_id.encode()).hexdigest(),
        "files": [{
            "file_path": file_path,
            "file_hash": hashlib.sha256(source.encode()).hexdigest(),
            "language": "python",
            "line_count": 1,
        }],
        "lines": [{
            "line_id": f"line:{event_id}:1",
            "file_path": file_path,
            "line_no": 1,
            "line_text": source,
        }],
    }


def _patch_event(event_id: str, patch_id: str) -> dict[str, Any]:
    old_hash = hashlib.sha256(f"{patch_id}:old".encode()).hexdigest()
    new_hash = hashlib.sha256(f"{patch_id}:new".encode()).hexdigest()
    return {
        "event_version": 1,
        "type": "patch_applied",
        "producer": "mcp-code-shrinker",
        "event_id": event_id,
        "repository_id": "repo-state-machine-matrix",
        "patch_id": patch_id,
        "outcome": "verified applied",
        "changed_files": ["src/post_commit.py"],
        "per_file": [{
            "file_path": "src/post_commit.py",
            "old_content_hash": old_hash,
            "new_content_hash": new_hash,
        }],
        "validation_report": {"status": "passed"},
        "rollback_steps": "restore the verified previous revision",
    }


def _inbox(tmp_path: Path) -> Path:
    path = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_event(tmp_path: Path, event: dict[str, Any], name: str = "event.json") -> None:
    (_inbox(tmp_path) / name).write_text(
        json.dumps(event, ensure_ascii=False), encoding="utf-8"
    )


def _call(provider: Any, limit: int = 1) -> dict[str, Any]:
    return json.loads(provider.handle_tool_call(OP, {"limit": limit}))


def _retry_files(tmp_path: Path) -> list[Path]:
    return sorted(_inbox(tmp_path).glob("retry-jop_*.json"))


def _done_files(tmp_path: Path) -> list[Path]:
    return sorted(
        (tmp_path / "context-coordination" / "done" / "code-shrinker").glob("*.json")
    )


def _dead_files(tmp_path: Path) -> list[Path]:
    return sorted(
        (tmp_path / "context-coordination" / "dead-letter" / "code-shrinker").glob("*.json")
    )


def _graph_contains(provider: Any, file_path: str) -> bool:
    return provider._connect().execute(
        "SELECT 1 FROM code_graph_files WHERE repository_id=? AND file_path=?",
        ("repo-state-machine-matrix", file_path),
    ).fetchone() is not None


def _inject_once(
    monkeypatch: pytest.MonkeyPatch,
    owner: Any,
    attribute: str,
    should_fail: Callable[..., bool],
    error_factory: Callable[[], BaseException],
):
    original = getattr(owner, attribute)
    state = {"failed": False}

    def wrapper(*args, **kwargs):
        if not state["failed"] and should_fail(*args, **kwargs):
            state["failed"] = True
            raise error_factory()
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, attribute, wrapper)
    return original, state


@pytest.mark.parametrize(
    "fault_stage,mutation_is_durable_after_first",
    [
        ("journal_before", False),
        ("claimed_read", False),
        ("sqlite_mutation", False),
        ("recovery_artifact", True),
        ("terminal_record", True),
        ("journal_after", True),
    ],
)
def test_transient_fault_matrix_requeues_then_rebuilds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_stage: str,
    mutation_is_durable_after_first: bool,
) -> None:
    """Every transient boundary failure retains one retry and later rebuilds."""
    module, provider = _load_provider(
        tmp_path, monkeypatch, f"memory_wiki_state_matrix_{fault_stage}"
    )
    try:
        baseline = provider._journal_checkpoint(f"before-{fault_stage}")
        event = _snapshot(f"matrix-{fault_stage}", fault_stage)
        file_path = event["files"][0]["file_path"]
        _write_event(tmp_path, event)
        restore_owner: Any
        restore_attribute: str

        if fault_stage in {"journal_before", "journal_after"}:
            phase = "before" if fault_stage == "journal_before" else "after"
            original, tripped = _inject_once(
                monkeypatch,
                provider,
                "_append_journal_event",
                lambda op, _payload, **kwargs: op == OP and kwargs.get("phase") == phase,
                lambda: OSError(f"injected {fault_stage} failure"),
            )
            restore_owner = provider
            restore_attribute = "_append_journal_event"
        elif fault_stage == "claimed_read":
            original = Path.read_bytes
            tripped = {"failed": False}

            def fail_claim_read_once(path: Path) -> bytes:
                if not tripped["failed"] and ".code-shrinker.processing." in path.name:
                    tripped["failed"] = True
                    raise OSError("injected claimed event read failure")
                return original(path)

            monkeypatch.setattr(Path, "read_bytes", fail_claim_read_once)
            restore_owner = Path
            restore_attribute = "read_bytes"
        elif fault_stage == "sqlite_mutation":
            original, tripped = _inject_once(
                monkeypatch,
                module,
                "_ingest_code_graph_event",
                lambda *_args, **_kwargs: True,
                lambda: sqlite3.OperationalError("injected transient database failure"),
            )
            restore_owner = module
            restore_attribute = "_ingest_code_graph_event"
        elif fault_stage == "recovery_artifact":
            original, tripped = _inject_once(
                monkeypatch,
                provider,
                "_store_code_graph_inbox_artifact",
                lambda *_args, **_kwargs: True,
                lambda: OSError("injected recovery artifact failure"),
            )
            restore_owner = provider
            restore_attribute = "_store_code_graph_inbox_artifact"
        else:
            done_dir = tmp_path / "context-coordination" / "done" / "code-shrinker"
            original, tripped = _inject_once(
                monkeypatch,
                module,
                "atomic_write",
                lambda path, *_args, **_kwargs: Path(path).parent == done_dir,
                lambda: OSError("injected terminal record failure"),
            )
            restore_owner = module
            restore_attribute = "atomic_write"

        # A limit larger than one proves the wrapper stops after the failed
        # claim instead of immediately spinning on its freshly requeued copy.
        first = _call(provider, limit=5)
        assert tripped["failed"], f"fault stage was not reached: {fault_stage}"
        assert first["success"] is False, first
        assert first["failed"] == 1, first
        assert first["retryable"] == 1, first
        assert first["retryable_unrequeued"] == 0, first
        assert len(_retry_files(tmp_path)) == 1
        assert not _dead_files(tmp_path)
        assert _graph_contains(provider, file_path) is mutation_is_durable_after_first
        public_failure = json.dumps(first, ensure_ascii=False)
        assert "injected" not in public_failure
        assert str(tmp_path) not in public_failure

        # A pending retry is intentionally not recoverable yet: recovery must
        # wait for the same opaque operation ID to reach a durable after record.
        pending = provider._rebuild_from_journal(
            apply=False, checkpoint=baseline["path"]
        )
        if fault_stage == "journal_before":
            assert pending["incomplete_events"] == 0, pending
        else:
            assert pending["incomplete_events"] >= 1, pending

        monkeypatch.setattr(restore_owner, restore_attribute, original)
        retried = _call(provider)
        assert retried["success"] is True, retried
        assert retried["processed"] == 1, retried
        assert retried["retryable"] == 0, retried
        assert not _retry_files(tmp_path)
        # journal-after fails after the first safe terminal record is already
        # durable; retry intentionally adds a second opaque audit record.
        assert len(_done_files(tmp_path)) == (
            2 if fault_stage == "journal_after" else 1
        )
        assert not _dead_files(tmp_path)
        assert _graph_contains(provider, file_path)
        ledger_count = provider._connect().execute(
            "SELECT COUNT(*) FROM code_graph_events WHERE event_id=?",
            (event["event_id"],),
        ).fetchone()[0]
        assert ledger_count == 1

        plan = provider._rebuild_from_journal(
            apply=False, checkpoint=baseline["path"]
        )
        assert plan["incomplete_events"] == 0, plan
        assert plan["unrecoverable_events"] == 0, plan
        assert plan["events_to_replay"] >= 1, plan
        rebuilt = provider._rebuild_from_journal(
            apply=True, checkpoint=baseline["path"]
        )
        assert rebuilt["applied"] is True, rebuilt
        assert rebuilt["failed"] == 0, rebuilt
        assert _graph_contains(provider, file_path)
    finally:
        _close(provider)


def test_checkpoint_failure_keeps_durable_after_replayable_and_acknowledged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed safety checkpoint cannot erase an already-fsynced after record."""
    _module, provider = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_checkpoint"
    )
    try:
        baseline = provider._journal_checkpoint("before-checkpoint-fault")
        event = _snapshot("matrix-checkpoint", "checkpoint")
        file_path = event["files"][0]["file_path"]
        _write_event(tmp_path, event)
        original, tripped = _inject_once(
            monkeypatch,
            provider,
            "_journal_checkpoint",
            lambda name="", *_args, **_kwargs: str(name).startswith("after-"),
            lambda: OSError("injected safety checkpoint failure"),
        )

        result = _call(provider)
        assert tripped["failed"]
        monkeypatch.setattr(provider, "_journal_checkpoint", original)
        assert result["success"] is True and result["processed"] == 1, result
        assert not _retry_files(tmp_path)
        assert len(_done_files(tmp_path)) == 1
        assert _graph_contains(provider, file_path)
        after = [
            event for event in provider._iter_journal_events()
            if event.get("op") == OP and event.get("phase") == "after"
        ]
        assert len(after) == 1

        plan = provider._rebuild_from_journal(
            apply=False, checkpoint=baseline["path"]
        )
        assert plan["incomplete_events"] == 0, plan
        assert plan["events_to_replay"] == 1, plan
        rebuilt = provider._rebuild_from_journal(
            apply=True, checkpoint=baseline["path"]
        )
        assert rebuilt["failed"] == 0 and _graph_contains(provider, file_path), rebuilt
    finally:
        _close(provider)


def test_acknowledgement_failure_requeues_same_operation_and_retry_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unlink failure after journal-after retains a stable-ID retry."""
    _module, provider = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_ack"
    )
    try:
        baseline = provider._journal_checkpoint("before-ack-fault")
        event = _snapshot("matrix-ack", "ack")
        file_path = event["files"][0]["file_path"]
        _write_event(tmp_path, event)
        original_ack = provider._acknowledge_code_shrinker_claim
        state = {"failed": False, "operation_id": ""}

        def fail_ack_once(claimed: Path, inbox: Path, operation_id: str) -> bool:
            if not state["failed"]:
                state["failed"] = True
                state["operation_id"] = operation_id
                provider._requeue_code_shrinker_event(
                    claimed, inbox, claimed.read_bytes(), operation_id
                )
                return False
            return original_ack(claimed, inbox, operation_id)

        monkeypatch.setattr(provider, "_acknowledge_code_shrinker_claim", fail_ack_once)
        first = _call(provider)
        assert first["success"] is True and first["processed"] == 1, first
        assert first["acknowledgement_pending"] == 1, first
        retries = _retry_files(tmp_path)
        assert len(retries) == 1
        assert retries[0].name == f"retry-{state['operation_id']}.json"
        assert _graph_contains(provider, file_path)

        second = _call(provider)
        assert second["success"] is True and second["processed"] == 1, second
        assert second["deduplicated"] == 1, second
        assert not _retry_files(tmp_path)
        # The original after-record and done artifact were already durable;
        # the stable-ID retry creates another opaque terminal audit record.
        assert len(_done_files(tmp_path)) == 2
        ledger_count = provider._connect().execute(
            "SELECT COUNT(*) FROM code_graph_events WHERE event_id=?",
            (event["event_id"],),
        ).fetchone()[0]
        assert ledger_count == 1

        plan = provider._rebuild_from_journal(
            apply=False, checkpoint=baseline["path"]
        )
        assert plan["incomplete_events"] == 0, plan
        assert plan["unrecoverable_events"] == 0, plan
        rebuilt = provider._rebuild_from_journal(
            apply=True, checkpoint=baseline["path"]
        )
        assert rebuilt["failed"] == 0 and _graph_contains(provider, file_path), rebuilt
    finally:
        _close(provider)


def test_batch_failure_preserves_prior_success_and_retries_only_failed_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later artifact failure cannot roll back or orphan an earlier event."""
    _module, provider = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_batch"
    )
    try:
        baseline = provider._journal_checkpoint("before-batch-fault")
        first_event = _snapshot("matrix-batch-first", "batch_first")
        second_event = _snapshot("matrix-batch-second", "batch_second")
        _write_event(tmp_path, first_event, "00-first.json")
        _write_event(tmp_path, second_event, "01-second.json")
        original_artifact = provider._store_code_graph_inbox_artifact
        state = {"calls": 0}

        def fail_second_artifact(*args, **kwargs):
            state["calls"] += 1
            if state["calls"] == 2:
                raise OSError("injected second-event artifact failure")
            return original_artifact(*args, **kwargs)

        monkeypatch.setattr(
            provider, "_store_code_graph_inbox_artifact", fail_second_artifact
        )
        first_pass = _call(provider, limit=2)
        assert first_pass["success"] is False, first_pass
        assert first_pass["processed"] == 1, first_pass
        assert first_pass["failed"] == 1 and first_pass["retryable"] == 1, first_pass
        assert len(_done_files(tmp_path)) == 1
        assert len(_retry_files(tmp_path)) == 1
        assert _graph_contains(provider, "src/batch_first.py")
        assert _graph_contains(provider, "src/batch_second.py")

        monkeypatch.setattr(
            provider, "_store_code_graph_inbox_artifact", original_artifact
        )
        second_pass = _call(provider, limit=2)
        assert second_pass["success"] is True, second_pass
        assert second_pass["processed"] == 1 and second_pass["deduplicated"] == 1, second_pass
        assert len(_done_files(tmp_path)) == 2
        assert not _retry_files(tmp_path)

        plan = provider._rebuild_from_journal(
            apply=False, checkpoint=baseline["path"]
        )
        assert plan["incomplete_events"] == 0, plan
        assert plan["unrecoverable_events"] == 0, plan
        rebuilt = provider._rebuild_from_journal(
            apply=True, checkpoint=baseline["path"]
        )
        assert rebuilt["failed"] == 0, rebuilt
        assert _graph_contains(provider, "src/batch_first.py")
        assert _graph_contains(provider, "src/batch_second.py")
    finally:
        _close(provider)


def test_invalid_event_is_terminally_rejected_instead_of_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry policy must not turn malformed producer input into a poison loop."""
    _module, provider = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_invalid"
    )
    try:
        malformed = _snapshot("matrix-invalid", "invalid")
        malformed["commit_sha"] = "not-a-git-object"
        _write_event(tmp_path, malformed)
        result = _call(provider)
        assert result["success"] is True, result
        assert result["processed"] == 0 and result["failed"] == 1, result
        assert result["retryable"] == 0, result
        assert not _retry_files(tmp_path)
        assert len(_dead_files(tmp_path)) == 2  # redacted body + safe error metadata
        assert not _graph_contains(provider, "src/invalid.py")
    finally:
        _close(provider)


def test_empty_event_bytes_are_terminal_not_an_unreadable_claim_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real empty body remains malformed; only ``None`` means unreadable."""
    _module, provider = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_empty_body"
    )
    try:
        event_path = _inbox(tmp_path) / "empty.json"
        event_path.write_bytes(b"")
        result = _call(provider, limit=5)
        assert result["success"] is True, result
        assert result["processed"] == 0 and result["failed"] == 1, result
        assert result["retryable"] == 0, result
        assert not _retry_files(tmp_path)
        assert len(_dead_files(tmp_path)) == 2
        assert not list(_inbox(tmp_path).glob(".code-shrinker.processing.*"))
    finally:
        _close(provider)


def test_patch_post_commit_exception_is_deferred_and_rebuildable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A derived callback failure after commit cannot destroy a patch event."""
    _module, provider = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_patch_post_commit"
    )
    try:
        baseline = provider._journal_checkpoint("before-patch-post-commit")
        event = _patch_event("matrix-patch-post-commit", "patch-post-commit")
        _write_event(tmp_path, event)
        secret_error = "ghp_" + "z" * 36
        original_after = provider._after_claim_commit
        original_apply = provider._apply_code_shrinker_patch_event
        captured: list[dict[str, Any]] = []

        def fail_after_claim_commit(*_args, **_kwargs):
            raise RuntimeError(f"injected callback failure {secret_error}")

        def capture_apply(*args, **kwargs):
            result = original_apply(*args, **kwargs)
            captured.append(result)
            return result

        monkeypatch.setattr(provider, "_after_claim_commit", fail_after_claim_commit)
        monkeypatch.setattr(provider, "_apply_code_shrinker_patch_event", capture_apply)
        result = _call(provider)
        assert result["success"] is True and result["processed"] == 1, result
        assert result["failed"] == 0 and result["retryable"] == 0, result
        assert captured
        deferred = captured[0]["outcome"]
        assert deferred["status"] == "committed_with_deferred_failures"
        assert deferred["post_commit_failures"] == [{
            "operation": "post_commit_callback",
            "error": "RuntimeError",
        }]
        assert secret_error not in repr(result)
        assert secret_error not in repr(captured)
        assert len(_done_files(tmp_path)) == 1
        assert not _dead_files(tmp_path) and not _retry_files(tmp_path)
        conn = provider._connect()
        assert conn.execute(
            "SELECT 1 FROM patch_outcomes WHERE patch_id=?",
            (event["patch_id"],),
        ).fetchone()

        durable_text = provider.journal_path.read_text(encoding="utf-8")
        durable_text += "".join(
            path.read_text(encoding="utf-8") for path in _done_files(tmp_path)
        )
        assert secret_error not in durable_text
        monkeypatch.setattr(provider, "_after_claim_commit", original_after)
        monkeypatch.setattr(
            provider, "_apply_code_shrinker_patch_event", original_apply
        )
        plan = provider._rebuild_from_journal(
            apply=False, checkpoint=baseline["path"]
        )
        assert plan["incomplete_events"] == 0, plan
        rebuilt = provider._rebuild_from_journal(
            apply=True, checkpoint=baseline["path"]
        )
        assert rebuilt["failed"] == 0, rebuilt
        assert provider._connect().execute(
            "SELECT 1 FROM patch_outcomes WHERE patch_id=?",
            (event["patch_id"],),
        ).fetchone()
    finally:
        _close(provider)


@pytest.mark.parametrize("persistent", [False, True])
def test_real_ack_unlink_failure_keeps_complete_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, persistent: bool
) -> None:
    """One-shot and persistent unlink failures retain the fsynced retry."""
    module, provider = _load_provider(
        tmp_path, monkeypatch, f"memory_wiki_state_matrix_ack_unlink_{persistent}"
    )
    provider_two = None
    try:
        event = _snapshot(f"matrix-ack-unlink-{persistent}", "ack_unlink")
        raw = json.dumps(event, ensure_ascii=False).encode("utf-8")
        event_path = _inbox(tmp_path) / "ack-unlink.json"
        event_path.write_bytes(raw)
        claimed_result = provider._claim_code_shrinker_event(event_path)
        assert claimed_result is not None
        claimed, operation_id = claimed_result
        original_unlink = Path.unlink
        state = {"failures": 0}

        def fail_claimed_unlink(path: Path, *args, **kwargs):
            if path == claimed and (persistent or state["failures"] == 0):
                state["failures"] += 1
                raise PermissionError("injected claimed unlink failure")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", fail_claimed_unlink)
        assert provider._acknowledge_code_shrinker_claim(
            claimed, _inbox(tmp_path), operation_id
        ) is False
        retries = _retry_files(tmp_path)
        assert len(retries) == 1
        assert retries[0].read_bytes() == raw
        assert retries[0].name == f"retry-{operation_id}.json"
        assert claimed.exists() is persistent
        assert provider._code_shrinker_claim_is_active(claimed) is False

        monkeypatch.setattr(Path, "unlink", original_unlink)
        provider_two = module.MemoryWikiProvider()
        provider_two.initialize(
            "state-matrix-ack-recovery", hermes_home=str(tmp_path), agent_context="test"
        )
        provider_two._make_secret_index_from_raw = lambda *_args, **_kwargs: ""
        recovered = _call(provider_two, limit=2)
        assert recovered["success"] is True, recovered
        assert recovered["processed"] == 1, recovered
        assert recovered["pending"] == 0, recovered
        assert not claimed.exists() and not _retry_files(tmp_path)
        assert _graph_contains(provider_two, "src/ack_unlink.py")
    finally:
        _close(provider)
        if provider_two is not None:
            _close(provider_two)


def test_active_same_pid_claim_reports_in_progress_then_inactive_claim_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live sibling owner is pending, while an inactive same-PID claim recovers."""
    module, provider = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_active_same_pid"
    )
    provider_two = module.MemoryWikiProvider()
    provider_two.initialize(
        "state-matrix-active-sibling", hermes_home=str(tmp_path), agent_context="test"
    )
    provider_two._make_secret_index_from_raw = lambda *_args, **_kwargs: ""
    try:
        event = _snapshot("matrix-active-same-pid", "active_same_pid")
        _write_event(tmp_path, event)
        claimed_result = provider._claim_code_shrinker_event(
            _inbox(tmp_path) / "event.json"
        )
        assert claimed_result is not None
        claimed, _operation_id = claimed_result

        concurrent = _call(provider_two)
        assert concurrent["success"] is True, concurrent
        assert concurrent["status"] == "in_progress", concurrent
        assert concurrent["pending"] == 1 and concurrent["active_claims"] == 1
        assert concurrent["processed"] == 0
        assert claimed.exists()

        provider._release_code_shrinker_claim(claimed)
        resumed = _call(provider_two)
        assert resumed["success"] is True and resumed["processed"] == 1, resumed
        assert resumed["recovered_processing"] >= 1, resumed
        assert resumed["pending"] == 0, resumed
        assert _graph_contains(provider_two, "src/active_same_pid.py")
    finally:
        _close(provider)
        _close(provider_two)


def test_recovery_rechecks_active_lease_after_waiting_for_claim_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recovery cannot steal a rename whose active lease is not published yet."""
    module, claimant = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_claim_publish_race"
    )
    recovery = module.MemoryWikiProvider()
    recovery.initialize(
        "state-matrix-claim-publish-race-recovery",
        hermes_home=str(tmp_path),
        agent_context="test",
    )
    recovery._make_secret_index_from_raw = lambda *_args, **_kwargs: ""
    event_path = _inbox(tmp_path) / "event.json"
    event_path.write_text(
        json.dumps(_snapshot("matrix-claim-publish-race", "claim_publish_race")),
        encoding="utf-8",
    )

    after_replace = threading.Event()
    recovery_waiting = threading.Event()
    claim_returned = threading.Event()
    keep_claimant_alive = threading.Event()
    publish_barrier = threading.Barrier(2)
    original_mark = claimant._mark_code_shrinker_claim_active
    original_recovery_scope = recovery._journal_operation_scope
    outcomes: dict[str, Any] = {}
    failures: list[BaseException] = []

    def pause_before_active_publish(claimed: Path) -> None:
        after_replace.set()
        publish_barrier.wait(timeout=10)
        original_mark(claimed)

    @contextmanager
    def observe_recovery_scope():
        recovery_waiting.set()
        with original_recovery_scope():
            yield

    monkeypatch.setattr(
        claimant, "_mark_code_shrinker_claim_active", pause_before_active_publish
    )
    monkeypatch.setattr(recovery, "_journal_operation_scope", observe_recovery_scope)

    def claim_worker() -> None:
        try:
            outcomes["claim"] = claimant._claim_code_shrinker_event(event_path)
            claim_returned.set()
            assert keep_claimant_alive.wait(timeout=10)
        except BaseException as exc:
            failures.append(exc)

    def recovery_worker() -> None:
        try:
            outcomes["recovery"] = _call(recovery)
        except BaseException as exc:
            failures.append(exc)

    claim_thread = threading.Thread(target=claim_worker, daemon=True)
    recovery_thread = threading.Thread(target=recovery_worker, daemon=True)
    try:
        claim_thread.start()
        assert after_replace.wait(timeout=10)
        assert not event_path.exists()
        recovery_thread.start()
        assert recovery_waiting.wait(timeout=10)

        # Claimant still owns operations.lock.  Publishing the active lease
        # before unlock forces recovery to observe it on its in-lock recheck.
        publish_barrier.wait(timeout=10)
        assert claim_returned.wait(timeout=10)
        recovery_thread.join(timeout=10)
        assert not recovery_thread.is_alive()
        assert not failures, failures
        recovery_result = outcomes["recovery"]
        assert recovery_result["success"] is True, recovery_result
        assert recovery_result["status"] == "in_progress", recovery_result
        assert recovery_result["processed"] == 0
        assert recovery_result["pending"] == 1
        assert recovery_result["active_claims"] == 1
        claimed_result = outcomes["claim"]
        assert claimed_result is not None
        claimed, _operation_id = claimed_result
        assert claimed.exists()
        assert claimant._code_shrinker_claim_is_active(claimed)
        assert not _retry_files(tmp_path)
    finally:
        keep_claimant_alive.set()
        if claim_thread.is_alive() and after_replace.is_set():
            try:
                publish_barrier.abort()
            except threading.BrokenBarrierError:
                pass
        if claim_thread.ident is not None:
            claim_thread.join(timeout=10)
        if recovery_thread.ident is not None:
            recovery_thread.join(timeout=10)
        claimed_result = outcomes.get("claim")
        if claimed_result is not None:
            claimed = claimed_result[0]
            claimant._release_code_shrinker_claim(claimed)
            claimed.unlink(missing_ok=True)
        _close(claimant)
        _close(recovery)


@pytest.mark.parametrize(
    "hidden,use_symlink",
    [
        pytest.param(False, False, id="visible-directory"),
        pytest.param(True, False, id="hidden-directory"),
        pytest.param(False, True, id="visible-symlink"),
        pytest.param(True, True, id="hidden-symlink"),
    ],
)
def test_unsafe_inbox_entry_is_left_untouched_and_publicly_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hidden: bool,
    use_symlink: bool,
) -> None:
    """Non-regular producer/claim names cannot become a false empty poll."""
    _module, provider = _load_provider(
        tmp_path,
        monkeypatch,
        f"memory_wiki_state_matrix_unsafe_{hidden}_{use_symlink}",
    )
    inbox = _inbox(tmp_path)
    operation_id = "jop_" + "e" * 32
    name = (
        f".code-shrinker.processing.{operation_id}.{os.getpid()}.919191"
        if hidden
        else "unsafe-event.json"
    )
    entry = inbox / name
    target = tmp_path / "unsafe-link-target.json"
    valid_event_path = inbox / "valid-event.json"
    try:
        valid_event_path.write_text(
            json.dumps(_snapshot("matrix-safe-sibling", "safe_sibling")),
            encoding="utf-8",
        )
        if use_symlink:
            target_body = json.dumps(
                _snapshot("matrix-unsafe-link", "unsafe_link_target")
            )
            target.write_text(
                target_body,
                encoding="utf-8",
            )
            try:
                entry.symlink_to(target)
            except (NotImplementedError, OSError) as exc:
                pytest.skip(f"symbolic links unavailable: {type(exc).__name__}")
        else:
            entry.mkdir()

        original_active_check = provider._code_shrinker_claim_is_active

        def reject_active_check_for_unsafe(path: Path) -> bool:
            assert path != entry, "unsafe entry reached the active-claim registry"
            return original_active_check(path)

        monkeypatch.setattr(
            provider,
            "_code_shrinker_claim_is_active",
            reject_active_check_for_unsafe,
        )

        first = _call(provider)
        second = _call(provider)
        for result in (first, second):
            assert result["success"] is False, result
            assert result["status"] == "blocked", result
            assert (
                result["error"]
                == "code_shrinker_inbox_contains_unsafe_entries"
            ), result
            assert result["blocked_entries"] == 1, result
            assert result["blocked_events"] == int(not hidden), result
            assert result["blocked_claims"] == int(hidden), result
            assert result["pending"] == 2 and result["processed"] == 0
        assert os.path.lexists(entry)
        assert valid_event_path.is_file()
        assert not _graph_contains(provider, "src/safe_sibling.py")
        if use_symlink:
            assert entry.is_symlink()
            assert target.read_text(encoding="utf-8") == target_body
            assert not _graph_contains(provider, "src/unsafe_link_target.py")
        else:
            assert entry.is_dir()
        assert not _done_files(tmp_path) and not _dead_files(tmp_path)
        assert not any(
            record.get("op") == OP for record in provider._iter_journal_events()
        )
    finally:
        _close(provider)


@pytest.mark.parametrize(
    "internal_control", ["__retry_after_reconnect", "__journal_replay"]
)
def test_unsafe_inbox_entry_internal_routes_remain_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    internal_control: str,
) -> None:
    """Reconnect and replay dispatch cannot relabel blocked work as success."""
    module, provider = _load_provider(
        tmp_path,
        monkeypatch,
        f"memory_wiki_state_matrix_blocked_{internal_control}",
    )
    blocked = _inbox(tmp_path) / "blocked-event.json"
    blocked.mkdir()
    try:
        result = json.loads(provider.handle_tool_call(
            OP,
            {"limit": 1, internal_control: True},
            **module._internal_journal_call_kwargs(),
        ))
        assert result["success"] is False, result
        assert result["status"] == "blocked", result
        assert result["error"] == "code_shrinker_inbox_contains_unsafe_entries"
        assert result["blocked_entries"] == 1 and result["pending"] == 1
        assert blocked.is_dir()
    finally:
        _close(provider)


def test_journaled_drain_uses_one_authoritative_state_after_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A producer arrival after recovery cannot be hidden by a stale bool scan."""
    _module, provider = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_single_pending_snapshot"
    )
    original_recover = provider._recover_abandoned_code_shrinker_claims
    inserted = {"value": False}

    def recover_then_publish(inbox: Path) -> int:
        recovered = original_recover(inbox)
        if not inserted["value"]:
            inserted["value"] = True
            _write_event(
                tmp_path,
                _snapshot("matrix-after-recovery-publish", "after_recovery_publish"),
            )
        return recovered

    def stale_boolean_scan_is_forbidden() -> bool:
        raise AssertionError("journaled drain used a stale preliminary bool scan")

    monkeypatch.setattr(
        provider, "_recover_abandoned_code_shrinker_claims", recover_then_publish
    )
    monkeypatch.setattr(
        provider,
        "_code_shrinker_inbox_has_pending_work",
        stale_boolean_scan_is_forbidden,
    )
    try:
        result = _call(provider)
        assert result["success"] is True, result
        assert result["processed"] == 1 and result["pending"] == 0, result
        assert _graph_contains(provider, "src/after_recovery_publish.py")
        assert len(_done_files(tmp_path)) == 1
    finally:
        _close(provider)


def test_retry_claim_has_exactly_one_thread_winner_across_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """operations.lock serializes retry claim check and atomic rename."""
    module, provider = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_thread_claim_a"
    )
    provider_two = module.MemoryWikiProvider()
    provider_two.initialize(
        "state-matrix-thread-claim-b", hermes_home=str(tmp_path), agent_context="test"
    )
    operation_id = "jop_" + "a" * 32
    retry = _inbox(tmp_path) / provider._code_shrinker_retry_filename(operation_id)
    retry.write_text(json.dumps(_snapshot("matrix-thread-winner", "thread_winner")), encoding="utf-8")
    barrier = threading.Barrier(3)
    results: list[Any] = []
    failures: list[BaseException] = []
    result_lock = threading.Lock()

    def claim(worker_provider: Any) -> None:
        try:
            barrier.wait(timeout=10)
            value = worker_provider._claim_code_shrinker_event(retry)
            with result_lock:
                results.append(value)
        except BaseException as exc:
            with result_lock:
                failures.append(exc)

    workers = [
        threading.Thread(target=claim, args=(provider,), daemon=True),
        threading.Thread(target=claim, args=(provider_two,), daemon=True),
    ]
    try:
        for worker in workers:
            worker.start()
        barrier.wait(timeout=10)
        for worker in workers:
            worker.join(15)
            assert not worker.is_alive()
        assert not failures, failures
        winners = [value for value in results if value is not None]
        assert len(winners) == 1, results
        assert winners[0][1] == operation_id
        assert not retry.exists()
        hidden = list(_inbox(tmp_path).glob(f".code-shrinker.processing.{operation_id}.*"))
        assert len(hidden) == 1
        provider._release_code_shrinker_claim(hidden[0])
    finally:
        for worker in workers:
            worker.join(15)
        _close(provider)
        _close(provider_two)


def test_retry_claim_has_exactly_one_process_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same claim scope has exactly one winner across Python processes."""
    _module, provider = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_process_parent"
    )
    operation_id = "jop_" + "b" * 32
    retry = _inbox(tmp_path) / provider._code_shrinker_retry_filename(operation_id)
    retry.write_text(json.dumps(_snapshot("matrix-process-winner", "process_winner")), encoding="utf-8")
    start = tmp_path / "process-claim-start"
    code = r"""
import importlib.util, json, os, sys, time
from pathlib import Path
home, plugin, retry, ready, start, module_name = sys.argv[1:]
os.environ.update({"HERMES_HOME": home, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0", "MEMORY_WIKI_CODE_GRAPH_EMBED": "0"})
spec = importlib.util.spec_from_file_location(module_name, plugin, submodule_search_locations=[str(Path(plugin).parent)])
module = importlib.util.module_from_spec(spec); sys.modules[module_name] = module; spec.loader.exec_module(module)
provider = module.MemoryWikiProvider(); provider.initialize(module_name, hermes_home=home, agent_context="test")
Path(ready).write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 180
while not Path(start).exists() and time.monotonic() < deadline: time.sleep(0.01)
result = provider._claim_code_shrinker_event(Path(retry))
print(json.dumps({"won": result is not None, "operation_id": result[1] if result else ""}))
"""
    processes = []
    ready_paths = [tmp_path / f"ready-{index}" for index in range(2)]

    def wait_for_ready(process: subprocess.Popen[str], ready: Path) -> None:
        deadline = time.monotonic() + 60
        while not ready.exists():
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(
                    "claim worker exited before ready: "
                    f"returncode={process.returncode}, stdout={stdout!r}, stderr={stderr!r}"
                )
            if time.monotonic() >= deadline:
                pytest.fail(
                    "claim worker did not become ready within 60 seconds: "
                    f"pid={process.pid}, returncode={process.poll()}"
                )
            time.sleep(0.02)

    try:
        # The assertion below concerns cross-process *claiming*. Bootstrap each
        # full provider independently before the race: concurrent SQLite/schema
        # initialization is not part of the claim invariant and is too sensitive
        # to hosted Windows filesystem scheduling.
        _close(provider)
        for index, ready in enumerate(ready_paths):
            process = subprocess.Popen(
                [
                    sys.executable, "-B", "-c", code, str(tmp_path), str(PLUGIN),
                    str(retry), str(ready), str(start), f"mw_process_claim_{index}",
                ],
                cwd=str(PLUGIN.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            processes.append(process)
            wait_for_ready(process, ready)
        start.touch()
        outputs = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
            outputs.append(json.loads(stdout.strip().splitlines()[-1]))
        assert sum(1 for output in outputs if output["won"]) == 1, outputs
        assert {output["operation_id"] for output in outputs if output["won"]} == {operation_id}
        assert len(list(_inbox(tmp_path).glob(f".code-shrinker.processing.{operation_id}.*"))) == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        _close(provider)


def _seed_retry_collision(
    provider: Any, tmp_path: Path, suffix: str
) -> tuple[Path, Path, str, dict[str, Any], dict[str, Any]]:
    operation_id = "jop_" + "c" * 32
    first = _snapshot(f"matrix-collision-hidden-{suffix}", f"collision_hidden_{suffix}")
    second = _snapshot(f"matrix-collision-retry-{suffix}", f"collision_retry_{suffix}")
    inbox = _inbox(tmp_path)
    hidden = inbox / (
        f".code-shrinker.processing.{operation_id}.{os.getpid()}.424242"
    )
    retry = inbox / provider._code_shrinker_retry_filename(operation_id)
    hidden.write_text(json.dumps(first), encoding="utf-8")
    retry.write_text(json.dumps(second), encoding="utf-8")
    return hidden, retry, operation_id, first, second


def test_retry_collision_is_reidentified_and_both_payloads_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distinct collision bytes receive a new ID before either is processed."""
    _module, provider = _load_provider(
        tmp_path, monkeypatch, "memory_wiki_state_matrix_collision_progress"
    )
    try:
        hidden, retry, operation_id, first, second = _seed_retry_collision(
            provider, tmp_path, "progress"
        )
        result = _call(provider, limit=2)
        assert result["success"] is True and result["processed"] == 2, result
        assert result["recovered_processing"] >= 1 and result["pending"] == 0
        assert not hidden.exists() and not _retry_files(tmp_path)
        assert len(_done_files(tmp_path)) == 2
        assert _graph_contains(provider, first["files"][0]["file_path"])
        assert _graph_contains(provider, second["files"][0]["file_path"])

        operation_by_event = {}
        for record in provider._iter_journal_events():
            if record.get("op") != OP or record.get("phase") != "after":
                continue
            recovery = (record.get("result") or {}).get("recovery") or {}
            artifacts = recovery.get("artifacts") or []
            if artifacts:
                operation_by_event[artifacts[0]["event_id"]] = record["payload"]["operation_id"]
        assert operation_by_event[first["event_id"]] == operation_id
        assert operation_by_event[second["event_id"]] != operation_id
    finally:
        _close(provider)


@pytest.mark.parametrize(
    "failure_stage", ["unlink", "fsync_before_unlink", "fsync_after_unlink"]
)
def test_collision_reidentification_interruption_is_truthful_then_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    """Failure after collision hard-linking preserves both bodies for retry."""
    _module, provider = _load_provider(
        tmp_path, monkeypatch, f"memory_wiki_state_matrix_collision_{failure_stage}"
    )
    try:
        hidden, retry, _operation_id, first, second = _seed_retry_collision(
            provider, tmp_path, failure_stage
        )
        original_unlink = Path.unlink
        original_fsync_dir = provider._fsync_dir
        tripped = {"value": False}

        if failure_stage == "unlink":
            def fail_old_retry_unlink(path: Path, *args, **kwargs):
                if path == retry and not tripped["value"]:
                    tripped["value"] = True
                    raise PermissionError("injected collision unlink failure")
                return original_unlink(path, *args, **kwargs)

            monkeypatch.setattr(Path, "unlink", fail_old_retry_unlink)
        else:
            fail_at = 1 if failure_stage == "fsync_before_unlink" else 2
            fsync_calls = {"value": 0}

            def fail_selected_fsync(path: Path) -> None:
                if path == _inbox(tmp_path):
                    fsync_calls["value"] += 1
                if (
                    path == _inbox(tmp_path)
                    and fsync_calls["value"] == fail_at
                ):
                    tripped["value"] = True
                    raise OSError("injected collision fsync failure")
                original_fsync_dir(path)

            monkeypatch.setattr(provider, "_fsync_dir", fail_selected_fsync)

        blocked = _call(provider, limit=3)
        assert tripped["value"]
        assert blocked["success"] is False, blocked
        assert blocked["status"] == "retry_pending", blocked
        assert blocked["error"] == "code_shrinker_claim_recovery_failed"
        assert blocked["pending"] >= 2, blocked
        assert hidden.exists()
        assert _retry_files(tmp_path)
        if failure_stage != "fsync_after_unlink":
            assert retry.exists()

        monkeypatch.setattr(Path, "unlink", original_unlink)
        monkeypatch.setattr(provider, "_fsync_dir", original_fsync_dir)
        resumed = _call(provider, limit=3)
        assert resumed["success"] is True and resumed["processed"] == 2, resumed
        assert resumed["pending"] == 0, resumed
        assert _graph_contains(provider, first["files"][0]["file_path"])
        assert _graph_contains(provider, second["files"][0]["file_path"])
    finally:
        _close(provider)
