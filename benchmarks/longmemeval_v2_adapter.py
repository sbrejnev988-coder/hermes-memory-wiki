"""LongMemEval-V2 text retrieval probe for Memory Wiki.

This is deliberately separate from the LongMemEval (2024) dialogue adapter.
V2 contains web-agent trajectories and optional screenshots, and its public
questions do not identify gold trajectory/state evidence. This script measures
offline FTS indexing and query latency; it does not produce the official V2 QA
or LAFS score. It never sends data to Qdrant, OpenRouter, or the live profile.

Inputs follow https://github.com/xiaowu0162/LongMemEval-V2 and the official
dataset schema at https://huggingface.co/datasets/xiaowu0162/longmemeval-v2.
The 1.2 GB trajectories JSONL is streamed one record at a time. A partial
prefix may be used only with --allow-partial and is explicitly reported.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_REPOSITORY = "https://github.com/xiaowu0162/LongMemEval-V2"
OFFICIAL_DATASET = "https://huggingface.co/datasets/xiaowu0162/longmemeval-v2"
OFFICIAL_DATASET_REVISION = "f152293e235517d504809563c833d7190b8c713b"
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
ENV = {
    "HERMES_SECURITY_STRICT": "0",
    "MEMORY_WIKI_SEMANTIC": "0",
    "MEMORY_WIKI_RERANK_ENABLED": "0",
    "MEMORY_WIKI_GRAPH_EXTRACT_ENABLED": "0",
    "MEMORY_WIKI_EPISODIC_ENABLED": "0",
    "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE": "0",
}


def _jsonl(path: Path, *, allow_partial: bool = False) -> Iterator[dict[str, Any]]:
    """Stream complete UTF-8 JSONL rows, detecting an interrupted final row."""
    with path.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            if not raw.endswith(b"\n"):
                if allow_partial:
                    break
                raise ValueError(f"incomplete JSONL record at {path}:{line_no}")
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid JSONL record at {path}:{line_no}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"JSONL record must be an object at {path}:{line_no}")
            yield item


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _official_hashes(data_root: Path) -> dict[str, str]:
    path = data_root / "checksums.sha256"
    if not path.exists():
        return {}
    hashes: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise ValueError("invalid official checksums.sha256")
        hashes[parts[1].lstrip("* ")] = parts[0]
    return hashes


def load_metadata(data_root: Path, *, tier: str, domain: str, limit: int,
                  include_image_questions: bool = False) -> tuple[list[dict[str, Any]], dict[str, list[str]], dict[str, Any]]:
    if tier not in {"small", "medium"} or domain not in {"web", "enterprise"} or limit < 1:
        raise ValueError("tier, domain, or limit is invalid")
    qpath = data_root / "questions.jsonl"
    hpath = data_root / "haystacks" / f"lme_v2_{tier}.json"
    expected = _official_hashes(data_root)
    checks = {}
    for rel, path in (("questions.jsonl", qpath), (f"haystacks/lme_v2_{tier}.json", hpath)):
        digest = _sha256(path)
        checks[rel] = {"sha256": digest, "official_sha256_match": digest == expected[rel] if rel in expected else None}
        if rel in expected and digest != expected[rel]:
            raise ValueError(f"official checksum mismatch for {rel}")
    questions = list(_jsonl(qpath))
    seen: set[str] = set()
    for q in questions:
        if (not isinstance(q.get("id"), str) or not SAFE_ID.fullmatch(q["id"])
                or q["id"] in seen or q.get("domain") not in {"web", "enterprise"}
                or not isinstance(q.get("environment"), str)
                or not isinstance(q.get("question_type"), str)
                or not isinstance(q.get("question"), str) or not q["question"].strip()
                or (q.get("image") is not None and not isinstance(q["image"], str))
                or "answer" not in q or not isinstance(q.get("eval_function"), str)):
            raise ValueError("invalid or duplicate V2 question")
        seen.add(q["id"])
    haystack = json.loads(hpath.read_text(encoding="utf-8"))
    if not isinstance(haystack, dict) or set(haystack) != seen:
        raise ValueError("V2 haystack question IDs do not match questions")
    for q in questions:
        ids = haystack[q["id"]]
        if (not isinstance(ids, list) or not ids or
                any(not isinstance(x, str) or not SAFE_ID.fullmatch(x) for x in ids) or
                len(ids) != len(set(ids)) or (tier == "small" and len(ids) != 100)):
            raise ValueError("invalid V2 haystack trajectory IDs")
    eligible = [q for q in questions if q["domain"] == domain and (include_image_questions or not q["image"])]
    selected = eligible[:limit]
    if not selected:
        raise ValueError("no V2 questions selected")
    return selected, haystack, {
        "dataset_questions": len(questions), "domain_questions": sum(q["domain"] == domain for q in questions),
        "selected_image_questions": sum(bool(q["image"]) for q in selected),
        "excluded_image_questions": sum(q["domain"] == domain and bool(q["image"]) for q in questions) if not include_image_questions else 0,
        "checksums": checks,
    }


def _validate_trajectory(row: dict[str, Any]) -> None:
    if (not isinstance(row.get("id"), str) or not SAFE_ID.fullmatch(row["id"])
            or row.get("domain") not in {"web", "enterprise"}
            or not isinstance(row.get("environment"), str)
            or not isinstance(row.get("goal"), str)
            or not isinstance(row.get("outcome"), str)
            or not isinstance(row.get("states"), list)):
        raise ValueError("invalid V2 trajectory")
    for index, state in enumerate(row["states"]):
        if (not isinstance(state, dict) or state.get("state_index") != index
                or not isinstance(state.get("accessibility_tree"), str)
                or not isinstance(state.get("url"), str)
                or (state.get("thought") is not None and not isinstance(state["thought"], str))
                or (state.get("screenshot") is not None and not isinstance(state["screenshot"], str))):
            raise ValueError(f"invalid V2 trajectory state {row['id']}:{index}")


def _load_plugin() -> Any:
    name = f"memory_wiki_lmev2_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Memory Wiki")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


@contextmanager
def _isolated_home(path: Path) -> Iterator[None]:
    values = {"HERMES_HOME": str(path), **ENV}
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _state_chunks(trajectory: dict[str, Any], state: dict[str, Any], max_state_chars: int) -> tuple[list[str], int]:
    def scalar(value: Any) -> str:
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    # The product recall path rejects raw multiline blobs and >1,800-char
    # fragments, so index compact text excerpts instead of entire states.
    header = " ".join((
        f"Trajectory goal: {trajectory['goal']}; Outcome: {trajectory['outcome']}; "
        f"URL: {state['url']}; Action: {scalar(state.get('action'))}; "
        f"Thought: {state.get('thought') or ''}; Accessibility tree:"
    ).split())[:350]
    tree = state["accessibility_tree"]
    omitted = max(0, len(tree) - max_state_chars)
    tree = " ".join(tree[:max_state_chars].split())
    budget = 1600 - len(header)
    chunks = []
    for start in range(0, max(1, len(tree)), budget):
        text = (header + " " + tree[start:start + budget]).strip()
        if len(text) >= 10:
            chunks.append(text)
    return chunks, omitted


def _index_trajectory(provider: Any, row: dict[str, Any], *, max_state_chars: int,
                      claim_to_state: dict[str, tuple[str, int]]) -> dict[str, int]:
    stamp = int(time.time())
    insert_rows = []
    omitted = screenshots = 0
    for state in row["states"]:
        chunks, lost = _state_chunks(row, state, max_state_chars)
        omitted += lost
        screenshots += bool(state.get("screenshot"))
        for part, text in enumerate(chunks):
            provenance = f"{row['id']}:{state['state_index']}:{part}"
            claim_id = "v2_" + hashlib.sha256(provenance.encode()).hexdigest()[:24]
            claim_to_state[claim_id] = (row["id"], state["state_index"])
            insert_rows.append((
                claim_id, text, text, "longmemeval_v2", "active", .9, .8,
                "benchmark:longmemeval_v2:raw_state", "", stamp, stamp, stamp,
                hashlib.sha256((claim_id + "\0" + text).encode()).hexdigest(),
                "global", "global", .9, "low", "fact", provenance,
            ))
    with provider._connect() as conn:
        conn.executemany("""INSERT INTO claims(
            id,claim,normalized_claim,topic,status,confidence,salience,source,evidence,
            created_at,updated_at,freshness_at,hash,scope,visibility_scope,
            quality,risk,trust_class,source_ref)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", insert_rows)
    return {"states": len(row["states"]), "chunks": len(insert_rows),
            "accessibility_chars_omitted": omitted, "screenshot_references": screenshots}


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile)))], 2)


