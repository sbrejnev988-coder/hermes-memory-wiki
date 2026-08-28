#!/usr/bin/env python3
"""Recovery regression: automatic attachment-cache ingestion has the same journal boundary as manual scans."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_automatic_document_cache_ingest_is_journaled_with_content_free_source_reference() -> None:
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC", "MEMORY_WIKI_DOCUMENT_ROOTS",
        "MEMORY_WIKI_DOCUMENT_CACHE_DIR", "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE",
        "MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID", "MEMORY_WIKI_DOCUMENT_AUTO_REPOSITORY_ID",
        "MEMORY_WIKI_DOCUMENT_AUTO_MIN_AGE_SECONDS", "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_SECONDS",
        "MEMORY_WIKI_DOCUMENT_AUTO_EMBED",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-auto-cache-replay-") as tmp:
            home = Path(tmp); cache = home / "cache" / "documents"; cache.mkdir(parents=True)
            marker = "AUTO_CACHE_RECOVERY_SENTINEL_4d61"; source = cache / "auto.md"
            source.write_text(f"# Automatic cache\n{marker}\n", encoding="utf-8")
            old = time.time() - 3; os.utime(source, (old, old))
            os.environ.update({
                "HERMES_HOME": str(home), "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_DOCUMENT_ROOTS": str(cache), "MEMORY_WIKI_DOCUMENT_CACHE_DIR": str(cache),
                "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE": "1", "MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID": "repo-auto",
                "MEMORY_WIKI_DOCUMENT_AUTO_REPOSITORY_ID": "repo-auto", "MEMORY_WIKI_DOCUMENT_AUTO_MIN_AGE_SECONDS": "2",
                "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_SECONDS": "1", "MEMORY_WIKI_DOCUMENT_AUTO_EMBED": "0",
            })
            module = load_provider("memory_wiki_auto_cache_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("auto-cache-replay", hermes_home=str(home), project_id="repo-auto")
            try:
                checkpoint = provider._journal_checkpoint("before-auto-cache")
                provider.on_turn_start(1, "hello")
                journal = provider.journal_path.read_text(encoding="utf-8")
                assert marker not in journal and str(source) not in journal
                assert "document_source_ref/v1" in journal
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0 and plan["events_to_replay"] >= 1, plan
                provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                count = provider._connect().execute("SELECT COUNT(*) FROM document_sources WHERE active=1").fetchone()[0]
                assert int(count) == 1
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_automatic_document_cache_ingest_is_journaled_with_content_free_source_reference()
    print("PASS test_automatic_document_cache_ingest_is_journaled_with_content_free_source_reference")
