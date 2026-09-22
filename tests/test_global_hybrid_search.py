"""Explicit cross-profile read-only hybrid search contract."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _home(root: Path, name: str, *, global_search: bool = True) -> Path:
    home = root if name == "default" else root / "profiles" / name
    home.mkdir(parents=True, exist_ok=True)
    lines = [
        "MEMORY_WIKI_SEMANTIC=1\n"
        "MEMORY_WIKI_QDRANT_URL=http://127.0.0.1:6333\n"
        f"MEMORY_WIKI_QDRANT_COLLECTION={name}_claims\n"
        f"MEMORY_WIKI_QDRANT_ALIAS={name}_active\n"
        f"MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION={name}_episodes\n"
        "MEMORY_WIKI_EMBED_API_KEY=synthetic-test-key\n"
    ]
    if global_search:
        lines.extend((
            "MEMORY_WIKI_GLOBAL_SEARCH_ENABLED=1\n",
            "MEMORY_WIKI_GLOBAL_SEARCH_PROFILES=default,gaming,learning,work\n",
        ))
    (home / ".env").write_text("".join(lines), encoding="utf-8")
    return home


def _load_module(home: Path, monkeypatch) -> object:
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "1")
    monkeypatch.setenv("MEMORY_WIKI_EMBED_PROVIDER", "stub")
    name = "memory_wiki_global_hybrid_search_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _provider(module, home: Path, profile: str):
    provider = module.MemoryWikiProvider()
    provider.initialize(
        "shared-global-search-session",
        hermes_home=str(home),
        bot_id=f"{profile}-bot",
        project_id=profile,
    )
    return provider


def test_global_hybrid_search_unifies_profiles_without_returning_secret_rows(
    tmp_path, monkeypatch,
):
    fleet_root = tmp_path / "default"
    default = _home(fleet_root, "default")
    gaming = _home(fleet_root, "gaming")
    learning = _home(fleet_root, "learning")
    work = _home(fleet_root, "work")
    module = _load_module(default, monkeypatch)
    monkeypatch.setattr(module, "_start_outbox_worker", lambda _path: None)
    monkeypatch.setattr(module, "_wake_outbox_worker", lambda _path: None)

    providers = {
        name: _provider(module, home, name)
        for name, home in {
            "default": default,
            "gaming": gaming,
            "learning": learning,
            "work": work,
        }.items()
    }
    try:
        default_id = providers["default"]._add_claim(
            "Atlas fleet controller uses an amber routing protocol.",
            topic="infrastructure",
            source="phase6_curated_summary:test",
            confidence=0.9,
            salience=0.9,
            visibility_scope="chat",
        )
        work_id = providers["work"]._add_claim(
            "Atlas fleet controller uses a cobalt routing protocol in work.",
            topic="infrastructure",
            source="phase6_curated_summary:test",
            confidence=0.9,
            salience=0.9,
            visibility_scope="chat",
        )
        secret_id = providers["work"]._add_claim(
            "Synthetic confidential Atlas routing material must not be returned.",
            topic="infrastructure",
            source="phase6_curated_summary:test",
            confidence=0.9,
            salience=0.9,
            visibility_scope="chat",
        )
        with providers["work"]._connect() as conn:
            conn.execute("UPDATE claims SET risk='secret' WHERE id=?", (secret_id,))

        module.SEMANTIC_ENABLED = True
        monkeypatch.setattr(module, "_semantic_available", lambda: True)
        monkeypatch.setattr(
            module, "_embed_query", lambda _query: [0.0] * module.QDRANT_VECTOR_SIZE,
        )
        qdrant_profiles = []

        def fake_qdrant_search(_vector, _limit=20, *, query_filter=None):
            profile = module._bound_profile_home().name
            qdrant_profiles.append(profile)
            matches = {
                "default": [(default_id, 0.91)],
                "work": [(secret_id, 0.99), (work_id, 0.89)],
            }
            return matches.get(profile, [])

        monkeypatch.setattr(module, "_qdrant_search", fake_qdrant_search)

        assert not providers["default"]._should_journal_tool(
            "memory_wiki_global_search", {"query": "Atlas fleet routing protocol"},
        )
        result = json.loads(
            providers["default"].handle_tool_call(
                "memory_wiki_global_search",
                {"query": "Atlas fleet routing protocol", "limit": 20, "mode": "hybrid"},
            )
        )

        assert result["success"] is True, result
        assert result["mode"] == "hybrid"
        assert set(result["searched_profiles"]) == {"default", "gaming", "learning", "work"}
        assert set(qdrant_profiles) == {"default", "gaming", "learning", "work"}
        returned = {(row["profile"], row["id"]) for row in result["claims"]}
        assert ("default", default_id) in returned
        assert ("work", work_id) in returned
        assert ("work", secret_id) not in returned
        assert all("secret" not in str(row).lower() for row in result["claims"])
    finally:
        for provider in providers.values():
            provider._connect().close()


def test_global_search_inherits_explicit_nonsecret_process_opt_in_for_a_profile(
    tmp_path, monkeypatch,
):
    fleet_root = tmp_path / "default"
    default = _home(fleet_root, "default", global_search=False)
    gaming = _home(fleet_root, "gaming", global_search=False)
    module = _load_module(default, monkeypatch)
    monkeypatch.setattr(module, "_start_outbox_worker", lambda _path: None)
    monkeypatch.setattr(module, "_wake_outbox_worker", lambda _path: None)
    monkeypatch.setenv("MEMORY_WIKI_GLOBAL_SEARCH_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_GLOBAL_SEARCH_PROFILES", "default,gaming")

    default_provider = _provider(module, default, "default")
    gaming_provider = _provider(module, gaming, "gaming")
    try:
        claim_id = gaming_provider._add_claim(
            "Phoenix profile-level lexical federation regression fixture.",
            topic="infrastructure",
            source="phase6_curated_summary:test",
            confidence=0.9,
            salience=0.9,
            visibility_scope="chat",
        )
        result = json.loads(
            gaming_provider.handle_tool_call(
                "memory_wiki_global_search",
                {"query": "Phoenix profile lexical federation", "limit": 20, "mode": "fts"},
            )
        )
        assert result["success"] is True, result
        assert result["configured_profiles"] == ["default", "gaming"]
        assert ("gaming", claim_id) in {
            (row["profile"], row["id"]) for row in result["claims"]
        }
    finally:
        default_provider._connect().close()
        gaming_provider._connect().close()
