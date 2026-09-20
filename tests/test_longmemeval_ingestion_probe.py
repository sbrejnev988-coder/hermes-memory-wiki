"""Dry-run ingestion probe maps decisions to official turn IDs without writes."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.longmemeval_ingestion_probe import probe


def test_probe_compares_raw_turn_sync_and_session_end_without_content(tmp_path: Path) -> None:
    case = {
        "question_id": "sample-1", "question_type": "single-session-user",
        "question": "Which port is used for backups?", "answer": "5432",
        "question_date": "2024/02/02 12:00",
        "haystack_session_ids": ["session-a"],
        "haystack_dates": ["2024/02/01 12:00"],
        "haystack_sessions": [[
            {"role": "user", "content": "Remember that the server uses port 5432 for backups.",
             "has_answer": True},
            {"role": "assistant", "content": "I can help with that later.",
             "has_answer": False},
        ]],
        "answer_session_ids": ["session-a"],
    }
    dataset = tmp_path / "oracle.json"
    dataset.write_text(json.dumps([case]), encoding="utf-8")
    result = probe(dataset, limit=1, include_turns=True)
    assert result["evaluated_questions"] == 1
    assert result["raw_whole_turn"]["gold:user:accept"] == 1
    turns = result["turns"]
    assert {turn["turn_id"] for turn in turns} == {"session-a:0", "session-a:1"}
    assert turns[0]["gold"] is True
    assert turns[0]["production_action"] in {"accepted", "queued", "no_candidate"}
    assert turns[0]["with_session_end_action"] in {"accepted", "queued", "no_candidate"}
    assert "server uses port 5432" not in json.dumps(result)
    assert not (tmp_path / "memory-wiki").exists()
