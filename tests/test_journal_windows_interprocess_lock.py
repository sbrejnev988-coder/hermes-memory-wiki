#!/usr/bin/env python3
"""Regression: concurrent Windows writers serialize journal sequence/hash updates."""
from __future__ import annotations

import importlib.util
import json
import multiprocessing as mp
import os
import sys
import tempfile
import time
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


def child_append(home: str, start, results) -> None:
    os.environ["HERMES_HOME"] = home
    os.environ["HERMES_SECURITY_STRICT"] = "0"
    os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
    module = load_provider(f"memory_wiki_journal_child_{os.getpid()}")
    provider = module.MemoryWikiProvider()
    provider.initialize("journal-lock-test", hermes_home=home, agent_context="test")
    original_read = provider._read_journal_meta

    def deliberately_slow_read():
        result = original_read()
        # Without an interprocess lock both child processes read the same seq/hash.
        time.sleep(0.35)
        return result

    provider._read_journal_meta = deliberately_slow_read
    try:
        if not start.wait(10):
            raise RuntimeError("start signal timed out")
        event = provider._append_journal_event("concurrent-lock-regression", {"pid": os.getpid()})
        results.put({"ok": True, "seq": event["seq"]})
    except Exception as exc:
        results.put({"ok": False, "error": repr(exc)})
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_concurrent_journal_append_has_unique_sequence_and_chain() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-journal-lock-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_journal_lock_parent")
            bootstrap = module.MemoryWikiProvider()
            bootstrap.initialize("journal-lock-test", hermes_home=tmp, agent_context="test")
            journal_path = Path(bootstrap.journal_path)
            if bootstrap._conn is not None:
                bootstrap._conn.close()
                bootstrap._conn = None

            ctx = mp.get_context("spawn")
            start = ctx.Event()
            results = ctx.Queue()
            workers = [ctx.Process(target=child_append, args=(tmp, start, results)) for _ in range(2)]
            for worker in workers:
                worker.start()
            start.set()
            for worker in workers:
                worker.join(20)
                assert worker.exitcode == 0, f"child did not finish cleanly: {worker.exitcode}"
            child_results = [results.get(timeout=5) for _ in workers]
            assert all(item["ok"] for item in child_results), child_results

            events = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if json.loads(line).get("op") == "concurrent-lock-regression"
            ]
            assert len(events) == 2
            events.sort(key=lambda event: event["seq"])
            assert [event["seq"] for event in events] == [1, 2]
            assert events[1]["prev_hash"] == events[0]["hash"]
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_concurrent_journal_append_has_unique_sequence_and_chain()
    print("PASS test_concurrent_journal_append_has_unique_sequence_and_chain")
