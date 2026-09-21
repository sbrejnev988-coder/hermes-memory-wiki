"""Synthetic shared-process profile isolation for Qdrant and durable outbox."""

from __future__ import annotations

import importlib.util
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _home(tmp_path: Path, name: str) -> Path:
    home = tmp_path / name
    home.mkdir()
    (home / ".env").write_text(
        "MEMORY_WIKI_QDRANT_URL=http://127.0.0.1:6333\n"
        f"MEMORY_WIKI_QDRANT_COLLECTION={name}_claims\n"
        f"MEMORY_WIKI_QDRANT_ALIAS={name}_active\n"
        f"MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION={name}_episodes\n"
        "MEMORY_WIKI_EMBED_API_KEY=synthetic-profile-key\n",
        encoding="utf-8",
    )
    return home


def _module(tmp_path, monkeypatch, *, importer: Path, ambient_home: Path, name: str):
    monkeypatch.setenv("HERMES_HOME", str(ambient_home))
    monkeypatch.setenv("MEMORY_WIKI_QDRANT_COLLECTION", f"{importer.name}_claims")
    monkeypatch.setenv("MEMORY_WIKI_QDRANT_ALIAS", f"{importer.name}_active")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION", f"{importer.name}_episodes")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    spec = importlib.util.spec_from_file_location(name, PLUGIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _provider(module, home: Path, monkeypatch):
    seen_at_initialize = []
    monkeypatch.setattr(module, "_start_outbox_worker", lambda _path: None)
    monkeypatch.setattr(module, "_wake_outbox_worker", lambda _path: None)
    monkeypatch.setattr(
        module.MemoryWikiProvider, "_sync_env_metadata",
        lambda self: seen_at_initialize.append(
            (module._qdrant_collection(), module._qdrant_alias(),
             module._outbox_db_path())
        ),
    )
    provider = module.MemoryWikiProvider()
    provider.initialize("chat-a", hermes_home=str(home), bot_id="bot-a")
    assert seen_at_initialize == [
        (f"{home.name}_claims", f"{home.name}_active",
         str(home / "memory-wiki" / "memory_wiki.sqlite3")),
    ]
    return provider


def test_mixed_import_routes_default_and_learning_to_their_own_targets(
    tmp_path, monkeypatch,
):
    default = _home(tmp_path, "default")
    learning = _home(tmp_path, "learning")
    module = _module(
        tmp_path, monkeypatch, importer=learning, ambient_home=default,
        name="mw_mixed_profile_direction_one",
    )
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda **_kwargs: False)
    monkeypatch.setattr(module, "_ensure_collection", lambda _collection=None: True)
    monkeypatch.setattr(module, "_embed_document", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE)
    requests = []
    monkeypatch.setattr(
        module, "_qdrant_req",
        lambda method, path, body=None, timeout=10.0: requests.append((method, path))
        or {"result": {"status": "completed"}},
    )
    provider = _provider(module, default, monkeypatch)
    assert (default / "memory-wiki" / "embedding_manifest.json").is_file()
    assert not (learning / "memory-wiki" / "embedding_manifest.json").exists()
    module.DEBUG_MODE = True
    with module._profile_qdrant_scope(default):
        module._debug_log("synthetic profile route")
    assert (default / "memory-wiki" / "debug.log").is_file()
    assert not (learning / "memory-wiki" / "debug.log").exists()
    module.SEMANTIC_ENABLED = True
    claim_id = provider._add_claim(
        "The synthetic default gateway uses port 5678.", topic="server",
        source="memory_tool:test", confidence=0.9, salience=0.9,
        visibility_scope="chat",
    )
    assert claim_id.startswith("c_")
    with provider._connect() as db:
        module._outbox_enqueue(
            "embed_and_upsert", "claim", claim_id,
            {"collection": f"learning_claims_{module._manifest_hash(module._embedding_manifest())}",
             "endpoint": "http://127.0.0.1:6333"}, conn=db,
        )
    result = module._outbox_process(20, db_path=str(provider.db_path), worker_id="synthetic")
    assert result["ok"] >= 1, (
        result, [tuple(row) for row in provider._connect().execute(
            "SELECT operation,status,COUNT(*),MIN(next_retry_at)-strftime('%s','now') "
            "FROM index_outbox GROUP BY operation,status"
        ).fetchall()],
    )
    assert all("learning_" not in path for _method, path in requests)
    assert any("default_claims_" in path for _method, path in requests)
    status = provider._semantic_status()
    assert status["alias"] == "default_active"
    assert status["expected_collection"].startswith("default_claims_")


