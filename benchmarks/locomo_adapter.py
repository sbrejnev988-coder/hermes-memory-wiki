"""Isolated retrieval and optional bounded reader on the official LoCoMo dataset.

Raw dialogue turns are indexed directly as FTS claims. This measures Memory
Wiki retrieval and evidence ranking, not automatic memory extraction. Optional
reader hypotheses are not scored as official LoCoMo QA. The official JSON is
fetched only with --download-official.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import statistics
import sys
import tempfile
import time
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

BENCHMARKS = Path(__file__).resolve().parent
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))
from qa_reader import AnswerBudget, answer_openrouter, looks_like_abstention, safe_outbound_evidence


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_COMMIT = "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"
OFFICIAL_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
OFFICIAL_URL = f"https://raw.githubusercontent.com/snap-research/locomo/{OFFICIAL_COMMIT}/data/locomo10.json"
MAX_DATASET_BYTES = 5_000_000
_SESSION = re.compile(r"session_(\d+)\Z")
_EVIDENCE_ID = re.compile(r"D\d+:\d+\Z")
_ISOLATED_ENV = {
    "HERMES_SECURITY_STRICT": "0",
    "MEMORY_WIKI_SEMANTIC": "0",
    "MEMORY_WIKI_RERANK_ENABLED": "0",
    "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE": "0",
    "MEMORY_WIKI_GRAPH_EXTRACT_ENABLED": "0",
}


def download_official() -> bytes:
    """Read one pinned public artifact, with a size cap and content hash."""
    with urllib.request.urlopen(OFFICIAL_URL, timeout=30) as response:
        length = response.headers.get("Content-Length")
        if length is not None and int(length) > MAX_DATASET_BYTES:
            raise ValueError("official LoCoMo dataset exceeds size cap")
        raw = response.read(MAX_DATASET_BYTES + 1)
    if len(raw) > MAX_DATASET_BYTES:
        raise ValueError("official LoCoMo dataset exceeds size cap")
    if hashlib.sha256(raw).hexdigest() != OFFICIAL_SHA256:
        raise ValueError("official LoCoMo dataset hash mismatch")
    return raw


def _load_dataset(raw: bytes) -> list[dict[str, Any]]:
    if len(raw) > MAX_DATASET_BYTES:
        raise ValueError("LoCoMo dataset exceeds size cap")
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, list) or not data:
        raise ValueError("LoCoMo dataset must be a nonempty array")
    sample_ids: set[str] = set()
    for sample in data:
        if not isinstance(sample, dict) or not isinstance(sample.get("sample_id"), str):
            raise ValueError("invalid LoCoMo sample")
        sample_id = sample["sample_id"]
        if sample_id in sample_ids:
            raise ValueError("duplicate LoCoMo sample ID")
        sample_ids.add(sample_id)
        conversation, questions = sample.get("conversation"), sample.get("qa")
        if not isinstance(conversation, dict) or not isinstance(questions, list):
            raise ValueError("invalid LoCoMo conversation or QA")
        dialogue_ids: set[str] = set()
        session_count = 0
        for key, turns in conversation.items():
            if not _SESSION.fullmatch(key):
                continue
            session_count += 1
            if not isinstance(turns, list) or not isinstance(conversation.get(key + "_date_time"), str):
                raise ValueError("invalid LoCoMo session")
            datetime.strptime(conversation[key + "_date_time"], "%I:%M %p on %d %B, %Y")
            for turn in turns:
                if (not isinstance(turn, dict) or not isinstance(turn.get("dia_id"), str)
                        or not isinstance(turn.get("text"), str)):
                    raise ValueError("invalid LoCoMo dialogue turn")
                if turn["dia_id"] in dialogue_ids:
                    raise ValueError("duplicate LoCoMo dialogue ID")
                dialogue_ids.add(turn["dia_id"])
        if not session_count:
            raise ValueError("LoCoMo conversation has no sessions")
        for question in questions:
            if (not isinstance(question, dict) or not isinstance(question.get("question"), str)
                    or not isinstance(question.get("evidence"), list)
                    or not all(isinstance(item, str) for item in question["evidence"])):
                raise ValueError("invalid LoCoMo question or evidence")
    return data


def _turns(sample: dict[str, Any]) -> Iterator[tuple[str, str, str, int]]:
    conversation = sample["conversation"]
    sessions = sorted((int(match.group(1)), key) for key in conversation
                      if (match := _SESSION.fullmatch(key)))
    for _, key in sessions:
        timestamp = int(datetime.strptime(conversation[key + "_date_time"],
                                          "%I:%M %p on %d %B, %Y").replace(tzinfo=timezone.utc).timestamp())
        for turn in conversation[key]:
            caption = str(turn.get("blip_caption") or "").strip()
            text = turn["text"].strip()
            if caption:
                text = (text + "\n" if text else "") + "Image caption: " + caption
            yield turn["dia_id"], key, text, timestamp


def _evidence_ids(raw: list[str]) -> tuple[set[str], list[str]]:
    """Expand explicitly separated IDs; never repair malformed annotations."""
    ids: set[str] = set()
    malformed: list[str] = []
    for entry in raw:
        parts = [part for part in re.split(r"[;,\s]+", entry.strip()) if part]
        for part in parts:
            if _EVIDENCE_ID.fullmatch(part):
                ids.add(part)
            else:
                malformed.append(part)
    return ids, malformed


def _load_plugin() -> Any:
    name = "memory_wiki_locomo_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py",
                                                   submodule_search_locations=[str(ROOT)])
    if spec is None or spec.loader is None:
        raise RuntimeError("Memory Wiki module cannot be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


@contextmanager
def _isolated_home(home: str) -> Iterator[None]:
    settings = {"HERMES_HOME": home, **_ISOLATED_ENV}
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


def _index_turns(provider: Any, module: Any, sample: dict[str, Any]) -> dict[str, Any]:
    stamp = module.now()
    rows = []
    id_to_dialogue: dict[str, str] = {}
    blank = 0
    short = 0
    long = 0
    skipped_ids: list[str] = []
    for dia_id, session_id, text, event_at in _turns(sample):
        if not text:
            blank += 1
            skipped_ids.append(dia_id)
            continue
        if len(text) < 10:
            short += 1
            skipped_ids.append(dia_id)
            continue
        if len(text) > 8000:
            long += 1
            skipped_ids.append(dia_id)
            continue
        claim_id = "lo_" + hashlib.sha256(f"{sample['sample_id']}\0{dia_id}".encode()).hexdigest()[:24]
        id_to_dialogue[claim_id] = dia_id
        rows.append((claim_id, text, text, "locomo_dialogue", "active", .9, .8,
                     "benchmark:locomo:raw_dialogue", "", stamp, stamp, stamp,
                     hashlib.sha256(f"{claim_id}\0{text}".encode()).hexdigest(),
                     "global", "global", .9, "low", "fact", event_at, "UTC",
                     f"locomo:{sample['sample_id']}:{dia_id}"))
    with provider._connect() as conn:
        conn.executemany("""INSERT INTO claims(
            id,claim,normalized_claim,topic,status,confidence,salience,source,evidence,
            created_at,updated_at,freshness_at,hash,scope,visibility_scope,
            quality,risk,trust_class,event_at,event_timezone,source_ref)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    provider._rebuild_fts()
    return {"claim_to_dialogue": id_to_dialogue, "indexed_turns": len(rows),
            "blank_turns": blank, "short_turns": short, "long_turns": long,
            "skipped_dialogue_ids": skipped_ids}


