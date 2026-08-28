#!/usr/bin/env python3
"""Regression: ambiguous code-prefetch must not query every repository."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "code_knowledge_graph.py"


def load_module():
    spec = importlib.util.spec_from_file_location("memory_wiki_code_prefetch_scope_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _connect(self) -> sqlite3.Connection:
        return self.conn


def test_ambiguous_prefetch_skips_cross_repository_query() -> None:
    module = load_module()
    previous = os.environ.get("MEMORY_WIKI_CODE_GRAPH_PREFETCH")
    try:
        os.environ["MEMORY_WIKI_CODE_GRAPH_PREFETCH"] = "1"
        with tempfile.TemporaryDirectory(prefix="mw-code-prefetch-") as tmp:
            conn = sqlite3.connect(str(Path(tmp) / "graph.sqlite3"))
            try:
                provider = Provider(conn)
                module.install_code_graph_schema(conn)
                conn.executemany(
                    """INSERT INTO code_graph_repositories(
                        repository_id,root,commit_sha,graph_revision,snapshot_hash,generated_at,updated_at,stats_json
                    ) VALUES(?,?,?,?,?,?,?,?)""",
                    [
                        ("repo-A", "", "", "", "a" * 64, 1, 1, "{}"),
                        ("repo-B", "", "", "", "b" * 64, 1, 1, "{}"),
                    ],
                )
                conn.commit()

                def fail_if_called(*_args, **_kwargs):
                    raise AssertionError("ambiguous prefetch queried all repositories")

                module.query_code_graph = fail_if_called
                assert module.maybe_prefetch_code_context(provider, "src/parser.py function lookup") == ""
            finally:
                conn.close()
    finally:
        if previous is None:
            os.environ.pop("MEMORY_WIKI_CODE_GRAPH_PREFETCH", None)
        else:
            os.environ["MEMORY_WIKI_CODE_GRAPH_PREFETCH"] = previous


if __name__ == "__main__":
    test_ambiguous_prefetch_skips_cross_repository_query()
    print("PASS test_ambiguous_prefetch_skips_cross_repository_query")
