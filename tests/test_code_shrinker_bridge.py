from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


def load_provider(tmp_path: Path):
    os.environ["HERMES_HOME"] = str(tmp_path)
    os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
    plugin = Path(__file__).resolve().parents[1] / "__init__.py"
    spec = importlib.util.spec_from_file_location("memory_wiki_under_test", plugin)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize("bridge-test", hermes_home=str(tmp_path))
    # This bridge test is not a secret-broker integration test. Keep the fixture
    # hermetic when hermes_secret_core is not installed in the test runner.
    provider._make_secret_index_from_raw = lambda *_a, **_k: ""
    provider._test_module = module
    return provider


def test_patch_event_archives_old_revision_and_is_idempotent(tmp_path):
    provider = load_provider(tmp_path)
    old_hash = hashlib.sha256(b"old source body").hexdigest()
    new_hash = hashlib.sha256(b"new source body").hexdigest()
    result = provider._code_claim_add({
        "claim": "Verified Hermes configuration runbook: function foo returns one; source revision and restore procedure were checked.",
        "topic": "code-shrinker", "repository_id": "owner/repo", "file_path": "src/a.js",
        "content_hash": old_hash, "symbol_id": "sym_foo", "symbol_revision": "rev1",
        "evidence": "verified exact source and backup restore procedure", "confidence": 0.95, "salience": 0.9,
    })
    claim_id = result["id"]
    conn = provider._connect()
    assert conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (claim_id,)).fetchone()
    event = {
        "event_version": 1, "event_id": "patch:test:event-1", "producer": "mcp-code-shrinker",
        "type": "patch_applied", "repository_id": "owner/repo", "patch_id": "p1", "outcome": "applied",
        "changed_files": ["src/a.js"], "changed_symbols": ["sym_foo"],
        "per_file": [{"file_path": "src/a.js", "old_content_hash": old_hash, "new_content_hash": new_hash}],
        "validation_report": {"status": "valid"}, "rollback_steps": "restore backup",
    }
    inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "event.json").write_text(json.dumps(event), encoding="utf-8")
    assert provider._drain_code_shrinker_events()["processed"] == 1
    assert conn.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()["status"] == "archived"
    assert not conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (claim_id,)).fetchone()
    row = conn.execute("SELECT * FROM patch_outcomes WHERE repository_id=? AND patch_id=?", ("owner/repo", "p1")).fetchone()
    assert row and row["new_content_hash"] == new_hash
    provider._rebuild_fts()
    assert not conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (claim_id,)).fetchone()
    (inbox / "event-again.json").write_text(json.dumps(event), encoding="utf-8")
    assert provider._drain_code_shrinker_events()["deduplicated"] == 1


def test_patch_event_retry_cannot_invalidate_file_added_to_mutated_duplicate(tmp_path):
    """A duplicate source event cannot gain new invalidation authority."""
    provider = load_provider(tmp_path)
    old_a = hashlib.sha256(b"a-old").hexdigest()
    new_a = hashlib.sha256(b"a-new").hexdigest()
    old_b = hashlib.sha256(b"b-old").hexdigest()
    new_b = hashlib.sha256(b"b-new").hexdigest()

    def add_claim(file_path: str, content_hash: str, symbol_id: str) -> str:
        result = provider._code_claim_add({
            "claim": (
                f"Verified current source behavior for {file_path}; the runbook and "
                "rollback procedure were checked against the repository revision."
            ),
            "topic": "code-shrinker",
            "repository_id": "owner/exactly-once",
            "file_path": file_path,
            "content_hash": content_hash,
            "symbol_id": symbol_id,
            "symbol_revision": "rev1",
            "evidence": "verified source and revision metadata",
            "confidence": 0.95,
            "salience": 0.9,
        })
        assert result.get("id"), result
        return str(result["id"])

    a_claim_id = add_claim("src/a.py", old_a, "a_symbol")
    first_event = {
        "event_version": 1,
        "type": "patch_applied",
        "event_id": "patch:exactly-once:source-event",
        "repository_id": "owner/exactly-once",
        "patch_id": "patch-exactly-once",
        "outcome": "applied",
        "changed_files": ["src/a.py"],
        "changed_symbols": ["a_symbol"],
        "per_file": [{
            "file_path": "src/a.py",
            "old_content_hash": old_a,
            "new_content_hash": new_a,
        }],
        "validation_report": {"status": "valid"},
    }
    first = provider._apply_code_shrinker_patch_event(first_event)
    assert first["deduplicated"] is False
    conn = provider._connect()
    assert conn.execute(
        "SELECT status FROM claims WHERE id=?", (a_claim_id,)
    ).fetchone()["status"] == "archived"

    # This claim was created after the original event.  A malformed retry
    # reusing its source event ID must not be able to archive it by adding a
    # new file to ``per_file``.
    b_claim_id = add_claim("src/b.py", old_b, "b_symbol")
    mutated_retry = {
        **first_event,
        "per_file": [
            *first_event["per_file"],
            {
                "file_path": "src/b.py",
                "old_content_hash": old_b,
                "new_content_hash": new_b,
            },
        ],
    }
    retry = provider._apply_code_shrinker_patch_event(mutated_retry)
    assert retry["deduplicated"] is True
    assert retry["invalidations"] == []
    assert conn.execute(
        "SELECT status FROM claims WHERE id=?", (b_claim_id,)
    ).fetchone()["status"] == "active"


