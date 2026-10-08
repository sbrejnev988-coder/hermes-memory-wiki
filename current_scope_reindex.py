"""Caller-visible, additive reindex; no historical transfer or full-index jobs."""
from __future__ import annotations

from pathlib import Path
from typing import Any


_FIELDS = ("id", "topic", "memory_revision", "updated_at", "visibility_scope",
           "origin_bot_id", "origin_session_id", "origin_chat_hash", "project_id",
           "event_at", "created_at")

_REFUSAL_REASONS = frozenset({
    "scope_erasure_authority_changed", "scope_erasure_replay_required",
    "scope_actor_or_context_changed", "scope_readonly_preflight_unavailable",
    "scope_active_target_binding_unproven", "scope_active_target_not_owned_or_compatible",
    "scope_active_target_contract_unproven", "scope_active_target_changed",
    "scope_claim_changed_or_erased", "scope_claim_text_changed",
    "scope_embedding_unavailable_or_invalid", "scope_upsert_or_readback_failed",
})


def _strict_target(module: Any, manifest: dict, manifest_hash: str) -> tuple[str, str]:
    """Fresh positive authority; legacy alias capability/fallback is not proof."""
    mode = module._qdrant_alias_mode()
    if mode == "physical":
        target, binding = module._physical_collection_name(manifest), "explicit_physical"
    elif mode in {"auto", "require"}:
        response = module._qdrant_req("GET", "/aliases", timeout=3.0)
        if not isinstance(response, dict) or response.get("status") != "ok":
            raise ValueError("scope_active_target_binding_unproven")
        body = response.get("result")
        records = body.get("aliases") if isinstance(body, dict) else None
        if not isinstance(records, list) or any(
                not isinstance(item, dict)
                or type(item.get("alias_name")) is not str or not item["alias_name"].strip()
                or type(item.get("collection_name")) is not str or not item["collection_name"].strip()
                for item in records):
            raise ValueError("scope_active_target_binding_unproven")
        matches = [item for item in records if item["alias_name"] == module._qdrant_alias()]
        if len(matches) != 1:
            raise ValueError("scope_active_target_binding_unproven")
        target, binding = matches[0]["collection_name"], "configured_alias"
    else:
        raise ValueError("scope_active_target_binding_unproven")
    if (not target or target == module._qdrant_alias()
            or not module._is_managed_claim_collection(target)
            or not module._profile_target_allowed(target)
            or manifest_hash not in target.split("_")):
        raise ValueError("scope_active_target_not_owned_or_compatible")
    return target, binding


