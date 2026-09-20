"""The synthetic quality suite catches retrieval and scope regressions."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


BENCHMARK = Path(__file__).resolve().parents[1] / "benchmarks" / "quality_eval.py"
ANSWER_BENCHMARK = BENCHMARK.with_name("answer_eval.py")


def test_quality_fixture_recall_and_access_boundaries():
    spec = importlib.util.spec_from_file_location("memory_wiki_quality_benchmark_test", BENCHMARK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = module.run()
    assert report["fixture_claims"] == 14
    assert report["fixture_cases"] == 9
    for score in report["scores"]:
        assert score["recall_at_5"] >= 0.8
        assert score["all_required_at_5"] >= 0.7
        assert score["forbidden_hits"] == 0
        assert score["scope_leaks"] == 0


def test_answer_rubric_rejects_invented_verification(monkeypatch):
    monkeypatch.syspath_prepend(str(BENCHMARK.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_answer_benchmark_test", ANSWER_BENCHMARK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = json.loads((BENCHMARK.parent / "fixtures" / "quality_cases.json").read_text(encoding="utf-8"))
    case = next(item for item in fixture["cases"] if item["name"] == "contradiction-evidence")
    assert module._score_answer(case, "The current policy is thirty days; seven days is an unverified note.")
    assert not module._score_answer(case, "The current verified policy is thirty days; seven days is an unverified note.")
