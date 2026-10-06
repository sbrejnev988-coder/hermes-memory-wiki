"""Native/file SQLite ownership boundaries; no fabricated provider or SQL."""
from __future__ import annotations

import __main__
import importlib
import inspect
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest
import memory_wiki as plugin
from agent.memory_provider import MemoryProvider

_HOME = Path(os.environ['HERMES_HOME']).resolve()
_MISSING = object()


def _record(**values):
    with (_HOME / 'ownership-proofs.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(values) + '\n')


def _closed(connection):
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')


def test_native_origins_and_real_lifecycle_methods(own_native_provider_connections):
    owner = own_native_provider_connections
    provider = plugin.MemoryWikiProvider()
    assert type(provider) is plugin.MemoryWikiProvider
    assert plugin.MemoryProvider is MemoryProvider
    assert type(provider).__bases__ == (MemoryProvider,)
    origin = Path(plugin.__file__).resolve()
    for method in (owner.original_init, owner.original_connect,
                   provider.initialize, provider.shutdown, provider._migrate):
        assert Path(inspect.getfile(method)).resolve() == origin
    native = {name: importlib.import_module(name) for name in (
        'agent.memory_provider', 'agent.auxiliary_client', 'agent.secret_scope',
        'hermes_constants', 'hermes_yaml', 'openai', 'httpx',
    )}
    core = Path(native['agent.memory_provider'].__file__).resolve().parents[1]
    for name in tuple(native)[:5]:
        assert Path(native[name].__file__).resolve().is_relative_to(core)
    assert Path(native['openai'].__file__).resolve().is_relative_to(Path(sys.executable).parents[1])
    (_HOME / 'native-lifecycle-origins.json').write_text(json.dumps({
        'python': sys.executable, 'provider_class': type(provider).__module__ + '.' + type(provider).__name__,
        'provider_origin': str(origin), 'native_base_origin': inspect.getfile(MemoryProvider),
        'origins': {name: module.__file__ for name, module in native.items()},
        'initialize_shutdown_migrate_unmodified': True,
        'test_instrumented_methods': ['__init__', '_connect'],
        'standalone_fallback_used': False,
    }, indent=2), encoding='utf-8')


def test_file_sqlite_is_closed_after_failure_inside_actual_migration(
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
            _record(case='file-partial-migration', connection_closed_before_tmp_path=True,
                    schema_incomplete=True, actual_migrate_executed=True,
                    retained_connection_reference_is_intentional=True)
        finally:
            # Safety release is after the closure oracle, never a substitute.
            connection.close()

    request.node.addfinalizer(verify_after_owner)
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    provider = plugin.MemoryWikiProvider()
    holder['provider'] = provider
    real_migrate = provider._migrate
    denied = []

    def fail_during_migration():
        connection = provider._conn
        holder['connection'] = connection
        assert isinstance(connection, sqlite3.Connection)
        assert connection.execute('SELECT 1').fetchone()[0] == 1
        database = connection.execute('PRAGMA database_list').fetchone()[2]
        assert Path(database).resolve() == provider.db_path.resolve()

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

    monkeypatch.setattr(provider, '_migrate', fail_during_migration)
    with pytest.raises(sqlite3.DatabaseError, match='not authorized'):
        provider.initialize('partial-file-chat', bot_id='partial-file-bot')
    assert denied == ['claims']
    connection = holder['connection']
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'meta' in tables and 'recovery_artifacts' in tables
    assert 'claims' not in tables
    with pytest.raises(sqlite3.OperationalError, match='no such table: claims'):
        provider.shutdown()
    assert connection.execute('SELECT 1').fetchone()[0] == 1
    assert provider._conn is connection


@pytest.mark.parametrize('pointer', ['absent', 'previous', 'newer'])
def test_multiple_owned_connections_close_without_closing_external_provider(
    pointer, tmp_path, monkeypatch, request, own_native_provider_connections,
):
    owner = own_native_provider_connections
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    previous = getattr(__main__, '_memory_wiki_instance', _MISSING)
    holder = {'owned': [], 'expected': previous, 'external': None}

    def safety():
        external = holder['external']
        if external is not None:
            external._conn.close()
            external._conn = None
            if getattr(__main__, '_memory_wiki_instance', _MISSING) is external:
                if previous is _MISSING:
                    del __main__._memory_wiki_instance
                else:
                    __main__._memory_wiki_instance = previous

    def verify():
        for provider, connection in holder['owned']:
            _closed(connection)
            assert provider._conn is None
        assert getattr(__main__, '_memory_wiki_instance', _MISSING) is holder['expected']
        external = holder['external']
        if external is not None:
            assert external._conn.execute('SELECT 1').fetchone()[0] == 1
        _record(case='pointer-' + pointer, owned_closed=len(holder['owned']), external_untouched=True)

    request.node.addfinalizer(safety)
    request.node.addfinalizer(verify)

    def external_provider():
        # Real constructor outside the ownership wrapper; genuine negative owner.
        external = object.__new__(plugin.MemoryWikiProvider)
        owner.original_init(external)
        external.db_path = ':memory:'
        external._connect()
        holder['external'] = external
        holder['expected'] = external

    if pointer == 'previous':
        external_provider()
    for _ in range(2):
        provider = plugin.MemoryWikiProvider()
        provider.db_path = ':memory:'
        connection = provider._connect()
        assert connection.execute('SELECT 1').fetchone()[0] == 1
        holder['owned'].append((provider, connection))
    if pointer == 'newer':
        external_provider()


def test_borrowed_sqlite_connection_is_not_closed(tmp_path, monkeypatch, request):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    connection = sqlite3.connect(':memory:')
    holder = {}

    def verify():
        try:
            assert connection.execute('SELECT 1').fetchone()[0] == 1
            assert holder['provider']._conn is connection
            _record(case='borrowed-connection', external_connection_untouched=True)
        finally:
            connection.close()
            holder['provider']._conn = None

    request.node.addfinalizer(verify)
    provider = plugin.MemoryWikiProvider()
    holder['provider'] = provider
    provider._conn = connection
    assert provider._connect() is connection
