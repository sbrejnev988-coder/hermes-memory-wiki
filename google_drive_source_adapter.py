"""Explicit, bounded Google Drive text-file connector.

The host supplies an OAuth access token. This module never searches Drive or
accepts a caller-selected URL: each call fetches one file ID from Google's
fixed API host, checks download permission, and verifies the revision around
content retrieval before marking the record as Drive-sourced.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
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


def _profile_credential(provider: Any, name: str) -> str:
    """Use process credentials only for the profile that owns the process."""
    provider_home = getattr(provider, "home", None)
    if provider_home is None:
        return ""
    ambient_home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    try:
        if Path(provider_home).expanduser().resolve(strict=False) != Path(
            ambient_home
        ).expanduser().resolve(strict=False):
            return ""
    except (OSError, ValueError):
        return ""
    return os.environ.get(name, "").strip()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("drive_redirect_denied")


def _open(request: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


class _ChunkCompletionReader:
    """Observe one native decoder's framing I/O, without parsing chunks.

    CPython accepts EOF in trailers and discards chunk delimiters unchecked.
    Require CRLF at those native read sites and bound total wire overhead.
    No class/parser hook is replaced; the owning response keeps its file.
    """

    def __init__(self, response: http.client.HTTPResponse, cap: int):
        self.response = response
        self.fp = response.fp
        self.remaining = cap + 65_536
        self.terminal_line = False

    def _charge(self, data: bytes) -> None:
        if not isinstance(data, bytes) or len(data) > self.remaining:
            raise ValueError("drive_http_error")
        self.remaining -= len(data)

    def read(self, amount: int) -> bytes:
        if amount < 0 or amount > self.remaining:
            raise ValueError("drive_http_error")
        data = self.fp.read(amount)
        self._charge(data)
        if self.response.chunk_left == 0 and amount == 2 and data != b"\r\n":
            raise ValueError("drive_http_error")
        return data

    def readline(self, limit: int) -> bytes:
        if limit <= 0:
            raise ValueError("drive_http_error")
        line = self.fp.readline(min(limit, self.remaining + 1))
        self._charge(line)
        if not line.endswith(b"\r\n"):
            raise ValueError("drive_http_error")
        self.terminal_line = line == b"\r\n"
        return line

    def close(self) -> None:
        self.fp.close()


def _bounded_complete_body(response: Any, cap: int) -> bytes:
    """Return only a complete bounded body; never infer EOF from short JSON.

    Content-Length must match both returned bytes and native remaining length.
    Native chunk completion additionally requires the terminal trailer CRLF;
    chunk syntax is still decoded by HTTPResponse, not by a second parser.
    Legal native EOF and in-memory BytesIO EOF remain supported. Unknown
    stream/framing contracts fail closed. Ownership/close stays with _request.
    """
    headers = getattr(response, "headers", None)
    length = headers.get("Content-Length") if headers is not None else None
    if headers is not None and hasattr(headers, "get_all"):
        if len(headers.get_all("Content-Length", [])) > 1:
            raise ValueError("drive_invalid_content_length")
        if len(headers.get_all("Transfer-Encoding", [])) > 1:
            raise ValueError("drive_http_error")
    declared = None
    if length is not None:
        try:
            if not isinstance(length, str) or len(length) > 20:
                raise ValueError
            length = length.strip()
            if not length.isascii() or not length.isdecimal():
                raise ValueError
            declared = int(length)
        except (TypeError, ValueError):
            raise ValueError("drive_invalid_content_length") from None
        if declared < 0 or declared > cap:
            raise ValueError("drive_response_too_large")
    stream = response if isinstance(response, http.client.HTTPResponse) else getattr(response, "fp", None)
    native = isinstance(stream, http.client.HTTPResponse)
    if not native and not isinstance(stream, io.BytesIO):
        raise ValueError("drive_http_error")
    transfer = headers.get("Transfer-Encoding", "") if headers is not None else ""
    tap = None
    if native:
        if stream.fp is None or stream.isclosed():
            raise ValueError("drive_http_error")
        if stream.chunked:
            if declared is not None or transfer.strip().lower() != "chunked":
                raise ValueError("drive_http_error")
            tap = _ChunkCompletionReader(stream, cap)
        elif transfer or stream.length != declared:
            raise ValueError("drive_http_error")
    elif transfer or stream.tell() != 0:
        raise ValueError("drive_http_error")
    if tap is not None:
        stream.fp = tap
    parts = []
    total = 0
    eof = False
    try:
        try:
            while total <= cap:
                part = response.read(cap + 1 - total)
                if not isinstance(part, bytes):
                    raise ValueError("drive_http_error")
                if not part:
                    eof = True
                    break
                parts.append(part)
                total += len(part)
                if native and stream.isclosed():
                    break
        except Exception:
            # Native exceptions can carry private partial bodies. Never expose
            # them, and never turn a read/framing failure into quota evidence.
            raise ValueError("drive_http_error") from None
        if total > cap:
            raise ValueError("drive_response_too_large")
        if declared is not None and total != declared:
            raise ValueError("drive_http_error")
        if native:
            if not stream.isclosed() or (declared is not None and stream.length != 0):
                raise ValueError("drive_http_error")
            if tap is not None and (stream.chunk_left is not None or not tap.terminal_line):
                raise ValueError("drive_http_error")
        elif not eof:
            raise ValueError("drive_http_error")
        return b"".join(parts)
    finally:
        # Restore only our own still-open adapter, never resurrect a file the
        # native response closed. HTTPError.close remains the sole owner close.
        if tap is not None and stream.fp is tap:
            stream.fp = tap.fp


def _http_error_kind(exc: urllib.error.HTTPError) -> str:
    """Classify bounded Google error codes; ownership stays with _request."""
    if exc.code == 429:
        # An actual HTTP 429 status is sufficient; no body-derived assertion.
        return "rate"
    if exc.code == 401:
        return "auth"
    if exc.code != 403:
        return "http"
    try:
        raw = _bounded_complete_body(exc, 8192)
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        # Native HTTPResponse framing failures (e.g. IncompleteRead) can carry
        # partial private bodies. Keep all ordinary read/parse failures coded.
        return "http"
    if not isinstance(payload, dict):
        return "http"
    error = payload.get("error")
    # OAuth revoked grants are failures, never a reason to refresh/borrow a token.
    if isinstance(error, str):
        return "auth" if error == "invalid_grant" else "http"
    if not isinstance(error, dict):
        return "http"
    if "code" in error and (type(error["code"]) is not int or error["code"] != exc.code):
        return "http"
    status = error.get("status")
    reasons = error.get("errors", [])
    if not isinstance(reasons, list) or len(reasons) > 16:
        return "http"
    codes = set()
    for reason in reasons:
        if not isinstance(reason, dict):
            return "http"
        code = reason.get("reason")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z_]{1,64}", code):
            return "http"
        codes.add(code)
    if status == "UNAUTHENTICATED" or codes.intersection({
        "authError", "invalidCredentials", "invalidGrant", "invalid_grant",
    }):
        return "auth"
    if status == "RESOURCE_EXHAUSTED" or codes.intersection({
        "rateLimitExceeded", "userRateLimitExceeded", "sharingRateLimitExceeded",
        "dailyLimitExceeded", "storageQuotaExceeded",
    }):
        return "rate"
    if status == "PERMISSION_DENIED" or codes.intersection({
        "insufficientPermissions", "insufficientFilePermissions", "appNotAuthorizedToFile",
        "domainPolicy", "downloadRestrictedForRevision", "teamDriveMembershipRequired", "forbidden",
    }):
        return "permission"
    return "http"


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
            return _bounded_complete_body(response, cap)
    except urllib.error.HTTPError as exc:
        cleanup_failed = False
        try:
            kind = _http_error_kind(exc)
            if kind == "rate":
                retry = exc.headers.get("Retry-After") if exc.headers is not None else None
                delay = 60
                if isinstance(retry, str) and len(retry) <= 32:
                    retry = retry.strip()
                    if re.fullmatch(r"[+-]?[0-9]{1,20}", retry):
                        delay = max(1, min(int(retry), 86400))
                provider._drive_rate_limit_until = time.time() + delay
                error = ValueError(f"drive_rate_limited:retry_after_seconds={delay}")
            elif kind == "auth":
                error = ValueError("drive_auth_failed")
            elif kind == "permission":
                error = ValueError("drive_permission_denied")
            elif exc.code == 404:
                error = ValueError("drive_source_unavailable")
            else:
                error = ValueError(f"drive_http_error:{exc.code}")
        finally:
            try:
                exc.close()
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            error.add_note("drive_http_error_body_close_failed")
        raise error from None


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
    token = _profile_credential(provider, "MEMORY_WIKI_GOOGLE_DRIVE_ACCESS_TOKEN")
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
        try:
            from .github_source_adapter import _complete_cached_source
        except ImportError:
            from github_source_adapter import _complete_cached_source
        return _complete_cached_source(provider, key, scope_id, repository_id,
                                       embed=bool(args.get("embed", False)))
    if (existing is not None and existing["status"] != "active"
            and existing["revision_key"] == connectors._sha(version)[:20]):
        raise ValueError("connector_cache_requires_download")
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
