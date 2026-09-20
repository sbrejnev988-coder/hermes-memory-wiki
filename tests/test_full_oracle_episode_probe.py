"""The full paired probe must use the actual opt-in episode tool."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks" / "full_oracle_episode_probe.py"


def test_production_episode_probe_with_isolated_oracle(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("full_oracle_episode_probe_test", SCRIPT)
    assert spec and spec.loader
    probe = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = probe
    spec.loader.exec_module(probe)
    case = {
        "question_id": "synthetic-1", "question": "Who owns the blue telescope?",
        "question_type": "single-session-assistant", "answer_session_ids": ["s1"],
        "haystack_session_ids": ["s1"], "haystack_dates": ["2026/01/01 00:00:00"],
        "haystack_sessions": [[
            {"role": "user", "content": "Who owns the blue telescope?"},
            {"role": "assistant", "content": "Aurora Observatory owns the blue telescope.",
             "has_answer": True},
            {"role": "user", "content": "api_key=sk-test-123456789012345678901234"},
        ]],
    }
    dataset = tmp_path / "oracle.json"
    dataset.write_text(json.dumps([case]), encoding="utf-8")
    report = probe.run(dataset, limit=1, progress_every=0)
    overall = report["overall"]
    assert overall["questions"] == 1
    assert overall["gold_capture"] == 1
    assert overall["secret_rejects"] == 1
    assert overall["capture_rejects"] >= 1
    assert overall["assistant_excerpts"] >= 1
    assert overall["fixed_any"] == 1.0
    assert overall["prompt_chars"] <= 800


def test_evidence_metrics_exclude_unlabeled_abstention_cases(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("full_oracle_episode_probe_aggregate_test", SCRIPT)
    assert spec and spec.loader
    probe = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = probe
    spec.loader.exec_module(probe)
    template = {
        "turns": 1, "gold_turns": 1, "gold_capture": 1, "gold_claim_capture": 0,
        "episode_capture": 1, "capture_rejects": 0, "secret_rejects": 0,
        "write_guard_rejects": 0, "read_guard_rejects": 0, "ingest_errors": 0,
        "accepted_claim_writes": 0, "queued_claim_writes": 0,
        "baseline_hits": 0, "fixed_hits": 1, "supplement_hits": 1,
        "episodes_returned": 1, "assistant_excerpts": 1, "prompt_chars": 25,
        "baseline_any": False, "fixed_any": True, "supplement_any": True,
        "baseline_all": False, "fixed_all": True, "supplement_all": True,
        "claim_ms": 1.0, "episode_tool_ms": 2.0,
    }
    unlabeled = {**template, "gold_turns": 0, "gold_capture": 0, "fixed_hits": 0,
                 "supplement_hits": 0, "fixed_any": False, "supplement_any": False,
                 "baseline_all": True}
    result = probe._aggregate([template, unlabeled])
    assert result["questions"] == 2
    assert result["evidence_scored_questions"] == 1
    assert result["fixed_any"] == 1.0
    assert result["baseline_all"] == 0.0