def test_review_queued_patch_event_has_no_invalidation_authority(tmp_path, monkeypatch):
    """A non-durable review outcome cannot mutate code state on any retry."""
    provider = load_provider(tmp_path)
    old_a = hashlib.sha256(b"review-a-old").hexdigest()
    new_a = hashlib.sha256(b"review-a-new").hexdigest()
    old_b = hashlib.sha256(b"review-b-old").hexdigest()
    new_b = hashlib.sha256(b"review-b-new").hexdigest()

    def add_claim(file_path: str, content_hash: str, symbol_id: str) -> str:
        result = provider._code_claim_add({
            "claim": (
                f"Verified source behavior for {file_path}; the runbook and "
                "rollback procedure were checked against the repository revision."
            ),
            "topic": "code-shrinker",
            "repository_id": "owner/review-exactly-once",
            "file_path": file_path,
            "content_hash": content_hash,
            "symbol_id": symbol_id,
            "symbol_revision": "rev1",
            "evidence": "verified source and revision metadata",
            "confidence": 0.95,
            "salience": 0.9,
        })
        assert result.get("id"), result
        return str(result["id"])

    a_claim_id = add_claim("src/a.py", old_a, "a_symbol")
    b_claim_id = add_claim("src/b.py", old_b, "b_symbol")
    # Exercise the real review-queue branch while keeping the previously
    # seeded code claims durable and active.
    monkeypatch.setattr(
        provider._test_module,
        "memory_gate_decision",
        lambda *_args, **_kwargs: {"action": "queue", "reason": "test review"},
    )
    first_event = {
        "event_version": 1,
        "type": "patch_applied",
        "event_id": "patch:review:source-event",
        "repository_id": "owner/review-exactly-once",
        "patch_id": "patch-review-exactly-once",
        "outcome": "applied",
        "per_file": [{
            "file_path": "src/a.py",
            "old_content_hash": old_a,
            "new_content_hash": new_a,
        }],
        "validation_report": {"status": "valid"},
    }
    first = provider._apply_code_shrinker_patch_event(first_event)
    assert first["outcome"]["status"] == "need_review", first
    assert first["invalidations"] == [], first
    conn = provider._connect()
    assert conn.execute("SELECT status FROM claims WHERE id=?", (a_claim_id,)).fetchone()["status"] == "active"
    assert conn.execute("SELECT status FROM claims WHERE id=?", (b_claim_id,)).fetchone()["status"] == "active"
    assert conn.execute(
        "SELECT count(*) FROM integration_events WHERE producer='mcp-code-shrinker' AND event_id=?",
        (first_event["event_id"],),
    ).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM patch_outcomes").fetchone()[0] == 0

    # Reusing the pending event ID with broader invalidation input cannot
    # archive a newly named file before the review is made durable.
    expanded_retry = {
        **first_event,
        "per_file": [
            *first_event["per_file"],
            {
                "file_path": "src/b.py",
                "old_content_hash": old_b,
                "new_content_hash": new_b,
            },
        ],
    }
    retry = provider._apply_code_shrinker_patch_event(expanded_retry)
    assert retry["outcome"]["status"] == "need_review", retry
    assert retry["invalidations"] == [], retry
    assert conn.execute("SELECT status FROM claims WHERE id=?", (b_claim_id,)).fetchone()["status"] == "active"
    assert conn.execute(
        "SELECT count(*) FROM integration_events WHERE producer='mcp-code-shrinker' AND event_id=?",
        (first_event["event_id"],),
    ).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM patch_outcomes").fetchone()[0] == 0