def run(data_root: Path, *, tier: str = "small", domain: str = "web", limit: int = 20,
        top_k: int = 5, max_state_chars: int = 20_000,
        allow_partial: bool = False, include_image_questions: bool = False) -> dict[str, Any]:
    if not 1 <= top_k <= 50 or not 1000 <= max_state_chars <= 200_000:
        raise ValueError("top_k or max_state_chars is invalid")
    data_root = data_root.resolve()
    questions, haystack, metadata = load_metadata(
        data_root, tier=tier, domain=domain, limit=limit,
        include_image_questions=include_image_questions,
    )
    selected_haystacks = {tuple(haystack[q["id"]]) for q in questions}
    if len(selected_haystacks) != 1:
        raise ValueError("selected questions have different haystacks; select one shared domain/tier")
    ordered_ids = next(iter(selected_haystacks))
    wanted = set(ordered_ids)
    trajectory_path = data_root / "trajectories.jsonl"
    expected = _official_hashes(data_root).get("trajectories.jsonl")
    observed: set[str] = set()
    claim_to_state: dict[str, tuple[str, int]] = {}
    totals: Counter[str] = Counter()
    start = time.perf_counter()
    home = Path(tempfile.mkdtemp(prefix="memory-wiki-lmev2-"))
    with _isolated_home(home):
        module = _load_plugin()
        provider = module.MemoryWikiProvider()
        try:
            provider.initialize("longmemeval-v2", hermes_home=str(home),
                                bot_id="longmemeval-v2-benchmark", project_id="longmemeval-v2")
            for row in _jsonl(trajectory_path, allow_partial=allow_partial):
                tid = row.get("id")
                if tid not in wanted:
                    continue
                _validate_trajectory(row)
                if row["domain"] != domain or tid in observed:
                    raise ValueError("duplicate or cross-domain V2 trajectory in haystack")
                observed.add(tid)
                totals.update(_index_trajectory(provider, row, max_state_chars=max_state_chars,
                                                claim_to_state=claim_to_state))
            missing = wanted - observed
            if missing and not allow_partial:
                raise ValueError(f"V2 haystack is incomplete: {len(missing)} trajectories missing")
            provider._rebuild_fts()
            index_ms = round((time.perf_counter() - start) * 1000, 2)
            scored = []
            for q in questions:
                qstart = time.perf_counter()
                hits = provider._search(q["question"], limit=top_k, retrieval_mode="fts",
                                        record_retrieval=False, apply_rerank=False)
                latency = (time.perf_counter() - qstart) * 1000
                sources = [claim_to_state.get(str(hit["id"])) for hit in hits]
                sources = [item for item in sources if item]
                scored.append({
                    "question_id": q["id"], "question_type": q["question_type"],
                    "image_question": bool(q["image"]), "hits": len(sources),
                    "unique_trajectories": len({tid for tid, _ in sources}),
                    "retrieved_state_ids": [f"{tid}:{state}" for tid, state in sources],
                    "search_ms": round(latency, 2),
                })
        finally:
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None
            sys.modules.pop(module.__name__, None)
    actual_sha = _sha256(trajectory_path)
    checksum_ok = actual_sha == expected if expected else None
    if checksum_ok is False and not allow_partial:
        raise ValueError("official checksum mismatch for trajectories.jsonl")
    latencies = [r["search_ms"] for r in scored]
    return {
        "benchmark": "LongMemEval-V2 text-only retrieval probe",
        "source_repository": OFFICIAL_REPOSITORY,
        "source_dataset": OFFICIAL_DATASET,
        "source_dataset_revision": OFFICIAL_DATASET_REVISION,
        "tier": tier, "domain": domain, "dataset": str(data_root),
        "isolated_hermes_home": str(home),
        "dataset_metadata": metadata,
        "trajectory_file_bytes": trajectory_path.stat().st_size,
        "trajectory_file_sha256": actual_sha,
        "official_trajectory_checksum_match": checksum_ok,
        "allow_partial": allow_partial,
        "official_haystack_trajectories": len(ordered_ids),
        "indexed_haystack_trajectories": len(observed),
        "missing_haystack_trajectories": len(wanted - observed),
        "states_indexed": totals["states"], "chunks_indexed": totals["chunks"],
        "accessibility_chars_omitted": totals["accessibility_chars_omitted"],
        "screenshot_references_not_indexed": totals["screenshot_references"],
        "index_ms": index_ms,
        "evaluated_questions": len(scored), "top_k": top_k,
        "questions_with_hits": sum(bool(r["hits"]) for r in scored),
        "query_p50_ms": _percentile(latencies, .5),
        "query_p95_ms": _percentile(latencies, .95),
        "official_qa_score": None, "gold_evidence_recall": None,
        "method": "raw text state chunks inserted into an isolated SQLite FTS index; automatic memory extraction bypassed",
        "limitations": [
            "The public V2 questions have no gold trajectory/state evidence IDs; retrieval hit counts are not accuracy.",
            "Screenshot pixels and image questions are not evaluated by this text-only adapter.",
            "Accessibility trees beyond max_state_chars are truncated per state; the omitted count is reported.",
            "Trajectory rows are indexed in dataset-file order, while the official harness inserts in haystack order.",
            "Official answer accuracy and LAFS need the V2 reader, judge, and full multimodal haystack.",
        ],
        "questions": scored,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--tier", choices=("small", "medium"), default="small")
    parser.add_argument("--domain", choices=("web", "enterprise"), default="web")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-state-chars", type=int, default=20_000)
    parser.add_argument("--allow-partial", action="store_true", help="Accept a truncated trajectories.jsonl prefix; report missing haystack rows")
    parser.add_argument("--include-image-questions", action="store_true", help="Include questions with unavailable image pixels as text-only queries")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.resolve() in {(args.data_root / "questions.jsonl").resolve(),
                                                   (args.data_root / "trajectories.jsonl").resolve()}:
        parser.error("--output must differ from dataset inputs")
    report = run(args.data_root, tier=args.tier, domain=args.domain, limit=args.limit,
                 top_k=args.top_k, max_state_chars=args.max_state_chars,
                 allow_partial=args.allow_partial,
                 include_image_questions=args.include_image_questions)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
