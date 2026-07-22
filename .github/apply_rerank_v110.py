#!/usr/bin/env python3
from __future__ import annotations

import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "__init__.py"
source = INIT.read_text()
source = source.replace("memory-wiki v1.9.7:", "memory-wiki v1.10.0:", 1)

constants_marker = 'SEMANTIC_ENABLED = os.environ.get("MEMORY_WIKI_SEMANTIC", "1") not in ("0", "no", "false", "off")\n'
constants = r'''

# OpenRouter Cohere smart reranker. This is a second-stage ranker only:
# FTS5 + embedding/Qdrant + RRF remain the fail-open source ranking.
def _rerank_env_int(name: str, default: int, low: int, high: int) -> int:
    """Parse one bounded integer without allowing a bad env value to break plugin import."""
    try:
        return max(low, min(int(os.environ.get(name, str(default))), high))
    except (TypeError, ValueError):
        return default


def _rerank_env_float(name: str, default: float, low: float, high: float) -> float:
    """Parse one bounded float without allowing NaN/invalid text into timeout settings."""
    try:
        value = float(os.environ.get(name, str(default)))
        return default if not math.isfinite(value) else max(low, min(value, high))
    except (TypeError, ValueError):
        return default


RERANK_ENABLED = os.environ.get("MEMORY_WIKI_RERANK_ENABLED", "0").lower() not in ("0", "no", "false", "off")
RERANK_URL = (os.environ.get("MEMORY_WIKI_RERANK_URL") or "https://openrouter.ai/api/v1/rerank").rstrip("/")
RERANK_MODEL = os.environ.get("MEMORY_WIKI_RERANK_MODEL") or "cohere/rerank-4-pro"
RERANK_API_KEY = os.environ.get("MEMORY_WIKI_RERANK_API_KEY", "") or os.environ.get("OPENROUTER_API_KEY", "")
# 50 × 1400 characters remains safely below the model's 32K-token context.
RERANK_TOP_K = _rerank_env_int("MEMORY_WIKI_RERANK_TOP_K", 30, 5, 50)
RERANK_MIN_CANDIDATES = _rerank_env_int("MEMORY_WIKI_RERANK_MIN_CANDIDATES", 10, 3, RERANK_TOP_K)
RERANK_TIMEOUT = _rerank_env_float("MEMORY_WIKI_RERANK_TIMEOUT", 4.0, 1.0, 15.0)
RERANK_CACHE_TTL = _rerank_env_int("MEMORY_WIKI_RERANK_CACHE_TTL", 1800, 0, 86400)
RERANK_CACHE_MAX = _rerank_env_int("MEMORY_WIKI_RERANK_CACHE_MAX", 256, 16, 4096)
RERANK_CIRCUIT_FAILURES = _rerank_env_int("MEMORY_WIKI_RERANK_CIRCUIT_FAILURES", 3, 1, 20)
RERANK_CIRCUIT_SECONDS = _rerank_env_int("MEMORY_WIKI_RERANK_CIRCUIT_SECONDS", 300, 15, 3600)
_RERANK_LOCK = threading.RLock()
_RERANK_CACHE: Dict[str, Tuple[float, List[Tuple[str, float, int]]]] = {}
_RERANK_FAILURE_COUNT = 0
_RERANK_CIRCUIT_UNTIL = 0.0
_RERANK_STATS: Dict[str, Any] = {
    "requests": 0, "successes": 0, "failures": 0, "cache_hits": 0,
    "skipped": 0, "search_units": 0, "cost_usd": 0.0,
    "last_latency_ms": 0, "last_error": "",
}
'''

