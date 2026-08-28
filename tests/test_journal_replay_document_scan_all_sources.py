#!/usr/bin/env python3
"""Regression: every source in an oversized document scan must survive journal replay."""
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


def test_document_scan_replay_captures_all_sources_beyond_display_result_cap() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC", "MEMORY_WIKI_DOCUMENT_ROOTS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-scan-all-recovery-") as tmp:
            home = Path(tmp); docs = home / "docs"; docs.mkdir()
            for index in range(201):
                (docs / f"document-{index:03d}.md").write_text(f"# {index}\nscan-recovery-{index}\n", encoding="utf-8")
            os.environ.update({
                "HERMES_HOME": str(home), "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_DOCUMENT_ROOTS": str(docs),
            })
            module = load_provider("memory_wiki_scan_all_recovery_test")
            provider = module.MemoryWikiProvider(); provider.initialize("scan-all", hermes_home=str(home), project_id="repo-scan-all")
            try:
                checkpoint = provider._journal_checkpoint("before-large-scan")
                live = json.loads(provider.handle_tool_call("memory_wiki_document_scan", {
                    "root": str(docs), "scope_id": "repo-scan-all", "repository_id": "repo-scan-all",
                    "max_files": 201,
                }))
                assert live["success"] is True and live["indexed"] == 201, live
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0 and plan["incomplete_events"] == 0, plan
                provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                count = provider._connect().execute("SELECT COUNT(*) FROM document_sources WHERE active=1").fetchone()[0]
                assert int(count) == 201
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_document_scan_replay_captures_all_sources_beyond_display_result_cap()
    print("PASS test_document_scan_replay_captures_all_sources_beyond_display_result_cap")
