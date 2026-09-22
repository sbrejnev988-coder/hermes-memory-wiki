from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def provider(module, home: Path, session: str, project: str = "project-a"):
    value = module.MemoryWikiProvider()
    value.initialize(session, hermes_home=str(home), bot_id="temporal-bot", project_id=project)
    return value


def add(provider, text: str, *, visibility: str = "chat", project: str = "") -> str:
    return provider._add_claim(
        text,
        topic="server",
        source="memory_tool:test",
        confidence=0.9,
        salience=0.9,
        visibility_scope=visibility,
        project_id=project,
    )


def status(provider, claim_id: str) -> str:
    row = provider._connect().execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()
    assert row is not None
    return str(row["status"])


def test_temporal_update_only_supersedes_same_subject_and_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = load_module("memory_wiki_temporal_subject_test")
    p = provider(module, tmp_path, "chat-a")
    intended = add(p, "Atlas gateway service uses port 1234 for local requests.")
    unrelated = add(p, "Backup worker uses port 6789 for replication jobs.")

    replacement = add(p, "Atlas gateway service now uses port 5678 for local requests.")

    assert replacement.startswith("c_")
    assert status(p, intended) == "archived"
    assert status(p, unrelated) == "active"


def test_temporal_update_cannot_cross_chat_partition(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = load_module("memory_wiki_temporal_chat_test")
    first = provider(module, tmp_path, "chat-a")
    second = provider(module, tmp_path, "chat-b")
    foreign = add(second, "Atlas gateway service uses port 1234 for local requests.")

    add(first, "Atlas gateway service now uses port 5678 for local requests.")

    assert status(first, foreign) == "active"


def test_temporal_update_cannot_cross_project_partition(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = load_module("memory_wiki_temporal_project_test")
    first = provider(module, tmp_path, "chat-a", "project-a")
    second = provider(module, tmp_path, "chat-b", "project-b")
    foreign = add(
        second,
        "Atlas gateway service uses port 1234 for local requests.",
        visibility="project",
        project="project-b",
    )

    add(
        first,
        "Atlas gateway service now uses port 5678 for local requests.",
        visibility="project",
        project="project-a",
    )

    assert status(first, foreign) == "active"
