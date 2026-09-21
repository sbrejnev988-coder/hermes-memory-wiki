"""Full paired LongMemEval evidence-retrieval probe against production episodes.

Runs the actual claim ingestion, episode capture, and model-facing episode tool
in one fresh temporary database per question. By default it is entirely
offline. The optional bounded reader answers from the very same retrieved
claims and episode excerpts; it never supplies gold answers to the model.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    from . import episodic_fallback_probe as prototype
except ImportError:
    import episodic_fallback_probe as prototype

qa_reader = prototype.official.qa_reader
AnswerBudget = qa_reader.AnswerBudget


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return round(sorted(values)[max(0, min(len(values) - 1, int(len(values) * fraction) - 1))], 2)


@contextmanager
def _feature_env(strict_guard: bool):
    updates = {"MEMORY_WIKI_EPISODIC_ENABLED": "1", "MEMORY_WIKI_EPISODIC_SCOPE": "bot"}
    if strict_guard:
        updates["HERMES_SECURITY_STRICT"] = "1"
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _score(provider: Any, module: Any, case: dict[str, Any], top_k: int,
           episode_slots: int, *, context_out: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    gold: set[tuple[str, int]] = set()
    claim_sources: dict[str, set[tuple[str, int]]] = defaultdict(set)
    episode_sources: dict[str, tuple[str, int]] = {}
    turns = accepted = queued = ingest_errors = 0
    secret_rejects = write_guard_rejects = read_guard_rejects = 0
    current: tuple[str, int] | None = None
    original_add = provider._add_claim
    original_inspect = provider._inspect_recall_text
    original_capture = module._episodic_memory.capture_turn

    def trace_add(*args: Any, **kwargs: Any) -> Any:
        nonlocal accepted, queued
        result = original_add(*args, **kwargs)
        if current is not None and isinstance(result, str):
            if result.startswith("c_"):
                claim_sources[result].add(current)
                accepted += 1
            elif result.startswith("rq_"):
                queued += 1
        return result

    def trace_guard(text: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal write_guard_rejects, read_guard_rejects
        result = original_inspect(text, **kwargs)
        if result.get("status") != "safe":
            source = kwargs.get("source", "")
            if source == "host:sync_turn":
                write_guard_rejects += 1
            elif source == "episodic:untrusted":
                read_guard_rejects += 1
        return result

    def trace_capture(capture_provider: Any, capture_module: Any, role: str,
                      content: str, *, session_id: str = "", turn_id: str = "") -> str | None:
        result = original_capture(capture_provider, capture_module, role, content,
                                  session_id=session_id, turn_id=turn_id)
        if result and current is not None:
            episode_sources[result] = current
        return result

    provider._add_claim = trace_add
    provider._inspect_recall_text = trace_guard
    module._episodic_memory.capture_turn = trace_capture
    try:
        for session_id, index, turn, _ in prototype.official.chronological_turns(case):
            turns += 1
            current = (session_id, index)
            if turn.get("has_answer") is True:
                gold.add(current)
            role = str(turn["role"])
            content = turn["content"]
            if module.secret_scan(module.scrub_memory_artifacts(content)).get("raw_secret"):
                secret_rejects += 1
            try:
                provider.sync_turn(content if role == "user" else "",
                                   content if role == "assistant" else "",
                                   session_id=session_id)
            except Exception:
                ingest_errors += 1
            finally:
                current = None
    finally:
        provider._add_claim = original_add
        module._episodic_memory.capture_turn = original_capture
    claim_start = time.perf_counter()
    rows = provider._search(case["question"], limit=top_k, retrieval_mode="fts",
                            record_retrieval=False, apply_rerank=False)
    claim_ms = (time.perf_counter() - claim_start) * 1000
    tool_start = time.perf_counter()
    response = json.loads(provider.handle_tool_call(
        "memory_wiki_query_episodes", {"query": case["question"], "limit": episode_slots},
    ))
    episode_ms = (time.perf_counter() - tool_start) * 1000
    if not response.get("success") or not response.get("enabled"):
        raise RuntimeError(f"episode tool unavailable for {case['question_id']}")
    episode_rows = response.get("episodes", [])
    episode_char_budget = module._episodic_memory._bounded_env(
        "MEMORY_WIKI_EPISODIC_QUERY_MAX_CHARS", 2400, 350, 12000,
    )
    if (len(episode_rows) > episode_slots
            or sum(len(r.get("content", "")) for r in episode_rows) > episode_char_budget):
        raise AssertionError("production episode tool exceeded retrieval budget")
    for row in episode_rows:
        if row.get("trust_level") != "untrusted":
            raise AssertionError("episode lost its untrusted label")
    if context_out is not None:
        context_out.extend(
            ("claim:" + str(row["id"]), str(row["claim"]))
            for row in rows[:top_k - episode_slots]
        )
        context_out.extend(
            ("episode:" + str(row["id"]), str(row["content"]))
            for row in episode_rows
        )
    claim_turns = [claim_sources.get(str(row["id"]), set()) for row in rows]
    baseline = set().union(*claim_turns) if claim_turns else set()
    fixed_claims = set().union(*claim_turns[:top_k - episode_slots]) if claim_turns else set()
    episode_turns = {episode_sources[r["id"]] for r in episode_rows if r["id"] in episode_sources}
    fixed = fixed_claims | episode_turns
    supplement = baseline | episode_turns
    all_claim_turns = set().union(*claim_sources.values()) if claim_sources else set()
    return {
        "question_id": case["question_id"], "category": case["question_type"],
        "turns": turns, "gold_turns": len(gold),
        "gold_capture": len(gold & set(episode_sources.values())),
        "gold_claim_capture": len(gold & all_claim_turns),
        "episode_capture": len(episode_sources), "capture_rejects": turns - len(episode_sources),
        "secret_rejects": secret_rejects, "write_guard_rejects": write_guard_rejects,
        "read_guard_rejects": read_guard_rejects, "ingest_errors": ingest_errors,
        "accepted_claim_writes": accepted, "queued_claim_writes": queued,
        "baseline_hits": len(gold & baseline), "fixed_hits": len(gold & fixed),
        "supplement_hits": len(gold & supplement),
        "baseline_any": bool(gold & baseline), "fixed_any": bool(gold & fixed),
        "supplement_any": bool(gold & supplement),
        "baseline_all": gold <= baseline, "fixed_all": gold <= fixed,
        "supplement_all": gold <= supplement,
        "episodes_returned": len(episode_rows),
        "assistant_excerpts": sum(r["role"] == "assistant" for r in episode_rows),
        "prompt_chars": sum(len(r["content"]) for r in episode_rows),
        "claim_ms": round(claim_ms, 2), "episode_tool_ms": round(episode_ms, 2),
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"questions": 0, "evidence_scored_questions": 0}
    scored = [r for r in rows if r["gold_turns"]]
    n = len(scored)
    gold = sum(r["gold_turns"] for r in scored)
    counts = ("turns", "gold_turns", "gold_capture", "gold_claim_capture",
              "episode_capture", "capture_rejects", "secret_rejects",
              "write_guard_rejects", "read_guard_rejects", "ingest_errors",
              "accepted_claim_writes", "queued_claim_writes", "baseline_hits",
              "fixed_hits", "supplement_hits", "episodes_returned",
              "assistant_excerpts", "prompt_chars")
    out: dict[str, Any] = {"questions": len(rows), "evidence_scored_questions": n}
    out.update({key: sum(r[key] for r in rows) for key in counts})
    for key in ("baseline_any", "fixed_any", "supplement_any",
                "baseline_all", "fixed_all", "supplement_all"):
        out[key] = round(sum(bool(r[key]) for r in scored) / n, 4) if n else None
    for key in ("baseline_hits", "fixed_hits", "supplement_hits"):
        out[key + "_per_gold"] = round(out[key] / gold, 4) if gold else None
    for key in ("claim_ms", "episode_tool_ms"):
        values = [r[key] for r in rows]
        out[key + "_p50"] = _percentile(values, .5)
        out[key + "_p95"] = _percentile(values, .95)
    return out


def run(dataset: Path, *, top_k: int = 5, episode_slots: int = 2,
        limit: int = 500, progress_every: int = 25, answer_model: str = "",
        env_file: Path | None = None, answer_max_tokens: int = 160,
        answer_context_chars: int = 6000, answer_request_budget: int | None = None,
        answer_cost_soft_cap_usd: float | None = None) -> dict[str, Any]:
    if not 1 <= episode_slots < top_k <= 50:
        raise ValueError("invalid fixed retrieval budget")
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    if answer_model and not (1 <= answer_max_tokens <= 256 and 256 <= answer_context_chars <= 10000):
        raise ValueError("answer limits must be 1-256 tokens and 256-10000 context characters")
    if not answer_model and (env_file is not None or answer_request_budget is not None or answer_cost_soft_cap_usd is not None):
        raise ValueError("reader options require --answer-model")
    env_values = prototype.official._env_file_values(env_file) if answer_model else {}
    api_key = env_values.get("OPENROUTER_API_KEY") or env_values.get("MEMORY_WIKI_EMBED_API_KEY") or ""
    if answer_model and (env_file is None or not api_key):
        raise ValueError("--answer-model requires --env-file with an OpenRouter API key")
    budget = AnswerBudget(limit if answer_request_budget is None else answer_request_budget,
                          answer_cost_soft_cap_usd) if answer_model else None
    try:
        from . import benchmark_provenance
    except ImportError:
        import benchmark_provenance
    # Both offline evidence and optional answer runs must attest to the code
    # that actually produced the result, rather than hashing it hours later.
    source_hash_before = benchmark_provenance._source_hashes(prototype.ROOT)
    sha = hashlib.sha256(dataset.read_bytes()).hexdigest()
    cases, total = prototype.official.load_cases(dataset, 500)
    cases = cases[:limit]
    guard_available = importlib.util.find_spec("hermes_trust_core") is not None
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="memory-wiki-full-episode-") as temp:
        with prototype._isolated_home(temp):
            with _feature_env(guard_available):
                module = prototype._load_plugin()
                try:
                    for index, case in enumerate(cases):
                        provider = module.MemoryWikiProvider()
                        try:
                            provider.initialize(
                                f"benchmark-chat-{index}", hermes_home=str(Path(temp) / f"case-{index}"),
                                bot_id=f"benchmark-bot-{index}", project_id=f"case-{index}",
                            )
                            context: list[tuple[str, str]] = []
                            row = _score(provider, module, case, top_k, episode_slots,
                                         context_out=context if answer_model else None)
                            if answer_model:
                                assert budget is not None
                                reason = budget.skip_reason()
                                if reason:
                                    row["answer_skipped_reason"] = reason
                                elif any(module.secret_scan(value).get("raw_secret") for _, value in context):
                                    row["answer_skipped_reason"] = "secret_guard"
                                elif module.secret_scan(str(case["question"])).get("raw_secret"):
                                    row["answer_skipped_reason"] = "secret_guard"
                                else:
                                    budget.begin()
                                    try:
                                        answer, usage, answer_ms = qa_reader.answer_openrouter(
                                            api_key=api_key, model=answer_model,
                                            question=case["question"], context=context,
                                            question_date=str(case.get("question_date") or ""),
                                            max_tokens=answer_max_tokens,
                                            context_chars=answer_context_chars,
                                        )
                                    except Exception as exc:
                                        row["answer_error"] = type(exc).__name__
                                        budget.unknown_cost = True
                                    else:
                                        row["hypothesis"] = answer
                                        row["answer_usage"] = usage
                                        row["answer_ms"] = answer_ms
                                        row["answer_abstention_heuristic"] = qa_reader.looks_like_abstention(answer)
                                        expected = case.get("answer")
                                        if expected is not None:
                                            answers = expected if isinstance(expected, list) else [expected]
                                            row["answer_proxy_exact_match"] = any(
                                                prototype.official._normalized_answer(answer)
                                                == prototype.official._normalized_answer(value)
                                                for value in answers
                                            )
                                        budget.record(usage)
                            rows.append(row)
                        finally:
                            if provider._conn is not None:
                                provider._conn.close()
                                provider._conn = None
                        if progress_every and (index + 1) % progress_every == 0:
                            print(f"scored {index + 1}/{len(cases)}", file=sys.stderr, flush=True)
                finally:
                    sys.modules.pop(module.__name__, None)
    categories = sorted({r["category"] for r in rows})
    source_hash_after = benchmark_provenance._source_hashes(prototype.ROOT)
    if source_hash_before != source_hash_after:
        raise RuntimeError("benchmark source changed during evaluation")
    if hashlib.sha256(dataset.read_bytes()).hexdigest() != sha:
        raise RuntimeError("benchmark dataset changed during evaluation")
    result = {
        "dataset_sha256": sha,
        "source_tree_sha256": benchmark_provenance._tree_sha256(source_hash_before),
        "official_oracle_sha256_match": sha == prototype.OFFICIAL_ORACLE_SHA256,
        "dataset_questions": total, "evaluated_questions": len(rows),
        "evidence_scored_questions": sum(bool(r["gold_turns"]) for r in rows),
        "comparison": (
            f"{top_k} FTS claims versus {top_k - episode_slots} FTS claims plus "
            f"{episode_slots} production query_episodes excerpts"
        ),
        "episode_scope": "explicit bot; one isolated bot and database per question",
        "guard_mode": "strict shared guard" if guard_available else "non-strict local guard; shared core unavailable",
        "retrieval_mode": "offline FTS; no OpenRouter/Qdrant or answer generation",
        "effective_config": {
            "top_k": top_k,
            "episode_slots": episode_slots,
            "episode_query_max_results": int(os.environ.get(
                "MEMORY_WIKI_EPISODIC_QUERY_MAX_RESULTS", "8"
            )),
            "episode_query_max_chars": int(os.environ.get(
                "MEMORY_WIKI_EPISODIC_QUERY_MAX_CHARS", "2400"
            )),
            "episode_query_mode": os.environ.get("MEMORY_WIKI_EPISODIC_QUERY_MODE", "auto"),
        },
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "overall": _aggregate(rows),
        "by_category": {name: _aggregate([r for r in rows if r["category"] == name]) for name in categories},
        "cases": rows,
    }
    if answer_model:
        assert budget is not None
        generated = [row for row in rows if "hypothesis" in row]
        proxy_rows = [row for row in generated if "answer_proxy_exact_match" in row]
        times = [row["answer_ms"] for row in generated]
        result["answer_evaluation"] = {
            "label": "unjudged exploratory answers; not official LongMemEval QA accuracy",
            "model": answer_model,
            "reader_prompt_version": 1,
            "max_completion_tokens_per_request": answer_max_tokens,
            "max_evidence_chars_per_request": answer_context_chars,
            "requests": budget.summary(),
            "generated": len(generated),
            "errors": sum("answer_error" in row for row in rows),
            "skipped": sum("answer_skipped_reason" in row for row in rows),
            "normalized_exact_match_proxy": (
                round(sum(row["answer_proxy_exact_match"] for row in proxy_rows) / len(proxy_rows), 4)
                if proxy_rows else None
            ),
            "proxy_coverage": len(proxy_rows),
            "abstention_heuristic_count": sum(row["answer_abstention_heuristic"] for row in generated),
            "answer_ms_p50": _percentile(times, .5),
            "answer_ms_p95": _percentile(times, .95),
            "source_tree_sha256": benchmark_provenance._tree_sha256(source_hash_before),
            "limitations": [
                "The normalized exact-match proxy is not the official model-judged score.",
                "The request count is a hard cap; the reported-cost cap is soft and may overshoot by one request.",
                "Unknown usage, failed requests, and omitted provider usage prevent exact total cost accounting.",
                "Retrieval uses offline FTS claims and local episode FTS; no Qdrant or embedding calls are made.",
            ],
        }
        result["retrieval_mode"] = "offline FTS; bounded OpenRouter answer generation; no Qdrant"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--episode-slots", type=int, default=2)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--answer-model", default="", help="Optional bounded OpenRouter reader model")
    parser.add_argument("--env-file", type=Path, help="Private dotenv file; required with --answer-model")
    parser.add_argument("--answer-max-tokens", type=int, default=160)
    parser.add_argument("--answer-context-chars", type=int, default=6000)
    parser.add_argument("--answer-request-budget", type=int, help="Hard maximum reader requests")
    parser.add_argument("--answer-cost-soft-cap-usd", type=float, help="Soft cap on reported reader cost")
    parser.add_argument("--output", type=Path, help="Write result JSON to this file")
    parser.add_argument("--hypotheses-out", type=Path, help="Write official question_id/hypothesis JSONL")
    args = parser.parse_args()
    if args.answer_model and (not args.output or not args.hypotheses_out):
        parser.error("--answer-model requires --output and --hypotheses-out")
    output_paths = [path for path in (args.output, args.hypotheses_out) if path is not None]
    inputs = [path for path in (args.dataset, args.env_file) if path is not None]
    if len({path.resolve() for path in output_paths}) != len(output_paths) or any(
        output.resolve() == source.resolve() for output in output_paths for source in inputs
    ):
        parser.error("result paths must be distinct from each other and all inputs")
    result = run(args.dataset, top_k=args.top_k, episode_slots=args.episode_slots,
                 limit=args.limit, progress_every=args.progress_every,
                 answer_model=args.answer_model, env_file=args.env_file,
                 answer_max_tokens=args.answer_max_tokens,
                 answer_context_chars=args.answer_context_chars,
                 answer_request_budget=args.answer_request_budget,
                 answer_cost_soft_cap_usd=args.answer_cost_soft_cap_usd)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.hypotheses_out:
        lines = [json.dumps({"question_id": row["question_id"], "hypothesis": row["hypothesis"]},
                            ensure_ascii=False) for row in result["cases"] if "hypothesis" in row]
        args.hypotheses_out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(rendered if not args.answer_model else json.dumps({
        "evaluated_questions": result["evaluated_questions"],
        "answer_evaluation": result["answer_evaluation"],
    }, ensure_ascii=False, indent=2))
