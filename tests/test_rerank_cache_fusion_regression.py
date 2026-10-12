"""Numerical UNIT: authored rank inputs, never fake successful provider HTTP.

The cache stores model ordinals by candidate set, not the incidental local
order. Current local RRF arithmetic stays diagnostic; successful ordinals win.
"""
from __future__ import annotations

from copy import deepcopy

import pytest
import memory_wiki as mw


def rows():
    return [{"id": cid, "score": score, "score_parts": {"rrf": score}}
            for cid, score in (("A", 3.0), ("B", 2.0), ("C", 1.0))]


def fuse(original, prefix, ranks, weight=.25):
    settings = {"RERANK_MIN_CANDIDATES": 3, "RERANK_WEIGHT_SEMANTIC": weight}
    return mw._fuse_rerank_order(original, prefix, ranks, query_mode="semantic",
                                settings=settings, order_key="a" * 64)


def test_rerank_cache_preserves_current_rrf_diagnostics_not_rank_regression():
    original = rows()
    ranks = [("A", .9, 1), ("B", .8, 2), ("C", .7, 3)]
    saved = deepcopy(original)
    forward = fuse(original, original, ranks)
    reverse_input = list(reversed(original))
    reverse = fuse(reverse_input, reverse_input, ranks)
    assert [item["id"] for item in forward] == ["A", "B", "C"]
    assert [item["id"] for item in reverse] == ["A", "B", "C"]
    assert reverse[0]["rerank_fusion_score"] == pytest.approx(.75 / (mw.RRF_K + 3) + .25 / (mw.RRF_K + 1))
    assert forward[0]["rerank_fusion_score"] != reverse[0]["rerank_fusion_score"]
    assert original == saved
    assert [item["score"] for item in reverse] == [3.0, 2.0, 1.0]
    assert [item["score_parts"] for item in reverse] == [item["score_parts"] for item in original]


def test_zero_weight_is_explicit_local_only_and_equal_scores_keep_ordinals():
    original = rows()
    ranks = [("C", .5, 1), ("B", .5, 2), ("A", .5, 3)]
    assert fuse(original, original, ranks, 0.0) == original
    assert [row["id"] for row in fuse(original, original, ranks, .01)] == ["C", "B", "A"]
    assert [row["id"] for row in fuse(original, original, ranks, 1.0)] == ["C", "B", "A"]


def test_guard_gaps_partial_topk_and_unranked_tail_keep_bounded_slots():
    original = rows() + [{"id": "D", "score": .5}, {"id": "tail", "score": .1}]
    gap = {"id": "guard-denied", "status": "retired"}
    original.insert(1, gap)
    prefix = [row for row in original if row["id"] not in {"guard-denied", "tail"}]
    ranks = [("C", .9, 1), ("B", .8, 2), ("A", .7, 3)]
    output = fuse(original, prefix, ranks)
    assert [row["id"] for row in output] == ["C", "guard-denied", "B", "A", "D", "tail"]
    assert output[1] is gap and output[-1] is original[-1]
    assert "rerank_rank" not in output[-2] and "_rerank_order" not in output[-2]
    assert [row["rerank_rank"] for row in output if "rerank_rank" in row] == [1, 2, 3]


@pytest.mark.parametrize("ranks", [
    [("A", .9, 1), ("A", .8, 2), ("C", .7, 3)],
    [("foreign:A", .9, 1), ("B", .8, 2), ("C", .7, 3)],
    [("A", float("nan"), 1), ("B", .8, 2), ("C", .7, 3)],
    [("A", float("inf"), 1), ("B", .8, 2), ("C", .7, 3)],
    [("A", True, 1), ("B", .8, 2), ("C", .7, 3)],
    [("A", .9, True), ("B", .8, 2), ("C", .7, 3)],
    [("A", .9, 1), ("B", .8, 1), ("C", .7, 3)],
    [("A", .9, 1), ("B", .8, 2), ("C", .7, 4)],
    [("A", .9, 1), ("B", .8, 2)],
    [("A", .9, 1), ("B", .8, 2), ("C",)],
], ids=["duplicate-id", "foreign-id", "nan", "infinite", "bool-score", "bool-rank",
        "duplicate-rank", "rank-gap", "below-threshold", "malformed-item"])
def test_malformed_or_foreign_rank_inputs_refuse_without_mutating_local_rows(ranks):
    original = rows()
    before = deepcopy(original)
    with pytest.raises(ValueError):
        fuse(original, original, ranks)
    assert original == before


def test_duplicate_candidate_ids_are_not_a_federation_or_dedup_authority():
    original = rows()
    original[2]["id"] = "A"
    with pytest.raises(ValueError, match="identity"):
        fuse(original, original, [("A", .9, 1), ("B", .8, 2), ("C", .7, 3)])


def test_outer_reordering_is_claim_cohort_only_after_authoritative_filtering():
    recall = mw._recall_orchestrator
    # Same textual ID in another source/profile is not a same-cohort candidate.
    ordered = [
        {"kind": "observation", "id": "A", "_rrf": 3.0},
        {"kind": "claim", "id": "B", "_rrf": 2.0},
        {"kind": "claim", "id": "foreign:A", "_rrf": 1.8},
        {"kind": "claim", "id": "A", "_rrf": 1.5},
        {"kind": "episode", "id": "B", "_rrf": 1.0},
    ]
    before = deepcopy(ordered)
    assert recall._preserve_claim_rerank_order(ordered, []) == before
    result = recall._preserve_claim_rerank_order(ordered, ["A", "revoked-C", "B"])
    assert [(r["kind"], r["id"]) for r in result] == [
        ("observation", "A"), ("claim", "A"), ("claim", "foreign:A"), ("claim", "B"), ("episode", "B")]
    assert sorted((r["kind"], r["id"], r["_rrf"]) for r in result) == sorted((r["kind"], r["id"], r["_rrf"]) for r in before)
    assert ordered == before


def test_outer_rrf_formula_and_deterministic_tie_policy_are_unchanged():
    recall = mw._recall_orchestrator
    candidates = {}
    for cid in ("B", "A"):
        recall._rrf_add(candidates, kind="claim", source_id=cid, rank=1, item={"kind": "claim"})
    recall._rrf_add(candidates, kind="claim", source_id="A", rank=3, item={"kind": "claim"})
    assert candidates[("claim", "A")]["_rrf"] == pytest.approx(1.0 / 61.0 + 1.0 / 63.0)
    tie = sorted([{"kind": "claim", "id": cid, "_rrf": 1.0, "_first_rank": 1} for cid in ("B", "A")],
                 key=lambda item: (-float(item["_rrf"]), recall._SOURCE_PRIORITY[item["kind"]], item["_first_rank"], item["id"]))
    assert [item["id"] for item in recall._preserve_claim_rerank_order(tie, [])] == ["A", "B"]
