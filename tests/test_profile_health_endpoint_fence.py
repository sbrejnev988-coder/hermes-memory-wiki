"""Synthetic profile boundaries for asynchronous health and old Qdrant endpoints."""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _home(tmp_path: Path, name: str, historical: str = "") -> Path:
    home = tmp_path / name
    home.mkdir()
    (home / ".env").write_text(
        "MEMORY_WIKI_QDRANT_URL=http://127.0.0.1:6333\n"
        f"MEMORY_WIKI_QDRANT_COLLECTION={name}_claims\n"
        f"MEMORY_WIKI_QDRANT_ALIAS={name}_active\n"
        f"MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION={name}_episodes\n"
        "MEMORY_WIKI_EMBED_API_KEY=synthetic-test-value\n"
        f"MEMORY_WIKI_QDRANT_HISTORICAL_ENDPOINTS={historical}\n",
        encoding="utf-8",
    )
    return home


def _module(monkeypatch, importer: Path, name: str):
    monkeypatch.setenv("HERMES_HOME", str(importer))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_DEBUG", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_EMBED_PROVIDER", "openrouter")
    monkeypatch.setenv("MEMORY_WIKI_EMBED_API_KEY", "synthetic-test-value")
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_health_refresh_retains_profile_context_and_separate_negative_cache(tmp_path, monkeypatch):
    default = _home(tmp_path, "default")
    learning = _home(tmp_path, "learning")
    module = _module(monkeypatch, default, "memory_wiki_profile_health_probe")
    seen: list[str] = []
    finished = {"default": threading.Event(), "learning": threading.Event()}

    def fake_health() -> bool:
        profile = module._bound_profile_home().name
        seen.append(profile)
        finished[profile].set()
        return profile == "learning"

    monkeypatch.setattr(module, "_openrouter_available", fake_health)
    with module._profile_qdrant_scope(default):
        module._openrouter_health_swr(force_refresh=True)
    assert finished["default"].wait(3)
    deadline = time.monotonic() + 3
    while True:
        with module._profile_qdrant_scope(default):
            default_health = module._openrouter_health_swr()
        if default_health is False or time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    assert default_health is False

    with module._profile_qdrant_scope(learning):
        assert module._openrouter_health_swr(force_refresh=True) is True
    assert finished["learning"].wait(3)
    with module._profile_qdrant_scope(learning):
        assert module._openrouter_health_swr() is True
    with module._profile_qdrant_scope(default):
        assert module._openrouter_health_swr() is False
    assert seen == ["default", "learning"]


def test_historical_delete_rejects_unlisted_endpoint_without_network(tmp_path, monkeypatch):
    default = _home(tmp_path, "default", historical="https://archive.example")
    module = _module(monkeypatch, default, "memory_wiki_profile_endpoint_probe")
    requests: list[str] = []
    monkeypatch.setattr(
        module, "_urlopen_no_redirect",
        lambda *_args, **_kwargs: requests.append("network"),
    )
    with module._profile_qdrant_scope(default):
        collection = module._physical_collection_name()
        assert module._profile_endpoint_allowed("https://archive.example")
        assert not module._profile_endpoint_allowed("https://foreign.example")
        assert not module._qdrant_delete_target(
            "synthetic-claim", collection=collection,
            endpoint="https://foreign.example",
        )
    assert requests == []


def test_legacy_home_without_env_rejects_unlisted_historical_endpoint(tmp_path, monkeypatch):
    home = tmp_path / "legacy"
    home.mkdir()
    module = _module(monkeypatch, home, "memory_wiki_legacy_endpoint_probe")
    requests: list[str] = []
    monkeypatch.setattr(
        module, "_urlopen_no_redirect",
        lambda *_args, **_kwargs: requests.append("network"),
    )
    with module._profile_qdrant_scope(home):
        assert module._profile_endpoint_allowed(module._normalized_qdrant_endpoint())
        assert not module._profile_endpoint_allowed("https://foreign.example")
        assert not module._qdrant_delete_target(
            "synthetic-claim", collection=module._physical_collection_name(),
            endpoint="https://foreign.example",
        )
    assert requests == []