def test_patch_event_rolls_back_outcome_when_invalidation_fails(tmp_path, monkeypatch):
    """A failed first invalidation must leave the source event retryable."""
    provider = load_provider(tmp_path)
    old_hash = hashlib.sha256(b"rollback-old").hexdigest()
    new_hash = hashlib.sha256(b"rollback-new").hexdigest()
    claim = provider._code_claim_add({
        "claim": (
            "Verified source behavior for the atomic patch rollback regression; "
            "the current revision and recovery procedure were checked."
        ),
        "topic": "code-shrinker",
        "repository_id": "owner/atomic-patch",
        "file_path": "src/atomic.py",
        "content_hash": old_hash,
        "symbol_id": "atomic_symbol",
        "symbol_revision": "rev1",
        "evidence": "verified source and revision metadata",
        "confidence": 0.95,
        "salience": 0.9,
    })
    claim_id = str(claim["id"])
    event = {
        "event_version": 1,
        "type": "patch_applied",
        "event_id": "patch:atomic:source-event",
        "repository_id": "owner/atomic-patch",
        "patch_id": "patch-atomic",
        "outcome": "applied",
        "changed_files": ["src/atomic.py"],
        "changed_symbols": ["atomic_symbol"],
        "per_file": [{
            "file_path": "src/atomic.py",
            "old_content_hash": old_hash,
            "new_content_hash": new_hash,
        }],
        "validation_report": {"status": "valid"},
    }
    original_invalidate = provider._invalidate_revision
    calls = 0

    def fail_first_invalidation(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            # The patch outcome and invalidations must share one open writer
            # transaction; otherwise a failure below cannot roll the outcome
            # and exactly-once ledger back for a retry.
            assert provider._connect().in_transaction
            raise RuntimeError("injected invalidation failure")
        return original_invalidate(*args, **kwargs)

    monkeypatch.setattr(provider, "_invalidate_revision", fail_first_invalidation)
    with pytest.raises(RuntimeError, match="injected invalidation failure"):
        provider._apply_code_shrinker_patch_event(event)

    conn = provider._connect()
    assert conn.execute(
        "SELECT status FROM claims WHERE id=?", (claim_id,)
    ).fetchone()["status"] == "active"
    assert conn.execute("SELECT COUNT(*) FROM patch_outcomes").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM integration_events "
        "WHERE producer='mcp-code-shrinker' AND event_id=?",
        (event["event_id"],),
    ).fetchone()[0] == 0

    monkeypatch.setattr(provider, "_invalidate_revision", original_invalidate)
    retried = provider._apply_code_shrinker_patch_event(event)
    assert retried["deduplicated"] is False
    assert retried["invalidations"][0]["invalidated"] == 1
    assert conn.execute(
        "SELECT status FROM claims WHERE id=?", (claim_id,)
    ).fetchone()["status"] == "archived"
    assert conn.execute("SELECT COUNT(*) FROM patch_outcomes").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM integration_events "
        "WHERE producer='mcp-code-shrinker' AND event_id=?",
        (event["event_id"],),
    ).fetchone()[0] == 1