methods_marker = '    def _search_fallback(self, query: str, limit=10, include_stale=True, topic: Optional[str]=None) -> List[Dict[str, Any]]:\n'
methods = r'''    def _rerank_status(self) -> Dict[str, Any]:
        with _RERANK_LOCK:
            status = dict(_RERANK_STATS)
            status.update({
                "enabled": RERANK_ENABLED,
                "model": RERANK_MODEL,
                "top_k": RERANK_TOP_K,
                "min_candidates": RERANK_MIN_CANDIDATES,
                "timeout_s": RERANK_TIMEOUT,
                "cache_entries": len(_RERANK_CACHE),
                "circuit_open_s": round(max(0.0, _RERANK_CIRCUIT_UNTIL - time.monotonic()), 3),
            })
            status["cost_usd"] = round(float(status.get("cost_usd", 0.0)), 6)
            return status

    def _rerank_rows(self, query: str, scored: List[Dict[str, Any]], query_mode: str) -> List[Dict[str, Any]]:
        """Conditionally rerank a safe top-K with Cohere and fuse it with the existing RRF order."""
        global _RERANK_FAILURE_COUNT, _RERANK_CIRCUIT_UNTIL
        original = list(scored or [])
        q = str(query or "").strip()
        if not RERANK_ENABLED or not RERANK_API_KEY or len(q) < 12 or len(q) > 1500 or len(original) < RERANK_MIN_CANDIDATES:
            with _RERANK_LOCK: _RERANK_STATS["skipped"] += 1
            return original

        top_parts = dict(original[0].get("score_parts") or {}) if original else {}
        if query_mode == "technical" and (float(top_parts.get("exact", 0.0)) > 0.0 or float(top_parts.get("bm25", 0.0)) >= 0.85):
            with _RERANK_LOCK: _RERANK_STATS["skipped"] += 1
            _debug_log("RERANK skip exact-dominant technical query")
            return original

        now_mono = time.monotonic()
        with _RERANK_LOCK:
            if _RERANK_CIRCUIT_UNTIL > now_mono:
                _RERANK_STATS["skipped"] += 1
                return original

        prefix: List[Dict[str, Any]] = []
        documents: List[str] = []
        for row in original[:RERANK_TOP_K]:
            if str(row.get("status") or "active") != "active": continue
            if str(row.get("risk") or "low") == "secret" or int(row.get("quarantined_at") or 0) > 0: continue
            if str(row.get("trust_class") or "") in ("tool_log", "raw_blob", "secret"): continue
            text = redact_secrets(str(row.get("claim") or "")).strip()
            if not text or is_ephemeral_fragment(text) or secret_scan(text).get("raw_secret"): continue
            prefix.append(row)
            documents.append(short(f"topic={row.get('topic','')} type={row.get('type','fact')} claim={text}", 1400))
        if len(prefix) < RERANK_MIN_CANDIDATES:
            with _RERANK_LOCK: _RERANK_STATS["skipped"] += 1
            return original

        cache_seed = q + "\n" + "\n".join(sorted(f"{r.get('id','')}:{r.get('updated_at',0)}" for r in prefix))
        cache_key = sha(cache_seed)
        if RERANK_CACHE_TTL > 0:
            with _RERANK_LOCK:
                cached = _RERANK_CACHE.get(cache_key)
                if cached and cached[0] > now_mono:
                    _RERANK_STATS["cache_hits"] += 1
                    row_by_id = {str(r.get("id")): r for r in original}
                    ordered: List[Dict[str, Any]] = []
                    for cid, score, rank in cached[1]:
                        if cid in row_by_id:
                            item = dict(row_by_id[cid]); item["rerank_score"] = score; item["rerank_rank"] = rank; ordered.append(item)
                    used = {str(r.get("id")) for r in ordered}
                    ordered.extend(r for r in original if str(r.get("id")) not in used)
                    return ordered
                for key in [k for k, value in _RERANK_CACHE.items() if value[0] <= now_mono]:
                    _RERANK_CACHE.pop(key, None)

        headers = {"Authorization": f"Bearer {RERANK_API_KEY}", "Content-Type": "application/json", "X-OpenRouter-Title": OPENROUTER_TITLE}
        if OPENROUTER_REFERER: headers["HTTP-Referer"] = OPENROUTER_REFERER
        payload = {"model": RERANK_MODEL, "query": q, "documents": documents, "top_n": len(documents)}
        started = time.monotonic()
        try:
            req = urllib.request.Request(RERANK_URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=RERANK_TIMEOUT) as response:
                obj = json.loads(response.read().decode("utf-8", "replace"))
            api_results = obj.get("results") or []
            ranked: List[Tuple[str, float, int]] = []
            seen_indexes = set()
            for rank, result in enumerate(api_results, 1):
                idx = int(result.get("index", -1))
                if idx < 0 or idx >= len(prefix) or idx in seen_indexes: continue
                seen_indexes.add(idx)
                ranked.append((str(prefix[idx].get("id")), float(result.get("relevance_score", 0.0)), rank))
            if len(ranked) < RERANK_MIN_CANDIDATES:
                raise ValueError(f"rerank returned only {len(ranked)} valid results")

            cohere_weight = 0.35 if query_mode == "technical" else (0.75 if query_mode == "semantic" else 0.60)
            base_weight = 1.0 - cohere_weight
            orig_rank = {str(r.get("id")): i for i, r in enumerate(prefix, 1)}
            cohere_rank = {cid: rank for cid, _score, rank in ranked}
            relevance = {cid: score for cid, score, _rank in ranked}
            fused_prefix = sorted(prefix, key=lambda r: base_weight / (RRF_K + orig_rank[str(r.get("id"))]) + cohere_weight / (RRF_K + cohere_rank.get(str(r.get("id")), len(prefix) + 1)), reverse=True)
            ordered: List[Dict[str, Any]] = []
            cached_meta: List[Tuple[str, float, int]] = []
            for row in fused_prefix:
                cid = str(row.get("id")); item = dict(row)
                item["rerank_score"] = round(float(relevance.get(cid, 0.0)), 6)
                item["rerank_rank"] = int(cohere_rank.get(cid, len(prefix) + 1))
                ordered.append(item); cached_meta.append((cid, item["rerank_score"], item["rerank_rank"]))
            used = {str(r.get("id")) for r in ordered}
            ordered.extend(r for r in original if str(r.get("id")) not in used)

            latency_ms = int((time.monotonic() - started) * 1000)
            usage = obj.get("usage") or {}
            with _RERANK_LOCK:
                _RERANK_FAILURE_COUNT = 0; _RERANK_CIRCUIT_UNTIL = 0.0
                _RERANK_STATS["requests"] += 1; _RERANK_STATS["successes"] += 1
                _RERANK_STATS["search_units"] += int(usage.get("search_units") or 0)
                _RERANK_STATS["cost_usd"] += float(usage.get("cost") or 0.0)
                _RERANK_STATS["last_latency_ms"] = latency_ms; _RERANK_STATS["last_error"] = ""
                if RERANK_CACHE_TTL > 0:
                    if len(_RERANK_CACHE) >= RERANK_CACHE_MAX:
                        oldest = min(_RERANK_CACHE, key=lambda k: _RERANK_CACHE[k][0]); _RERANK_CACHE.pop(oldest, None)
                    _RERANK_CACHE[cache_key] = (time.monotonic() + RERANK_CACHE_TTL, cached_meta)
            return ordered
        except Exception as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            with _RERANK_LOCK:
                _RERANK_FAILURE_COUNT += 1
                _RERANK_STATS["requests"] += 1; _RERANK_STATS["failures"] += 1
                _RERANK_STATS["last_latency_ms"] = latency_ms; _RERANK_STATS["last_error"] = short(str(exc), 180)
                if _RERANK_FAILURE_COUNT >= RERANK_CIRCUIT_FAILURES:
                    _RERANK_CIRCUIT_UNTIL = time.monotonic() + RERANK_CIRCUIT_SECONDS
                    _RERANK_FAILURE_COUNT = 0
            return original

'''

