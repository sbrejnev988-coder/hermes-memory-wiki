"""Native F05 release-error regressions; no SDK/final-validator replacement.

These tests exercise real SQL authorizer failures on synthetic in-memory DBs.
They do not repair or exercise the rejected fixture-lifecycle/F9 roadmap.
"""
from __future__ import annotations
import importlib.util
import sqlite3
from pathlib import Path
import pytest

_spec = importlib.util.spec_from_file_location(
    '_audit_release_native_helpers',
    Path(__file__).with_name('audit_native_helpers_20261003.py'),
)
assert _spec and _spec.loader
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)

@pytest.fixture(autouse=True)
def offline_policy(monkeypatch):
    h.configure_offline(monkeypatch)


def release_refusal(connection, *, once):
    denied = []
    def authorizer(action, first, second, *_remaining):
        if (action == sqlite3.SQLITE_SAVEPOINT and first == 'RELEASE'
                and str(second).startswith('memory_wiki_unified_final_')
                and (not once or not denied)):
            denied.append(second)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    connection.set_authorizer(authorizer)
    return denied


@pytest.mark.parametrize('factory', [sqlite3.Connection, h.NativeConnection])
@pytest.mark.parametrize('once', [True, False], ids=['one-release-failure', 'persistent-release-refusal'])
def test_native_release_failure_removes_nonclaim_evidence_from_final_response(factory, once):
    with h.native_provider(factory=factory) as provider:
        ids = h.seed_nonclaims(provider)
        h.assert_visible(h.recall_all(provider), ids)
        connection = provider._connect()
        denied = release_refusal(connection, once=once)
        try:
            result = h.recall_all(provider)
            assert denied, 'The native final snapshot RELEASE must actually fail'
            assert not [item for item in result['items'] if item['kind'] != 'claim']
            assert result['evidence_count'] == len(result['items'])
            assert result['answer_policy']['allowed_citations'] == [item['citation'] for item in result['items']]
            assert all(citation.startswith('[M:C:') for citation in result['answer_policy']['allowed_citations'])
            assert provider._connect() is connection, 'Do not close provider-owned connections'
        finally:
            connection.set_authorizer(None)
            # An authorizer can refuse every RELEASE; recovery belongs to this
            # fixture owner, not to a validator rolling back a caller's work.
            if connection.in_transaction:
                connection.rollback()


@pytest.mark.parametrize('factory', [sqlite3.Connection, h.NativeConnection])
def test_release_failure_does_not_commit_or_close_caller_transaction(factory):
    with h.native_provider(factory=factory) as provider:
        h.seed_nonclaims(provider)
        connection = provider._connect()
        events = h.events.query_events(provider, h.plugin, h.QUERY, limit=10, scope='chat')['events']
        assert events
        row = events[0]
        candidate = {'kind': 'event', '_source_id': row['event_id'],
                     '_snapshot_fingerprint': h.recall._event_snapshot_fingerprint(row)}
        kwargs = dict(episodic_backend=h.episodes, event_backend=h.events,
                      observation_backend=h.observations, event_scope='chat', runtime_module=h.plugin)
        expected = {('event', row['event_id'], '')}
        assert h.recall._final_visible_nonclaims(provider, [candidate], **kwargs) == expected
        connection.execute('CREATE TABLE audit_caller_pending(value TEXT)')
        connection.commit()
        connection.execute('BEGIN')
        connection.execute("INSERT INTO audit_caller_pending VALUES ('caller-owned-uncommitted')")
        denied = release_refusal(connection, once=True)
        try:
            visible = h.recall._final_visible_nonclaims(provider, [candidate], **kwargs)
            assert denied
            assert visible == set()
            assert connection.in_transaction, 'Do not commit the caller transaction'
            assert connection.execute('SELECT value FROM audit_caller_pending').fetchone()[0] == 'caller-owned-uncommitted'
            assert provider._connect() is connection
            connection.rollback()
            assert connection.execute('SELECT count(*) FROM audit_caller_pending').fetchone()[0] == 0
        finally:
            connection.set_authorizer(None)
            if connection.in_transaction:
                connection.rollback()
