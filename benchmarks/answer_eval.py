"""Optional end-to-end answer check over the isolated synthetic retrieval fixture.

Supply an OpenRouter chat model explicitly. This script sends only synthetic
fixture questions and retrieved synthetic claims, never active user memory.
Regex checks are transparent smoke tests, not a replacement for human judging.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

from quality_eval import DEFAULT_FIXTURE, _percentile, run as run_retrieval


def _api_key(env_file: Path | None) -> str:
    if env_file is None:
        import os
        return os.environ.get("OPENROUTER_API_KEY", "")
    try:
        from dotenv import dotenv_values
    except ImportError as exc:
        raise RuntimeError("--env-file requires python-dotenv") from exc
    return str(dotenv_values(env_file).get("OPENROUTER_API_KEY") or "")


def _answer(model: str, api_key: str, context: list[str], question: str) -> tuple[str, dict, float]:
    prompt = (
        "Use only the supplied memory facts. When facts conflict, distinguish current or verified facts "
        "from unverified notes and explain which is better supported. Do not claim a fact is verified "
        "unless the supplied fact explicitly says so. "
        "If the facts do not answer the question, say UNKNOWN. Keep the answer short.\n\n"
        + "\n".join(f"[{index + 1}] {fact}" for index, fact in enumerate(context))
        + "\n\nQuestion: " + question
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Answer questions using only the supplied synthetic memory."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 160,
    }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenRouter answer request returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"OpenRouter answer request failed: {type(exc).__name__}") from None
    elapsed = (time.perf_counter() - started) * 1000
    choices = result.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise RuntimeError("OpenRouter returned no answer choice")
    answer = str((choices[0].get("message") or {}).get("content") or "")
    if not answer:
        raise RuntimeError("OpenRouter returned an empty answer")
    usage = result.get("usage") or {}
    return answer, {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
    }, elapsed


def _score_answer(case: dict, answer: str) -> bool:
    return all(re.search(pattern, answer) for pattern in case.get("answer_must_match", [])) and not any(
        re.search(pattern, answer) for pattern in case.get("answer_must_not_match", [])
    )


def run(fixture_path: Path, *, model: str, env_file: Path | None = None,
        semantic: bool = False, mode: str = "hybrid") -> dict:
    if not model.strip():
        raise ValueError("an OpenRouter answer model is required")
    key = _api_key(env_file)
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is missing")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    retrieval = run_retrieval(fixture_path, semantic=semantic, env_file=env_file)
    score = next((part for part in retrieval["scores"] if part["mode"] == mode), None)
    if score is None:
        raise ValueError(f"retrieval mode not available: {mode}")
    scored_by_name = {case["name"]: case for case in score["cases"]}
    claims = {item["id"]: item["claim"] for item in fixture["claims"]}
    results = []
    for case in fixture["cases"]:
        top_ids = scored_by_name[case["name"]]["top_5"]
        context = [claims[claim_id] for claim_id in top_ids]
        answer, usage, latency = _answer(model, key, context, case["query"])
        results.append({
            "name": case["name"], "category": case["category"],
            "passed": bool(_score_answer(case, answer)),
            "answer": answer, "retrieved_ids": top_ids,
            "latency_ms": round(latency, 2), **usage,
        })
    durations = [item["latency_ms"] for item in results]
    return {
        "model": model, "fixture_version": fixture["version"],
        "semantic": semantic, "retrieval_mode": mode,
        "retrieval_recall_at_5": score["recall_at_5"],
        "retrieval_scope_leaks": score["scope_leaks"],
        "answer_accuracy": round(sum(item["passed"] for item in results) / len(results), 3),
        "answer_p50_ms": round(statistics.median(durations), 2),
        "answer_p95_ms": round(_percentile(durations, 0.95), 2),
        "prompt_tokens": sum(item["prompt_tokens"] for item in results),
        "completion_tokens": sum(item["completion_tokens"] for item in results),
        "cases": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--model", required=True, help="Explicit OpenRouter chat model ID")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--mode", choices=("fts", "hybrid"), default="hybrid")
    args = parser.parse_args()
    print(json.dumps(run(args.fixture, model=args.model, env_file=args.env_file,
                         semantic=args.semantic, mode=args.mode), ensure_ascii=False, indent=2))
