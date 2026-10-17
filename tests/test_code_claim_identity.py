"""CSL1: lossless mapped identity, historical slices and exact retirement.

SOURCE fixtures reuse the shipped atomicity loader. No SDK/trust substitute or
profile/quality admission override. Legacy writes execute the exact accepted373
_code_claim_add body below; only historical link corruption is explicitly
SQL-authored, never represented as native provenance.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import textwrap

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "code_identity_atomicity_peer", Path(__file__).with_name("test_code_graph_idempotency_atomicity.py")
)
assert _SPEC and _SPEC.loader
peer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(peer)
REPO = peer.REPOSITORY_ID
TEXT = (
    "The verified Boreal implementation preserves deterministic source provenance, "
    "explicit transaction ownership, reliable revision history and independent integrity checks."
)
H = hashlib.sha256(TEXT.encode()).hexdigest()
# Dots keep these ordinary identities outside the token redactor's long-word
# rule. Lengths refer to accepted canonical keys, not a raw-input assumption.
PATH_B = "src/" + "part." * 100 + "entry.py"
SYMBOL_B = "unit." * 50 + "worker"
assert len(PATH_B) == 512 and len(SYMBOL_B) == 256
LEGACY_ADD_SOURCE = '    def _code_claim_add(\n        self,\n        a: Dict[str, Any],\n        *,\n        conn: Optional[sqlite3.Connection] = None,\n        after_commit_callbacks: Optional[List[Tuple[str, str, str]]] = None,\n        _prepared_code_claim: Optional[Dict[str, Any]] = None,\n        trusted_opaque_graph_ids: bool = False,\n    ) -> Dict[str, Any]:\n        """Atomically persist a previously validated code claim.\n\n        ``_prepared_code_claim`` is an internal graph-worker hand-off.  It keeps\n        preparation (which may write a quarantine/review record) outside the\n        graph worker\'s private ``BEGIN IMMEDIATE`` transaction.\n        """\n        if conn is not None:\n            self._require_claim_writer(conn)\n        if _prepared_code_claim is None:\n            raw_claim = a.get("claim", "")\n            source_event_id = self._code_graph_identity(\n                str(a.get("source_event_id", "")).strip(),\n                trusted_opaque_graph_ids=trusted_opaque_graph_ids,\n                conn=conn,\n            )\n            producer = str(a.get("producer", "code-shrinker") or "code-shrinker").strip()\n            phase_sep_version = str(a.get("phase_sep_version", "2") or "2").strip()\n            existing_claim_id = self._ingest_idempotent(\n                str(raw_claim or ""), source_event_id, phase_sep_version, producer, conn=conn\n            )\n            if existing_claim_id:\n                return {\n                    "id": existing_claim_id,\n                    "status": "deduplicated",\n                    "deduplicated": True,\n                    "source_event_id": source_event_id,\n                }\n            prepared_code_claim = self._prepare_code_claim(\n                a, trusted_opaque_graph_ids=trusted_opaque_graph_ids,\n            )\n        else:\n            prepared_code_claim = dict(_prepared_code_claim)\n            expected_hash = str(a.get("content_hash", "")).strip().lower()\n            if expected_hash.startswith("sha256:"):\n                expected_hash = expected_hash[7:]\n            if (\n                str(prepared_code_claim.get("claim", "")) != str(a.get("claim", ""))\n                or str(prepared_code_claim.get("content_hash", "")) != expected_hash\n            ):\n                raise ValueError("invalid preprepared code claim")\n\n        def persist(active_conn: sqlite3.Connection) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], str]:\n            # This must be the first graph-identity operation inside the\n            # writer transaction.  A checkpoint may have completed v1 -> v2\n            # after preparation but before this writer became exclusive.\n            final = self._recanonicalize_prepared_code_claim_for_write(\n                a,\n                prepared_code_claim,\n                active_conn,\n                trusted_opaque_graph_ids=trusted_opaque_graph_ids,\n            )\n            claim = final["claim"]\n            source_event_id = final["source_event_id"]\n            producer = final["producer"]\n            phase_sep_version = final["phase_sep_version"]\n            repo_id = final["repository_id"]\n            commit_sha = final["commit_sha"]\n            file_path = final["file_path"]\n            symbol_id = final["symbol_id"]\n            symbol_rev = final["symbol_revision"]\n            content_hash_f = final["content_hash"]\n            claim_type = final["claim_type"]\n            confidence = final["confidence"]\n            salience = final["salience"]\n            existing_claim_id = self._ingest_idempotent(\n                str(claim or ""), source_event_id, phase_sep_version,\n                producer, conn=active_conn,\n            )\n            if existing_claim_id:\n                return ({\n                    "id": existing_claim_id,\n                    "status": "deduplicated",\n                    "deduplicated": True,\n                    "source_event_id": source_event_id,\n                }, None, "")\n            prepared_value = final.get("prepared")\n            if isinstance(prepared_value, str) and prepared_value.startswith("rq_"):\n                return ({\n                    "status": "need_review",\n                    "review_id": prepared_value,\n                    "type": claim_type,\n                    "repository_id": repo_id,\n                }, None, "")\n            if not isinstance(prepared_value, dict):\n                raise ValueError("invalid preprepared code claim")\n            prepared = dict(prepared_value)\n            _register_code_graph_identity_provenance(\n                active_conn, (repo_id, file_path, symbol_id, source_event_id),\n            )\n            cid = self._add_claim_tx(active_conn, prepared, confidence, salience)\n            active_conn.execute(\n                """INSERT INTO code_claim_metadata(claim_id,repository_id,commit_sha,file_path,symbol_id,symbol_revision,content_hash,claim_type)\n                   VALUES(?,?,?,?,?,?,?,?)\n                   ON CONFLICT(claim_id) DO UPDATE SET\n                   repository_id=excluded.repository_id, commit_sha=excluded.commit_sha,\n                   file_path=excluded.file_path, symbol_id=excluded.symbol_id,\n                   symbol_revision=excluded.symbol_revision, content_hash=excluded.content_hash,\n                   claim_type=excluded.claim_type""",\n                (\n                    cid, repo_id, commit_sha[:64], file_path[:512],\n                    symbol_id[:256], symbol_rev[:64], content_hash_f[:256],\n                    claim_type[:64],\n                ),\n            )\n            self._mark_ingested(\n                cid,\n                source_event_id,\n                content_hash=content_hash_f,\n                producer=producer,\n                claim_text=str(claim or ""),\n                phase_sep_version=phase_sep_version,\n                conn=active_conn,\n            )\n            return ({\n                "id": cid,\n                "type": claim_type,\n                "repository_id": repo_id,\n                "source_event_id": source_event_id,\n                "deduplicated": bool(prepared.get("_no_op")),\n                "status": "deduplicated" if prepared.get("_no_op") else "committed",\n            }, prepared, cid)\n\n        if conn is None:\n            with self._lock:\n                active_conn = self._connect()\n                with self._claim_transaction(active_conn):\n                    result, prepared, cid = persist(active_conn)\n            if prepared is not None and not prepared.get("_no_op"):\n                post_commit_failures = self._after_claim_commit(\n                    cid, prepared["topic"], prepared["claim"],\n                )\n                if post_commit_failures:\n                    result["status"] = "committed_with_deferred_failures"\n                    result["post_commit_failures"] = post_commit_failures\n            return result\n\n        if conn.in_transaction and after_commit_callbacks is None:\n            raise RuntimeError("caller_owned_claim_requires_post_commit_callbacks")\n        with self._claim_transaction(conn, join=True):\n            result, prepared, cid = persist(conn)\n        if prepared is not None and not prepared.get("_no_op") and after_commit_callbacks is not None:\n            after_commit_callbacks.append((cid, prepared["topic"], prepared["claim"]))\n        return result\n'
LEGACY_ADD_SHA256 = "1ec6930025745c16314323e7db0f9bae197bd1498d7bc36d061d7f5bbdcee16d"


