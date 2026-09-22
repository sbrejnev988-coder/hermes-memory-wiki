"""Isolated retrieval regression suite for temporal, multi-hop, and scope cases.

By default this runs offline against a temporary Hermes home. ``--semantic``
uses the configured embedding service and Qdrant, but gives the fixture a
random, temporary Qdrant collection. The user's memory database and active
Qdrant alias are never read or modified.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "quality_cases.json"
CONFIG_KEYS = (
    "OPENROUTER_API_KEY", "MEMORY_WIKI_EMBED_API_KEY", "MEMORY_WIKI_EMBED_PROVIDER",
    "MEMORY_WIKI_EMBED_MODEL", "MEMORY_WIKI_EMBED_URL", "MEMORY_WIKI_EMBED_DIMENSIONS",
    "MEMORY_WIKI_VECTOR_SIZE", "MEMORY_WIKI_QDRANT_URL", "MEMORY_WIKI_QDRANT_API_KEY",
)


def _load_module():
    name = f"memory_wiki_quality_eval_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Memory Wiki module cannot be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _env_file_values(path: Path) -> dict[str, str]:
    try:
        from dotenv import dotenv_values
    except ImportError as exc:
        raise RuntimeError("--env-file requires python-dotenv") from exc
    values = dotenv_values(path)
    return {key: str(values[key]) for key in CONFIG_KEYS if values.get(key)}


def _insert_fixture(provider, module, fixture: dict) -> None:
    now = module.now()
    rows = []
    for item in fixture["claims"]:
        visibility = str(item.get("visibility") or "global")
        session = str(item.get("session") or "")
        project = str(item.get("project") or "")
        claim = str(item["claim"])
        rows.append((
            str(item["id"]), claim, claim, "quality-eval",
            str(item.get("status") or "active"), 0.95, 0.85,
            "benchmark:synthetic", "Synthetic fixture; no user data", now, now, now,
            f"quality-eval-{item['id']}", "project" if visibility == "project" else "global",
            visibility, session, provider._chat_hash(session) if session else "",
            str(item.get("bot") or ""), project, 0.95, "low", "fact",
        ))
    with provider._connect() as conn:
        conn.executemany(
            """INSERT INTO claims(
                id,claim,normalized_claim,topic,status,confidence,salience,source,evidence,
                created_at,updated_at,freshness_at,hash,scope,visibility_scope,
                origin_session_id,origin_chat_hash,origin_bot_id,project_id,quality,risk,trust_class
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    provider._rebuild_fts()


def _percentile(durations: list[float], percentile: float) -> float:
    ordered = sorted(durations)
    if not ordered:
        return 0.0
    return ordered[max(0, min(len(ordered) - 1, int(len(ordered) * percentile + 0.999999) - 1))]


def _score_cases(providers: dict, fixture: dict, *, mode: str) -> dict:
    cases = []
    durations = []
    for item in fixture["cases"]:
        context = item["context"]
        key = (context["session"], context["bot"], context["project"])
        provider = providers[key]
        started = time.perf_counter()
        rows = provider._search(
            item["query"], limit=5, retrieval_mode=mode,
            record_retrieval=False, apply_rerank=False,
        )
        elapsed = (time.perf_counter() - started) * 1000
        durations.append(elapsed)
        ids = [str(row["id"]) for row in rows]
        required = [str(value) for value in item.get("required", [])]
        forbidden = [str(value) for value in item.get("forbidden", [])]
        hits = [claim_id for claim_id in required if claim_id in ids]
        violations = [claim_id for claim_id in forbidden if claim_id in ids]
        first_rank = min((ids.index(claim_id) + 1 for claim_id in hits), default=0)
        cases.append({
            "name": item["name"], "category": item["category"],
            "required": required, "found": hits, "forbidden_found": violations,
            "rank_first": first_rank, "top_5": ids,
            "latency_ms": round(elapsed, 2),
        })
    with_required = [case for case in cases if case["required"]]
    scope_cases = [case for case in cases if case["category"] == "scope"]
    return {
        "mode": mode, "cases": cases,
        "recall_at_5": round(sum(len(case["found"]) / len(case["required"]) for case in with_required) / len(with_required), 3),
        "all_required_at_5": round(sum(len(case["found"]) == len(case["required"]) for case in with_required) / len(with_required), 3),
        "mrr_at_5": round(sum(1 / case["rank_first"] if case["rank_first"] else 0 for case in with_required) / len(with_required), 3),
        "forbidden_hits": sum(len(case["forbidden_found"]) for case in cases),
        "scope_leaks": sum(len(case["forbidden_found"]) for case in scope_cases),
        "latency_p50_ms": round(statistics.median(durations), 2),
        "latency_p95_ms": round(_percentile(durations, 0.95), 2),
    }


def run(fixture_path: Path = DEFAULT_FIXTURE, *, semantic: bool = False,
        env_file: Path | None = None) -> dict:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if fixture.get("version") != 1 or not fixture.get("cases"):
        raise ValueError("quality fixture must be version 1 and contain cases")
    with tempfile.TemporaryDirectory(prefix="memory-wiki-quality-") as tmp:
        collection = f"memory_wiki_quality_{uuid.uuid4().hex[:16]}"
        overrides = {
            "HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0",
            "MEMORY_WIKI_SEMANTIC": "1" if semantic else "0",
            "MEMORY_WIKI_RERANK_ENABLED": "0",
            "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE": "0",
            "MEMORY_WIKI_QDRANT_COLLECTION": collection,
            "MEMORY_WIKI_QDRANT_ALIAS": f"{collection}_active",
            "MEMORY_WIKI_QDRANT_ALIAS_MODE": "physical",
        }
        if semantic and env_file:
            overrides.update(_env_file_values(env_file))
        previous = {key: os.environ.get(key) for key in set(CONFIG_KEYS) | set(overrides)}
        os.environ.update(overrides)
        module = None
        providers = {}
        result = None
        try:
            module = _load_module()
            contexts = {
                (item["context"]["session"], item["context"]["bot"], item["context"]["project"])
                for item in fixture["cases"]
            }
            primary_context = sorted(contexts)[0]
            primary = module.MemoryWikiProvider()
            primary.initialize(
                primary_context[0], hermes_home=tmp, bot_id=primary_context[1],
                project_id=primary_context[2],
            )
            providers[primary_context] = primary
            _insert_fixture(primary, module, fixture)
            for session, bot, project in sorted(contexts - {primary_context}):
                provider = module.MemoryWikiProvider()
                provider.initialize(session, hermes_home=tmp, bot_id=bot, project_id=project)
                providers[(session, bot, project)] = provider
            reindex = None
            if semantic:
                reindex = primary._reindex()
                if not reindex.get("ok"):
                    raise RuntimeError(f"isolated semantic reindex failed: {reindex.get('error')}")
            scores = [_score_cases(providers, fixture, mode="fts")]
            scores.append(_score_cases(providers, fixture, mode="hybrid"))
            result = {
                "fixture_version": fixture["version"],
                "fixture_claims": len(fixture["claims"]),
                "fixture_cases": len(fixture["cases"]),
                "semantic": semantic,
                "reindex": {key: reindex.get(key) for key in ("ok", "count", "total", "status")}
                if reindex else None,
                "scores": scores,
            }
        finally:
            for provider in providers.values():
                try:
                    provider.shutdown()
                except Exception:
                    pass
            if semantic and module is not None:
                # The name is generated in this call, never supplied by the user.
                physical = module._physical_collection_name()
                if physical.startswith(collection + "_"):
                    deleted = module._qdrant_req("DELETE", f"/collections/{physical}", timeout=10)
                    if result is not None:
                        result["isolated_collection_removed"] = bool(
                            isinstance(deleted, dict)
                            and str(deleted.get("status") or "ok") == "ok"
                            and deleted.get("result") is not False
                        )
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--semantic", action="store_true", help="Use live embeddings and isolated Qdrant collection")
    parser.add_argument("--env-file", type=Path, help="Optional dotenv file containing configured service credentials")
    args = parser.parse_args()
    print(json.dumps(run(args.fixture, semantic=args.semantic, env_file=args.env_file), ensure_ascii=False, indent=2))
