from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_metadata_registry_query_works_without_legacy_secret_core(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    registry = tmp_path / "secret-vault" / "secrets_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "secret_id": "sec_safe_registry_test",
                        "lookup_key": "safe-test/hermes/ssh",
                        "aliases": [],
                        "secret_type": "ssh_credential",
                        "status": "active",
                        "has_value": True,
                        "policy": {
                            "allowed_executors": ["ssh"],
                            "require_user_approval": True,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    module = _load_provider("memory_wiki_no_legacy_secret_core_test")
    assert module._SECRET_CORE_AVAILABLE is False
    provider = module.MemoryWikiProvider()
    provider.initialize("safe-registry-test", hermes_home=str(tmp_path), agent_context="test")
    try:
        rows = provider._query_secrets("safe-test", limit=5)
        assert len(rows) == 1
        assert rows[0]["lookup_key"] == "safe-test/hermes/ssh"
        assert rows[0]["origin"] == "vault_registry"
        assert rows[0]["has_value"] is True
        assert rows[0]["locator"] == ""
        assert rows[0]["username"] == ""
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_metadata_registry_query_skips_legacy_index_by_default_when_core_exists(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    registry = tmp_path / "secret-vault" / "secrets_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "secret_id": "sec_default_no_legacy_test",
                        "lookup_key": "safe-test/default/ssh",
                        "aliases": [],
                        "secret_type": "ssh_credential",
                        "status": "active",
                        "has_value": True,
                        "policy": {"allowed_executors": ["ssh"], "require_user_approval": True},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    module = _load_provider("memory_wiki_default_no_legacy_index_test")
    monkeypatch.setattr(module, "_SECRET_CORE_AVAILABLE", True)
    provider = module.MemoryWikiProvider()
    provider.initialize("default-no-legacy", hermes_home=str(tmp_path), agent_context="test")
    monkeypatch.setattr(
        provider,
        "_get_secret_store",
        lambda: pytest.fail("legacy secret index must remain disabled by default"),
    )
    try:
        rows = provider._query_secrets("safe-test", limit=5)
        assert [row["lookup_key"] for row in rows] == ["safe-test/default/ssh"]
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_memory_context_never_instructs_model_to_use_plaintext_lookup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    module = _load_provider("memory_wiki_no_plaintext_lookup_prompt_test")
    provider = module.MemoryWikiProvider()
    provider._query_secrets = lambda *_args, **_kwargs: [
        {
            "id": "sec_prompt_safety_test",
            "lookup_key": "safe-test/prompt/ssh",
            "origin": "vault_registry",
            "subject": "safe-test/prompt/ssh",
            "scope": "safe-test/prompt/ssh",
            "secret_type": "ssh_credential",
            "locator": "",
            "purpose": "",
        }
    ]
    rendered = provider._secret_context("safe-test", limit=1)
    assert "secret_context_lookup" not in rendered
    assert "local executor" in rendered.lower()
    assert "safe-test/prompt/ssh" in rendered