@pytest.fixture
def case(request, tmp_path_factory, monkeypatch):
    token = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    home = tmp_path_factory.mktemp("code-identity-" + token, numbered=False)
    # The existing loader sets HERMES_HOME before import and initialize.
    module, provider = peer.load_provider("memory_wiki_code_identity_" + token, home, monkeypatch)
    assert module._IMPORT_HERMES_HOME == home.resolve()
    assert provider.home.resolve() == home.resolve()
    assert provider._runtime_identity()["profile_ready"] is True
    assert provider._runtime_identity()["missing_key_names"] == []
    graph = sys.modules[module.__name__ + ".code_knowledge_graph"]
    try:
        yield module, provider, graph
    finally:
        unknown = provider._transaction_quarantine
        if unknown is None:
            provider._shutdown_lifecycle(render=False)
            assert provider._conn is None and provider._owned_conn is None
        else:
            # Fixture-owned release AFTER exact UNKNOWN assertions; not product
            # recovery, and no owner/quarantine/primary fields are reset.
            owner, primary = provider._claim_tx_connection, provider._transaction_primary
            handles = set(getattr(provider, "_graph_writer_connections", {}))
            handles.update({provider._conn, provider._owned_conn, unknown} - {None})
            for conn in handles:
                sqlite3.Connection.set_authorizer(conn, None)
                sqlite3.Connection.close(conn)
            assert provider._transaction_quarantine is unknown
            assert provider._claim_tx_connection is owner and provider._transaction_primary is primary


