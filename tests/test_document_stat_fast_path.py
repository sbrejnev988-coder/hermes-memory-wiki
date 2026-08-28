#!/usr/bin/env python3
"""Regression: timestamp-only unchanged detection needs an explicit trust opt-in."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_document_stat_fast_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    project_scope = "scope-A"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _connect(self) -> sqlite3.Connection:
        return self.conn


def test_stat_fast_path_is_ignored_without_trusted_store_opt_in() -> None:
    keys = (
        "HERMES_HOME", "MEMORY_WIKI_DOCUMENT_ROOTS", "MEMORY_WIKI_DOCUMENT_ALLOW_STAT_FAST_PATH",
        "MEMORY_WIKI_DOCUMENT_CACHE_DIR", "HERMES_DOCUMENT_CACHE_DIR",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-stat-fast-") as tmp:
            home = Path(tmp)
            docs = home / "cache" / "documents"
            docs.mkdir(parents=True)
            path = docs / "same.txt"
            path.write_text("same stat but require hash", encoding="utf-8")
            stat = path.stat()
            os.environ["HERMES_HOME"] = str(home)
            for key in (
                "MEMORY_WIKI_DOCUMENT_ROOTS",
                "MEMORY_WIKI_DOCUMENT_ALLOW_STAT_FAST_PATH",
                "MEMORY_WIKI_DOCUMENT_CACHE_DIR",
                "HERMES_DOCUMENT_CACHE_DIR",
            ):
                os.environ.pop(key, None)
            module = load_module()
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            provider = Provider(conn)
            module.install_document_graph_schema(conn)
            conn.execute(
                """INSERT INTO document_sources(
                    source_id,scope_id,repository_id,source_path,display_name,extension,
                    mtime_ns,size_bytes,parser,parser_version,revision_id,status,active,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("source", "scope-A", "scope-A", str(path.resolve()), path.name, ".txt",
                 stat.st_mtime_ns, stat.st_size, "fixture", module._CURRENT_PARSER_VERSION,
                 "revision", "active", 1, 1, 1),
            )
            conn.commit()
            calls = []

            def fake_ingest(_provider, args):
                calls.append(args["path"])
                return {"status": "indexed"}

            module.ingest_document = fake_ingest
            result = module.scan_documents(
                provider,
                {
                    "root": str(docs),
                    "recursive": False,
                    "max_files": 1,
                    "max_changed": 1,
                    "stat_fast_path": True,
                    "scope_id": "scope-A",
                    "repository_id": "scope-A",
                },
            )
            assert calls == [str(path)]
            assert result["indexed"] == 1
            conn.close()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_stat_fast_path_is_ignored_without_trusted_store_opt_in()
    print("PASS test_stat_fast_path_is_ignored_without_trusted_store_opt_in")
