"""LoCoMo retrieval adapter tests use synthetic official-format records."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks" / "locomo_adapter.py"
SPEC = importlib.util.spec_from_file_location("locomo_adapter_test", SCRIPT)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def _sample() -> dict:
    return {
        "sample_id": "synthetic-1",
        "conversation": {
            "speaker_a": "Ada", "speaker_b": "Bea",
            "session_1_date_time": "1:56 pm on 8 May, 2023",
            "session_1": [
                {"speaker": "Ada", "dia_id": "D1:1", "text": "The telescope was green."},
                {"speaker": "Bea", "dia_id": "D1:2", "text": "Arbor observatory has the blue telescope."},
            ],
            "session_2_date_time": "2:00 pm on 9 May, 2023",
            "session_2": [{"speaker": "Ada", "dia_id": "D2:1", "text": "The gallery opens on Sunday."}],
        },
        "qa": [
            {"question": "Which observatory has the blue telescope?", "answer": "Arbor",
             "category": 1, "evidence": ["D1:2"]},
            {"question": "When does the gallery open?", "answer": "Sunday",
             "category": 2, "evidence": ["D2:1"]},
        ],
    }


def test_evidence_parser_expands_composites_without_repairing_typos():
    ids, malformed = adapter._evidence_ids(["D1:2; D2:1", "D3:04 D:4:5", "D"])
    assert ids == {"D1:2", "D2:1", "D3:04"}
    assert malformed == ["D:4:5", "D"]


def test_retrieval_evidence_metrics_are_not_answer_accuracy():
    sample = _sample()
    ids = {"c_blue": "D1:2", "c_green": "D1:1"}

    class Provider:
        def _search(self, query, **kwargs):
            assert kwargs["retrieval_mode"] == "fts"
            return [{"id": "c_green"}, {"id": "c_blue"}]

    row = adapter._score_question(Provider(), sample["qa"][0], ids, set(ids.values()), 2)
    assert row["recall_at_k"] == 1.0
    assert row["reciprocal_rank"] == .5
    assert row["retrieved_dialogue_ids"] == ["D1:1", "D1:2"]
    assert "answer_accuracy" not in row


def test_real_adapter_isolates_home_and_disables_semantic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    live = tmp_path / "live"
    live.mkdir()
    marker = live / "marker.txt"
    marker.write_text("untouched", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(live))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "1")
    raw = json.dumps([_sample()]).encode("utf-8")
    report = adapter.run(raw, max_conversations=1, questions_per_conversation=None, top_k=3)
    assert report["dataset_questions"] == 2
    assert report["evaluated_questions"] == 2
    assert report["samples"][0]["indexed_turns"] == 3
    assert report["answer_generation_scored"] is False
    assert report["retrieval_mode"] == "fts"
    assert report["metrics"]["evidence_scored_questions"] == 2
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert not (live / "memory-wiki").exists()
    assert os.environ["HERMES_HOME"] == str(live)
    assert os.environ["MEMORY_WIKI_SEMANTIC"] == "1"


def test_validation_rejects_duplicate_dialogue_and_bad_question():
    sample = _sample()
    sample["conversation"]["session_2"][0]["dia_id"] = "D1:2"
    with pytest.raises(ValueError, match="duplicate LoCoMo dialogue ID"):
        adapter._load_dataset(json.dumps([sample]).encode())
    sample = _sample()
    sample["qa"][0]["evidence"] = "D1:2"
    with pytest.raises(ValueError, match="invalid LoCoMo question"):
        adapter._load_dataset(json.dumps([sample]).encode())


def test_short_turn_is_reported_as_unindexed_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sample = _sample()
    sample["conversation"]["session_1"][1]["text"] = "Bye!"
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(live))
    report = adapter.run(json.dumps([sample]).encode(), questions_per_conversation=1)
    result = report["samples"][0]
    assert result["short_turns"] == 1
    assert result["skipped_dialogue_ids"] == ["D1:2"]
    assert result["questions"][0]["unresolved_gold_dialogue_ids"] == ["D1:2"]


def test_optional_reader_obeys_request_cap_without_live_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = tmp_path / "private.env"
    env.write_text("OPENROUTER_API_KEY=synthetic-key\n", encoding="utf-8")
    called = []

    def fake_answer(**kwargs):
        called.append(kwargs["question"])
        assert kwargs["context"]
        return "Arbor", {"prompt_tokens": 20, "completion_tokens": 2,
                         "total_tokens": 22, "cost": .00002, "context_chars": 100}, 4.0

    monkeypatch.setattr(adapter, "answer_openrouter", fake_answer)
    report = adapter.run(json.dumps([_sample()]).encode(), questions_per_conversation=None,
                         answer_model="test/model", env_file=env, answer_request_budget=1)
    assert len(called) == 1
    assert report["answer_generated"] == 1
    assert report["answer_skipped"] == 1
    assert report["answer_reported_cost"] == .00002
    assert report["samples"][0]["questions"][1]["answer_skipped_reason"] == "request_budget"