def event(label, pairs=(), *, mode="full", deleted=()):
    paths = sorted({path for path, _ in pairs})
    return dict(
        event_version=2, type="code_graph_snapshot", graph_schema_version=1,
        producer="code-shrinker", repository_id=REPO, event_id=label,
        snapshot_mode=mode, commit_sha=hashlib.sha1(label.encode()).hexdigest(),
        files=[dict(file_path=path, file_hash=H, language="python", line_count=3) for path in paths],
        chunks=[dict(chunk_id=symbol, file_path=path, symbol_id="", qualified_name="verified.worker",
                     start_line=1, end_line=3, chunk_text=TEXT, embedding_text=TEXT, content_hash=H)
                for path, symbol in pairs], deleted_files=list(deleted),
    )


def observe(provider, label, **extra):
    """Canonical durable state and FTS observations precede safety assertions."""
    with closing(sqlite3.connect(str(provider.db_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT c.id,c.status,c.hash,m.* FROM claims c JOIN code_claim_metadata m ON m.claim_id=c.id ORDER BY c.id"
        )]
        links = [dict(r) for r in conn.execute(
            "SELECT repository_id,file_path,chunk_id,content_hash,embedding_claim_id FROM code_graph_chunks ORDER BY chunk_id"
        )]
        fts = [r[0] for r in conn.execute("SELECT id FROM claims_fts ORDER BY id")]
        result = dict(label=label, rows=rows, links=links, claims_fts=fts, **extra)
    print("CSL1_SQL " + json.dumps(result, sort_keys=True))
    with (Path(provider.home) / "code-identity-observations.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(result, sort_keys=True) + "\n")
    return result


def linked(provider, symbol):
    row = provider._connect().execute(
        "SELECT embedding_claim_id FROM code_graph_chunks WHERE repository_id=? AND chunk_id=?", (REPO, symbol)
    ).fetchone()
    assert row is not None and row[0]
    return str(row[0])


def status(provider, cid):
    return provider._connect().execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0]


def direct_args(path=PATH_B, symbol=SYMBOL_B, revision="", **extra):
    return dict(claim=TEXT, topic="code-intelligence", repository_id=REPO,
                file_path=path, symbol_id=symbol, symbol_revision=revision,
                content_hash=H, confidence=.95, salience=.9, evidence="Verified exact source identity.", **extra)


@pytest.mark.parametrize("axis", ["both", "path", "symbol"])
def test_prefix_alias_withdrawal_preserves_live_source(case, monkeypatch, axis):
    module, p, _graph = case
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    a_path = PATH_B + ".extra.py" if axis != "symbol" else "src/shared.py"
    b_path = PATH_B if axis != "symbol" else a_path
    a_symbol = SYMBOL_B + ".child" if axis != "path" else "shared.owner.a"
    b_symbol = SYMBOL_B if axis != "path" else "shared.owner.b"
    module._ingest_code_graph_event(p, event("prefix-a", [(a_path, a_symbol)]))
    a_id = linked(p, a_symbol)
    # A remains an exact live source. A delta touching another path preserves
    # it; a same-file replacement explicitly carries both chunks.
    pairs = [(b_path, b_symbol)] if a_path != b_path else [(a_path, a_symbol), (b_path, b_symbol)]
    added = module._ingest_code_graph_event(p, event("prefix-b", pairs, mode="delta"))
    b_id = linked(p, b_symbol)
    before = observe(p, "before-alias-withdrawal", added=added)
    if a_path != b_path:
        removed = module._ingest_code_graph_event(p, event("prefix-remove-b", mode="delta", deleted=[b_path]))
    else:
        removed = p._invalidate_revision(dict(repository_id=REPO, file_path=b_path, symbol_id=b_symbol))
    after = observe(p, "after-alias-withdrawal", removed=removed)
    # This is the baseline oracle, intentionally before any optional lexical
    # retrieval/helper premise or metadata-shape assertion.
    assert status(p, a_id) == "active", "CSL1 lawful surviving A archived by prefix-alias B withdrawal"
    assert a_id in after["claims_fts"]
    assert any(r["file_path"] == a_path and r["chunk_id"] == a_symbol and r["embedding_claim_id"] == a_id
               for r in after["links"])
    assert a_id != b_id and status(p, b_id) == "archived"
    row = next(r for r in before["rows"] if r["id"] == a_id)
    assert (row["file_path"], row["symbol_id"]) == (a_path, a_symbol)
    assert p._code_graph_identity(a_path) == a_path and p._code_graph_identity(a_symbol) == a_symbol
    assert not p._transaction_quarantine


@pytest.mark.parametrize("boundary", ["short", "exact"])
def test_unchanged_source_hash_reuse_and_final_withdrawal(case, monkeypatch, boundary):
    module, p, _graph = case
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    path, symbol = (PATH_B, SYMBOL_B) if boundary == "exact" else ("src/stable.py", "stable.chunk")
    first = module._ingest_code_graph_event(p, event("healthy-a", [(path, symbol)]))
    cid = linked(p, symbol)
    repeated = module._ingest_code_graph_event(p, event("healthy-b", [(path, symbol)]))
    assert first["embedding"]["created"] == 1
    assert repeated["invalidated_claims"] == 0 and repeated["embedding"]["reused"] == 1, repeated
    assert linked(p, symbol) == cid and status(p, cid) == "active"
    row = p._code_claim_query(dict(repository_id=REPO, file_path=path, symbol_id=symbol))["claims"]
    assert len(row) == 1 and row[0]["id"] == cid
    assert row[0]["file_path"] == path and row[0]["symbol_id"] == symbol
    removed = module._ingest_code_graph_event(p, event("healthy-remove", mode="delta", deleted=[path]))
    after = observe(p, "healthy-final-withdrawal", removed=removed)
    assert status(p, cid) == "archived" and cid not in after["claims_fts"]
    assert not after["links"] and removed["invalidated_claims"] == 1


def test_direct_metadata_lossless_revision_identity_and_queries(case):
    module, p, _graph = case
    path, symbol = PATH_B + ".extra.py", SYMBOL_B + ".child"
    revision = "release." * 12 + "verified"
    kind = "verified." * 9 + "code_claim"
    args = direct_args(path, symbol, revision, claim_type=kind)
    first = p._code_claim_add(args)
    assert first.get("id") and not first["id"].startswith("rq_"), first
    cid = first["id"]
    row = p._connect().execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (cid,)).fetchone()
    assert tuple(row[k] for k in ("file_path", "symbol_id", "symbol_revision", "claim_type")) == (path, symbol, revision, kind)
    result = p._code_claim_query(dict(repository_id=REPO, file_path=path, symbol_id=symbol))["claims"]
    assert len(result) == 1 and result[0]["symbol_revision"] == revision
    assert p._code_claim_query(dict(repository_id=REPO, file_path=PATH_B))["claims"] == []
    assert p._symbol_history(dict(repository_id=REPO, symbol_id=symbol))["history"][0]["id"] == cid
    assert p._repository_context(dict(repository_id=REPO))["claims"][0]["id"] == cid
    # Same content but a distinct accepted full revision is a distinct identity.
    other = p._code_claim_add({**args, "symbol_revision": revision + ".child"})
    assert other["id"] != cid
    assert p._code_claim_add(args)["id"] == cid
    edited = TEXT + " The reviewed annotation remains source-owned."
    p._update_claim(dict(claim_id=cid, claim=edited))
    row = p._connect().execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone()
    scope = "\0".join(("code_claim", REPO, path, symbol, revision))
    assert row["hash"] == module.sha(scope + "\0" + module.normalize_claim(edited).lower())
    observe(p, "direct-lossless-revisions")


