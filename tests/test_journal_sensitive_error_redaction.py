#!/usr/bin/env python3
"""Regression: failed sensitive mutations do not place exception text or source paths in JSONL."""
from __future__ import annotations

import importlib.util
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


def test_failed_document_journal_operation_redacts_error_text_and_request_path() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-sensitive-error-journal-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_sensitive_error_journal_test")
            provider = module.MemoryWikiProvider(); provider.initialize("sensitive-error", hermes_home=tmp, agent_context="test")
            marker = "SENSITIVE_DOCUMENT_ERROR_SENTINEL_01ef"
            source = str(Path(tmp) / f"{marker}.md")
            try:
                try:
                    provider._journal_operation(
                        "memory_wiki_document_ingest", {"path": source},
                        lambda: (_ for _ in ()).throw(RuntimeError(marker)),
                    )
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("synthetic failure unexpectedly succeeded")
                journal = provider.journal_path.read_text(encoding="utf-8")
                assert marker not in journal and source not in journal
                assert "sensitive mutation failed" in journal
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_failed_document_journal_operation_redacts_error_text_and_request_path()
    print("PASS test_failed_document_journal_operation_redacts_error_text_and_request_path")
