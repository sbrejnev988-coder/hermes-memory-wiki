from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "recall_planner.py"
spec = importlib.util.spec_from_file_location("memory_wiki_recall_planner_test", MODULE)
assert spec and spec.loader
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def test_fast_mode_is_bounded_and_exact():
    assert planner.expand_memory_queries("  Where is the amber telescope?  ", "fast") == [
        "Where is the amber telescope"
    ]


def test_auto_removes_recall_boilerplate_without_inventing_terms():
    rows = planner.expand_memory_queries("Do you remember what I said about the Atlas gateway port?", "auto")
    assert rows[0] == "Do you remember what I said about the Atlas gateway port"
    assert "what I said about the Atlas gateway port" in rows or "the Atlas gateway port" in rows
    assert all("Atlas" in row or row == rows[0] for row in rows)


def test_deep_splits_multihop_english_and_russian_queries():
    english = planner.expand_memory_queries(
        "Which camera did I buy and what lens did I later choose?", "deep"
    )
    russian = planner.expand_memory_queries(
        "Какую камеру я купил и какой объектив потом выбрал?", "deep"
    )
    assert any("camera" in row.casefold() and "lens" not in row.casefold() for row in english[1:])
    assert any("lens" in row.casefold() and "camera" not in row.casefold() for row in english[1:])
    assert any("камер" in row.casefold() and "объектив" not in row.casefold() for row in russian[1:])
    assert any("объектив" in row.casefold() and "камер" not in row.casefold() for row in russian[1:])


def test_intent_exposes_temporal_current_negative_and_preference_signals():
    current = planner.classify_memory_intent("What is the latest Atlas endpoint now?")
    absent = planner.classify_memory_intent("I never said that I moved to Berlin, did I?")
    preference = planner.classify_memory_intent("Что я предпочитаю для утренней тренировки?")
    assert current["temporal"] and current["current_state"] and current["deep_recommended"]
    assert absent["negative_premise"] and absent["deep_recommended"]
    assert preference["primary"] == "preference"


def test_expansion_has_hard_caps_and_deduplicates():
    query = "alpha and alpha and beta and gamma and delta and epsilon and zeta and eta and theta"
    rows = planner.expand_memory_queries(query, "deep", max_queries=4)
    assert len(rows) == 4
    assert len({row.casefold() for row in rows}) == len(rows)