def test_post_commit_artifact_failure_requeues_and_later_closes_journal_pair(tmp_path, monkeypatch):
    """A retry must preserve committed state and later capture its replay ref."""
    provider = load_provider(tmp_path)
    checkpoint = provider._journal_checkpoint("before-artifact-retry")
    old_hash = hashlib.sha256(b"artifact-retry-old").hexdigest()
    new_hash = hashlib.sha256(b"artifact-retry-new").hexdigest()
    claim = provider._code_claim_add({
        "claim": "Verified artifact retry source behavior and its recovery procedure.",
        "topic": "code-shrinker", "repository_id": "owner/artifact-retry",
        "file_path": "src/retry.py", "content_hash": old_hash,
        "symbol_id": "retry_symbol", "symbol_revision": "rev1",
        "evidence": "verified source and revision metadata", "confidence": 0.95, "salience": 0.9,
    })
    claim_id = str(claim["id"])
    event = {
        "event_version": 1, "type": "patch_applied", "producer": "mcp-code-shrinker",
        "event_id": "patch:artifact-retry:source-event", "repository_id": "owner/artifact-retry",
        "patch_id": "patch-artifact-retry", "outcome": "applied",
        "changed_files": ["src/retry.py"], "changed_symbols": ["retry_symbol"],
        "per_file": [{"file_path": "src/retry.py", "old_content_hash": old_hash, "new_content_hash": new_hash}],
        "validation_report": {"status": "valid"},
    }
    inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
    inbox.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(event, sort_keys=True).encode("utf-8")
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    producer_name = "artifact-retry-event.json"
    (inbox / producer_name).write_bytes(raw)
    original_store = provider._store_code_graph_inbox_artifact
    calls = 0

    def fail_first_artifact(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected recovery artifact write failure")
        return original_store(*args, **kwargs)

    monkeypatch.setattr(provider, "_store_code_graph_inbox_artifact", fail_first_artifact)
    first = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
    assert first["success"] is False, first
    assert first["processed"] == 0 and first["failed"] == 1, first
    assert first["retryable"] == 1 and first["retryable_unrequeued"] == 0, first
    conn = provider._connect()
    assert conn.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()["status"] == "archived"
    assert conn.execute("SELECT COUNT(*) FROM patch_outcomes").fetchone()[0] == 1
    assert not list((tmp_path / "context-coordination" / "dead-letter" / "code-shrinker").glob("*.json"))
    retries = list(inbox.glob("retry-jop_*.json"))
    assert len(retries) == 1
    assert producer_name not in retries[0].name

    records = [json.loads(line) for line in provider.journal_path.read_text(encoding="utf-8").splitlines() if line]
    before = next(record for record in records if record["phase"] == "before")
    operation_id = before["payload"]["operation_id"]
    assert provider._code_shrinker_retry_operation_id(retries[0].name) == operation_id
    assert raw_sha256 not in provider.journal_path.read_text(encoding="utf-8")
    assert not any(record["phase"] == "after" for record in records)

    monkeypatch.setattr(provider, "_store_code_graph_inbox_artifact", original_store)
    second = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
    assert second["success"] is True and second["processed"] == 1, second
    assert second["deduplicated"] == 1, second
    assert len(second["recovery_artifacts"]) == 1
    assert not list(inbox.glob("retry-jop_*.json"))
    assert conn.execute("SELECT COUNT(*) FROM patch_outcomes").fetchone()[0] == 1
    plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
    assert plan["incomplete_events"] == 0 and plan["unrecoverable_events"] == 0, plan


def test_crash_after_artifact_before_journal_after_reuses_random_claim_id(tmp_path, monkeypatch):
    """The raw claim remains until the journal after-record is durable."""
    provider = load_provider(tmp_path)
    checkpoint = provider._journal_checkpoint("before-after-crash")
    old_hash = hashlib.sha256(b"after-crash-old").hexdigest()
    new_hash = hashlib.sha256(b"after-crash-new").hexdigest()
    claim = provider._code_claim_add({
        "claim": "Verified journal-after crash recovery source behavior.",
        "topic": "code-shrinker", "repository_id": "owner/after-crash",
        "file_path": "src/after_crash.py", "content_hash": old_hash,
        "symbol_id": "after_crash_symbol", "symbol_revision": "rev1",
        "evidence": "verified source and revision metadata", "confidence": 0.95, "salience": 0.9,
    })
    claim_id = str(claim["id"])
    event = {
        "event_version": 1, "type": "patch_applied", "producer": "mcp-code-shrinker",
        "event_id": "patch:after-crash:source-event", "repository_id": "owner/after-crash",
        "patch_id": "patch-after-crash", "outcome": "applied",
        "changed_files": ["src/after_crash.py"], "changed_symbols": ["after_crash_symbol"],
        "per_file": [{"file_path": "src/after_crash.py", "old_content_hash": old_hash, "new_content_hash": new_hash}],
        "validation_report": {"status": "valid"},
    }
    inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
    inbox.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(event, sort_keys=True).encode("utf-8")
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    (inbox / "after-crash-event.json").write_bytes(raw)
    original_after_result = provider._journal_after_result
    calls = 0

    def crash_before_after(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SystemExit("injected crash before journal after")
        return original_after_result(*args, **kwargs)

    monkeypatch.setattr(provider, "_journal_after_result", crash_before_after)
    with pytest.raises(SystemExit, match="injected crash before journal after"):
        provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1})

    conn = provider._connect()
    assert conn.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()["status"] == "archived"
    hidden = [path for path in inbox.iterdir() if ".processing.jop_" in path.name]
    assert len(hidden) == 1
    records = [json.loads(line) for line in provider.journal_path.read_text(encoding="utf-8").splitlines() if line]
    first_before = next(record for record in records if record["phase"] == "before")
    operation_id = first_before["payload"]["operation_id"]
    assert operation_id in hidden[0].name
    assert raw_sha256 not in provider.journal_path.read_text(encoding="utf-8")
    assert not any(record["phase"] == "after" for record in records)

    monkeypatch.setattr(provider, "_journal_after_result", original_after_result)
    monkeypatch.setattr(provider, "_code_shrinker_process_is_alive", lambda _pid: False)
    recovered = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
    assert recovered["success"] is True and recovered["processed"] == 1, recovered
    assert recovered["deduplicated"] == 1
    assert recovered["recovered_processing"] == 1
    assert not [path for path in inbox.iterdir() if ".processing." in path.name]
    plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
    assert plan["incomplete_events"] == 0 and plan["unrecoverable_events"] == 0, plan


