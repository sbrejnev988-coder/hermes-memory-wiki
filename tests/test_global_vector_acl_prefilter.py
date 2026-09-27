"""Synthetic Qdrant top-K regression for read-only federated vector search."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _home(root: Path, label: str) -> Path:
    home = root if label == "default" else root / "profiles" / label
    home.mkdir(parents=True, exist_ok=True)
    lines = [
        "MEMORY_WIKI_QDRANT_URL=http://127.0.0.1:9\n",
        f"MEMORY_WIKI_QDRANT_COLLECTION=synthetic_{label}_claims\n",
        f"MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION=synthetic_{label}_episodes\n",
        f"MEMORY_WIKI_QDRANT_ALIAS=synthetic_{label}_active\n",
    ]
    if label == "default":
        lines += [
            "MEMORY_WIKI_GLOBAL_SEARCH_ENABLED=1\n",
            "MEMORY_WIKI_GLOBAL_SEARCH_PROFILES=default,work\n",
            "MEMORY_WIKI_GLOBAL_SEARCH_CANDIDATE_LIMIT=20\n",
        ]
    (home / ".env").write_text("".join(lines), encoding="utf-8")
    return home


def _load(home: Path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_RERANK_ENABLED", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_ROOTS", raising=False)
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_CACHE_DIR", raising=False)
    name = f"memory_wiki_global_vector_acl_{home.parent.name}_{home.name}"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _matches_qdrant_filter(payload: dict, condition: dict) -> bool:
    """Evaluate the small must/should/match subset used by the Qdrant ACL."""
    if "key" in condition:
        assert set(condition) == {"key", "match"}
        return payload.get(condition["key"]) == condition["match"]["value"]
    assert set(condition) <= {"must", "should"}, condition
    assert condition, "A missing filter would select all points"
    return (all(_matches_qdrant_filter(payload, part) for part in condition.get("must", []))
            and (not condition.get("should") or any(
                _matches_qdrant_filter(payload, part) for part in condition["should"]
            )))


def _seed(module, provider, claim_id: str, visibility: str, *, bot: str,
          session: str, chat_hash: str, project: str) -> dict:
    now = module.now()
    with provider._connect() as db:
        db.execute(
            """INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
               created_at,updated_at,freshness_at,access_count,last_accessed,hash,
               scope,visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash,
               project_id,quality,risk,quarantined_at,trust_class,type)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (claim_id, "Synthetic routing evidence remains documented.", "audit", "active",
             .9, .9, "synthetic", "", now, now, now, 0, 0, claim_id,
             "global", visibility, bot, session, chat_hash, project, .9, "low", 0,
             "fact", "fact"),
        )
    return {"visibility_scope": visibility, "origin_bot_id": bot,
            "origin_session_id": session, "origin_chat_hash": chat_hash,
            "project_id": project}


def test_global_vector_search_prefilters_each_profile_before_top_k(tmp_path, monkeypatch):
    default = _home(tmp_path / "default", "default")
    work = _home(tmp_path / "default", "work")
    module = _load(default, monkeypatch)
    caller = module.MemoryWikiProvider()
    caller.initialize("synthetic-session", hermes_home=str(default),
                      bot_id="synthetic-bot", project_id="synthetic-project")
    foreign = module.MemoryWikiProvider()
    foreign.initialize("foreign-session", hermes_home=str(work),
                       bot_id="foreign-bot", project_id="foreign-project")
    try:
        session = caller.session_id
        chat_hash = caller._chat_hash(session)
        own_points = []
        foreign_points = []

        def add(provider, bucket, claim_id, visibility, score, *, bot="synthetic-bot",
                sid=session, chat=chat_hash, project="synthetic-project"):
            payload = _seed(module, provider, claim_id, visibility, bot=bot,
                            session=sid, chat_hash=chat, project=project)
            bucket.append((claim_id, score, payload))

        # Hidden, high-scoring points must not consume Qdrant's top-20 budget.
        for i in range(20):
            add(caller, own_points, f"own-hidden-{i:02d}", "private", 1.0 - i / 100,
                bot="unrelated-bot", sid="unrelated-session")
            # Even a foreign point with matching caller ownership is not visible
            # outside its source profile unless it is explicitly global.
            add(foreign, foreign_points, f"foreign-hidden-{i:02d}", "private",
                1.0 - i / 100)
        for scope in ("global", "bot", "chat", "private", "project"):
            add(caller, own_points, f"own-{scope}", scope, .70)
        add(foreign, foreign_points, "foreign-global", "global", .70)
        for scope in ("bot", "chat", "project"):
            add(foreign, foreign_points, f"foreign-{scope}", scope, .65)
        # A stale/mislabeled Qdrant ACL is not authority: SQLite must still
        # reject both same-profile and foreign private rows after hydration.
        add(caller, own_points, "own-stale-payload", "private", .75,
            bot="unrelated-bot", sid="unrelated-session")
        own_points[-1][2]["visibility_scope"] = "global"
        add(foreign, foreign_points, "foreign-stale-payload", "private", .75)
        foreign_points[-1][2]["visibility_scope"] = "global"

        monkeypatch.setattr(module, "SEMANTIC_ENABLED", True)
        semantic_modes = []

        def fake_semantic_available(*, read_only=False):
            semantic_modes.append(read_only)
            return True

        monkeypatch.setattr(module, "_semantic_available", fake_semantic_available)
        monkeypatch.setattr(module, "_embed_query", lambda _q: [0.0] * module.QDRANT_VECTOR_SIZE)
        calls = {}

        def fake_qdrant_search(_vector, limit, *, query_filter=None):
            profile = module._bound_profile_home().name
            calls[profile] = query_filter
            points = own_points if profile == "default" else foreign_points
            ranked = sorted(points, key=lambda point: point[1], reverse=True)
            if query_filter is not None:
                ranked = [p for p in ranked if _matches_qdrant_filter(p[2], query_filter)]
            return [(claim_id, score) for claim_id, score, _payload in ranked[:limit]]

        monkeypatch.setattr(module, "_qdrant_search", fake_qdrant_search)
        result = caller._global_search("synthetic routing", limit=10, mode="vector")
        expected = {f"own-{scope}" for scope in ("global", "bot", "chat", "private", "project")}
        expected.add("foreign-global")
        assert result["candidate_limit_per_profile"] == 20
        assert {row["id"] for row in result["claims"]} == expected, result["profile_diagnostics"]
        assert set(calls) == {"default", "work"}
        assert semantic_modes and all(mode is True for mode in semantic_modes)
        assert all(filter_value is not None for filter_value in calls.values())
    finally:
        caller._connect().close()
        foreign._connect().close()
