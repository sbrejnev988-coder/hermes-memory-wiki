"""Bounded GitHub Contents API file connector with explicit provenance.

Only one owner/repository/path is fetched per call. No crawling, download URL,
arbitrary host, or redirect is accepted. A successful GitHub API response is
validated against its declared Git blob object ID before it becomes a record.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
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


MAX_HTTP_BYTES = 1_500_000
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
_BLOB_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_TEXT_EXTENSIONS = frozenset({
    ".md", ".markdown", ".txt", ".rst", ".adoc", ".json",
    ".yaml", ".yml", ".toml", ".csv", ".tsv", ".py",
    ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".c", ".h", ".cpp", ".hpp", ".sh", ".ps1",
})


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
        raise ValueError("github_redirect_denied")


def _open(request: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def _identity(args: dict[str, Any]) -> tuple[str, str, str, str]:
    owner = str(args.get("owner") or "").strip()
    repo = str(args.get("repo") or "").strip()
    path = str(args.get("path") or "").strip()
    ref = str(args.get("ref") or "").strip()
    if not _NAME.fullmatch(owner) or not _NAME.fullmatch(repo):
        raise ValueError("invalid_github_repository")
    if repo in {".", ".."} or repo.endswith(".git"):
        raise ValueError("invalid_github_repository")
    if (not path or len(path) > 512 or "\\" in path or path.startswith("/")
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or Path(path).suffix.lower() not in _TEXT_EXTENSIONS
            or any(ord(char) < 32 for char in path)):
        raise ValueError("invalid_github_text_path")
    if ref and (not _REF.fullmatch(ref) or ".." in ref or "//" in ref):
        raise ValueError("invalid_github_ref")
    return owner, repo, path, ref


def _request_url(owner: str, repo: str, path: str, ref: str) -> str:
    encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
    base = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}"
    return base + ("?" + urllib.parse.urlencode({"ref": ref}) if ref else "")


def _source_uri(owner: str, repo: str, path: str, ref: str) -> str:
    encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
    encoded_ref = urllib.parse.quote(ref or "HEAD", safe="")
    return f"https://github.com/{owner}/{repo}/blob/{encoded_ref}/{encoded_path}"


def _valid_etag(value: Any) -> str:
    etag = str(value or "").strip()
    if (not etag or len(etag) > 200 or any(ord(ch) < 33 or ord(ch) > 126 for ch in etag)
            or not re.fullmatch(r'(?:W/)?"[^"\\]{1,190}"', etag)):
        return ""
    return etag


def _retry_after(headers: Any) -> int:
    raw = str(headers.get("Retry-After") or "")
    try:
        if raw:
            return max(1, min(int(raw), 86400))
    except ValueError:
        pass
    if str(headers.get("X-RateLimit-Remaining") or "") == "0":
        try:
            return max(1, min(int(headers.get("X-RateLimit-Reset")) - int(time.time()), 86400))
        except (TypeError, ValueError):
            pass
    return 60


def _blob_oid(body: bytes, width: int) -> str:
    payload = f"blob {len(body)}\0".encode("ascii") + body
    return (hashlib.sha1(payload).hexdigest() if width == 40
            else hashlib.sha256(payload).hexdigest())


def _decode_file(response_body: bytes, *, requested_path: str) -> tuple[str, str]:
    try:
        obj = json.loads(response_body.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("github_invalid_json") from exc
    if (not isinstance(obj, dict) or obj.get("type") != "file"
            or obj.get("path") != requested_path or obj.get("encoding") != "base64"):
        raise ValueError("github_response_not_regular_file")
    try:
        size = int(obj.get("size"))
    except (TypeError, ValueError) as exc:
        raise ValueError("github_invalid_file_size") from exc
    if size < 0 or size > connectors.MAX_RECORD_BYTES:
        raise ValueError("github_file_too_large")
    encoded = obj.get("content")
    if not isinstance(encoded, str) or len(encoded) > MAX_HTTP_BYTES:
        raise ValueError("github_invalid_content")
    try:
        raw = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
    except binascii.Error as exc:
        raise ValueError("github_invalid_base64") from exc
    if len(raw) != size or len(raw) > connectors.MAX_RECORD_BYTES or b"\x00" in raw:
        raise ValueError("github_invalid_text_file")
    oid = str(obj.get("sha") or "").lower()
    if not _BLOB_OID.fullmatch(oid) or _blob_oid(raw, len(oid)) != oid:
        raise ValueError("github_blob_hash_mismatch")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("github_file_not_utf8") from exc
    return text, oid


def sync_file(provider: Any, args: dict[str, Any]) -> dict[str, Any]:
    owner, repo, path, ref = _identity(args)
    scope_id, repository_id = connectors._scope(
        provider, str(args.get("scope_id") or ""), str(args.get("repository_id") or ""),
    )
    token = _profile_credential(provider, "GITHUB_TOKEN")
    if len(token) > 500 or any(ord(ch) < 33 or ord(ch) > 126 for ch in token):
        raise ValueError("invalid_github_token_configuration")
    source_type = "github_authenticated" if token else "github_public"
    uri = _source_uri(owner, repo, path, ref)
    key = connectors._source_key(provider, uri, scope_id, repository_id, "github")
    connectors.authorize_write(provider, key)
    existing = provider._connect().execute(
        "SELECT * FROM external_sources WHERE source_key=?", (key,),
    ).fetchone()
    prior_etag = ""
    if (existing is not None and existing["status"] == "active"
            and existing["source_type"] == source_type):
        try:
            snapshot = connectors._record_snapshot_path(provider, key)
            document = provider._connect().execute(
                "SELECT active FROM document_sources WHERE source_id=?",
                (existing["document_source_id"],),
            ).fetchone()
            if snapshot.is_file() and document is not None and int(document["active"] or 0):
                prior_etag = _valid_etag(existing["etag"])
        except (OSError, ValueError):
            pass
    cooldown = float(getattr(provider, "_github_rate_limit_until", 0) or 0)
    if cooldown > time.time():
        raise ValueError(f"github_rate_limited:retry_after_seconds={int(cooldown-time.time())+1}")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "hermes-memory-wiki",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if prior_etag:
        headers["If-None-Match"] = prior_etag
    request = urllib.request.Request(_request_url(owner, repo, path, ref), headers=headers)
    try:
        timeout = max(2.0, min(float(os.environ.get("MEMORY_WIKI_GITHUB_TIMEOUT_SECONDS", "10")), 15.0))
    except ValueError:
        timeout = 10.0
    try:
        with _open(request, timeout) as response:
            status = int(getattr(response, "status", None) or response.getcode())
            response_headers = response.headers
            if status == 304:
                if not prior_etag:
                    raise ValueError("github_unexpected_not_modified")
                return {"status": "unchanged", "source_key": key,
                        "source_id": str(existing["document_source_id"]),
                        "scope_id": scope_id, "repository_id": repository_id,
                        "conditional_hit": True}
            if status != 200:
                raise ValueError(f"github_http_error:{status}")
            length = response_headers.get("Content-Length")
            if length is not None:
                try:
                    declared_length = int(length)
                except (TypeError, ValueError) as exc:
                    raise ValueError("github_invalid_content_length") from exc
                if declared_length < 0 or declared_length > MAX_HTTP_BYTES:
                    raise ValueError("github_response_too_large")
            response_body = response.read(MAX_HTTP_BYTES + 1)
            if len(response_body) > MAX_HTTP_BYTES:
                raise ValueError("github_response_too_large")
            etag = _valid_etag(response_headers.get("ETag"))
            if str(response_headers.get("X-RateLimit-Remaining") or "") == "0":
                provider._github_rate_limit_until = time.time() + _retry_after(response_headers)
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and prior_etag:
            return {"status": "unchanged", "source_key": key,
                    "source_id": str(existing["document_source_id"]),
                    "scope_id": scope_id, "repository_id": repository_id,
                    "conditional_hit": True}
        if exc.code in {403, 429}:
            retry = _retry_after(exc.headers)
            provider._github_rate_limit_until = time.time() + retry
            raise ValueError(f"github_rate_limited:retry_after_seconds={retry}") from None
        if exc.code == 401:
            raise ValueError("github_auth_failed") from None
        if exc.code == 404:
            # Private repositories also use 404 for unauthorized callers.
            # Never infer deletion from an ambiguous response.
            raise ValueError("github_source_unavailable") from None
        raise ValueError(f"github_http_error:{exc.code}") from None
    text, oid = _decode_file(response_body, requested_path=path)
    result = connectors.upsert_record(provider, connectors.SourceRecord(
        uri=uri, revision=oid, text=text, title=Path(path).name,
        scope_id=scope_id, repository_id=repository_id,
        source_type=source_type, embed=bool(args.get("embed", False)),
    ))
    with provider._connect() as conn:
        # A validated fetch may match an earlier unverified record byte for
        # byte. The generic upsert can then return unchanged; provenance must
        # still reflect this successfully verified GitHub response.
        conn.execute("UPDATE external_sources SET etag=?,source_type=? WHERE source_key=?",
                     (etag, source_type, key))
    return {**result, "source_type": source_type, "github_blob_oid": oid,
            "etag_used": bool(prior_etag)}
