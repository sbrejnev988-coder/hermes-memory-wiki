"""Genuine SDK + SQLite FTS/terminal regression; no stand-in provider or guard.

Called by the owned native packet after ordinary MemoryManager initialization.
All SQL operates only on authored synthetic stores. No quarantine is cleared.
"""
from __future__ import annotations
import json
import sqlite3
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import memory_wiki as wiki
from agent.memory_provider import MemoryProvider, spawn_context_thread
from agent.memory_manager import MemoryManager
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from memory_wiki.code_knowledge_graph import _open_graph_writer_connection, _close_graph_writer_connection

QUERY = 'Лазурный маяк керамические этикетки'
CLAIM = 'Пользователь предпочитает овальные керамические этикетки для проекта Лазурный маяк.'


def public(manager, name='memory_wiki_query', **args):
    return json.loads(manager.handle_tool_call(name, {'query': QUERY, 'limit': 3, **args}))


def dirty_fts(provider, *, rows=True):
    """Explicit owned fixture corruption, not a simulated repair implementation."""
    c = provider._conn
    with provider._claim_transaction(c):
        if rows:
            c.execute('DELETE FROM claims_fts')
        c.execute("UPDATE meta SET value='stale' WHERE key='claims_fts_format'")
    assert not c.in_transaction and provider._transaction_quarantine is None


def accounting(provider, cid):
    c = provider._conn
    return {
        'claim': tuple(c.execute('SELECT access_count,recall_count,last_recalled FROM claims WHERE id=?', (cid,)).fetchone()),
        'recall_events': c.execute('SELECT count(*) FROM recall_events WHERE claim_id=?', (cid,)).fetchone()[0],
        'feedback': c.execute('SELECT count(*) FROM recall_feedback WHERE claim_id=?', (cid,)).fetchone()[0],
        'audits': c.execute('SELECT count(*) FROM audit_log').fetchone()[0],
    }


def run_fts_packet(provider, manager, root, checkpoint):
    assert type(provider).__bases__ == (MemoryProvider,)
    assert provider._lifecycle_state == 'ready'
    assert provider._transaction_quarantine is None
    c = provider._conn
    out = []
    saved = json.loads(manager.handle_tool_call('memory_wiki_add_claim', {
        'claim': CLAIM, 'topic': 'preferences',
        'evidence': 'Синтетическое авторское предпочтение для изолированного теста.',
        'confidence': .8, 'salience': .75,
    }))
    assert saved.get('state') == 'stored' and saved.get('immediately_recallable') is True
    cid = saved['id']
    assert cid.startswith('c_')
    checkpoint('authored_stored', {'id': cid})

    def query(case, *, stale=True, recall=False):
        before = accounting(provider, cid)
        payload = public(manager, 'memory_wiki_recall' if recall else 'memory_wiki_query',
                         **({'mode': 'fast'} if recall else {'include_stale': stale, 'mode': 'fts'}))
        rows = payload.get('items', []) if recall else payload.get('claims', [])
        assert not payload.get('error'), 'canonical_query_error'
        assert any(row.get('id') == cid for row in rows), 'canonical_authored_output_empty'
        assert payload.get('disclosure_status') != 'withheld'
        after = accounting(provider, cid)
        assert after['claim'][0] > before['claim'][0]
        assert after['claim'][1] > before['claim'][1]
        assert after['recall_events'] > before['recall_events']
        assert after['feedback'] > before['feedback']
        assert c is provider._conn is provider._owned_conn
        assert not c.in_transaction and provider._transaction_quarantine is None
        assert provider._claim_tx_connection is None and provider._claim_tx_thread is None
        assert provider._lifecycle_state == 'ready'
        searches = payload.get('retrieval_receipt', {}).get('searches', [])
        assert searches and any(s.get('lexical', {}).get('kind') == 'fts5' for s in searches)
        checkpoint(case, {'count': len(rows), 'accounting_committed': True,
                          'lexical_kinds': [s.get('lexical', {}).get('kind') for s in searches]})
        out.append(case)

    mode = public(manager, 'memory_wiki_query_mode')
    assert not mode.get('error')
    query('current_canonical_query_include_stale_true')
    query('current_canonical_query_include_stale_false', stale=False)
    query('current_fast_recall', recall=True)

    dirty_fts(provider)
    checkpoint('dirty_fts_before_public_query', {'in_transaction': c.in_transaction})
    query('dirty_fts_real_rebuild_canonical_query', stale=False)
    assert c.execute("SELECT value FROM meta WHERE key='claims_fts_format'").fetchone()[0] == 'v3'
    assert c.execute('SELECT count(*) FROM claims_fts').fetchone()[0] > 0
    assert int(c.execute("SELECT value FROM meta WHERE key='fts_latest_revision'").fetchone()[0]) >= provider._meta_int('memory_revision')

    dirty_fts(provider)
    query('dirty_fts_real_rebuild_fast_recall', recall=True)
    dirty_fts(provider, rows=False)
    query('matching_rows_stale_marker_refresh', stale=False)
    text = manager.prefetch_all(QUERY, session_id=provider.session_id)
    assert 'Лазурный маяк' in text
    assert provider._transaction_quarantine is None and not c.in_transaction
    out.append('normal_prefetch_after_real_repair')
    checkpoint(out[-1], {'nonempty': True})
    return out, cid


