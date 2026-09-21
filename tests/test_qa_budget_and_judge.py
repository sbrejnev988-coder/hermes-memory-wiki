"""Synthetic, network-free checks for bounded public benchmark QA."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "benchmarks" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_hard_request_budget_and_cost_coverage() -> None:
    budget = _load("qa_reader", "qa_reader.py").AnswerBudget(2, .0001)
    budget.begin()
    budget.record({"cost": .00005})
    budget.begin()
    budget.record({"cost": .00006})
    assert budget.skip_reason() == "request_budget"
    assert budget.summary()["reported_cost_usd"] == .00011
    assert budget.summary()["cost_cap_is_hard"] is False
    missing = _load("qa_reader_missing", "qa_reader.py").AnswerBudget(2, .01)
    missing.begin()
    missing.record({"cost": None})
    assert missing.skip_reason() == "unreported_cost"
    assert missing.summary()["reported_cost_usd"] is None


def test_official_judge_parser_binds_exact_hypotheses(tmp_path: Path) -> None:
    judge = _load("official_longmemeval_judge", "official_longmemeval_judge.py")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({
        "dataset_sha256": "a" * 64, "answer_model": "reader/test", "evaluated_questions": 2,
        "questions": [
            {"question_id": "q1", "question_type": "single-session-user", "hypothesis": "Blue."},
            {"question_id": "q2_abs", "question_type": "multi-session", "hypothesis": "I don't know."},
        ],
    }), encoding="utf-8")
    output = tmp_path / "judge.jsonl"
    rows = [
        {"question_id": "q1", "hypothesis": "Blue.", "autoeval_label": {"model": "gpt-4o-2024-08-06", "label": True}},
        {"question_id": "q2_abs", "hypothesis": "I don't know.", "autoeval_label": {"model": "gpt-4o-2024-08-06", "label": False}},
    ]
    output.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    summary = judge.summarize(report, output)
    assert summary["qa_accuracy_on_judged"] == .5
    assert summary["qa_accuracy_full_run"] == .5
    assert summary["abstention_accuracy_on_judged"] == 0
    rows[0]["hypothesis"] = "Changed"
    output.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="edited hypothesis"):
        judge.summarize(report, output)