def test_journal_after_capture_failure_requeues_for_immediate_retry(tmp_path, monkeypatch):
    """An ordinary after-capture error must not require a process restart."""
    provider = load_provider(tmp_path)
    checkpoint = provider._journal_checkpoint("before-after-capture-retry")
    old_hash = hashlib.sha256(b"capture-retry-old").hexdigest()
    new_hash = hashlib.sha256(b"capture-retry-new").hexdigest()
    claim = provider._code_claim_add({
        "claim": "Verified recovery-reference capture retry behavior.",
        "topic": "code-shrinker", "repository_id": "owner/capture-retry",
        "file_path": "src/capture_retry.py", "content_hash": old_hash,
        "symbol_id": "capture_retry_symbol", "symbol_revision": "rev1",
        "evidence": "verified source and revision metadata", "confidence": 0.95, "salience": 0.9,
    })
    claim_id = str(claim["id"])
    event = {
        "event_version": 1, "type": "patch_applied", "producer": "mcp-code-shrinker",
        "event_id": "patch:capture-retry:source-event", "repository_id": "owner/capture-retry",
        "patch_id": "patch-capture-retry", "outcome": "applied",
        "changed_files": ["src/capture_retry.py"], "changed_symbols": ["capture_retry_symbol"],
        "per_file": [{"file_path": "src/capture_retry.py", "old_content_hash": old_hash, "new_content_hash": new_hash}],
        "validation_report": {"status": "valid"},
    }
    inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
    inbox.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(event, sort_keys=True).encode("utf-8")
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    (inbox / "capture-retry-event.json").write_bytes(raw)
    original_after_result = provider._journal_after_result
    calls = 0

    def fail_first_capture(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected after-result capture failure")
        return original_after_result(*args, **kwargs)

    monkeypatch.setattr(provider, "_journal_after_result", fail_first_capture)
    first = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
    assert first["success"] is False, first
    assert first["failed"] == 1 and first["retryable"] == 1, first
    assert first["retryable_unrequeued"] == 0, first
    assert first["error"] == "code_shrinker_journal_failed"
    conn = provider._connect()
    assert conn.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()["status"] == "archived"
    assert conn.execute("SELECT COUNT(*) FROM patch_outcomes").fetchone()[0] == 1
    retries = list(inbox.glob("retry-jop_*.json"))
    assert len(retries) == 1
    assert not [path for path in inbox.iterdir() if ".processing." in path.name]
    records = [json.loads(line) for line in provider.journal_path.read_text(encoding="utf-8").splitlines() if line]
    before = next(record for record in records if record["phase"] == "before")
    error = next(record for record in records if record["phase"] == "error")
    assert provider._code_shrinker_retry_operation_id(retries[0].name) == before["payload"]["operation_id"]
    assert error["result"]["retryable_code_shrinker_failure"] is True
    assert raw_sha256 not in provider.journal_path.read_text(encoding="utf-8")

    monkeypatch.setattr(provider, "_journal_after_result", original_after_result)
    second = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
    assert second["success"] is True and second["processed"] == 1, second
    assert second["deduplicated"] == 1, second
    assert not list(inbox.glob("retry-jop_*.json"))
    plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
    assert plan["incomplete_events"] == 0 and plan["unrecoverable_events"] == 0, plan


def test_journal_after_append_failure_requeues_and_closes_prior_before(tmp_path, monkeypatch):
    """A failed after fsync leaves a replayable raw claim, not a stuck before."""
    provider = load_provider(tmp_path)
    checkpoint = provider._journal_checkpoint("before-after-append-retry")
    old_hash = hashlib.sha256(b"append-retry-old").hexdigest()
    new_hash = hashlib.sha256(b"append-retry-new").hexdigest()
    claim = provider._code_claim_add({
        "claim": "Verified journal append retry behavior for code recovery.",
        "topic": "code-shrinker", "repository_id": "owner/append-retry",
        "file_path": "src/append_retry.py", "content_hash": old_hash,
        "symbol_id": "append_retry_symbol", "symbol_revision": "rev1",
        "evidence": "verified source and revision metadata", "confidence": 0.95, "salience": 0.9,
    })
    claim_id = str(claim["id"])
    event = {
        "event_version": 1, "type": "patch_applied", "producer": "mcp-code-shrinker",
        "event_id": "patch:append-retry:source-event", "repository_id": "owner/append-retry",
        "patch_id": "patch-append-retry", "outcome": "applied",
        "changed_files": ["src/append_retry.py"], "changed_symbols": ["append_retry_symbol"],
        "per_file": [{"file_path": "src/append_retry.py", "old_content_hash": old_hash, "new_content_hash": new_hash}],
        "validation_report": {"status": "valid"},
    }
    inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "append-retry-event.json").write_text(json.dumps(event), encoding="utf-8")
    original_append = provider._append_journal_event
    failed_after = False

    def fail_first_after_append(op, payload, *, phase="after", **kwargs):
        nonlocal failed_after
        if phase == "after" and not failed_after:
            failed_after = True
            raise OSError("injected after journal fsync failure")
        return original_append(op, payload, phase=phase, **kwargs)

    monkeypatch.setattr(provider, "_append_journal_event", fail_first_after_append)
    first = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
    assert first["success"] is False and first["retryable"] == 1, first
    assert first["retryable_unrequeued"] == 0, first
    assert provider._connect().execute(
        "SELECT status FROM claims WHERE id=?", (claim_id,)
    ).fetchone()["status"] == "archived"
    retries = list(inbox.glob("retry-jop_*.json"))
    assert len(retries) == 1
    records = [json.loads(line) for line in provider.journal_path.read_text(encoding="utf-8").splitlines() if line]
    assert [record["phase"] for record in records] == ["before"]
    operation_id = records[0]["payload"]["operation_id"]
    assert provider._code_shrinker_retry_operation_id(retries[0].name) == operation_id

    monkeypatch.setattr(provider, "_append_journal_event", original_append)
    second = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
    assert second["success"] is True and second["deduplicated"] == 1, second
    assert not list(inbox.glob("retry-jop_*.json"))
    plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
    assert plan["incomplete_events"] == 0 and plan["unrecoverable_events"] == 0, plan