def legacy_write(module, provider, args):
    """Exact frozen old writer, real current guards/TX; not native authority."""
    raw = LEGACY_ADD_SOURCE.encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == LEGACY_ADD_SHA256
    namespace = dict(vars(module))
    exec(compile(textwrap.dedent(LEGACY_ADD_SOURCE), "<accepted373:_code_claim_add>", "exec"), namespace)
    return namespace["_code_claim_add"](provider, args)


@pytest.mark.parametrize("historical_false_link", [False, True])
def test_legacy_truncated_owner_survives_alias_then_retires_final_support(case, monkeypatch, historical_false_link):
    module, p, graph = case
    a_path, a_symbol = PATH_B + ".extra.py", SYMBOL_B + ".child"
    # Ingest actual snapshot with deferred derivative, then execute the genuine
    # accepted373 writer. The old graph link is explicitly authored in the real
    # owning TX, bound to the exact full chunk; not a fabricated trust receipt.
    module._ingest_code_graph_event(p, event("legacy-a", [(a_path, a_symbol)]))
    args = direct_args(a_path, a_symbol, H[:32], claim_type="code_graph_chunk")
    a_id = legacy_write(module, p, args)["id"]
    with p._claim_transaction() as conn:
        cur = conn.execute("UPDATE code_graph_chunks SET embedding_claim_id=? WHERE repository_id=? AND chunk_id=? AND file_path=? AND content_hash=? AND embedding_claim_id=''",
                           (a_id, REPO, a_symbol, a_path, H))
        assert cur.rowcount == 1
    old = dict(p._connect().execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (a_id,)).fetchone())
    assert old["file_path"] == PATH_B and old["symbol_id"] == SYMBOL_B
    if not historical_false_link:
        monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    module._ingest_code_graph_event(p, event("legacy-b", [(PATH_B, SYMBOL_B)], mode="delta"))
    if historical_false_link:
        with p._claim_transaction() as conn:
            cur = conn.execute("UPDATE code_graph_chunks SET embedding_claim_id=? WHERE repository_id=? AND chunk_id=? AND file_path=? AND content_hash=? AND embedding_claim_id=''",
                               (a_id, REPO, SYMBOL_B, PATH_B, H))
            assert cur.rowcount == 1
    else:
        assert linked(p, SYMBOL_B) != a_id, "legacy truncated metadata authorized a new cross-source link"
    observe(p, "legacy-before-withdrawal", genuine_old_writer=True, authored_historical_link=True)
    module._ingest_code_graph_event(p, event("legacy-remove-b", mode="delta", deleted=[PATH_B]))
    middle = observe(p, "legacy-surviving-support")
    assert status(p, a_id) == "active" and a_id in middle["claims_fts"]
    assert linked(p, a_symbol) == a_id
    # No guessed expansion of durable historical metadata occurred.
    assert dict(p._connect().execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (a_id,)).fetchone()) == old
    final = module._ingest_code_graph_event(p, event("legacy-remove-a", mode="delta", deleted=[a_path]))
    after = observe(p, "legacy-final-support", removed=final)
    assert status(p, a_id) == "archived" and a_id not in after["claims_fts"]
    assert not after["links"] and final["invalidated_claims"] == 1


