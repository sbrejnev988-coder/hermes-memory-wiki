"""Small observation policy/hash primitives; no filesystem or SQL authority.

Only source_connectors.observe_local_file supplies admitted indexed metadata
and descriptor samples. A matching hash proves byte equality at a check, never
parser validity, unsaved editor buffers, or a permanent freshness lease.
"""
from __future__ import annotations

import hashlib
import re


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"docrev_[0-9a-f]{28}\Z")
_BLOCK_BYTES = 1024 * 1024
_DISK_STATES = frozenset({"stable", "unstable", "missing", "locked", "unsupported",
                          "too_large", "unavailable", "not_checked"})


def _is_hash(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def empty_indexed_revision():
    return {"state": "unavailable", "revision_id": None, "file_hash": None}


def indexed_revision_evidence(source, revision, connector):
    """Validate an indexed tuple, not its owner or the truth of extracted text.

    The wrapper must establish scope/owner before using this pure projection.
    Unsupported/error derivatives and incoherent connector pointers cannot
    become a usable indexed revision merely because some file hashes match.
    """
    if revision is None:
        return empty_indexed_revision()
    digest, revision_id = source.get("file_hash"), source.get("revision_id")
    if (not _is_hash(digest) or type(revision_id) is not str
            or _REVISION.fullmatch(revision_id) is None
            or source.get("active") != 1 or source.get("status") != "ok"
            or revision.get("status") != "active"
            or type(revision.get("unit_count")) is not int or revision["unit_count"] <= 0
            or not source.get("source_id")
            or revision.get("source_id") != source["source_id"]
            or connector.get("document_source_id") != source["source_id"]
            or revision.get("revision_id") != revision_id
            or revision.get("file_hash") != digest or connector.get("content_hash") != digest
            or connector.get("revision_key") != digest[:20]
            or not source.get("parser") or not source.get("parser_version")
            or any(revision.get(k) != source.get(k) for k in ("parser", "parser_version"))):
        return empty_indexed_revision()
    return {"state": "available", "revision_id": revision_id, "file_hash": digest}


def hash_exact_bytes(read_block, *, size, max_bytes):
    """Hash exactly the admitted size with bounded reads; no opener or snapshot.

    A short read is legal, an early EOF/oversized/non-bytes block is not a
    complete observation. The descriptor owner must also fence size/identity/
    timestamps and compare an independent second pass. Never read a max+1
    probe or materialize the whole document in memory.
    """
    if (type(size) is not int or type(max_bytes) is not int
            or size < 0 or max_bytes < 0 or size > max_bytes):
        raise ValueError("observation_size_refused")
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        count = min(_BLOCK_BYTES, remaining)
        block = read_block(count)
        if type(block) is not bytes or not block or len(block) > count:
            return None
        digest.update(block)
        remaining -= len(block)
    return digest.hexdigest()


def stable_file_hash(stamps, first_hash, second_hash):
    """Six samples: path/open/mid-read/end-read/path/final descriptor.

    Each stamp is (device, inode, size, mtime_ns, ctime_ns). Identity comes from
    the document module's real _file_identity, not from a path/hash inference.
    Physical identity/size agree across APIs; complete images agree only
    within path-stat and within FD-fstat. Windows ctime domains can differ.
    This pure predicate grants no permission to obtain any sample.
    """
    if (type(stamps) is not tuple or len(stamps) != 6
            or not _is_hash(first_hash) or first_hash != second_hash):
        return False
    for stamp in stamps:
        if (type(stamp) is not tuple or len(stamp) != 5
                or any(type(v) is not int for v in stamp)
                or stamp[0] <= 0 or stamp[1] <= 0 or any(v < 0 for v in stamp[2:])):
            return False
    path_before, opened, middle, after_read, path_after, final_descriptor = stamps
    return (all(stamp[:3] == path_before[:3] for stamp in stamps[1:])
            and path_before == path_after
            and opened == middle == after_read == final_descriptor)


def finish_descriptor(close_descriptor, primary):
    """One close attempt; preserve body fatal, otherwise propagate cleanup fatal.

    The caller owns the descriptor and retains any pending body exception.
    This callback seam neither opens an FD nor retries an UNKNOWN close.
    Fixed, best-effort diagnostics must not replace the selected exception.
    """
    try:
        close_descriptor()
    except BaseException as cleanup_error:
        preserve_primary = primary is not None and (
            not isinstance(primary, Exception) or isinstance(cleanup_error, Exception))
        selected = primary if preserve_primary else cleanup_error
        try:
            selected.add_note("observation descriptor cleanup failed; outcome UNKNOWN")
        except BaseException:
            pass
        if not preserve_primary:
            raise


def observation_result(indexed, disk_state, observed_hash, checked_at):
    """Closed response vocabulary; no content, exception text, paths or owner IDs."""
    if disk_state not in _DISK_STATES:
        disk_state = "unavailable"
    if disk_state == "stable" and not _is_hash(observed_hash):
        disk_state = "unstable"
    if disk_state != "stable":
        observed_hash = None  # Never publish a partial/racy digest as evidence.
        status = disk_state + "_at_check"
    elif indexed["state"] != "available":
        status = "indexed_revision_unavailable"
    else:
        status = "current_at_check" if observed_hash == indexed["file_hash"] else "changed_at_check"
    return {"status": status, "indexed_revision": dict(indexed),
            "disk_at_check": {"state": disk_state, "file_hash": observed_hash},
            "checked_at": checked_at, "parser_validity": "not_checked"}


def unobserved_result(status, checked_at):
    if status not in {"invalid_request", "not_authorized", "unavailable_at_check"}:
        status = "unavailable_at_check"
    result = observation_result(empty_indexed_revision(), "not_checked", None, checked_at)
    result["status"] = status
    return result


def file_error_state(error):
    """Classify typed errors only; never stringify raw paths or platform errors."""
    # The existing allowed-path guard wraps OSError in ValueError. Preserve its
    # typed cause, with a small bound and cycle detection, not message parsing.
    seen = set()
    for _ in range(4):
        if id(error) in seen:
            break
        seen.add(id(error))
        if isinstance(error, FileNotFoundError):
            return "missing"
        if isinstance(error, PermissionError):
            return "locked" if getattr(error, "winerror", None) in {32, 33} else "unavailable"
        if isinstance(error, OSError) and getattr(error, "winerror", None) in {32, 33}:
            return "locked"
        error = error.__cause__
        if error is None:
            break
    return "unavailable"
