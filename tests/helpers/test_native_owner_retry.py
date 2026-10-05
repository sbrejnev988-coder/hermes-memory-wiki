"""Native ownership retry oracles; no live threads or SDK/provider stand-ins."""
from __future__ import annotations

import __main__
import json
import os
from pathlib import Path
import sqlite3

import pytest
import memory_wiki as plugin

_MISSING = object()
_HOME = Path(os.environ['HERMES_HOME']).resolve()


class FailFirstClose(sqlite3.Connection):
    """A genuine SQLite handle with an explicit one-shot close fault only."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_close = True

    def close(self):
        if self.fail_close:
            self.fail_close = False
            raise RuntimeError('fixture-close-sentinel')
        return super().close()


def _closed(connection):
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')


def _record(**values):
    with (_HOME / 'owner-retry-proofs.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(values) + '\n')


def _external(owner):
    provider = object.__new__(plugin.MemoryWikiProvider)
    owner.original_init(provider)
    provider.db_path = ':memory:'
    connection = owner.original_connect(provider)
    assert id(provider) not in owner._owned
    return provider, connection


@pytest.mark.parametrize('pointer', ['absent', 'previous', 'newer'])
@pytest.mark.parametrize('refusal', ['worker', 'close-error'])
def test_owner_keeps_pending_handles_and_singleton_policy_until_safe_retry(
    pointer, refusal, own_native_provider_connections,
):
    owner = own_native_provider_connections
    initial = getattr(__main__, '_memory_wiki_instance', _MISSING)
    externals = []
    connections = []
    provider = worker = None
    try:
        if hasattr(__main__, '_memory_wiki_instance'):
            del __main__._memory_wiki_instance
        previous = _MISSING
        if pointer == 'previous':
            previous, external_connection = _external(owner)
            externals.append((previous, external_connection))
        provider = plugin.MemoryWikiProvider()
        provider.db_path = ':memory:'
        acquired = provider._connect()
        connections.append(acquired)
        assert isinstance(acquired, sqlite3.Connection)
        assert acquired.execute('SELECT 1').fetchone()[0] == 1
        pending = acquired
        if refusal == 'worker':
            # Actual native Worker, intentionally never started: no live worker
            # can race teardown. Its presence exercises the owner's safety guard.
            worker = plugin._background_jobs.Worker(provider, plugin)
            assert worker.thread.ident is None
            assert not worker.thread.is_alive()
            provider._background_worker = worker
            message = 'refuses to close an active worker connection'
        else:
            pending = sqlite3.connect(':memory:', factory=FailFirstClose)
            connections.append(pending)
            # Explicitly own the fault-injection handle; no _connect/SQLite/SDK
            # substitution. The first handle came from the actual native method.
            owner._owned[id(provider)][1].append(pending)
            provider._conn = pending
            message = '^fixture-close-sentinel$'
        expected_during_refusal = provider
        expected_after_retry = previous
        if pointer == 'newer':
            external, external_connection = _external(owner)
            externals.append((external, external_connection))
            expected_during_refusal = expected_after_retry = external
        owned_entry = owner._owned[id(provider)]
        captured_previous = owned_entry[2]
        if previous is not _MISSING:
            assert captured_previous is previous
        with pytest.raises(RuntimeError, match=message):
            owner.release(provider)
        # Failure/refusal must not silently discard ownership or restore an old
        # singleton while this provider still has a live, owned handle.
        assert id(provider) in owner._owned
        entry = owner._owned[id(provider)]
        assert entry[0] is provider
        assert entry is owned_entry
        assert entry[2] is captured_previous
        assert len(entry[1]) == 1 and entry[1][0] is pending
        assert provider._conn is pending
        assert pending.execute('SELECT 1').fetchone()[0] == 1
        assert getattr(__main__, '_memory_wiki_instance', _MISSING) is expected_during_refusal
        if refusal == 'close-error':
            _closed(acquired)
        else:
            assert acquired.execute('SELECT 1').fetchone()[0] == 1
            assert provider._background_worker is worker
            assert not worker.thread.is_alive()
            provider._background_worker = None
        for external, external_connection in externals:
            assert external._conn is external_connection
            assert external_connection.execute('SELECT 1').fetchone()[0] == 1
        owner.release(provider)
        for connection in connections:
            _closed(connection)
        assert provider._conn is None
        assert id(provider) not in owner._owned
        assert getattr(__main__, '_memory_wiki_instance', _MISSING) is expected_after_retry
        owner.release(provider)  # Already released: idempotent, no external effects.
        assert getattr(__main__, '_memory_wiki_instance', _MISSING) is expected_after_retry
        for external, external_connection in externals:
            assert external_connection.execute('SELECT 1').fetchone()[0] == 1
        _record(case=refusal + '-' + pointer, retained_metadata_after_refusal=True,
                pending_handle_open=True, owned_handles_closed_after_retry=True,
                exact_singleton_identity=True, external_connections_untouched=True,
                real_worker_unstarted=(worker is not None), live_workers_started=0)
    finally:
        # Safe fallback is after the assertions, not evidence of successful retry.
        if provider is not None:
            if worker is not None:
                assert not worker.thread.is_alive()
                provider._background_worker = None
            owner.release(provider)
        for connection in connections:
            if isinstance(connection, FailFirstClose):
                connection.fail_close = False
            connection.close()
        for external, external_connection in externals:
            external_connection.close()
            external._conn = None
        if initial is _MISSING:
            if hasattr(__main__, '_memory_wiki_instance'):
                del __main__._memory_wiki_instance
        else:
            __main__._memory_wiki_instance = initial


def test_worker_marker_does_not_transfer_a_borrowed_sqlite_handle(
    own_native_provider_connections,
):
    owner = own_native_provider_connections
    previous = getattr(__main__, '_memory_wiki_instance', _MISSING)
    connection = sqlite3.connect(':memory:')
    provider = plugin.MemoryWikiProvider()
    worker = plugin._background_jobs.Worker(provider, plugin)
    assert worker.thread.ident is None
    assert not worker.thread.is_alive()
    provider._conn = connection
    provider._background_worker = worker
    try:
        assert provider._connect() is connection
        assert owner._owned[id(provider)][1] == []
        owner.release(provider)
        assert provider._conn is connection
        assert connection.execute('SELECT 1').fetchone()[0] == 1
        assert provider._background_worker is worker
        assert getattr(__main__, '_memory_wiki_instance', _MISSING) is previous
        assert id(provider) not in owner._owned
        _record(case='borrowed-worker-marker', borrowed_handle_untouched=True,
                live_workers_started=0, exact_singleton_identity=True)
    finally:
        assert not worker.thread.is_alive()
        provider._background_worker = None
        connection.close()
        provider._conn = None
        owner.release(provider)


def test_partial_native_initialization_has_a_same_item_finalizer_oracle(
    tmp_path, monkeypatch, request,
):
    previous = getattr(__main__, '_memory_wiki_instance', _MISSING)
    holder = {}

    def verify_after_owner():
        connection = holder['connection']
        try:
            _closed(connection)
            assert holder['provider']._conn is None
            assert getattr(__main__, '_memory_wiki_instance', _MISSING) is previous
            assert tmp_path.exists()
            _record(case='same-item-partial-migration', real_migration_denied=True,
                    connection_closed_before_tmp_path=True, exact_singleton_identity=True)
        finally:
            connection.close()

    request.node.addfinalizer(verify_after_owner)
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    provider = plugin.MemoryWikiProvider()
    holder['provider'] = provider
    real_migrate = provider._migrate
    denied = []

    def deny_claims_in_real_migration():
        connection = provider._conn
        holder['connection'] = connection
        assert isinstance(connection, sqlite3.Connection)
        assert connection.execute('SELECT 1').fetchone()[0] == 1

        def authorizer(action, table, *_args):
            if action == sqlite3.SQLITE_CREATE_TABLE and table == 'claims':
                denied.append(table)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorizer)
        try:
            return real_migrate()
        finally:
            connection.set_authorizer(None)

    monkeypatch.setattr(provider, '_migrate', deny_claims_in_real_migration)
    with pytest.raises(sqlite3.DatabaseError, match='not authorized'):
        provider.initialize('same-item-partial-chat', bot_id='same-item-partial-bot')
    assert denied == ['claims']
    connection = holder['connection']
    assert provider._conn is connection
    assert connection.execute('SELECT 1').fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError, match='no such table: claims'):
        provider.shutdown()
    assert connection.execute('SELECT 1').fetchone()[0] == 1