def test_unproven_legacy_slice_is_retained_not_repaired_or_exposed_as_alias(case):
    module, p, _graph = case
    args = direct_args(PATH_B + ".extra.py", SYMBOL_B + ".child", "release." * 12 + "verified")
    cid = legacy_write(module, p, args)["id"]
    old = dict(p._connect().execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (cid,)).fetchone())
    result = p._invalidate_revision(dict(repository_id=REPO, file_path=PATH_B, symbol_id=SYMBOL_B))
    assert result["invalidated"] == 0 and status(p, cid) == "active"
    assert dict(p._connect().execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (cid,)).fetchone()) == old
    assert p._code_claim_query(dict(repository_id=REPO, file_path=PATH_B, symbol_id=SYMBOL_B))["claims"] == []
    with pytest.raises(ValueError, match="code.claim.*identity|identity.*unproven"):
        p._update_claim(dict(claim_id=cid, claim=TEXT + " An edited unproven historical identity is not adopted."))
    # A fresh exact accepted request can restore its OWN lossless metadata via
    # canonical hash equality. No reverse inference from the truncated prefix.
    repaired = p._code_claim_add(args)
    assert repaired["id"] == cid
    row = p._connect().execute("SELECT * FROM code_claim_metadata WHERE claim_id=?", (cid,)).fetchone()
    assert (row["file_path"], row["symbol_id"], row["symbol_revision"]) == (args["file_path"], args["symbol_id"], args["symbol_revision"])
    assert p._code_claim_query(dict(repository_id=REPO, file_path=args["file_path"]))["claims"][0]["id"] == cid


