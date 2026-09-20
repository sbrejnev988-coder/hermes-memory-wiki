"""Explicit, bounded Google Drive text-file connector.

The host supplies an OAuth access token. This module never searches Drive or
accepts a caller-selected URL: each call fetches one file ID from Google's
fixed API host, checks download permission, and verifies the revision around
content retrieval before marking the record as Drive-sourced.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    from . import source_connectors as connectors
except ImportError:
    import source_connectors as connectors


_FILE_ID = re.compile(r"[A-Za-z0-9_-]{10,200}\Z")
_BLOB_MIME = frozenset({
    "text/plain", "text/markdown", "text/csv", "text/tab-separated-values",
    "application/json", "application/x-yaml", "text/yaml", "text/x-python",
})
_DOC_MIME = "application/vnd.google-apps.document"
_MAX_META_BYTES = 32_768


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("drive_redirect_denied")


def _open(request: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def _request(provider: Any, url: str, token: str, cap: int) -> bytes:
    cooldown = float(getattr(provider, "_drive_rate_limit_until", 0) or 0)
    if cooldown > time.time():
        raise ValueError(f"drive_rate_limited:retry_after_seconds={int(cooldown-time.time())+1}")
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json",
        "User-Agent": "hermes-memory-wiki",
    })
    try:
        timeout = max(2.0, min(float(os.environ.get("MEMORY_WIKI_DRIVE_TIMEOUT_SECONDS", "10")), 15.0))
    except ValueError:
        timeout = 10.0
    try:
        with _open(request, timeout) as response:
            if int(getattr(response, "status", None) or response.getcode()) != 200:
                raise ValueError("drive_http_error")
            length = response.headers.get("Content-Length")
            if length is not None:
                try:
                    declared = int(length)
                except (TypeError, ValueError) as exc:
                    raise ValueError("drive_invalid_content_length") from exc
                if declared < 0 or declared > cap:
                    raise ValueError("drive_response_too_large")
            body = response.read(cap + 1)
            if len(body) > cap:
                raise ValueError("drive_response_too_large")
            return body
    except urllib.error.HTTPError as exc:
        if exc.code in {429, 403}:
            try:
                delay = max(1, min(int(exc.headers.get("Retry-After") or 60), 86400))
            except (TypeError, ValueError):
                delay = 60
            provider._drive_rate_limit_until = time.time() + delay
            raise ValueError(f"drive_rate_limited:retry_after_seconds={delay}") from None
        if exc.code == 401:
            raise ValueError("drive_auth_failed") from None
        if exc.code == 404:
            raise ValueError("drive_source_unavailable") from None
        raise ValueError(f"drive_http_error:{exc.code}") from None


def _metadata(provider: Any, file_id: str, token: str) -> dict[str, Any]:
    fields = "id,name,mimeType,size,md5Checksum,version,trashed,capabilities(canDownload)"
    url = (f"https://www.googleapis.com/drive/v3/files/{file_id}?"
           + urllib.parse.urlencode({"fields": fields, "supportsAllDrives": "true"}))
    raw = _request(provider, url, token, _MAX_META_BYTES)
    try:
        item = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("drive_invalid_metadata") from exc
    if (not isinstance(item, dict) or item.get("id") != file_id
            or item.get("trashed") is not False
            or not isinstance(item.get("capabilities"), dict)
            or item["capabilities"].get("canDownload") is not True):
        raise ValueError("drive_file_not_downloadable")
    mime = str(item.get("mimeType") or "")
    if mime not in _BLOB_MIME and mime != _DOC_MIME:
        raise ValueError("drive_unsupported_text_type")
    version = str(item.get("version") or "")
    if not version.isdigit() or len(version) > 30:
        raise ValueError("drive_invalid_revision")
    if mime != _DOC_MIME:
        try:
            size = int(item.get("size"))
        except (TypeError, ValueError) as exc:
            raise ValueError("drive_invalid_size") from exc
        if size < 0 or size > connectors.MAX_RECORD_BYTES:
            raise ValueError("drive_file_too_large")
    return item


def sync_file(provider: Any, args: dict[str, Any]) -> dict[str, Any]:
    file_id = str(args.get("file_id") or "").strip()
    if not _FILE_ID.fullmatch(file_id):
        raise ValueError("invalid_drive_file_id")
    token = os.environ.get("MEMORY_WIKI_GOOGLE_DRIVE_ACCESS_TOKEN", "").strip()
    if not token:
        raise ValueError("drive_access_token_required")
    if len(token) > 4096 or any(ord(ch) < 33 or ord(ch) > 126 for ch in token):
        raise ValueError("invalid_drive_access_token_configuration")
    scope_id, repository_id = connectors._scope(
        provider, str(args.get("scope_id") or ""), str(args.get("repository_id") or ""),
    )
    uri = f"https://drive.google.com/file/d/{file_id}/view"
    key = connectors._source_key(provider, uri, scope_id, repository_id, "google_drive")
    connectors.authorize_write(provider, key)
    before = _metadata(provider, file_id, token)
    version = str(before["version"])
    existing = provider._connect().execute(
        "SELECT * FROM external_sources WHERE source_key=?", (key,),
    ).fetchone()
    if (existing is not None and existing["status"] == "active"
            and existing["source_type"] == "google_drive"
            and existing["revision_key"] == connectors._sha(version)[:20]):
        staged = connectors._record_snapshot_path(provider, key)
        source = provider._connect().execute(
            "SELECT active FROM document_sources WHERE source_id=?",
            (existing["document_source_id"],),
        ).fetchone()
        if staged.is_file() and source is not None and int(source["active"] or 0):
            return {"status": "unchanged", "source_key": key,
                    "source_id": str(existing["document_source_id"]),
                    "scope_id": scope_id, "repository_id": repository_id}
    if before["mimeType"] == _DOC_MIME:
        url = (f"https://www.googleapis.com/drive/v3/files/{file_id}/export?"
               + urllib.parse.urlencode({"mimeType": "text/plain"}))
    else:
        url = (f"https://www.googleapis.com/drive/v3/files/{file_id}?"
               + urllib.parse.urlencode({"alt": "media", "supportsAllDrives": "true"}))
    raw = _request(provider, url, token, connectors.MAX_RECORD_BYTES)
    after = _metadata(provider, file_id, token)
    if str(after["version"]) != version or after["mimeType"] != before["mimeType"]:
        raise ValueError("drive_revision_changed_during_fetch")
    if before["mimeType"] != _DOC_MIME:
        if len(raw) != int(before["size"]):
            raise ValueError("drive_size_mismatch")
        md5 = str(before.get("md5Checksum") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{32}", md5) or hashlib.md5(raw).hexdigest() != md5.lower():
            raise ValueError("drive_checksum_mismatch")
    if b"\x00" in raw:
        raise ValueError("drive_binary_content")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("drive_file_not_utf8") from exc
    result = connectors.upsert_record(provider, connectors.SourceRecord(
        uri=uri, revision=version, text=text, title=str(before.get("name") or ""),
        scope_id=scope_id, repository_id=repository_id,
        source_type="google_drive", embed=bool(args.get("embed", False)),
    ))
    return {**result, "source_type": "google_drive"}