def reindex(provider: Any, module: Any, limit: int, *, dry_run: bool) -> dict[str, Any]:
    """Use only an already-initialized native caller and its existing target.

    Preflight deliberately avoids _connect, journal, ledger.load/replay and any
    text read. Existing typed erasure authority is inspected, never initialized.
    Scope operations do not become whole-corpus recovery references.
    """
    result: dict[str, Any] = {
        "ok": False, "current_scope_only": True, "dry_run": dry_run,
        "alias_switched": False, "attempts": 0, "ok_count": 0, "failed": 0,
        "status": "refused",
    }
    try:
        conn = getattr(provider, "_conn", None)
        if conn is None or module._set_native_home is None:
            return {**result, "error": "scope_requires_initialized_native_provider"}
        if conn.in_transaction:
            return {**result, "error": "scope_requires_idle_connection"}
        identity = provider._runtime_identity()
        result["runtime_identity"] = identity
        if (not identity.get("conn_path_matches") or not identity.get("profile_ready")
                or Path(identity["request_home"]).resolve() != Path(provider.home).resolve()):
            return {**result, "error": "scope_runtime_identity_mismatch"}
        if not module.SEMANTIC_ENABLED or not module.EMBED_CONTRACT_VALID:
            return {**result, "error": "scope_semantic_contract_unavailable"}
        ledger = getattr(provider, "_privacy_erasure", None)
        if (not isinstance(ledger, module._privacy_erasure.ErasureLedger)
                or ledger.dir.resolve() != (provider.root / "privacy-erasure").resolve()):
            return {**result, "error": "scope_existing_erasure_authority_required"}

        def actor() -> tuple[Any, ...]:
            return (provider.bot_id, provider.session_id, provider.project_scope,
                    getattr(provider, "_bot_scope_trusted", False), provider.platform,
                    provider.agent_context, str(Path(provider.home).resolve()),
                    str(Path(provider.db_path).resolve()), id(provider._conn),
                    module._REQUEST_HOME.get(), module._profile_configuration_generation())

        anchor = actor()
        manifest = module._embedding_manifest()
        manifest_hash = module._manifest_hash(manifest)
        result["manifest_hash"] = manifest_hash

        def erasures() -> list[dict[str, Any]]:
            # Read the bound connection, never _meta_int's lazy _connect path.
            if provider._conn is not conn:
                raise ValueError("scope_actor_or_context_changed")
            if provider._privacy_erasure is not ledger:
                raise ValueError("scope_erasure_authority_changed")
            entries = ledger._load_unlocked()
            seq = conn.execute("SELECT value FROM meta WHERE key=?",
                               ("privacy_erasure_applied_seq",)).fetchone()
            applied = int(seq[0] or 0) if seq is not None else 0
            if applied != len(entries):
                raise ValueError("scope_erasure_replay_required")
            return entries

        def erased_id(row: Any, entries: list[dict[str, Any]]) -> bool:
            digest = ledger.digest("claim-id", str(row["id"]))
            return any(ledger._owner_allows(entry["owner"], row, "claim")
                       and digest in entry["claims"] for entry in entries)

        entries = erasures()
        visibility, params = provider._claim_visibility_sql()
        where = ("status='active' AND normalized_claim IS NOT NULL "
                 "AND normalized_claim!='' AND " + visibility)
        # ACL is in SQL BEFORE ordering/limit. Metadata only; tombstones also
        # precede the work budget. Nothing from the invisible corpus is counted.
        rows = conn.execute("SELECT " + ",".join(_FIELDS) + " FROM claims WHERE "
                            + where + " ORDER BY id", params).fetchall()
        eligible = [row for row in rows if provider._claim_visible(row)
                    and not erased_id(row, entries)]
        if actor() != anchor:
            raise ValueError("scope_actor_or_context_changed")
        result.update(eligible_count=len(eligible), selected_count=min(limit, len(eligible))
                      if limit else len(eligible))
        if not eligible:
            return {**result, "ok": True, "status": "scoped_noop"}
        # The read-only health path uses GET and create=False, never a POST
        # dimension probe, optimistic background refresh or collection bootstrap.
        target, binding = _strict_target(module, manifest, manifest_hash)
        if not module._semantic_available(read_only=True, read_only_target=target):
            raise ValueError("scope_readonly_preflight_unavailable")
        endpoint = module._normalized_qdrant_endpoint()
        def target_contract() -> None:
            config = module._collection_config(target)
            if (not isinstance(config, dict) or type(config.get("size")) is not int
                    or config["size"] != module.QDRANT_VECTOR_SIZE
                    or str(config.get("distance", "")).lower() != "cosine"):
                raise ValueError("scope_active_target_contract_unproven")
        target_contract()
        result.update(collection=target, target_binding=binding, embedding_ok=True)
        if actor() != anchor or module._manifest_hash(module._embedding_manifest()) != manifest_hash:
            raise ValueError("scope_actor_or_context_changed")
        erasures()
        def context_fence() -> None:
            if (actor() != anchor or provider._conn is not conn
                    or module._manifest_hash(module._embedding_manifest()) != manifest_hash
                    or module._normalized_qdrant_endpoint() != endpoint):
                raise ValueError("scope_actor_or_context_changed")
            if _strict_target(module, manifest, manifest_hash) != (target, binding):
                raise ValueError("scope_active_target_changed")
            target_contract()
            # Repeat AFTER awaited/external metadata reads, not merely before.
            if actor() != anchor:
                raise ValueError("scope_actor_or_context_changed")

        context_fence()
        if dry_run:
            return {**result, "ok": True, "status": "scoped_preflight"}

        def current_document(row: Any, expected_hash: str = "") -> str:
            context_fence()
            entries_now = erasures()
            current = conn.execute("SELECT " + ",".join(_FIELDS) + " FROM claims WHERE id=? AND "
                                   + where, (str(row["id"]), *params)).fetchone()
            if (current is None or not provider._claim_visible(current)
                    or tuple(current[key] for key in _FIELDS) != tuple(row[key] for key in _FIELDS)
                    or erased_id(current, entries_now)):
                raise ValueError("scope_claim_changed_or_erased")
            match = " AND ".join(f"{key} IS ?" for key in _FIELDS)
            text_row = conn.execute("SELECT normalized_claim FROM claims WHERE " + where + " AND " + match,
                                    (*params, *(row[key] for key in _FIELDS))).fetchone()
            if text_row is None:
                raise ValueError("scope_claim_changed_or_erased")
            text = str(text_row[0])
            digest = module.sha(text.strip())
            if expected_hash and digest != expected_hash:
                raise ValueError("scope_claim_text_changed")
            normalized = str(module.normalize_claim(text) or "").casefold()
            if any(ledger._owner_allows(entry["owner"], current, "claim")
                   and int(current["created_at"] or 0) <= int(entry["created_at"])
                   and ledger._contains_digest(normalized, entry["claim_text"], "claim-text")
                   for entry in entries_now):
                raise ValueError("scope_claim_changed_or_erased")
            if actor() != anchor:
                raise ValueError("scope_actor_or_context_changed")
            return text

        selected = eligible[:limit] if limit else eligible
        for row in selected:
            result["attempts"] += 1
            try:
                # No registered-vector path at all: invisible vectors cannot
                # become an alternative authority for this operation.
                with provider._lock:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        text = current_document(row)
                    finally:
                        conn.rollback()
                text_hash = module.sha(text.strip())
                vector = module._validate_embedding_vector(module._embed_document(text), "scope claim")
                if vector is None:
                    raise ValueError("scope_embedding_unavailable_or_invalid")
                with provider._lock:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        current_document(row, text_hash)
                        module._record_claim_vector_target(
                            conn, str(row["id"]), collection=target, endpoint=endpoint,
                            manifest_hash=manifest_hash, status="write_pending")
                        conn.commit()  # Crash-safe location before any PUT.
                    finally:
                        if conn.in_transaction:
                            conn.rollback()
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        def before_write() -> None:
                            current_document(row, text_hash)
                        payload = module._qdrant_claim_payload(
                            str(row["id"]), text, row, manifest_hash=manifest_hash)
                        if not module._qdrant_upsert(str(row["id"]), vector, payload, collection=target,
                                                     create_collection=False, before_write=before_write):
                            raise ValueError("scope_upsert_or_readback_failed")
                        current_document(row, text_hash)
                        module._record_claim_vector_target(
                            conn, str(row["id"]), collection=target, endpoint=endpoint,
                            manifest_hash=manifest_hash, status="active", indexed_at=module.now())
                        conn.commit()
                        result["ok_count"] += 1
                    finally:
                        if conn.in_transaction:
                            conn.rollback()
            except Exception:
                # No IDs, remote exception strings or invisible/global totals.
                result["failed"] += 1
        result["remaining"] = len(eligible) - result["ok_count"]
        complete = result["failed"] == 0 and result["remaining"] == 0
        return {**result, "ok": complete, "status": "scoped_completed" if complete else "scoped_partial"}
    except Exception as exc:
        # Code-owned reasons only. Neither private text nor provider errors leak.
        reason = (exc.args[0] if type(exc) is ValueError and len(exc.args) == 1
                  and type(exc.args[0]) is str and exc.args[0] in _REFUSAL_REASONS
                  else "scope_preflight_failed")
        return {**result, "error": reason}
