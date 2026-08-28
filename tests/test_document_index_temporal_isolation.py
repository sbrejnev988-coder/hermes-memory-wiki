#!/usr/bin/env python
"""Regression: document chunks are historical artifacts, not temporal facts."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

PLUGIN_PATH = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN_PATH, submodule_search_locations=[str(PLUGIN_PATH.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_document_index_claims_do_not_temporally_supersede() -> None:
    old_home = os.environ.get("HERMES_HOME")
    old_semantic = os.environ.get("MEMORY_WIKI_SEMANTIC")
    try:
        with tempfile.TemporaryDirectory(prefix="mw-document-temporal-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("mw_document_temporal_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("test-session", hermes_home=tmp, agent_context="test")
            first = provider._add_claim(
                "Document snapshot now uses model 2.0.",
                topic="document-intelligence",
                source="artifact:document-index",
                evidence="document_chunk_ref:abcd1234-efgh5678",
            )
            second = provider._add_claim(
                "Document snapshot now uses model 3.0.",
                topic="document-intelligence",
                source="artifact:document-index",
                evidence="document_chunk_ref:ijkl9012-mnop3456",
            )
            rows = provider._connect().execute(
                "SELECT id,status FROM claims WHERE id IN (?,?) ORDER BY id", (first, second)
            ).fetchall()
            actual = {row["id"]: row["status"] for row in rows}
            if provider._conn is not None:
                provider._conn.close()
            assert actual == {
                first: "active", second: "active"
            }
            if provider._conn is not None:
                provider._conn.close()
    finally:
        if old_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = old_home
        if old_semantic is None:
            os.environ.pop("MEMORY_WIKI_SEMANTIC", None)
        else:
            os.environ["MEMORY_WIKI_SEMANTIC"] = old_semantic


if __name__ == "__main__":
    test_document_index_claims_do_not_temporally_supersede()
    print("PASS test_document_index_claims_do_not_temporally_supersede")