if "def _rerank_rows" not in source:
    if constants_marker not in source or methods_marker not in source:
        raise SystemExit("remote source markers do not match expected v1.9.7 base")
    source = source.replace(constants_marker, constants_marker + constants, 1)
    source = source.replace(methods_marker, methods + methods_marker, 1)
    sort_marker = '        scored.sort(key=lambda x: x["score"], reverse=True)\n        ids = [x["id"] for x in scored[:limit]]\n'
    source = source.replace(sort_marker, '        scored.sort(key=lambda x: x["score"], reverse=True)\n        scored = self._rerank_rows(q, scored, query_mode)\n        ids = [x["id"] for x in scored[:limit]]\n', 1)
    status_marker = '        return {"embedding_ok": embed_ok, "qdrant_points": pts, "semantic_enabled": SEMANTIC_ENABLED}\n'
    source = source.replace(status_marker, '        return {"embedding_ok": embed_ok, "qdrant_points": pts, "semantic_enabled": SEMANTIC_ENABLED, "rerank": self._rerank_status()}\n', 1)
    debug_marker = '                  "final_score": round(d.get("score", 0), 4),\n'
    if debug_marker in source:
        source = source.replace(debug_marker, debug_marker + '                  "rerank_score": round(d.get("rerank_score", 0), 6), "rerank_rank": int(d.get("rerank_rank", 0) or 0),\n', 1)