RETAINED_UNKNOWN = []


@contextmanager
def terminal_hook(provider, function, callback):
    """Diagnostic child only: real terminal seam, never SDK/class replacement."""
    prior = sys.getprofile()
    done = False
    terminal_file = str(Path(wiki.__file__).with_name('disclosure_fence.py'))

    def observe(frame, event, arg):
        nonlocal done
        if prior is not None:
            prior(frame, event, arg)
        if (not done and event == 'call' and frame.f_code.co_filename == terminal_file
                and frame.f_code.co_name == function):
            delivery = frame.f_locals.get('self')
            if delivery is not None and getattr(delivery, 'provider', None) is provider:
                done = True
                callback(delivery)
    sys.setprofile(observe)
    try:
        yield
        assert done, 'actual_terminal_seam_not_reached'
    finally:
        sys.setprofile(prior)


def run_negative_packet(provider, manager, root, checkpoint):
    c = provider._conn
    cid = c.execute('SELECT id FROM claims WHERE claim=?', (CLAIM,)).fetchone()[0]
    results = []

    # This exact factory, not a same-path/UUID connection, issues the native
    # private handle. Claim/revision/FTS triggers survive its context completion.
    revision = provider._meta_int('memory_revision')
    writer, owned = _open_graph_writer_connection(provider)
    assert owned and writer is not c
    old_cursor = writer.cursor()
    try:
        with writer:
            private_id = provider._add_claim(
                'Пользователь предпочитает бирюзовые керамические этикетки для проекта Лазурный маяк.',
                'preferences', 'Синтетическое авторское предпочтение.', 'model_tool:claim', .8, .75,
                conn=writer, visibility_scope='chat')
            assert private_id.startswith('c_')
            assert provider._claim_tx_connection is writer
            assert provider._claim_tx_thread == threading.get_ident()
        assert not writer.in_transaction and writer._graph_state == 'expired'
        for execute in (writer.execute, old_cursor.execute):
            try:
                execute('SELECT 1')
            except RuntimeError as exc:
                assert exc.args[0] == 'graph_writer_lifetime_expired'
            else:
                raise AssertionError('expired_native_private_writer_admitted')
    finally:
        _close_graph_writer_connection(writer, owned)
    assert writer._graph_state == 'closed' and writer not in provider._graph_writer_connections
    assert provider._meta_int('memory_revision') > revision
    assert any(row['id'] == private_id for row in public(manager).get('claims', []))
    results.append('genuine_factory_private_claim_revision_and_expiry')

    foreign = sqlite3.connect(str(provider.db_path), check_same_thread=False)
    try:
        try:
            with provider._claim_transaction(foreign, begin='EXCLUSIVE'):
                raise AssertionError('same_path_foreign_handle_admitted')
        except RuntimeError as exc:
            assert exc.args[0] == 'claim_mutation_transaction_not_owned'
        assert not foreign.in_transaction and provider._transaction_quarantine is None
    finally:
        foreign.close()
    results.append('same_path_unissued_native_connection_denied')

    # Exact active terminal ownership is thread-bound. A real second thread
    # cannot borrow the actual canonical transaction's original fence.
    def wrong_thread(delivery):
        assert delivery.phase == 'owned'
        fence = delivery.fences[0]
        assert delivery.owns_snapshot(fence)
        values = []
        thread = spawn_context_thread(lambda: values.append(delivery.owns_snapshot(fence)),
                                      name='owned-terminal-wrong-thread', daemon=False)
        thread.start(); thread.join(3)
        assert not thread.is_alive() and values == [False]
    with terminal_hook(provider, '_apply', wrong_thread):
        assert public(manager).get('claims')
    results.append('real_terminal_wrong_thread_original_fence_denied')

    def terminal_exclusive_denied(delivery):
        assert delivery.phase == 'prepare' and not c.in_transaction
        try:
            with provider._claim_transaction(c, begin='EXCLUSIVE', _terminal=delivery):
                raise AssertionError('exclusive_mode_admitted_as_terminal')
        except wiki._DeliveryWithheld as exc:
            assert exc.args[0] == 'terminal_transaction_owner_unproven'
        assert not c.in_transaction and provider._claim_tx_connection is None
    with terminal_hook(provider, 'commit', terminal_exclusive_denied):
        assert public(manager).get('claims')
    results.append('exclusive_writer_mode_does_not_grant_terminal_admission')

    # Authorizer DENY is a genuine native DDL failure. SQLite rollback restores
    # the old FTS/table/triggers; there is no post-refusal cleanup commit.
    master = c.execute("SELECT type,name,sql FROM sqlite_master WHERE name LIKE 'claims_fts%' OR type='trigger' ORDER BY type,name").fetchall()
    before = [tuple(r) for r in master]
    temp_before = [tuple(r) for r in c.execute('SELECT type,name,sql FROM sqlite_temp_master ORDER BY type,name')]
    denied = []
    def deny_create(action, first, second, database, trigger):
        if action == sqlite3.SQLITE_CREATE_VTABLE:
            denied.append(action)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    c.set_authorizer(deny_create)
    try:
        try:
            provider._rebuild_fts()
        except sqlite3.DatabaseError as exc:
            assert not c.in_transaction and provider._transaction_quarantine is None
            assert provider._transaction_primary is None
        else:
            raise AssertionError('native_ddl_denial_not_propagated')
    finally:
        c.set_authorizer(None)
    after = [tuple(r) for r in c.execute("SELECT type,name,sql FROM sqlite_master WHERE name LIKE 'claims_fts%' OR type='trigger' ORDER BY type,name")]
    assert denied and before == after
    assert temp_before == [tuple(r) for r in c.execute('SELECT type,name,sql FROM sqlite_temp_master ORDER BY type,name')]
    assert public(manager).get('claims')
    results.append('native_fts_ddl_deny_known_rollback_preserves_schema')

    # A native trigger side effect is not one of the terminal's measured own
    # effects. The real canonical result is withheld and all accounting rolls back.
    with provider._claim_transaction(c):
        c.execute("CREATE TRIGGER owned_terminal_unaccounted AFTER UPDATE OF access_count ON claims BEGIN INSERT OR REPLACE INTO meta(key,value) VALUES('owned_unaccounted','1'); END")
    before = accounting(provider, cid)
    payload = public(manager)
    assert not payload.get('claims') and payload.get('disclosure_status') == 'withheld'
    assert accounting(provider, cid) == before
    assert c.execute("SELECT 1 FROM meta WHERE key='owned_unaccounted'").fetchone() is None
    assert not c.in_transaction and provider._transaction_quarantine is None
    with provider._claim_transaction(c):
        c.execute('DROP TRIGGER owned_terminal_unaccounted')
    results.append('real_trigger_audit_counter_effect_fence_withheld_rollback')

    # Primary cancellation is not rewritten to success or generic UNKNOWN.
    # Raised only by an owned diagnostic hook at the real pre-effect seam.
    cancellation = KeyboardInterrupt('owned_terminal_cancel')
    before = accounting(provider, cid)
    def cancel(delivery):
        raise cancellation
    try:
        with terminal_hook(provider, '_apply', cancel):
            public(manager)
    except KeyboardInterrupt as caught:
        assert caught is cancellation
    else:
        raise AssertionError('primary_cancellation_not_propagated')
    assert accounting(provider, cid) == before
    assert not c.in_transaction and provider._transaction_quarantine is None
    assert public(manager).get('claims')
    results.append('canonical_cancellation_exact_primary_known_rollback')

    # Late erasure belongs to this exact registered/importer home. Exercise
    # its genuine original carrier without turning a different, unqualified
    # profile-home cache generation into a synthetic positive fixture.
    before = accounting(provider, cid)
    def erase(delivery):
        provider._privacy_erasure.append(provider, wiki.normalize_claim(CLAIM), claim_ids=[cid],
                                         event_ids=[], episode_ids=[], episode_surface='')
    with terminal_hook(provider, 'commit', erase):
        payload = public(manager)
    assert not payload.get('claims') and payload.get('disclosure_status') == 'withheld'
    assert accounting(provider, cid) == before
    assert provider._transaction_quarantine is None and not c.in_transaction
    results.append('late_real_erasure_ledger_original_carrier_withheld')
    # Apply only the authored fixture's real erasure intent through its existing
    # owner, before the unchanged lifecycle controls. This is not UNKNOWN recovery.
    with provider._claim_transaction(c):
        provider._privacy_erasure.replay(provider, wiki, conn=c)
    assert c.execute('SELECT status FROM claims WHERE id=?', (cid,)).fetchone()[0] == 'retired'
    assert any(row.get('id') == private_id for row in public(manager).get('claims', []))
    for case in results:
        checkpoint(case)
    return results


