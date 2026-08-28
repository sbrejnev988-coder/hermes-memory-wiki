#!/usr/bin/env python3
"""Regression: auto-embed also drains unchanged sources with pending chunks."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"
sys.path.insert(0, str(MODULE.parent))


def load_module(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class Provider:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _connect(self) -> sqlite3.Connection:
        return self.conn


def test_auto_embed_processes_pending_unchanged_source() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "MEMORY_WIKI_DOCUMENT_ROOTS")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-auto-embed-") as tmp:
            home = Path(tmp)
            root = home / "cache" / "documents"
            root.mkdir(parents=True)
            document = root / "note.md"
            document.write_text("# Note\n\nPending document chunk\n", encoding="utf-8")
            stat = document.stat()
            os.environ["HERMES_HOME"] = str(home)
            os.environ["MEMORY_WIKI_DOCUMENT_ROOTS"] = str(root)
            module = load_module("memory_wiki_auto_embed_unchanged_test")
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            module.install_document_graph_schema(conn)
            source_id = "docsrc_pending"
            conn.execute(
                """INSERT INTO document_sources(
                    source_id,source_path,display_name,mtime_ns,size_bytes,parser_version,
                    revision_id,status,active,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    source_id, str(document.resolve()), document.name, stat.st_mtime_ns,
                    stat.st_size, module._CURRENT_PARSER_VERSION, "docrev_pending", "ok", 1, 1, 1,
                ),
            )
            conn.execute(
                """INSERT INTO document_chunks(
                    chunk_id,source_id,revision_id,content_hash,chunk_text,embedding_text,active,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                ("docchunk_pending", source_id, "docrev_pending", "hash", "Pending document chunk", "Pending document chunk", 1, 1),
            )
            conn.commit()
            provider = Provider(conn)
            calls: list[dict] = []
            module.embed_pending_documents = lambda _provider, args: calls.append(dict(args)) or {"processed": 1}

            result = module.scan_documents(
                provider,
                {
                    "root": str(root),
                    "recursive": True,
                    "stat_fast_path": True,
                    "embed": True,
                    "max_files": 10,
                },
            )
            conn.close()

            assert result["unchanged"] == 1
            assert calls == [{"source_id": source_id, "limit": 200}]
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_auto_embed_processes_pending_unchanged_source()
    print("PASS test_auto_embed_processes_pending_unchanged_source")
