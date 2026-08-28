#!/usr/bin/env python3
"""Regression: logical checkpoints preserve non-secret SQLite meta values."""
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


def test_checkpoint_preserves_meta_values_needed_for_recovery() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-checkpoint-meta-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_checkpoint_meta_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("checkpoint-meta-test", hermes_home=tmp, agent_context="test")
            try:
                expected = str(
                    provider._connect().execute(
                        "SELECT value FROM meta WHERE key='memory_revision'"
                    ).fetchone()[0]
                )
                with provider._connect() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO document_graph_meta(key,value) VALUES(?,?)",
                        ("schema_version", "1"),
                    )
                checkpoint = provider._journal_checkpoint("meta-regression")
                payload = json.loads(Path(checkpoint["path"]).read_text(encoding="utf-8"))
                meta_rows = {row["key"]: str(row["value"]) for row in payload["tables"]["meta"]}
                doc_meta_rows = {
                    row["key"]: str(row["value"])
                    for row in payload["tables"]["document_graph_meta"]
                }
                assert meta_rows["memory_revision"] == expected
                assert meta_rows["memory_revision"] != "<redacted>"
                assert doc_meta_rows["schema_version"] == "1"
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
    test_checkpoint_preserves_meta_values_needed_for_recovery()
    print("PASS test_checkpoint_preserves_meta_values_needed_for_recovery")
