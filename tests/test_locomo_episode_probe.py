"""The LoCoMo episode probe uses bounded production retrieval in isolation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks" / "locomo_episode_probe.py"


def test_one_synthetic_conversation(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("locomo_episode_probe_test", SCRIPT)
    assert spec and spec.loader
    probe = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = probe
    spec.loader.exec_module(probe)
    sample = {
        "sample_id": "synthetic-episode-1",
        "conversation": {
            "speaker_a": "Ada", "speaker_b": "Bea",
            "session_1_date_time": "1:56 pm on 8 May, 2023",
            "session_1": [
                {"speaker": "Ada", "dia_id": "D1:1", "text": "The telescope is green."},
                {"speaker": "Bea", "dia_id": "D1:2",
                 "text": "Aurora Observatory owns the blue telescope."},
            ],
        },
        "qa": [{"question": "Who owns the blue telescope?", "answer": "Aurora Observatory",
                "category": 2, "evidence": ["D1:2"]}],
    }
    dataset = tmp_path / "locomo.json"
    dataset.write_text(json.dumps([sample]), encoding="utf-8")
    report = probe.run(dataset, conversations=1, questions_per_conversation=1)
    assert report["sample_questions"] == 1
    assert report["retrieval_only"] is True
    assert report["overall"]["gold_capture"] == 1
    assert report["overall"]["fixed_any"] == 1.0
    assert report["overall"]["prompt_chars"] <= 800