def test_invalid_precommit_event_is_terminal_noop_not_journal_incomplete(tmp_path):
    """Rejected producer input has no mutation to replay or retry."""
    provider = load_provider(tmp_path)
    checkpoint = provider._journal_checkpoint("before-invalid-producer")
    secret = "ghp_" + "v" * 36
    event = {
        "event_version": 1,
        "type": "patch_applied",
        "producer": "unexpected-producer",
        "event_id": "patch:invalid-producer:event",
        "validation_report": {"token": secret},
    }
    inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "invalid-producer-event.json").write_text(json.dumps(event), encoding="utf-8")

    result = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
    assert result["success"] is True, result
    assert result["processed"] == 0 and result["failed"] == 1, result
    assert result["retryable"] == 0 and result["retryable_unrequeued"] == 0, result
    assert not list(inbox.glob("*.json"))
    dead = tmp_path / "context-coordination" / "dead-letter" / "code-shrinker"
    assert len(list(dead.glob("event-*.json"))) == 2
    journal = provider.journal_path.read_text(encoding="utf-8")
    assert secret not in journal
    records = [json.loads(line) for line in journal.splitlines() if line]
    assert [record["phase"] for record in records] == ["before", "after"]
    assert records[-1]["result"]["recovery"]["kind"] == "noop"
    plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
    assert plan["ignored_events"] == 1, plan
    assert plan["incomplete_events"] == 0 and plan["unrecoverable_events"] == 0, plan


def test_stale_processing_claim_recovers_without_stealing_live_owner(tmp_path, monkeypatch):
    """Recovery may take only definitely-dead claims and keeps its opaque ID."""
    provider = load_provider(tmp_path)
    inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
    inbox.mkdir(parents=True, exist_ok=True)
    producer_name = "producer-name-with-ghp_" + "z" * 36 + ".json"
    raw = b'{"event_version":1}'
    source = inbox / producer_name
    source.write_bytes(raw)
    claimed = provider._claim_code_shrinker_event(source)
    assert claimed is not None
    claimed_path, operation_id = claimed
    assert producer_name not in claimed_path.name
    assert operation_id in claimed_path.name

    monkeypatch.setattr(provider, "_code_shrinker_process_is_alive", lambda _pid: True)
    assert provider._recover_abandoned_code_shrinker_claims(inbox) == 0
    assert claimed_path.exists()
    assert not list(inbox.glob("retry-jop_*.json"))

    # The new process-local registry is stronger than a PID probe: explicitly
    # end this fixture's ownership lease before simulating an abandoned owner.
    provider._release_code_shrinker_claim(claimed_path)
    monkeypatch.setattr(provider, "_code_shrinker_process_is_alive", lambda _pid: False)
    assert provider._recover_abandoned_code_shrinker_claims(inbox) == 1
    retries = list(inbox.glob("retry-jop_*.json"))
    assert len(retries) == 1
    assert provider._code_shrinker_retry_operation_id(retries[0].name) == operation_id
    assert retries[0].read_bytes() == raw
    assert not claimed_path.exists()


