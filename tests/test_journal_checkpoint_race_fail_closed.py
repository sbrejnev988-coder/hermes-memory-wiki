#!/usr/bin/env python3
"""Regression: a raced post-mutation checkpoint cannot hide a later incomplete before-event."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_raced_checkpoint_is_removed_and_recovery_stays_fail_closed() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-checkpoint-race-", ignore_cleanup_errors=True) as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_checkpoint_race_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("checkpoint-race", hermes_home=tmp, agent_context="test")
            try:
                real_checkpoint = provider._journal_checkpoint
                injected = False

                def raced_checkpoint(name="", **kwargs):
                    nonlocal injected
                    if not injected:
                        injected = True
                        provider._append_journal_event(
                            "memory_wiki_document_ingest", {"path": "interrupted.md"}, phase="before"
                        )
                    return real_checkpoint(name, **kwargs)

                provider._journal_checkpoint = raced_checkpoint
                _result, journal = provider._journal_operation(
                    "memory_wiki_document_ingest", {"path": "completed.md"},
                    lambda: json.dumps({"success": True, "status": "indexed"}),
                )
                assert journal["checkpoint"].get("error"), journal
                plan = provider._rebuild_from_journal(apply=False)
                assert plan["incomplete_events"] >= 1, plan
                try:
                    provider._rebuild_from_journal(apply=True)
                except RuntimeError as exc:
                    assert "incomplete" in str(exc)
                else:
                    raise AssertionError("raced incomplete event did not block recovery")
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
    test_raced_checkpoint_is_removed_and_recovery_stays_fail_closed()
    print("PASS test_raced_checkpoint_is_removed_and_recovery_stays_fail_closed")
