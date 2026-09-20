"""Isolated A/B experiment for bounded, local retrieval diversity.

Supply a local official LongMemEval JSON. LoCoMo is read only when a local
file is supplied or --download-locomo is explicitly requested. This harness
does not modify the plugin or access the active Hermes profile.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import longmemeval_adapter as lm
import locomo_adapter as lo


VARIANTS = ("baseline", "resort", "text_mmr", "event", "event_guarded")
_MULTI_EVIDENCE_QUERY = re.compile(
    r"\b(?:how many|number of|count|total|first|last|before|after|across|over time|"
    r"different|various|each|сколько|всего|перв\w*|последн\w*|до|после|разн\w*|кажд\w*)\b",
    re.IGNORECASE,
)


def _text_mmr(rows: list[dict[str, Any]], tokenize: Callable[[str], set[str]], *,
              cap: int = 40, weight: float = 0.18) -> list[dict[str, Any]]:
    """Reorder only an already visible candidate prefix; keep top-1 stable."""
    if len(rows) < 3:
        return rows
    pool = list(rows[:cap])
    rest = list(rows[cap:])
    terms = {str(row["id"]): {word for word in tokenize(str(row.get("claim") or "")) if len(word) > 2}
             for row in pool}
    highest = max(float(row.get("score") or 0.0) for row in pool)
    selected = [pool.pop(0)]
    while pool:
        def utility(row: dict[str, Any]) -> float:
            words = terms[str(row["id"])]
            similarity = max(
                len(words & terms[str(prior["id"])]) / max(1, len(words | terms[str(prior["id"])]))
                for prior in selected
            )
            return float(row.get("score") or 0.0) - weight * highest * similarity
        best = max(range(len(pool)), key=lambda index: (utility(pool[index]), -index))
        selected.append(pool.pop(best))
    return selected + rest


def _event_diversity(rows: list[dict[str, Any]], query: str, *, guarded: bool,
                     cap: int = 12, score_margin: float = 0.95) -> list[dict[str, Any]]:
    """Use close-scoring evidence from distinct known events after stable top-2."""
    if len(rows) < 4 or (guarded and not _MULTI_EVIDENCE_QUERY.search(query)):
        return rows
    pool = list(rows[:cap])
    selected = [pool.pop(0), pool.pop(0)]
    if len({int(row.get("event_at") or 0) for row in rows[:cap] if int(row.get("event_at") or 0)}) < 2:
        return rows
    while pool:
        current = pool[0]
        event = int(current.get("event_at") or 0)
        seen = {int(row.get("event_at") or 0) for row in selected}
        replacement = None
        if event and event in seen:
            threshold = float(current.get("score") or 0.0) * score_margin
            replacement = next((index for index, item in enumerate(pool[1:], 1)
                                if int(item.get("event_at") or 0) > 0
                                and int(item.get("event_at") or 0) not in seen
                                and float(item.get("score") or 0.0) >= threshold), None)
        selected.append(pool.pop(replacement if replacement is not None else 0))
    return selected + list(rows[cap:])


def _set_variant(provider: Any, original: Callable, variant: str, module: Any, query: str = "") -> None:
    if variant == "baseline":
        provider._apply_diversity = original
    elif variant == "resort":
        provider._apply_diversity = lambda rows, mode: sorted(
            original(rows, mode), key=lambda row: float(row.get("score") or 0.0), reverse=True,
        )
    elif variant == "text_mmr":
        provider._apply_diversity = lambda rows, mode: _text_mmr(
            original(rows, mode), lambda value: set(module.tokens(value)),
        )
    elif variant == "event":
        provider._apply_diversity = lambda rows, mode: _event_diversity(original(rows, mode), query, guarded=False)
    elif variant == "event_guarded":
        provider._apply_diversity = lambda rows, mode: _event_diversity(original(rows, mode), query, guarded=True)
    else:
        raise ValueError(variant)


def _aggregate(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any]:
    scored = [row for row in rows if row.get("scored")]
    result = {"questions": len(rows), "scored": len(scored)}
    for field in fields:
        result[field] = round(statistics.mean(float(row[field]) for row in scored), 4) if scored else None
    result["search_p50_ms"] = round(statistics.median(row["search_ms"] for row in rows), 2) if rows else None
    return result


def run_longmemeval(path: Path, *, limit: int = 500, top_k: int = 5) -> dict[str, Any]:
    cases, total = lm.load_cases(path, limit)
    scored_by_variant: dict[str, list[dict[str, Any]]] = {name: [] for name in VARIANTS}
    with tempfile.TemporaryDirectory(prefix="memory-wiki-lme-ab-") as tmp:
        with lm._isolated_environment(tmp):
            module = lm._load_plugin()
            try:
                for index, case in enumerate(cases):
                    provider = module.MemoryWikiProvider()
                    try:
                        provider.initialize(f"longmemeval-ab-{index}", hermes_home=str(Path(tmp) / f"case-{index:04d}"),
                                            project_id=f"longmemeval-ab-{index}", bot_id="longmemeval-benchmark")
                        claim_sources: dict[str, list[tuple[str, int]]] = defaultdict(list)
                        gold_turns: set[tuple[str, int]] = set()
                        for sid, turn_index, turn, timestamp in lm.chronological_turns(case):
                            if turn.get("has_answer") is True:
                                gold_turns.add((sid, turn_index))
                            if not turn["content"].strip():
                                continue
                            try:
                                cid = provider._add_claim(
                                    turn["content"].strip(), topic="longmemeval",
                                    evidence=f"session={sid}; turn={turn_index}",
                                    source=f"benchmark:longmemeval:{turn['role']}",
                                    visibility_scope="global", event_at=timestamp, event_timezone="UTC",
                                )
                            except Exception:
                                continue
                            if isinstance(cid, str) and cid.startswith("c_"):
                                claim_sources[cid].append((sid, turn_index))
                        original = provider._apply_diversity
                        gold_sessions = set(case["answer_session_ids"])
                        evidence_scored = not case["question_id"].endswith("_abs") and bool(gold_sessions)
                        for variant in VARIANTS:
                            _set_variant(provider, original, variant, module, case["question"])
                            started = time.perf_counter()
                            hits = provider._search(case["question"], limit=top_k, retrieval_mode="fts",
                                                    record_retrieval=False, apply_rerank=False)
                            elapsed = (time.perf_counter() - started) * 1000
                            retrieved = [claim_sources.get(str(hit["id"]), []) for hit in hits]
                            sessions = {sid for sources in retrieved for sid, _ in sources}
                            turns = {item for sources in retrieved for item in sources}
                            rank = next((place for place, sources in enumerate(retrieved, 1)
                                         if any(sid in gold_sessions for sid, _ in sources)), 0)
                            scored_by_variant[variant].append({
                                "question_id": case["question_id"], "category": case["question_type"],
                                "scored": evidence_scored,
                                "session_all": float(gold_sessions <= sessions) if evidence_scored else None,
                                "session_any": float(bool(gold_sessions & sessions)) if evidence_scored else None,
                                "session_mrr": 1 / rank if rank and evidence_scored else 0.0 if evidence_scored else None,
                                "turn_all": float(gold_turns <= turns) if gold_turns and evidence_scored else None,
                                "search_ms": elapsed,
                                "retrieved_ids": [str(hit["id"]) for hit in hits],
                            })
                    finally:
                        connection = getattr(provider, "_conn", None)
                        if connection is not None:
                            connection.close()
                            provider._conn = None
                    if (index + 1) % 50 == 0:
                        print(f"LongMemEval {index + 1}/{len(cases)}", file=sys.stderr, flush=True)
            finally:
                sys.modules.pop(module.__name__, None)
    fields = ("session_all", "session_any", "session_mrr")
    categories = sorted({row["category"] for row in scored_by_variant["baseline"]})
    return {
        "dataset_questions": total, "evaluated_questions": len(cases), "top_k": top_k,
        "scores": {variant: {
            "all": _aggregate(rows, fields),
            "by_category": {cat: _aggregate([row for row in rows if row["category"] == cat], fields)
                            for cat in categories},
        } for variant, rows in scored_by_variant.items()},
        "changes": _changes(scored_by_variant, "session_all"),
    }


def _changes(by_variant: dict[str, list[dict[str, Any]]], field: str) -> dict[str, Any]:
    baseline = by_variant["baseline"]
    result = {}
    for variant in VARIANTS[1:]:
        comparisons = [(left, right) for left, right in zip(baseline, by_variant[variant]) if left["scored"]]
        result[variant] = {
            "improved": sum(right[field] > left[field] for left, right in comparisons),
            "regressed": sum(right[field] < left[field] for left, right in comparisons),
            "changed_top_k": sum(left["retrieved_ids"] != right["retrieved_ids"] for left, right in comparisons),
            "by_category": {
                cat: {
                    "improved": sum(right[field] > left[field] for left, right in comparisons if left["category"] == cat),
                    "regressed": sum(right[field] < left[field] for left, right in comparisons if left["category"] == cat),
                } for cat in sorted({left["category"] for left, _ in comparisons})
            },
        }
    return result


def run_locomo(raw: bytes, *, top_k: int = 5, max_conversations: int | None = None,
               questions_per_conversation: int | None = None) -> dict[str, Any]:
    data = lo._load_dataset(raw)
    selected_data = data[:max_conversations]
    by_variant: dict[str, list[dict[str, Any]]] = {name: [] for name in VARIANTS}
    with tempfile.TemporaryDirectory(prefix="memory-wiki-locomo-ab-") as tmp:
        with lo._isolated_home(tmp):
            module = lo._load_plugin()
            try:
                for index, sample in enumerate(selected_data):
                    provider = module.MemoryWikiProvider()
                    try:
                        provider.initialize(f"locomo-ab-{index}", hermes_home=str(Path(tmp) / f"sample-{index}"),
                                            bot_id="locomo-benchmark", project_id=f"locomo-{index}")
                        indexed = lo._index_turns(provider, module, sample)
                        mapping = indexed["claim_to_dialogue"]
                        original = provider._apply_diversity
                        for question in sample["qa"][:questions_per_conversation]:
                            gold, malformed = lo._evidence_ids(question["evidence"])
                            for variant in VARIANTS:
                                _set_variant(provider, original, variant, module, question["question"])
                                started = time.perf_counter()
                                hits = provider._search(question["question"], limit=top_k, retrieval_mode="fts",
                                                        record_retrieval=False, apply_rerank=False)
                                elapsed = (time.perf_counter() - started) * 1000
                                found = [mapping[str(hit["id"])] for hit in hits if str(hit["id"]) in mapping]
                                intersection = gold & set(found)
                                rank = next((place for place, dia in enumerate(found, 1) if dia in gold), 0)
                                by_variant[variant].append({
                                    "question_id": question["question"], "category": str(question.get("category")),
                                    "scored": bool(gold),
                                    "evidence_recall": len(intersection) / len(gold) if gold else None,
                                    "evidence_all": float(gold <= set(found)) if gold else None,
                                    "evidence_any": float(bool(intersection)) if gold else None,
                                    "evidence_mrr": 1 / rank if rank and gold else 0.0 if gold else None,
                                    "search_ms": elapsed,
                                    "retrieved_ids": found,
                                })
                    finally:
                        connection = getattr(provider, "_conn", None)
                        if connection is not None:
                            connection.close()
                            provider._conn = None
                    print(f"LoCoMo {index + 1}/{len(selected_data)}", file=sys.stderr, flush=True)
            finally:
                sys.modules.pop(module.__name__, None)
    fields = ("evidence_recall", "evidence_all", "evidence_any", "evidence_mrr")
    categories = sorted({row["category"] for row in by_variant["baseline"]})
    return {
        "conversations": len(selected_data), "questions": len(by_variant["baseline"]), "top_k": top_k,
        "scores": {variant: {
            "all": _aggregate(rows, fields),
            "by_category": {cat: _aggregate([row for row in rows if row["category"] == cat], fields)
                            for cat in categories},
        } for variant, rows in by_variant.items()},
        "changes": _changes(by_variant, "evidence_all"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--longmemeval", type=Path, required=True, help="Local official LongMemEval JSON")
    parser.add_argument("--limit", type=int, default=500)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--locomo", type=Path, help="Local official LoCoMo JSON")
    source.add_argument("--download-locomo", action="store_true", help="Fetch pinned official LoCoMo JSON")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--locomo-questions-per-conversation", type=int, default=0,
                        help="0 means all questions (default); positive value caps each conversation")
    parser.add_argument("--locomo-max-conversations", type=int, default=0,
                        help="0 means all ten conversations (default); positive value caps the pilot")
    args = parser.parse_args()
    if not 1 <= args.top_k <= 50:
        parser.error("--top-k must be 1..50")
    started = time.perf_counter()
    lme = run_longmemeval(args.longmemeval, limit=args.limit, top_k=args.top_k)
    locomo_raw = lo.download_official() if args.download_locomo else args.locomo.read_bytes()
    locomo = run_locomo(locomo_raw, top_k=args.top_k,
                        max_conversations=args.locomo_max_conversations or None,
                        questions_per_conversation=args.locomo_questions_per_conversation or None)
    print(json.dumps({"elapsed_seconds": round(time.perf_counter() - started, 2),
                      "longmemeval": lme, "locomo": locomo}, ensure_ascii=False, indent=2))
