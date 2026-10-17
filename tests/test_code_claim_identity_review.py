"""CSL1 review corrections: real SOURCE writer/read compositions, not native SPI.

Reuse the unchanged shipped CSL1/atomicity fixtures, including the exact373
legacy writer. SQL-authored crowding/foreign rows are explicitly synthetic
historical data; no SDK, trust, owner or quality stand-ins are supplied.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "code_identity_review_peer", Path(__file__).with_name("test_code_claim_identity.py")
)
assert _SPEC and _SPEC.loader
old = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(old)
case = old.case
REPO, TEXT, H = old.REPO, old.TEXT, old.H
PATH, SYMBOL = old.PATH_B, old.SYMBOL_B


def api_rows(p, *, repo=REPO, path=PATH, symbol="limit.worker", limit=1):
    return (
        p._code_claim_query(dict(repository_id=repo, file_path=path, symbol_id=symbol, limit=limit)),
        p._symbol_history(dict(repository_id=repo, symbol_id=symbol, limit=limit)),
        p._repository_context(dict(repository_id=repo, limit=limit)),
    )


def ids(results):
    return [[row["id"] for row in r.get("claims", r.get("history", []))] for r in results]


def args(path, symbol, revision="release", text=TEXT, **extra):
    return {**old.direct_args(path, symbol, revision), "claim": text, **extra}


def test_L1_mixed_prefix_before_limit_and_bounded_no_eligible(case):
    module, p, _graph = case
    unknown = old.legacy_write(module, p, args(PATH + ".legacy.py", "limit.worker"))["id"]
    healthy = p._code_claim_add(args(PATH, "limit.worker"))["id"]
    with p._claim_transaction() as c:
        c.execute("UPDATE claims SET updated_at=10,salience=.5 WHERE id=?", (healthy,))
        c.execute("UPDATE claims SET updated_at=20,salience=.99 WHERE id=?", (unknown,))
    results = api_rows(p)
    old.observe(p, "L1-mixed-prefix", projections=ids(results))
    assert ids(results) == [[healthy]] * 3, "L1 eligible tail lost after identity filter LIMIT"
    assert all(r["selection"]["scanned"] == 2 and r["selection"]["result_limit"] == 1 for r in results)
    assert all(not k.startswith("_code_identity_") for r in results for row in r.get("claims", r.get("history", [])) for k in row)

    # Synthetic historical crowding: reproduce the genuine old slicing/hash
    # contract in bulk, without 199 unrelated rendering/postcommit operations.
    c = p._connect()
    template = dict(c.execute("SELECT * FROM claims WHERE id=?", (unknown,)).fetchone())
    metadata = dict(c.execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (unknown,)).fetchone())
    columns = [r[1] for r in c.execute("PRAGMA table_xinfo(claims)") if r[6] == 0]
    with p._claim_transaction(c):
        for index in range(199):
            full = dict(repository_id=REPO, file_path=PATH + f".legacy.{index}.py", symbol_id="limit.worker", symbol_revision="release")
            scoped = "\0".join(("code_claim", full["repository_id"], full["file_path"], full["symbol_id"], full["symbol_revision"]))
            digest = module.sha(scoped + "\0" + template["normalized_claim"].lower())
            row = {**template, "id": "c_" + digest[:12], "hash": digest}
            c.execute("INSERT INTO claims(" + ",".join(columns) + ") VALUES(" + ",".join("?" for _ in columns) + ")", [row[k] for k in columns])
            c.execute("INSERT INTO code_claim_metadata(" + ",".join(metadata) + ") VALUES(" + ",".join("?" for _ in metadata) + ")",
                      [row["id"] if k == "claim_id" else metadata[k] for k in metadata])
    exhausted = api_rows(p)
    assert ids(exhausted) == [[], [], []]
    assert all(r["selection"]["scanned"] == r["selection"]["scan_limit"] == 200 and r["selection"]["scan_limit_reached"] for r in exhausted)
    assert old.status(p, healthy) == "active"  # Tail retained, not silently deleted.

    no_repo = "repo-code-no-eligible"
    old.legacy_write(module, p, args(PATH + ".only.legacy.py", "limit.worker", repository_id=no_repo))
    empty = api_rows(p, repo=no_repo)
    assert ids(empty) == [[], [], []]
    assert all(r["selection"]["scanned"] == 1 and not r["selection"]["scan_limit_reached"] for r in empty)
    assert p._transaction_quarantine is None


def test_L1_refill_keeps_original_public_disclosure_epoch(case, monkeypatch):
    module, p, _graph = case
    old.legacy_write(module, p, args(PATH + ".legacy.py", "epoch.worker"))
    healthy = p._code_claim_add(args(PATH, "epoch.worker"))["id"]
    with p._claim_transaction() as c:
        c.execute("UPDATE claims SET updated_at=10 WHERE id=?", (healthy,))
        c.execute("UPDATE claims SET updated_at=20 WHERE id<>?", (healthy,))
    request = dict(repository_id=REPO, file_path=PATH, symbol_id="epoch.worker", limit=1)
    positive = json.loads(p.handle_tool_call("memory_wiki_code_claim_query", request))
    assert [r["id"] for r in positive["claims"]] == [healthy], positive
    resolve = p._code_claim_metadata_identity
    fired = []
    def revoke_during_scan(conn, row):
        if not fired:
            fired.append(True)
            with p._claim_transaction() as c:
                c.execute("UPDATE claims SET status='archived' WHERE id=?", (healthy,))
        return resolve(conn, row)
    # Test-only callback at eligibility, not an authority/quality override.
    monkeypatch.setattr(p, "_code_claim_metadata_identity", revoke_during_scan)
    denied = json.loads(p.handle_tool_call("memory_wiki_code_claim_query", request))
    assert fired and not denied.get("claims"), denied
    assert denied.get("disclosure_status") == "withheld", denied
    assert old.status(p, healthy) == "archived" and p._transaction_quarantine is None


def test_L2_fresh_delete_readd_and_hash_return(case, monkeypatch):
    module, p, _graph = case
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    path, symbol = "src/return.py", "return.chunk"
    first = old.event("return-first", [(path, symbol)])
    module._ingest_code_graph_event(p, first)
    cid = old.linked(p, symbol)
    canonical = p._connect().execute("SELECT hash FROM claims WHERE id=?", (cid,)).fetchone()[0]
    removed = module._ingest_code_graph_event(p, old.event("return-delete", mode="delta", deleted=[path]))
    assert old.status(p, cid) == "archived" and removed["invalidated_claims"] == 1
    returned = module._ingest_code_graph_event(p, old.event("return-fresh", [(path, symbol)], mode="delta"))
    old.observe(p, "L2-lawful-return", returned=returned)
    assert returned["embedding"]["created"] == 1 and returned["embedding"]["failed"] == 0, "L2 fresh authoritative generation cannot return archived H"
    assert old.linked(p, symbol) == cid and old.status(p, cid) == "active"
    assert p._connect().execute("SELECT hash FROM claims WHERE id=?", (cid,)).fetchone()[0] == canonical

    changed = old.event("return-H2", [(path, symbol)])
    changed_text = TEXT + " The alternate reviewed implementation uses a distinct deterministic algorithm."
    changed_hash = hashlib.sha256(changed_text.encode()).hexdigest()
    changed["files"][0]["file_hash"] = changed_hash
    changed["chunks"][0].update(chunk_text=changed_text, embedding_text=changed_text, content_hash=changed_hash)
    module._ingest_code_graph_event(p, changed)
    h2 = old.linked(p, symbol)
    assert h2 != cid and old.status(p, cid) == "archived"
    restored = module._ingest_code_graph_event(p, old.event("return-H1-again", [(path, symbol)]))
    assert restored["embedding"]["created"] == 1 and restored["embedding"]["failed"] == 0
    assert old.linked(p, symbol) == cid and old.status(p, h2) == "archived"
    repeated = module._ingest_code_graph_event(p, old.event("return-H1-unchanged", [(path, symbol)]))
    assert repeated["embedding"]["reused"] == 1 and old.linked(p, symbol) == cid
    assert p._connect().execute("SELECT 1 FROM claims_fts WHERE id=?", (cid,)).fetchone()


def test_L2_manual_stale_and_privacy_cannot_borrow_source_return(case, monkeypatch):
    module, p, graph = case
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    pairs = [("src/manual.py", "manual.chunk"), ("src/erased.py", "erased.chunk"), ("src/stale.py", "stale.chunk")]
    original = old.event("negative-first", pairs)
    module._ingest_code_graph_event(p, original)
    manual, erased, stale = [old.linked(p, s) for _, s in pairs]
    p._archive_claim_ids([manual], reason="manual hold")
    erased_text = p._connect().execute("SELECT claim FROM claims WHERE id=?", (erased,)).fetchone()[0]
    privacy = p._set_status_by_text(erased_text, status="archived", reason="explicit privacy erasure", erase_memory_events=True)
    assert privacy["privacy_intent_durable"] and erased in privacy["claim_ids"]
    with p._claim_transaction() as c:
        c.execute("UPDATE code_graph_chunks SET embedding_claim_id='' WHERE repository_id=? AND chunk_id IN (?,?)", (REPO, "manual.chunk", "erased.chunk"))
    backfill = graph.embed_pending_chunks(p, dict(repository_id=REPO, limit=10))
    assert backfill["embedding"]["created"] == backfill["embedding"]["reused"] == 0
    assert old.status(p, manual) == old.status(p, erased) == "archived"
    module._ingest_code_graph_event(p, old.event("negative-delete-stale", mode="delta", deleted=["src/stale.py"]))
    assert old.status(p, stale) == "archived"
    duplicate = module._ingest_code_graph_event(p, original)
    assert duplicate["deduplicated"] is True
    assert p._connect().execute("SELECT 1 FROM code_graph_chunks WHERE chunk_id='stale.chunk'").fetchone() is None
    # A producer label/boolean without a new matching snapshot is not authority.
    stored = p._connect().execute("SELECT claim FROM claims WHERE id=?", (stale,)).fetchone()[0]
    with pytest.raises(PermissionError, match="archived_claim_hash_collision"):
        p._code_claim_add(args("src/stale.py", "stale.chunk", H[:32], stored,
            claim_type="code_graph_chunk", producer="mcp-code-shrinker-knowledge-graph",
            phase_sep_version="kg-v2", source_event_id="forged-fresh-label", revive_archived=True))
    fresh = module._ingest_code_graph_event(p, old.event("negative-new-snapshot", pairs))
    assert old.linked(p, "stale.chunk") == stale and old.status(p, stale) == "active", fresh
    assert old.status(p, manual) == old.status(p, erased) == "archived"
    assert fresh["embedding"]["created"] == 1 and fresh["embedding"]["failed"] == 2
    for symbol in ("manual.chunk", "erased.chunk"):
        assert p._connect().execute("SELECT embedding_claim_id FROM code_graph_chunks WHERE chunk_id=?", (symbol,)).fetchone()[0] == ""
    assert not p._connect().execute("SELECT 1 FROM claims_fts WHERE id IN (?,?)", (manual, erased)).fetchone()
    # Stronger composition: privacy intent AFTER a lawful revision retirement
    # must veto even a matching receipt plus a genuinely fresh source snapshot.
    retired = module._ingest_code_graph_event(p, old.event("privacy-after-retirement-delete", mode="delta", deleted=["src/stale.py"]))
    assert stale in retired["revision_retirements"] and old.status(p, stale) == "archived"
    intent = p._set_status_by_text(stored, status="archived", reason="privacy after ordinary retirement", erase_memory_events=True)
    assert intent["privacy_intent_durable"] and intent["matched_count"] == 1
    refused = module._ingest_code_graph_event(p, old.event("privacy-after-retirement-fresh", [("src/stale.py", "stale.chunk")], mode="delta"))
    assert refused["embedding"]["created"] == refused["embedding"]["reused"] == 0
    assert old.status(p, stale) == "archived"
    assert p._connect().execute("SELECT embedding_claim_id FROM code_graph_chunks WHERE chunk_id='stale.chunk'").fetchone()[0] == ""
    assert p._transaction_quarantine is None


def test_L3_temporal_legacy_alias_retained_and_proven_groups_retire(case):
    module, p, _graph = case
    path, long_symbol = "src/legacy-temporal.py", SYMBOL + ".child"
    module._ingest_code_graph_event(p, old.event("temporal-legacy", [(path, long_symbol)]))
    aid = old.legacy_write(module, p, args(path, long_symbol, H[:32], claim_type="code_graph_chunk"))["id"]
    with p._claim_transaction() as c:
        c.execute("UPDATE code_graph_chunks SET embedding_claim_id=? WHERE chunk_id=?", (aid, long_symbol))
    foreign = p._code_claim_add(args("src/foreign.py", SYMBOL, "foreign", visibility_scope="private"))["id"]
    with p._claim_transaction() as c:
        c.execute("UPDATE claims SET origin_bot_id='foreign-bot' WHERE id=?", (foreign,))
    unknown = old.legacy_write(module, p, args("src/unknown-temporal.py", SYMBOL + ".unknown", "legacy"))["id"]
    p._code_claim_add(args("src/new-temporal.py", SYMBOL, "new", TEXT + " The verified service now uses version 2.0."))
    old.observe(p, "L3-temporal-prefix")
    assert old.status(p, aid) == "active", "L3 prefix-discovered temporal peer was destructively retired"
    assert old.linked(p, long_symbol) == aid
    assert old.status(p, foreign) == old.status(p, unknown) == "active"

    # Preserve documented repo+symbol grouping across *different* files and
    # different revisions/hashes, and repo+file when the new symbol is absent.
    before = p._code_claim_add(args("src/old.py", "same.symbol", "one", TEXT + " The service uses version 1.0."))["id"]
    successor = p._code_claim_add(args("src/new.py", "same.symbol", "two", TEXT + " The service now uses version 2.0."))["id"]
    assert old.status(p, before) == "archived" and old.status(p, successor) == "active"
    file_before = p._code_claim_add(args("src/file-group.py", "", "one", TEXT + " The service uses version 1.0."))["id"]
    p._code_claim_add(args("src/file-group.py", "", "two", TEXT + " The service now uses version 2.0."))
    assert old.status(p, file_before) == "archived"
    # Same-owner proven legacy full graph symbol still participates.
    p._code_claim_add(args("src/moved.py", long_symbol, "successor", TEXT + " The service now uses version 3.0."))
    assert old.status(p, aid) == "archived"
    personal = p._add_claim("The verified Boreal service uses port 8123 and retains deterministic transaction ownership.", topic="personal-ports")
    p._add_claim("The verified Boreal service now uses port 9234 and retains deterministic transaction ownership.", topic="personal-ports")
    assert old.status(p, personal) == "archived"
    assert p._transaction_quarantine is None


def test_L4_patch_namespace_boundary_queries_and_exact_invalidation(case):
    module, p, _graph = case
    patch = p._patch_outcome_add(dict(repository_id=REPO, patch_id="boundary-patch", outcome="verified service procedure applied",
        changed_files=[PATH], changed_symbols=[SYMBOL], source_event_id="boundary-patch-event"))
    assert patch.get("id") and not patch["id"].startswith("rq_"), patch
    cid = patch["id"]
    projected = api_rows(p, symbol=SYMBOL)
    invalidated = p._invalidate_revision(dict(repository_id=REPO, file_path=PATH, symbol_id=SYMBOL))
    old.observe(p, "L4-patch-boundaries", projections=ids(projected), invalidated=invalidated)
    assert ids(projected) == [[cid]] * 3 and invalidated["ids"] == [cid], "L4 lawful patch namespace rejected as unknown code identity"
    assert old.status(p, cid) == "archived"
    assert p._symbol_history(dict(repository_id=REPO, symbol_id=SYMBOL))["history"][0]["id"] == cid
    assert p._code_claim_query(dict(repository_id=REPO))["claims"] == []
    # Neither arbitrary claim_type nor a copied source label substitutes for
    # actual patch link/hash/changed-file proof. Keep legacy code UNKNOWN.
    fake = old.legacy_write(module, p, args(PATH + ".fake.py", SYMBOL + ".fake", "fake", claim_type="patch_outcome"))["id"]
    assert p._code_claim_query(dict(repository_id=REPO, file_path=PATH))["claims"] == []
    with p._claim_transaction() as c:
        c.execute("UPDATE claims SET source='tool:patch_outcome_add' WHERE id=?", (fake,))
    assert p._code_claim_query(dict(repository_id=REPO, file_path=PATH))["claims"] == []
    assert p._invalidate_revision(dict(repository_id=REPO, file_path=PATH))["invalidated"] == 0
    assert old.status(p, fake) == "active" and p._transaction_quarantine is None
