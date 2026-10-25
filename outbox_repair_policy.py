"""Inert decisions for addressed outbox retry; never an authority or a writer.

The provider must first prove its native owner, caller ACL, source/erasure
snapshot and current physical target. These functions cannot confer any of
those capabilities and intentionally have no I/O, provider or queue imports.
"""
from __future__ import annotations

import json
import re

MAX_JOB_IDS = 100
JOB_ID_PATTERN = r"^[0-9a-f]{16}$"
JOB_FIELDS = (
    "id", "operation", "object_type", "object_id", "payload_json", "payload_hash",
    "attempts", "status", "last_error", "created_at", "updated_at", "worker_id",
    "lease_until", "next_retry_at",
)


def validate_job_ids(value):
    """Reject, rather than trim, coerce, truncate or silently deduplicate IDs."""
    if value is None:
        return (), "outbox_job_ids_required"
    if (type(value) is not list or not 1 <= len(value) <= MAX_JOB_IDS
            or any(type(item) is not str or re.fullmatch(JOB_ID_PATTERN, item) is None
                   for item in value)):
        return (), "outbox_job_ids_invalid"
    if len(set(value)) != len(value):
        return (), "outbox_job_ids_invalid"
    return tuple(value), ""


def _object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate key")
        obj[key] = value
    return obj


def _invalid_constant(_value):
    raise ValueError("non-finite JSON")


def decode_payload(raw):
    """A missing/malformed/non-object hint is not a default online target."""
    if type(raw) is not str or not raw.strip():
        return None, "outbox_payload_invalid"
    try:
        payload = json.loads(raw, object_pairs_hook=_object, parse_constant=_invalid_constant)
    except (ValueError, TypeError, RecursionError):
        return None, "outbox_payload_invalid"
    if type(payload) is not dict:
        return None, "outbox_payload_invalid"
    collection = payload.get("collection")
    if (type(collection) is not str or not collection
            or collection != collection.strip() or "\x00" in collection):
        return None, "outbox_target_missing_or_invalid"
    return payload, ""


def same_job(original, current):
    """Complete typed queue image, including lease, attempts and retained error."""
    return (type(original) is dict and type(current) is dict
            and all(key in original and key in current
                    and type(original[key]) is type(current[key])
                    and original[key] == current[key] for key in JOB_FIELDS))


def same_epoch(original, current, own_updates=0):
    """Allow only row-counted own changes, never adopt a fresh source epoch."""
    return (type(original) is tuple and type(current) is tuple
            and len(original) == len(current) == 3
            and type(own_updates) is int and own_updates >= 0
            and type(original[1]) is type(current[1]) is int
            and type(original[2]) is type(current[2]) is int
            and original[:2] == current[:2]
            and current[2] == original[2] + own_updates)


def job_hint(job):
    """Local negative checks, before any target lookup; never default a hint."""
    if not same_job(job, job):
        return None, "outbox_job_image_invalid"
    if job["status"] != "failed":
        return None, "outbox_job_not_failed"
    if job["worker_id"] != "" or type(job["lease_until"]) is not int or job["lease_until"] != 0:
        return None, "outbox_job_leased"
    if type(job["attempts"]) is not int or job["attempts"] < 0:
        return None, "outbox_job_image_invalid"
    if job["operation"] == "delete":
        # The current delete worker can expand a hint to multiple ledger targets.
        # No exact-target, caller-owned deletion capability exists at this seam.
        return None, "outbox_delete_capability_required"
    if job["object_type"] != "claim" or job["operation"] not in {"upsert", "embed_and_upsert"}:
        return None, "outbox_operation_unsupported"
    return decode_payload(job["payload_json"])


def retry_reason(job, claim, *, collection, alias, endpoint, manifest_hash, vector_target_hash):
    """Return a fixed code; inputs are already caller-authorized snapshots.

    Explicit alias hints are accepted only when the provider supplied a freshly
    proven alias binding. The hint is NEVER rewritten. Optional routing fields
    are checked when present; the normal claim enqueue contract has only an
    explicit collection, canonical revision/time and ownership metadata.
    """
    payload, error = job_hint(job)
    if error:
        return error
    if (type(collection) is not str or not collection or type(endpoint) is not str or not endpoint
            or type(manifest_hash) is not str or not manifest_hash
            or type(vector_target_hash) is not str or not vector_target_hash):
        return "outbox_target_unproven"
    if payload["collection"] != collection and not (alias and payload["collection"] == alias):
        return "outbox_target_mismatch"
    for key, expected in (("endpoint", endpoint), ("manifest_hash", manifest_hash),
                          ("vector_target_hash", vector_target_hash)):
        if key in payload and (type(payload[key]) is not str or payload[key] != expected):
            return "outbox_target_mismatch"
    if type(claim) is not dict or claim.get("id") != job["object_id"] or claim.get("status") != "active":
        return "outbox_claim_changed"
    # These fields are supplied by the real _add_claim outbox producer. Missing
    # legacy revision/owner evidence does not authorize replay of retained text.
    for key in ("memory_revision", "updated_at", "event_at", "visibility_scope",
                "origin_bot_id", "origin_session_id", "origin_chat_hash", "project_id"):
        expected = claim.get(key)
        if key not in payload or type(payload[key]) is not type(expected) or payload[key] != expected:
            return "outbox_claim_changed"
    if any(type(payload[key]) is not int or payload[key] < 0
           for key in ("memory_revision", "updated_at", "event_at")):
        return "outbox_claim_changed"
    if "text" in payload and (type(payload["text"]) is not str
                              or payload["text"] != claim.get("normalized_claim")):
        return "outbox_claim_changed"
    return ""
