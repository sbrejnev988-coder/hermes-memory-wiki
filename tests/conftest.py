"""Pytest-only isolation for machine-specific Memory Wiki access policy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_OWNER_SPEC = importlib.util.spec_from_file_location(
    '_native_fixture_provider_lifecycle',
    Path(__file__).parent / 'helpers' / 'provider_lifecycle.py',
)
assert _OWNER_SPEC and _OWNER_SPEC.loader
_OWNER = importlib.util.module_from_spec(_OWNER_SPEC)
_OWNER_SPEC.loader.exec_module(_OWNER)


@pytest.fixture(autouse=True)
def own_native_provider_connections(request, monkeypatch):
    # The native runner preloads the actual package; no standalone SDK fallback.
    import memory_wiki
    from agent.memory_provider import MemoryProvider

    assert memory_wiki.MemoryProvider is MemoryProvider
    assert memory_wiki.MemoryWikiProvider.__bases__ == (MemoryProvider,)
    owner = _OWNER.FixtureProviderOwner(
        memory_wiki.MemoryWikiProvider, request, monkeypatch,
    )
    # Historical fixtures load the same real source under distinct package
    # names. Bind only that exact source after its actual loader has executed;
    # never rewrite sys.modules or substitute the native SDK/MemoryProvider.
    source = Path(memory_wiki.__file__).resolve()
    real_exec = importlib.machinery.SourceFileLoader.exec_module

    def execute(loader, module):
        real_exec(loader, module)
        if Path(getattr(module, '__file__', '')).resolve() == source:
            assert module.MemoryProvider is MemoryProvider
            owner.bind(module.MemoryWikiProvider)

    monkeypatch.setattr(importlib.machinery.SourceFileLoader, 'exec_module', execute)
    return owner


# These values are intentionally configured in the user's real Hermes process,
# but fixture providers use independent temporary databases and project scopes.
# Letting a host-level access policy leak into them makes the suite depend on the
# developer's active profile rather than the fixture's explicit scope.
_DOCUMENT_ACCESS_POLICY_ENV = (
    "MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID",
    "MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID",
    "MEMORY_WIKI_DOCUMENT_ALLOW_CROSS_SCOPE",
    "MEMORY_WIKI_DOCUMENT_ALLOW_SCOPE_MIGRATION",
)


@pytest.fixture(autouse=True)
def isolate_document_access_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _DOCUMENT_ACCESS_POLICY_ENV:
        monkeypatch.delenv(key, raising=False)
