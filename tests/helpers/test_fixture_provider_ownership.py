"""Native lifecycle regression oracles; no SDK stand-ins or forced GC.

The retained connection is intentional test evidence, not a passive observer.
It is released after the exact closure assertion, including on RED failure.
"""
from __future__ import annotations

import __main__
import sqlite3
from pathlib import Path

import pytest
import memory_wiki as plugin
from agent.memory_provider import MemoryProvider

_CONNECTION = None
_PROVIDER_ID = None


def test_01_partial_initialization_opens_real_sqlite_before_schema_failure(
    tmp_path, monkeypatch,
):
    global _CONNECTION, _PROVIDER_ID
    assert plugin.MemoryWikiProvider.__bases__ == (MemoryProvider,)
    assert Path(plugin.MemoryProvider.__module__.replace('.', '/')).as_posix() == 'agent/memory_provider'
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    provider = plugin.MemoryWikiProvider()
    provider.db_path = ':memory:'
    _PROVIDER_ID = id(provider)

    def fail_migration():
        global _CONNECTION
        _CONNECTION = provider._conn
        assert isinstance(_CONNECTION, sqlite3.Connection)
        assert _CONNECTION.execute('SELECT 1').fetchone()[0] == 1
        assert _CONNECTION.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        ).fetchall() == []
        raise RuntimeError('fixture-migration-sentinel')

    monkeypatch.setattr(provider, '_migrate', fail_migration)
    with pytest.raises(RuntimeError, match='^fixture-migration-sentinel$'):
        provider.initialize('fixture-partial-chat', bot_id='fixture-partial-bot')
    assert provider._conn is _CONNECTION
    assert _CONNECTION.execute('SELECT 1').fetchone()[0] == 1
    # The rejected f9 helper relied on shutdown. In a true partial schema it
    # raises before close, so the fixture owner must not rely on rendering.
    with pytest.raises(sqlite3.OperationalError, match='no such table: claims'):
        provider.shutdown()
    assert _CONNECTION.execute('SELECT 1').fetchone()[0] == 1
    assert getattr(__main__, '_memory_wiki_instance') is provider


def test_02_previous_fixture_connection_is_closed_before_next_test():
    global _CONNECTION, _PROVIDER_ID
    assert _CONNECTION is not None, 'Run together with test_01; no skipped oracle'
    try:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            _CONNECTION.execute('SELECT 1')
        assert id(getattr(__main__, '_memory_wiki_instance', None)) != _PROVIDER_ID
    finally:
        # Test-only safety release follows the oracle; it cannot make RED green.
        _CONNECTION.close()
        _CONNECTION = None
        _PROVIDER_ID = None
