"""Tests-only recovery discovery. Real native package; authored, synthetic SQLite rows."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import pytest
import memory_wiki as plugin
from memory_wiki import document_knowledge_graph as graph

OUT = Path(os.environ['RECOVERY_DIAGNOSTIC_OUT'])
MARKER = 'BENIGN_SYNTH_Я✓_"quoted"_\\route_6ed1'
WINDOWS_PATH = 'C:\\synthetic-only\\' + MARKER + '\\source.md'
SAFE_TEXT = 'Synthetic recovery evidence remains a literal source quotation.'
SUMMARY_KEYS = {'success', 'status', 'source_id', 'revision_id', 'repository_id',
                'processed', 'indexed', 'unchanged', 'failed', 'deleted', 'deduplicated',
                'invalidated', 'pending_before', 'pending_after', 'created', 'reused',
                'count', 'chunks', 'units', 'edges', 'snapshot_hash', 'event_id'}


def save(name, value):
    with (OUT / (name + '.json')).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def scalar_strings(value, depth=0):
    """Walk keys/scalars, recursively decode serialized JSON and JSON escapes."""
    if depth > 12:
        raise AssertionError('Diagnostic JSON depth exceeded')
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from scalar_strings(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            yield from scalar_strings(v, depth + 1)
    elif isinstance(value, str):
        yield value
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            decoded = value
        if decoded != value:
            yield from scalar_strings(decoded, depth + 1)
        if '\\u' in value or '\\"' in value or '\\\\' in value:
            # Do not unicode_escape-decode UTF-8; JSON string decoding preserves Unicode.
            try:
                decoded = json.loads('"' + value + '"')
            except ValueError:
                decoded = value
            if decoded != value:
                yield from scalar_strings(decoded, depth + 1)


def journal_checks(provider, start):
    lines = provider.journal_path.read_text(encoding='utf-8').splitlines()[start:]
    events = [json.loads(line) for line in lines]
    strings = [s for event in events for field in ('payload', 'result', 'error')
               for s in scalar_strings(event.get(field))]
    leaks = sum(MARKER in s or WINDOWS_PATH in s for s in strings)
    summaries = [e['result']['summary'] for e in events
                 if isinstance(e.get('result'), dict) and 'summary' in e['result']]
    allowlisted = all(set(s) <= SUMMARY_KEYS and all(type(v) in
                      (str, int, float, bool, type(None)) for v in s.values()) for s in summaries)
    pairs = all(set(e['payload']) <= {'schema', 'operation_id', 'operation', 'nonmutating'}
                and all(type(v) in (str, int, float, bool, type(None)) for v in e['payload'].values())
                for e in events)
    return {'events': len(events), 'phases': [e['phase'] for e in events],
            'decoded_scalars': len(strings), 'marker_leaks': leaks,
            'summary_scalar_allowlist': allowlisted, 'request_pair_scalar_allowlist': pairs}


def start_line(provider):
    return len(provider.journal_path.read_text(encoding='utf-8').splitlines())


@pytest.fixture(scope='module')
def provider():
    home = OUT / 'home'
    p = plugin.MemoryWikiProvider()
    p.initialize('synthetic-recovery-diagnostic', hermes_home=str(home),
                 agent_context='test', bot_id='synthetic-recovery-bot', project_id='diagnostic')
    assert p.__class__.__bases__ == (plugin.MemoryProvider,)
    assert p.db_path.resolve().is_relative_to(OUT.resolve())
    graph.install_document_graph_schema(p._connect())
    yield p
    # Explicit fixture-owned finalization, not a production lifetime/cleanup oracle.
    if p._conn is not None:
        p._conn.close()
        p._conn = None


def seed_source(provider, label, count=1, large=False):
    """Author graph state via real SQLite schema, native identity writer and no parser."""
    path = OUT / 'home/cache/documents' / (label + '.md')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SAFE_TEXT, encoding='utf-8')
    sid = graph._source_id(path)
    uid, cid, rid = 'unit-' + label, 'chunk-' + label, 'revision-' + label
    raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    conn = provider._connect()
    with conn:
        conn.execute('INSERT INTO document_sources(source_id,source_path,scope_id,repository_id,title,display_name,file_hash,revision_id,parser,parser_version,status,active,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,1,1,1,?)',
                     (sid, str(path), 'diagnostic', 'diagnostic', MARKER, MARKER, raw_hash, rid,
                      'synthetic-fixture', '1', 'ok', json.dumps({'source_text': MARKER})))
        conn.execute('INSERT INTO document_units(unit_id,source_id,revision_id,unit_type,anchor,ordinal,unit_text,content_hash,active,updated_at) VALUES(?,?,?,?,?,1,?,?,1,1)',
                     (uid, sid, rid, 'paragraph', 'p:1', SAFE_TEXT, raw_hash))
        conn.execute('INSERT INTO document_units_fts(source_id,unit_id,unit_type,title,anchor,unit_text) VALUES(?,?,?,?,?,?)',
                     (sid, uid, 'paragraph', 'Fixture', 'p:1', SAFE_TEXT))
        conn.execute('INSERT INTO document_chunks(chunk_id,source_id,revision_id,scope_id,repository_id,chunk_text,embedding_text,content_hash,active,updated_at) VALUES(?,?,?,?,?,?,?,?,1,1)',
                     (cid, sid, rid, 'diagnostic', 'diagnostic', SAFE_TEXT, SAFE_TEXT, raw_hash))
        conn.execute('INSERT INTO document_chunks_fts(source_id,chunk_id,title,anchors,chunk_text) VALUES(?,?,?,?,?)',
                     (sid, cid, 'Fixture', 'p:1', SAFE_TEXT))
        fixture_volume = 100 + int(hashlib.sha256(label.encode()).hexdigest()[:6], 16)
        identities = [(123456789123456789 + i, 987654321987654321 + i) if large
                      else (fixture_volume, 10000 + i) for i in range(count)]
        for ident in identities:
            assert graph._remember_file_identity(conn, sid, ident)
    return sid, identities, raw_hash


def state(provider, sid):
    conn = provider._connect()
    tables = ('document_sources', 'document_units', 'document_chunks', 'document_edges',
              'document_revisions', 'document_units_fts', 'document_chunks_fts', 'document_graph_meta')
    rows = {}
    for table in tables:
        data = [list(row) for row in conn.execute('SELECT * FROM ' + table).fetchall()]
        rows[table] = {'count': len(data), 'sha256': hashlib.sha256(
            json.dumps(sorted(data, key=repr), ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()}
    pointer = provider._latest_journal_checkpoint()
    p = Path(pointer['path']) if pointer else None
    return {'tables': rows, 'source_active': int(conn.execute(
        'SELECT active FROM document_sources WHERE source_id=?', (sid,)).fetchone()[0]),
        'target_unit_fts': int(conn.execute('SELECT count(*) FROM document_units_fts WHERE source_id=?', (sid,)).fetchone()[0]),
        'target_chunk_fts': int(conn.execute('SELECT count(*) FROM document_chunks_fts WHERE source_id=?', (sid,)).fetchone()[0]),
        'identity_count': len(graph._file_identity_history(conn, sid)),
        'checkpoint_pointer': {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} if p else None,
        'sqlite_integrity': conn.execute('PRAGMA quick_check').fetchone()[0],
        'foreign_key_violations': len(conn.execute('PRAGMA foreign_key_check').fetchall())}


def test_01_recursive_scanner_control():
    wrapped = json.dumps({'error': WINDOWS_PATH, 'nested': json.dumps({'value': MARKER}, ensure_ascii=True)}, ensure_ascii=True)
    assert WINDOWS_PATH not in wrapped and MARKER not in wrapped
    strings = list(scalar_strings(json.loads(wrapped)))
    assert any(WINDOWS_PATH in s for s in strings)
    assert any(MARKER in s for s in strings)
    save('scanner-control', {'raw_substring_false_negative': True, 'decoded_counterexample_detected': True,
                             'synthetic_only': True, 'unicode_preserved': True})


def test_02_actual_public_tool_failure_decoded_secrecy(provider):
    n = start_line(provider)
    result = provider.handle_tool_call('memory_wiki_document_ingest', {'path': WINDOWS_PATH, 'embed': False})
    parsed = json.loads(result) if isinstance(result, str) else result
    observed = journal_checks(provider, n)
    observed.update(producer='MemoryWikiProvider.handle_tool_call -> ingest_document/_allowed_path -> native tool_error',
                    native_tool_success=parsed.get('success'), parser_launches=0)
    save('public-tool-error-decoded', observed)
    assert parsed['success'] is False
    assert observed['phases'] == ['before', 'error']
    assert observed['marker_leaks'] == 0
    assert observed['summary_scalar_allowlist'] and observed['request_pair_scalar_allowlist']


def test_03_actual_raised_mutation_failure_decoded_secrecy(provider):
    n = start_line(provider)
    with pytest.raises(ValueError, match='not found'):
        provider._journal_operation('memory_wiki_document_delete', {'source_id': MARKER, 'path': WINDOWS_PATH},
            lambda: graph.delete_document(provider, {'source_id': MARKER}))
    observed = journal_checks(provider, n)
    observed.update(producer='MemoryWikiProvider._journal_operation -> document_knowledge_graph.delete_document',
                    native_exception='ValueError')
    save('raised-mutation-error-decoded', observed)
    assert observed['phases'] == ['before', 'error'] and observed['marker_leaks'] == 0
    assert observed['summary_scalar_allowlist'] and observed['request_pair_scalar_allowlist']


def test_04_real_delete_summary_and_reference_decoded_secrecy(provider):
    sid, _, raw_hash = seed_source(provider, 'summary-safe')
    n = start_line(provider)
    result = json.loads(provider.handle_tool_call('memory_wiki_document_delete', {'source_id': sid}))
    observed = journal_checks(provider, n)
    observed.update(producer='public document_delete -> real SQLite transaction -> native summary/reference/checkpoint',
                    source_text_omitted=True, raw_file_hash_requirement='preserved, not replaced by redaction assertion')
    events = [json.loads(s) for s in provider.journal_path.read_text(encoding='utf-8').splitlines()[n:]]
    after = next(e for e in events if e['phase'] == 'after')
    observed['raw_file_hash_preserved'] = after['result']['recovery']['references'][0]['file_hash'] == raw_hash
    save('success-summary-decoded', observed)
    assert result['success'] is True and result['status'] == 'deleted'
    assert observed['marker_leaks'] == 0
    assert observed['summary_scalar_allowlist'] and observed['request_pair_scalar_allowlist']
    assert observed['raw_file_hash_preserved']


def test_05_existing_char_limit_rejects_before_commit_and_retains_history(provider):
    # Actual fixed production reader/writer limit, not a fabricated config or monkeypatch.
    assert graph._MAX_FILE_IDENTITY_HISTORY_CHARS == 12000
    sid, identities, raw_hash = seed_source(provider, 'char-limit', count=299, large=True)
    cp = provider._journal_checkpoint('diagnostic-near-char-cap')
    saved = json.loads(Path(cp['path']).read_text(encoding='utf-8'))
    history = next(r['value'] for r in saved['tables']['document_graph_meta'] if r['key'] == 'file_identities:' + sid)
    assert json.loads(history) == [list(i) for i in identities]
    assert next(r['file_hash'] for r in saved['tables']['document_sources'] if r['source_id'] == sid) == raw_hash
    before = state(provider, sid)
    rejected = (123456789123456789 + 299, 987654321987654321 + 299)
    with pytest.raises(RuntimeError, match='checkpoint-safe limit'):
        with provider._connect() as conn:
            graph._remember_file_identity(conn, sid, rejected)
    after = state(provider, sid)
    owner_absent = provider._connect().execute('SELECT 1 FROM document_graph_meta WHERE key=?',
        ('file_identity_owner:' + str(rejected[0]) + ':' + str(rejected[1]),)).fetchone() is None
    save('char-overflow-state', {'producer': 'native _remember_file_identity inside real SQLite transaction',
          'before': before, 'after': after, 'retained_previous_identity_count': len(identities),
          'rejected_owner_absent': owner_absent, 'checkpoint_near_cap_exact': True,
          'history_chars': len(history), 'actual_limit': graph._MAX_FILE_IDENTITY_HISTORY_CHARS,
          'fixture_limit_override': None, 'ingest_parser_integration': 'not exercised; process contracts forbidden'})
    assert before == after and owner_absent
    assert graph._file_identity_history(provider._connect(), sid) == set(identities)


def test_06_journal_history_overflow_must_refuse_before_source_index_pointer_commit(provider):
    # 501 short identities are valid under the writer's 12000-char cap, but exceed
    # the actual recovery reference / JSONL list cap of 500. No protection disabled.
    sid, identities, _ = seed_source(provider, 'list-limit', count=501)
    stored = provider._connect().execute('SELECT value FROM document_graph_meta WHERE key=?', ('file_identities:' + sid,)).fetchone()[0]
    assert len(stored) < graph._MAX_FILE_IDENTITY_HISTORY_CHARS
    provider._journal_checkpoint('diagnostic-before-list-overflow')
    before = state(provider, sid)
    n = start_line(provider)
    result = json.loads(provider.handle_tool_call('memory_wiki_document_delete', {'source_id': sid}))
    after = state(provider, sid)
    observed = journal_checks(provider, n)
    capture_refused = 'recovery reference' in str(result.get('error', ''))
    save('list-overflow-state', {'producer': 'public native document_delete -> real delete_document callback -> _document_source_recovery_reference',
          'before': before, 'after': after, 'native_tool_success': result.get('success'),
          'reference_capture_refused': capture_refused, 'journal': observed,
          'history_entries': len(identities), 'history_chars': len(stored), 'actual_journal_list_cap': 500,
          'actual_checkpoint_char_cap': graph._MAX_FILE_IDENTITY_HISTORY_CHARS,
          'fixture_limit_override': None, 'scope': 'authored valid synthetic identity metadata; no physical 501-file/parser proof'})
    assert result['success'] is False and capture_refused
    assert observed['phases'] == ['before', 'error'] and observed['marker_leaks'] == 0
    assert before == after, 'BLOCKER: history-cap refusal follows committed source/FTS deletion; checkpoint pointer retained'
