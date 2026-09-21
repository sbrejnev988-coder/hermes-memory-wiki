"""Claim edits retain canonical visibility identity and deterministic deduplication."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module(name: str):
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _provider(module, home, session: str):
    provider = module.MemoryWikiProvider()
    provider.initialize(
        session, hermes_home=str(home), bot_id="partition-bot",
        agent_context="test",
    )
    provider._ingest_text = lambda *args, **kwargs: None
    return provider


def _add(provider, text: str) -> str:
    return provider._add_claim(
        text,
        "general",
        "Partition hash regression evidence.",
        "phase6_curated_summary:test",
        0.9,
        0.8,
        visibility_scope="chat",
    )


def _apply_edit(provider, path: str, claim_id: str, text: str) -> None:
    if path == "update":
        provider._update_claim({"claim_id": claim_id, "claim": text})
    elif path == "rewrite":
        provider._rewrite_claim({"claim_id": claim_id, "claim": text})
    else:
        operation = "update_claim" if path == "atomic_update" else "rewrite_claim"
        result = provider._transaction([
            {"tool": operation, "args": {"claim_id": claim_id, "claim": text}},
            {"tool": "update_claim", "args": {
                "claim_id": claim_id, "salience": 0.81,
            }},
        ], mode="apply")
        assert result["rolled_back"] is False, result


@pytest.mark.parametrize(
    "path", ("update", "rewrite", "atomic_update", "atomic_rewrite"),
)
def test_edit_hash_is_partitioned_across_chats_and_readd_is_idempotent(
    tmp_path, monkeypatch, path,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module(f"memory_wiki_partition_hash_{path}")
    first = _provider(module, tmp_path, "chat-a")
    second = _provider(module, tmp_path, "chat-b")
    try:
        first_id = _add(first, f"Original observatory fact for {path} chat A.")
        second_id = _add(second, f"Original observatory fact for {path} chat B.")
        target = f"The {path} observatory calibration target is violet."

        _apply_edit(first, path, first_id, target)
        _apply_edit(second, path, second_id, target)

        first_row = first._connect().execute(
            "SELECT * FROM claims WHERE id=?", (first_id,),
        ).fetchone()
        second_row = second._connect().execute(
            "SELECT * FROM claims WHERE id=?", (second_id,),
        ).fetchone()
        assert first_row["hash"] != second_row["hash"]
        assert first_row["hash"] == module.sha(
            first._claim_visibility_identity_scope(first_row)
            + "\0" + module.normalize_claim(target).lower()
        )
        assert second_row["hash"] == module.sha(
            second._claim_visibility_identity_scope(second_row)
            + "\0" + module.normalize_claim(target).lower()
        )

        assert _add(first, target) == first_id
        assert _add(second, target) == second_id
        for provider, row in ((first, first_row), (second, second_row)):
            count = provider._connect().execute(
                """SELECT COUNT(*) FROM claims
                     WHERE status='active' AND normalized_claim=?
                       AND visibility_scope='chat' AND origin_bot_id=?
                       AND origin_chat_hash=?""",
                (
                    module.normalize_claim(target), "partition-bot",
                    row["origin_chat_hash"],
                ),
            ).fetchone()[0]
            assert count == 1
    finally:
        if first._conn is not None:
            first._conn.close()
        if second._conn is not None:
            second._conn.close()


def test_same_partition_collision_fails_without_changing_claims_or_history(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module("memory_wiki_partition_hash_collision")
    provider = _provider(module, tmp_path, "one-chat")
    try:
        first_id = _add(provider, "The amber telescope belongs to the north dome.")
        second_text = "The violet compass belongs to the west dome."
        second_id = _add(provider, second_text)
        conn = provider._connect()
        before = {
            row["id"]: dict(row) for row in conn.execute(
                "SELECT * FROM claims WHERE id IN (?,?)", (first_id, second_id),
            ).fetchall()
        }
        evidence_before = conn.execute(
            "SELECT COUNT(*) FROM evidence WHERE claim_id IN (?,?)",
            (first_id, second_id),
        ).fetchone()[0]
        mutations_before = conn.execute(
            "SELECT COUNT(*) FROM memory_mutations WHERE target_id IN (?,?)",
            (first_id, second_id),
        ).fetchone()[0]

        with pytest.raises(
            ValueError, match="already exists in this visibility partition",
        ):
            provider._rewrite_claim({"claim_id": first_id, "claim": second_text})
        atomic = provider._transaction([
            {"tool": "update_claim", "args": {
                "claim_id": first_id, "claim": second_text,
            }},
            {"tool": "update_claim", "args": {
                "claim_id": first_id, "salience": 0.82,
            }},
        ], mode="apply")
        assert atomic["rolled_back"] is True, atomic

        after = {
            row["id"]: dict(row) for row in conn.execute(
                "SELECT * FROM claims WHERE id IN (?,?)", (first_id, second_id),
            ).fetchall()
        }
        assert after == before
        assert conn.execute(
            "SELECT COUNT(*) FROM evidence WHERE claim_id IN (?,?)",
            (first_id, second_id),
        ).fetchone()[0] == evidence_before
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_mutations WHERE target_id IN (?,?)",
            (first_id, second_id),
        ).fetchone()[0] == mutations_before
    finally:
        if provider._conn is not None:
            provider._conn.close()


def test_code_and_patch_claim_edits_preserve_explicit_identity_scope(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module("memory_wiki_partition_hash_explicit_identity")
    provider = _provider(module, tmp_path, "code-chat")
    try:
        code_id = _add(provider, "Repository code symbol originally returns amber.")
        patch_id = _add(provider, "Patch outcome originally reports amber success.")
        conn = provider._connect()
        with conn:
            conn.execute(
                """INSERT INTO code_claim_metadata(
                       claim_id,repository_id,commit_sha,file_path,symbol_id,
                       symbol_revision,content_hash,claim_type)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    code_id, "repo_one", "commit_one", "src/service.py",
                    "symbol_one", "revision_one", "content_one", "code_claim",
                ),
            )
            conn.execute(
                """INSERT INTO code_claim_metadata(
                       claim_id,repository_id,commit_sha,file_path,symbol_id,
                       symbol_revision,content_hash,claim_type)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    patch_id, "repo_patch", "commit_patch", "src/patch.py",
                    "symbol_patch", "revision_patch", "content_patch",
                    "patch_outcome",
                ),
            )
            conn.execute(
                """INSERT INTO patch_outcomes(
                       repository_id,patch_id,claim_id,outcome,created_at,updated_at)
                   VALUES(?,?,?,?,?,?)""",
                ("repo_patch", "patch_42", patch_id, "passed", 1, 1),
            )

        code_text = "Repository code symbol now returns violet."
        patch_text = "Patch outcome now reports violet success."
        provider._update_claim({"claim_id": code_id, "claim": code_text})
        provider._rewrite_claim({"claim_id": patch_id, "claim": patch_text})
        code_hash = conn.execute(
            "SELECT hash FROM claims WHERE id=?", (code_id,),
        ).fetchone()[0]
        patch_hash = conn.execute(
            "SELECT hash FROM claims WHERE id=?", (patch_id,),
        ).fetchone()[0]
        assert code_hash == module.sha(
            "\0".join((
                "code_claim", "repo_one", "src/service.py", "symbol_one",
                "revision_one",
            )) + "\0" + module.normalize_claim(code_text).lower()
        )
        assert patch_hash == module.sha(
            "\0".join(("patch_outcome", "repo_patch", "patch_42"))
            + "\0" + module.normalize_claim(patch_text).lower()
        )
    finally:
        if provider._conn is not None:
            provider._conn.close()
