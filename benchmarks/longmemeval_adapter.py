"""Offline, isolated LongMemEval retrieval adapter for Memory Wiki.

Reads a user-supplied official LongMemEval JSON file. It never downloads data
or loads the active Hermes profile. The default FTS baseline is offline;
``--semantic --env-file`` explicitly enables OpenRouter and isolated physical
Qdrant collections. Neither mode is the official answer-generation evaluation.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
_ISOLATED_ENV = {
    "HERMES_SECURITY_STRICT": "0",
    "MEMORY_WIKI_SEMANTIC": "0",
    "MEMORY_WIKI_RERANK_ENABLED": "0",
    "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE": "0",
}
_SERVICE_ENV_KEYS = (
    "OPENROUTER_API_KEY", "NOUS_API_KEY", "MEMORY_WIKI_EMBED_API_KEY",
    "MEMORY_WIKI_EMBED_PROVIDER", "MEMORY_WIKI_EMBED_MODEL", "MEMORY_WIKI_EMBED_URL",
    "MEMORY_WIKI_EMBED_DIMENSIONS", "MEMORY_WIKI_EMBED_INPUT_MAX_CHARS", "MEMORY_WIKI_VECTOR_SIZE",
    "MEMORY_WIKI_QDRANT_URL", "MEMORY_WIKI_QDRANT_API_KEY",
    "MEMORY_WIKI_QUERY_INSTRUCTION", "MEMORY_WIKI_DOCUMENT_PREFIX",
)


def _official_date(value: str) -> int:
    """Return a deterministic UTC ordering key for official session dates."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid LongMemEval session date: {value!r}")
    cleaned = re.sub(r"\s*\([A-Za-z]{3,9}\)", "", value.strip())
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid LongMemEval session date: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _iter_json_array(path: Path) -> Iterator[Any]:
    """Decode the top-level array incrementally, keeping only one case in RAM."""
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8-sig") as stream:
        buffer = ""
        position = 0
        eof = False

        def fill() -> None:
            nonlocal buffer, position, eof
            chunk = stream.read(65536)
            buffer = buffer[position:] + chunk
            position = 0
            if not chunk:
                eof = True

        def skip_space() -> None:
            nonlocal position
            while True:
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if position < len(buffer) or eof:
                    return
                fill()

        fill()
        skip_space()
        if position >= len(buffer) or buffer[position] != "[":
            raise ValueError("Official LongMemEval JSON must be an array of questions")
        position += 1
        expect_value = True
        after_comma = False
        while True:
            skip_space()
            if position >= len(buffer):
                raise ValueError("Unexpected end of LongMemEval JSON array")
            if expect_value:
                if buffer[position] == "]":
                    if after_comma:
                        raise ValueError("Trailing comma in LongMemEval JSON array")
                    position += 1
                    break
                while True:
                    try:
                        item, position = decoder.raw_decode(buffer, position)
                        break
                    except json.JSONDecodeError:
                        if eof:
                            raise
                        fill()
                yield item
                expect_value = False
                after_comma = False
            elif buffer[position] == ",":
                position += 1
                expect_value = True
                after_comma = True
            elif buffer[position] == "]":
                position += 1
                break
            else:
                raise ValueError("Invalid separator in LongMemEval JSON array")
        skip_space()
        if position < len(buffer):
            raise ValueError("Unexpected content after LongMemEval JSON array")


def load_cases(path: Path, limit: int) -> tuple[list[dict[str, Any]], int]:
    if limit < 1:
        raise ValueError("--limit must be a positive cap")
    selected = []
    total = 0
    for item in _iter_json_array(path):
        total += 1
        if len(selected) < limit:
            selected.append(item)
    for index, case in enumerate(selected):
        if not isinstance(case, dict):
            raise ValueError(f"Question {index} must be an object")
        for key in ("question_id", "question", "question_type", "haystack_session_ids", "haystack_dates", "haystack_sessions", "answer_session_ids"):
            if key not in case:
                raise ValueError(f"Question {index} is missing {key}")
        if not all(isinstance(case[key], str) for key in ("question_id", "question", "question_type")):
            raise ValueError(f"Question {index} has invalid id/question/type")
        ids, dates, sessions = (case[key] for key in ("haystack_session_ids", "haystack_dates", "haystack_sessions"))
        if not all(isinstance(part, list) for part in (ids, dates, sessions)) or len(ids) != len(dates) or len(ids) != len(sessions):
            raise ValueError(f"Question {index} has mismatched haystack session arrays")
        if not isinstance(case["answer_session_ids"], list) or not all(isinstance(sid, str) for sid in case["answer_session_ids"]):
            raise ValueError(f"Question {index} has invalid answer_session_ids")
        if not all(isinstance(sid, str) for sid in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"Question {index} has duplicate or invalid session IDs")
        if not set(case["answer_session_ids"]) <= set(ids):
            raise ValueError(f"Question {index} has answer_session_ids outside the haystack")
        for session in sessions:
            if not isinstance(session, list) or not all(isinstance(turn, dict) and isinstance(turn.get("content"), str) and isinstance(turn.get("role"), str) for turn in session):
                raise ValueError(f"Question {index} has an invalid session turn")
        for date in dates:
            _official_date(date)
    return selected, total


