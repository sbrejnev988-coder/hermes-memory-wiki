"""Offline LongMemEval write-policy probe without memory/database mutations.

Compares the oracle adapter's whole-turn claim gate with the production
``_ingest_text`` and session-end extraction paths. These are observed through a dry-run
``_add_claim`` hook, so counts describe candidate decisions rather than actual
durable writes. Only provenance IDs and candidate digests are emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from . import longmemeval_adapter as adapter
except ImportError:
    import longmemeval_adapter as adapter


def _key(gold: bool, role: str, action: str) -> str:
    return f"{'gold' if gold else 'nongold'}:{role}:{action}"


def probe(dataset: Path, *, limit: int = 500, include_turns: bool = False) -> dict[str, Any]:
    cases, total = adapter.load_cases(dataset, limit)
    raw_counts: Counter[str] = Counter()
    production_counts: Counter[str] = Counter()
    session_end_counts: Counter[str] = Counter()
    candidate_counts: Counter[str] = Counter()
    mapping_counts: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    production_by_turn: dict[tuple[str, str, int], str] = {}
    detail_by_turn: dict[tuple[str, str, int], dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="memory-wiki-lme-ingestion-probe-") as home:
        cache = Path(home) / "cache" / "documents"
        overrides = {
            "MEMORY_WIKI_DOCUMENT_CACHE_DIR": str(cache),
            "MEMORY_WIKI_DOCUMENT_ROOTS": str(cache),
            "MW_EXTRACTION_ENABLED": "0",
        }
        with adapter._isolated_environment(home, overrides):
            module = adapter._load_plugin()
            provider = module.MemoryWikiProvider()
            candidates: list[dict[str, str]] = []
            candidate_texts: list[tuple[str, str, str]] = []

            def dry_run_add(claim: str, topic: str = "general", evidence: str = "",
                            source: str = "tool", **kwargs: Any) -> str:
                # A real write quarantines raw secret-bearing claim/evidence;
                # the probe records this without touching the secret store.
                if module.secret_scan(str(claim) + " " + str(evidence)).get("raw_secret"):
                    action, reason = "secret_quarantine", "raw secret-like material"
                else:
                    gate = module.memory_gate_decision(claim, topic, source)
                    action, reason = str(gate["action"]), str(gate["reason"])
                fingerprint = hashlib.sha256(str(claim).encode("utf-8")).hexdigest()[:16]
                candidates.append({"digest": fingerprint, "action": action, "reason": reason})
                candidate_texts.append((str(claim), action, fingerprint))
                return "c_probe" if action == "accept" else "rq_probe"

            provider._add_claim = dry_run_add
            try:
                for case in cases:
                    for session_id, turn_index, turn, _ in adapter.chronological_turns(case):
                        role = str(turn["role"])
                        gold = turn.get("has_answer") is True
                        raw_text = str(turn["content"] or "").strip()
                        if raw_text:
                            cleaned = module.normalize_claim(module.scrub_memory_artifacts(raw_text))
                            if module.secret_scan(raw_text).get("raw_secret"):
                                raw_action = "secret_quarantine"
                            else:
                                raw_action = str(module.memory_gate_decision(
                                    cleaned, "longmemeval", f"benchmark:longmemeval:{role}",
                                )["action"])
                        else:
                            raw_action = "empty"
                        raw_counts[_key(gold, role, raw_action)] += 1

                        candidates = []
                        if role in {"user", "assistant"}:
                            provider._ingest_text(
                                raw_text, source=f"turn:{role}:{session_id}",
                                max_claims=8 if role == "user" else 2,
                            )
                        if not candidates:
                            production_action = "no_candidate"
                        elif any(item["action"] == "accept" for item in candidates):
                            production_action = "accepted"
                        elif any(item["action"] == "secret_quarantine" for item in candidates):
                            production_action = "secret_quarantine"
                        elif any(item["action"] == "queue" for item in candidates):
                            production_action = "queued"
                        else:
                            production_action = "rejected"
                        production_counts[_key(gold, role, production_action)] += 1
                        candidate_counts[_key(gold, role, "calls")] += len(candidates)
                        identity = (case["question_id"], session_id, turn_index)
                        production_by_turn[identity] = production_action
                        if include_turns:
                            record = {
                                "question_id": case["question_id"],
                                "turn_id": f"{session_id}:{turn_index}",
                                "role": role, "gold": gold,
                                "raw_action": raw_action,
                                "production_action": production_action,
                                "candidates": list(candidates),
                                "session_end_candidates": [],
                            }
                            details.append(record)
                            detail_by_turn[identity] = record
                for case in cases:
                    for session_id, turns in zip(case["haystack_session_ids"],
                                                 case["haystack_sessions"]):
                        indexed_turns = list(enumerate(turns))
                        messages = [{"role": turn["role"], "content": turn["content"]}
                                    for _, turn in indexed_turns]
                        mapped: dict[int, list[str]] = {index: [] for index, _ in indexed_turns}

                        def map_candidates(path: str,
                                           eligible: list[tuple[int, dict[str, Any]]]) -> None:
                            candidate_counts[path] += len(candidate_texts)
                            for claim, action, digest in candidate_texts:
                                needle = module.normalize_claim(claim).casefold()
                                matches = [index for index, turn in eligible
                                           if needle and needle in module.normalize_claim(
                                               turn["content"]).casefold()]
                                if len(matches) != 1:
                                    mapping_counts[f"{path}:{'unmapped' if not matches else 'ambiguous'}"] += 1
                                    continue
                                turn_index = matches[0]
                                mapped[turn_index].append(action)
                                mapping_counts[f"{path}:mapped"] += 1
                                identity = (case["question_id"], session_id, turn_index)
                                if include_turns:
                                    detail_by_turn[identity]["session_end_candidates"].append({
                                        "digest": digest, "action": action, "path": path,
                                    })

                        session_text = "\n".join(
                            str(message.get("content", ""))[:4000]
                            for message in messages[-24:]
                        )
                        candidates = []; candidate_texts = []
                        provider._ingest_text(session_text, source=f"session_end:{session_id}",
                                              max_claims=14)
                        map_candidates("session_end_sentences", indexed_turns[-24:])

                        candidates = []; candidate_texts = []
                        module.extract_session_claims(
                            messages[-32:], session_id=session_id,
                            add_claim_callback=dry_run_add,
                        )
                        map_candidates("session_end_heuristic", [
                            (index, turn) for index, turn in indexed_turns[-32:]
                            if turn["role"] == "user"
                        ])

                        for turn_index, turn in indexed_turns:
                            identity = (case["question_id"], session_id, turn_index)
                            actions = [production_by_turn[identity], *mapped[turn_index]]
                            if "accepted" in actions or "accept" in actions:
                                final_action = "accepted"
                            elif "secret_quarantine" in actions:
                                final_action = "secret_quarantine"
                            elif "queued" in actions or "queue" in actions:
                                final_action = "queued"
                            elif "rejected" in actions or "reject" in actions:
                                final_action = "rejected"
                            else:
                                final_action = "no_candidate"
                            session_end_counts[_key(turn.get("has_answer") is True,
                                                    str(turn["role"]), final_action)] += 1
                            if include_turns:
                                detail_by_turn[identity]["with_session_end_action"] = final_action
            finally:
                # No initialize() or _connect() call is made by the probe.
                adapter.sys.modules.pop(module.__name__, None)
    result: dict[str, Any] = {
        "dataset_questions": total,
        "evaluated_questions": len(cases),
        "raw_whole_turn": dict(sorted(raw_counts.items())),
        "production_extraction": dict(sorted(production_counts.items())),
        "production_with_session_end": dict(sorted(session_end_counts.items())),
        "production_candidate_calls": dict(sorted(candidate_counts.items())),
        "session_end_mapping": dict(sorted(mapping_counts.items())),
        "method": "dry-run quality decisions; no durable writes, Qdrant, OpenRouter, or user profile",
    }
    if include_turns:
        result["turns"] = details
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--output", type=Path, help="Write aggregate and per-turn provenance/digests as JSON")
    args = parser.parse_args()
    result = probe(args.dataset, limit=args.limit, include_turns=bool(args.output))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result = {key: value for key, value in result.items() if key != "turns"}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
