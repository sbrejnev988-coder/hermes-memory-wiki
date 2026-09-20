"""Entity graph search must filter all rows before applying its result limit."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def test_graph_query_finds_old_rows_without_substring_matches(monkeypatch) -> None:
    # Legacy graph rows have no ownership field and require an explicit
    # single-authorization-domain opt-in before they can be queried.
    monkeypatch.setenv("MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_GRAPH", "1")
    spec = importlib.util.spec_from_file_location(
        "memory_wiki_entity_graph_query_test", PLUGIN,
        submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE entities (id TEXT, name TEXT, aliases TEXT, notes TEXT, updated_at INTEGER)"
    )
    conn.execute(
        "CREATE TABLE relations (id TEXT, subject TEXT, predicate TEXT, object TEXT, "
        "evidence TEXT, created_at INTEGER)"
    )
    conn.execute("INSERT INTO entities VALUES ('old-cat', 'cat', '[]', '', 1)")
    conn.execute("INSERT INTO relations VALUES ('old-rel', 'pet', 'related_to', 'home', 'cat', 1)")
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?, '[]', '', ?)",
        ((f"entity-{i}", f"catalog{i}", i + 2) for i in range(600)),
    )
    conn.executemany(
        "INSERT INTO relations VALUES (?, ?, 'related_to', 'home', '', ?)",
        ((f"relation-{i}", f"catalog{i}", i + 2) for i in range(1100)),
    )
    provider = module.MemoryWikiProvider()
    provider._conn = conn
    try:
        found = provider._graph_query("cat", limit=10)
        assert [row["id"] for row in found["entities"]] == ["old-cat"]
        assert [row["id"] for row in found["relations"]] == ["old-rel"]
        assert provider._graph_query("catalog", limit=10) == {"entities": [], "relations": []}
    finally:
        conn.close()
        provider._conn = None