def test_direct_patch_outcome_scrubs_free_form_payloads_before_sqlite_write(tmp_path):
    """The direct public patch API must not retain report/rollback secrets."""
    provider = load_provider(tmp_path)
    secret = "ghp_" + "q" * 36
    result = provider._patch_outcome_add({
        "patch_id": "patch-validation-redaction",
        "outcome": f"applied with {secret}",
        "repository_id": "owner/validation-redaction",
        "producer": f"mcp-code-shrinker-{secret}",
        "source_event_id": "patch:validation-redaction:event",
        "new_content_hash": hashlib.sha256(b"validation-redaction").hexdigest(),
        "changed_files": ["src/validation.py"],
        "validation_report": {
            "status": "verified",
            "details": f"credential={secret}",
            "nested": {"message": f"credential={secret}"},
            f"header_{secret}": {"nested": [f"Bearer {secret}"]},
        },
        "rollback_steps": f"Restore the prior revision using {secret}",
    })
    assert result.get("structured") is True, result

    conn = provider._connect()
    patch_row = conn.execute(
        "SELECT outcome,rollback_steps,validation_report_json FROM patch_outcomes"
    ).fetchone()
    event_row = conn.execute(
        "SELECT producer FROM integration_events"
    ).fetchone()
    claim_row = conn.execute(
        "SELECT claim,evidence FROM claims WHERE id=?", (result["id"],)
    ).fetchone()
    serialized = json.dumps({
        "patch": dict(patch_row),
        "event": dict(event_row),
        "claim": dict(claim_row),
    }, ensure_ascii=False)
    assert secret not in serialized
    assert "credential=" not in serialized
    assert json.loads(str(patch_row["validation_report_json"]))["status"] == "verified"


