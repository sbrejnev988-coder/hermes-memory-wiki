"""Ambient secret-registry overrides cannot cross a requested profile home."""

from __future__ import annotations

import vault_registry_adapter as adapter


def test_foreign_override_falls_back_to_requested_profiles_registry(tmp_path, monkeypatch):
    default = tmp_path / "default"
    learning = default / "profiles" / "learning"
    (default / "secret-vault").mkdir(parents=True)
    (learning / "secret-vault").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(learning))
    monkeypatch.setenv(
        "MEMORY_WIKI_SECRET_REGISTRY",
        str(learning / "secret-vault" / "secrets_registry.json"),
    )
    assert adapter.registry_path(default) == default / "secret-vault" / "secrets_registry.json"


def test_requested_profile_ignores_registry_override(tmp_path, monkeypatch):
    default = tmp_path / "default"
    learning = tmp_path / "learning"
    (default / "secret-vault").mkdir(parents=True)
    local = default / "secret-vault" / "alternate.json"
    monkeypatch.setenv("HERMES_HOME", str(learning))
    monkeypatch.setenv("MEMORY_WIKI_SECRET_REGISTRY", str(local))
    assert adapter.registry_path(default) == default / "secret-vault" / "secrets_registry.json"


def test_ambient_profile_ignores_explicit_registry_override(tmp_path, monkeypatch):
    home = tmp_path / "home"
    override = tmp_path / "shared" / "registry.json"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("MEMORY_WIKI_SECRET_REGISTRY", str(override))
    assert adapter.registry_path(home) == home / "secret-vault" / "secrets_registry.json"


def test_named_profile_resolves_the_shared_registry(tmp_path, monkeypatch):
    default = tmp_path / "default"
    learning = default / "profiles" / "learning"
    monkeypatch.setenv("HERMES_HOME", str(learning))
    assert adapter.registry_path(learning) == default / "secret-vault" / "secrets_registry.json"
