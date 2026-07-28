from __future__ import annotations

import hashlib
import json

from test_repository_scoping_regression import code_args, load_provider


def test_pack_context_excludes_foreign_repository_and_keeps_global_preference(tmp_path, monkeypatch):
    provider = load_provider(tmp_path, monkeypatch)
    foreign = provider._code_claim_add(
        code_args(
            "repo-B",
            "Repository B uses the foreign implementation sentinel",
            symbol="sym_foreign",
            content="foreign-body",
        )
    )
    preference_id = provider._add_claim(
        "The user prefers concise verification summaries",
        "preferences",
        "Explicit durable user preference",
        "explicit_user",
        0.95,
        0.9,
    )

    raw = provider.handle_tool_call(
        "memory_wiki_pack_context",
        {
            "query": "foreign implementation concise verification summaries",
            "max_tokens": 2000,
            "output_mode": "debug",
            "coverage_manifest": {
                "protocol_version": 1,
                "repository_id": "repo-A",
                "covered": [],
            },
        },
    )
    result = json.loads(raw)
    assert result["success"] is True, result
    rendered = json.dumps(result, ensure_ascii=False)
    assert foreign["id"] not in result.get("claim_ids", [])
    assert "foreign implementation sentinel" not in rendered.lower()
    assert preference_id in result.get("claim_ids", []) or "concise verification summaries" in rendered.lower()
    suppressed = result.get("suppression_manifest", {}).get("suppressed", [])
    assert any(
        item.get("claim_id") == foreign["id"]
        and item.get("reason") == "foreign_repository"
        for item in suppressed
    )


def test_pack_context_exact_source_suppresses_duplicate_even_with_contract_after_it(tmp_path, monkeypatch):
    provider = load_provider(tmp_path, monkeypatch)
    digest = hashlib.sha256(b"same-body").hexdigest()
    claim = provider._code_claim_add(
        code_args(
            "repo-A",
            "Service uses port 1234",
            symbol="sym_shared",
            revision="rev1",
            content="same-body",
        )
    )

    raw = provider.handle_tool_call(
        "memory_wiki_pack_context",
        {
            "query": "Service uses port 1234",
            "max_tokens": 2000,
            "output_mode": "debug",
            "coverage_manifest": {
                "protocol_version": 1,
                "repository_id": "repo-A",
                "covered": [
                    {
                        "kind": "exact_source",
                        "file_path": "src/shared.py",
                        "symbol_id": "sym_shared",
                        "revision": "rev1",
                        "content_hash": digest,
                    },
                    {
                        "kind": "contract",
                        "file_path": "src/shared.py",
                        "symbol_id": "sym_shared",
                        "revision": "rev1",
                        "content_hash": "b" * 64,
                    },
                ],
            },
        },
    )
    result = json.loads(raw)
    assert result["success"] is True, result
    assert claim["id"] not in result.get("claim_ids", [])
    suppressed = result.get("suppression_manifest", {}).get("suppressed", [])
    assert any(
        item.get("claim_id") == claim["id"]
        and item.get("reason") == "exact_content_hash_match"
        for item in suppressed
    )