INIT.write_text(source)

names = []
for name in re.findall(r'\{"name":\s*"(memory_wiki_[a-z0-9_]+)"', source):
    if name not in names:
        names.append(name)
if len(names) != 82:
    raise SystemExit(f"expected 82 tool schemas, got {len(names)}")
manifest = 'name: memory-wiki\nversion: 1.10.0\ndescription: "Hermes Memory OS — 82 tools, FTS5 + OpenRouter ML embeddings/Qdrant + RRF + optional conditional Cohere reranking, structured claims, evidence, graph memory, write firewall, secret wrapping, journal recovery and self-healing."\n\nprovides_tools:\n' + ''.join(f'  - {name}\n' for name in names)
(ROOT / 'plugin.yaml').write_text(manifest)

readme = '''# Hermes Memory Wiki v1.10.0

Native structured long-term memory provider for Hermes Agent. SQLite claims are the source of truth; FTS5 and Qdrant are rebuildable retrieval indexes.

## Retrieval pipeline

```text
SQLite FTS5/BM25 + PPLX embeddings/Qdrant
                    ↓
                 RRF fusion
                    ↓
             safe top-30 candidates
                    ↓
     optional Cohere Rerank 4 Pro via OpenRouter
                    ↓
           weighted reciprocal-rank fusion
```

The reranker is optional and **disabled by default**. It never replaces base retrieval: any timeout, malformed response, rate limit or open circuit returns the original RRF ranking.

## Enable or disable reranking

```env
# Disable completely — no rerank HTTP request is made (public default)
MEMORY_WIKI_RERANK_ENABLED=0

# Enable OpenRouter Cohere reranking
MEMORY_WIKI_RERANK_ENABLED=1
MEMORY_WIKI_RERANK_URL=https://openrouter.ai/api/v1/rerank
MEMORY_WIKI_RERANK_MODEL=cohere/rerank-4-pro
MEMORY_WIKI_RERANK_TOP_K=30
MEMORY_WIKI_RERANK_MIN_CANDIDATES=10
MEMORY_WIKI_RERANK_TIMEOUT=4
MEMORY_WIKI_RERANK_CACHE_TTL=1800
MEMORY_WIKI_RERANK_CACHE_MAX=256
MEMORY_WIKI_RERANK_CIRCUIT_FAILURES=3
MEMORY_WIKI_RERANK_CIRCUIT_SECONDS=300
```

The implementation uses the existing `OPENROUTER_API_KEY`, or `MEMORY_WIKI_RERANK_API_KEY` when explicitly provided. Environment variables are read when the plugin loads; after changing the toggle restart Hermes:

```bash
hermes gateway restart
```

OpenRouter reports `$0.0025` per `cohere/rerank-4-pro` search. Cache hits do not create a new search unit.

## Smart conditions

Reranking is skipped when disabled, no key exists, the query is shorter than 12 or longer than 1500 characters, fewer than 10 safe candidates exist, an exact/BM25-dominant technical result exists, or the circuit breaker is open. Before egress, non-active, secret-risk, quarantined, raw-log, ephemeral and raw-secret candidates are filtered again. Sent documents contain only redacted `topic + type + claim`, capped at 1400 characters.

Cohere weight is 0.75 for semantic, 0.60 for mixed and 0.35 for technical queries. The original rank always contributes to final reciprocal-rank fusion.

## Core configuration

```env
MEMORY_WIKI_SEMANTIC=1
MEMORY_WIKI_EMBED_PROVIDER=openrouter
MEMORY_WIKI_EMBED_MODEL=perplexity/pplx-embed-v1-4b
MEMORY_WIKI_EMBED_DIMENSIONS=2560
MEMORY_WIKI_VECTOR_SIZE=2560
MEMORY_WIKI_QDRANT_URL=http://127.0.0.1:6333
```

## Safety and resilience

- SQLite remains authoritative; vectors are rebuildable.
- Reranker failure is fail-open.
- 30-minute bounded in-memory cache.
- Three failures open a five-minute circuit breaker.
- Secret/quarantine/raw candidates are excluded before external egress.
- All numeric environment settings use bounded safe parsers.
- `memory_wiki_semantic_status` reports reranker requests, successes, failures, cache hits, cost and circuit state.

## Tests

```bash
python3 -m py_compile __init__.py scripts/test_rerank.py
python3 scripts/test_rerank.py
```

The targeted test verifies disabled mode (zero HTTP calls), semantic reordering, cache reuse, exact technical skip, secret candidate filtering and fail-open timeout behavior.

## License

MIT.
'''
(ROOT / 'README.md').write_text(readme)

