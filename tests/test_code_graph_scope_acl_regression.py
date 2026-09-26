"""Code graph reads must use the caller's project scope, not DB-wide repo labels."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


GRAPH_PATH = Path(__file__).resolve().parents[1] / "code_knowledge_graph.py"
spec = importlib.util.spec_from_file_location("code_graph_scope_acl_regression", GRAPH_PATH)
assert spec and spec.loader
code_graph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(code_graph)


class Provider:
    project_scope = "repo-A"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _connect(self) -> sqlite3.Connection:
        return self.conn

    def _search(self, *_args, **_kwargs) -> list:
        return []  # No network, embeddings, or billable provider calls.


@pytest.fixture
def graph_fixture(monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_PREFETCH", "1")
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_RERANK", "0")
    connections = []

    def create(*repositories: str) -> Provider:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        connections.append(conn)
        code_graph.install_code_graph_schema(conn)
        for repo in repositories:
            conn.execute(
                "INSERT INTO code_graph_repositories(repository_id) VALUES(?)", (repo,)
            )
            conn.execute(
                "INSERT INTO code_graph_chunks(repository_id,chunk_id,file_path,chunk_text,search_text) "
                "VALUES(?,?,?,?,?)",
                (repo, "chunk-1", "src/parser.py", f"scopeprobe visible content from {repo}", "scopeprobe"),
            )
            conn.execute(
                "INSERT INTO code_graph_chunks_fts(repository_id,chunk_id,file_path,search_text,chunk_text) "
                "VALUES(?,?,?,?,?)",
                (repo, "chunk-1", "src/parser.py", "scopeprobe", f"scopeprobe visible content from {repo}"),
            )
        conn.commit()
        return Provider(conn)

    yield create
    for conn in connections:
        conn.close()


def test_explicit_foreign_repository_is_rejected(graph_fixture) -> None:
    provider = graph_fixture("repo-A", "repo-B")
    with pytest.raises(PermissionError, match="repository"):
        code_graph.query_code_graph(provider, {"query": "scopeprobe", "repository_id": "repo-B"})


def test_empty_repository_defaults_to_active_scope(graph_fixture) -> None:
    provider = graph_fixture("repo-A", "repo-B")
    result = code_graph.query_code_graph(provider, {"query": "scopeprobe", "repository_id": ""})
    assert result["repository_id"] == "repo-A"
    assert result["results"]
    assert {hit["repository_id"] for hit in result["results"]} == {"repo-A"}
    assert "repo-B" not in repr(result)


def test_prefetch_does_not_inject_only_foreign_repository(graph_fixture) -> None:
    provider = graph_fixture("repo-B")
    context = code_graph.maybe_prefetch_code_context(provider, "repo-B function scopeprobe")
    assert context == ""


def test_active_repository_remains_queryable(graph_fixture) -> None:
    provider = graph_fixture("repo-A", "repo-B")
    result = code_graph.query_code_graph(provider, {"query": "scopeprobe", "repository_id": "repo-A"})
    assert result["repository_id"] == "repo-A"
    assert result["results"]
    assert {hit["repository_id"] for hit in result["results"]} == {"repo-A"}


def test_active_repository_remains_prefetchable(graph_fixture) -> None:
    provider = graph_fixture("repo-A")
    context = code_graph.maybe_prefetch_code_context(provider, "repo-A function scopeprobe")
    assert "scopeprobe visible content from repo-A" in context


def test_query_without_project_scope_fails_closed(graph_fixture) -> None:
    provider = graph_fixture("repo-B")
    provider.project_scope = ""
    with pytest.raises(PermissionError, match="scope"):
        code_graph.query_code_graph(provider, {"query": "scopeprobe", "repository_id": "repo-B"})