def test_inverse_import_and_foreign_delete_job_fail_closed(tmp_path, monkeypatch):
    default = _home(tmp_path, "default")
    learning = _home(tmp_path, "learning")
    module = _module(
        tmp_path, monkeypatch, importer=default, ambient_home=learning,
        name="mw_mixed_profile_direction_two",
    )
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda **_kwargs: False)
    provider = _provider(module, learning, monkeypatch)
    module.SEMANTIC_ENABLED = True
    claim_id = provider._add_claim(
        "The synthetic learning gateway uses port 6789.", topic="server",
        source="memory_tool:test", confidence=0.9, salience=0.9,
        visibility_scope="chat",
    )
    foreign = f"default_claims_{module._manifest_hash(module._embedding_manifest())}"
    endpoint = "http://127.0.0.1:6333"
    with provider._connect() as db:
        db.execute("DELETE FROM index_outbox")
        target = module._record_claim_vector_target(
            db, claim_id, collection=foreign, endpoint=endpoint,
            status="delete_pending",
        )
        module._outbox_enqueue(
            "delete", "claim", claim_id,
            {**target, "reason": "claim_target_recovery"}, conn=db,
        )
    network = []
    monkeypatch.setattr(
        module, "_urlopen_no_redirect",
        lambda *_args, **_kwargs: network.append("foreign-request"),
    )
    monkeypatch.setattr(
        module, "_qdrant_resolved_active_collection",
        lambda: module._physical_collection_name(),
    )
    result = module._outbox_process(20, db_path=str(provider.db_path), worker_id="synthetic")
    assert result["fail"] == 1, (
        result,
        [tuple(row) for row in provider._connect().execute(
            "SELECT operation,status,COUNT(*),MIN(next_retry_at)-strftime('%s','now') "
            "FROM index_outbox GROUP BY operation,status"
        ).fetchall()],
    )
    assert network == []
    rows = provider._connect().execute(
        "SELECT payload_json FROM index_outbox WHERE operation='delete' AND object_id=?",
        (claim_id,),
    ).fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][0])["collection"] == foreign
    assert module._profile_target_allowed(foreign)  # legacy unbound helpers
    with module._profile_qdrant_scope(learning):
        assert not module._profile_target_allowed(foreign)
        assert module._profile_target_allowed(module._physical_collection_name())


def test_llm_pack_uses_bound_home_config_in_mixed_process(tmp_path, monkeypatch):
    default = _home(tmp_path, "default")
    learning = _home(tmp_path, "learning")
    with (default / ".env").open("a", encoding="utf-8") as out:
        out.write("MEMORY_WIKI_LLM_PACK=1\n")
    (default / "config.yaml").write_text(
        "base_url: http://127.0.0.1:18646/v1\n"
        "api_key: synthetic-default-key\nmodel: synthetic-model\n", encoding="utf-8",
    )
    (learning / "config.yaml").write_text(
        "base_url: http://127.0.0.1:28646/v1\n"
        "api_key: synthetic-learning-key\nmodel: synthetic-model\n", encoding="utf-8",
    )
    module = _module(
        tmp_path, monkeypatch, importer=learning, ambient_home=default,
        name="mw_mixed_profile_llm_config",
    )
    monkeypatch.setenv("HERMES_CONFIG", str(learning / "config.yaml"))
    monkeypatch.setenv("MEMORY_WIKI_LLM_API_KEY", "synthetic-learning-key")
    provider = _provider(module, default, monkeypatch)
    requests = []

    def respond(request, **_kwargs):
        requests.append((request.full_url, request.get_header("Authorization")))
        return io.BytesIO(b'{"choices":[{"message":{"content":"Synthetic context."}}]}')

    monkeypatch.setattr(module, "_urlopen_no_redirect", respond)
    assert provider._llm_pack_context("synthetic query", "Synthetic candidate.", 1500)
    assert requests == [
        ("http://127.0.0.1:18646/v1/chat/completions",
         "Bearer synthetic-default-key"),
    ]


