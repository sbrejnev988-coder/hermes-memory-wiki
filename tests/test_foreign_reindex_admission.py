"""ADJ-REINDEX-FOREIGN-01 genuine SPI regressions; never SOURCE admission.

Reuse the shipped, key-free direct-component peer. Requires genuine SDK and
native fixture admission. The stdlib-only companion is foreign_reindex_cases.py.
"""
from __future__ import annotations
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location('foreign_reindex_claim_peer',
    Path(__file__).parent / 'ci_owned/claim_embedding_fixture.py')
f = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = f
_SPEC.loader.exec_module(f)
claim_embedding_case = f.claim_embedding_case
FOREIGN_COPY_ID = 'claim-foreign-copy'
FOREIGN_COPY_TEXT = 'CANARY_FOREIGN_COPY_MUST_NOT_LEAVE_SQLITE'


def seed_foreign_copy(case):
    f.seed(case)  # A visible row prevents the already-complete fast path.
    case.claim(FOREIGN_COPY_ID, text=FOREIGN_COPY_TEXT, visibility='private',
               origin_bot_id='foreign-owner', origin_session_id='foreign-session')
    case.ready()
    m = case.m
    row = case.conn.execute('SELECT * FROM claims WHERE id=?', (FOREIGN_COPY_ID,)).fetchone()
    source = m._physical_collection_name()
    manifest = m._manifest_hash(m._embedding_manifest())
    payload = m._qdrant_claim_payload(FOREIGN_COPY_ID, FOREIGN_COPY_TEXT, row, manifest_hash=manifest)
    m._record_claim_vector_target(case.conn, FOREIGN_COPY_ID, collection=source,
                                 manifest_hash=manifest, status='active', indexed_at=17)
    case.conn.commit()
    case.points[source] = {str(m._qdrant_point_id(FOREIGN_COPY_ID)): {
        'id': m._qdrant_point_id(FOREIGN_COPY_ID), 'vector': [0.5] * 8, 'payload': payload}}
    return source


def change_foreign_copy(case, kind):
    if kind == 'owner':
        case.p.on_session_switch('changed-owner-session', reset=False)
        return
    if kind == 'generation':
        case.m._embedding_cache_clear()
        return
    if kind.startswith('erasure'):
        with case.p._claim_transaction(case.conn):
            seq = case.p._privacy_erasure.append(case.p,
                FOREIGN_COPY_TEXT if kind == 'erasure-text' else '',
                claim_ids=[FOREIGN_COPY_ID] if kind == 'erasure-id' else [],
                event_ids=[], episode_ids=[], episode_surface='')
            if kind != 'erasure-pending':
                case.conn.execute("UPDATE meta SET value=? WHERE key='privacy_erasure_applied_seq'", (str(seq),))
        return
    writer = sqlite3.connect(str(case.path))
    try:
        if kind == 'delete':
            writer.execute('DELETE FROM claims WHERE id=?', (FOREIGN_COPY_ID,))
        elif kind == 'retire':
            writer.execute("UPDATE claims SET status='retired' WHERE id=?", (FOREIGN_COPY_ID,))
        elif kind == 'revision':
            writer.execute('UPDATE claims SET memory_revision=memory_revision+1 WHERE id=?', (FOREIGN_COPY_ID,))
        elif kind == 'acl':
            writer.execute("UPDATE claims SET visibility_scope='bot' WHERE id=?", (FOREIGN_COPY_ID,))
        elif kind == 'canonical-ABA':
            writer.execute("UPDATE claims SET origin_bot_id='transient-owner' WHERE id=?", (FOREIGN_COPY_ID,))
            writer.execute("UPDATE claims SET origin_bot_id='foreign-owner' WHERE id=?", (FOREIGN_COPY_ID,))
        elif kind == 'registry':
            writer.execute("UPDATE claim_vector_targets SET status='delete_pending' WHERE claim_id=?", (FOREIGN_COPY_ID,))
        elif kind == 'registry-ABA':
            old = writer.execute('SELECT updated_at FROM claim_vector_targets WHERE claim_id=?', (FOREIGN_COPY_ID,)).fetchone()[0]
            writer.execute('UPDATE claim_vector_targets SET updated_at=updated_at+1 WHERE claim_id=?', (FOREIGN_COPY_ID,))
            writer.execute('UPDATE claim_vector_targets SET updated_at=? WHERE claim_id=?', (old, FOREIGN_COPY_ID))
        else:
            raise AssertionError('unregistered_foreign_copy_change')
        writer.commit()
    finally:
        writer.close()


