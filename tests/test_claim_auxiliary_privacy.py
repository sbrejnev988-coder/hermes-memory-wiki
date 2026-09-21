"""Auxiliary metadata and failure diagnostics cannot persist credentials."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
EXTRACTOR = PLUGIN.with_name("extractor.py")


def _load(path: Path, label: str, *, package: bool = False):
    spec = importlib.util.spec_from_file_location(
        label, path, submodule_search_locations=[str(path.parent)] if package else None
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[label] = module
    spec.loader.exec_module(module)
    return module


def test_claim_timezone_and_auxiliary_secrets_are_rejected_before_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _load(PLUGIN, "memory_wiki_claim_aux_privacy", package=True)
    provider = module.MemoryWikiProvider()
    provider.initialize("chat", hermes_home=str(tmp_path), bot_id="test-bot")
    try:
        for extra in (
            {"event_timezone": "password=supersecret-timezone"},
            {"topic": "api_key=sk-test-123456789012345678901234"},
            {"project_id": "Bearer abcdefghijklmnopqrstuvwxyz123456"},
        ):
            with pytest.raises(ValueError, match="secret in claim metadata"):
                provider._add_claim(
                    "My telescope lens is violet.", evidence="ordinary evidence",
                    source="tool", visibility_scope="chat", **extra,
                )
        with pytest.raises(ValueError, match="event timezone"):
            provider._add_claim(
                "My telescope lens is violet.", "general", "ordinary evidence",
                "tool", visibility_scope="chat", event_timezone="not-a-timezone",
            )
        assert provider._connect().execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
    finally:
        provider.shutdown()


def test_validated_code_digest_exception_keeps_other_identity_components_guarded(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _load(PLUGIN, "memory_wiki_code_digest_privacy", package=True)
    provider = module.MemoryWikiProvider()
    provider.initialize("chat", hermes_home=str(tmp_path), bot_id="test-bot")
    digest = "a" * 64
    claim = (
        "Verified snapshot lifecycle for src/main.py: the indexed implementation, "
        "exact content hash, and repository recovery behavior were reviewed."
    )
    try:
        added = provider._code_claim_add({
            "claim": claim,
            "repository_id": "repo-safe",
            "file_path": "src/main.py",
            "content_hash": digest,
            "evidence": "verified exact source revision and lifecycle behavior",
        })
        identity = f"code_claim\0repo-safe\0src/main.py\0{digest}"
        assert added["id"] == "c_" + module.sha(
            identity + "\0" + module.normalize_claim(claim).lower()
        )[:12]

        # This private exception is bound to an exact validated terminal
        # digest. It cannot suppress a secret elsewhere in the identity.
        with pytest.raises(ValueError, match="secret in claim metadata"):
            provider._prepare_claim(
                claim, source="tool:code_claim:code_claim",
                identity_scope=f"code_claim\0password=supersecret-value\0src/main.py\0{digest}",
                _validated_code_content_hash=digest,
            )
        with pytest.raises(ValueError, match="invalid code claim digest identity"):
            provider._prepare_claim(
                claim, source="tool:code_claim:code_claim",
                identity_scope=f"code_claim\0repo-safe\0src/main.py\0{digest}",
                _validated_code_content_hash="b" * 64,
            )
        with pytest.raises(ValueError, match="secret in claim metadata"):
            provider._prepare_claim(
                claim, source="tool:code_claim:code_claim",
                identity_scope=f"code_claim\0repo-safe\0src/main.py\0{digest}",
            )
    finally:
        provider.shutdown()


def test_invalid_qdrant_endpoint_identity_never_contains_credentials():
    module = _load(PLUGIN, "memory_wiki_endpoint_privacy", package=True)
    malformed = "http://user:password-secret@[broken/collection"
    fingerprint = module._normalized_qdrant_endpoint(malformed)
    assert fingerprint.startswith("invalid-endpoint:")
    assert "password" not in fingerprint and "user" not in fingerprint


def test_extractor_errors_never_echo_transcript_or_token(monkeypatch):
    module = _load(EXTRACTOR, "memory_wiki_extractor_errors")
    secret = "password=supersecret-message"
    monkeypatch.setenv("MW_EXTRACTION_ENABLED", "1")
    monkeypatch.setenv("MW_EXTRACTION_BASE_URL", "http://127.0.0.1:18089/v1/chat/completions")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("MW_EXTRACTION_API_KEY", raising=False)

    def failure(*_args, **_kwargs):
        raise RuntimeError("upstream echoed " + secret)

    monkeypatch.setattr(module, "_urlopen_no_redirect", failure)
    result = module.extract_session_claims([
        {"role": "user", "content": "I prefer violet lenses."}
    ])
    assert result["error"] == "RuntimeError"
    assert secret not in str(result)

    monkeypatch.setenv("MW_EXTRACTION_ENABLED", "0")
    result = module.extract_session_claims(
        [{"role": "user", "content": "Remember: My telescope is violet."}],
        add_claim_callback=failure,
    )
    assert result["errors"] == ["RuntimeError"]
    assert secret not in str(result)
