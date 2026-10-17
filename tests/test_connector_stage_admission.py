"""Managed connector cache admission, below SDK/trust/host integration.

The precommit residue is fixture-owned completed os.replace, NOT a process
crash. SOURCE decoding uses the actual safe .txt extractor on the real secure
snapshot in-process; native parser/worker/transport is deliberately NOT_RUN.
Reuse the shipped legacy standalone provider fixture only on genuine SDK
absence. No fabricated SDK, ACL, authority or successful extraction payload.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'connector_stage_existing_fixture', Path(__file__).with_name('test_code_graph_idempotency_atomicity.py'))
peer = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = peer
_SPEC.loader.exec_module(peer)
SCOPE = peer.REPOSITORY_ID
A = ('BorealLedger documents the approved archive procedure with exact source '
     'revisions, daily integrity verification, explicit ownership and durable transaction records.')
B = ('CedarResidue describes a different uncompleted archive generation with '
     'independent publication checks, immutable provenance and precise transaction boundaries.')
TABLES = ('document_sources', 'document_revisions', 'document_units', 'document_chunks',
          'document_edges', 'document_events', 'document_units_fts', 'document_chunks_fts',
          'document_graph_meta', 'external_sources', 'claims', 'claims_fts', 'evidence',
          'memory_mutations', 'claim_write_fingerprints', 'index_outbox')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class Store:
    def __init__(self, module, provider, root):
        self.m, self.p, self.root = module, provider, root
        self.g = sys.modules[module.__name__ + '.document_knowledge_graph']
        self.c = sys.modules[module.__name__ + '.source_connectors']
        self.x = sys.modules[module.__name__ + '.document_extractors']
        self.db = provider._connect()
        self.decodes = []

    def source_txt_decoder_SOURCE(self, snapshot, args):
        assert snapshot.suffix == '.txt' and snapshot.is_relative_to(self.p.home)
        result = self.x.extract_document(snapshot, args.get('_effective_extraction_options'))
        self.decodes.append(dict(snapshot_sha256=digest(snapshot.read_bytes()),
                                 file_hash=result['file_hash'], parser=result['parser']))
        return result

    def record(self, revision='one', text=A, *, kind='record', embed=False):
        return self.c.SourceRecord(uri='urn:connector-stage:approved', revision=revision,
                                   text=text, scope_id=SCOPE, repository_id=SCOPE,
                                   source_type=kind, embed=embed)

    def upsert(self, record=None):
        return self.c.upsert_record(self.p, record or self.record())

    def path(self, record=None):
        r = record or self.record()
        namespace = 'github' if r.source_type.startswith('github_') else r.source_type
        key = self.c._source_key(self.p, r.uri, SCOPE, SCOPE, namespace)
        return self.c._record_snapshot_path(self.p, key)

    def replace_file(self, path, text):
        temporary = path.with_name('.fixture-completed-replace.tmp')
        temporary.write_bytes(text.encode('utf-8'))
        os.replace(temporary, path)

    def ingest(self, path, **options):
        return self.g.ingest_document(self.p, dict(path=str(path), scope_id=SCOPE,
                                                 repository_id=SCOPE, embed=False, **options))

    def durable(self):
        # A SQLite connection context commits/rolls back but does NOT close.
        with closing(sqlite3.connect(str(self.p.db_path), timeout=0)) as reader:
            return {name: sorted([list(row) for row in reader.execute('SELECT * FROM ' + name)], key=repr)
                    for name in TABLES}

    def tuple(self, path):
        sid = self.g._source_id(path)
        with closing(sqlite3.connect(str(self.p.db_path), timeout=0)) as reader:
            reader.row_factory = sqlite3.Row
            source = reader.execute('SELECT * FROM document_sources WHERE source_id=?', (sid,)).fetchone()
            links = reader.execute('SELECT * FROM external_sources WHERE document_source_id=?', (sid,)).fetchall()
            hits = reader.execute("SELECT unit_text FROM document_units_fts WHERE source_id=? AND document_units_fts MATCH 'CedarResidue'", (sid,)).fetchall()
            return dict(source=dict(source) if source else None, external=[dict(r) for r in links],
                        residue_hits=[r[0] for r in hits])

    def witness(self, event, **value):
        with (self.root / 'observations.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(event=event, **value), ensure_ascii=False, sort_keys=True) + '\n')

    def coherent(self, path, record):
        value = self.tuple(path)
        assert value['source'] and len(value['external']) == 1
        source, external = value['source'], value['external'][0]
        expected = digest(record.text.encode('utf-8'))
        assert source['file_hash'] == external['content_hash'] == digest(path.read_bytes()) == expected
        assert external['revision_key'] == digest(record.revision.encode('utf-8'))[:20]
        assert external['owner_bot_id'] == self.p.bot_id and external['status'] == 'active'
        revision = self.db.execute('SELECT * FROM document_revisions WHERE revision_id=?', (source['revision_id'],)).fetchone()
        assert revision['source_id'] == source['source_id'] and revision['file_hash'] == expected
        assert revision['status'] == 'active'
        return value


@pytest.fixture
def stage(request, tmp_path_factory, monkeypatch):
    assert importlib.util.find_spec('agent') is None, 'SOURCE requires genuine SDK absence'
    assert importlib.util.find_spec('hermes_trust_core') is None
    token = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    root = tmp_path_factory.mktemp('connector-stage-' + token, numbered=False)
    home = root / 'home'
    home.mkdir()
    for key, value in {
        'HOME': str(home), 'USERPROFILE': str(home), 'LOCALAPPDATA': str(home / 'local'),
        'APPDATA': str(home / 'roaming'), 'MEMORY_WIKI_BOT_ID': 'connector-stage-owner',
        'MEMORY_WIKI_EMBED_PROVIDER': 'stub', 'MEMORY_WIKI_EMBED_MODEL': 'hash-ngram-8',
        'MEMORY_WIKI_EMBED_DIMENSIONS': '8', 'MEMORY_WIKI_VECTOR_SIZE': '8',
        'MEMORY_WIKI_BACKGROUND_JOBS_ENABLED': '0', 'MEMORY_WIKI_ENV_META_SYNC': '0',
        'MEMORY_WIKI_RERANK_ENABLED': '0', 'MEMORY_WIKI_LLM_PACK': '0',
        'MEMORY_WIKI_GRAPH_EXTRACT_ENABLED': '0', 'MEMORY_WIKI_GRAPH_AUTO_EXTRACT': '0',
        'MEMORY_WIKI_EXTRACT_ENABLED': '0', 'MEMORY_WIKI_EVENT_LEDGER_ENABLED': '0',
        'MEMORY_WIKI_EPISODIC_ENABLED': '0', 'MEMORY_WIKI_OBSERVATIONS_ENABLED': '0',
        'MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE': '0',
        'MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID': SCOPE, 'MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID': SCOPE,
        'MEMORY_WIKI_DOCUMENT_ALLOW_CROSS_SCOPE': '0', 'MEMORY_WIKI_DOCUMENT_ALLOW_SCOPE_MIGRATION': '0',
    }.items():
        monkeypatch.setenv(key, value)
    module, p = peer.load_provider('connector_stage_' + token, home, monkeypatch)
    store = Store(module, p, root)
    assert p._owned_conn is store.db and p._transaction_quarantine is None
    assert module.MemoryWikiProvider.__bases__ == (module.MemoryProvider,)
    assert module.MemoryProvider.__module__ == module.__name__, 'actual standalone fallback required'
    monkeypatch.setattr(store.g, '_extract', store.source_txt_decoder_SOURCE)
    try:
        with store.g._document_profile_scope(p.home):
            assert store.g._document_access_scope(p, SCOPE, SCOPE) == (SCOPE, SCOPE)
            yield store
    finally:
        # Disposal of this fixture AFTER the retained UNKNOWN witnesses is NOT
        # production recovery. Never reset quarantine/admissions or retry owner.
        store.db.set_authorizer(None)
        store.db.close()
        assert not getattr(p, '_graph_reader_connections', {})
        store.witness('fixture_owned_handles_closed', shared=True, private_readers=0)


@pytest.mark.parametrize('generation', ['initial', 'update'])
def test_residue_cannot_be_adopted_by_direct_ingest(stage, generation):
    s = stage
    if generation == 'update':
        s.upsert()
    path = s.path()
    before = s.durable()
    s.replace_file(path, B)
    refused = None
    try:
        s.ingest(path)
    except PermissionError as error:
        refused = type(error).__name__
    after = s.durable()
    value = s.tuple(path)
    s.witness('durable_secondary_adoption_discriminator', generation=generation,
              before_sha256=digest(json.dumps(before, sort_keys=True).encode()),
              after_sha256=digest(json.dumps(after, sort_keys=True).encode()),
              validated_residue_sha256=digest(path.read_bytes()), outcome=value, refusal=refused)
    assert after == before, 'R3-STAGED-CACHE-ADOPTION-01 durable ' + generation + ' adoption/split tuple'
    assert refused == 'PermissionError' and not value['residue_hits']
    assert path.read_bytes() == B.encode(), 'admission must not restore or remove residue'


@pytest.mark.parametrize('automatic', [False, True])
def test_scan_excludes_reserved_subtree_before_cutoff_and_keeps_attachment(stage, monkeypatch, automatic):
    s = stage
    cache = s.p.home / 'cache/documents'
    for number in range(5):
        path = cache / 'connectors' / 'nested' / ('not-a-source-key-' + str(number) + '.txt')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(B, encoding='utf-8')
    tail = cache / 'ordinary-attachment.txt'
    tail.write_text(A, encoding='utf-8')
    os.utime(tail, ns=(946684800_000_000_000, 946684800_000_000_000))
    if automatic:
        monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID', SCOPE)
        monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_AUTO_REPOSITORY_ID', SCOPE)
        monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_AUTO_SCAN_MAX_FILES', '1')
        monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_AUTO_MIN_AGE_SECONDS', '0')
        result = s.g.maybe_ingest_document_cache(s.p, force=True)
    else:
        result = s.g.scan_documents(s.p, dict(root=str(cache), max_files=1, newest_first=True,
                                              scope_id=SCOPE, repository_id=SCOPE, embed=False))
    assert result['discovered'] == result['indexed'] == 1 and result['failed'] == 0, result
    assert result['results'][0]['source_id'] == s.g._source_id(tail)
    assert not s.db.execute("SELECT 1 FROM document_sources WHERE source_path LIKE '%connectors%'").fetchone()
    assert len(s.decodes) == 1


def test_explicit_managed_scan_and_prune_do_not_become_connector_owner(stage):
    s = stage
    s.upsert()
    path = s.path()
    before = s.durable()
    path.unlink()  # A missing committed cache is not an attachment-prune grant.
    result = s.g.scan_documents(s.p, dict(root=str(path.parent), prune_missing=True,
                                         scope_id=SCOPE, repository_id=SCOPE))
    assert result['discovered'] == result['pruned'] == result['missing_existing'] == 0
    assert s.durable() == before


@pytest.mark.parametrize('kind', ['record', 'github_public', 'github_authenticated', 'google_drive', 'api'])
def test_genuine_upsert_first_repeat_revision_and_postcommit_embedding(stage, kind):
    s = stage
    old = s.record(kind=kind)
    first = s.upsert(old)
    path = s.path(old)
    initial = s.coherent(path, old)
    repeat = s.upsert(old)
    assert repeat['status'] == 'unchanged' and repeat['source_id'] == first['source_id']
    assert s.coherent(path, old) == initial
    seen = []
    target = s.g.embed_pending_documents.__code__
    def observe(frame, event, arg):
        if event == 'call' and frame.f_code is target:
            seen.append((s.db.in_transaction, s.tuple(path)))
    previous = sys.getprofile()
    sys.setprofile(observe)
    try:
        new = replace(old, revision='two', text=B, embed=True)
        changed = s.upsert(new)
    finally:
        sys.setprofile(previous)
    coherent = s.coherent(path, new)
    assert changed['revision_id'] != first['revision_id']
    assert seen and all(not pending and value == coherent for pending, value in seen)
    assert s.db.execute("SELECT COUNT(*) FROM external_sources").fetchone()[0] == 1
    assert len(s.decodes) == 2 and all(d['snapshot_sha256'] == d['file_hash'] for d in s.decodes)
    assert s.p._claim_tx_document_stage is None and s.p._transaction_quarantine is None


def test_matching_committed_same_byte_replacement_and_rematerialization(stage, monkeypatch):
    s = stage
    record = s.record()
    result = s.upsert(record)
    path = s.path()
    old_identity = s.g._file_identity(path.stat())
    s.replace_file(path, A)
    new_identity = s.g._file_identity(path.stat())
    assert new_identity != old_identity
    same = s.ingest(path)
    assert same['status'] == 'unchanged' and same['file_identity_updated'] is True
    assert {old_identity, new_identity}.issubset(s.g._file_identity_history(s.db, result['source_id']))
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_CHUNK_CHARS', '1200')
    renewed = s.ingest(path)
    assert renewed['status'] == 'indexed' and renewed['revision_id'] != result['revision_id']
    s.coherent(path, record)
    assert len(s.decodes) == 1, 'validated current extraction cache is allowed'


def test_ordinary_attachment_and_local_file_outside_reserved_namespace(stage):
    s = stage
    path = s.p.home / 'cache/documents/attachments/connectors/ordinary.txt'
    path.parent.mkdir(parents=True)
    path.write_text(A, encoding='utf-8')
    first = s.ingest(path)
    local = s.c.sync_local_file(s.p, dict(path=str(path), scope_id=SCOPE, repository_id=SCOPE))
    assert local['source_id'] == first['source_id']
    row = s.db.execute('SELECT * FROM external_sources').fetchone()
    assert row['source_type'] == 'local_file' and row['content_hash'] == digest(path.read_bytes())
    assert s.ingest(path)['status'] == 'unchanged'


@pytest.mark.parametrize('hook_kind', ['local_file', 'arbitrary', 'detached_record'])
def test_managed_path_cannot_use_local_arbitrary_or_detached_record_hook(stage, hook_kind):
    s = stage
    path = s.path()
    path.write_text(B, encoding='utf-8')
    before = s.durable()
    if hook_kind == 'local_file':
        operation = lambda: s.c.sync_local_file(s.p, dict(path=str(path), scope_id=SCOPE, repository_id=SCOPE))
    else:
        hook = object() if hook_kind == 'arbitrary' else s.c._RecordCommitHook(
            s.p, s.db, source_key=path.stem, uri=s.record().uri, namespace='record',
            source_id=s.g._source_id(path), source_type='record', display_uri=s.record().uri,
            scope_id=SCOPE, repository_id=SCOPE, revision_key=digest(b'two')[:20], content_hash=digest(B.encode()))
        operation = lambda: s.g.ingest_document(s.p, dict(path=str(path)), _commit_hook=hook)
    with pytest.raises((PermissionError, TypeError)):
        operation()
    assert s.durable() == before and not s.decodes and path.read_text(encoding='utf-8') == B


@pytest.mark.parametrize('mismatch', ['external_hash', 'revision_hash', 'document_hash', 'revision_key', 'deleted', 'foreign_owner', 'foreign_scope'])
def test_incoherent_or_unowned_committed_tuple_refuses_without_decode_or_writes(stage, mismatch):
    s = stage
    result = s.upsert()
    path = s.path()
    assignments = {
        'external_hash': ("UPDATE external_sources SET content_hash=?", digest(b'other')),
        'revision_hash': ("UPDATE document_revisions SET file_hash=? WHERE status='active'", digest(b'other')),
        'document_hash': ("UPDATE document_sources SET file_hash=?", digest(b'other')),
        'revision_key': ("UPDATE external_sources SET revision_key=?", 'not-a-revision-digest'),
        'deleted': ("UPDATE external_sources SET status=?", 'deleted'),
        'foreign_owner': ("UPDATE external_sources SET owner_bot_id=?", 'foreign-owner'),
        'foreign_scope': ("UPDATE external_sources SET scope_id=?", 'foreign-scope'),
    }
    sql, value = assignments[mismatch]
    with s.p._claim_transaction(s.db):
        s.db.execute(sql, (value,))
    before = s.durable()
    decoded = len(s.decodes)
    with pytest.raises(PermissionError):
        s.ingest(path)
    assert s.durable() == before and len(s.decodes) == decoded
    assert result['source_id'] == s.g._source_id(path)


def test_strict_cached_reuse_and_replay_keep_matching_positive_and_mismatch_denial(stage):
    s = stage
    result = s.upsert()
    path = s.path()
    adapter = importlib.import_module(s.m.__name__ + '.github_source_adapter')
    reference = s.g._document_source_recovery_reference(s.p, result['source_id'], action='ingest')
    assert adapter._complete_cached_source(s.p, result['source_key'], SCOPE, SCOPE, embed=False)['status'] == 'unchanged'
    assert s.g._replay_document_source_reference(s.p, reference)['status'] == 'restored'
    s.replace_file(path, B)
    before = s.durable()
    with pytest.raises(ValueError, match='connector_cache_requires_download'):
        adapter._complete_cached_source(s.p, result['source_key'], SCOPE, SCOPE, embed=False)
    with pytest.raises((PermissionError, RuntimeError)):
        s.g._replay_document_source_reference(s.p, reference)
    assert s.durable() == before and path.read_text(encoding='utf-8') == B


@pytest.mark.parametrize('seam', ['healthy', 'parser', 'outer_return', 'journal'])
def test_original_managed_admission_survives_parser_and_actual_outer_commit(stage, monkeypatch, seam):
    s = stage
    s.upsert()
    path = s.path()
    before = s.durable()
    seen = []
    def change():
        seen.append(seam)
        s.db.execute("UPDATE external_sources SET revision_key=?", (digest(b'late-other')[:20],))
    if seam == 'parser':
        monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_MAX_UNITS', '101')
        original = s.g._extract
        def decoder(snapshot, args):
            payload = original(snapshot, args)
            with s.p._claim_transaction(s.db, join=True):
                change()
            return payload
        monkeypatch.setattr(s.g, '_extract', decoder)
    if seam == 'journal':
        original = s.p._claim_journal_pending_commit
        def journal(conn):
            value = original(conn)
            if s.p._claim_tx_document_stage[2]:
                change()
            return value
        monkeypatch.setattr(s.p, '_claim_journal_pending_commit', journal)
    def operation():
        with s.p._claim_transaction(s.db):
            s.ingest(path)
            stage_image = s.p._claim_tx_document_stage
            assert stage_image[0] is s.db and stage_image[2] and len(stage_image[2][0][1]) == 7
            if seam == 'outer_return':
                change()
    if seam == 'healthy':
        operation()
        s.coherent(path, s.record())
    else:
        with pytest.raises((PermissionError, RuntimeError), match='document_.*(changed|uncommitted)'):
            operation()
        assert seen and s.durable() == before
    assert s.p._claim_tx_document_stage is None and s.p._transaction_quarantine is None


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('outcome', ['rolled_back', 'unknown', 'committed'])
def test_record_failure_preserves_primary_files_and_exact_unknown_owner(stage, monkeypatch, existing, outcome):
    s = stage
    if existing:
        s.upsert()
    path = s.path()
    before = s.durable()
    primary = RuntimeError('authored record owning callback failure')
    reached = []
    if outcome == 'committed':
        original = s.g._guard_document_output
        def fail(value, *args, **kwargs):
            result = original(value, *args, **kwargs)
            if isinstance(value, dict) and value.get('status') == 'indexed':
                reached.append('postcommit')
                raise primary
            return result
        monkeypatch.setattr(s.g, '_guard_document_output', fail)
    else:
        def fail(conn):
            reached.append('precommit')
            raise primary
        monkeypatch.setattr(s.p, '_claim_journal_pending_commit', fail)
        if outcome == 'unknown':
            def deny_rollback(action, a, b, database, trigger):
                return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and a == 'ROLLBACK' else sqlite3.SQLITE_OK
            s.db.set_authorizer(deny_rollback)
    with pytest.raises(RuntimeError) as captured:
        s.upsert(s.record('two', B))
    assert captured.value is primary and reached
    artifacts = sorted(path.parent.glob('.*.bak'))
    if outcome == 'rolled_back':
        assert s.durable() == before and not s.db.in_transaction
        assert s.p._claim_tx_document_stage is None and s.p._transaction_quarantine is None
        assert (path.read_text(encoding='utf-8') == A) if existing else not path.exists()
        assert not artifacts
    elif outcome == 'committed':
        s.coherent(path, s.record('two', B))
        assert path.read_text(encoding='utf-8') == B and not artifacts
    else:
        owner_stage = s.p._claim_tx_document_stage
        assert s.db.in_transaction and s.p._claim_tx_connection is s.db
        assert owner_stage[0] is s.db and owner_stage[2] and len(owner_stage[2][0][1]) == 7
        assert s.p._transaction_quarantine is s.db and s.p._transaction_primary is primary
        assert s.durable() == before and path.read_text(encoding='utf-8') == B
        assert len(artifacts) == int(existing)
        if existing:
            assert artifacts[0].read_text(encoding='utf-8') == A
        with pytest.raises(RuntimeError):
            s.p._connect()
        assert s.p._claim_tx_document_stage is owner_stage and s.p._transaction_primary is primary
        assert any('UNKNOWN' in note for note in getattr(primary, '__notes__', ()))
    s.witness('actual_record_failure', outcome=outcome, existing=existing,
              primary_identity_preserved=captured.value is primary,
              owned_transaction_pending=s.db.in_transaction,
              exact_owner_retained=s.p._claim_tx_connection is s.db,
              quarantined=s.p._transaction_quarantine is s.db,
              artifact_hashes=[digest(p.read_bytes()) for p in artifacts])


def test_join_cannot_bless_its_own_uncommitted_connector_tuple(stage):
    s = stage
    s.upsert()
    before = s.durable()
    with s.p._claim_transaction(s.db):
        s.db.execute('UPDATE external_sources SET revision_key=?', (digest(b'tentative')[:20],))
        with pytest.raises(PermissionError, match='document_managed_connector_generation_uncommitted'):
            s.ingest(s.path())
        # This is the caller's unrelated write, not an ingest obligation.
        s.db.execute('UPDATE external_sources SET revision_key=?', (digest(b'one')[:20],))
    assert s.durable() == before and not s.p._graph_reader_connections


def test_upsert_cannot_rebase_expected_record_generation_at_late_hook(stage, monkeypatch):
    s = stage
    s.upsert()
    before = s.durable()
    seen = []
    original = s.p._claim_journal_pending_commit
    def journal(conn):
        value = original(conn)
        image = s.p._claim_tx_document_stage
        hook = image[2][0][1][6][1]
        seen.append(hook)
        conn.execute('UPDATE external_sources SET revision_key=?', (digest(b'foreign-generation')[:20],))
        hook.fields['revision_key'] = digest(b'foreign-generation')[:20]
        hook.expected = hook._tuple()
        return value
    monkeypatch.setattr(s.p, '_claim_journal_pending_commit', journal)
    with pytest.raises(PermissionError, match='document_managed_connector_hook_changed'):
        s.upsert(s.record('two', B))
    assert seen and s.durable() == before
    assert s.path().read_text(encoding='utf-8') == A and s.p._transaction_quarantine is None


def test_erased_claim_history_is_not_revived_from_retained_or_residue_cache(stage):
    s = stage
    result = s.upsert(s.record(embed=True))
    claims = s.db.execute("SELECT id,claim FROM claims WHERE source='artifact:document-index' AND status='active'").fetchall()
    assert claims, 'real healthy derivative prerequisite, not a manufactured claim'
    for claim in claims:
        erased = s.p._set_status_by_text(claim['claim'], 'archived', 'SOURCE owner privacy removal', erase_memory_events=True)
        assert erased['privacy_intent_durable'] is True and erased['count'] == 1
    path = s.path()
    assert s.ingest(path)['status'] == 'unchanged'
    embedded = s.g.embed_pending_documents(s.p, dict(source_id=result['source_id']))
    assert embedded['created'] == embedded['reused'] == 0
    assert all(s.db.execute('SELECT status FROM claims WHERE id=?', (r['id'],)).fetchone()[0] == 'archived' for r in claims)
    before = s.durable()
    s.replace_file(path, B)
    with pytest.raises(PermissionError):
        s.ingest(path)
    assert s.durable() == before
    fresh = replace(s.record(), uri='urn:connector-stage:fresh', text='MapleArchive preserves a newly approved daily ledger with explicit ownership and verified publication checks.')
    s.upsert(fresh)
    s.coherent(s.path(fresh), fresh)
