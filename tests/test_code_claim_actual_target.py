"""Exact generic fingerprint result must retain stored graph obligations."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "code_actual_target_peer", Path(__file__).with_name("test_code_claim_identity_consumers.py")
)
assert _SPEC and _SPEC.loader
peer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(peer)
old, case = peer.old, peer.case


def test_fingerprint_actual_graph_target_rejected_after_hash_edit(case, monkeypatch):
    module, p, _graph = case
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    path, symbol = "src/actual-target.py", "actual.chunk"
    text = (f"Code semantic chunk in repository {old.REPO}. "
            f"File {path} lines 1-3; symbol verified.worker.\n{old.TEXT}")
    request = {**old.direct_args(path, symbol, old.H[:32]), "claim": text}
    cid = p._code_claim_add(request)["id"]
    c = p._connect()
    h0 = c.execute("SELECT hash FROM claims WHERE id=?", (cid,)).fetchone()[0]
    ordinary_fingerprints = [r[0] for r in c.execute("SELECT fingerprint FROM claim_write_fingerprints WHERE claim_id=? ORDER BY fingerprint", (cid,))]
    assert ordinary_fingerprints
    materialized = module._ingest_code_graph_event(p, old.event("actual-target-materialize", [(path, symbol)]))
    assert materialized["embedding"]["failed"] == 0 and old.linked(p, symbol) == cid
    assert c.execute("SELECT claim_type FROM code_claim_metadata WHERE claim_id=?", (cid,)).fetchone()[0] == "code_graph_chunk"
    p._update_claim(dict(claim_id=cid, claim=text + " The owner approved an updated deterministic explanation."))
    before = dict(c.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone())
    metadata = dict(c.execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (cid,)).fetchone())
    assert before["hash"] != h0 and c.execute("SELECT 1 FROM claims WHERE hash=?", (h0,)).fetchone() is None
    assert all(c.execute("SELECT claim_id FROM claim_write_fingerprints WHERE fingerprint=?", (f,)).fetchone()[0] == cid for f in ordinary_fingerprints)
    denied = False
    try:
        p._code_claim_add(request)
    except PermissionError as exc:
        assert str(exc) == "protected_graph_claim_type_change"
        denied = True
    old.observe(p, "actual-fingerprint-target", denied=denied)
    assert denied, "L2-R2 actual fingerprint result downgraded protected graph target"
    assert dict(c.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone()) == before
    assert dict(c.execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (cid,)).fetchone()) == metadata
    assert old.linked(p, symbol) == cid
    # A legal ordinary fingerprint replay remains a no-op on its current ID,
    # even after an ordinary edit; this fix is not a generic dedup rewrite.
    ordinary_request = old.direct_args("src/ordinary-target.py", "ordinary.target", "release")
    ordinary = p._code_claim_add(ordinary_request)["id"]
    p._update_claim(dict(claim_id=ordinary, claim=old.TEXT + " This ordinary note was updated by its owner."))
    ordinary_before = dict(c.execute("SELECT * FROM claims WHERE id=?", (ordinary,)).fetchone())
    replayed = p._code_claim_add(ordinary_request)
    assert replayed["id"] == ordinary and replayed["deduplicated"] is True
    assert dict(c.execute("SELECT * FROM claims WHERE id=?", (ordinary,)).fetchone()) == ordinary_before
    assert p._transaction_quarantine is None
