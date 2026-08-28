#!/usr/bin/env python3
"""Recovery regression: document ingest replays from a content-free source reference."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
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


def test_rebuild_replays_document_ingest_from_hashed_source_reference_without_journaling_path_or_text() -> None:
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
        "MEMORY_WIKI_DOCUMENT_ROOTS", "MEMORY_WIKI_DOCUMENT_CACHE_DIR",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-document-replay-") as tmp:
            home = Path(tmp)
            docs = home / "documents"
            docs.mkdir()
            source = docs / "recovery.md"
            marker = "DOCUMENT_RECOVERY_SOURCE_SENTINEL_7f3d"
            source.write_text(f"# Recovery\n\n{marker}\n", encoding="utf-8")
            os.environ.update({
                "HERMES_HOME": str(home),
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_DOCUMENT_ROOTS": str(docs),
                "MEMORY_WIKI_DOCUMENT_CACHE_DIR": str(docs),
            })
            module = load_provider("memory_wiki_document_source_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("document-source-replay", hermes_home=str(home), project_id="repo-replay")
            try:
                checkpoint = provider._journal_checkpoint("before-document-source-replay")
                live = json.loads(provider.handle_tool_call(
                    "memory_wiki_document_ingest",
                    {"path": str(source), "scope_id": "repo-replay", "repository_id": "repo-replay"},
                ))
                assert live["success"] is True and live["status"] == "indexed", live
                source_id = live["source_id"]

                journal_text = provider.journal_path.read_text(encoding="utf-8")
                assert str(source) not in journal_text
                assert marker not in journal_text
                assert "document_source_ref/v1" in journal_text

                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] >= 1, rebuilt
                row = provider._connect().execute(
                    "SELECT source_id,file_hash,active FROM document_sources WHERE source_id=?", (source_id,)
                ).fetchone()
                assert row is not None and int(row["active"]) == 1
                unit = provider._connect().execute(
                    "SELECT 1 FROM document_units WHERE source_id=? AND active=1 AND unit_text LIKE ? LIMIT 1",
                    (source_id, f"%{marker}%"),
                ).fetchone()
                assert unit is not None
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
    test_rebuild_replays_document_ingest_from_hashed_source_reference_without_journaling_path_or_text()
    print("PASS test_rebuild_replays_document_ingest_from_hashed_source_reference_without_journaling_path_or_text")
