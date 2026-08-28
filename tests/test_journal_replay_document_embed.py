#!/usr/bin/env python3
"""Recovery integration: document embedding mutations recompute from restored chunks."""
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


def test_rebuild_recomputes_document_embeddings_from_recovered_source_refs() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC", "MEMORY_WIKI_DOCUMENT_ROOTS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-document-embed-replay-") as tmp:
            home = Path(tmp); docs = home / "docs"; docs.mkdir(); source = docs / "embed.md"
            source.write_text("# Verified recovery document\nThis source is safe for semantic recovery testing.\n", encoding="utf-8")
            os.environ.update({
                "HERMES_HOME": str(home), "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_DOCUMENT_ROOTS": str(docs),
            })
            module = load_provider("memory_wiki_document_embed_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("document-embed-replay", hermes_home=str(home), project_id="repo-embed")
            provider._make_secret_index_from_raw = lambda *_args, **_kwargs: ""
            try:
                checkpoint = provider._journal_checkpoint("before-document-embed")
                indexed = json.loads(provider.handle_tool_call("memory_wiki_document_ingest", {
                    "path": str(source), "scope_id": "repo-embed", "repository_id": "repo-embed", "embed": False,
                }))
                assert indexed["success"] is True, indexed
                embedded = json.loads(provider.handle_tool_call("memory_wiki_document_embed_pending", {
                    "source_id": indexed["source_id"], "scope_id": "repo-embed", "repository_id": "repo-embed", "limit": 50,
                }))
                assert embedded["success"] is True and embedded["failed"] == 0, embedded
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                count = provider._connect().execute(
                    "SELECT COUNT(*) FROM document_chunks WHERE source_id=? AND active=1 AND embedding_claim_id<>''",
                    (indexed["source_id"],),
                ).fetchone()[0]
                assert int(count) > 0
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_rebuild_recomputes_document_embeddings_from_recovered_source_refs()
    print("PASS test_rebuild_recomputes_document_embeddings_from_recovered_source_refs")