def chronological_turns(case: dict[str, Any]) -> Iterator[tuple[str, int, dict[str, Any], int]]:
    sessions = zip(case["haystack_session_ids"], case["haystack_dates"], case["haystack_sessions"])
    ordered = sorted(enumerate(sessions), key=lambda pair: (_official_date(pair[1][1]), pair[0]))
    for _, (session_id, date, turns) in ordered:
        timestamp = _official_date(date)
        for turn_index, turn in enumerate(turns):
            yield session_id, turn_index, turn, timestamp


def _normalized_answer(value: Any) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", str(value).casefold()).split())


def load_hypotheses(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    hypotheses: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict) or not isinstance(item.get("question_id"), str) or not isinstance(item.get("hypothesis"), str):
                raise ValueError(f"Invalid hypothesis JSONL line {line_number}")
            if item["question_id"] in hypotheses:
                raise ValueError(f"Duplicate hypothesis for {item['question_id']}")
            hypotheses[item["question_id"]] = item["hypothesis"]
    return hypotheses


def _evaluate_case(provider: Any, case: dict[str, Any], top_k: int, hypothesis: str | None,
                   *, retrieval_mode: str = "fts", reindex: bool = False,
                   context_out: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    claim_sources: dict[str, list[tuple[str, int]]] = {}
    gold_turns: set[tuple[str, int]] = set()
    queued_gold_turns: set[tuple[str, int]] = set()
    skipped_gold_turns: set[tuple[str, int]] = set()
    ingest_errors: Counter[str] = Counter()
    ingested = queued = failed = 0
    ingest_started = time.perf_counter()
    for session_id, turn_index, turn, timestamp in chronological_turns(case):
        if turn.get("has_answer") is True:
            gold_turns.add((session_id, turn_index))
        content = turn["content"].strip()
        if not content:
            failed += 1
            if turn.get("has_answer") is True:
                skipped_gold_turns.add((session_id, turn_index))
            continue
        # The public claim write path applies the product's quality policy.
        # The benchmark reports queued turns instead of silently counting them
        # as indexed. Session/turn IDs stay in provenance, not query text.
        try:
            result = provider._add_claim(
                content, topic="longmemeval", evidence=f"session={session_id}; turn={turn_index}",
                source=f"benchmark:longmemeval:{turn['role']}",
                visibility_scope="global", event_at=timestamp, event_timezone="UTC",
            )
        except Exception as exc:
            # Real conversations can trigger optional subsystems unavailable in
            # this offline profile. Keep the sample running and make the loss
            # explicit; never turn failed writes into successful evidence.
            kind = "hermes_secret_core_unavailable" if str(exc).startswith("hermes_secret_core_unavailable") else type(exc).__name__
            ingest_errors[kind] += 1
            failed += 1
            if turn.get("has_answer") is True:
                skipped_gold_turns.add((session_id, turn_index))
            continue
        if isinstance(result, str) and result.startswith("rq_"):
            queued += 1
            if turn.get("has_answer") is True:
                queued_gold_turns.add((session_id, turn_index))
        elif isinstance(result, str) and result.startswith("c_"):
            claim_sources.setdefault(result, []).append((session_id, turn_index))
            ingested += 1
        else:
            failed += 1
            if turn.get("has_answer") is True:
                skipped_gold_turns.add((session_id, turn_index))
    ingest_ms = (time.perf_counter() - ingest_started) * 1000
    reindex_result = None
    if reindex:
        reindex_started = time.perf_counter()
        outcome = provider._reindex()
        if not isinstance(outcome, dict) or not outcome.get("ok"):
            reason = outcome.get("error", "unknown") if isinstance(outcome, dict) else "unknown"
            raise RuntimeError(f"isolated semantic reindex failed: {reason}")
        reindex_result = {
            "status": outcome.get("status"), "count": outcome.get("count"),
            "total": outcome.get("total"),
            "elapsed_ms": round((time.perf_counter() - reindex_started) * 1000, 2),
        }
    started = time.perf_counter()
    hits = provider._search(case["question"], limit=top_k, retrieval_mode=retrieval_mode, record_retrieval=False, apply_rerank=False)
    search_ms = (time.perf_counter() - started) * 1000
    if context_out is not None:
        context_out.extend((str(hit["id"]), str(hit["claim"])) for hit in hits)
    retrieved_ids = [str(hit["id"]) for hit in hits]
    retrieved_turns = [claim_sources.get(cid, []) for cid in retrieved_ids]
    retrieved_sessions = {sid for sources in retrieved_turns for sid, _ in sources}
    retrieved_turn_set = {item for sources in retrieved_turns for item in sources}
    gold_sessions = set(case["answer_session_ids"])
    indexed_sessions = {sid for sources in claim_sources.values() for sid, _ in sources}
    indexed_gold_turns = gold_turns & {item for sources in claim_sources.values() for item in sources}
    abstention = case["question_id"].endswith("_abs") or not gold_sessions
    first_relevant_rank = next((rank for rank, sources in enumerate(retrieved_turns, 1) if any(sid in gold_sessions for sid, _ in sources)), None)
    result: dict[str, Any] = {
        "question_id": case["question_id"], "question_type": case["question_type"],
        "gold_session_ids": sorted(gold_sessions),
        "gold_turn_ids": [f"{sid}:{turn}" for sid, turn in sorted(gold_turns)],
        "gold_turn_ids_indexed": [f"{sid}:{turn}" for sid, turn in sorted(indexed_gold_turns)],
        "gold_turn_ids_queued": [f"{sid}:{turn}" for sid, turn in sorted(queued_gold_turns)],
        "gold_turn_ids_skipped": [f"{sid}:{turn}" for sid, turn in sorted(skipped_gold_turns)],
        "retrieved_claim_ids": retrieved_ids,
        "retrieved_evidence_ids": [[f"{sid}:{turn}" for sid, turn in sources] for sources in retrieved_turns],
        "retrieved_session_ids": sorted(retrieved_sessions),
        "gold_session_ids_without_indexed_claim": sorted(gold_sessions - indexed_sessions),
        "gold_session_ids_indexed_but_not_retrieved": sorted((gold_sessions & indexed_sessions) - retrieved_sessions),
        "accepted_turns": ingested, "unique_indexed_claims": len(claim_sources),
        "queued_turns": queued, "skipped_turns": failed,
        "ingest_error_counts": dict(ingest_errors),
        "ambiguous_claim_ids": sum(len(sources) > 1 for sources in claim_sources.values()),
        "ingest_ms": round(ingest_ms, 2), "search_ms": round(search_ms, 2),
        "retrieval_mode": retrieval_mode, "semantic_reindex": reindex_result,
        "evidence_scored": not abstention,
        "session_recall_all": None if abstention else gold_sessions <= retrieved_sessions,
        "session_recall_any": None if abstention else bool(gold_sessions & retrieved_sessions),
        "reciprocal_rank": None if abstention else (1 / first_relevant_rank if first_relevant_rank else 0.0),
        "turn_recall_all": None if abstention or not gold_turns else gold_turns <= retrieved_turn_set,
    }
    if hypothesis is not None:
        expected = case.get("answer")
        answers = expected if isinstance(expected, list) else [expected]
        result["answer_proxy_exact_match"] = any(_normalized_answer(hypothesis) == _normalized_answer(value) for value in answers)
    return result


def _answer_openrouter(case: dict[str, Any], context: list[tuple[str, str]], *,
                       api_key: str, model: str, max_tokens: int, context_chars: int) -> tuple[str, dict[str, Any], float]:
    """Generate one bounded answer from retrieved isolated claims only."""
    remaining = context_chars
    evidence = []
    for claim_id, claim in context:
        if remaining <= 0:
            break
        line = f"[{claim_id}] " + " ".join(claim.split())
        excerpt = line[:min(remaining, 1600)]
        if excerpt:
            evidence.append(excerpt)
            remaining -= len(excerpt)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Answer the question using only the supplied memory evidence. If it does not support an answer, say I don't know. Keep the answer concise."},
            {"role": "user", "content": "Question date: " + str(case.get("question_date") or "")[:80]
             + "\nQuestion: " + case["question"][:2000]
             + "\nMemory evidence:\n" + ("\n".join(evidence) if evidence else "(none)")},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            reply = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenRouter answer request returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"OpenRouter answer request failed: {type(exc).__name__}") from None
    elapsed_ms = (time.perf_counter() - started) * 1000
    choices = reply.get("choices") if isinstance(reply, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("OpenRouter answer response has no choice")
    message = choices[0].get("message") or {}
    answer = message.get("content") if isinstance(message, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("OpenRouter answer response has no text")
    usage = reply.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    reported = {
        "prompt_tokens": int(usage["prompt_tokens"]) if isinstance(usage.get("prompt_tokens"), (int, float)) else None,
        "completion_tokens": int(usage["completion_tokens"]) if isinstance(usage.get("completion_tokens"), (int, float)) else None,
        "total_tokens": int(usage["total_tokens"]) if isinstance(usage.get("total_tokens"), (int, float)) else None,
        "cost": float(usage["cost"]) if isinstance(usage.get("cost"), (int, float)) else None,
        "context_chars": context_chars - remaining,
    }
    return answer.strip(), reported, round(elapsed_ms, 2)


def _attach_generated_answer(row: dict[str, Any], case: dict[str, Any], context: list[tuple[str, str]], *,
                             api_key: str, model: str, max_tokens: int, context_chars: int) -> None:
    try:
        answer, usage, latency = _answer_openrouter(
            case, context, api_key=api_key, model=model,
            max_tokens=max_tokens, context_chars=context_chars,
        )
    except Exception as exc:
        row["answer_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return
    expected = case.get("answer")
    answers = expected if isinstance(expected, list) else [expected]
    row["hypothesis"] = answer
    row["answer_proxy_exact_match"] = any(_normalized_answer(answer) == _normalized_answer(value) for value in answers)
    row["answer_usage"] = usage
    row["answer_ms"] = latency


def _load_plugin() -> Any:
    name = f"memory_wiki_longmemeval_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot import Memory Wiki plugin")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _env_file_values(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        from dotenv import dotenv_values
    except ImportError as exc:
        raise RuntimeError("--env-file requires python-dotenv") from exc
    values = dotenv_values(path)
    return {key: str(values[key]) for key in _SERVICE_ENV_KEYS if values.get(key)}


@contextmanager
def _isolated_environment(home: str, overrides: dict[str, str] | None = None) -> Iterator[None]:
    settings = {"HERMES_HOME": home, **_ISOLATED_ENV, **(overrides or {})}
    previous = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _qdrant_collection_names(module: Any) -> set[str]:
    response = module._qdrant_req("GET", "/collections")
    if not isinstance(response, dict) or str(response.get("status") or "") != "ok":
        raise RuntimeError("Qdrant collection listing unavailable; cannot verify isolation")
    items = (response.get("result") or {}).get("collections")
    if not isinstance(items, list):
        raise RuntimeError("Qdrant collection listing has unexpected shape")
    return {str(item["name"]) for item in items if isinstance(item, dict) and isinstance(item.get("name"), str)}


def _remove_isolated_collection(module: Any, physical: str, generated_prefix: str) -> bool:
    if not physical.startswith(generated_prefix + "_") or module.QDRANT_ALIAS_MODE != "physical":
        raise RuntimeError("Refusing to remove a collection outside this benchmark case")
    for attempt in range(3):
        if physical not in _qdrant_collection_names(module):
            return True
        module._qdrant_req("DELETE", f"/collections/{physical}", timeout=10)
        if physical not in _qdrant_collection_names(module):
            return True
        if attempt < 2:
            time.sleep(1)
    return False


def _run_semantic_case(case: dict[str, Any], index: int, top_k: int, hypothesis: str | None,
                       *, tmp: str, env_values: dict[str, str], run_token: str,
                       answer_model: str = "", answer_max_tokens: int = 160,
                       answer_context_chars: int = 6000) -> dict[str, Any]:
    generated_prefix = f"memory_wiki_lme_{run_token}_{index:04d}"
    overrides = {
        **env_values, "MEMORY_WIKI_SEMANTIC": "1",
        "MEMORY_WIKI_QDRANT_COLLECTION": generated_prefix,
        "MEMORY_WIKI_QDRANT_ALIAS": f"{generated_prefix}_alias",
        "MEMORY_WIKI_QDRANT_ALIAS_MODE": "physical",
    }
    with _isolated_environment(tmp, overrides):
        module = _load_plugin()
        physical = module._physical_collection_name()
        if module.QDRANT_ALIAS_MODE != "physical" or not physical.startswith(generated_prefix + "_"):
            sys.modules.pop(module.__name__, None)
            raise RuntimeError("Semantic benchmark failed its collection isolation guard")
        try:
            existing_names = _qdrant_collection_names(module)
        except Exception:
            sys.modules.pop(module.__name__, None)
            raise
        if physical in existing_names:
            sys.modules.pop(module.__name__, None)
            raise RuntimeError("Generated collection already exists; refusing to use or remove it")
        # Explicit synchronous reindex is the only benchmark writer. A daemon
        # outbox worker could otherwise recreate a deleted collection later.
        module._start_outbox_worker = lambda *args, **kwargs: None
        module._wake_outbox_worker = lambda *args, **kwargs: None
        embedding_calls: list[tuple[str, int]] = []
        original_embed = module._openrouter_embed

        def count_embed(text: str, *, input_type: str, **kwargs: Any) -> Any:
            embedding_calls.append((input_type, min(len(str(text)), module.EMBED_INPUT_MAX_CHARS)))
            return original_embed(text, input_type=input_type, **kwargs)

        module._openrouter_embed = count_embed
        provider = None
        result = None
        try:
            provider = module.MemoryWikiProvider()
            provider.initialize(
                f"longmemeval-{index}", hermes_home=str(Path(tmp) / f"case-{index:04d}"),
                project_id=f"longmemeval-{index}", bot_id="longmemeval-benchmark",
            )
            context: list[tuple[str, str]] = []
            result = _evaluate_case(provider, case, top_k, hypothesis, retrieval_mode="hybrid", reindex=True,
                                    context_out=context if answer_model else None)
            if answer_model:
                _attach_generated_answer(
                    result, case, context, api_key=env_values.get("OPENROUTER_API_KEY") or env_values.get("MEMORY_WIKI_EMBED_API_KEY") or "",
                    model=answer_model, max_tokens=answer_max_tokens, context_chars=answer_context_chars,
                )
            result["embedding_operations"] = len(embedding_calls)
            result["embedding_input_chars"] = sum(chars for _, chars in embedding_calls)
            result["embedding_provider"] = module.EMBED_PROVIDER
            result["embedding_model"] = module.EMBED_MODEL
            result["isolated_collection"] = physical
        finally:
            if provider is not None:
                try:
                    provider.shutdown()
                except Exception:
                    connection = getattr(provider, "_conn", None)
                    if connection is not None:
                        connection.close()
                        provider._conn = None
            try:
                removed = _remove_isolated_collection(module, physical, generated_prefix)
            finally:
                sys.modules.pop(module.__name__, None)
        if not removed:
            raise RuntimeError(f"Could not verify cleanup of isolated collection {physical}")
        assert result is not None
        result["isolated_collection_removed"] = True
        return result


def _mean(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row[field] is not None]
    return round(statistics.mean(values), 4) if values else None


def run(dataset: Path, *, limit: int = 5, top_k: int = 5, hypotheses: Path | None = None,
        semantic: bool = False, env_file: Path | None = None, answer_model: str = "",
        answer_max_tokens: int = 160, answer_context_chars: int = 6000) -> dict[str, Any]:
    if not 1 <= top_k <= 50:
        raise ValueError("--top-k must be between 1 and 50")
    if answer_model and not (1 <= answer_max_tokens <= 256 and 256 <= answer_context_chars <= 10000):
        raise ValueError("answer limits must be 1-256 tokens and 256-10000 context characters")
    if answer_model and hypotheses is not None:
        raise ValueError("--hypotheses and --answer-model cannot be combined")
    cases, total_questions = load_cases(dataset, limit)
    supplied_hypotheses = load_hypotheses(hypotheses)
    results = []
    env_values = _env_file_values(env_file) if semantic or answer_model else {}
    if answer_model and (env_file is None or not (env_values.get("OPENROUTER_API_KEY") or env_values.get("MEMORY_WIKI_EMBED_API_KEY"))):
        raise ValueError("--answer-model requires --env-file with an OpenRouter API key")
    if semantic:
        if env_file is None:
            raise ValueError("--semantic requires an explicit --env-file")
        if env_values.get("MEMORY_WIKI_EMBED_PROVIDER") != "openrouter":
            raise ValueError("--semantic requires an OpenRouter embedding provider in --env-file")
        if not (env_values.get("MEMORY_WIKI_EMBED_API_KEY") or env_values.get("OPENROUTER_API_KEY")):
            raise ValueError("--semantic requires an embedding API key in --env-file")
        if not env_values.get("MEMORY_WIKI_QDRANT_URL"):
            raise ValueError("--semantic requires MEMORY_WIKI_QDRANT_URL in --env-file")
    with tempfile.TemporaryDirectory(prefix="memory-wiki-longmemeval-") as tmp:
        if semantic:
            run_token = uuid.uuid4().hex[:16]
            for index, case in enumerate(cases):
                results.append(_run_semantic_case(
                    case, index, top_k, supplied_hypotheses.get(case["question_id"]),
                    tmp=tmp, env_values=env_values, run_token=run_token,
                    answer_model=answer_model, answer_max_tokens=answer_max_tokens,
                    answer_context_chars=answer_context_chars,
                ))
        else:
            with _isolated_environment(tmp, env_values if answer_model else None):
                module = _load_plugin()
                try:
                    for index, case in enumerate(cases):
                        case_home = Path(tmp) / f"case-{index:04d}"
                        provider = module.MemoryWikiProvider()
                        try:
                            provider.initialize(
                                f"longmemeval-{index}", hermes_home=str(case_home),
                                project_id=f"longmemeval-{index}", bot_id="longmemeval-benchmark",
                            )
                            context: list[tuple[str, str]] = []
                            row = _evaluate_case(
                                provider, case, top_k, supplied_hypotheses.get(case["question_id"]),
                                context_out=context if answer_model else None,
                            )
                            if answer_model:
                                _attach_generated_answer(
                                    row, case, context,
                                    api_key=env_values.get("OPENROUTER_API_KEY") or env_values.get("MEMORY_WIKI_EMBED_API_KEY") or "",
                                    model=answer_model, max_tokens=answer_max_tokens,
                                    context_chars=answer_context_chars,
                                )
                            results.append(row)
                        finally:
                            connection = getattr(provider, "_conn", None)
                            if connection is not None:
                                connection.close()
                                provider._conn = None
                finally:
                    sys.modules.pop(module.__name__, None)
    evidence_rows = [row for row in results if row["evidence_scored"]]
    answer_rows = [row for row in results if "answer_proxy_exact_match" in row]
    by_type = {}
    for question_type in sorted({row["question_type"] for row in evidence_rows}):
        group = [row for row in evidence_rows if row["question_type"] == question_type]
        by_type[question_type] = {"n": len(group), "session_recall_all": _mean(group, "session_recall_all"), "session_recall_any": _mean(group, "session_recall_any")}
    return {
        "dataset": str(dataset.resolve()), "dataset_questions": total_questions,
        "evaluated_questions": len(results), "top_k": top_k,
        "retrieval_mode": "hybrid" if semantic else "fts",
        "isolation": (
            "temporary Hermes profile and per-question database/physical Qdrant collection; alias disabled"
            if semantic else "temporary Hermes profile and per-question database; semantic/Qdrant disabled"
        ),
        "evidence_questions": len(evidence_rows),
        "session_recall_all_at_k": _mean(evidence_rows, "session_recall_all"),
        "session_recall_any_at_k": _mean(evidence_rows, "session_recall_any"),
        "session_mrr_at_k": _mean(evidence_rows, "reciprocal_rank"),
        "turn_recall_all_at_k": _mean(evidence_rows, "turn_recall_all"),
        "answer_proxy_exact_match": _mean(answer_rows, "answer_proxy_exact_match"),
        "answer_proxy_coverage": len(answer_rows),
        "answer_model": answer_model or None,
        "answer_errors": sum("answer_error" in row for row in results),
        "answer_p50_ms": round(statistics.median([row["answer_ms"] for row in results if "answer_ms" in row]), 2) if answer_rows and answer_model else None,
        "answer_prompt_tokens": sum((row.get("answer_usage") or {}).get("prompt_tokens") or 0 for row in results) if answer_model else None,
        "answer_completion_tokens": sum((row.get("answer_usage") or {}).get("completion_tokens") or 0 for row in results) if answer_model else None,
        "answer_reported_cost": (
            round(sum((row.get("answer_usage") or {}).get("cost") or 0.0 for row in results), 8)
            if answer_model and all((row.get("answer_usage") or {}).get("cost") is not None for row in answer_rows) and answer_rows else None
        ),
        "search_p50_ms": round(statistics.median([row["search_ms"] for row in results]), 2) if results else None,
        "embedding_operations": sum(row.get("embedding_operations", 0) for row in results) if semantic else 0,
        "embedding_input_chars": sum(row.get("embedding_input_chars", 0) for row in results) if semantic else 0,
        "embedding_tokens": None,
        "embedding_cost": None,
        "isolated_collections_removed": all(row.get("isolated_collection_removed") is True for row in results) if semantic else None,
        "by_question_type": by_type, "questions": results,
        "limitations": [
            ("Hybrid retrieval uses live configured embeddings/Qdrant; exact token usage and cost are unavailable from the plugin embedding client."
             if semantic else "FTS-only retrieval; no Qdrant or OpenRouter requests are made."),
            "Raw turns are sent through claim quality policy; queued turns are not searchable.",
            "Duplicate turns can merge into a claim, making one retrieved claim map to multiple evidence IDs.",
            "The optional normalized exact-match answer score is a local proxy, not the official model-judged LongMemEval QA metric.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Local official LongMemEval JSON file (no download)")
    parser.add_argument("--limit", type=int, default=5, help="Maximum questions to evaluate (default: 5)")
    parser.add_argument("--top-k", type=int, default=5, help="Top claims per question, 1-50 (default: 5)")
    parser.add_argument("--hypotheses", type=Path, help="Optional official-format JSONL with question_id and hypothesis")
    parser.add_argument("--semantic", action="store_true", help="Use configured OpenRouter embeddings and isolated Qdrant collections")
    parser.add_argument("--env-file", type=Path, help="Required with --semantic or --answer-model; service credentials")
    parser.add_argument("--answer-model", default="", help="Optional OpenRouter chat model for answers from retrieved claims")
    parser.add_argument("--answer-max-tokens", type=int, default=160, help="Maximum completion tokens per answer (1-256)")
    parser.add_argument("--answer-context-chars", type=int, default=6000, help="Maximum retrieved context characters (256-10000)")
    parser.add_argument("--hypotheses-out", type=Path, help="Official-format hypothesis JSONL output; required with --answer-model")
    parser.add_argument("--output", type=Path, help="Optional result JSON path")
    args = parser.parse_args()
    if args.output and args.output.resolve() == args.dataset.resolve():
        parser.error("--output must differ from --dataset")
    if args.output and args.hypotheses and args.output.resolve() == args.hypotheses.resolve():
        parser.error("--output must differ from --hypotheses")
    if args.answer_model and not args.hypotheses_out:
        parser.error("--answer-model requires --hypotheses-out")
    if args.hypotheses_out:
        sources = [args.dataset, args.output, args.hypotheses, args.env_file]
        if any(path is not None and path.resolve() == args.hypotheses_out.resolve() for path in sources):
            parser.error("--hypotheses-out must differ from all input and result paths")
    result = run(args.dataset, limit=args.limit, top_k=args.top_k, hypotheses=args.hypotheses,
                 semantic=args.semantic, env_file=args.env_file, answer_model=args.answer_model,
                 answer_max_tokens=args.answer_max_tokens, answer_context_chars=args.answer_context_chars)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.hypotheses_out:
        lines = [json.dumps({"question_id": row["question_id"], "hypothesis": row["hypothesis"]}, ensure_ascii=False)
                 for row in result["questions"] if "hypothesis" in row]
        args.hypotheses_out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