def _score_question(provider: Any, question: dict[str, Any], claim_to_dialogue: dict[str, str],
                    indexed_dialogues: set[str], top_k: int,
                    context_out: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    gold, malformed = _evidence_ids(question["evidence"])
    unresolved = sorted(gold - indexed_dialogues)
    started = time.perf_counter()
    found = provider._search(question["question"], limit=top_k, retrieval_mode="fts",
                             record_retrieval=False, apply_rerank=False)
    latency_ms = (time.perf_counter() - started) * 1000
    if context_out is not None:
        context_out.extend((claim_to_dialogue.get(str(row["id"]), ""), str(row.get("claim") or ""))
                           for row in found if claim_to_dialogue.get(str(row["id"])))
    retrieved = [claim_to_dialogue.get(str(row["id"]), "") for row in found]
    retrieved = [dia_id for dia_id in retrieved if dia_id]
    hits = gold.intersection(retrieved)
    first = next((rank for rank, dia_id in enumerate(retrieved, 1) if dia_id in gold), None)
    return {
        "category": question.get("category"), "question": question["question"],
        "gold_dialogue_ids": sorted(gold), "malformed_gold_annotations": malformed,
        "unresolved_gold_dialogue_ids": unresolved, "retrieved_dialogue_ids": retrieved,
        "hit_dialogue_ids": sorted(hits), "evidence_scored": bool(gold),
        "recall_at_k": len(hits) / len(gold) if gold else None,
        "any_evidence_at_k": bool(hits) if gold else None,
        "all_evidence_at_k": gold <= set(retrieved) if gold else None,
        "reciprocal_rank": 1 / first if first else (0.0 if gold else None),
        "search_ms": round(latency_ms, 2),
    }


def _aggregate(rows: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
    scored = [row for row in rows if row["evidence_scored"]]
    def mean(field: str) -> float | None:
        return round(statistics.mean(float(row[field]) for row in scored), 4) if scored else None
    return {
        "questions": len(rows), "evidence_scored_questions": len(scored),
        "questions_with_malformed_evidence": sum(bool(row["malformed_gold_annotations"]) for row in rows),
        "questions_with_unresolved_evidence": sum(bool(row["unresolved_gold_dialogue_ids"]) for row in rows),
        f"evidence_recall_at_{top_k}": mean("recall_at_k"),
        f"any_evidence_at_{top_k}": mean("any_evidence_at_k"),
        f"all_evidence_at_{top_k}": mean("all_evidence_at_k"),
        "mrr": mean("reciprocal_rank"),
        "search_p50_ms": round(statistics.median(row["search_ms"] for row in rows), 2) if rows else None,
    }


def run(raw: bytes, *, max_conversations: int | None = 1,
        questions_per_conversation: int | None = 50, top_k: int = 5,
        answer_model: str = "", env_file: Path | None = None,
        answer_max_tokens: int = 160, answer_context_chars: int = 6000,
        answer_request_budget: int | None = None,
        answer_cost_soft_cap_usd: float | None = None) -> dict[str, Any]:
    if max_conversations is not None and max_conversations < 1:
        raise ValueError("max_conversations must be positive")
    if questions_per_conversation is not None and questions_per_conversation < 1:
        raise ValueError("questions_per_conversation must be positive")
    if not 1 <= top_k <= 50:
        raise ValueError("top_k must be 1..50")
    if answer_model and not (1 <= answer_max_tokens <= 256 and 256 <= answer_context_chars <= 10000):
        raise ValueError("answer limits must be 1-256 tokens and 256-10000 context characters")
    if not answer_model and (answer_request_budget is not None or answer_cost_soft_cap_usd is not None):
        raise ValueError("answer budgets require --answer-model")
    if answer_model:
        if env_file is None:
            raise ValueError("--answer-model requires --env-file")
        try:
            from dotenv import dotenv_values
        except ImportError as exc:
            raise RuntimeError("--env-file requires python-dotenv") from exc
        api_key = str(dotenv_values(env_file).get("OPENROUTER_API_KEY") or "")
        if not api_key:
            raise ValueError("--answer-model requires --env-file with OPENROUTER_API_KEY")
    else:
        api_key = ""
    data = _load_dataset(raw)
    selected = data[:max_conversations]
    question_count = sum(len(sample["qa"][:questions_per_conversation]) for sample in selected)
    budget = AnswerBudget(question_count if answer_request_budget is None else answer_request_budget,
                          answer_cost_soft_cap_usd) if answer_model else None
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="memory-wiki-locomo-") as tmp:
        with _isolated_home(tmp):
            module = _load_plugin()
            try:
                for index, sample in enumerate(selected):
                    provider = module.MemoryWikiProvider()
                    try:
                        provider.initialize(f"locomo-{index}", hermes_home=str(Path(tmp) / f"sample-{index}"),
                                            bot_id="locomo-benchmark", project_id=f"locomo-{index}")
                        indexed = _index_turns(provider, module, sample)
                        rows = []
                        for question in sample["qa"][:questions_per_conversation]:
                            context: list[tuple[str, str]] = []
                            row = _score_question(provider, question, indexed["claim_to_dialogue"],
                                                  set(indexed["claim_to_dialogue"].values()), top_k,
                                                  context_out=context if answer_model else None)
                            if answer_model:
                                assert budget is not None
                                reason = (
                                    None if safe_outbound_evidence(
                                        module.secret_scan, str(question["question"]), context,
                                    ) else "secret_guard"
                                ) or budget.skip_reason()
                                if reason:
                                    row["answer_skipped_reason"] = reason
                                else:
                                    budget.begin()
                                    try:
                                        answer, usage, elapsed = answer_openrouter(
                                            api_key=api_key, model=answer_model,
                                            question=question["question"], context=context,
                                            max_tokens=answer_max_tokens,
                                            context_chars=answer_context_chars,
                                            unsupported_answer="No information available",
                                        )
                                    except Exception as exc:
                                        row["answer_error"] = type(exc).__name__
                                        budget.unknown_cost = True
                                    else:
                                        row["hypothesis"] = answer
                                        row["answer_usage"] = usage
                                        row["answer_ms"] = elapsed
                                        row["answer_abstention_heuristic"] = looks_like_abstention(answer)
                                        row["expected_abstention"] = question["category"] == 5
                                        budget.record(usage)
                            rows.append(row)
                        results.append({
                            "sample_id": sample["sample_id"], "indexed_turns": indexed["indexed_turns"],
                            "blank_turns": indexed["blank_turns"],
                            "short_turns": indexed["short_turns"], "long_turns": indexed["long_turns"],
                            "skipped_dialogue_ids": indexed["skipped_dialogue_ids"],
                            "metrics": _aggregate(rows, top_k),
                            "questions": rows,
                        })
                    finally:
                        if provider._conn is not None:
                            provider._conn.close()
                            provider._conn = None
            finally:
                sys.modules.pop(module.__name__, None)
    all_rows = [row for sample in results for row in sample["questions"]]
    answered = [row for row in all_rows if "answer_usage" in row]
    def complete_usage(field: str) -> int | None:
        return (sum(int(row["answer_usage"][field]) for row in answered)
                if answered and all(row["answer_usage"].get(field) is not None for row in answered)
                else None)
    categories = sorted({str(row["category"]) for row in all_rows})
    return {
        "benchmark": "LoCoMo official dialogue evidence retrieval",
        "source_repository": "https://github.com/snap-research/locomo",
        "official_commit": OFFICIAL_COMMIT if hashlib.sha256(raw).hexdigest() == OFFICIAL_SHA256 else None,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "dataset_bytes": len(raw), "dataset_conversations": len(data),
        "dataset_questions": sum(len(sample["qa"]) for sample in data),
        "evaluated_conversations": len(results), "evaluated_questions": len(all_rows),
        "retrieval_mode": "fts", "top_k": top_k,
        "indexing": "raw dialogue turns inserted as isolated FTS claims; automatic memory extraction bypassed",
        "answer_generation_scored": False,
        "answer_model": answer_model or None,
        "answer_config": {
            "reader_prompt_version": 1,
            "max_completion_tokens_per_request": answer_max_tokens,
            "max_retrieved_context_chars_per_request": answer_context_chars,
            "temperature": 0,
        } if answer_model else None,
        "answer_budget": budget.summary() if budget else None,
        "answer_generated": len(answered),
        "answer_errors": sum("answer_error" in row for row in all_rows),
        "answer_skipped": sum("answer_skipped_reason" in row for row in all_rows),
        "answer_prompt_tokens": complete_usage("prompt_tokens") if answer_model else None,
        "answer_completion_tokens": complete_usage("completion_tokens") if answer_model else None,
        "answer_reported_cost": budget.summary()["reported_cost_usd"] if budget else None,
        "answer_p50_ms": round(statistics.median(row["answer_ms"] for row in answered), 2) if answered else None,
        "answer_p95_ms": round(sorted(row["answer_ms"] for row in answered)[max(0, int(len(answered) * .95 + .999999) - 1)], 2) if answered else None,
        "answer_abstention_heuristic": {
            "expected": sum(row["expected_abstention"] for row in answered),
            "recognized": sum(row["expected_abstention"] and row["answer_abstention_heuristic"] for row in answered),
            "false_abstentions": sum(not row["expected_abstention"] and row["answer_abstention_heuristic"] for row in answered),
        } if answer_model else None,
        "metrics": _aggregate(all_rows, top_k),
        "by_category": {category: _aggregate([row for row in all_rows if str(row["category"]) == category], top_k)
                        for category in categories},
        "samples": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset", type=Path, help="Local official-format locomo10.json")
    source.add_argument("--download-official", action="store_true", help="Fetch pinned official JSON with SHA-256 verification")
    parser.add_argument("--max-conversations", type=int, default=1, help="Default 1; use 10 for the full official set")
    parser.add_argument("--questions-per-conversation", type=int, default=50, help="Default 50; use 0 for all")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--answer-model", default="", help="Optional OpenRouter chat model for retrieved dialogue answers")
    parser.add_argument("--env-file", type=Path, help="Dotenv file with OPENROUTER_API_KEY; required for --answer-model")
    parser.add_argument("--answer-max-tokens", type=int, default=160)
    parser.add_argument("--answer-context-chars", type=int, default=6000)
    parser.add_argument("--answer-request-budget", type=int, help="Hard cap on answer requests")
    parser.add_argument("--answer-cost-soft-cap-usd", type=float, help="Stop future calls after reported cost cap; may overshoot by one request")
    parser.add_argument("--output", type=Path, help="Optional result JSON file")
    args = parser.parse_args()
    if args.output and args.env_file and args.output.resolve() == args.env_file.resolve():
        parser.error("--output must differ from --env-file")
    if args.output and args.dataset and args.output.resolve() == args.dataset.resolve():
        parser.error("--output must differ from --dataset")
    payload = download_official() if args.download_official else args.dataset.read_bytes()
    report = run(payload, max_conversations=args.max_conversations,
                 questions_per_conversation=args.questions_per_conversation or None,
                 top_k=args.top_k, answer_model=args.answer_model, env_file=args.env_file,
                 answer_max_tokens=args.answer_max_tokens,
                 answer_context_chars=args.answer_context_chars,
                 answer_request_budget=args.answer_request_budget,
                 answer_cost_soft_cap_usd=args.answer_cost_soft_cap_usd)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
