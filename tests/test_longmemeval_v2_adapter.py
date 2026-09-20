"""Synthetic official-format checks for the isolated LongMemEval-V2 probe."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks" / "longmemeval_v2_adapter.py"
SPEC = importlib.util.spec_from_file_location("longmemeval_v2_adapter_test", SCRIPT)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def _question(*, image: str | None = None) -> dict:
    return {
        "id": "q0000001", "domain": "web", "environment": "testsite",
        "question_type": "static-environment", "question": "Where is the blue telescope?",
        "image": image, "answer": "observatory", "eval_function": "exact_match",
    }


def _trajectory(*, trajectory_id: str = "t0000001", domain: str = "web") -> dict:
    return {
        "id": trajectory_id, "domain": domain, "environment": "testsite",
        "goal": "Find the observatory", "outcome": "success", "start_url": "https://test.invalid",
        "states": [{
            "state_index": 0, "step": 0, "url": "https://test.invalid/observatory",
            "action": None, "thought": "Look for the blue telescope",
            "accessibility_tree": "The blue telescope is at the observatory entrance.",
            "screenshot": "screenshots/t0000001/0.png",
        }],
    }


def _dataset(root: Path, *, complete: bool = False) -> None:
    (root / "haystacks").mkdir(parents=True)
    (root / "questions.jsonl").write_text(json.dumps(_question()) + "\n", encoding="utf-8")
    ids = ["t0000001", *(f"t{i:07d}" for i in range(2, 101))]
    (root / "haystacks" / "lme_v2_small.json").write_text(
        json.dumps({"q0000001": ids}), encoding="utf-8")
    rows = [_trajectory(trajectory_id=tid) for tid in (ids if complete else ids[:1])]
    (root / "trajectories.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_official_v2_shape_and_image_filter(tmp_path: Path) -> None:
    _dataset(tmp_path)
    questions, haystack, meta = adapter.load_metadata(
        tmp_path, tier="small", domain="web", limit=1)
    assert len(questions) == 1 and len(haystack["q0000001"]) == 100
    assert meta["selected_image_questions"] == 0
    (tmp_path / "questions.jsonl").write_text(
        json.dumps(_question(image="question_screenshots/q.png")) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no V2 questions"):
        adapter.load_metadata(tmp_path, tier="small", domain="web", limit=1)
    selected, _, meta = adapter.load_metadata(
        tmp_path, tier="small", domain="web", limit=1, include_image_questions=True)
    assert selected[0]["image"] and meta["selected_image_questions"] == 1


def test_rejects_invalid_haystack_and_truncated_rows(tmp_path: Path) -> None:
    _dataset(tmp_path)
    hpath = tmp_path / "haystacks" / "lme_v2_small.json"
    hpath.write_text(json.dumps({"q0000001": ["t0000001", "t0000001"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="haystack trajectory"):
        adapter.load_metadata(tmp_path, tier="small", domain="web", limit=1)
    path = tmp_path / "truncated.jsonl"
    path.write_bytes((json.dumps(_trajectory()) + "\n" + '{"id":"unfinished"').encode())
    with pytest.raises(ValueError, match="incomplete JSONL"):
        list(adapter._jsonl(path))
    assert len(list(adapter._jsonl(path, allow_partial=True))) == 1


def test_official_metadata_checksum_is_enforced(tmp_path: Path) -> None:
    _dataset(tmp_path)
    qpath = tmp_path / "questions.jsonl"
    hpath = tmp_path / "haystacks" / "lme_v2_small.json"
    (tmp_path / "checksums.sha256").write_text(
        f"{adapter._sha256(qpath)}  questions.jsonl\n"
        f"{adapter._sha256(hpath)}  haystacks/lme_v2_small.json\n",
        encoding="utf-8",
    )
    adapter.load_metadata(tmp_path, tier="small", domain="web", limit=1)
    qpath.write_text(json.dumps(_question()) + "\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        adapter.load_metadata(tmp_path, tier="small", domain="web", limit=1)


def test_state_chunking_enforces_claim_size_and_counts_omitted() -> None:
    row = _trajectory()
    row["states"][0]["accessibility_tree"] = "x" * 30_000
    chunks, omitted = adapter._state_chunks(row, row["states"][0], 20_000)
    assert omitted == 10_000 and len(chunks) >= 3
    assert all(10 <= len(chunk) <= 1601 and "\n" not in chunk for chunk in chunks)
    assert "Trajectory goal" in chunks[0]


def test_partial_official_haystack_is_reported_not_scored_as_accuracy(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "public-data"
    _dataset(data)
    live = tmp_path / "live-hermes"
    live.mkdir()
    marker = live / "marker.txt"
    marker.write_text("untouched", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(live))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "1")
    result = adapter.run(data, tier="small", domain="web", limit=1, allow_partial=True)
    assert result["official_haystack_trajectories"] == 100
    assert result["indexed_haystack_trajectories"] == 1
    assert result["missing_haystack_trajectories"] == 99
    assert result["states_indexed"] == 1 and result["chunks_indexed"] >= 1
    assert result["evaluated_questions"] == 1
    assert result["official_qa_score"] is None and result["gold_evidence_recall"] is None
    assert result["questions_with_hits"] == 1
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert not (live / "memory-wiki").exists()
    assert os.environ["HERMES_HOME"] == str(live)
    assert os.environ["MEMORY_WIKI_SEMANTIC"] == "1"
    assert Path(result["isolated_hermes_home"]).is_dir()
    with pytest.raises(ValueError, match="incomplete"):
        adapter.run(data, tier="small", domain="web", limit=1)
