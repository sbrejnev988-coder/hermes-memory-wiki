"""Actual SOURCE consumer compositions; reuse unchanged shipped fixtures."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "code_identity_consumer_peer", Path(__file__).with_name("test_code_claim_identity_review.py")
)
assert _SPEC and _SPEC.loader
review = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(review)
old, case = review.old, review.case


def public_results(p, symbol="acl.worker"):
    return [json.loads(p.handle_tool_call(name, args)) for name, args in (
        ("memory_wiki_code_claim_query", dict(repository_id=old.REPO, limit=5)),
        ("memory_wiki_symbol_history", dict(repository_id=old.REPO, symbol_id=symbol, limit=5)),
        ("memory_wiki_repository_context", dict(repository_id=old.REPO, limit=5)),
    )]


def test_S1_public_projection_never_discloses_private_scan_counts(case):
    _module, p, _graph = case
    empty = public_results(p)
    foreign = p._code_claim_add(old.direct_args("src/acl-foreign.py", "acl.worker"))["id"]
    # Authored historical foreign partition, not an authority override. Keep
    # its genuine code identity and row physically present throughout the read.
    with p._claim_transaction() as c:
        c.execute("UPDATE claims SET visibility_scope='private',origin_bot_id='foreign-bot',origin_session_id='foreign-session' WHERE id=?", (foreign,))
    denied = public_results(p)
    old.observe(p, "S1-public-private-counts", empty=empty, foreign=denied)
    assert all("selection" not in r for r in denied), "S1 pre-ACL scan metadata crossed public projection"
    assert denied == empty
    own = p._code_claim_add(old.direct_args("src/acl-own.py", "acl.worker"))["id"]
    allowed = public_results(p)
    assert review.ids(allowed) == [[own]] * 3
    assert all("selection" not in r for r in allowed)
    assert old.status(p, foreign) == "active" and p._transaction_quarantine is None


def test_S2_stored_graph_kind_cannot_be_downgraded_for_revival(case, monkeypatch):
    module, p, _graph = case
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    pairs = [("src/type-manual.py", "type.manual"), ("src/type-erased.py", "type.erased")]
    module._ingest_code_graph_event(p, old.event("consumer-graph", pairs))
    c = p._connect()
    manual, erased = [old.linked(p, s) for _, s in pairs]
    texts = {cid: c.execute("SELECT claim FROM claims WHERE id=?", (cid,)).fetchone()[0] for cid in (manual, erased)}
    p._archive_claim_ids([manual], reason="manual consumer hold")
    removal = p._set_status_by_text(texts[erased], status="archived", reason="consumer privacy", erase_memory_events=True)
    assert removal["privacy_intent_durable"] and erased in removal["claim_ids"]
    for cid, (path, symbol) in zip((manual, erased), pairs):
        before = dict(c.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone())
        metadata = dict(c.execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (cid,)).fetchone())
        for kind in (None, "code_claim", "annotation", "patch_outcome"):
            request = {**old.direct_args(path, symbol, old.H[:32]), "claim": texts[cid]}
            if kind is not None:
                request["claim_type"] = kind
            denied = False
            try:
                p._code_claim_add(request)
            except PermissionError as exc:
                assert str(exc) == "protected_graph_claim_type_change"
                denied = True
            old.observe(p, "S2-alternate-type", denied=denied, kind=kind)
            assert denied, "S2 caller type revived protected stored graph identity"
            assert dict(c.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone()) == before
            assert dict(c.execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (cid,)).fetchone()) == metadata
    # The protected producer contract must not ban ordinary lawful re-add.
    request = old.direct_args("src/ordinary.py", "ordinary.worker", "release")
    ordinary = p._code_claim_add(request)["id"]
    p._archive_claim_ids([ordinary], reason="ordinary reversible retirement")
    assert p._code_claim_add(request)["id"] == ordinary
    assert old.status(p, ordinary) == "active" and p._transaction_quarantine is None


def test_L4_durable_namespace_survives_source_and_text_mutations(case):
    module, p, _graph = case
    patch_id = "consumer-boundary-patch"
    cid = p._patch_outcome_add(dict(repository_id=old.REPO, patch_id=patch_id,
        outcome="verified service procedure applied", changed_files=[old.PATH_B],
        changed_symbols=[old.SYMBOL_B], source_event_id="consumer-patch-event"))["id"]
    c = p._connect()
    metadata = dict(c.execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (cid,)).fetchone())
    mutations = (
        lambda: p._pin_claim(cid),
        lambda: p._update_claim(dict(claim_id=cid, salience=.83)),
        lambda: p._add_evidence(cid, "Independent owner-reviewed supporting evidence.", untrusted_model=True),
        lambda: p._update_claim(dict(claim_id=cid, claim="The verified boundary patch preserves reliable revision history and deterministic transaction ownership after an approved textual correction.")),
    )
    for mutate in mutations:
        mutate()
        row = c.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone()
        assert str(row["source"]).startswith("model_tool:") and row["verification_status"] == "unverified"
        results = review.api_rows(p, symbol=old.SYMBOL_B)
        old.observe(p, "L4-source-mutation", projections=review.ids(results))
        assert review.ids(results) == [[cid]] * 3, "L4 mutable testimony displaced durable patch namespace"
        assert dict(c.execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (cid,)).fetchone()) == metadata
        assert row["hash"] == module.sha("\0".join(("patch_outcome", old.REPO, patch_id, row["normalized_claim"].lower())))
    invalidated = p._invalidate_revision(dict(repository_id=old.REPO, file_path=old.PATH_B, symbol_id=old.SYMBOL_B))
    assert invalidated["ids"] == [cid] and old.status(p, cid) == "archived"
    assert p._symbol_history(dict(repository_id=old.REPO, symbol_id=old.SYMBOL_B))["history"][0]["id"] == cid
    assert p._transaction_quarantine is None
