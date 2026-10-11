"""Real-SDK lifecycle/TX regression packet, no MemoryProvider or guard mocks.

The isolated entrypoint runs run_lifecycle_packet on the provider whose authored
sync/public read/prefetch/session-end path it has already exercised. UNKNOWN
owners are retained until the owning interpreter exits, not reset for cleanup.
"""
from __future__ import annotations
import contextvars
import json
import sqlite3
import threading
import time
from pathlib import Path

import memory_wiki as wiki
from agent.memory_provider import MemoryProvider, spawn_context_thread
from hermes_constants import set_hermes_home_override, reset_hermes_home_override

RETAINED_UNKNOWN = []


def _query(provider):
    return json.loads(provider.handle_tool_call('memory_wiki_query', {'query': 'Лазурный маяк', 'limit': 5}))


def _new(home, sid):
    token = set_hermes_home_override(home)
    try:
        provider = wiki.MemoryWikiProvider()
        assert provider.__class__.__bases__ == (MemoryProvider,)
        provider.initialize(sid, hermes_home=str(home), platform='cli',
                            bot_id='owned-lifecycle-bot', visibility_scope='chat')
        assert provider._lifecycle_state == 'ready'
        return provider
    finally:
        reset_hermes_home_override(token)


def run_lifecycle_packet(provider, root):
    results = []
    assert provider._transaction_quarantine is None
    assert provider._claim_tx_connection is None and provider._claim_tx_thread is None

    # Original transaction errors remain primary when real rollback succeeds.
    conn = provider._conn
    primary = ValueError('owned_primary_rollback')
    try:
        with provider._claim_transaction(conn):
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('owned_rollback_probe','not_committed')")
            raise primary
    except ValueError as caught:
        assert caught is primary
    assert not conn.in_transaction and provider._transaction_quarantine is None
    assert conn.execute("SELECT 1 FROM meta WHERE key='owned_rollback_probe'").fetchone() is None
    assert _query(provider).get('claims'), 'public_read_after_known_rollback_empty'
    results.append('known_rollback_exact_primary_healthy')

    # A genuine event writer holds the registered lifetime. A normal reader
    # waits for its handoff, rather than quarantining the shared connection.
    inserted, release, reader_started, reader_done = [threading.Event() for _ in range(4)]
    errors, answers = [], []
    def pause(c, event_id):
        assert c is conn and c.in_transaction
        assert provider._claim_tx_connection is c
        assert provider._claim_tx_thread == threading.get_ident()
        inserted.set()
        assert release.wait(4), 'registered_writer_release_timeout'
    def write():
        try:
            event_id = wiki._memory_events.capture_event(
                provider, wiki, 'В проекте Лазурный маяк хранятся овальные керамические этикетки.',
                role='user', event_type='dialogue_turn', session_id=provider.session_id,
                provenance={'source': 'owned:concurrency'}, _after_insert=pause)
            assert event_id and provider._transaction_quarantine is None
        except BaseException as exc:
            errors.append(type(exc).__name__)
            inserted.set()
    def read():
        reader_started.set()
        try:
            answers.append(_query(provider))
        except BaseException as exc:
            errors.append(type(exc).__name__)
        finally:
            reader_done.set()
    writer = spawn_context_thread(write, name='owned-registered-writer', daemon=False)
    reader = spawn_context_thread(read, name='owned-ordinary-reader', daemon=False)
    writer.start()
    try:
        assert inserted.wait(4) and not errors, 'registered_writer_not_reached'
        reader.start()
        assert reader_started.wait(2)
        assert not reader_done.wait(.08), 'reader_failed_to_wait_for_registered_writer'
    finally:
        release.set()
        writer.join(5)
        if reader.ident is not None:
            reader.join(5)
    assert not writer.is_alive() and not reader.is_alive() and not errors
    assert answers and answers[0].get('claims'), 'public_read_after_registered_handoff_empty'
    assert provider._conn is conn and provider._owned_conn is conn
    assert not conn.in_transaction and provider._transaction_quarantine is None
    results.append('registered_event_writer_public_reader_sharing')

    # Public ACL remains session-bound even when two genuine providers share
    # the same SQLite file. Neither a new home nor borrowed credentials grants it.
    peer = _new(provider.home, 'owned-lifecycle-session-b')
    try:
        payload = _query(peer)
        assert not payload.get('error') and not payload.get('claims'), 'peer_chat_disclosure'
    finally:
        peer.shutdown()
    assert peer._conn is None and peer._owned_conn is None
    results.append('same_file_peer_session_denied')

    # Restart the owned provider ordinarily, without rebind/reconnect/flag edits.
    sid, home = provider.session_id, provider.home
    provider.shutdown()
    assert provider._conn is None and provider._owned_conn is None
    restarted = _new(home, sid)
    try:
        assert any('Лазурный маяк' in c.get('claim', '') for c in _query(restarted).get('claims', [])), 'restart_public_read_empty'
    finally:
        restarted.shutdown()
    assert restarted._conn is None and restarted._owned_conn is None
    results.append('ordinary_restart_durable_public_read')

    # A real foreign unregistered owner still denies. Its own thread performs
    # its normal rollback after the refusal; the plugin retains quarantine.
    foreign = _new(Path(root) / 'foreign-home', 'owned-foreign-session')
    foreign_conn = foreign._conn
    active, finish = threading.Event(), threading.Event()
    foreign_errors = []
    def foreign_owner():
        token = set_hermes_home_override(foreign.home)
        try:
            foreign_conn.execute('BEGIN IMMEDIATE')
            active.set()
            assert finish.wait(4)
            foreign_conn.rollback()  # Original owner, never a provider recovery.
        except BaseException as exc:
            foreign_errors.append(type(exc).__name__)
            active.set()
        finally:
            reset_hermes_home_override(token)
    thread = spawn_context_thread(foreign_owner, name='owned-foreign-owner', daemon=False)
    thread.start()
    token = set_hermes_home_override(foreign.home)
    try:
        assert active.wait(4) and not foreign_errors
        payload = json.loads(foreign.handle_tool_call('memory_wiki_query_mode', {'query': 'Лазурный маяк'}))
        assert 'provider_transaction_owner_pending' in payload.get('error', '')
        assert foreign._transaction_quarantine is foreign_conn
        assert foreign._conn is foreign_conn and foreign._owned_conn is foreign_conn
    finally:
        finish.set(); thread.join(5)
        reset_hermes_home_override(token)
    assert not thread.is_alive() and not foreign_errors
    assert not foreign_conn.in_transaction and foreign._lifecycle_state == 'quarantined'
    RETAINED_UNKNOWN.append(foreign)
    results.append('foreign_real_thread_owner_denied_exact_retention')

    # Genuine SQLite authorizer denial of ROLLBACK, not a fake Connection.
    unknown = _new(Path(root) / 'unknown-home', 'owned-unknown-session')
    unknown_conn = unknown._conn
    def deny_rollback(action, first, second, database, trigger):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and first == 'ROLLBACK' else sqlite3.SQLITE_OK
    unknown_conn.set_authorizer(deny_rollback)
    primary = ValueError('owned_primary_unknown')
    token = set_hermes_home_override(unknown.home)
    try:
        try:
            with unknown._claim_transaction(unknown_conn):
                raise primary
        except ValueError as caught:
            assert caught is primary
        else:
            raise AssertionError('primary_not_propagated')
        assert unknown._transaction_primary is primary
        assert unknown._transaction_quarantine is unknown_conn
        assert unknown._conn is unknown_conn and unknown._owned_conn is unknown_conn
        assert unknown._claim_tx_connection is unknown_conn
        assert unknown._claim_tx_thread == threading.get_ident()
        assert unknown_conn.in_transaction
        assert 'rollback_DatabaseError' in unknown._transaction_cleanup_notes
        assert any('outcome=UNKNOWN' in note for note in primary.__notes__)
        for action in [unknown._connect, unknown.shutdown,
                       lambda: unknown.initialize('must-not-replace', hermes_home=str(unknown.home))]:
            try:
                action()
            except RuntimeError:
                pass
            else:
                raise AssertionError('unknown_reconnect_or_shutdown_admitted')
        denied = json.loads(unknown.handle_tool_call('memory_wiki_query_mode', {'query': 'Лазурный маяк'}))
        assert 'provider_lifecycle_not_ready' in denied.get('error', '')
        assert unknown._conn is unknown_conn and unknown._transaction_primary is primary
    finally:
        reset_hermes_home_override(token)
    RETAINED_UNKNOWN.append(unknown)
    results.append('real_sqlite_rollback_denied_same_primary_unknown_retained')
    return results
