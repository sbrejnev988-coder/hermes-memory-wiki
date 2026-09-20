"""Bounded LoCoMo dialogue-evidence probe with production host episode capture.

This uses one isolated bot and the actual sync_turn/query_episodes path. It
compares five automatically extracted claims to three claims plus two episode
excerpts. It measures evidence retrieval, never answer quality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from . import episodic_fallback_probe as prototype
    from . import full_oracle_episode_probe as full
    from . import locomo_adapter as official
except ImportError:
    import episodic_fallback_probe as prototype
    import full_oracle_episode_probe as full
    import locomo_adapter as official


def run(dataset: Path, *, conversations: int = 1, questions_per_conversation: int = 50) -> dict[str, Any]:
    if not 1 <= conversations <= 10 or not 1 <= questions_per_conversation <= 1000:
        raise ValueError("invalid bounded LoCoMo sample")
    raw = dataset.read_bytes()
    samples = official._load_dataset(raw)[:conversations]
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="memory-wiki-locomo-episodes-") as temp:
        with prototype._isolated_home(temp):
            with full._feature_env(False):
                module = prototype._load_plugin()
                try:
                    for sample_index, sample in enumerate(samples):
                        provider = module.MemoryWikiProvider()
                        provider.initialize(f"locomo-episode-chat-{sample_index}",
                                            hermes_home=str(Path(temp) / f"sample-{sample_index}"),
                                            bot_id=f"locomo-episode-bot-{sample_index}")
                        claim_sources: dict[str, set[str]] = defaultdict(set)
                        episode_sources: dict[str, str] = {}
                        current = ""
                        original_add = provider._add_claim
                        original_capture = module._episodic_memory.capture_turn

                        def trace_add(*args: Any, **kwargs: Any) -> Any:
                            result = original_add(*args, **kwargs)
                            if current and isinstance(result, str) and result.startswith("c_"):
                                claim_sources[result].add(current)
                            return result

                        def trace_capture(capture_provider: Any, capture_module: Any, role: str,
                                          text: str, **kwargs: Any) -> str | None:
                            result = original_capture(capture_provider, capture_module, role, text, **kwargs)
                            if current and result:
                                episode_sources[result] = current
                            return result

                        provider._add_claim = trace_add
                        module._episodic_memory.capture_turn = trace_capture
                        ingest_errors = 0
                        indexed = 0
                        try:
                            for dia_id, session_id, text, _ in official._turns(sample):
                                current = dia_id
                                indexed += 1
                                try:
                                    # LoCoMo is a two-person conversation. Both
                                    # utterances enter the host user channel.
                                    provider.sync_turn(text, "", session_id=session_id)
                                except Exception:
                                    ingest_errors += 1
                                finally:
                                    current = ""
                        finally:
                            provider._add_claim = original_add
                            module._episodic_memory.capture_turn = original_capture
                        for question in sample["qa"][:questions_per_conversation]:
                            gold, malformed = official._evidence_ids(question["evidence"])
                            claim_start = time.perf_counter()
                            claim_rows = provider._search(question["question"], limit=5,
                                                          retrieval_mode="fts", record_retrieval=False,
                                                          apply_rerank=False)
                            claim_ms = (time.perf_counter() - claim_start) * 1000
                            episode_start = time.perf_counter()
                            tool = json.loads(provider.handle_tool_call(
                                "memory_wiki_query_episodes",
                                {"query": question["question"], "limit": 2},
                            ))
                            episode_ms = (time.perf_counter() - episode_start) * 1000
                            if not tool.get("success") or not tool.get("enabled"):
                                raise RuntimeError("production episode tool disabled")
                            ep_rows = tool["episodes"]
                            claims = [claim_sources.get(str(row["id"]), set()) for row in claim_rows]
                            baseline = set().union(*claims) if claims else set()
                            fixed_claims = set().union(*claims[:3]) if claims else set()
                            episodes = {episode_sources[row["id"]] for row in ep_rows if row["id"] in episode_sources}
                            fixed = fixed_claims | episodes
                            results.append({
                                "sample_id": sample["sample_id"], "category": question.get("category"),
                                "gold": len(gold), "malformed": len(malformed),
                                "gold_capture": len(gold & set(episode_sources.values())),
                                "baseline_hits": len(gold & baseline), "fixed_hits": len(gold & fixed),
                                "baseline_any": bool(gold & baseline) if gold else None,
                                "fixed_any": bool(gold & fixed) if gold else None,
                                "baseline_all": gold <= baseline if gold else None,
                                "fixed_all": gold <= fixed if gold else None,
                                "episode_count": len(ep_rows),
                                "prompt_chars": sum(len(row["content"]) for row in ep_rows),
                                "claim_ms": round(claim_ms, 2), "episode_tool_ms": round(episode_ms, 2),
                                "indexed_turns": indexed, "captured_turns": len(episode_sources),
                                "ingest_errors": ingest_errors,
                            })
                        if provider._conn is not None:
                            provider._conn.close()
                            provider._conn = None
                finally:
                    sys.modules.pop(module.__name__, None)

    def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        scored = [row for row in rows if row["gold"]]
        gold = sum(row["gold"] for row in scored)
        return {
            "questions": len(rows), "scored_questions": len(scored),
            "gold_turns": gold, "gold_capture": sum(row["gold_capture"] for row in scored),
            "baseline_any": round(statistics.mean(row["baseline_any"] for row in scored), 4) if scored else None,
            "fixed_any": round(statistics.mean(row["fixed_any"] for row in scored), 4) if scored else None,
            "baseline_all": round(statistics.mean(row["baseline_all"] for row in scored), 4) if scored else None,
            "fixed_all": round(statistics.mean(row["fixed_all"] for row in scored), 4) if scored else None,
            "baseline_hits_per_gold": round(sum(row["baseline_hits"] for row in scored) / gold, 4) if gold else None,
            "fixed_hits_per_gold": round(sum(row["fixed_hits"] for row in scored) / gold, 4) if gold else None,
            "episode_tool_ms_p50": full._percentile([r["episode_tool_ms"] for r in rows], .5),
            "episode_tool_ms_p95": full._percentile([r["episode_tool_ms"] for r in rows], .95),
            "prompt_chars": sum(row["prompt_chars"] for row in rows),
        }

    categories = sorted({str(row["category"]) for row in results})
    return {
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "official_dataset_sha256_match": hashlib.sha256(raw).hexdigest() == official.OFFICIAL_SHA256,
        "sample_conversations": len(samples), "sample_questions": len(results),
        "comparison": "five auto-ingested FTS claims vs three claims plus two guarded production episodes",
        "role_mapping": "both LoCoMo human speakers enter sync_turn's user channel",
        "guard_mode": "non-strict local guard; shared core unavailable",
        "retrieval_only": True,
        "overall": aggregate(results),
        "by_category": {name: aggregate([r for r in results if str(r["category"]) == name])
                        for name in categories},
        "cases": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--conversations", type=int, default=1)
    parser.add_argument("--questions-per-conversation", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(run(args.dataset, conversations=args.conversations,
                         questions_per_conversation=args.questions_per_conversation),
                     ensure_ascii=False, indent=2))
