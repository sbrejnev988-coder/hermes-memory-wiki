#!/usr/bin/env python3
"""Regression: auto-cache cooldowns do not append no-op journal events every turn."""
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


def test_auto_document_cache_cooldown_does_not_create_noop_journal_pairs() -> None:
    keys = (
        "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC", "MEMORY_WIKI_DOCUMENT_ROOTS",
        "MEMORY_WIKI_DOCUMENT_CACHE_DIR", "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE",
        "MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID", "MEMORY_WIKI_DOCUMENT_AUTO_REPOSITORY_ID",
        "MEMORY_WIKI_DOCUMENT_AUTO_MIN_AGE_SECONDS", "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_SECONDS",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-auto-cooldown-") as tmp:
            home = Path(tmp); cache = home / "cache" / "documents"; cache.mkdir(parents=True)
            source = cache / "once.md"; source.write_text("# once\n", encoding="utf-8")
            old = time.time() - 3; os.utime(source, (old, old))
            os.environ.update({
                "HERMES_HOME": str(home), "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_DOCUMENT_ROOTS": str(cache), "MEMORY_WIKI_DOCUMENT_CACHE_DIR": str(cache),
                "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE": "1", "MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID": "repo-auto",
                "MEMORY_WIKI_DOCUMENT_AUTO_REPOSITORY_ID": "repo-auto", "MEMORY_WIKI_DOCUMENT_AUTO_MIN_AGE_SECONDS": "2",
                "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_SECONDS": "300",
            })
            module = load_provider("memory_wiki_auto_cooldown_test")
            provider = module.MemoryWikiProvider(); provider.initialize("auto-cooldown", hermes_home=str(home), project_id="repo-auto")
            try:
                provider.on_turn_start(1, "first")
                after_first = provider._journal_status(verify=True)["events_total"]
                provider.on_turn_start(2, "second")
                after_second = provider._journal_status(verify=True)["events_total"]
                assert after_first >= 2
                assert after_second == after_first
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_auto_document_cache_cooldown_does_not_create_noop_journal_pairs()
    print("PASS test_auto_document_cache_cooldown_does_not_create_noop_journal_pairs")
