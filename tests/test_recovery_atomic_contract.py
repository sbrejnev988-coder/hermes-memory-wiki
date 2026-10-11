"""Focused genuine provider/SQLite controls; no SDK, sanitizer or parser substitutes.

The separate packet retains all six original recovery assertions. These controls
exercise only their new journal classifier and real pre-commit owner boundary.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading

import pytest
import memory_wiki as wiki
from memory_wiki import document_knowledge_graph as graph


@pytest.fixture
def owned(request):
    root = Path(os.environ["RECOVERY_DIAGNOSTIC_OUT"]) / "controls" / hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    root.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location("_recovery_helpers_" + root.name, Path(__file__).parent / "ci_owned/recovery_cases.py")
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    helpers.OUT = root  # Test-only synthetic paths; no production callback replacement.
    # The preserved historical helper expects a dict checkpoint pointer; the
    # current public reader returns Optional[Path]. Bind our explicit fixture
    # projection without changing any original assertion or product function.
    helpers.state = fixture_state_current_pointer
    provider = wiki.MemoryWikiProvider()
    provider.initialize("atomic-control-" + root.name, hermes_home=str(root / "home"),
                        agent_context="test", bot_id="synthetic-recovery-bot", project_id="diagnostic")
    assert provider._lifecycle_state == "ready"
    graph.install_document_graph_schema(provider._connect())
    with wiki._native_profile_scope(provider.home), graph._document_profile_scope(provider.home):
        yield provider, helpers
    # Explicit test-owned close, including a deliberately retained UNKNOWN TX.
    # Never clear provider quarantine or use this cleanup as a production proof.
    if provider._conn is not None:
        provider._conn.set_authorizer(None)
        provider._conn.close()


def fixture_state_current_pointer(provider, sid):
    """Unchanged historical fixture state with actual Optional[Path] mapping."""
    conn = provider._connect()
    tables = ('document_sources', 'document_units', 'document_chunks', 'document_edges',
              'document_revisions', 'document_units_fts', 'document_chunks_fts', 'document_graph_meta')
    rows = {}
    for table in tables:
        data = [list(row) for row in conn.execute('SELECT * FROM ' + table).fetchall()]
        rows[table] = {'count': len(data), 'sha256': hashlib.sha256(
            json.dumps(sorted(data, key=repr), ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()}
    pointer = provider._latest_journal_checkpoint()
    p = Path(pointer) if pointer else None
    return {'tables': rows, 'source_active': int(conn.execute(
        'SELECT active FROM document_sources WHERE source_id=?', (sid,)).fetchone()[0]),
        'target_unit_fts': int(conn.execute('SELECT count(*) FROM document_units_fts WHERE source_id=?', (sid,)).fetchone()[0]),
        'target_chunk_fts': int(conn.execute('SELECT count(*) FROM document_chunks_fts WHERE source_id=?', (sid,)).fetchone()[0]),
        'identity_count': len(graph._file_identity_history(conn, sid)),
        'checkpoint_pointer': {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} if p else None,
        'sqlite_integrity': conn.execute('PRAGMA quick_check').fetchone()[0],
        'foreign_key_violations': len(conn.execute('PRAGMA foreign_key_check').fetchall())}


def snapshot(provider):
    conn = provider._connect()
    tables = ("document_sources", "document_units", "document_chunks", "document_edges",
              "document_revisions", "document_events", "document_units_fts", "document_chunks_fts", "document_graph_meta")
    result = {}
    for table in tables:
        rows = [list(row) for row in conn.execute("SELECT * FROM " + table)]
        result[table] = hashlib.sha256(json.dumps(sorted(rows, key=repr), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    pointer = provider._latest_journal_checkpoint()
    result["pointer"] = (str(pointer), hashlib.sha256(pointer.read_bytes()).hexdigest()) if pointer else None
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    return result


@pytest.mark.parametrize("kind", ["native_error", "empty_error", "explicit_failure"])
def test_failure_envelopes_close_error_without_checkpoint_or_free_text(owned, kind):
    provider, helpers = owned
    result = (wiki.tool_error(helpers.WINDOWS_PATH) if kind == "native_error" else
              wiki.tool_error("") if kind == "empty_error" else
              wiki.tool_result(success=False, error=helpers.WINDOWS_PATH))
    n = helpers.start_line(provider)
    pointer = provider._latest_journal_checkpoint()
    returned, receipt = provider._journal_operation("memory_wiki_document_ingest", {}, lambda: result)
    assert returned == result
    assert "error" in receipt and "after" not in receipt and receipt["checkpoint"] == {}
    assert provider._latest_journal_checkpoint() == pointer
    observed = helpers.journal_checks(provider, n)
    assert observed["phases"] == ["before", "error"] and observed["marker_leaks"] == 0


def test_exact_500_delete_preserves_complete_reference_and_checkpoint(owned):
    provider, helpers = owned
    sid, identities, raw_hash = helpers.seed_source(provider, "exact-500", count=500)
    provider._journal_checkpoint("before-exact-500")
    pointer = provider._latest_journal_checkpoint()
    n = helpers.start_line(provider)
    result = json.loads(provider.handle_tool_call("memory_wiki_document_delete", {"source_id": sid}))
    assert result["success"] is True and result["status"] == "deleted"
    events = [json.loads(line) for line in provider.journal_path.read_text(encoding="utf-8").splitlines()[n:]]
    assert [event["phase"] for event in events] == ["before", "after"]
    ref = events[-1]["result"]["recovery"]["references"][0]
    assert ref["file_identities"] == [list(item) for item in identities]
    assert ref["file_hash"] == raw_hash and ref["active"] == 0
    assert provider._latest_journal_checkpoint() != pointer
    assert graph._file_identity_history(provider._connect(), sid) == set(identities)
    assert provider._connect().execute("SELECT COUNT(*) FROM document_units_fts WHERE source_id=?", (sid,)).fetchone()[0] == 0
    assert provider._connect().execute("SELECT COUNT(*) FROM document_chunks_fts WHERE source_id=?", (sid,)).fetchone()[0] == 0
    assert helpers.journal_checks(provider, n)["marker_leaks"] == 0


def test_admission_is_inside_actual_owner_and_blocks_separate_sqlite_writer(owned):
    provider, helpers = owned
    sid, _, _ = helpers.seed_source(provider, "serialized-500", count=500)
    rival = sqlite3.connect(str(provider.db_path), timeout=0)
    observed = []
    target = graph._document_recovery_file_identities.__code__

    def profile(frame, event, arg):
        if event != "call" or frame.f_code is not target or frame.f_locals["source_id"] != sid:
            return
        conn = frame.f_locals["conn"]
        assert conn is provider._conn and conn.in_transaction
        assert provider._claim_tx_connection is conn and provider._claim_tx_thread == threading.get_ident()
        try:
            rival.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            assert exc.sqlite_errorcode in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
            observed.append("separate_writer_blocked")
        else:
            rival.rollback()
            observed.append("UNPROTECTED")

    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        result = graph.delete_document(provider, {"source_id": sid})
    finally:
        sys.setprofile(previous)
        rival.close()
    assert result["status"] == "deleted"
    assert observed == ["separate_writer_blocked"]
    assert not provider._conn.in_transaction and provider._claim_tx_connection is None


def test_joined_delete_cannot_commit_caller_and_primary_rollback_is_preserved(owned):
    provider, helpers = owned
    sid, _, _ = helpers.seed_source(provider, "joined")
    before = snapshot(provider)
    primary = ValueError("owned-test-primary")
    observer = sqlite3.connect(str(provider.db_path), timeout=0)
    try:
        with pytest.raises(ValueError) as caught:
            with provider._claim_transaction() as conn:
                assert graph.delete_document(provider, {"source_id": sid})["status"] == "deleted"
                assert conn.in_transaction and provider._claim_tx_connection is conn
                assert conn.execute("SELECT active FROM document_sources WHERE source_id=?", (sid,)).fetchone()[0] == 0
                assert observer.execute("SELECT active FROM document_sources WHERE source_id=?", (sid,)).fetchone()[0] == 1
                raise primary
        assert caught.value is primary
    finally:
        observer.close()
    assert snapshot(provider) == before and provider._transaction_quarantine is None
    assert provider._claim_tx_connection is None and not provider._conn.in_transaction


def test_ingest_commit_admission_rolls_back_candidate_501_and_owner_entry(owned):
    provider, helpers = owned
    sid, identities, _ = helpers.seed_source(provider, "ingest-500", count=500)
    before = snapshot(provider)
    extra = (identities[-1][0], identities[-1][1] + 1)
    conn = provider._connect()
    with pytest.raises(graph._DocumentRecoveryHistoryOverflow):
        with graph._ingest_transaction(provider, conn, None, source_id=sid):
            conn.execute("UPDATE document_sources SET status='candidate' WHERE source_id=?", (sid,))
            assert graph._remember_file_identity(conn, sid, extra)
            assert len(graph._file_identity_history(conn, sid)) == 501
    assert snapshot(provider) == before
    assert conn.execute("SELECT 1 FROM document_graph_meta WHERE key=?", (f"file_identity_owner:{extra[0]}:{extra[1]}",)).fetchone() is None
    assert provider._transaction_quarantine is None and provider._claim_tx_connection is None


def test_replay_union_overflow_is_atomic_and_exact_history_replay_remains_positive(owned):
    provider, helpers = owned
    sid, identities, _ = helpers.seed_source(provider, "replay-500", count=500)
    ref = graph._document_source_recovery_reference(provider, sid, action="delete")
    extra = (identities[-1][0], identities[-1][1] + 1)
    oversized = {**ref, "file_identities": [list(extra)]}
    before = snapshot(provider)
    with pytest.raises(graph._DocumentRecoveryHistoryOverflow):
        graph._replay_document_source_reference(provider, oversized)
    assert snapshot(provider) == before
    assert graph._replay_document_source_reference(provider, ref)["status"] == "deleted"
    assert graph._file_identity_history(provider._connect(), sid) == set(identities)
    assert graph._replay_document_source_reference(provider, ref)["status"] == "already_deleted"


def test_foreign_handle_and_scope_stay_fail_closed(owned):
    provider, helpers = owned
    sid, _, _ = helpers.seed_source(provider, "foreign")
    foreign = sqlite3.connect(str(provider.db_path), timeout=0)
    before = snapshot(provider)
    try:
        with pytest.raises(RuntimeError, match="transaction_not_owned"):
            with graph._document_write_transaction(provider, foreign):
                pytest.fail("foreign connection admitted")
        assert not foreign.in_transaction and snapshot(provider) == before
    finally:
        foreign.close()
    with provider._claim_transaction() as conn:
        conn.execute("UPDATE document_sources SET scope_id='other',repository_id='other' WHERE source_id=?", (sid,))
    before = snapshot(provider)
    n = helpers.start_line(provider)
    result = json.loads(provider.handle_tool_call("memory_wiki_document_delete", {"source_id": sid}))
    assert set(result) == {"error"}
    assert snapshot(provider) == before
    assert helpers.journal_checks(provider, n)["phases"] == ["before", "error"]


def test_real_rollback_refusal_retains_unknown_owner_and_never_reports_safe_admission(owned):
    provider, helpers = owned
    sid, _, _ = helpers.seed_source(provider, "rollback-501", count=501)
    conn = provider._connect()
    n = helpers.start_line(provider)
    pointer = provider._latest_journal_checkpoint()
    denied = []

    def authorizer(action, arg1, arg2, db, source):
        if action == sqlite3.SQLITE_TRANSACTION and arg1 == "ROLLBACK":
            denied.append("native_rollback_denied")
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorizer)
    result = json.loads(provider.handle_tool_call("memory_wiki_document_delete", {"source_id": sid}))
    assert set(result) == {"error"} and "UNKNOWN" in result["error"]
    primary = provider._transaction_primary
    assert isinstance(primary, graph._DocumentRecoveryHistoryOverflow)
    assert denied == ["native_rollback_denied"]
    assert provider._transaction_quarantine is conn and provider._claim_tx_connection is conn
    assert conn.in_transaction and provider._owned_conn is conn
    assert any("outcome=UNKNOWN" in note for note in primary.__notes__)
    with pytest.raises(RuntimeError, match="provider_lifecycle_not_ready"):
        provider._connect()
    assert provider._transaction_primary is primary and provider._conn is conn
    assert helpers.journal_checks(provider, n)["phases"] == ["before", "error"]
    assert provider._latest_journal_checkpoint() == pointer
    # Native quarantine/retention above is the observed production state.
    # Fixture-owned authorizer removal/close happens only after the assertions.


# correction01: authored rows/cache only, real snapshot + unchanged ingest;
# no extractor/parser/SDK/source-module substitution or worker admission.
from contextlib import contextmanager


def journal_image(provider):
    return {str(p.relative_to(provider.journal_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in provider.journal_dir.rglob('*') if p.is_file()}


@pytest.mark.parametrize('outer', ['commit', 'rollback'])
def test_public_joined_journal_refuses_before_effect_and_preserves_caller_rows(owned, outer):
    provider, helpers = owned
    sid, _, _ = helpers.seed_source(provider, 'public-joined')
    provider._journal_checkpoint('before-public-joined')
    before = helpers.state(provider, sid)
    journal_before = journal_image(provider)
    conn = provider._connect()
    observer = sqlite3.connect(str(provider.db_path), timeout=0)
    primary = ValueError('caller-primary')

    def caller():
        with provider._claim_transaction() as exact:
            exact.execute("UPDATE document_sources SET title='caller-owned' WHERE source_id=?", (sid,))
            result = provider.handle_tool_call('memory_wiki_document_delete', {'source_id': sid})
            assert result == wiki.tool_error('journal_mutation_requires_idle_owner')
            assert json.loads(result) == {'error': 'journal_mutation_requires_idle_owner'}
            assert exact is conn and exact.in_transaction and provider._claim_tx_connection is exact
            assert exact.execute('SELECT active FROM document_sources WHERE source_id=?', (sid,)).fetchone()[0] == 1
            assert observer.execute('SELECT title FROM document_sources WHERE source_id=?', (sid,)).fetchone()[0] == helpers.MARKER
            assert journal_image(provider) == journal_before
            assert provider._transaction_quarantine is None
            if outer == 'rollback':
                raise primary
    try:
        if outer == 'rollback':
            with pytest.raises(ValueError) as caught:
                caller()
            assert caught.value is primary and helpers.state(provider, sid) == before
        else:
            caller()
            assert observer.execute('SELECT title,active FROM document_sources WHERE source_id=?', (sid,)).fetchone() == ('caller-owned', 1)
            assert graph._file_identity_history(conn, sid)
            assert helpers.state(provider, sid)['checkpoint_pointer'] == before['checkpoint_pointer']
    finally:
        observer.close()
    assert journal_image(provider) == journal_before
    assert not conn.in_transaction and provider._claim_tx_connection is None
    assert provider._transaction_quarantine is None


def test_private_journal_entry_also_refuses_without_calling_mutation(owned):
    provider, helpers = owned
    sid, _, _ = helpers.seed_source(provider, 'private-journal-joined')
    before = snapshot(provider)
    journal_before = journal_image(provider)
    calls = []
    with provider._claim_transaction() as conn:
        result, receipt = provider._journal_operation('memory_wiki_document_delete', {'source_id': sid},
            lambda: calls.append('called') or graph.delete_document(provider, {'source_id': sid}))
        assert result == wiki.tool_error('journal_mutation_requires_idle_owner') and receipt == {}
        assert calls == [] and conn.in_transaction and provider._claim_tx_connection is conn
    assert snapshot(provider) == before and journal_image(provider) == journal_before
    assert provider._transaction_quarantine is None


def test_legal_direct_joined_delete_still_commits_only_with_caller(owned):
    provider, helpers = owned
    sid, _, _ = helpers.seed_source(provider, 'direct-joined-commit')
    observer = sqlite3.connect(str(provider.db_path), timeout=0)
    journal_before = journal_image(provider)
    try:
        with provider._claim_transaction() as conn:
            assert graph.delete_document(provider, {'source_id': sid})['status'] == 'deleted'
            assert conn.in_transaction and provider._claim_tx_connection is conn
            assert observer.execute('SELECT active FROM document_sources WHERE source_id=?', (sid,)).fetchone()[0] == 1
        assert observer.execute('SELECT active FROM document_sources WHERE source_id=?', (sid,)).fetchone()[0] == 0
    finally:
        observer.close()
    assert journal_image(provider) == journal_before
    assert not provider._conn.in_transaction and provider._claim_tx_connection is None


def authored_cached_source(provider, helpers, label, *, count=498, large=False, remember_physical=True):
    """Author a typed retained cache, NOT a claimed parser/extractor execution."""
    from memory_wiki.document_extractors import extraction_options_fingerprint
    sid, identities, raw_hash = helpers.seed_source(provider, label, count=count, large=large)
    conn = provider._connect()
    path = Path(conn.execute('SELECT source_path FROM document_sources WHERE source_id=?', (sid,)).fetchone()[0])
    info = path.stat()
    physical = graph._file_identity(info)
    extraction_fp = extraction_options_fingerprint(path, graph._worker_options({'path': str(path)}))
    material_fp = graph._sha(graph._json(graph._materialization_options()))
    parser = 'authored-retained-cache-no-parser-run'
    version = graph._CURRENT_PARSER_VERSION
    revision = 'docrev_' + graph._sha(f'{sid}\0{raw_hash}\0{parser}\0{version}\0{extraction_fp}\0{material_fp}')[:28]
    payload = graph._sanitize_extracted_json({
        'file_hash': raw_hash, 'parser': parser, 'parser_version': version,
        'extractor_version': graph._EXTRACTOR_VERSION, 'status': 'ok',
        'title': 'Authored cache fixture', 'mime_type': 'text/markdown',
        'file_name': path.name, 'extension': '.md', 'path': str(path),
        'file_size': info.st_size, 'mtime_ns': info.st_mtime_ns, 'secret_redactions': 0,
        'metadata': {}, 'warnings': [], 'secret_categories': {},
        'units': [{'kind': 'paragraph', 'anchor': 'p:1', 'text': helpers.SAFE_TEXT,
                   'title': '', 'parent_anchor': '', 'ordinal': 1, 'locator': {}, 'metadata': {}}],
        'edges': [],
    }, max_items=1_000_000, max_string=2_000_000, max_depth=16)
    metadata = {'extraction_fingerprint': extraction_fp, 'materialization_fingerprint': material_fp,
                'extraction_payload': payload, 'extraction_payload_hash': graph._sha(graph._json(payload))}
    with provider._claim_transaction() as exact:
        exact.execute('UPDATE document_sources SET revision_id=?,parser=?,parser_version=? WHERE source_id=?', (revision, parser, version, sid))
        for table in ('document_units', 'document_chunks'):
            exact.execute('UPDATE ' + table + ' SET revision_id=? WHERE source_id=?', (revision, sid))
        exact.execute('INSERT INTO document_revisions(revision_id,source_id,file_hash,parser,parser_version,status,unit_count,chunk_count,edge_count,metadata_json,created_at) VALUES(?,?,?,?,?,\'active\',1,1,0,?,1)',
                      (revision, sid, raw_hash, parser, version, graph._json(metadata)))
        if remember_physical:
            assert graph._remember_file_identity(exact, sid, physical)
    assert graph._cached_extraction_payload(graph._json(metadata), extraction_fp=extraction_fp,
        file_hash=raw_hash, parser=parser, parser_version=version) is not None
    reference = graph._document_source_recovery_reference(provider, sid, action='ingest')
    return sid, identities, physical, reference


@contextmanager
def cached_replay_trace(provider):
    """Passive primitive witnesses; never replace or intercept product calls."""
    events = []
    targets = {getattr(graph, n).__code__: n for n in ('ingest_document', '_snapshot_allowed_file',
        '_cached_extraction_payload', '_extract', '_verify_document_ingest_replay')}
    def profile(frame, event, arg):
        if event == 'call' and frame.f_code in targets:
            conn = provider._conn
            events.append({'call': targets[frame.f_code], 'pending': conn.in_transaction,
                           'exact_owner': provider._claim_tx_connection is conn,
                           'same_thread': provider._claim_tx_thread == threading.get_ident()})
    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        yield events
    finally:
        sys.setprofile(previous)
    names = [e['call'] for e in events]
    assert names.count('ingest_document') >= 1 and names.count('_snapshot_allowed_file') >= 1
    assert names.count('_cached_extraction_payload') >= 1 and '_extract' not in names
    witnesses = [e for e in events if e['call'] == '_verify_document_ingest_replay']
    assert witnesses and witnesses[0]['pending'] and witnesses[0]['exact_owner'] and witnesses[0]['same_thread']


def test_actual_ingest_replay_500_plus_500_overlap_499_refuses_union_atomically(owned):
    provider, helpers = owned
    sid, identities, physical, reference = authored_cached_source(provider, helpers, 'ingest-union-500', count=499)
    extra = (identities[-1][0], identities[-1][1] + 1)
    incoming = [list(i) for i in identities] + [list(extra)]
    current = graph._file_identity_history(provider._connect(), sid)
    assert len(current) == len(incoming) == 500
    assert len(current & {tuple(i) for i in incoming}) == 499
    assert len(current | {tuple(i) for i in incoming}) == 501
    before = snapshot(provider)
    with cached_replay_trace(provider) as events:
        with pytest.raises(graph._DocumentRecoveryHistoryOverflow):
            graph._replay_document_source_reference(provider, {**reference, 'file_identities': incoming})
    assert snapshot(provider) == before
    assert graph._file_identity_history(provider._conn, sid) == current
    assert provider._conn.execute('SELECT value FROM document_graph_meta WHERE key=?', (f'file_identity_owner:{extra[0]}:{extra[1]}',)).fetchone() is None
    assert not provider._conn.in_transaction and provider._claim_tx_connection is None and provider._transaction_quarantine is None
    helpers.save('F2-union-refusal', {'current': len(current), 'incoming': len(incoming), 'overlap': 499, 'union': 501,
        'actual_calls': events, 'authored_cache_not_parser_execution': True, 'snapshot_unchanged': True})


def test_actual_ingest_replay_exact_500_complete_and_idempotent(owned):
    provider, helpers = owned
    sid, identities, physical, reference = authored_cached_source(provider, helpers, 'ingest-union-positive')
    extra = (identities[-1][0], identities[-1][1] + 1)
    expected = set(identities) | {physical, extra}
    reference = {**reference, 'file_identities': [list(i) for i in sorted(expected)]}
    assert len(expected) == 500
    with cached_replay_trace(provider) as events:
        result = graph._replay_document_source_reference(provider, reference)
        after = snapshot(provider)
        repeated = graph._replay_document_source_reference(provider, reference)
    assert result == repeated == {'status': 'restored', 'source_id': sid, 'unit_count': 1, 'chunk_count': 1, 'edge_count': 0, 'embedding': {}}
    assert snapshot(provider) == after and graph._file_identity_history(provider._conn, sid) == expected
    for dev, ino in expected:
        assert provider._conn.execute('SELECT value FROM document_graph_meta WHERE key=?', (f'file_identity_owner:{dev}:{ino}',)).fetchone()[0] == sid
    assert not provider._conn.in_transaction and provider._transaction_quarantine is None
    helpers.save('F2-exact500-positive', {'identities': len(expected), 'idempotent': True, 'actual_calls': events,
                                        'authored_cache_not_parser_execution': True})


@pytest.mark.parametrize('field', ['source_id', 'file_hash', 'parser', 'parser_version', 'revision_id', 'unit_count'])
def test_ingest_replay_reference_checks_roll_back_actual_new_physical_identity(owned, field):
    provider, helpers = owned
    sid, identities, physical, reference = authored_cached_source(provider, helpers, 'replay-checks', count=1, remember_physical=False)
    before = snapshot(provider)
    bad = {**reference, field: (reference[field] + 1 if field == 'unit_count' else
                              '0' * 64 if field == 'file_hash' else str(reference[field]) + '-changed')}
    with cached_replay_trace(provider):
        with pytest.raises(RuntimeError, match='document recovery'):
            graph._replay_document_source_reference(provider, bad)
    assert snapshot(provider) == before and graph._file_identity_history(provider._conn, sid) == set(identities)
    assert provider._conn.execute('SELECT value FROM document_graph_meta WHERE key=?', (f'file_identity_owner:{physical[0]}:{physical[1]}',)).fetchone() is None
    assert not provider._conn.in_transaction and provider._claim_tx_connection is None and provider._transaction_quarantine is None


@pytest.mark.parametrize('refusal', ['owner', 'chars'])
def test_ingest_replay_owner_and_12000_char_admission_keep_all_rows(owned, refusal):
    provider, helpers = owned
    sid, identities, physical, reference = authored_cached_source(provider, helpers, 'replay-admission',
        count=298 if refusal == 'chars' else 1, large=refusal == 'chars', remember_physical=False)
    extra = (identities[-1][0] + 1, identities[-1][1] + 1)
    second = (extra[0] + 1, extra[1] + 1)
    incoming = reference['file_identities'] + [list(extra)] + ([list(second)] if refusal == 'chars' else [])
    expected = set(identities) | {physical, extra} | ({second} if refusal == 'chars' else set())
    assert len(incoming) <= 500 and len(expected) <= 500
    if refusal == 'owner':
        with provider._claim_transaction() as conn:
            conn.execute('INSERT INTO document_graph_meta(key,value) VALUES(?,?)', (f'file_identity_owner:{extra[0]}:{extra[1]}', 'other-authored-source'))
    else:
        assert len(graph._json([list(i) for i in sorted(expected)])) > 12000
    before = snapshot(provider)
    with cached_replay_trace(provider):
        with pytest.raises(PermissionError if refusal == 'owner' else RuntimeError,
                           match='another source' if refusal == 'owner' else 'checkpoint-safe limit'):
            graph._replay_document_source_reference(provider, {**reference, 'file_identities': incoming})
    assert snapshot(provider) == before and graph._file_identity_history(provider._conn, sid) == set(identities)
    assert not provider._conn.in_transaction and provider._transaction_quarantine is None


@pytest.mark.parametrize('outer', ['commit', 'rollback'])
def test_valid_ingest_replay_join_keeps_outer_owner_and_observer_boundary(owned, outer):
    provider, helpers = owned
    sid, identities, physical, reference = authored_cached_source(provider, helpers, 'replay-joined', count=1)
    extra = (identities[-1][0], identities[-1][1] + 1)
    reference = {**reference, 'file_identities': reference['file_identities'] + [list(extra)]}
    before = snapshot(provider)
    key = f'file_identity_owner:{extra[0]}:{extra[1]}'
    observer = sqlite3.connect(str(provider.db_path), timeout=0)
    primary = ValueError('replay-caller-primary')
    def caller():
        with provider._claim_transaction() as conn:
            assert graph._replay_document_source_reference(provider, reference)['status'] == 'restored'
            assert conn.in_transaction and provider._claim_tx_connection is conn
            assert conn.execute('SELECT value FROM document_graph_meta WHERE key=?', (key,)).fetchone()[0] == sid
            assert observer.execute('SELECT value FROM document_graph_meta WHERE key=?', (key,)).fetchone() is None
            if outer == 'rollback':
                raise primary
    try:
        if outer == 'rollback':
            with pytest.raises(ValueError) as caught:
                caller()
            assert caught.value is primary and snapshot(provider) == before
        else:
            caller()
            assert observer.execute('SELECT value FROM document_graph_meta WHERE key=?', (key,)).fetchone()[0] == sid
            assert graph._file_identity_history(provider._conn, sid) == set(identities) | {physical, extra}
    finally:
        observer.close()
    assert not provider._conn.in_transaction and provider._claim_tx_connection is None and provider._transaction_quarantine is None
