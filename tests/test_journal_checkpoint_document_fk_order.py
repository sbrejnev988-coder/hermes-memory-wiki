#!/usr/bin/env python3
"""Checkpoint restore must honor document graph foreign-key dependencies."""
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


def test_checkpoint_restore_orders_document_sources_before_revisions_and_children() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC", "MEMORY_WIKI_DOCUMENT_ROOTS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-checkpoint-doc-fk-") as tmp:
            home = Path(tmp); docs = home / "docs"; docs.mkdir(); source = docs / "document.md"
            source.write_text("# Checkpoint\nforeign key ordering\n", encoding="utf-8")
            os.environ.update({
                "HERMES_HOME": str(home), "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_DOCUMENT_ROOTS": str(docs),
            })
            module = load_provider("memory_wiki_checkpoint_doc_fk_test")
            provider = module.MemoryWikiProvider(); provider.initialize("checkpoint-doc-fk", hermes_home=str(home), project_id="repo-checkpoint-doc")
            try:
                live = json.loads(provider.handle_tool_call("memory_wiki_document_ingest", {
                    "path": str(source), "scope_id": "repo-checkpoint-doc", "repository_id": "repo-checkpoint-doc",
                }))
                assert live["success"] is True, live
                source_id = live["source_id"]
                checkpoint = provider._journal_checkpoint("document-fk-order")
                provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                row = provider._connect().execute("SELECT active FROM document_sources WHERE source_id=?", (source_id,)).fetchone()
                assert row is not None and int(row[0]) == 1
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_checkpoint_restore_orders_document_sources_before_revisions_and_children()
    print("PASS test_checkpoint_restore_orders_document_sources_before_revisions_and_children")
