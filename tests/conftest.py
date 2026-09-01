"""Pytest-only isolation for machine-specific Memory Wiki access policy."""

from __future__ import annotations

import pytest


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
