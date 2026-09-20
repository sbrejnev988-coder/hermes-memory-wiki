"""Official-format LongMemEval adapter tests; all data is synthetic."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks" / "longmemeval_adapter.py"
SPEC = importlib.util.spec_from_file_location("longmemeval_adapter_test", SCRIPT)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def _case() -> dict:
    return {
        "question_id": "q1", "question_type": "single-session-user",
        "question": "Which observatory has the blue telescope?", "answer": "Arbor Observatory",
        "question_date": "2024/02/03 (Sat) 12:00",
        # Oracle-style unsorted sessions: adapter must ingest the older one first.
        "haystack_session_ids": ["new", "old"],
        "haystack_dates": ["2024/02/02 (Fri) 12:00", "2024/02/01 (Thu) 12:00"],
        "haystack_sessions": [
            [{"role": "user", "content": "Arbor Observatory has the blue telescope.", "has_answer": True}],
            [{"role": "user", "content": "The old telescope was green.", "has_answer": False}],
        ],
        "answer_session_ids": ["new"],
    }


def test_official_session_order_and_evidence_scoring() -> None:
    case = _case()

    class Provider:
        def __init__(self) -> None:
            self.writes = []

        def _add_claim(self, content, **kwargs):
            self.writes.append((content, kwargs))
            return "c_old" if "old" in content else "c_new"

        def _search(self, query, **kwargs):
            assert query == case["question"]
            assert kwargs["retrieval_mode"] == "fts"
            return [{"id": "c_new"}]

    provider = Provider()
    result = adapter._evaluate_case(provider, case, 5, "Arbor Observatory")
    assert [content for content, _ in provider.writes] == [
        "The old telescope was green.", "Arbor Observatory has the blue telescope.",
    ]
    assert provider.writes[0][1]["event_at"] < provider.writes[1][1]["event_at"]
    assert result["retrieved_evidence_ids"] == [["new:0"]]
    assert result["session_recall_all"] is True
    assert result["turn_recall_all"] is True
    assert result["answer_proxy_exact_match"] is True


def test_load_cases_caps_and_rejects_invalid_shape(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text(json.dumps([_case(), _case()]), encoding="utf-8")
    cases, total = adapter.load_cases(path, 1)
    assert len(cases) == 1 and total == 2
    with pytest.raises(ValueError, match="positive cap"):
        adapter.load_cases(path, 0)
    bad = _case()
    bad["haystack_dates"] = []
    path.write_text(json.dumps([bad]), encoding="utf-8")
    with pytest.raises(ValueError, match="mismatched"):
        adapter.load_cases(path, 1)


def test_json_array_streams_across_chunks(tmp_path: Path) -> None:
    path = tmp_path / "large.json"
    large = _case()
    large["haystack_sessions"][0][0]["content"] = "A" * 140_000
    path.write_text(json.dumps([large, _case()]), encoding="utf-8")
    cases, total = adapter.load_cases(path, 1)
    assert total == 2
    assert len(cases) == 1
    assert len(cases[0]["haystack_sessions"][0][0]["content"]) == 140_000


def test_ingest_exception_is_reported_without_aborting_question() -> None:
    case = _case()

    class Provider:
        def _add_claim(self, content, **kwargs):
            if "blue telescope" in content:
                raise RuntimeError("hermes_secret_core_unavailable: synthetic")
            return "c_old"

        def _search(self, query, **kwargs):
            return [{"id": "c_old"}]

    result = adapter._evaluate_case(Provider(), case, 5, None)
    assert result["skipped_turns"] == 1
    assert result["gold_turn_ids_skipped"] == ["new:0"]
    assert result["ingest_error_counts"] == {"hermes_secret_core_unavailable": 1}
    assert result["session_recall_all"] is False


def test_semantic_collection_cleanup_only_targets_generated_physical_name() -> None:
    class QdrantModule:
        QDRANT_ALIAS_MODE = "physical"

        def __init__(self) -> None:
            self.names = {"memory_wiki_lme_token_0000_abcd", "active_user_collection"}
            self.calls = []

        def _qdrant_req(self, method, path, **kwargs):
            self.calls.append((method, path))
            if method == "GET" and path == "/collections":
                return {"status": "ok", "result": {"collections": [{"name": name} for name in self.names]}}
            if method == "DELETE":
                self.names.remove(path.rsplit("/", 1)[-1])
                return {"status": "ok", "result": True}
            raise AssertionError((method, path))

    module = QdrantModule()
    assert adapter._remove_isolated_collection(module, "memory_wiki_lme_token_0000_abcd", "memory_wiki_lme_token_0000")
    assert module.names == {"active_user_collection"}
    assert module.calls == [
        ("GET", "/collections"),
        ("DELETE", "/collections/memory_wiki_lme_token_0000_abcd"),
        ("GET", "/collections"),
    ]
    with pytest.raises(RuntimeError, match="Refusing"):
        adapter._remove_isolated_collection(module, "active_user_collection", "memory_wiki_lme_token_0000")


def test_bounded_openrouter_answer_uses_only_retrieved_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "Arbor Observatory"}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 3, "total_tokens": 45, "cost": 0.00001},
            }).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        assert timeout == 45
        return Response()

    monkeypatch.setattr(adapter.urllib.request, "urlopen", fake_urlopen)
    answer, usage, latency = adapter._answer_openrouter(
        _case(), [("c_1", "Arbor Observatory has the blue telescope."), ("c_2", "x" * 5000)],
        api_key="synthetic-key", model="test/model", max_tokens=96, context_chars=256,
    )
    assert answer == "Arbor Observatory"
    assert usage["prompt_tokens"] == 42 and usage["cost"] == 0.00001
    assert usage["context_chars"] <= 256
    assert latency >= 0
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["payload"]["max_tokens"] == 96
    assert "Arbor Observatory" in captured["payload"]["messages"][1]["content"]


def test_answer_model_requires_explicit_credentials(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([_case()]), encoding="utf-8")
    with pytest.raises(ValueError, match="requires --env-file"):
        adapter.run(dataset, limit=1, answer_model="test/model")


def test_real_run_uses_temporary_profile_and_restores_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([_case()]), encoding="utf-8")
    live = tmp_path / "live-hermes"
    live.mkdir()
    marker = live / "marker.txt"
    marker.write_text("untouched", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(live))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "1")
    result = adapter.run(dataset, limit=1, top_k=5)
    assert result["evaluated_questions"] == 1
    assert result["retrieval_mode"] == "fts"
    assert result["questions"][0]["accepted_turns"] + result["questions"][0]["queued_turns"] >= 1
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert not (live / "memory-wiki").exists()
    assert os.environ["HERMES_HOME"] == str(live)
    assert os.environ["MEMORY_WIKI_SEMANTIC"] == "1"