def test_graph_reuse_checks_revision_and_never_revives_archived_hash(case, monkeypatch):
    module, p, graph = case
    path, symbol = "src/revision.py", "revision.chunk"
    wrong = p._code_claim_add(direct_args(path, symbol, "other.release", claim_type="code_graph_chunk"))["id"]
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    result = module._ingest_code_graph_event(p, event("revision-a", [(path, symbol)]))
    cid = linked(p, symbol)
    assert result["embedding"]["created"] == 1 and cid != wrong, result
    with p._claim_transaction() as conn:
        conn.execute("UPDATE claims SET status='archived' WHERE id=?", (cid,))
        conn.execute("UPDATE code_graph_chunks SET embedding_claim_id='' WHERE repository_id=? AND chunk_id=?", (REPO, symbol))
    backfill = graph.embed_pending_chunks(p, dict(repository_id=REPO, limit=10))
    assert backfill["embedding"]["created"] == backfill["embedding"]["reused"] == 0, backfill
    assert status(p, cid) == "archived"
    assert p._connect().execute("SELECT embedding_claim_id FROM code_graph_chunks WHERE chunk_id=?", (symbol,)).fetchone()[0] == ""


def test_pending_C2_exact_identity_model_boundary_and_foreign_writer(case, monkeypatch):
    module, p, graph = case
    path, symbol = PATH_B + ".extra.py", SYMBOL_B + ".child"
    module._ingest_code_graph_event(p, event("pending-a", [(path, symbol)]))
    model = p._invalidate_revision(dict(repository_id=REPO, file_path=path), model_scope=True)
    assert model["invalidated"] == model["retired_pending"] == 0
    assert p._connect().execute("SELECT COUNT(*) FROM code_graph_chunks WHERE embedding_claim_id=''").fetchone()[0] == 1
    withdrawn = p._invalidate_revision(dict(repository_id=REPO, file_path=path, symbol_id=symbol))
    assert withdrawn["retired_pending"] == 1
    assert p._connect().execute("SELECT COUNT(*) FROM code_graph_chunks_fts").fetchone()[0] == 0
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    assert graph.embed_pending_chunks(p, dict(repository_id=REPO))["embedding"]["created"] == 0
    module._ingest_code_graph_event(p, event("pending-fresh", [(path, symbol)]))
    cid = linked(p, symbol)
    assert p._invalidate_revision(dict(repository_id=REPO, file_path=path), model_scope=True)["invalidated"] == 0
    with p._claim_transaction() as conn:
        conn.execute("UPDATE claims SET visibility_scope='private',origin_bot_id=?,origin_session_id=? WHERE id=?", (p.bot_id, p.session_id, cid))
    assert p._invalidate_revision(dict(repository_id=REPO, file_path=path), model_scope=True)["invalidated"] == 1
    with closing(sqlite3.connect(str(p.db_path))) as foreign:
        with pytest.raises(RuntimeError):
            p._code_claim_add(direct_args(), conn=foreign, after_commit_callbacks=[])
    assert status(p, cid) == "archived" and p._transaction_quarantine is None


