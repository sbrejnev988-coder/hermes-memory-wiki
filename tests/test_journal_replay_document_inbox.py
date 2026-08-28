#!/usr/bin/env python3
"""Recovery integration: document inbox manifests replay child source refs without journaling manifest paths."""
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


def journal_strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from journal_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from journal_strings(item)
    elif isinstance(value, str):
        yield value


def test_rebuild_replays_document_inbox_child_reference_without_manifest_contents_in_journal() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC", "MEMORY_WIKI_DOCUMENT_ROOTS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-document-inbox-replay-") as tmp:
            home = Path(tmp); docs = home / "docs"; docs.mkdir(); source = docs / "inbox.md"
            marker = "INBOX_DOCUMENT_RECOVERY_8d22"
            source.write_text(f"# Inbox\n{marker}\n", encoding="utf-8")
            os.environ.update({
                "HERMES_HOME": str(home), "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_DOCUMENT_ROOTS": str(docs),
            })
            module = load_provider("memory_wiki_document_inbox_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("document-inbox-replay", hermes_home=str(home), project_id="repo-inbox")
            try:
                checkpoint = provider._journal_checkpoint("before-document-inbox")
                inbox = home / "context-coordination" / "inbox" / "documents"; inbox.mkdir(parents=True, exist_ok=True)
                manifest = {
                    "event_type": "document_manifest", "scope_id": "repo-inbox", "repository_id": "repo-inbox",
                    "documents": [{"path": str(source)}],
                }
                (inbox / "event.json").write_text(json.dumps(manifest), encoding="utf-8")
                live = json.loads(provider.handle_tool_call("memory_wiki_document_ingest_inbox", {"limit": 1}))
                assert live["success"] is True and len(live["processed"]) == 1, live
                source_id = live["processed"][0]["results"][0]["source_id"]
                journal = provider.journal_path.read_text(encoding="utf-8")
                journal_values = list(journal_strings([json.loads(line) for line in journal.splitlines() if line.strip()]))
                assert str(source) not in journal_values and marker not in journal_values
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                restored = provider._connect().execute(
                    "SELECT active FROM document_sources WHERE source_id=?", (source_id,)
                ).fetchone()
                assert restored is not None and int(restored[0]) == 1
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_rebuild_replays_document_inbox_child_reference_without_manifest_contents_in_journal()
    print("PASS test_rebuild_replays_document_inbox_child_reference_without_manifest_contents_in_journal")