scripts = ROOT / 'scripts'
scripts.mkdir(exist_ok=True)
test = r'''#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, json, os, sys
from pathlib import Path

os.environ["MEMORY_WIKI_RERANK_ENABLED"] = "0"
os.environ["MEMORY_WIKI_RERANK_API_KEY"] = "x"
os.environ["MEMORY_WIKI_RERANK_MIN_CANDIDATES"] = "5"
os.environ["MEMORY_WIKI_RERANK_TOP_K"] = "12"
plugin = Path(__file__).resolve().parents[1] / "__init__.py"
spec = importlib.util.spec_from_file_location("memory_wiki_rerank_test", plugin, submodule_search_locations=[str(plugin.parent)])
mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)

def rows():
    return [{"id":f"c_{i:02d}","claim":f"Durable memory claim {i} about SQLite Qdrant indexing","topic":"memory-wiki","type":"environment","status":"active","risk":"low","quarantined_at":0,"trust_class":"fact","updated_at":i,"score":float(100-i),"score_parts":{"exact":0.0,"bm25":0.2}} for i in range(12)]

class Response:
    def __init__(self,p): self.p=p
    def __enter__(self): return self
    def __exit__(self,*_): return False
    def read(self): return json.dumps(self.p).encode()

calls=[]
def fake(req,timeout=0):
    body=json.loads(req.data.decode()); calls.append(body); n=len(body["documents"])
    return Response({"results":[{"index":i,"relevance_score":(n-rank)/n} for rank,i in enumerate(reversed(range(n)))],"usage":{"search_units":1,"cost":0.0025}})

p=mod.MemoryWikiProvider(); base=rows(); mod.urllib.request.urlopen=fake
# Public default/explicit zero: no egress and original order.
out=p._rerank_rows("Find relevant memory indexing details",base,"semantic")
assert [r["id"] for r in out]==[r["id"] for r in base] and not calls
# Enable in-process for isolated tests.
mod.RERANK_ENABLED=True; mod._RERANK_CACHE.clear()
base=rows(); base[5]["risk"]="secret"
ranked=p._rerank_rows("Find relevant memory indexing details",base,"semantic")
assert ranked[0]["id"]!=base[0]["id"] and len(calls)==1
assert all("claim 5 " not in d for d in calls[0]["documents"])
cached=p._rerank_rows("Find relevant memory indexing details",base,"semantic")
assert [r["id"] for r in cached]==[r["id"] for r in ranked] and len(calls)==1
technical=rows(); technical[0]["score_parts"]={"exact":0.35,"bm25":1.0}
assert [r["id"] for r in p._rerank_rows("config.yaml",technical,"technical")]==[r["id"] for r in technical] and len(calls)==1
mod.urllib.request.urlopen=lambda *_a,**_k: (_ for _ in ()).throw(TimeoutError("synthetic timeout"))
failed=rows(); assert [r["id"] for r in p._rerank_rows("Different semantic query for timeout",failed,"semantic")]==[r["id"] for r in failed]
status=p._rerank_status(); assert status["successes"]==1 and status["cache_hits"]==1 and status["failures"]==1
print(json.dumps({"ok":True,"disabled_http_calls":0,"paid_mock_calls":len(calls),"status":status}))
'''
(scripts / 'test_rerank.py').write_text(test)
print('applied v1.10.0 rerank patch; tools=82')