def test_concurrent_outbox_workers_keep_separate_profile_contexts(tmp_path, monkeypatch):
    default = _home(tmp_path, "default")
    learning = _home(tmp_path, "learning")
    module = _module(
        tmp_path, monkeypatch, importer=learning, ambient_home=default,
        name="mw_mixed_concurrent_outbox",
    )
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda **_kwargs: False)
    monkeypatch.setattr(module, "_qdrant_resolved_active_collection", lambda: module._physical_collection_name())
    monkeypatch.setattr(module, "_embed_document", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE)
    observed = []
    monkeypatch.setattr(
        module, "_qdrant_upsert",
        lambda _id, _vector, _payload, collection=None: observed.append(
            (module._bound_profile_home().name, collection)
        ) or True,
    )
    providers = [_provider(module, home, monkeypatch) for home in (default, learning)]
    module.SEMANTIC_ENABLED = True
    for provider in providers:
        claim_id = provider._add_claim(
            f"Synthetic {provider.home.name} gateway uses port 5678.",
            topic="server", source="memory_tool:test", confidence=0.9,
            salience=0.9, visibility_scope="chat",
        )
        with provider._connect() as db:
            module._outbox_enqueue(
                "embed_and_upsert", "claim", claim_id,
                {"collection": "stale-other-profile-hint"}, conn=db,
            )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda provider: module._outbox_process(
                20, db_path=str(provider.db_path), worker_id=provider.home.name,
            ), providers,
        ))
    assert all(result["ok"] >= 1 for result in results)
    assert sorted(observed) == sorted([
        (home.name, f"{home.name}_claims_{module._manifest_hash(module._embedding_manifest())}")
        for home in (default, learning)
    ])


def test_foreign_home_without_env_fails_closed_before_semantic_io(tmp_path, monkeypatch):
    default = _home(tmp_path, "default")
    foreign = tmp_path / "unconfigured"
    foreign.mkdir()
    module = _module(
        tmp_path, monkeypatch, importer=default, ambient_home=default,
        name="mw_foreign_home_no_env",
    )
    monkeypatch.setattr(module.MemoryWikiProvider, "_sync_env_metadata", lambda self: None)
    provider = module.MemoryWikiProvider()
    provider.initialize("chat-a", hermes_home=str(foreign), bot_id="bot-a")
    assert provider.is_available()
    calls = []
    monkeypatch.setattr(
        module, "_urlopen_no_redirect",
        lambda *_args, **_kwargs: calls.append("remote"),
    )
    with module._profile_qdrant_scope(foreign):
        assert not module._semantic_profile_ready()
        assert module._qdrant_req("GET", "/collections") is None
    result = module._outbox_process(1, db_path=str(provider.db_path), worker_id="synthetic")
    assert result["error"] == "profile embedding contract mismatch"
    assert calls == []


def test_foreign_profile_uses_own_embedding_key(tmp_path, monkeypatch):
    default = _home(tmp_path, "default")
    learning = _home(tmp_path, "learning")
    with (learning / ".env").open("a", encoding="utf-8") as out:
        out.write("MEMORY_WIKI_EMBED_API_KEY=synthetic-learning-key\n")
    monkeypatch.setenv("MEMORY_WIKI_EMBED_API_KEY", "synthetic-default-key")
    module = _module(
        tmp_path, monkeypatch, importer=default, ambient_home=default,
        name="mw_scoped_embedding_key",
    )
    with module._profile_qdrant_scope(learning):
        assert module._semantic_profile_ready()
        assert module._embed_api_key() == "synthetic-learning-key"
    with module._profile_qdrant_scope(default):
        assert module._embed_api_key() == "synthetic-profile-key"


def test_foreign_profile_partial_route_disables_semantic_io(tmp_path, monkeypatch):
    default = _home(tmp_path, "default")
    partial = _home(tmp_path, "partial")
    (partial / ".env").write_text(
        "MEMORY_WIKI_EMBED_API_KEY=synthetic-partial-key\n"
        "MEMORY_WIKI_QDRANT_URL=http://127.0.0.1:6333\n",
        encoding="utf-8",
    )
    module = _module(
        tmp_path, monkeypatch, importer=default, ambient_home=default,
        name="mw_foreign_partial_route",
    )
    seen = []
    monkeypatch.setattr(
        module, "_urlopen_no_redirect",
        lambda *_args, **_kwargs: seen.append("remote"),
    )
    with module._profile_qdrant_scope(partial):
        assert not module._semantic_profile_ready()
        assert module._qdrant_req("GET", "/collections") is None
    assert seen == []
