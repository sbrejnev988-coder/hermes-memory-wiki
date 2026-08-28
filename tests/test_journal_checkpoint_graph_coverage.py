#!/usr/bin/env python3
"""Regression: journal checkpoints include durable code and document graph state."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
EXPECTED_TABLES = {
    "code_claim_metadata",
    "code_graph_repositories",
    "code_graph_files",
    "code_graph_symbols",
    "code_graph_chunks",
    "code_graph_lines",
    "code_graph_edges",
    "code_graph_events",
    "document_graph_meta",
    "document_sources",
    "document_revisions",
    "document_units",
    "document_chunks",
    "document_edges",
    "document_events",
}


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_checkpoint_includes_durable_code_and_document_graph_tables() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-checkpoint-graphs-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_checkpoint_graphs_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("checkpoint-graphs-test", hermes_home=tmp, agent_context="test")
            try:
                content_hash = "b" * 64
                with provider._connect() as conn:
                    conn.execute(
                        """INSERT INTO claims(
                            id,claim,topic,status,confidence,salience,source,evidence,
                            created_at,updated_at,freshness_at,access_count,last_accessed,hash
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        ("c_checkpoint_hash", "Verified checkpoint hash fixture.", "tests", "active",
                         0.9, 0.9, "test", "", 1, 1, 1, 0, 0, "checkpoint-hash-fixture"),
                    )
                    conn.execute(
                        """INSERT INTO code_claim_metadata(
                            claim_id,repository_id,commit_sha,file_path,symbol_id,symbol_revision,content_hash,claim_type
                        ) VALUES(?,?,?,?,?,?,?,?)""",
                        ("c_checkpoint_hash", "repo-checkpoint", "", "src/checkpoint.py", "fixture", "", content_hash, "code_claim"),
                    )
                checkpoint = provider._journal_checkpoint("graph-coverage")
                payload = json.loads(Path(checkpoint["path"]).read_text(encoding="utf-8"))
                missing = EXPECTED_TABLES - set(payload["tables"])
                assert not missing, f"checkpoint omits durable graph tables: {sorted(missing)}"
                metadata = next(
                    row for row in payload["tables"]["code_claim_metadata"]
                    if row["claim_id"] == "c_checkpoint_hash"
                )
                assert metadata["content_hash"] == content_hash
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
    test_checkpoint_includes_durable_code_and_document_graph_tables()
    print("PASS test_checkpoint_includes_durable_code_and_document_graph_tables")
