"""Real helper-context singleton/SQLite oracles, not owner-only teardown tests."""
from __future__ import annotations

import __main__
import importlib.util
import json
import os
from pathlib import Path
import sqlite3

import pytest
import memory_wiki as plugin
from agent.memory_provider import MemoryProvider

_SPEC = importlib.util.spec_from_file_location(
    '_singleton_fix_native_helper',
    Path(__file__).with_name('audit_native_helpers_20261003.py'),
)
assert _SPEC and _SPEC.loader
native = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(native)
_MISSING = object()
_HOME = Path(os.environ['HERMES_HOME']).resolve()


def _closed(connection):
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')


def _record(**values):
    with (_HOME / 'helper-singleton-proofs.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(values) + '\n')


def _external_provider(owner):
    # Native constructor outside this item's wrapper: a genuine negative owner.
    provider = object.__new__(plugin.MemoryWikiProvider)
    owner.original_init(provider)
    provider.db_path = ':memory:'
    connection = owner.original_connect(provider)
    assert isinstance(connection, sqlite3.Connection)
    assert type(provider).__bases__ == (MemoryProvider,)
    assert connection.execute('SELECT 1').fetchone()[0] == 1
    assert id(provider) not in owner._owned
    return provider, connection


@pytest.mark.parametrize('pointer', ['previous', 'absent', 'newer'])
def test_helper_context_restores_only_its_exact_previous_singleton(
    pointer, own_native_provider_connections, monkeypatch,
):
    owner = own_native_provider_connections
    native.configure_offline(monkeypatch)
    initial = getattr(__main__, '_memory_wiki_instance', _MISSING)
    externals = []
    provider = connection = None
    try:
        if hasattr(__main__, '_memory_wiki_instance'):
            del __main__._memory_wiki_instance
        if pointer == 'previous':
            previous, external_connection = _external_provider(owner)
            externals.append((previous, external_connection))
        else:
            previous = _MISSING
        expected = previous
        with native.native_provider() as provider:
            connection = provider._connect()
            assert isinstance(connection, sqlite3.Connection)
            assert type(provider) is plugin.MemoryWikiProvider
            assert plugin.MemoryProvider is MemoryProvider
            assert getattr(__main__, '_memory_wiki_instance') is provider
            assert connection.execute('SELECT 1').fetchone()[0] == 1
            if pointer == 'newer':
                expected, external_connection = _external_provider(owner)
                externals.append((expected, external_connection))
                assert getattr(__main__, '_memory_wiki_instance') is expected
        # Check at context exit, before any item-level owner finalizer runs.
        _closed(connection)
        assert provider._conn is None
        assert id(provider) in owner._owned
        assert getattr(__main__, '_memory_wiki_instance', _MISSING) is expected
        for external, external_connection in externals:
            assert external._conn is external_connection
            assert external_connection.execute('SELECT 1').fetchone()[0] == 1
        owner.release(provider)
        assert getattr(__main__, '_memory_wiki_instance', _MISSING) is expected
        _closed(connection)
        _record(case='helper-' + pointer, before_owner_finalizer=True,
                exact_singleton_identity=True, closed_connection=True,
                external_connections_untouched=True)
    finally:
        # Safety is strictly after the closure/identity oracle, including RED.
        if connection is not None:
            connection.close()
        if provider is not None:
            owner.release(provider)
        for external, external_connection in externals:
            external_connection.close()
            external._conn = None
        if initial is _MISSING:
            if hasattr(__main__, '_memory_wiki_instance'):
                del __main__._memory_wiki_instance
        else:
            __main__._memory_wiki_instance = initial


def test_nested_helper_contexts_restore_exact_singletons_in_lifo_order(
    own_native_provider_connections, monkeypatch,
):
    owner = own_native_provider_connections
    native.configure_offline(monkeypatch)
    initial = getattr(__main__, '_memory_wiki_instance', _MISSING)
    previous, external_connection = _external_provider(owner)
    providers = []
    connections = []
    try:
        with native.native_provider() as outer:
            providers.append(outer)
            outer_connection = outer._connect()
            connections.append(outer_connection)
            assert getattr(__main__, '_memory_wiki_instance') is outer
            with native.native_provider() as inner:
                providers.append(inner)
                inner_connection = inner._connect()
                connections.append(inner_connection)
                assert getattr(__main__, '_memory_wiki_instance') is inner
                assert inner_connection is not outer_connection
            _closed(inner_connection)
            assert inner._conn is None
            assert getattr(__main__, '_memory_wiki_instance', _MISSING) is outer
            assert outer._conn is outer_connection
            assert outer_connection.execute('SELECT 1').fetchone()[0] == 1
            owner.release(inner)
            assert getattr(__main__, '_memory_wiki_instance') is outer
        _closed(outer_connection)
        _closed(inner_connection)
        assert outer._conn is None
        assert getattr(__main__, '_memory_wiki_instance', _MISSING) is previous
        assert previous._conn is external_connection
        assert external_connection.execute('SELECT 1').fetchone()[0] == 1
        owner.release(outer)
        assert getattr(__main__, '_memory_wiki_instance') is previous
        _record(case='helper-nested-lifo', before_owner_finalizer=True,
                exact_singleton_identity=True, closed_connections=2,
                outer_open_after_inner_exit=True, external_connection_untouched=True)
    finally:
        for connection in reversed(connections):
            connection.close()
        for provider in reversed(providers):
            owner.release(provider)
        external_connection.close()
        previous._conn = None
        if initial is _MISSING:
            if hasattr(__main__, '_memory_wiki_instance'):
                del __main__._memory_wiki_instance
        else:
            __main__._memory_wiki_instance = initial
