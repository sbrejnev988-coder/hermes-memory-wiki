"""Fixture ownership for resources acquired by the real native provider.

This is test instrumentation, not a provider/SDK substitute. Constructor and
_connect wrappers delegate unchanged calls/results. Only connections opened
by a provider constructed during this item belong to its finalizer; borrowed
connections and a previous/newer external singleton remain external.
"""
from __future__ import annotations

import __main__
from functools import wraps
import sqlite3

_MISSING = object()


class FixtureProviderOwner:
    def __init__(self, provider_class, request, monkeypatch):
        self.provider_class = provider_class
        self.original_init = provider_class.__init__
        self.original_connect = provider_class._connect
        self._owned = {}
        self._bound = set()
        self._request = request
        self._monkeypatch = monkeypatch
        self.bind(provider_class)

    def bind(self, provider_class):
        if provider_class in self._bound:
            return
        from agent.memory_provider import MemoryProvider
        assert provider_class.__bases__ == (MemoryProvider,)
        self._bound.add(provider_class)
        original_init = provider_class.__init__
        original_connect = provider_class._connect

        @wraps(original_init)
        def construct(provider, *args, **kwargs):
            previous = getattr(__main__, '_memory_wiki_instance', _MISSING)
            entry = (provider, [], previous)
            self._owned[id(provider)] = entry
            # Item-level LIFO finalizers run before tmp_path and monkeypatch.
            # Register before even __init__ can raise, and before initialize.
            self._request.node.addfinalizer(lambda: self.release(provider))
            original_init(provider, *args, **kwargs)

        @wraps(original_connect)
        def connect(provider, *args, **kwargs):
            before = getattr(provider, '_conn', None)
            connection = original_connect(provider, *args, **kwargs)
            entry = self._owned.get(id(provider))
            if entry is not None and entry[0] is provider and before is None:
                assert isinstance(connection, sqlite3.Connection)
                if not any(owned is connection for owned in entry[1]):
                    entry[1].append(connection)
            return connection

        self._monkeypatch.setattr(provider_class, '__init__', construct)
        self._monkeypatch.setattr(provider_class, '_connect', connect)

    def release(self, provider):
        entry = self._owned.get(id(provider))
        if entry is None:
            return
        assert entry[0] is provider
        connections, previous = entry[1], entry[2]
        # Refusal is not a release: retain the exact handles and restoration
        # metadata for an explicit safe retry after the worker is detached.
        if connections and getattr(provider, '_background_worker', None) is not None:
            raise RuntimeError('Fixture owner refuses to close an active worker connection')
        errors = []
        pending = []
        for connection in reversed(connections):
            try:
                # shutdown renders claims and cannot own partial schemas.
                # Close our acquired SQLite resource directly, not via GC.
                connection.close()
                if getattr(provider, '_conn', None) is connection:
                    provider._conn = None
            except Exception as error:
                errors.append(error)
                pending.append(connection)
        # Successful closes are not retried; failed handles keep their original
        # acquisition order and previous singleton identity until retry succeeds.
        connections[:] = reversed(pending)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup('Fixture-owned SQLite teardown failed', errors)
        self._owned.pop(id(provider))
        if getattr(__main__, '_memory_wiki_instance', _MISSING) is provider:
            if previous is _MISSING:
                del __main__._memory_wiki_instance
            else:
                __main__._memory_wiki_instance = previous
