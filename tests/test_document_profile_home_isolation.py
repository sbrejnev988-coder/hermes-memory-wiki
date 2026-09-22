"""Synthetic shared-process isolation for document paths and policy settings."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def _module():
    spec = importlib.util.spec_from_file_location("document_profile_home_probe", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _home(tmp_path: Path, name: str) -> tuple[Path, Path]:
    home = tmp_path / name
    cache = home / "cache" / "documents"
    cache.mkdir(parents=True)
    source = cache / "synthetic.txt"
    source.write_text(name, encoding="utf-8")
    (home / ".env").write_text(
        f"MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID={name}-scope\n"
        "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE=1\n",
        encoding="utf-8",
    )
    return home, source


def test_provider_document_paths_ignore_another_profiles_ambient_home(tmp_path, monkeypatch):
    module = _module()
    default, default_file = _home(tmp_path, "default")
    learning, learning_file = _home(tmp_path, "learning")
    monkeypatch.setenv("HERMES_HOME", str(learning))
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_CACHE_DIR", str(learning_file.parent))
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ROOTS", str(learning_file.parent))
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID", "learning-scope")

    with module._document_profile_scope(default):
        assert module._hermes_home() == default
        assert module._document_cache_root() == default_file.parent
        assert module._roots() == [default_file.parent]
        assert module._inbox_dir() == default / "context-coordination" / "inbox" / "documents"
        assert module._allowed_path(default_file) == default_file
        with pytest.raises(ValueError):
            module._allowed_path(learning_file)
        assert module._document_env("MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID") == "default-scope"
        assert module._document_env("MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID") is None
        snapshot, _ = module._snapshot_allowed_file(default_file, max_bytes=1024)
        try:
            assert snapshot.parent.parent == default / "memory-wiki" / "document-snapshots"
            assert snapshot.read_text(encoding="utf-8") == "default"
        finally:
            snapshot.unlink()
            snapshot.parent.rmdir()

    assert module._hermes_home() == learning
    assert module._document_cache_root() == learning_file.parent


def test_nested_document_scopes_restore_each_profiles_configuration(tmp_path, monkeypatch):
    module = _module()
    default, default_file = _home(tmp_path, "default")
    learning, learning_file = _home(tmp_path, "learning")
    monkeypatch.setenv("HERMES_HOME", str(default))
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_CACHE_DIR", raising=False)
    monkeypatch.delenv("HERMES_DOCUMENT_CACHE_DIR", raising=False)
    with module._document_profile_scope(default):
        assert module._document_cache_root() == default_file.parent
        with module._document_profile_scope(learning):
            assert module._document_cache_root() == learning_file.parent
            assert module._document_env("MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID") == "learning-scope"
        assert module._document_cache_root() == default_file.parent


def test_document_profile_scope_allows_only_safe_global_feature_defaults(tmp_path, monkeypatch):
    module = _module()
    default, _ = _home(tmp_path, "default")
    gaming, _ = _home(tmp_path, "gaming")
    monkeypatch.setenv("HERMES_HOME", str(default))
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_PREFETCH", "1")
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_RERANK", "1")
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID", "must-not-leak")

    with module._document_profile_scope(gaming):
        assert module._document_env("MEMORY_WIKI_DOCUMENT_PREFETCH") == "1"
        assert module._document_env("MEMORY_WIKI_DOCUMENT_RERANK") == "1"
        # Global safe feature defaults must not widen file/scope authorization.
        assert module._document_env("MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID") is None