def test_graph_claim_link_CAS_failure_rolls_back_all_derived_effects(case, monkeypatch):
    module, p, graph = case
    module._ingest_code_graph_event(p, event("cas-a", [(PATH_B + ".extra.py", SYMBOL_B + ".child")]))
    with p._claim_transaction() as conn:
        conn.execute("CREATE TRIGGER authored_ignore_code_link BEFORE UPDATE OF embedding_claim_id ON code_graph_chunks WHEN NEW.embedding_claim_id<>'' BEGIN SELECT RAISE(IGNORE); END")
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    before = observe(p, "CAS-before")
    result = graph.embed_pending_chunks(p, dict(repository_id=REPO, limit=10))
    after = observe(p, "CAS-after", result=result)
    assert result["embedding"]["failed"] == 1 and result["embedding"]["created"] == 0
    assert after["rows"] == before["rows"] == [] and after["claims_fts"] == []
    assert all(not r["embedding_claim_id"] for r in after["links"])
    for table in ("evidence", "claim_write_fingerprints", "index_outbox", "integration_events"):
        assert p._connect().execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0, table
    assert not p._connect().in_transaction and p._transaction_quarantine is None


def test_private_code_write_UNKNOWN_keeps_exact_owner_and_primary(case):
    _module, p, graph = case
    conn, owned = graph._open_graph_writer_connection(p)
    assert owned
    primary = RuntimeError("authored code-identity owning failure")
    denied = []
    def authorize(op, one, two, db, trigger):
        if op == sqlite3.SQLITE_TRANSACTION and one == "ROLLBACK":
            denied.append(one)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    conn.set_authorizer(authorize)
    with pytest.raises(RuntimeError) as caught:
        with p._claim_transaction(conn):
            result = p._code_claim_add(direct_args(PATH_B + ".extra.py", SYMBOL_B + ".child"), conn=conn, after_commit_callbacks=[])
            assert result["id"]
            raise primary
    assert caught.value is primary and denied
    assert conn.in_transaction and p._transaction_quarantine is p._claim_tx_connection is conn
    assert p._transaction_primary is primary and conn in p._graph_writer_connections
    assert any("UNKNOWN" in note for note in primary.__notes__)
    with closing(sqlite3.connect(str(p.db_path))) as observer:
        assert observer.execute("SELECT COUNT(*) FROM code_claim_metadata").fetchone()[0] == 0
    with pytest.raises(RuntimeError):
        p._connect()
    assert p._transaction_quarantine is conn and p._transaction_primary is primary