def run_retained_fts_unknown(home, session_id, checkpoint):
    """After healthy owners close: exact current-home native UNKNOWN, no reset."""
    home = Path(home)
    token = set_hermes_home_override(home)
    p, m = wiki.MemoryWikiProvider(), MemoryManager()
    try:
        m.add_provider(p)
        m.initialize_all(session_id, hermes_home=str(home), platform='cli',
                         bot_id='owned-lifecycle-bot', visibility_scope='chat')
        assert p._lifecycle_state == 'ready'
        assert public(m).get('claims')
        pc = p._conn
        deny_actions = []
        def deny_ddl_rollback(action, first, second, database, trigger):
            refusal = (action == sqlite3.SQLITE_CREATE_VTABLE or
                       (action == sqlite3.SQLITE_TRANSACTION and first == 'ROLLBACK'))
            if refusal:
                deny_actions.append('DDL' if action == sqlite3.SQLITE_CREATE_VTABLE else 'ROLLBACK')
            return sqlite3.SQLITE_DENY if refusal else sqlite3.SQLITE_OK
        pc.set_authorizer(deny_ddl_rollback)
        try:
            p._rebuild_fts()
        except sqlite3.DatabaseError as primary:
            assert p._transaction_primary is primary
            assert p._transaction_quarantine is pc
            assert p._claim_tx_connection is pc and p._claim_tx_thread == threading.get_ident()
            assert pc is p._conn is p._owned_conn and pc.in_transaction
            assert 'rollback_DatabaseError' in p._transaction_cleanup_notes
            assert any('outcome=UNKNOWN' in note for note in primary.__notes__)
            assert deny_actions == ['DDL', 'ROLLBACK']
            checkpoint('native_fts_unknown_before_close', {
                'primary_type': type(primary).__name__,
                'primary_identity_retained': p._transaction_primary is primary,
                'in_transaction': pc.in_transaction, 'cleanup': list(p._transaction_cleanup_notes)})
            for call in (p._connect, p.shutdown, lambda: p.initialize('must-not-replace', hermes_home=str(home))):
                try:
                    call()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('native_unknown_owner_replaced_or_closed')
            denied = public(m)
            assert not denied.get('claims') and denied.get('error')
            assert str(primary) in denied['error'] and 'terminal_owner_quarantine_UNKNOWN' not in denied['error']
            assert p._transaction_primary is primary and p._transaction_quarantine is pc
        else:
            raise AssertionError('native_rollback_deny_not_retained')
        RETAINED_UNKNOWN.append((p, m))
        return ['real_fts_rollback_deny_exact_primary_unknown_retained']
    finally:
        reset_hermes_home_override(token)