def test_patch_recovery_artifact_and_legacy_scrub_share_report_firewall(tmp_path):
    """Patch report secrets cannot survive in recovery artifacts or old SQLite rows."""
    provider = load_provider(tmp_path)
    secret = "ghp_" + "r" * 36
    request = {
        "patch_id": "patch-recovery-report-redaction",
        "outcome": f"applied with {secret}",
        "repository_id": "owner/recovery-report-redaction",
        "producer": f"mcp-code-shrinker-{secret}",
        "source_event_id": "patch:recovery-report-redaction:event",
        "new_content_hash": hashlib.sha256(b"recovery-report-redaction").hexdigest(),
        "changed_files": ["src/recovery_validation.py"],
        "validation_report": {
            "status": "verified",
            "nested": {"message": f"credential={secret}"},
            f"header_{secret}": {"nested": [f"Bearer {secret}"]},
        },
        "rollback_steps": f"Restore using {secret}",
    }
    result = json.loads(provider.handle_tool_call("memory_wiki_patch_outcome_add", request))
    assert result.get("success") is True and result.get("structured") is True, result

    artifact_path = next(
        (tmp_path / "memory-wiki" / "recovery-artifacts" / "patch_outcome_request").glob("*.json"),
    )
    artifact_text = artifact_path.read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)
    assert secret not in artifact_text
    assert "credential=" not in artifact_text
    assert artifact["payload"]["validation_report"]["status"] == "verified"

    # Simulate a row created before the patch-report firewall existed.  It must
    # be repaired through the public apply=True maintenance path, including a
    # token hidden in a JSON property name and one in an ordinary nested value.
    conn = provider._connect()
    conn.execute(
        """INSERT INTO patch_outcomes(
               repository_id,patch_id,claim_id,outcome,commit_sha,
               old_content_hash,new_content_hash,changed_files_json,
               changed_symbols_json,validation_report_json,rollback_steps,
               source_event_id,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "owner/legacy-report-redaction", "legacy-report-redaction", result["id"],
            f"legacy outcome {secret}", "", "", "", "[]", "[]",
            json.dumps({
                "status": "legacy-verified",
                "nested": {"message": f"credential={secret}"},
                f"header_{secret}": {"inner": f"Bearer {secret}"},
            }),
            f"legacy rollback {secret}", "legacy-report-redaction-event", 1, 1,
        ),
    )
    conn.commit()

    scrubbed = provider._scrub_secrets(apply=True, limit=100)
    legacy = conn.execute(
        "SELECT outcome,rollback_steps,validation_report_json FROM patch_outcomes "
        "WHERE repository_id=? AND patch_id=?",
        ("owner/legacy-report-redaction", "legacy-report-redaction"),
    ).fetchone()
    assert legacy is not None
    legacy_text = json.dumps(dict(legacy), ensure_ascii=False)
    assert secret not in legacy_text
    assert "credential=" not in legacy_text
    assert json.loads(str(legacy["validation_report_json"]))["status"] == "legacy-verified"
    assert scrubbed["code_graph"]["fields"] >= 3


def test_patch_event_recovery_artifact_scrubs_validation_report_keys(tmp_path):
    """The Code Shrinker inbox recovery copy uses the patch report firewall."""
    provider = load_provider(tmp_path)
    secret = "ghp_" + "s" * 36
    event = {
        "event_version": 1,
        "type": "patch_applied",
        "producer": "mcp-code-shrinker",
        "event_id": "patch:artifact-report-redaction:event",
        "repository_id": "owner/artifact-report-redaction",
        "patch_id": "patch-artifact-report-redaction",
        "outcome": f"applied with {secret}",
        "changed_files": ["src/artifact_validation.py"],
        "validation_report": {
            "status": "passed",
            "nested": {"message": f"credential={secret}"},
            f"header_{secret}": {"nested": [f"Bearer {secret}"]},
        },
        "rollback_steps": f"Restore using {secret}",
    }
    inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "patch-artifact-report-redaction.json").write_text(
        json.dumps(event), encoding="utf-8",
    )

    result = provider._drain_code_shrinker_events(limit=1)
    assert result["processed"] == 1, result
    artifact_path = next(
        (tmp_path / "memory-wiki" / "recovery-artifacts" / "code-graph-inbox").glob("*.json"),
    )
    artifact_text = artifact_path.read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)
    done_path = next((tmp_path / "context-coordination" / "done" / "code-shrinker").glob("*.json"))
    done_text = done_path.read_text(encoding="utf-8")
    assert secret not in artifact_text
    assert secret not in done_text
    assert "credential=" not in artifact_text
    assert artifact["validation_report"]["status"] == "passed"


def test_snapshot_recovery_artifact_scrubs_arbitrary_json_keys(tmp_path):
    """Unknown producer properties cannot retain a secret in an artifact key."""
    provider = load_provider(tmp_path)
    secret = "ghp_" + "t" * 36
    second_secret = "ghp_" + "u" * 36
    event = {
        "event_version": 2,
        "type": "code_graph_snapshot",
        "graph_schema_version": 1,
        "producer": "mcp-code-shrinker",
        "event_id": "snapshot:artifact-key-redaction:event",
        "repository_id": "owner/artifact-key-redaction",
        "snapshot_mode": "full",
        "snapshot_hash": "artifact-key-redaction-snapshot",
        "safe_metadata": {"status": "legitimate"},
        f"unrelated_{secret}": {"note": "nonsecret control"},
        secret: {"note": "first collision control"},
        second_secret: {"note": "second collision control"},
    }
    inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "snapshot-artifact-key-redaction.json").write_text(
        json.dumps(event), encoding="utf-8",
    )

    result = provider._drain_code_shrinker_events(limit=1)
    assert result["processed"] == 1, result
    artifact_path = next(
        (tmp_path / "memory-wiki" / "recovery-artifacts" / "code-graph-inbox").glob("*.json"),
    )
    artifact_text = artifact_path.read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)
    artifact_event = artifact.get("event", artifact)
    assert secret not in artifact_text
    assert second_secret not in artifact_text
    assert artifact_event["safe_metadata"]["status"] == "legitimate"
    assert "<GITHUB_TOKEN_REDACTED>" in artifact_event
    assert "<GITHUB_TOKEN_REDACTED>_2" in artifact_event


def test_qdrant_reindex_builds_physical_collection_before_alias_switch(tmp_path):
    provider = load_provider(tmp_path)
    module = provider._test_module
    result = provider._code_claim_add({
        "claim": "Verified Hermes configuration runbook: semantic indexing and restore procedure were checked.",
        "topic": "code-shrinker", "repository_id": "owner/repo", "file_path": "src/semantic.js",
        "content_hash": hashlib.sha256(b"semantic source body").hexdigest(), "symbol_id": "sym_semantic", "symbol_revision": "rev1",
        "evidence": "verified exact source and backup restore procedure", "confidence": 0.95, "salience": 0.9,
    })
    assert result.get("id")

    # R21: model the current Qdrant contract, not only point count. _reindex now
    # asks _qdrant_claim_state() for the complete vector/ACL payload contract
    # before deciding whether a collection is complete/reusable.
    points: dict[str, dict[str, dict]] = {}
    switched = []
    created = []
    module.SEMANTIC_ENABLED = True
    module._semantic_available = lambda: True
    module._ensure_collection = lambda collection=None: created.append(collection) or True
    module._embed_document = lambda text: [0.0] * module.QDRANT_VECTOR_SIZE

    def fake_upsert(claim_id, vector, payload, collection=None):
        points.setdefault(collection, {})[claim_id] = dict(payload)
        return True

    module._qdrant_upsert = fake_upsert
    module._qdrant_count = lambda collection=None: len(points.get(collection, {}))
    module._qdrant_claim_state = lambda collection, max_points=200000: {
        claim_id: module._qdrant_claim_reconciliation_state(payload)
        for claim_id, payload in points.get(collection, {}).items()
    }
    module._qdrant_alias_supported = lambda: True
    module._qdrant_alias_target = lambda alias=module.QDRANT_ALIAS: switched[-1] if switched else "old_collection"
    module._switch_alias = lambda collection: switched.append(collection) or True

    first = provider._reindex()
    assert first["status"] == "completed"
    assert first["alias_switched"] is True
    assert switched[-1].startswith(module.QDRANT_COLLECTION + "_")
    assert "_force_" not in switched[-1]

    forced = provider._reindex(force=True)
    assert forced["status"] == "completed"
    assert "_force_" in switched[-1]
    assert created
