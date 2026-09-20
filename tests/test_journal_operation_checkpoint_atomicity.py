#!/usr/bin/env python3
"""Regression: checkpoints/rebuilds cannot cut through a journal operation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import multiprocessing as mp
import os
import sys
import tempfile
import threading
from pathlib import Path


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


def _code_claim(source_event_id: str, file_path: str) -> dict:
    return {
        "claim": "Verified durable code claim for journal ordering recovery regression.",
        "repository_id": "journal-operation-atomicity",
        "file_path": file_path,
        "symbol_id": "journal_boundary",
        "content_hash": hashlib.sha256(source_event_id.encode("utf-8")).hexdigest(),
        "source_event_id": source_event_id,
    }


def _operation_pair_child(
    home: str,
    label: str,
    started,
    release,
    completed,
    outcomes,
) -> None:
    """Run one journal operation in an isolated process for the lock test."""
    try:
        os.environ.update({
            "HERMES_HOME": home,
            "HERMES_SECURITY_STRICT": "0",
            "MEMORY_WIKI_SEMANTIC": "0",
            "MEMORY_WIKI_JOURNAL_SAFETY_CHECKPOINTS": "1",
        })
        module = load_provider(
            f"memory_wiki_journal_operation_process_{label}_{os.getpid()}"
        )
        provider = module.MemoryWikiProvider()
        provider.initialize("journal-operation-process", hermes_home=home, agent_context="test")
        try:
            if label == "second":
                # Signal that this process is about to contend for the
                # operation scope, not that it already reached its mutation.
                started.set()

            def mutate() -> str:
                if label == "first":
                    started.set()
                    if not release.wait(20):
                        raise RuntimeError("test did not release first process")
                return json.dumps({"success": True, "status": "indexed"})

            result, journal = provider._journal_operation(
                "memory_wiki_document_ingest",
                {"path": f"{label}.txt"},
                mutate,
            )
            outcomes.put({
                "label": label,
                "ok": json.loads(result).get("success") is True,
                "before": journal["before"]["seq"],
                "after": journal["after"]["seq"],
            })
            completed.set()
        finally:
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None
    except BaseException as exc:
        outcomes.put({"label": label, "ok": False, "error": repr(exc)})
        completed.set()


def test_processes_cannot_publish_checkpoint_inside_another_journal_pair() -> None:
    """The OS-level operation lock closes the same gap across providers."""
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
        "MEMORY_WIKI_JOURNAL_SAFETY_CHECKPOINTS",
    )
    previous = {key: os.environ.get(key) for key in keys}
    first_process = second_process = None
    release = None
    try:
        with tempfile.TemporaryDirectory(prefix="mw-journal-operation-process-") as tmp:
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_JOURNAL_SAFETY_CHECKPOINTS": "1",
            })
            ctx = mp.get_context("spawn")
            first_started = ctx.Event()
            second_started = ctx.Event()
            first_completed = ctx.Event()
            second_completed = ctx.Event()
            release = ctx.Event()
            outcomes = ctx.Queue()
            first_process = ctx.Process(
                target=_operation_pair_child,
                args=(tmp, "first", first_started, release, first_completed, outcomes),
            )
            second_process = ctx.Process(
                target=_operation_pair_child,
                args=(tmp, "second", second_started, release, second_completed, outcomes),
            )
            first_process.start()
            assert first_started.wait(20), "first process did not reach its mutation"
            second_process.start()
            assert second_started.wait(20), "second process did not enter its operation"

            # A per-append-only lock allows the second process to mutate and
            # checkpoint here.  The operation lock must keep it out until the
            # first pair has an ``after`` record and matching checkpoint.
            assert not second_completed.wait(1.0)
            release.set()
            first_process.join(30)
            second_process.join(30)
            assert first_process.exitcode == 0
            assert second_process.exitcode == 0
            result_rows = [outcomes.get(timeout=10) for _ in range(2)]
            assert all(row["ok"] for row in result_rows), result_rows
            by_label = {row["label"]: row for row in result_rows}
            assert by_label["first"]["after"] < by_label["second"]["before"], by_label

            module = load_provider("memory_wiki_journal_operation_process_parent")
            provider = module.MemoryWikiProvider()
            provider.initialize("journal-operation-process", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._latest_journal_checkpoint()
                assert checkpoint is not None
                plan = provider._rebuild_from_journal(apply=False, checkpoint=str(checkpoint))
                assert plan["incomplete_events"] == 0, plan
                assert plan["unrecoverable_events"] == 0, plan
            finally:
                if provider._conn is not None:
                    provider._conn.close()
                    provider._conn = None
    finally:
        if release is not None:
            release.set()
        for process in (first_process, second_process):
            if process is not None:
                process.join(10)
                if process.is_alive():
                    process.terminate()
                    process.join(10)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_checkpoint_and_rebuild_wait_for_open_code_claim_journal_pair() -> None:
    """A later checkpoint must not see A.before but omit A's durable write.

    Without the operation-level lock, the second code claim can complete its
    before/after/checkpoint while the first claim is paused after ``before``.
    The latest checkpoint then skips the first ``before`` but sees its later
    ``after`` as an orphan during recovery.
    """
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
        "MEMORY_WIKI_JOURNAL_SAFETY_CHECKPOINTS",
    )
    previous = {key: os.environ.get(key) for key in keys}
    first_release = threading.Event()
    first_entered = threading.Event()
    second_started = threading.Event()
    second_reached_mutation = threading.Event()
    planner_started = threading.Event()
    planner_finished = threading.Event()
    workers: list[threading.Thread] = []
    try:
        with tempfile.TemporaryDirectory(prefix="mw-journal-operation-pair-") as tmp:
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_JOURNAL_SAFETY_CHECKPOINTS": "1",
            })
            module = load_provider("memory_wiki_journal_operation_pair_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("journal-operation-pair", hermes_home=tmp, agent_context="test")
            try:
                first = _code_claim("journal-pair-first", "src/first.py")
                second = _code_claim("journal-pair-second", "src/second.py")
                original_code_claim_add = provider._code_claim_add
                results: dict[str, object] = {}
                failures: dict[str, BaseException] = {}

                def gated_code_claim_add(arguments, *extra_args, **extra_kwargs):
                    event_id = str(arguments.get("source_event_id") or "")
                    if event_id == "journal-pair-first":
                        first_entered.set()
                        if not first_release.wait(10):
                            raise RuntimeError("test did not release first journal operation")
                    elif event_id == "journal-pair-second":
                        second_reached_mutation.set()
                    return original_code_claim_add(arguments, *extra_args, **extra_kwargs)

                provider._code_claim_add = gated_code_claim_add

                def write_claim(label: str, arguments: dict, started: threading.Event | None = None) -> None:
                    try:
                        if started is not None:
                            started.set()
                        results[label] = json.loads(
                            provider.handle_tool_call("memory_wiki_code_claim_add", arguments)
                        )
                    except BaseException as exc:  # relay worker failures to the test thread
                        failures[label] = exc

                def plan_rebuild() -> None:
                    try:
                        planner_started.set()
                        results["plan_during_first"] = provider._rebuild_from_journal(apply=False)
                    except BaseException as exc:
                        failures["plan_during_first"] = exc
                    finally:
                        planner_finished.set()

                first_worker = threading.Thread(
                    target=write_claim, args=("first", first), daemon=True,
                )
                workers.append(first_worker)
                first_worker.start()
                assert first_entered.wait(5), "first operation never reached its mutation"

                second_worker = threading.Thread(
                    target=write_claim,
                    args=("second", second, second_started),
                    daemon=True,
                )
                planner_worker = threading.Thread(target=plan_rebuild, daemon=True)
                workers.extend((second_worker, planner_worker))
                second_worker.start()
                assert second_started.wait(5), "second operation never started"
                planner_worker.start()
                assert planner_started.wait(5), "rebuild planner never started"

                # Both must remain behind the first operation's durable
                # before->mutation->after->checkpoint boundary.  On the old
                # implementation the second worker reaches its mutation and
                # publishes a checkpoint during this wait.
                assert not second_reached_mutation.wait(0.75)
                assert not planner_finished.wait(0.75)

                first_release.set()
                for worker in workers:
                    worker.join(15)
                    assert not worker.is_alive(), "journal-operation worker did not finish"
                assert not failures, failures
                assert results["first"]["success"] is True, results
                assert results["second"]["success"] is True, results
                assert results["plan_during_first"]["incomplete_events"] == 0, results

                provider._code_claim_add = original_code_claim_add
                checkpoint = provider._latest_journal_checkpoint()
                assert checkpoint is not None
                plan = provider._rebuild_from_journal(apply=False, checkpoint=str(checkpoint))
                assert plan["incomplete_events"] == 0, plan
                assert plan["unrecoverable_events"] == 0, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=str(checkpoint))
                assert rebuilt["applied"] is True, rebuilt
                assert rebuilt["failed"] == 0, rebuilt
            finally:
                first_release.set()
                for worker in workers:
                    worker.join(15)
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
    test_checkpoint_and_rebuild_wait_for_open_code_claim_journal_pair()
    print("PASS test_checkpoint_and_rebuild_wait_for_open_code_claim_journal_pair")
