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
import os
import re
import subprocess
import tempfile
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

EXTRACTOR_VERSION = "3.0.0"
SECRET_POLICY_VERSION = "3.0.0"

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
    r"(?P<quote>[\"']?)(?P<value>[^\s|,;\"']{4,})(?P=quote)"
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
        return {
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


def _zip_guard(zf: zipfile.ZipFile, *, max_entries: int, max_uncompressed: int, max_ratio: int) -> None:
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
        compressed = max(1, int(info.compress_size))
        if int(info.file_size) > 1024 * 1024 and int(info.file_size) / compressed > max_ratio:
            raise ValueError(f"suspicious compression ratio for {info.filename}")
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or "../" in f"/{name}":
            raise ValueError(f"unsafe archive path: {name}")


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
    """Resolve workbook sheet names through relationship IDs.

    OOXML does not guarantee that workbook order/names match sorted
    ``sheet1.xml``, ``sheet2.xml`` filenames.  The old positional mapping could
    silently assign a sheet's data to the wrong name after sheets were reordered.
    """
    fallback = sorted(
        (name for name in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", name)),
        key=lambda name: int(re.search(r"(\d+)", name).group(1)),
    )
    try:
        workbook = _read_zip_xml(zf, "xl/workbook.xml")
        rels = _read_zip_xml(zf, "xl/_rels/workbook.xml.rels")
        rel_targets: Dict[str, str] = {}
        for rel in rels.iter():
            if _xml_local(rel.tag) != "Relationship":
                continue
            rel_id = str(rel.attrib.get("Id") or "")
            target = str(rel.attrib.get("Target") or "").replace("\\", "/")
            if not rel_id or not target:
                continue
            if target.startswith("/"):
                normalized = target.lstrip("/")
            elif target.startswith("xl/"):
                normalized = target
            else:
                normalized = "xl/" + target.lstrip("./")
            rel_targets[rel_id] = normalized
        parts: List[Tuple[str, str]] = []
        for sheet in (elem for elem in workbook.iter() if _xml_local(elem.tag) == "sheet"):
            name = next((str(value) for key, value in sheet.attrib.items() if key.endswith("name")), "")
            rel_id = next((str(value) for key, value in sheet.attrib.items() if key.endswith("}id") or key == "r:id"), "")
            target = rel_targets.get(rel_id, "")
            if target in zf.namelist():
                parts.append((name or Path(target).stem, target))
        if parts:
            return parts
    except Exception:
        pass
    return [(f"Sheet{index}", name) for index, name in enumerate(fallback, 1)]


def extract_xlsx(path: Path, max_units: int, max_cells: int, zip_limits: Dict[str, int]) -> ExtractedDocument:
    units: List[Unit] = []; edges: List[Dict[str, Any]] = []; warnings: List[str] = []
    with zipfile.ZipFile(path) as zf:
        _zip_guard(zf, **zip_limits)
        shared = _xlsx_shared_strings(zf)
        sheet_parts = _xlsx_sheet_parts(zf)
        sheet_names = [name for name, _ in sheet_parts]
        cells_seen = 0
        for s_idx, (sheet_name, part_name) in enumerate(sheet_parts, 1):
            root = _read_zip_xml(zf, part_name)
            units.append(_unit("sheet", f"sheet:{s_idx}", sheet_name, title=sheet_name, ordinal=len(units)+1,
                               locator={"sheet": sheet_name, "sheet_index": s_idx}))
            sheet_header: List[str] = []
            for row in (e for e in root.iter() if _xml_local(e.tag) == "row"):
                row_num = int(row.attrib.get("r") or 0)
                raw_cells: List[Dict[str, Any]] = []
                for cell in (e for e in list(row) if _xml_local(e.tag) == "c"):
                    cells_seen += 1
                    if cells_seen > max_cells:
                        warnings.append("max_cells reached")
                        break
                    coord = cell.attrib.get("r", "")
                    ctype = cell.attrib.get("t", "")
                    formula = next((e.text or "" for e in cell if _xml_local(e.tag) == "f"), "")
                    value = next((e.text or "" for e in cell if _xml_local(e.tag) == "v"), "")
                    inline = "".join(e.text or "" for e in cell.iter() if _xml_local(e.tag) == "t")
                    if ctype == "s" and value.isdigit() and int(value) < len(shared):
                        rendered = shared[int(value)]
                    elif ctype == "inlineStr":
                        rendered = inline
                    elif ctype == "b":
                        rendered = "TRUE" if value == "1" else "FALSE"
                    else:
                        rendered = value or inline
                    raw_cells.append({"coordinate": coord, "value": rendered, "formula": formula, "type": ctype})
                    if formula:
                        for match in _FORMULA_REF_RE.finditer(formula):
                            ref_sheet = (match.group(1) or match.group(2) or sheet_name).strip()
                            ref_coord = f"{match.group(3)}{match.group(4)}"
                            edges.append({"source_anchor": f"sheet:{sheet_name}/cell:{coord}", "predicate": "formula_ref",
                                          "target_anchor": f"sheet:{ref_sheet}/cell:{ref_coord}", "evidence": formula})
                raw_values = [item["value"] for item in raw_cells]
                safe_values, findings = sanitize_table_cells(raw_values, sheet_header if sheet_header else None)
                if not sheet_header and raw_values:
                    sheet_header = [clean_text(value, 500) for value in raw_values]
                row_values: List[str] = []
                cell_meta: List[Dict[str, Any]] = []
                for index, item in enumerate(raw_cells):
                    safe_value = safe_values[index]
                    formula = clean_text(item["formula"], 4000)
                    display = (f"={formula} => {safe_value}" if safe_value else f"={formula}") if formula else safe_value
                    row_values.append(f"{item['coordinate']}={display}")
                    cell_meta.append({"coordinate": item["coordinate"], "value": safe_value,
                                      "formula": formula, "type": item["type"]})
                if row_values:
                    anchor = f"sheet:{sheet_name}/row:{row_num}"
                    units.append(_unit("table_row", anchor, " | ".join(row_values), parent=f"sheet:{s_idx}",
                                       ordinal=len(units)+1, locator={"sheet": sheet_name, "row": row_num},
                                       metadata={"cells": cell_meta, "secret_findings": findings}))
                if len(units) >= max_units or cells_seen > max_cells:
                    break
            if len(units) >= max_units or cells_seen > max_cells:
                break
    return ExtractedDocument("stdlib-xlsx-ooxml", _mime_for(path), path.stem, units,
                             metadata={"sheets": sheet_names, "cells": cells_seen}, warnings=warnings, edges=edges)


def extract_pptx(path: Path, max_units: int, zip_limits: Dict[str, int]) -> ExtractedDocument:
    units: List[Unit] = []; warnings: List[str] = []
    with zipfile.ZipFile(path) as zf:
        _zip_guard(zf, **zip_limits)
        slide_files = sorted((n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                             key=lambda n: int(re.search(r"(\d+)", n).group(1)))
        for s_idx, name in enumerate(slide_files, 1):
            root = _read_zip_xml(zf, name)
            shape_no = 0
            slide_texts = []
            for shape in (e for e in root.iter() if _xml_local(e.tag) in {"sp", "graphicFrame"}):
                texts = [t.text or "" for t in shape.iter() if _xml_local(t.tag) == "t" and (t.text or "").strip()]
                if not texts:
                    continue
                shape_no += 1
                text = clean_text("\n".join(texts)).strip()
                slide_texts.append(text)
                units.append(_unit("slide_shape", f"slide:{s_idx}/shape:{shape_no}", text,
                                   parent=f"slide:{s_idx}", ordinal=len(units)+1,
                                   locator={"slide": s_idx, "shape": shape_no}))
            units.insert(max(0, len(units)-shape_no), _unit("slide", f"slide:{s_idx}", "\n".join(slide_texts),
                         title=(slide_texts[0][:160] if slide_texts else f"Slide {s_idx}"), ordinal=s_idx,
                         locator={"slide": s_idx}))
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
    units.append(_unit("email_headers", "headers", "\n".join(f"{k}: {v}" for k, v in headers.items() if v), title=title, ordinal=1))
    part_no = 0
    for part in msg.walk():
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
                raw = zf.read(name)
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


def _extract_pdf_pymupdf(path: Path, max_units: int, max_pages: int, ocr: bool, ocr_language: str, min_native_chars: int) -> Optional[ExtractedDocument]:
    try:
        import fitz  # type: ignore
    except Exception:
        return None
    doc = fitz.open(str(path))
    units: List[Unit] = []; warnings: List[str] = []
    for page_idx in range(min(len(doc), max_pages)):
        page = doc[page_idx]
        text = page.get_text("text", sort=True) or ""
        used_ocr = False
        if ocr and len(text.strip()) < min_native_chars:
            try:
                tp = page.get_textpage_ocr(language=ocr_language, dpi=300, full=True)
                text = page.get_text("text", textpage=tp, sort=True) or text
                used_ocr = True
            except Exception as exc:
                warnings.append(f"page {page_idx+1} OCR failed: {type(exc).__name__}: {exc}")
        text = clean_text(text).strip()
        if text:
            units.append(_unit("page", f"page:{page_idx+1}", text, ordinal=page_idx+1,
                               locator={"page": page_idx+1}, metadata={"ocr": used_ocr}))
        if len(units) >= max_units:
            break
    metadata = dict(doc.metadata or {})
    title = str(metadata.get("title") or path.stem)
    doc.close()
    return ExtractedDocument("pymupdf", "application/pdf", title, units, metadata=metadata, warnings=warnings)


def _extract_pdf_pypdf(path: Path, max_units: int, max_pages: int) -> Optional[ExtractedDocument]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return None
    reader = PdfReader(str(path))
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            return ExtractedDocument("pypdf", "application/pdf", path.stem, [], warnings=["encrypted PDF"], status="encrypted")
    units = []
    for idx, page in enumerate(reader.pages[:max_pages], 1):
        text = clean_text(page.extract_text() or "").strip()
        if text:
            units.append(_unit("page", f"page:{idx}", text, ordinal=idx, locator={"page": idx}))
        if len(units) >= max_units:
            break
    meta = {str(k).lstrip("/"): str(v) for k, v in (reader.metadata or {}).items()}
    return ExtractedDocument("pypdf", "application/pdf", meta.get("Title") or path.stem, units, metadata=meta)


def extract_image_ocr(path: Path, max_chars: int, language: str, timeout: int) -> ExtractedDocument:
    exe = os.environ.get("MEMORY_WIKI_TESSERACT_BIN", "tesseract")
    cmd = [exe, str(path), "stdout", "-l", language, "--psm", os.environ.get("MEMORY_WIKI_OCR_PSM", "3")]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return ExtractedDocument("none", _mime_for(path), path.stem, [], warnings=["tesseract executable not found"], status="unsupported")
    if proc.returncode != 0:
        return ExtractedDocument("tesseract", _mime_for(path), path.stem, [], warnings=[proc.stderr[-1000:]], status="failed")
    text = clean_text(proc.stdout, max_chars).strip()
    units = [_unit("image_ocr", "image:1", text, title=path.stem, ordinal=1)] if text else []
    return ExtractedDocument("tesseract", _mime_for(path), path.stem, units, metadata={"language": language})


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


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects before urllib can resend untrusted document bytes."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(
            req.full_url, code, f"Tika redirect refused: {newurl}", headers, fp
        )


def extract_tika(path: Path, *, tika_url: str, timeout: int, max_chars: int) -> ExtractedDocument:
    if not tika_url:
        return ExtractedDocument("none", _mime_for(path), path.stem, [], warnings=["no parser available and Tika disabled"], status="unsupported")
    if not _is_loopback_http_url(tika_url):
        raise ValueError("Tika URL must be loopback-only")
    data = path.read_bytes()
    req = urllib.request.Request(tika_url, data=data, method="PUT", headers={"Accept": "text/plain", "Content-Type": _mime_for(path)})
    try:
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(req, timeout=timeout) as response:
            if not _is_loopback_http_url(response.geturl()):
                raise ValueError("Tika response came from a non-loopback URL")
            raw = response.read(max_chars + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Tika HTTP {exc.code}: {exc.reason}") from exc
    truncated = len(raw) > max_chars
    text, encoding = decode_text(raw[:max_chars])
    text = clean_text(text, max_chars).strip()
    units = [_unit("document_text", "document:1", text, title=path.stem, ordinal=1)] if text else []
    warnings = ["Tika response truncated at configured max_chars"] if truncated else []
    return ExtractedDocument("apache-tika", _mime_for(path), path.stem, units,
                             metadata={"encoding": encoding, "truncated": truncated}, warnings=warnings)


def extract_document(path: Path, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    options = dict(options or {})
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
        result = _extract_pdf_pymupdf(path, max_units, max_pages, bool(options.get("ocr", False)),
                                      str(options.get("ocr_language", "eng+rus")), int(options.get("ocr_min_native_chars", 40)))
        if result is None:
            result = _extract_pdf_pypdf(path, max_units, max_pages)
        if result is None:
            result = extract_tika(path, tika_url=str(options.get("tika_url") or ""),
                                  timeout=int(options.get("external_timeout", 90)), max_chars=max_chars)
    elif ext in IMAGE_EXTENSIONS:
        if bool(options.get("ocr", False)):
            result = extract_image_ocr(path, max_chars, str(options.get("ocr_language", "eng+rus")),
                                       int(options.get("external_timeout", 90)))
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
