"""Real deletion-race call assertions plus an item-level teardown oracle."""
from __future__ import annotations

import __main__
import importlib.util
import inspect
from pathlib import Path

import pytest
import memory_wiki
from agent.memory_provider import MemoryProvider

_SPEC = importlib.util.spec_from_file_location(
    '_native_race_call_contracts',
    Path(__file__).resolve().parents[1] / 'test_unified_recall.py',
)
assert _SPEC and _SPEC.loader
contracts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(contracts)
_MISSING = object()


@pytest.mark.parametrize('name', [
    'test_event_deleted_during_facade_guard_is_not_returned',
    'test_episode_deleted_during_facade_guard_is_not_returned',
], ids=['event', 'episode'])
def test_real_race_fixture_releases_owned_provider_before_tmp_path_teardown(
    name, tmp_path, monkeypatch, request,
):
    previous = getattr(__main__, '_memory_wiki_instance', _MISSING)
    holder = {}

    def after_provider_release():
        provider = holder['provider']
        assert getattr(__main__, '_memory_wiki_instance', _MISSING) is previous
        assert provider._conn is None

    # Register the oracle before constructor ownership registers its cleanup.
    request.node.addfinalizer(after_provider_release)
    getattr(contracts, name)(tmp_path, monkeypatch)
    provider = getattr(__main__, '_memory_wiki_instance')
    holder['provider'] = provider
    assert isinstance(provider, MemoryProvider)
    assert next(base for base in type(provider).__mro__
                if base.__name__ == 'MemoryProvider') is MemoryProvider
    assert Path(inspect.getfile(type(provider))).resolve() == Path(memory_wiki.__file__).resolve()
    assert Path(inspect.getfile(MemoryProvider)).is_file()