@contextmanager
def foreign_copy_seam(case, phase, effect):
    m = case.m
    target = m._semantic_response_json if phase == 'source-response' else m._semantic_request_bytes
    def selected(frame, event, arg):
        parent = frame.f_back
        if event != 'return' or parent is None or parent.f_code is not m._qdrant_req.__code__:
            return False
        local = parent.f_locals
        body = local.get('body') or {}
        if phase == 'put-prepared':
            return (local.get('method') == 'PUT' and any(
                p.get('payload', {}).get('claim_id') == FOREIGN_COPY_ID for p in body.get('points', [])))
        return (local.get('method') == 'POST' and body.get('with_vector') is True
                and body.get('ids') == [m._qdrant_point_id(FOREIGN_COPY_ID)])
    with f.at(case, target.__code__, selected, effect) as seen:
        yield seen


@pytest.mark.parametrize('phase', ['source-prepared', 'source-response', 'put-prepared'])
@pytest.mark.parametrize('kind', ['retire', 'delete', 'revision', 'acl', 'canonical-ABA',
                                 'registry', 'registry-ABA', 'erasure-id', 'erasure-text',
                                 'erasure-pending', 'owner', 'generation'])
def test_foreign_copy_original_lifetime(claim_embedding_case, phase, kind):
    with f.Fixture() as case:
        seed_foreign_copy(case)
        def revoke():
            assert case.calls['put'] == 1  # Only the visible control was sent.
            change_foreign_copy(case, kind)
        with foreign_copy_seam(case, phase, revoke) as seen:
            out = f.public(case, scoped=False)
        assert seen, 'foreign_copy_fault_seam_not_reached'
        assert case.calls['put'] == 1, 'revoked_foreign_projection_reached_PUT'
        assert out['status'] == 'partial' and out['alias_switched'] is False
        assert FOREIGN_COPY_ID in out['failed_ids'] and out['failed'] == 1
        assert FOREIGN_COPY_TEXT not in json.dumps(case.requests)
        assert case.conn.execute('SELECT status FROM reindex_jobs WHERE target_collection=?',
                                 (out['collection'],)).fetchone()[0] == 'running'


def test_foreign_copy_healthy_exact_intent_and_sole_source(claim_embedding_case):
    with f.Fixture() as case:
        source = seed_foreign_copy(case)
        original = []
        def before_source():
            # Destination == source: its ONLY active registry row must survive
            # until the genuine verifier has received the compatible vector.
            assert case.conn.execute('SELECT status FROM claim_vector_targets WHERE claim_id=?',
                                     (FOREIGN_COPY_ID,)).fetchone()[0] == 'active'
        def after_intent():
            assert case.conn.execute('SELECT status FROM claim_vector_targets WHERE claim_id=?',
                                     (FOREIGN_COPY_ID,)).fetchone()[0] == 'write_pending'
            assert not case.conn.in_transaction
        sql = []
        case.conn.set_trace_callback(sql.append)
        try:
            with foreign_copy_seam(case, 'source-response', before_source) as fetched:
                with foreign_copy_seam(case, 'put-prepared', after_intent) as pending:
                    with f.at(case, case.m._DisclosureFence.index_copy.__code__,
                              lambda fr, ev, a: ev == 'return' and a is not None,
                              lambda: original.append(True)):
                        out = f.public(case, scoped=False)
        finally:
            case.conn.set_trace_callback(None)
        assert fetched and pending and original and out['status'] == 'completed'
        assert out['failed'] == 0 and case.calls['put'] == 2 and case.calls['post'] == 1
        point = case.points[source][str(case.m._qdrant_point_id(FOREIGN_COPY_ID))]
        assert point['vector'] == [0.5] * 8 and 'claim' not in point['payload']
        assert FOREIGN_COPY_TEXT not in json.dumps(case.requests)
        assert not any('SELECT * FROM claims' in statement and FOREIGN_COPY_ID in statement for statement in sql)
        assert not any('SELECT normalized_claim FROM claims' in statement and FOREIGN_COPY_ID in statement for statement in sql)


@pytest.mark.parametrize('kind', ['absent', 'manifest', 'revision', 'vector'])
def test_foreign_copy_unusable_stays_partial(claim_embedding_case, kind):
    with f.Fixture() as case:
        source = seed_foreign_copy(case)
        point = case.points[source][str(case.m._qdrant_point_id(FOREIGN_COPY_ID))]
        if kind == 'absent':
            case.conn.execute('DELETE FROM claim_vector_targets WHERE claim_id=?', (FOREIGN_COPY_ID,))
            case.conn.commit()
        elif kind == 'manifest':
            point['payload']['manifest_hash'] = 'incompatible'
        elif kind == 'revision':
            point['payload']['memory_revision'] = -1
        else:
            point['vector'] = [0.5]
        out = f.public(case, scoped=False)
        assert out['status'] == 'partial' and out['alias_switched'] is False
        assert FOREIGN_COPY_ID in out['failed_ids'] and case.calls['put'] == 1
        assert FOREIGN_COPY_TEXT not in json.dumps(case.requests)
