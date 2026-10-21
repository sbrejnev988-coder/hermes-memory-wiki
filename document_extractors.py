"""Safe, structure-aware document extraction for Hermes Memory Wiki.

The module deliberately has a useful stdlib-only baseline. Optional libraries
improve fidelity but are never required for DOCX/XLSX/PPTX/ODF/XML/text formats.
Legacy Office and exotic formats use an explicitly configured local Apache Tika
server as a bounded fallback.

Every parser returns addressable ``units``. A unit is a page, paragraph, row,
cell, slide, note, section, heading or other structural element. Embeddings are
created later for semantic chunks assembled from these units, never for every
single cell or line.
"""
from __future__ import annotations

import csv
import email
import hashlib
import html
import io
import ipaddress
import itertools
import json
import mimetypes
import math
import os
import re
import subprocess
import threading
import time
import unicodedata
from contextlib import ExitStack
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field, asdict
from email import policy
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

# Package import in the plugin; the standalone SOURCE/worker path binds the
# same shipped module, never an optional spreadsheet engine.
if __package__:
    from .spreadsheet_formulas import evaluate_cells
else:
    from spreadsheet_formulas import evaluate_cells

EXTRACTOR_VERSION = "3.1.8"
SECRET_POLICY_VERSION = "3.0.0"
# Separate documentKG representation policy; parser/evaluator semantics did not change.
XLSX_IDENTITY_POLICY = "xlsx-literal-structure-v1"

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".ini", ".cfg", ".conf",
    ".toml", ".yaml", ".yml", ".json", ".jsonl", ".ndjson", ".xml",
    ".html", ".htm", ".xhtml", ".csv", ".tsv", ".sql", ".rtf",
}
OOXML_EXTENSIONS = {".docx", ".docm", ".dotx", ".xlsx", ".xlsm", ".xltx", ".pptx", ".pptm", ".potx"}
ODF_EXTENSIONS = {".odt", ".ods", ".odp", ".odg", ".ott", ".ots", ".otp"}
PDF_EXTENSIONS = {".pdf"}
EMAIL_EXTENSIONS = {".eml"}
EBOOK_EXTENSIONS = {".epub"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
LEGACY_OFFICE_EXTENSIONS = {
    ".doc", ".xls", ".ppt", ".vsd", ".pub", ".wps",
    ".msg", ".pages", ".numbers", ".key",
}
GOOGLE_POINTER_EXTENSIONS = {".gdoc", ".gsheet", ".gslides", ".gdraw"}
SUPPORTED_EXTENSIONS = (
    TEXT_EXTENSIONS | OOXML_EXTENSIONS | ODF_EXTENSIONS | PDF_EXTENSIONS |
    EMAIL_EXTENSIONS | EBOOK_EXTENSIONS | IMAGE_EXTENSIONS |
    LEGACY_OFFICE_EXTENSIONS | GOOGLE_POINTER_EXTENSIONS
)

_SECRET_LABEL_RE = re.compile(
    r"(?ix)^\s*(?:"
    r"password|passwd|passcode|pwd|парол(?:ь|я|и|ем)?|код[ _-]?доступа|"
    r"api[ _-]?key|access[ _-]?key|secret[ _-]?key|client[ _-]?secret|"
    r"token|токен|секрет|authorization|авторизац(?:ия|ии)|"
    r"private[ _-]?key|приватн(?:ый|ого)[ _-]?ключ|ssh[ _-]?key"
    r")\s*[:=\-–—]?\s*$"
)
_SECRET_ASSIGN_RE = re.compile(
    r"(?ix)(?P<label>\b(?:"
    r"password|passwd|passcode|pwd|парол(?:ь|я|и|ем)?|код[ _-]?доступа|"
    r"api[ _-]?key|access[ _-]?key|secret[ _-]?key|client[ _-]?secret|"
    r"token|токен|секрет|authorization|авторизац(?:ия|ии)|"
    r"private[ _-]?key|приватн(?:ый|ого)[ _-]?ключ|ssh[ _-]?key"
    r")\b\s*(?:[:=|]|[-–—]>?|\s{1,4})\s*)"
    r"(?:"
    r"(?P<quote>[\"'])(?P<quoted>[^\"']{4,})(?P=quote)"
    r"|(?:bearer\s+)?(?P<bare>[^\s|,;\"']{4,})"
    r")"
)
_PROVIDER_SECRET_PATTERNS = [
    ("openai", re.compile(r"(?<![A-Za-z0-9])[s]k-(?:proj-)?[A-Za-z0-9_-]{16,}")),
    ("github", re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("aws_access_key", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    ("google_api_key", re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{30,}")),
    ("slack", re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{16,}")),
    ("jwt", re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
]
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_URL_CREDENTIAL_RE = re.compile(r"(?i)\b(https?://)([^\s/@:]+):([^\s/@]+)@")
_FORMULA_REF_RE = re.compile(r"(?<![A-Za-z0-9_])(?:'([^']+)'|([A-Za-z0-9_ ]+))?!?\$?([A-Z]{1,3})\$?(\d+)")


def _is_secret_label(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and len(text) <= 80 and _SECRET_LABEL_RE.fullmatch(text))


def redact_secret_text(value: Any, limit: int = 200_000) -> Tuple[str, List[Dict[str, Any]]]:
    """Redact secrets before any SQLite, FTS or embedding persistence.

    The detector combines labelled assignments, well-known provider token shapes,
    URL credentials and PEM private-key blocks.  It never returns a raw secret in
    findings; only category and count are exposed for diagnostics.
    """
    text = str(value or "").replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    findings: List[Dict[str, Any]] = []

    def note(category: str) -> None:
        findings.append({"category": category})

    def replace_assignment(match: re.Match[str]) -> str:
        label = match.group("label")
        note("labelled_secret")
        return f"{label}<REDACTED>"

    text = _PRIVATE_KEY_RE.sub(lambda _m: (note("private_key") or "<REDACTED_PRIVATE_KEY>"), text)
    text = _URL_CREDENTIAL_RE.sub(lambda m: (note("url_credentials") or f"{m.group(1)}<REDACTED>@"), text)
    text = _SECRET_ASSIGN_RE.sub(replace_assignment, text)
    for category, pattern in _PROVIDER_SECRET_PATTERNS:
        text = pattern.sub(lambda _m, category=category: (note(category) or "<REDACTED>"), text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text[: max(0, int(limit))], findings


def sanitize_table_cells(cells: Sequence[Any], headers: Optional[Sequence[Any]] = None) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Context-aware redaction for CSV/Word/Excel rows.

    Handles both header-oriented tables (``Password`` column) and key/value rows
    (``Пароль | value``).  Raw values are replaced before building unit text or
    metadata, so they never reach SQLite/FTS/Qdrant.
    """
    raw = [str(item or "") for item in cells]
    safe: List[str] = []
    findings: List[Dict[str, Any]] = []
    header_values = [str(item or "") for item in (headers or [])]
    secret_columns = {idx for idx, item in enumerate(header_values) if _is_secret_label(item)}
    label_columns = {idx for idx, item in enumerate(raw) if _is_secret_label(item)}
    adjacent_secret_columns = {idx + 1 for idx in label_columns if idx + 1 < len(raw)}

    for idx, item in enumerate(raw):
        if item and (idx in secret_columns or idx in adjacent_secret_columns):
            safe.append("<REDACTED>")
            findings.append({"category": "table_context", "column": idx + 1})
            continue
        redacted, local = redact_secret_text(item, 200_000)
        safe.append(redacted)
        findings.extend({**entry, "column": idx + 1} for entry in local)
    return safe, findings



def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, block: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(block)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def clean_text(value: Any, limit: int = 200_000) -> str:
    return redact_secret_text(value, limit)[0]


def sanitize_json(value: Any, *, depth: int = 0, max_depth: int = 8,
                  max_items: int = 10_000, max_string: int = 20_000) -> Any:
    """Return a JSON-safe, bounded and secret-redacted copy.

    Extracted text was already redacted, but parser metadata previously retained
    raw spreadsheet cell values, Google-pointer fields and PDF metadata.  Since
    metadata is returned by document tools, it must cross the same redaction
    boundary as visible text.
    """
    if depth >= max_depth:
        return "<MAX_DEPTH>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return clean_text(value, max_string)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<BINARY:{len(value)} bytes>"
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                out["<TRUNCATED>"] = len(value) - max_items
                break
            safe_key = clean_text(key, 500)
            out[safe_key] = sanitize_json(
                item, depth=depth + 1, max_depth=max_depth,
                max_items=max_items, max_string=max_string,
            )
        return out
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        out = [
            sanitize_json(
                item, depth=depth + 1, max_depth=max_depth,
                max_items=max_items, max_string=max_string,
            )
            for item in seq[:max_items]
        ]
        if len(seq) > max_items:
            out.append(f"<TRUNCATED:{len(seq) - max_items}>")
        return out
    return clean_text(value, max_string)


def decode_text(data: bytes) -> Tuple[str, str]:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        encodings = ["utf-16", "utf-8-sig", "utf-8", "cp1251", "latin-1"]
    else:
        encodings = ["utf-8-sig", "utf-8", "cp1251", "cp1252", "latin-1"]
    for enc in encodings:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace"), "utf-8-replace"


@dataclass
class Unit:
    kind: str
    anchor: str
    text: str
    title: str = ""
    parent_anchor: str = ""
    ordinal: int = 0
    locator: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        item = asdict(self)
        item["text"] = clean_text(item["text"])
        item["title"] = clean_text(item["title"], 2000)
        item["anchor"] = clean_text(item["anchor"], 2000)
        item["parent_anchor"] = clean_text(item["parent_anchor"], 2000)
        item["locator"] = sanitize_json(item.get("locator") or {})
        item["metadata"] = sanitize_json(item.get("metadata") or {})
        # Restore only a validated sheet identity/structural pair, not arbitrary
        # locator keys or text. The literal path still runs the secret detector.
        sheet = (self.locator.get("sheet") if getattr(self, "_xlsx_literal_output", False) is True
                 and type(self.locator) is dict else None)
        if type(sheet) is str:
            index, row = self.locator.get("sheet_index"), self.locator.get("row")
            if (self.kind == "sheet" and type(index) is int and 1 <= index <= 10000
                    and self.anchor == f"sheet:{index}" and self.title == sheet):
                item["locator"]["sheet"] = item["title"] = _xlsx_literal_id(sheet)
            elif (self.kind == "table_row" and type(row) is int and 1 <= row <= 1048576
                    and self.anchor == f"sheet:{sheet}/row:{row}"
                    and re.fullmatch(r"sheet:(?:[1-9][0-9]{0,3}|10000)", self.parent_anchor)):
                item["locator"]["sheet"] = _xlsx_literal_id(sheet)
                item["anchor"] = _xlsx_output_anchor(self.anchor)
        return item


@dataclass
class ExtractedDocument:
    parser: str
    mime_type: str
    title: str
    units: List[Unit]
    metadata: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "ok"

    def to_dict(self) -> Dict[str, Any]:
        item = {
            "extractor_version": EXTRACTOR_VERSION,
            "parser": self.parser,
            "mime_type": self.mime_type,
            "title": clean_text(self.title, 2000),
            "units": [u.to_dict() for u in self.units],
            "metadata": sanitize_json(self.metadata),
            "warnings": sanitize_json(self.warnings, max_string=4000),
            "edges": sanitize_json(self.edges, max_string=4000),
            "status": self.status,
        }
        if self.parser == "stdlib-xlsx-ooxml":
            names = self.metadata.get("sheets")
            if type(names) is list and len(names) <= 10000:
                item["metadata"]["sheets"] = [_xlsx_literal_id(name) for name in names]
            for original, edge in zip(self.edges[:10000], item["edges"]):
                if (type(original) is dict and type(edge) is dict
                        and original.get("predicate") == "formula_ref"):
                    for key in ("source_anchor", "target_anchor"):
                        edge[key] = _xlsx_output_anchor(original.get(key))
        return item


class _VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.blocks: List[Tuple[str, str]] = []
        self.current: List[str] = []
        self.current_tag = "p"
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote", "pre"}:
            self._flush()
            self.current_tag = "heading" if tag.startswith("h") else ("table_row" if tag == "tr" else tag)
        elif tag in {"br", "hr"}:
            self.current.append("\n")
        elif tag in {"td", "th"} and self.current:
            self.current.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote", "pre"}:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = html.unescape(data)
        if self._in_title:
            self.title += value
        self.current.append(value)

    def _flush(self) -> None:
        text = re.sub(r"[ \t]+", " ", "".join(self.current)).strip()
        if text:
            self.blocks.append((self.current_tag, text))
        self.current = []
        self.current_tag = "p"

    def finish(self) -> None:
        self._flush()


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _zip_guard(zf: zipfile.ZipFile, *, max_entries: int, max_uncompressed: int,
               max_ratio: int, max_member: int | None = None) -> None:
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise ValueError(f"archive has {len(infos)} entries; limit={max_entries}")
    total = 0
    for info in infos:
        if info.is_dir():
            continue
        total += int(info.file_size)
        if total > max_uncompressed:
            raise ValueError(f"archive expands beyond {max_uncompressed} bytes")
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or "../" in f"/{name}":
            raise ValueError(f"unsafe archive path: {name}")
        if max_member is not None and int(info.file_size) > max_member:
            raise ValueError(f"archive member exceeds configured limit ({max_member} bytes): {info.filename}")
        compressed = max(1, int(info.compress_size))
        if int(info.file_size) > 1024 * 1024 and int(info.file_size) / compressed > max_ratio:
            raise ValueError(f"suspicious compression ratio for {info.filename}")


def _read_zip_xml(zf: zipfile.ZipFile, name: str, max_bytes: int = 32_000_000) -> ET.Element:
    info = zf.getinfo(name)
    if info.file_size > max_bytes:
        raise ValueError(f"XML part too large: {name}")
    with zf.open(info) as fh:
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"XML part exceeds {max_bytes} bytes: {name}")
    xml_upper = data.upper()
    if b"<!DOCTYPE" in xml_upper or b"<!ENTITY" in xml_upper:
        raise ValueError("DTD/entity declarations are not allowed in document XML")
    return ET.fromstring(data)


def _read_zip_member(zf: zipfile.ZipFile, name: str, max_bytes: int) -> bytes:
    info = zf.getinfo(name)
    if int(info.file_size) > max_bytes:
        raise ValueError(f"archive member too large: {name}")
    chunks: List[bytes] = []
    total = 0
    with zf.open(info) as fh:
        while True:
            block = fh.read(min(1024 * 1024, max_bytes + 1))
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                raise ValueError(f"archive member exceeds {max_bytes} bytes: {name}")
            chunks.append(block)
    return b"".join(chunks)


def _mime_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    ext = path.suffix.lower()
    overrides = {
        ".md": "text/markdown", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".odt": "application/vnd.oasis.opendocument.text", ".ods": "application/vnd.oasis.opendocument.spreadsheet",
        ".odp": "application/vnd.oasis.opendocument.presentation", ".epub": "application/epub+zip",
        ".eml": "message/rfc822",
    }
    return overrides.get(ext, guessed or "application/octet-stream")


def _unit(kind: str, anchor: str, text: Any, *, title: str = "", parent: str = "", ordinal: int = 0, locator=None, metadata=None) -> Unit:
    return Unit(kind=kind, anchor=anchor, text=clean_text(text), title=title, parent_anchor=parent,
                ordinal=ordinal, locator=dict(locator or {}), metadata=dict(metadata or {}))


def extract_plain(path: Path, data: bytes, max_units: int) -> ExtractedDocument:
    text, encoding = decode_text(data)
    ext = path.suffix.lower()
    title = path.stem
    units: List[Unit] = []
    if ext in {".html", ".htm", ".xhtml"}:
        parser = _VisibleHTML(); parser.feed(text); parser.finish()
        title = parser.title.strip() or title
        for i, (kind, block) in enumerate(parser.blocks[:max_units], 1):
            units.append(_unit(kind, f"block:{i}", block, title=block[:120] if kind == "heading" else "", ordinal=i))
        return ExtractedDocument("stdlib-html", _mime_for(path), title, units, {"encoding": encoding})
    if ext in {".json", ".jsonl", ".ndjson"}:
        if ext == ".json":
            try:
                obj = json.loads(text)
                def walk(value: Any, pointer: str = "") -> None:
                    if len(units) >= max_units:
                        return
                    if isinstance(value, dict):
                        for key, child in value.items():
                            walk(child, pointer + "/" + str(key).replace("~", "~0").replace("/", "~1"))
                    elif isinstance(value, list):
                        for idx, child in enumerate(value):
                            walk(child, pointer + f"/{idx}")
                    else:
                        units.append(_unit("json_value", f"json:{pointer or '/'}", f"{pointer or '/'} = {value}", ordinal=len(units)+1,
                                           locator={"json_pointer": pointer or "/"}))
                walk(obj)
                return ExtractedDocument("stdlib-json", "application/json", title, units, {"encoding": encoding})
            except Exception:
                pass
        for i, line in enumerate(text.splitlines()[:max_units], 1):
            if line.strip():
                units.append(_unit("json_line", f"line:{i}", line, ordinal=i, locator={"line": i}))
        return ExtractedDocument("stdlib-jsonl", "application/x-ndjson", title, units, {"encoding": encoding})
    if ext in {".csv", ".tsv"}:
        delim = "\t" if ext == ".tsv" else ","
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        sampled = list(itertools.islice(reader, max_units + 1))
        truncated = len(sampled) > max_units
        rows = sampled[:max_units]
        header = [str(v) for v in (rows[0] if rows else [])]
        max_columns = 0
        for r_idx, row in enumerate(rows, 1):
            raw_cells = [str(v) for v in row]
            cells, findings = sanitize_table_cells(raw_cells, header if r_idx > 1 else None)
            max_columns = max(max_columns, len(cells))
            label = " | ".join(f"{clean_text(header[i], 500)}={v}" if i < len(header) and r_idx > 1 else v for i, v in enumerate(cells))
            units.append(_unit("table_row", f"row:{r_idx}", label, ordinal=r_idx,
                               locator={"row": r_idx}, metadata={"cells": cells, "secret_findings": findings}))
        warnings = ["max_units reached; CSV rows were truncated"] if truncated else []
        return ExtractedDocument(
            "stdlib-csv", "text/tab-separated-values" if ext == ".tsv" else "text/csv", title, units,
            {"encoding": encoding, "delimiter": delim, "rows_indexed": len(rows), "columns": max_columns,
             "truncated": truncated}, warnings=warnings,
        )
    if ext == ".rtf":
        # Conservative RTF fallback. Tika/LibreOffice remains preferable for complex RTF.
        stripped = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
        stripped = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", stripped)
        stripped = stripped.replace("{", " ").replace("}", " ")
        text = html.unescape(re.sub(r"[ \t]+", " ", stripped))
    lines = text.splitlines()
    current: List[str] = []
    anchor_no = 0
    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()
        heading = bool(re.match(r"^(#{1,6}\s+|[A-ZА-ЯЁ][^.!?]{0,120}:$)", stripped))
        if heading and current:
            anchor_no += 1
            units.append(_unit("paragraph", f"paragraph:{anchor_no}", "\n".join(current), ordinal=anchor_no,
                               locator={"start_line": line_no - len(current), "end_line": line_no - 1}))
            current = []
        if heading:
            anchor_no += 1
            units.append(_unit("heading", f"heading:{anchor_no}", stripped, title=stripped.lstrip("# "), ordinal=anchor_no,
                               locator={"line": line_no}))
        elif stripped:
            current.append(line)
        elif current:
            anchor_no += 1
            units.append(_unit("paragraph", f"paragraph:{anchor_no}", "\n".join(current), ordinal=anchor_no,
                               locator={"end_line": line_no - 1}))
            current = []
        if len(units) >= max_units:
            break
    if current and len(units) < max_units:
        anchor_no += 1
        units.append(_unit("paragraph", f"paragraph:{anchor_no}", "\n".join(current), ordinal=anchor_no))
    return ExtractedDocument("stdlib-text", _mime_for(path), title, units, {"encoding": encoding, "line_count": len(lines)})


def extract_docx(path: Path, max_units: int, zip_limits: Dict[str, int]) -> ExtractedDocument:
    units: List[Unit] = []; warnings: List[str] = []
    with zipfile.ZipFile(path) as zf:
        _zip_guard(zf, **zip_limits)
        root = _read_zip_xml(zf, "word/document.xml")
        body = next((e for e in root.iter() if _xml_local(e.tag) == "body"), root)
        para_no = table_no = 0
        for child in list(body):
            if len(units) >= max_units:
                warnings.append("max_units reached")
                break
            local = _xml_local(child.tag)
            if local == "p":
                text = "".join(t.text or "" for t in child.iter() if _xml_local(t.tag) in {"t", "tab", "br"})
                text = clean_text(text).strip()
                if text:
                    para_no += 1
                    style = ""
                    for el in child.iter():
                        if _xml_local(el.tag) == "pStyle":
                            style = next(iter(el.attrib.values()), "")
                            break
                    kind = "heading" if style.lower().startswith("heading") or style.lower().startswith("заголов") else "paragraph"
                    units.append(_unit(kind, f"paragraph:{para_no}", text, title=text[:160] if kind == "heading" else "",
                                       ordinal=len(units)+1, locator={"paragraph": para_no}, metadata={"style": style}))
            elif local == "tbl":
                table_no += 1
                row_no = 0
                table_header: List[str] = []
                for tr in (e for e in child.iter() if _xml_local(e.tag) == "tr"):
                    if len(units) >= max_units:
                        warnings.append("max_units reached")
                        break
                    row_no += 1
                    raw_cells = []
                    for tc in (e for e in list(tr) if _xml_local(e.tag) == "tc"):
                        raw_cells.append(" ".join(t.text or "" for t in tc.iter() if _xml_local(t.tag) == "t").strip())
                    cells, findings = sanitize_table_cells(raw_cells, table_header if row_no > 1 else None)
                    if row_no == 1:
                        table_header = [clean_text(value, 500) for value in raw_cells]
                    units.append(_unit("table_row", f"table:{table_no}/row:{row_no}", " | ".join(cells),
                                       parent=f"table:{table_no}", ordinal=len(units)+1,
                                       locator={"table": table_no, "row": row_no},
                                       metadata={"cells": cells, "secret_findings": findings}))
            if len(units) >= max_units:
                warnings.append("max_units reached")
                break
        for name in sorted(n for n in zf.namelist() if re.match(r"word/(header|footer)\d+\.xml$", n)):
            try:
                xroot = _read_zip_xml(zf, name)
                text = clean_text(" ".join(t.text or "" for t in xroot.iter() if _xml_local(t.tag) == "t")).strip()
                if text and len(units) < max_units:
                    kind = "header" if "/header" in name else "footer"
                    units.append(_unit(kind, name, text, ordinal=len(units)+1, locator={"part": name}))
            except Exception as exc:
                warnings.append(f"{name}: {type(exc).__name__}")
        title = path.stem
        try:
            props = _read_zip_xml(zf, "docProps/core.xml")
            title = next((e.text for e in props.iter() if _xml_local(e.tag) == "title" and e.text), title)
        except Exception:
            pass
    return ExtractedDocument("stdlib-docx-ooxml", _mime_for(path), title, units, warnings=warnings)


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = _read_zip_xml(zf, "xl/sharedStrings.xml")
    out = []
    for si in (e for e in root.iter() if _xml_local(e.tag) == "si"):
        out.append("".join(t.text or "" for t in si.iter() if _xml_local(t.tag) == "t"))
    return out


def _xlsx_sheet_parts(zf: zipfile.ZipFile) -> List[Tuple[str, str]]:
    """Exact IDs; worksheet-only legacy archives require BOTH metadata parts absent."""
    names = zf.namelist()
    if len(names) != len(set(names)):
        raise ValueError("xlsx_duplicate_archive_member")
    if "xl/workbook.xml" not in names and "xl/_rels/workbook.xml.rels" not in names:
        fallback = sorted((n for n in names if re.fullmatch(r"xl/worksheets/sheet[0-9]+\.xml", n)),
                          key=lambda n: int(re.search(r"([0-9]+)", n)[1]))
        return [(f"Sheet{index}", name) for index, name in enumerate(fallback, 1)]
    workbook = _read_zip_xml(zf, "xl/workbook.xml")
    rels = _read_zip_xml(zf, "xl/_rels/workbook.xml.rels")
    targets: Dict[str, str] = {}
    for rel in (e for e in rels.iter() if _xml_local(e.tag) == "Relationship"):
        rid, target = rel.get("Id", ""), rel.get("Target", "")
        if not rid or rid in targets:
            raise ValueError("xlsx_invalid_relationship_id")
        if rel.get("TargetMode", "Internal") != "Internal":
            targets[rid] = ""  # never fetch external relationships
            continue
        if target.startswith("/xl/"):
            target = target[1:]
        elif not target.startswith("xl/"):
            target = "xl/" + target
        if "\\" in target or any(p in {"", ".", ".."} for p in target.split("/")):
            raise ValueError("xlsx_invalid_relationship_target")
        targets[rid] = target
    parts, ids, sheets, used_parts = [], set(), set(), set()
    for sheet in (e for e in workbook.iter() if _xml_local(e.tag) == "sheet"):
        name, sid = sheet.get("name", ""), sheet.get("sheetId", "")
        rid = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", sheet.get("r:id", ""))
        if (not name or len(name) > 1024 or name in sheets or not re.fullmatch(r"[1-9][0-9]{0,9}", sid, re.ASCII)
                or int(sid) > 4294967295 or sid in ids or rid not in targets):
            raise ValueError("xlsx_invalid_or_duplicate_sheet_id")
        target = targets[rid]
        if target and target in used_parts:
            raise ValueError("xlsx_duplicate_sheet_part")
        ids.add(sid); sheets.add(name); used_parts.add(target)
        parts.append((name, target))  # missing targets remain visible to coverage
    return parts


def _xlsx_coordinate(value: str) -> Tuple[int, int]:
    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", value, re.ASCII)
    if match is None:
        raise ValueError("xlsx_invalid_literal_cell_id")
    column = 0
    for char in match[1]:
        column = column * 26 + ord(char) - ord("A") + 1
    row = int(match[2])
    if column > 16384 or row > 1048576:
        raise ValueError("xlsx_invalid_literal_cell_id")
    return column, row


def _xlsx_scalar_text(value: Any) -> str:
    """Legacy cell.value stays a string; value_type retains scalar distinctions."""
    if value is None:
        return ""
    if type(value) is bool:
        return "TRUE" if value else "FALSE"
    if type(value) is float and value.is_integer():
        return str(int(value))
    return str(value)


def _xlsx_literal_id(value: Any) -> str:
    """Bounded plain ID, not display prose: no strip/normalization or secret bypass."""
    if (type(value) is not str or not value or len(value) > 1024
            or any(unicodedata.category(c).startswith("C") or c in "\u2028\u2029" for c in value)):
        return "<REDACTED>"
    _, findings = redact_secret_text(value, 1024)
    return "<REDACTED>" if findings else value


def _xlsx_output_anchor(value: Any) -> str:
    """Only known XLSX sheet/row/cell framing can carry literal sheet spaces."""
    if type(value) is not str:
        return "<REDACTED>"
    match = re.fullmatch(r"sheet:(.+)/(row|cell):([^/]+)", value, re.DOTALL)
    if match is None:
        return "<REDACTED>"
    name, kind, coordinate = match.groups()
    try:
        if kind == "cell":
            _xlsx_coordinate(coordinate)
        elif not re.fullmatch(r"[1-9][0-9]{0,6}", coordinate, re.ASCII) or int(coordinate) > 1048576:
            return "<REDACTED>"
    except ValueError:
        return "<REDACTED>"
    return f"sheet:{_xlsx_literal_id(name)}/{kind}:{coordinate}"


@dataclass(frozen=True)
class _XlsxIdentityContext:
    sheets: Tuple[str, ...]
    positions: Dict[str, int]


def xlsx_identity_context(metadata: Any) -> Optional[_XlsxIdentityContext]:
    """Validate a bounded producer schema, not a parser label or arbitrary key.

    This is representation eligibility, NEVER owner/privacy/disclosure authority.
    Callers must retain their real read guards, including guard transformations.
    Redacted, blank or malformed identities cannot attest literal fidelity.
    """
    if type(metadata) is not dict:
        return None
    names, policy, coverage = (metadata.get(key) for key in ("sheets", "formula_policy", "coverage"))
    if (type(names) is not list or not 1 <= len(names) <= 10000
            or type(policy) is not dict or policy.get("engine") != "bounded_subset_v1"
            or type(coverage) is not dict or type(coverage.get("declared_sheets")) is not int
            or coverage["declared_sheets"] != len(names)
            or type(coverage.get("input_complete")) is not bool
            or type(coverage.get("output_truncated")) is not bool):
        return None
    for name in names:
        if (type(name) is not str or not name or name.isspace()
                or "<REDACTED" in name or name.startswith("[filtered")
                or _xlsx_literal_id(name) != name):
            return None
    if len(set(names)) != len(names):
        return None
    return _XlsxIdentityContext(tuple(names), {name: index for index, name in enumerate(names, 1)})


def xlsx_identity_fields(value: Any, *, shape: str, context: Any,
                         unit: Any = None) -> Iterable[Tuple[Tuple[Any, ...], str]]:
    """Yield ONLY validated structural leaves; all other fields stay generic.

    No text/formula/key exemption, normalization, fuzzy match or ID recovery.
    The iterator avoids accumulating a second workbook-sized identity mapping.
    The context is built once from xlsx_identity_context's validated schema.
    """
    if type(context) is not _XlsxIdentityContext:
        return

    def unit_fields(record):
        if type(record) is not dict or type(record.get("locator")) is not dict:
            return
        kind = record.get("kind", record.get("unit_type"))
        if ("kind" in record and "unit_type" in record and record["kind"] != record["unit_type"]):
            return
        loc = record["locator"]
        name = loc.get("sheet")
        if type(name) is not str or name not in context.positions:
            return
        index = context.positions[name]
        if type(record.get("ordinal")) is not int or not 1 <= record["ordinal"] <= 1000000:
            return
        if kind == "sheet":
            if (set(loc) != {"sheet", "sheet_index"} or type(loc["sheet_index"]) is not int
                    or loc["sheet_index"] != index or record.get("anchor") != f"sheet:{index}"
                    or record.get("title") != name or record.get("parent_anchor", "") != ""):
                return
            yield ("title",), name
        elif kind in {"table_row", "cell"}:
            if kind == "table_row":
                row = loc.get("row")
                if (set(loc) != {"sheet", "row"} or type(row) is not int or not 1 <= row <= 1048576
                        or record.get("anchor") != f"sheet:{name}/row:{row}"):
                    return
                cells = (record.get("metadata") or {}).get("cells") if type(record.get("metadata")) is dict else None
                if cells is not None:
                    if type(cells) is not list or len(cells) > 10000:
                        return
                    seen = set()
                    for cell in cells:
                        if type(cell) is not dict or type(cell.get("coordinate")) is not str:
                            return
                        try:
                            _, cell_row = _xlsx_coordinate(cell["coordinate"])
                        except ValueError:
                            return
                        if cell_row != row or cell["coordinate"] in seen:
                            return
                        seen.add(cell["coordinate"])
            else:
                coordinate = loc.get("cell")
                if set(loc) != {"sheet", "cell"} or type(coordinate) is not str:
                    return
                try:
                    _xlsx_coordinate(coordinate)
                except ValueError:
                    return
                if record.get("anchor") != f"sheet:{name}/cell:{coordinate}":
                    return
            if "parent_anchor" in record and record["parent_anchor"] != f"sheet:{index}":
                return
        else:
            return
        yield ("locator", "sheet"), name
        yield ("anchor",), record["anchor"]
        if record.get("parent_anchor"):
            yield ("parent_anchor",), record["parent_anchor"]

    def edge_fields(record):
        if type(record) is not dict or record.get("predicate") != "formula_ref":
            return
        anchors = []
        for key in ("source_anchor", "target_anchor"):
            anchor = record.get(key)
            if type(anchor) is not str or len(anchor) > 1100 or not anchor.startswith("sheet:"):
                return
            name, sep, coordinate = anchor[6:].rpartition("/cell:")
            if not sep or name not in context.positions:
                return
            try:
                _xlsx_coordinate(coordinate)
            except ValueError:
                return
            anchors.append((key, anchor))
        for key, anchor in anchors:
            yield (key,), anchor

    if shape == "metadata":
        if type(value) is dict and value.get("sheets") == list(context.sheets):
            for index, name in enumerate(context.sheets):
                yield ("sheets", index), name
    elif shape == "unit":
        yield from unit_fields(value)
    elif shape == "locator" and type(unit) is dict:
        for path, literal in unit_fields({**unit, "locator": value}):
            if path[0] == "locator":
                yield path[1:], literal
    elif shape == "edge":
        yield from edge_fields(value)
    elif shape == "payload":
        if (type(value) is not dict or value.get("parser") != "stdlib-xlsx-ooxml"
                or value.get("extension") not in {".xlsx", ".xlsm", ".xltx"}
                or type(value.get("units")) is not list or len(value["units"]) > 1000000
                or type(value.get("edges")) is not list or len(value["edges"]) > 2010000):
            return
        yield from ((("metadata",) + path, literal) for path, literal in
                    xlsx_identity_fields(value.get("metadata"), shape="metadata", context=context))
        for index, record in enumerate(value["units"]):
            for path, literal in unit_fields(record):
                yield ("units", index) + path, literal
        for index, record in enumerate(value["edges"]):
            for path, literal in edge_fields(record):
                yield ("edges", index) + path, literal


_XLSX_FORMULA_TOKEN_RE = re.compile(
    r'"(?:[^\"]|\"\")*"|(?<![\w.$])'
    r"(?:(?P<sheet>'(?:[^']|'')*'|[^\W\d][\w.$]*)\s*!\s*)?"
    r"(?P<first>\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})(?![\w.$])"
    r"(?:\s*:\s*(?:(?P<last_sheet>'(?:[^']|'')*'|[^\W\d][\w.$]*)\s*!\s*)?"
    r"(?P<last>\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})(?![\w.$]))?"
)


def _xlsx_formula_edges(sheet: str, coordinate: str, formula: str) -> List[Dict[str, Any]]:
    # Only supported evaluated expressions: lexical endpoints, NOT a full DAG.
    # Quoted text is inert; sheet whitespace/apostrophes are not normalized.
    edges = []
    for match in _XLSX_FORMULA_TOKEN_RE.finditer(formula):
        if match["first"] is None:
            continue
        target = match["sheet"]
        for token, part in ((target, match["first"]), (match["last_sheet"] or target, match["last"])):
            if part is None:
                continue
            name = sheet if token is None else (token[1:-1].replace("''", "'") if token.startswith("'") else token)
            edges.append({"source_anchor": f"sheet:{sheet}/cell:{coordinate}", "predicate": "formula_ref",
                          "target_anchor": f"sheet:{name}/cell:{part.replace('$', '')}", "evidence": formula})
    return edges


def extract_xlsx(path: Path, max_units: int, max_cells: int, zip_limits: Dict[str, int]) -> ExtractedDocument:
    """Complete admitted OOXML -> one bounded evaluation -> sanitized row units.

    Output limits never cut evaluator inputs. Incomplete input withholds ALL
    computations; an omitted dependency is not blank. Unsupported OOXML modes
    become refusal dependencies, never ordinary formulas/literal caches.
    """
    units, edges, reasons, sheets = [], [], [], []
    workbook: Dict[str, Dict[str, Any]] = {}
    cells_seen = read_sheets = 0
    with zipfile.ZipFile(path) as zf:
        _zip_guard(zf, **zip_limits)
        sheet_parts = _xlsx_sheet_parts(zf)
        try:
            shared = _xlsx_shared_strings(zf)
        except (ValueError, KeyError, OSError, ET.ParseError, zipfile.BadZipFile):
            shared = []
            reasons.append("shared_strings_unreadable")
        for sheet_name, part_name in sheet_parts:
            records: Dict[str, Any] = {}
            workbook[sheet_name] = records
            rows = []
            sheets.append((sheet_name, rows))
            if cells_seen > max_cells:
                continue
            try:
                root = _read_zip_xml(zf, part_name)
            except (ValueError, KeyError, OSError, ET.ParseError, zipfile.BadZipFile):
                reasons.append("worksheet_unreadable")
                continue
            if _xml_local(root.tag) != "worksheet":
                reasons.append("worksheet_representation_unsupported")
                continue
            sheet_data = [e for e in root if _xml_local(e.tag) == "sheetData"]
            if len(sheet_data) != 1:
                reasons.append("worksheet_structure_incomplete")
                continue
            read_sheets += 1
            row_ids = set()
            for row in (e for e in sheet_data[0] if _xml_local(e.tag) == "row"):
                rid = row.get("r", "")
                if not re.fullmatch(r"[1-9][0-9]{0,6}", rid, re.ASCII) or int(rid) > 1048576 or rid in row_ids:
                    raise ValueError("xlsx_invalid_or_duplicate_row_id")
                row_ids.add(rid)
                raw_cells = []
                for cell in (e for e in row if _xml_local(e.tag) == "c"):
                    cells_seen += 1
                    if cells_seen > max_cells:
                        reasons.append("max_cells_reached")
                        break
                    coord, ctype = cell.get("r", ""), cell.get("t", "")
                    column, cell_row = _xlsx_coordinate(coord)
                    if cell_row != int(rid) or coord in records:
                        raise ValueError("xlsx_duplicate_or_mismatched_cell_id")
                    fs = [e for e in cell if _xml_local(e.tag) == "f"]
                    vs = [e for e in cell if _xml_local(e.tag) == "v"]
                    if len(fs) > 1 or len(vs) > 1:
                        raise ValueError("xlsx_duplicate_formula_or_value")
                    formula_scalar = not fs or len(fs[0]) == 0
                    value_scalar = not vs or (len(vs[0]) == 0 and not vs[0].attrib)
                    formula, attrs = (fs[0].text or "", dict(fs[0].attrib)) if fs else ("", {})
                    # Never bless a parseable prefix or concatenate unknown XML.
                    if not formula_scalar:
                        formula = ""
                    raw_value = (vs[0].text or "") if vs and value_scalar else None
                    value, invalid_cache = raw_value, bool(vs) and not value_scalar
                    unsupported = ""
                    if ctype == "s":
                        if value is not None and re.fullmatch(r"[0-9]{1,10}", value, re.ASCII) and int(value) < len(shared):
                            value = shared[int(value)]
                        else:
                            value = None
                            invalid_cache |= bool(vs)
                            if not fs:
                                unsupported = "invalid_shared_string"
                    elif ctype == "inlineStr":
                        value = "".join(e.text or "" for e in cell.iter() if _xml_local(e.tag) == "t")
                    if not value_scalar and not fs:
                        unsupported = "ooxml_value_scalar_unsupported"
                    if fs:
                        mode = attrs.get("t", "normal")
                        if not formula_scalar:
                            unsupported = "ooxml_formula_scalar_unsupported"
                        elif mode != "normal" or set(attrs) - {"t", "ca", "bx"}:
                            unsupported = "ooxml_formula_representation_unsupported"
                        elif not formula.strip():
                            unsupported = "empty_formula_unsupported"
                    if "cm" in cell.attrib or "vm" in cell.attrib:
                        unsupported = "cell_metadata_unsupported"
                    item = {"coordinate": coord, "column": column, "type": ctype, "formula": formula,
                            "formula_present": bool(fs), "formula_attributes": attrs, "cached_present": bool(vs) if fs else False,
                            "value_present": bool(vs), "input_value": value,
                            "cache_raw": raw_value if invalid_cache else value,
                            "invalid_cache": invalid_cache, "unsupported": unsupported}
                    raw_cells.append(item)
                    records[coord] = {"value": value, "formula": "" if unsupported else formula,
                                      "type": "ooxml_unsupported" if unsupported else ctype}
                if raw_cells:
                    rows.append((int(rid), raw_cells))
                if cells_seen > max_cells:
                    break
    collected = sum(len(cells) for cells in workbook.values())
    # Refuse declared shared/array/dataTable followers, including absent cells.
    # Virtual blockers are not emitted as source cells; bounded expansion counts
    # duplicate coverage too, avoiding quadratic overlapping-region work.
    expansion = 0
    for sheet_name, rows in sheets:
        items = {item["coordinate"]: item for _, cells in rows for item in cells}
        for item in list(items.values()):
            region = item["formula_attributes"].get("ref")
            if region is None:
                continue
            try:
                endpoints = region.split(":")
                if len(endpoints) not in (1, 2):
                    raise ValueError("xlsx_invalid_formula_region")
                c1, r1 = _xlsx_coordinate(endpoints[0])
                c2, r2 = _xlsx_coordinate(endpoints[-1])
            except ValueError:
                reasons.append("formula_region_incomplete")
                continue
            size = (abs(c2 - c1) + 1) * (abs(r2 - r1) + 1)
            expansion += size
            if expansion > min(max_cells, 100000):
                reasons.append("formula_region_limit")
                continue
            for row_num in range(min(r1, r2), max(r1, r2) + 1):
                for col in range(min(c1, c2), max(c1, c2) + 1):
                    letters, number = "", col
                    while number:
                        number, remainder = divmod(number - 1, 26)
                        letters = chr(65 + remainder) + letters
                    coord = letters + str(row_num)
                    workbook[sheet_name][coord] = {"value": None, "formula": "", "type": "ooxml_unsupported"}
                    if coord in items:
                        items[coord]["unsupported"] = "ooxml_formula_region_unsupported"
    input_cells = sum(len(cells) for cells in workbook.values())
    if input_cells > min(max_cells, 100000) or len(workbook) > 10000:
        reasons.append("evaluator_workbook_limit")
    reasons = list(dict.fromkeys(reasons))
    complete = not reasons
    evaluated = evaluate_cells(workbook) if complete else None  # exactly one shared budget
    masks, prepared, statuses = set(), [], {}
    has_context = False
    for sheet_name, rows in sheets:
        headers = {}
        prepared_rows = []
        for row_num, cells in rows:
            row_meta, raw_values, final_values = [], [], []
            for item in cells:
                coord = item["coordinate"]
                is_formula = item["formula_present"] or item["unsupported"] in {
                    "ooxml_formula_region_unsupported", "cell_metadata_unsupported"}
                raw = _xlsx_scalar_text(item["input_value"])
                if evaluated is not None:
                    result = dict(evaluated[sheet_name][coord])
                else:
                    result = {"value": None if is_formula or item["unsupported"] else item["input_value"],
                              "value_type": "unknown", "status": "incomplete_workbook" if is_formula else "literal",
                              "value_origin": "none" if is_formula else "input_unvalidated", "reason": "incomplete_workbook",
                              "error": None, "cached_value": None, "cached_value_type": "unknown", "cache_status": "not_applicable"}
                result.update(coordinate=coord, formula=item["formula"], type=item["type"],
                              formula_present=item["formula_present"], formula_attributes=item["formula_attributes"],
                              value_present=item["value_present"], cached_present=item["value_present"] if is_formula else False)
                if item["unsupported"]:
                    result.update(value=None, value_type="unknown", status="unsupported", value_origin="none", reason=item["unsupported"])
                if is_formula:
                    result["cached_raw_value"] = _xlsx_scalar_text(item["cache_raw"]) if item["value_present"] and item["cache_raw"] is not None else None
                    if evaluated is None or item["unsupported"]:
                        result.update(cached_value=raw if item["value_present"] else None, cached_value_type="unvalidated",
                                      cache_status="unvalidated" if item["value_present"] else "absent")
                    if item["invalid_cache"]:
                        result.update(cached_value=None, cached_value_type="unknown", cache_status="invalid")
                result["value"] = _xlsx_scalar_text(result["value"]) if result["value"] is not None else None
                if result["cached_value"] is not None:
                    result["cached_value"] = _xlsx_scalar_text(result["cached_value"])
                row_meta.append(result); raw_values.append(raw)
                final_values.append(result["value"] if result["value"] is not None else "")
                statuses[result["status"]] = statuses.get(result["status"], 0) + 1
            aligned_headers = [headers.get(item["column"], "") for item in cells]
            safe_raw, raw_findings = sanitize_table_cells(raw_values, aligned_headers)
            safe_final, final_findings = sanitize_table_cells(final_values, aligned_headers)
            # Protection belongs to a document slot, not to a successful value.
            # A refused/no-cache formula still has source/attributes to protect.
            context = {idx for idx, header in enumerate(aligned_headers) if _is_secret_label(header)}
            context.update(idx + 1 for values in (raw_values, final_values)
                           for idx, value in enumerate(values)
                           if idx + 1 < len(cells) and _is_secret_label(value))
            observed_context = {f["column"] - 1 for f in raw_findings + final_findings
                                if f["category"] == "table_context"}
            context.update(observed_context)
            raw_findings.extend({"category": "table_context", "column": idx + 1}
                                for idx in sorted(context - observed_context))
            has_context |= bool(context)
            # A display-only trim/truncation is not a secret finding and must
            # not turn a matching benign sheet identity into a contextual mask.
            raw_redactions = context | {f["column"] - 1 for f in raw_findings}
            final_redactions = context | {f["column"] - 1 for f in final_findings}
            for idx, meta in enumerate(row_meta):
                for original, safe, redacted in ((raw_values[idx], safe_raw[idx], idx in raw_redactions),
                                                 (final_values[idx], safe_final[idx], idx in final_redactions)):
                    if redacted and original and original != safe:
                        masks.add(original)
                if idx in context:
                    for key in ("value", "cached_value", "cached_raw_value"):
                        value = meta.get(key)
                        if value:
                            masks.add(value)
                            meta[key] = "<REDACTED>"
                elif meta["value"] is not None:
                    meta["value"] = safe_final[idx]
            if not headers:
                headers = {item["column"]: ("Password" if _is_secret_label(raw_values[idx]) or _is_secret_label(final_values[idx])
                                            else raw_values[idx]) for idx, item in enumerate(cells)}
            prepared_rows.append((row_num, row_meta, raw_findings + final_findings))
        prepared.append((sheet_name, prepared_rows))
    # The helper intentionally has no secrecy/taint API. Do not pretend that
    # literal replacement proves secrecy of transformed numeric/string results:
    # when table context protects any value, conservatively withhold all formula
    # values/caches AND every formula representation in this workbook. Decoded
    # string masks cannot cover Excel doubled quotes or transformed results.
    if has_context:
        for _, rows in prepared:
            for _, cells, _ in rows:
                for meta in cells:
                    if "cached_raw_value" in meta:
                        meta["context_redacted"] = True
                        if meta["formula"]:
                            masks.add(meta["formula"])  # also hide literal copies of encoded source
                        for key in ("value", "cached_value", "cached_raw_value"):
                            if meta.get(key) is not None:
                                meta[key] = "<REDACTED>"
                        meta["formula"] = "<REDACTED>" if meta["formula_present"] else ""
                        meta["formula_attributes"] = {}  # document-owned keys too
    ordered_masks = sorted(masks, key=len, reverse=True)

    def data_output(value):
        # ONLY document-owned slots use contextual masks. Producer schema,
        # finite status/provenance codes and counters are not document values.
        if isinstance(value, str):
            for secret in ordered_masks:
                value = value.replace(secret, "<REDACTED>")
            return value
        if isinstance(value, dict):
            return {data_output(k): data_output(v) for k, v in value.items()}
        if isinstance(value, list):
            return [data_output(v) for v in value]
        return value

    def sheet_id(name):
        return _xlsx_literal_id(data_output(name))

    output_cells = 0
    output_truncated = edge_truncated = False
    for s_idx, (sheet_name, rows) in enumerate(prepared, 1):
        if len(units) >= max_units:
            output_truncated = True
            break
        name = sheet_id(sheet_name)
        unit = Unit("sheet", f"sheet:{s_idx}", clean_text(name), title=name,
                    ordinal=len(units)+1, locator={"sheet": name, "sheet_index": s_idx})
        unit._xlsx_literal_output = True  # local serializer opt-in, not a dataclass/output field
        units.append(unit)
        for row_num, cells, findings in rows:
            if len(units) >= max_units:
                output_truncated = True
                break
            values = []
            for cell in cells:
                for key in ("value", "cached_value", "cached_raw_value", "formula", "type"):
                    if key in cell:
                        cell[key] = data_output(cell[key])
                cell["formula_attributes"] = data_output(cell["formula_attributes"])
                formula, value = cell["formula"], cell["value"]
                display = (f"={formula} => {value}" if value is not None else f"={formula}") if cell["formula_present"] else (value or "")
                values.append(f"{cell['coordinate']}={display}")
                if cell["formula_present"] and cell["status"] in {"computed", "error"} and cell["value_origin"] == "evaluated":
                    source_formula = workbook[sheet_name][cell["coordinate"]]["formula"]
                    refs = _xlsx_formula_edges(sheet_name, cell["coordinate"], source_formula)
                    for edge in refs:
                        for key in ("source_anchor", "target_anchor"):
                            target_name, coordinate = edge[key][6:].rsplit("/cell:", 1)
                            edge[key] = f"sheet:{sheet_id(target_name)}/cell:{coordinate}"
                        edge["evidence"] = "<REDACTED>" if has_context else clean_text(data_output(source_formula), 4000)
                    remaining = max(0, 10000 - len(edges))
                    edges.extend(refs[:remaining])
                    edge_truncated |= len(refs) > remaining or bool(refs and not has_context and len(data_output(source_formula)) > 4000)
            row_text = " | ".join(values)
            row_limited = len(cells) > 10000 or len(row_text) > 200000
            for cell in cells:
                cell_limited = any(len(v) > 20000 for v in cell.values() if isinstance(v, str))
                cell_limited |= any(len(k) > 500 or len(v) > 20000
                                    for k, v in cell["formula_attributes"].items())
                cell["output_truncated"] = cell_limited
                row_limited |= cell_limited
            output_truncated |= row_limited
            unit = Unit("table_row", f"sheet:{name}/row:{row_num}",
                clean_text(row_text), parent_anchor=f"sheet:{s_idx}", ordinal=len(units)+1,
                locator={"sheet": name, "row": row_num},
                metadata=sanitize_json({"cells": cells, "secret_findings": findings}))
            unit._xlsx_literal_output = True
            units.append(unit)
            output_cells += min(len(cells), 10000)
    partial = not complete or output_truncated or edge_truncated or any(k not in {"literal", "computed"} for k in statuses)
    warnings = list(reasons)
    if output_truncated:
        warnings.append("output units/text/metadata bounded; evaluator input was not truncated")
    if edge_truncated:
        warnings.append("formula_ref edge output truncated")
    if partial and not warnings:
        warnings.append("bounded formula or literal refusals; inspect cell status")
    metadata = {"sheets": [sheet_id(name) for name, _ in sheet_parts], "cells": cells_seen,
        "formula_policy": {"engine": "bounded_subset_v1", "max_cells": 100000, "max_range_cells": 100000,
                           "max_operations": 250000, "max_depth": 64, "cache_fallback": False},
        "formula_context_redaction": "workbook_conservative" if has_context else "not_needed",
        "coverage": {"input_complete": complete, "evaluation_attempted": evaluated is not None,
            "declared_sheets": len(sheet_parts), "read_sheets": read_sheets, "collected_cells": collected,
            "evaluator_input_cells": input_cells, "representation_expansion_cells": expansion,
            "output_cells": output_cells, "output_truncated": output_truncated, "partial": partial,
            "truncated": not complete or output_truncated or edge_truncated, "input_refusals": reasons,
            "cell_statuses": statuses, "formula_ref_coverage": "evaluated_lexical_endpoints_not_dependency_DAG",
            "formula_ref_truncated": edge_truncated}}
    safe_metadata = sanitize_json(metadata)
    safe_metadata["sheets"] = metadata["sheets"][:10000]
    return ExtractedDocument("stdlib-xlsx-ooxml", _mime_for(path), clean_text(data_output(path.stem)), units,
        metadata=safe_metadata, warnings=sanitize_json(warnings),
        edges=edges, status=("partial" if partial else "ok") if output_cells else "empty")

def extract_pptx(path: Path, max_units: int, zip_limits: Dict[str, int]) -> ExtractedDocument:
    units: List[Unit] = []; warnings: List[str] = []
    with zipfile.ZipFile(path) as zf:
        _zip_guard(zf, **zip_limits)
        slide_files = sorted((n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                             key=lambda n: int(re.search(r"(\d+)", n).group(1)))
        for s_idx, name in enumerate(slide_files, 1):
            if len(units) >= max_units:
                warnings.append("max_units reached")
                break
            root = _read_zip_xml(zf, name)
            shape_no = 0
            slide_texts = []
            shape_units: List[Unit] = []
            # Reserve one unit for the slide-level structural summary.
            shape_budget = max(0, max_units - len(units) - 1)
            for shape in (e for e in root.iter() if _xml_local(e.tag) in {"sp", "graphicFrame"}):
                if len(shape_units) >= shape_budget:
                    break
                texts = [t.text or "" for t in shape.iter() if _xml_local(t.tag) == "t" and (t.text or "").strip()]
                if not texts:
                    continue
                shape_no += 1
                text = clean_text("\n".join(texts)).strip()
                slide_texts.append(text)
                shape_units.append(_unit("slide_shape", f"slide:{s_idx}/shape:{shape_no}", text,
                                         parent=f"slide:{s_idx}", ordinal=len(units) + len(shape_units) + 2,
                                         locator={"slide": s_idx, "shape": shape_no}))
            units.append(_unit("slide", f"slide:{s_idx}", "\n".join(slide_texts),
                               title=(slide_texts[0][:160] if slide_texts else f"Slide {s_idx}"), ordinal=len(units)+1,
                               locator={"slide": s_idx}))
            units.extend(shape_units)
            notes = f"ppt/notesSlides/notesSlide{s_idx}.xml"
            if notes in zf.namelist() and len(units) < max_units:
                try:
                    nroot = _read_zip_xml(zf, notes)
                    ntext = clean_text("\n".join(t.text or "" for t in nroot.iter() if _xml_local(t.tag) == "t")).strip()
                    if ntext:
                        units.append(_unit("speaker_notes", f"slide:{s_idx}/notes", ntext,
                                           parent=f"slide:{s_idx}", ordinal=len(units)+1, locator={"slide": s_idx}))
                except Exception as exc:
                    warnings.append(f"notes slide {s_idx}: {type(exc).__name__}")
            if len(units) >= max_units:
                warnings.append("max_units reached")
                break
    return ExtractedDocument("stdlib-pptx-ooxml", _mime_for(path), path.stem, units,
                             metadata={"slides": len(slide_files)}, warnings=warnings)


def extract_odf(path: Path, max_units: int, zip_limits: Dict[str, int]) -> ExtractedDocument:
    units: List[Unit] = []; warnings: List[str] = []
    with zipfile.ZipFile(path) as zf:
        _zip_guard(zf, **zip_limits)
        root = _read_zip_xml(zf, "content.xml")
        counts: Dict[str, int] = {}
        ext = path.suffix.lower()
        if ext in {".ods", ".ots"}:
            # A table-row already contains all descendant cell text; indexing
            # both rows and cells duplicated the workbook content substantially.
            accepted = {"table-row": "table_row", "h": "heading", "p": "paragraph"}
        elif ext in {".odp", ".otp", ".odg"}:
            accepted = {"page": "slide", "h": "heading", "p": "paragraph"}
        else:
            accepted = {"h": "heading", "p": "paragraph", "table-row": "table_row"}
        for elem in root.iter():
            local = _xml_local(elem.tag)
            if local not in accepted:
                continue
            text = clean_text(" ".join(t.strip() for t in elem.itertext() if t and t.strip())).strip()
            if not text:
                continue
            counts[local] = counts.get(local, 0) + 1
            idx = counts[local]
            units.append(_unit(accepted[local], f"{accepted[local]}:{idx}", text,
                               title=text[:160] if accepted[local] in {"heading", "slide"} else "",
                               ordinal=len(units)+1))
            if len(units) >= max_units:
                warnings.append("max_units reached")
                break
    return ExtractedDocument("stdlib-odf-xml", _mime_for(path), path.stem, units, warnings=warnings)


def extract_eml(path: Path, data: bytes, max_units: int) -> ExtractedDocument:
    msg = email.message_from_bytes(data, policy=policy.default)
    title = str(msg.get("subject") or path.stem)
    units: List[Unit] = []
    headers = {k: str(msg.get(k) or "") for k in ("from", "to", "cc", "date", "message-id", "subject")}
    if max_units > 0:
        units.append(_unit("email_headers", "headers", "\n".join(f"{k}: {v}" for k, v in headers.items() if v), title=title, ordinal=1))
    part_no = 0
    for part in msg.walk():
        if len(units) >= max_units:
            break
        if part.is_multipart():
            continue
        part_no += 1
        ctype = part.get_content_type()
        filename = part.get_filename()
        if filename:
            units.append(_unit("attachment", f"attachment:{part_no}", filename, ordinal=len(units)+1,
                               metadata={"content_type": ctype, "filename": filename, "size": len(part.get_payload(decode=True) or b"")}))
            continue
        try:
            content = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True) or b""
            content, _ = decode_text(payload)
        if ctype == "text/html":
            hp = _VisibleHTML(); hp.feed(str(content)); hp.finish(); content = "\n\n".join(t for _, t in hp.blocks)
        content = clean_text(content).strip()
        if content:
            units.append(_unit("email_body", f"part:{part_no}", content, ordinal=len(units)+1,
                               metadata={"content_type": ctype}))
        if len(units) >= max_units:
            break
    return ExtractedDocument("stdlib-email", "message/rfc822", title, units, metadata=headers)


def extract_epub(path: Path, max_units: int, zip_limits: Dict[str, int]) -> ExtractedDocument:
    units: List[Unit] = []; warnings: List[str] = []
    with zipfile.ZipFile(path) as zf:
        _zip_guard(zf, **zip_limits)
        html_files = [n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
        for file_no, name in enumerate(html_files, 1):
            try:
                raw = _read_zip_member(zf, name, int(zip_limits.get("max_member") or min(16 * 1024 * 1024, zip_limits["max_uncompressed"])))
                text, _ = decode_text(raw)
                hp = _VisibleHTML(); hp.feed(text); hp.finish()
                for block_no, (kind, block) in enumerate(hp.blocks, 1):
                    units.append(_unit(kind, f"chapter:{file_no}/block:{block_no}", block,
                                       title=block[:160] if kind == "heading" else "", ordinal=len(units)+1,
                                       locator={"part": name, "block": block_no}))
                    if len(units) >= max_units:
                        break
            except Exception as exc:
                warnings.append(f"{name}: {type(exc).__name__}")
            if len(units) >= max_units:
                break
    return ExtractedDocument("stdlib-epub", "application/epub+zip", path.stem, units, warnings=warnings)


def extract_google_pointer(path: Path, data: bytes) -> ExtractedDocument:
    text, enc = decode_text(data)
    try:
        obj = json.loads(text)
    except Exception:
        obj = {"raw": text[:4000]}
    url = str(obj.get("url") or obj.get("doc_id") or "")
    name = str(obj.get("name") or path.stem)
    unit = _unit("remote_document_pointer", "pointer", f"Google document pointer: {name}\nURL: {url}", title=name,
                 locator={"url": url}, metadata={"pointer": obj})
    return ExtractedDocument("google-pointer", "application/json", name, [unit],
                             metadata={"encoding": enc, "remote_content_indexed": False},
                             warnings=["Google pointer files contain no document body; export or authenticated connector access is required."],
                             status="metadata_only")


def _text_quality(text: str) -> Dict[str, Any]:
    """Observable text health, not an OCR accuracy/confidence estimate."""
    count = alnum = replacements = controls = 0
    for char in text:
        if char.isspace():
            continue
        count += 1
        alnum += char.isalnum()
        replacements += char == "\ufffd"
        controls += ord(char) < 32 or 127 <= ord(char) < 160
    usable = bool(count and alnum and alnum / count >= 0.25
                  and replacements / count <= 0.10 and controls / count <= 0.02)
    return {"status": "usable" if usable else ("low_quality" if count else "empty"),
            "characters": len(text), "alnum_characters": alnum,
            "replacement_ratio": round(replacements / count, 4) if count else 0.0,
            "control_ratio": round(controls / count, 4) if count else 0.0,
            "method": "text_health_heuristic", "confidence": None}


def _pdf_bbox(value: Any) -> Optional[List[float]]:
    if value is None:
        return None
    try:
        values = list(value)
        if len(values) != 4 or any(isinstance(v, bool) for v in values):
            return None
        box = [float(v) for v in values]
        if not all(math.isfinite(v) and abs(v) <= 10_000_000 for v in box):
            return None
        if box[2] < box[0] or box[3] < box[1]:
            return None
        return box
    except (ValueError, TypeError, OverflowError):
        return None


def _pdf_locator(page: int, bbox=None, **fields) -> Dict[str, Any]:
    locator = {"page": page, **fields}
    box = _pdf_bbox(bbox)
    if box is not None:
        locator.update(bbox=box, coordinate_system="pymupdf_unrotated_top_left_points")
    return locator


class _PdfPrivacyVetoError(RuntimeError):
    """Terminal reader failure, not an empty document or alternate-reader grant.

    Keep original exceptions privately, never their text in the public error.
    A failed ExitStack callback does not establish closure of its native owner.
    """
    def __init__(self, primary_error, cleanup_error):
        super().__init__("pdf_privacy_veto_reader_failure")
        self.primary_error = primary_error
        self.cleanup_error = cleanup_error
        self.diagnostics = {"status": "failed", "pdf_fallback_veto": "incomplete_table_context",
                            "cleanup": "unknown" if cleanup_error is not None else "complete",
                            "ownership": "unknown" if cleanup_error is not None else "complete"}


class _PdfReaderOwner(ExitStack):
    """Retain veto and fatal identity through every actual LIFO callback."""
    def __init__(self, output):
        super().__init__()
        self.output = output
        self.cleanup_errors = []  # private objects, in actual callback order
        self._fatal_cleanup = None
        self.diagnostics = {"cleanup": "complete", "ownership": "complete"}

    def _push_exit_callback(self, callback, is_sync=True):
        # Instance-local common registration seam for callback and enter_context.
        # ExitStack still owns invocation, suppression, chaining and full drain.
        def observed(*details):
            try:
                return callback(*details)
            except BaseException as error:
                self.cleanup_errors.append(error)
                self.diagnostics.update(cleanup="unknown", ownership="unknown")
                if self._fatal_cleanup is None and not isinstance(error, Exception):
                    self._fatal_cleanup = error
                raise
        super()._push_exit_callback(observed, is_sync)

    def _raise_fatal(self, fatal, primary):
        try:
            raise fatal  # selected exact object, never an ordinary carrier
        finally:
            if self.cleanup_errors:
                try:
                    # ExitStack can leave missing links. Project only actual
                    # observed objects: head, reverse LIFO, original body last.
                    # Latest occurrence wins here; the private ledger is intact.
                    chain, seen = [fatal], {id(fatal)}
                    for error in [*reversed(self.cleanup_errors), primary]:
                        if error is not None and id(error) not in seen:
                            seen.add(id(error))
                            chain.append(error)
                    context = None
                    for error in reversed(chain):
                        # Use the native descriptor, not foreign metadata hooks.
                        # Explicit causes and unobserved graphs are not traversed.
                        BaseException.__context__.__set__(error, context)
                        context = error
                except BaseException:
                    # Secondary metadata failure must not replace the fatal.
                    # The occurrence ledger and cleanup/ownership UNKNOWN remain.
                    pass

    def __exit__(self, exc_type, primary, traceback):
        try:
            suppressed = super().__exit__(exc_type, primary, traceback)
        except BaseException as cleanup:
            fatal = primary if primary is not None and not isinstance(primary, Exception) else self._fatal_cleanup
            if fatal is not None:
                self._raise_fatal(fatal, primary)
            if not isinstance(cleanup, Exception):
                raise
            if self.output.fallback_veto == "incomplete_table_context":
                raise _PdfPrivacyVetoError(primary if primary is not None else cleanup, cleanup) from cleanup
            raise
        fatal = primary if primary is not None and not isinstance(primary, Exception) else self._fatal_cleanup
        if fatal is not None:
            self._raise_fatal(fatal, primary)
        if (primary is not None and isinstance(primary, Exception)
                and self.output.fallback_veto == "incomplete_table_context"):
            cleanup = self.cleanup_errors[-1] if self.cleanup_errors else None
            raise _PdfPrivacyVetoError(primary, cleanup) from (cleanup if cleanup is not None else primary)
        return suppressed


class _PdfOutput:
    """Bound retained units/text/cells across all selected pages."""
    def __init__(self, options):
        self.units: List[Unit] = []
        self.max_units = options["max_units"]
        self.max_chars = options["max_chars"]
        self.max_cells = options["max_cells"]
        self.characters = self.cells = self.metadata_characters = 0
        self.truncated = False
        self.fallback_veto = None  # only the actual emitter refusal sets this latch

    @property
    def context_alternates_allowed(self):
        """One owning-output admission/use invariant, independent of reader age."""
        return self.fallback_veto != "incomplete_table_context"

    @property
    def full(self):
        return len(self.units) >= self.max_units or self.characters >= self.max_chars

    def add(self, kind, anchor, text="", **kwargs):
        if self.full:
            self.truncated = True
            return False
        # _unit/to_dict have a 200k per-unit cap. Account for that cap explicitly.
        safe = clean_text(text, 500_000_000)
        limit = min(200_000, self.max_chars - self.characters)
        metadata = dict(kwargs.pop("metadata", None) or {})
        if len(safe) > limit:
            metadata["truncated"] = True
            self.truncated = True
        safe = safe[:limit]
        self.units.append(_unit(kind, anchor, safe, ordinal=len(self.units) + 1,
                                metadata=metadata, **kwargs))
        self.characters += len(safe)
        return True


def _pdf_emit_page(output: _PdfOutput, number: int, text: str, blocks: list,
                   tables: list, options: dict, *, origin="native", tables_status="available_native_only") -> Dict[str, Any]:
    """Consume primitive, source-documented PyMuPDF block/table records.

    Cell locators live in row metadata, like XLSX; no invented merged-cell spans.
    Containers have no duplicate body. pypdf/plain fallback never gets a bbox.
    """
    anchor = f"page:{number}"
    before = len(output.units)
    # A retained prefix of table records cannot protect the rest of the page:
    # a Password header and its value can live in separate raw blocks. Do not
    # inspect additional cells beyond the budget or publish unprotected fallback.
    cells_limited = sum(len(row["cells"]) for table in tables for row in table["rows"]) > output.max_cells - output.cells
    if options["pdf_mode"] == "blocks" and options["pdf_tables"] and (
            cells_limited or len(tables) > options["pdf_max_tables_per_page"]
            or tables_status == "resource_limited" or tables_status.startswith("failed_")
            or (not output.context_alternates_allowed and origin != "native")):
        output.fallback_veto = "incomplete_table_context"
        output.truncated = True
        return {"units": 0, "text_units": 0, "structure": "withheld_incomplete_table_context",
                "partial": True, "truncated": True, "table_cells_limited": cells_limited,
                "table_context": "withheld_structural_refusal"}
    quality = _text_quality(text)
    if quality["status"] != "usable":
        return {"units": 0, "text_units": 0, "structure": "no_usable_text", "truncated": False}
    if options["pdf_mode"] == "pages" or (not blocks and not tables):
        output.add("page", anchor, text, title=f"Page {number}",
                   locator={"page": number}, metadata={"origin": origin, "quality": quality,
                   "reading_order_method": "parser_text_order", "ocr": origin in {"ocr", "mixed"}})
        return {"units": len(output.units) - before,
                "text_units": sum(bool(u.text.strip()) for u in output.units[before:]), "structure": "page_text_only",
                "truncated": output.truncated}

    masks = set()
    groups = []
    contained = []
    table_cells_limited = False
    for table_no, table in enumerate(tables[:options["pdf_max_tables_per_page"]], 1):
        safe_rows = []
        header = []
        for row_no, row in enumerate(table["rows"], 1):
            raw_cells = row["cells"]
            if len(raw_cells) > output.max_cells - output.cells:
                table_cells_limited = output.truncated = True
                break
            output.cells += len(raw_cells)
            raw = [cell["text"] or "" for cell in raw_cells]
            safe, findings = sanitize_table_cells(raw, header if row_no > 1 else None)
            if row_no == 1:
                header = raw
            cells = []
            for column, (cell, value) in enumerate(zip(raw_cells, safe), 1):
                if cell["text"] and value != cell["text"]:
                    masks.add(cell["text"])
                limit = min(20_000, max(0, output.max_chars - output.metadata_characters))
                if len(value) > limit:
                    output.truncated = True
                value = value[:limit]
                safe[column - 1] = value
                output.metadata_characters += len(value)
                cells.append({"text": value,
                              "anchor": f"{anchor}/table:{table_no}/row:{row_no}/cell:{column}",
                              "locator": _pdf_locator(number, cell.get("bbox"), table=table_no,
                                                       row=row_no, column=column),
                              "missing_geometry": cell.get("bbox") is None})
            safe_rows.append((row_no, row.get("bbox"), safe, cells, findings))
        box = _pdf_bbox(table.get("bbox"))
        if safe_rows:
            if box and not table_cells_limited:
                contained.append(box)
            groups.append({"kind": "table", "number": table_no, "bbox": box, "rows": safe_rows})
    # When block extraction is absent/faulted, table success is not proof that
    # native prose was covered. Select the complete page text instead of table
    # units (not both), applying the same row-context masks before publication.
    for secret in sorted(masks, key=len, reverse=True):
        text = text.replace(secret, "<REDACTED>")
    if not blocks and tables:
        output.add("page", anchor, text, title=f"Page {number}", locator={"page": number},
                   metadata={"origin": origin, "quality": quality,
                             "reading_order_method": "parser_text_order",
                             "structure_fallback": "blocks_unavailable_table_structure_omitted",
                             "ocr": origin in {"ocr", "mixed"}})
        return {"units": len(output.units) - before,
                "text_units": sum(bool(u.text.strip()) for u in output.units[before:]),
                "structure": "page_text_only", "partial": True, "truncated": output.truncated,
                "table_structure_omitted": True}
    for block in blocks[:options["pdf_max_blocks_per_page"]]:
        # PyMuPDF: (x0,y0,x1,y1,text,block_no,block_type); type 1 is an image label.
        if len(block) < 7 or block[6] != 0 or not isinstance(block[4], str) or not block[4].strip():
            continue
        box = _pdf_bbox(block[:4])
        if box and any(b[0] <= box[0] and b[1] <= box[1] and box[2] <= b[2] and box[3] <= b[3]
                       for b in contained):
            continue
        safe = block[4]
        # Do not leak a secret through an overlapping text block after row-context redaction.
        for secret in sorted(masks, key=len, reverse=True):
            safe = safe.replace(secret, "<REDACTED>")
        groups.append({"kind": "block", "number": block[5], "bbox": box, "text": safe,
                       "origin": "ocr" if len(block) > 7 and block[7] == "ocr" else origin})
    if len(blocks) > options["pdf_max_blocks_per_page"] or len(tables) > options["pdf_max_tables_per_page"]:
        output.truncated = True
    if not groups:
        output.add("page", anchor, text, title=f"Page {number}", locator={"page": number},
                   metadata={"origin": origin, "structure_fallback": "no_usable_blocks"})
        return {"units": len(output.units) - before, "text_units": sum(bool(u.text.strip()) for u in output.units[before:]),
                "structure": "page_text_only", "truncated": output.truncated}
    method = "geometric_y1_x0" if options["pdf_reading_order"] == "layout" else "parser_source_order"
    if options["pdf_reading_order"] == "layout":
        # Matches get_text('blocks', sort=True) in the inspected PyMuPDF source.
        groups.sort(key=lambda g: (g["bbox"][3], g["bbox"][0]) if g["bbox"] else (math.inf, math.inf))
    elif tables:
        method = "parser_tables_then_blocks"  # no claim of cross-API source-order equivalence
    output.add("page", anchor, title=f"Page {number}", locator={"page": number},
               metadata={"origin": origin, "reading_order_method": method,
                         "ocr": origin in {"ocr", "mixed"}})
    for order, group in enumerate(groups, 1):
        metadata = {"origin": origin, "reading_order": order, "reading_order_method": method}
        if group["kind"] == "block":
            block_label = "ocr-block" if origin == "mixed" and group["origin"] == "ocr" else "block"
            output.add("text_block", f"{anchor}/{block_label}:{group['number']}", group["text"], parent=anchor,
                       locator=_pdf_locator(number, group["bbox"], block=group["number"], text_origin=group["origin"]),
                       metadata={**metadata, "origin": group["origin"]})
        else:
            table_no = group["number"]
            parent = f"{anchor}/table:{table_no}"
            output.add("table", parent, parent=anchor,
                       locator=_pdf_locator(number, group["bbox"], table=table_no),
                       metadata={**metadata, "detection": "native_geometry_heuristic"})
            for row_no, bbox, safe, cells, findings in group["rows"]:
                if not output.add("table_row", f"{parent}/row:{row_no}", " | ".join(safe), parent=parent,
                    locator=_pdf_locator(number, bbox, table=table_no, row=row_no),
                    metadata={**metadata, "cells": cells, "secret_findings": findings}):
                    break
        if output.full:
            output.truncated = True
            break
    return {"units": len(output.units) - before,
            "text_units": sum(bool(u.text.strip()) for u in output.units[before:]),
            "structure": "blocks_and_native_tables" if tables else "blocks",
            "reading_order_method": method, "truncated": output.truncated,
            "table_cells_limited": table_cells_limited}


def _ocr_selection(native: str, candidate: str, min_chars: int) -> Tuple[bool, str, Dict[str, Any]]:
    quality = _text_quality(candidate)
    if quality["status"] != "usable" or quality["alnum_characters"] < min_chars:
        return False, "empty_or_low_quality", quality
    if _text_quality(native)["status"] == "usable" and quality["alnum_characters"] < _text_quality(native)["alnum_characters"]:
        return False, "native_text_is_better", quality
    return True, "accepted_text_health_not_accuracy", quality


def _pdf_finish(path: Path, parser: str, output: _PdfOutput, pages: list, total: int,
                warnings: list, metadata=None) -> ExtractedDocument:
    usable = sum(p["quality"]["status"] == "usable" and p.get("text_units", 0) > 0 for p in pages)
    # Keep the emitter's privacy refusal separate from ordinary empty coverage.
    # Even with no usable pages, another raw reader cannot recover lost context.
    table_context_veto = (output.fallback_veto == "incomplete_table_context"
                          or any(p.get("table_context") == "withheld_structural_refusal" for p in pages))
    missing = len(pages) - usable
    omitted = max(0, total - len(pages))
    partial = bool(missing or omitted or output.truncated or len(pages) > 10_000 or any(p.get("partial") for p in pages))
    status = ("partial" if partial else "ok") if usable else "empty"
    if not usable and pages and all(p.get("error") for p in pages):
        status = "failed"
    if partial:
        warnings.append("PDF extraction incomplete; inspect per-page coverage and resource limits")
    return ExtractedDocument(parser, "application/pdf", str((metadata or {}).get("title") or path.stem), output.units,
        metadata={**(metadata or {}), "pages": pages, "coverage": {
            "total_pages": total, "examined_pages": len(pages), "usable_pages": usable,
            "missing_pages": missing, "omitted_pages": omitted,
            "native_pages": sum(p.get("origin") in {"native", "pypdf"} for p in pages),
            "ocr_pages": sum(p.get("origin") in {"ocr", "mixed"} for p in pages),
            "partial": partial, "truncated": output.truncated,
            "diagnostics_truncated": len(pages) > 10_000,
            "basis": "page_text_health_not_exhaustive_image_region_coverage"},
            "pdf_fallback_veto": "incomplete_table_context" if table_context_veto else None,
            "quality_basis": "text_health_heuristic_not_recognition_accuracy"}, warnings=warnings, status=status)


def _open_pypdf(path: Path, stack: ExitStack):
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None
    # Supplying an owned stream avoids a parser-internal unowned file handle.
    stream = stack.enter_context(path.open("rb"))
    reader = PdfReader(stream)
    if callable(getattr(reader, "close", None)):
        stack.callback(reader.close)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("encrypted_pdf")
    return reader


def _pymupdf_tables(page, options: dict, remaining_cells: int) -> Tuple[list, str]:
    if not options["pdf_tables"] or options["pdf_mode"] == "pages":
        return [], "disabled"
    if not callable(getattr(page, "find_tables", None)):
        return [], "unavailable_api"
    finder = page.find_tables(strategy=options["pdf_table_strategy"])
    records = []
    limited = False
    for table in finder.tables[:options["pdf_max_tables_per_page"]]:
        rows = table.rows
        count = sum(len(row.cells) for row in rows)
        if count > remaining_cells:
            limited = True
            break
        remaining_cells -= count
        values = table.extract()  # consume before another page.find_tables resets its globals
        records.append({"bbox": _pdf_bbox(table.bbox), "rows": [
            {"bbox": _pdf_bbox(row.bbox), "cells": [
                {"bbox": _pdf_bbox(box), "text": str(values[r][c] or "")}
                for c, box in enumerate(row.cells)]}
            for r, row in enumerate(rows)]})
    limited |= len(finder.tables) > options["pdf_max_tables_per_page"]
    return records, "resource_limited" if limited else "available_native_only"


def _extract_pdf_pymupdf(path: Path, max_units: int, max_pages: int, ocr: bool,
                        ocr_language: str, min_native_chars: int, *, options=None) -> Optional[ExtractedDocument]:
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        try:
            import fitz  # type: ignore
        except ImportError:
            return None
    o = effective_extraction_options({**(options or {}), "max_units": max_units, "max_pages": max_pages,
        "ocr": ocr, "ocr_language": ocr_language, "ocr_min_native_chars": min_native_chars})
    output = _PdfOutput(o)
    pages = []
    warnings = []
    fallback = None
    fallback_tried = False
    ocr_attempts = 0
    with _PdfReaderOwner(output) as stack:
        doc = fitz.open(str(path))
        stack.callback(doc.close)
        if doc.needs_pass and not doc.authenticate(""):
            return ExtractedDocument("pymupdf", "application/pdf", path.stem, [], status="encrypted",
                                     warnings=["encrypted PDF; no password supplied"])
        total = len(doc)
        metadata = dict(doc.metadata or {})
        metadata["parser_library_version"] = str(getattr(fitz, "VersionBind", "unknown"))
        for index in range(min(total, max_pages)):
            if output.full:
                output.truncated = True
                break
            number = index + 1
            page_d = {"page": number, "origin": "native", "native_characters": 0,
                      "ocr": {"requested": ocr, "attempted": False, "engine": "tesseract-via-pymupdf",
                              "language": ocr_language, "confidence": None,
                              "status": "disabled" if not ocr else "not_needed"}}
            try:
                page = doc[index]
                try:
                    text = page.get_text("text", sort=o["pdf_reading_order"] == "layout") or ""
                except Exception as exc:
                    if output.fallback_veto == "incomplete_table_context":
                        raise
                    text = ""
                    page_d["native_error"] = type(exc).__name__
                page_d["native_characters"] = len(text.strip())
                blocks = []
                if o["pdf_mode"] == "blocks":
                    try:
                        blocks = page.get_text("blocks", sort=o["pdf_reading_order"] == "layout")
                    except Exception as exc:
                        if output.fallback_veto == "incomplete_table_context":
                            raise
                        page_d["blocks_status"] = "failed_" + type(exc).__name__
                        page_d["partial"] = True
                # Try the other installed native reader BEFORE considering OCR.
                needs_alternate = not text.strip() or len(text.strip()) < min_native_chars or _text_quality(text)["status"] != "usable"
                if needs_alternate and o["pdf_native_fallback"] and not output.context_alternates_allowed:
                    page_d.update(native_fallback="withheld_incomplete_table_context", partial=True)
                if needs_alternate and o["pdf_native_fallback"] and output.context_alternates_allowed:
                    if not fallback_tried:
                        fallback_tried = True
                        try:
                            fallback = _open_pypdf(path, stack)
                        except Exception as exc:
                            if output.fallback_veto == "incomplete_table_context":
                                raise
                            page_d["native_fallback"] = "failed_" + type(exc).__name__
                    if fallback is not None:
                        try:
                            alternate = fallback.pages[index].extract_text() or ""
                            if (_text_quality(alternate)["status"] == "usable" and
                                (_text_quality(text)["status"] != "usable" or
                                 (text.strip() in alternate and len(alternate.strip()) > len(text.strip())))):
                                text, blocks = alternate, []
                                page_d["origin"] = "pypdf"
                            page_d["native_fallback"] = "examined"
                        except Exception as exc:
                            if output.fallback_veto == "incomplete_table_context":
                                raise
                            page_d["native_fallback"] = "failed_" + type(exc).__name__
                    elif "native_fallback" not in page_d:
                        page_d["native_fallback"] = "unavailable"
                needs_ocr = len(text.strip()) < min_native_chars or _text_quality(text)["status"] != "usable"
                if ocr and needs_ocr:
                    diag = page_d["ocr"]
                    diag["dpi"] = o["ocr_dpi"]
                    rect = _pdf_bbox(page.rect)
                    pixels = (math.ceil((rect[2] - rect[0]) * o["ocr_dpi"] / 72) *
                              math.ceil((rect[3] - rect[1]) * o["ocr_dpi"] / 72)) if rect else None
                    diag["estimated_pixels"] = pixels
                    if not output.context_alternates_allowed:
                        diag["status"] = "withheld_incomplete_table_context"
                    elif not callable(getattr(page, "get_textpage_ocr", None)):
                        diag["status"] = "unavailable_api"
                    elif ocr_attempts >= o["ocr_max_pages"] or pixels is None or not 0 < pixels <= o["ocr_max_pixels"]:
                        diag["status"] = "resource_limited"
                    else:
                        ocr_attempts += 1
                        diag["attempted"] = True
                        try:
                            # Full-page rasterization obeys the declared DPI/pixel preflight;
                            # partial-image OCR can decode unbounded source-image dimensions.
                            # Native text was already tried and is retained if OCR loses it.
                            tp = page.get_textpage_ocr(language=ocr_language, dpi=o["ocr_dpi"], full=True)
                            try:
                                candidate = page.get_text("text", textpage=tp, sort=o["pdf_reading_order"] == "layout") or ""
                                accepted, reason, q = _ocr_selection(text, candidate, o["ocr_min_chars"])
                                diag.update(status="accepted" if accepted else "low_quality", reason=reason, quality=q)
                                if accepted:
                                    new_blocks = page.get_text("blocks", textpage=tp, sort=o["pdf_reading_order"] == "layout") if o["pdf_mode"] == "blocks" else []
                                    # Never replace usable native text with a recognition that lost it.
                                    if _text_quality(text)["status"] == "usable" and text.strip() not in candidate:
                                        seen = {b[4].strip() for b in blocks if len(b) >= 7 and b[6] == 0}
                                        extra = [b for b in new_blocks if len(b) >= 7 and b[6] == 0 and b[4].strip() not in seen]
                                        # Source block IDs remain exact; OCR anchors have a separate namespace.
                                        blocks = blocks + [(*b[:7], "ocr") for b in extra] if blocks else []
                                        text = text + "\n" + candidate
                                        page_d["origin"] = "mixed"
                                    else:
                                        text, blocks = candidate, new_blocks
                                        page_d["origin"] = "ocr"
                            finally:
                                # TextPage has no public close() in the inspected API.
                                tp = None
                        except Exception as exc:
                            if output.fallback_veto == "incomplete_table_context":
                                raise
                            diag.update(status="unavailable_or_failed", reason=type(exc).__name__)
                    if diag["status"] != "accepted":
                        page_d["partial"] = True
                tables = []
                if page_d["origin"] in {"native", "mixed"}:
                    try:
                        tables, table_status = _pymupdf_tables(page, o, output.max_cells - output.cells)
                        page_d["tables_status"] = table_status
                        if table_status == "resource_limited":
                            output.truncated = True
                    except Exception as exc:
                        if output.fallback_veto == "incomplete_table_context":
                            raise
                        page_d["tables_status"] = "failed_" + type(exc).__name__
                        page_d["partial"] = True
                else:
                    page_d["tables_status"] = "unavailable_for_selected_text"
                page_d["quality"] = _text_quality(text)
                page_d.update(_pdf_emit_page(output, number, text, blocks, tables, o, origin=page_d["origin"],
                                            tables_status=page_d["tables_status"]))
            except Exception as exc:
                if output.fallback_veto == "incomplete_table_context":
                    raise  # late read/emission failure must reach the owning exit
                page_d.update(error=type(exc).__name__, quality=_text_quality(""), units=0, partial=True)
            pages.append(page_d)
        return _pdf_finish(path, "pymupdf", output, pages, total, warnings, metadata)


def _extract_pdf_pypdf(path: Path, max_units: int, max_pages: int, *, options=None) -> Optional[ExtractedDocument]:
    o = effective_extraction_options({**(options or {}), "max_units": max_units, "max_pages": max_pages})
    output = _PdfOutput(o)
    pages = []
    with _PdfReaderOwner(output) as stack:
        try:
            reader = _open_pypdf(path, stack)
        except ValueError as exc:
            if str(exc) != "encrypted_pdf":
                raise
            return ExtractedDocument("pypdf", "application/pdf", path.stem, [], status="encrypted", warnings=["encrypted PDF"])
        if reader is None:
            return None
        total = len(reader.pages)
        for index in range(min(total, max_pages)):
            if output.full:
                output.truncated = True
                break
            diag = {"page": index + 1, "origin": "pypdf", "tables_status": "unavailable_api",
                    "ocr": {"requested": o["ocr"], "attempted": False, "engine": None,
                            "language": o["ocr_language"], "confidence": None,
                            "status": "unavailable_with_pypdf" if o["ocr"] else "disabled"}}
            try:
                text = reader.pages[index].extract_text() or ""
                diag["quality"] = _text_quality(text)
                diag.update(_pdf_emit_page(output, index + 1, text, [], [], o, origin="pypdf"))
                if o["ocr"] and len(text.strip()) < o["ocr_min_native_chars"]:
                    diag["partial"] = True
            except Exception as exc:
                if output.fallback_veto == "incomplete_table_context":
                    raise
                diag.update(error=type(exc).__name__, quality=_text_quality(""), units=0, partial=True)
            pages.append(diag)
        metadata = {str(k).lstrip("/").lower(): str(v) for k, v in (reader.metadata or {}).items()}
        return _pdf_finish(path, "pypdf", output, pages, total,
                           ["pypdf fallback: page text only; no block/cell bbox or table/semantic reading-order claims"], metadata)


def extract_pdf(path: Path, options: dict) -> ExtractedDocument:
    """Native-text-first; missing/empty/faulted readers never become empty success."""
    attempts = []
    best = None
    readers = ("pymupdf", "pypdf") if options["pdf_parser"] == "auto" else (options["pdf_parser"],)
    for name in readers:
        try:
            if name == "pymupdf":
                result = _extract_pdf_pymupdf(path, options["max_units"], options["max_pages"], options["ocr"],
                    options["ocr_language"], options["ocr_min_native_chars"], options=options)
            else:
                result = _extract_pdf_pypdf(path, options["max_units"], options["max_pages"], options=options)
            attempts.append({"parser": name, "status": result.status if result else "unavailable"})
        except _PdfPrivacyVetoError:
            # This reader already withheld unsafe context. Its exit/finish
            # failure is not permission to try another raw representation.
            raise
        except Exception as exc:
            attempts.append({"parser": name, "status": "failed", "reason": type(exc).__name__})
            continue
        if result is not None:
            best = result
            # A privacy-withheld empty result is terminal too: pypdf/Tika have
            # no access to the table context that caused this refusal. Do not
            # treat all empty/truncated results as vetoes or discard safe pages.
            if (result.metadata.get("pdf_fallback_veto") == "incomplete_table_context"
                    or result.status not in {"empty", "failed", "unsupported"}):
                result.metadata["parser_attempts"] = attempts
                return result
    if options["tika_url"]:
        # Explicit loopback opt-in only, after native readers. Tika has no page coverage API here.
        fallback = extract_tika(path, tika_url=options["tika_url"], timeout=options["external_timeout"], max_chars=options["max_chars"])
        fallback.metadata.update(parser_attempts=attempts, coverage_known=False)
        fallback.warnings.append("Tika fallback has no verified per-page/structural coverage")
        fallback.status = "partial" if any(u.text.strip() for u in fallback.units) else "empty"
        return fallback
    if best is None:
        best = ExtractedDocument("none", "application/pdf", path.stem, [], status=
            "failed" if any(a["status"] == "failed" for a in attempts) else "unsupported",
            metadata={"coverage_known": False, "ocr": {"requested": options["ocr"],
                      "language": options["ocr_language"], "engine": None, "status": "unavailable"}})
    best.metadata["parser_attempts"] = attempts
    best.warnings.append("No usable native PDF text; OCR requires an available explicitly enabled local engine")
    return best


_OCR_RETAINED = []


def _run_ocr_command(cmd: list, timeout: int, cap: int) -> Tuple[int, bytes]:
    """Bound both pipes and wall time; parent worker containment still owns descendants.

    Do not detach a timed-out reader or admit a replacement while ownership is unknown.
    This is direct-child cleanup, not a process-tree or OS sandbox guarantee.
    """
    if _OCR_RETAINED:
        raise RuntimeError("ocr_previous_ownership_unknown")
    # Prepare Python state/callbacks before acquiring a child. Every operation
    # after a returned Popen, including Thread construction/start, is owned below.
    deadline = time.monotonic() + timeout
    buffers = [bytearray(), bytearray()]
    exceeded = threading.Event()
    errors, cleanup_errors, observed = [], [], []  # private exact objects
    threads = []
    process = primary = cleanup_deadline = None
    live = False

    def cleanup_error(stage, error):
        cleanup_errors.append(error)
        observed.append((stage, error))

    def remaining(minimum=0):
        # A clock refusal must not prevent wait/join themselves or later owners.
        if cleanup_deadline is not None:
            try:
                return max(minimum, cleanup_deadline - time.monotonic())
            except BaseException as error:
                cleanup_error("cleanup_clock_unknown", error)
        return minimum

    def drain(index, stream, limit):
        try:
            while True:
                data = stream.read(8192)
                if not data:
                    break
                room = limit - len(buffers[index])
                buffers[index].extend(data[:max(0, room)])
                if len(data) > room:
                    exceeded.set()
        except BaseException as error:
            errors.append(error)
            observed.append(("pipe_read_failed", error))

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                   close_fds=True, bufsize=0)
        for index, stream, limit in ((0, process.stdout, cap), (1, process.stderr, 16_384)):
            thread = threading.Thread(target=drain, args=(index, stream, limit), daemon=True, name="document-ocr-pipe")
            threads.append(thread)
            thread.start()
        while True:
            if exceeded.is_set() or errors:
                raise RuntimeError("ocr_capture_limit_or_read_failure")
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(cmd, timeout)
            if process.poll() is not None and not any(t.is_alive() for t in threads):
                break
            time.sleep(0.01)
    except BaseException as error:
        primary = error
    finally:
        if process is not None:
            try:
                cleanup_deadline = time.monotonic() + 3
            except BaseException as error:
                cleanup_error("cleanup_clock_unknown", error)
            running = True  # an unsuccessful poll is not completion evidence
            try:
                running = process.poll() is None
            except BaseException as error:
                cleanup_error("child_poll_unknown", error)
            if running:
                try:
                    process.kill()
                except BaseException as error:
                    cleanup_error("child_kill_unknown", error)
            try:
                process.wait(timeout=remaining(0.01))
            except BaseException as error:
                cleanup_error("child_reap_unknown", error)
            for thread in threads:
                try:
                    if thread.ident is not None:
                        thread.join(timeout=remaining())
                except BaseException as error:
                    cleanup_error("reader_join_unknown", error)
                try:
                    if thread.is_alive():
                        live = True
                except BaseException as error:
                    live = True
                    cleanup_error("reader_state_unknown", error)
            # Do not close a pipe underneath a live/unknown reader. All other
            # joins/state checks still ran, and the exact owners remain retained.
            if not live:
                for name in ("stdout", "stderr"):
                    try:
                        stream = getattr(process, name)
                        if stream is not None:
                            stream.close()
                    except BaseException as error:
                        cleanup_error("pipe_close_unknown", error)
            if live or cleanup_errors:
                _OCR_RETAINED.append((process, threads))

    # Body fatal wins. Otherwise promote the first actually observed reader or
    # cleanup fatal, never a string/ordinary carrier that callers can bless.
    selected = primary if primary is not None and not isinstance(primary, Exception) else None
    if selected is None:
        selected = next((error for _, error in observed if not isinstance(error, Exception)), primary)
    if selected is None and (live or cleanup_errors):
        selected = RuntimeError("ocr_cleanup_ownership_unknown")
    # A reader can record its final chunk/failure after the loop's first check.
    if selected is None and (exceeded.is_set() or errors):
        selected = RuntimeError("ocr_capture_limit_or_read_failure")
    if selected is not None:
        try:
            raise selected
        finally:
            try:
                # Private diagnostics contain exact objects, never foreign text.
                # Bypass subclass setattr hooks; failure cannot mask selection.
                details = BaseException.__getattribute__(selected, "__dict__")
                if type(details) is dict:
                    dict.update(details, _ocr_primary_error=primary, _ocr_reader_errors=errors,
                                _ocr_cleanup_errors=cleanup_errors, _ocr_observed_errors=observed,
                                _ocr_diagnostics={"cleanup": "unknown" if live or cleanup_errors else "complete",
                                                  "ownership": "unknown" if live or cleanup_errors else "complete"})
            except BaseException:
                pass
            if observed:
                try:
                    # Project only observed objects, as for the existing PDF
                    # owner: distinct reverse occurrence order, original body last.
                    # Native context setters leave explicit causes untouched.
                    chain, seen = [selected], {id(selected)}
                    for error in [*(error for _, error in reversed(observed)), primary]:
                        if error is not None and id(error) not in seen:
                            seen.add(id(error))
                            chain.append(error)
                    context = None
                    for error in reversed(chain):
                        BaseException.__context__.__set__(error, context)
                        context = error
                except BaseException:
                    pass  # no arbitrary foreign-graph or metadata guarantee
    return process.returncode, bytes(buffers[0])


def _image_ocr_tsv(path: Path, raw: bytes, max_chars: int, language: str,
                   *, min_chars=8, max_rows=100_000, max_pages=100_000, truncated=False) -> ExtractedDocument:
    """Tesseract TSV (documented level 1 page, level 5 word)."""
    text = raw.decode("utf-8-sig", "strict")
    # TSV has no CSV quoting. Decode bounded rows directly instead of changing
    # csv.field_size_limit process-globally (the default rejects >128k words).
    lines = io.StringIO(text)
    fields = next(lines, "").rstrip("\r\n").split("\t")
    required = {"level", "page_num", "block_num", "par_num", "line_num", "word_num",
                "left", "top", "width", "height", "conf", "text"}
    if set(fields) != required or len(fields) != len(required):
        raise ValueError("invalid_tesseract_tsv_header")
    pages = {}
    chars = 0
    for index, line_text in enumerate(lines):
        if index >= max_rows:
            truncated = True
            break
        columns = line_text.rstrip("\r\n").split("\t")
        if len(columns) != len(fields):
            raise ValueError("invalid_tesseract_tsv_row")
        row = dict(zip(fields, columns))
        page_no = int(row["page_num"])
        if page_no < 1 or page_no > 100_000:
            raise ValueError("invalid_tesseract_page")
        if page_no not in pages and len(pages) >= max_pages:
            truncated = True
            break
        page = pages.setdefault(page_no, {"lines": {}, "confidence_sum": 0.0, "confidence_words": 0,
                                          "bbox": None, "truncated": False})
        level = int(row["level"])
        x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        if min(x, y, w, h) < 0:
            raise ValueError("invalid_tesseract_geometry")
        box = _pdf_bbox([x, y, x + w, y + h])
        if box is None:
            raise ValueError("invalid_tesseract_geometry")
        if level == 1:
            page["bbox"] = box
        if level != 5 or not row["text"].strip():
            continue
        word = row["text"]
        if chars + len(word) + 1 > max_chars:
            page["truncated"] = truncated = True
            break
        chars += len(word) + 1
        key = tuple(int(row[k]) for k in ("block_num", "par_num", "line_num"))
        line = page["lines"].setdefault(key, [])
        confidence = float(row["conf"])
        if not math.isfinite(confidence) or not -1 <= confidence <= 100:
            raise ValueError("invalid_tesseract_confidence")
        if confidence >= 0:
            page["confidence_sum"] += confidence
            page["confidence_words"] += 1
        line.append(word)
    units = []
    diagnostics = []
    for number, page in sorted(pages.items()):
        body = "\n".join(" ".join(words) for words in page["lines"].values())
        if len(body) > 200_000:
            body = body[:200_000]
            page["truncated"] = truncated = True
        quality = _text_quality(body)
        confidence = round(page["confidence_sum"] / page["confidence_words"], 2) if page["confidence_words"] else None
        usable = quality["status"] == "usable" and quality["alnum_characters"] >= min_chars
        # Tesseract confidences are engine scores, not calibrated correctness probabilities.
        if confidence is not None and confidence < 20:
            usable = False
        diag = {"page": number, "engine": "tesseract", "language": language, "quality": quality,
                "confidence": confidence, "confidence_basis": "mean_word_engine_score_not_accuracy",
                "status": "usable" if usable else "empty_or_low_quality", "truncated": page["truncated"]}
        if usable:
            locator = {"page": number, "image": 1}
            if page["bbox"] is not None:
                locator.update(bbox=page["bbox"], coordinate_system="image_top_left_pixels")
            units.append(_unit("image_ocr", f"image:1/page:{number}", body, title=path.stem,
                               ordinal=len(units) + 1, locator=locator, metadata=diag))
        diagnostics.append(diag)
    partial = truncated or not diagnostics or any(p["status"] != "usable" for p in diagnostics)
    status = ("partial" if partial else "ok") if units else "empty"
    return ExtractedDocument("tesseract", _mime_for(path), path.stem, units,
        metadata={"language": language, "pages": diagnostics, "coverage": {
            "examined_pages": len(diagnostics), "usable_pages": len(units), "partial": partial,
            "truncated": truncated, "total_pages_known": False}},
        warnings=["OCR partial/low quality; inspect page diagnostics"] if partial else [], status=status)


def extract_image_ocr(path: Path, max_chars: int, language: str, timeout: int,
                      *, executable: str = "tesseract", psm: str = "3", min_chars: int = 8,
                      max_rows: int = 100_000, max_pages: int = 100_000) -> ExtractedDocument:
    cmd = [executable, str(path), "stdout", "-l", language, "--psm", psm, "tsv"]
    try:
        code, raw = _run_ocr_command(cmd, timeout, min(16_000_000, max(64_000, max_chars * 8)))
        if code:
            return ExtractedDocument("tesseract", _mime_for(path), path.stem, [], status="failed",
                metadata={"engine": "tesseract", "language": language, "exit_code": code, "coverage_known": False},
                warnings=["tesseract failed; stderr intentionally not published"])
        return _image_ocr_tsv(path, raw, max_chars, language, min_chars=min_chars, max_rows=max_rows, max_pages=max_pages)
    except FileNotFoundError:
        status, reason = "unsupported", "engine_unavailable"
    except subprocess.TimeoutExpired:
        status, reason = "failed", "timeout"
    except (RuntimeError, OSError, ValueError, UnicodeError) as exc:
        status, reason = "failed", type(exc).__name__
    return ExtractedDocument("tesseract", _mime_for(path), path.stem, [], status=status,
        metadata={"engine": "tesseract", "language": language, "ocr_status": reason, "coverage_known": False},
        warnings=["OCR unavailable/failed; no recognized text was accepted"])


def _is_loopback_http_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(str(value or ""))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost":
            return True
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def _tika_request_identity(value: str) -> str:
    """Opaque identity for the complete URL used by the loopback PUT.

    Preserve query order, repeated keys, escapes and userinfo as sent, not a
    lossy semantic projection. Existing loopback admission uses hostname even
    with userinfo; this does not create an auth route. Never persist the URL,
    query, credentials or the effective options dict; only this digest escapes.
    """
    if not value:
        return ""
    try:
        if not isinstance(value, str) or len(value) > 8192:
            raise ValueError
        if any(ord(char) <= 32 or ord(char) == 127 for char in value):
            raise ValueError
        raw = value.encode("utf-8")
        if len(raw) > 8192 or not _is_loopback_http_url(value):
            raise ValueError
        urllib.parse.urlsplit(value).port  # Validate the same endpoint before cache/dispatch.
    except (TypeError, ValueError, UnicodeError):
        raise ValueError("invalid loopback Tika request URL") from None
    return sha256_bytes(raw)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects before urllib can resend untrusted document bytes."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(
            req.full_url, code, f"Tika redirect refused: {newurl}", headers, fp
        )


def extract_tika(path: Path, *, tika_url: str, timeout: int, max_chars: int) -> ExtractedDocument:
    if not tika_url:
        return ExtractedDocument("none", _mime_for(path), path.stem, [], warnings=["no parser available and Tika disabled"], status="unsupported")
    _tika_request_identity(tika_url)
    data = path.read_bytes()
    req = urllib.request.Request(tika_url, data=data, method="PUT", headers={"Accept": "text/plain", "Content-Type": _mime_for(path)})
    try:
        # The parser is deliberately loopback-only.  urllib otherwise honors
        # HTTP_PROXY and could send the complete document to a remote proxy.
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirectHandler(),
        )
        with opener.open(req, timeout=timeout) as response:
            if not _is_loopback_http_url(response.geturl()):
                raise ValueError("Tika response came from a non-loopback URL")
            raw = response.read(max_chars + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Tika HTTP {exc.code}") from None
    truncated = len(raw) > max_chars
    text, encoding = decode_text(raw[:max_chars])
    text = clean_text(text, max_chars).strip()
    units = [_unit("document_text", "document:1", text, title=path.stem, ordinal=1)] if text else []
    warnings = ["Tika response truncated at configured max_chars"] if truncated else []
    return ExtractedDocument("apache-tika", _mime_for(path), path.stem, units,
                             metadata={"encoding": encoding, "truncated": truncated}, warnings=warnings)


def effective_extraction_options(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalize the values the parser actually consumes, not caller aliases."""
    o = dict(options or {})
    bounded = lambda key, default, lo, hi: max(lo, min(int(o.get(key, default)), hi))
    max_bytes = int(o.get("max_bytes", 128 * 1024 * 1024))
    enums = {"pdf_parser": ("auto", "pymupdf", "pypdf"), "pdf_mode": ("blocks", "pages"),
             "pdf_reading_order": ("layout", "source"), "pdf_table_strategy": ("lines", "lines_strict", "text")}
    selected = {}
    for key, values in enums.items():
        selected[key] = o.get(key, values[0])
        if selected[key] not in values:
            raise ValueError("invalid " + key)
    language = str(o.get("ocr_language", "eng+rus"))
    if len(language) > 256 or not re.fullmatch(r"(?:[A-Za-z0-9_]+/)?[A-Za-z0-9_]+(?:\+(?:[A-Za-z0-9_]+/)?[A-Za-z0-9_]+)*", language):
        raise ValueError("invalid ocr_language")
    psm = str(o.get("ocr_psm", os.environ.get("MEMORY_WIKI_OCR_PSM", "3")))
    if psm not in {str(n) for n in range(14)}:
        raise ValueError("invalid ocr_psm")
    return {
        **selected,
        "pdf_tables": bool(o.get("pdf_tables", True)),
        "pdf_native_fallback": bool(o.get("pdf_native_fallback", True)),
        "pdf_max_blocks_per_page": bounded("pdf_max_blocks_per_page", 2000, 1, 20_000),
        "pdf_max_tables_per_page": bounded("pdf_max_tables_per_page", 32, 1, 1000),
        "max_bytes": max_bytes,
        "max_units": bounded("max_units", 100_000, 1, 1_000_000),
        "max_cells": bounded("max_cells", 500_000, 1, 5_000_000),
        "max_pages": bounded("max_pages", 10_000, 1, 100_000),
        "max_chars": bounded("max_chars", 100_000_000, 1000, 500_000_000),
        "zip_max_entries": bounded("zip_max_entries", 50_000, 10, 1_000_000),
        "zip_expansion_factor": bounded("zip_expansion_factor", 8, 1, 100),
        "zip_max_ratio": bounded("zip_max_ratio", 200, 5, 10_000),
        "zip_max_member": bounded("zip_max_member", 16 * 1024 * 1024, 1024 * 1024, max_bytes),
        "ocr": bool(o.get("ocr", False)),
        "ocr_language": language,
        "ocr_min_native_chars": bounded("ocr_min_native_chars", 40, 0, 10_000),
        "ocr_min_chars": bounded("ocr_min_chars", 8, 1, 10_000),
        "ocr_dpi": bounded("ocr_dpi", 200, 72, 400),
        "ocr_max_pixels": bounded("ocr_max_pixels", 20_000_000, 1_000_000, 100_000_000),
        "ocr_max_pages": bounded("ocr_max_pages", 100, 1, 10_000),
        "ocr_max_tsv_rows": bounded("ocr_max_tsv_rows", 100_000, 1, 1_000_000),
        "tesseract_bin": str(o.get("tesseract_bin", os.environ.get("MEMORY_WIKI_TESSERACT_BIN", "tesseract"))),
        "ocr_psm": psm,
        "external_timeout": bounded("external_timeout", 90, 1, 900),
        "tika_url": str(o.get("tika_url") or ""),
    }


def extraction_options_fingerprint(path: Path, options: Dict[str, Any]) -> str:
    """Content-affecting parser axes; deadlines and embedding routes are absent."""
    o = effective_extraction_options(options)
    ext = path.suffix.lower()
    keys = {"max_bytes", "max_units"}
    if ext in OOXML_EXTENSIONS | ODF_EXTENSIONS | EBOOK_EXTENSIONS:
        keys.update({"zip_max_entries", "zip_expansion_factor", "zip_max_ratio", "zip_max_member"})
    if ext in {".xlsx", ".xlsm", ".xltx"}: keys.add("max_cells")
    if ext in PDF_EXTENSIONS:
        keys.update({"max_pages", "max_chars", "max_cells", "ocr", "pdf_parser", "pdf_mode",
                     "pdf_reading_order", "pdf_tables", "pdf_table_strategy", "pdf_native_fallback",
                     "pdf_max_blocks_per_page", "pdf_max_tables_per_page", "ocr_min_native_chars"})
    if ext in IMAGE_EXTENSIONS: keys.update({"max_chars", "max_pages", "ocr"})
    if ext in PDF_EXTENSIONS | IMAGE_EXTENSIONS and o["ocr"]:
        keys.update({"ocr_language", "ocr_min_chars"})
        if ext in PDF_EXTENSIONS:
            keys.update({"ocr_min_native_chars", "ocr_dpi", "ocr_max_pixels", "ocr_max_pages"})
        else:
            keys.update({"tesseract_bin", "ocr_psm", "ocr_max_tsv_rows"})
    material = {k: o[k] for k in sorted(keys)}
    if ext in PDF_EXTENSIONS or ext not in SUPPORTED_EXTENSIONS - LEGACY_OFFICE_EXTENSIONS:
        # Hash the whole bounded request URL, including query, only in memory.
        # URI/query credentials must never be persisted as plaintext material.
        material["tika_parser"] = _tika_request_identity(o["tika_url"])
        material["max_chars"] = o["max_chars"]
    material["extractor_version"] = EXTRACTOR_VERSION
    material["secret_policy_version"] = SECRET_POLICY_VERSION
    return sha256_bytes(json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())


def extract_document(path: Path, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    options = effective_extraction_options(options)
    path = path.expanduser().resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise ValueError("document path must be a regular non-symlink file")
    max_bytes = int(options.get("max_bytes", 128 * 1024 * 1024))
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"file size {size} exceeds limit {max_bytes}")
    max_units = max(1, min(int(options.get("max_units", 100_000)), 1_000_000))
    max_cells = max(1, min(int(options.get("max_cells", 500_000)), 5_000_000))
    max_pages = max(1, min(int(options.get("max_pages", 10_000)), 100_000))
    max_chars = max(1000, min(int(options.get("max_chars", 100_000_000)), 500_000_000))
    zip_limits = {
        "max_entries": max(10, min(int(options.get("zip_max_entries", 50_000)), 1_000_000)),
        "max_uncompressed": max_bytes * max(1, min(int(options.get("zip_expansion_factor", 8)), 100)),
        "max_ratio": max(5, min(int(options.get("zip_max_ratio", 200)), 10_000)),
        "max_member": max(1_024 * 1_024, min(int(options.get("zip_max_member", 16 * 1024 * 1024)), max_bytes)),
    }
    ext = path.suffix.lower()
    data = path.read_bytes() if ext in TEXT_EXTENSIONS | EMAIL_EXTENSIONS | GOOGLE_POINTER_EXTENSIONS else b""
    if ext in TEXT_EXTENSIONS:
        result = extract_plain(path, data, max_units)
    elif ext in {".docx", ".docm", ".dotx"}:
        result = extract_docx(path, max_units, zip_limits)
    elif ext in {".xlsx", ".xlsm", ".xltx"}:
        result = extract_xlsx(path, max_units, max_cells, zip_limits)
    elif ext in {".pptx", ".pptm", ".potx"}:
        result = extract_pptx(path, max_units, zip_limits)
    elif ext in ODF_EXTENSIONS:
        result = extract_odf(path, max_units, zip_limits)
    elif ext in EMAIL_EXTENSIONS:
        result = extract_eml(path, data, max_units)
    elif ext in EBOOK_EXTENSIONS:
        result = extract_epub(path, max_units, zip_limits)
    elif ext in GOOGLE_POINTER_EXTENSIONS:
        result = extract_google_pointer(path, data)
    elif ext in PDF_EXTENSIONS:
        result = extract_pdf(path, options)
    elif ext in IMAGE_EXTENSIONS:
        if bool(options.get("ocr", False)):
            result = extract_image_ocr(path, max_chars, options["ocr_language"],
                                       options["external_timeout"], executable=options["tesseract_bin"],
                                       psm=options["ocr_psm"], min_chars=options["ocr_min_chars"],
                                       max_rows=options["ocr_max_tsv_rows"],
                                       max_pages=min(max_units, max_pages))
        else:
            result = ExtractedDocument("none", _mime_for(path), path.stem, [],
                                       warnings=["image OCR disabled"], status="metadata_only")
    else:
        result = extract_tika(path, tika_url=str(options.get("tika_url") or ""),
                              timeout=int(options.get("external_timeout", 90)), max_chars=max_chars)
    payload = result.to_dict()
    finding_categories: Dict[str, int] = {}
    finding_count = 0
    for unit in payload.get("units") or []:
        for finding in (unit.get("metadata") or {}).get("secret_findings") or []:
            category = str(finding.get("category") or "secret")
            finding_categories[category] = finding_categories.get(category, 0) + 1
            finding_count += 1
    payload.update({
        "path": str(path), "file_name": path.name, "extension": ext,
        "file_size": size, "file_hash": sha256_file(path), "mtime_ns": path.stat().st_mtime_ns,
        "parser_version": f"{EXTRACTOR_VERSION}:secret-policy-{SECRET_POLICY_VERSION}",
        "secret_redactions": finding_count, "secret_categories": finding_categories,
        "security_status": "redacted_before_index" if finding_count else "no_detected_secret",
    })
    # Stable contains/next edges are generated after parser-specific edges.
    prev = ""
    for unit in payload["units"]:
        if unit.get("parent_anchor"):
            payload["edges"].append({"source_anchor": unit["parent_anchor"], "predicate": "contains", "target_anchor": unit["anchor"]})
        if prev:
            payload["edges"].append({"source_anchor": prev, "predicate": "next", "target_anchor": unit["anchor"]})
        prev = unit["anchor"]
    return payload
