#!/usr/bin/env python3
"""Cross-source context collapse for Hermes Memory Wiki.

The public API intentionally returns the original item dictionaries so callers
can consume the result without understanding this module's internal wrappers.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Set, Tuple

_WORD_RE = re.compile(r"[\w-]+", re.UNICODE)


def collapse_tokenize(text: str) -> Set[str]:
    """Return normalized content tokens suitable for overlap scoring."""
    return {
        match.group(0).casefold()
        for match in _WORD_RE.finditer(str(text or ""))
        if len(match.group(0)) >= 4
    }


def _item_text(item: Any) -> str:
    if isinstance(item, dict):
        return " ".join(
            str(item.get(key) or "")
            for key in ("claim", "content", "text", "summary", "topic")
        ).strip()
    return str(item or "").strip()


def _identifier_digest(value: Any) -> str:
    """Bound serialization, never stringify mappings or expose an identifier."""
    if type(value) not in (str, int):
        return ""
    try:
        text = str(value)
    except ValueError:
        return ""
    if not text:
        return ""
    digest = hashlib.sha256()
    for start in range(0, len(text), 4096):
        digest.update(text[start:start + 4096].encode("utf-8", "surrogatepass"))
    return digest.hexdigest()


def _identity_maps(item: Any) -> List[Dict[str, Any]]:
    if not isinstance(item, dict):
        return []
    maps = [item]
    payload = item.get("payload")
    if isinstance(payload, dict):
        maps.append(payload)
    for mapping in tuple(maps):
        if isinstance(mapping.get("source"), dict):
            maps.append(mapping["source"])
    return maps


def _first_identifier(maps: List[Dict[str, Any]], names: Tuple[str, ...]) -> str:
    for mapping in maps:
        for name in names:
            value = _identifier_digest(mapping.get(name))
            if value:
                return value
    return ""


def _record_namespace(item: Any) -> Tuple[str, str]:
    maps = _identity_maps(item)
    storage = _first_identifier(maps, ("storage_instance_id", "database_instance_id"))
    uri = _first_identifier(maps, ("source_uri",))
    source_id = _first_identifier(maps, ("source_id",))
    source = "uri:" + uri if uri else "source:" + source_id if source_id else ""
    if not source:
        origins = [m["origin"] for m in maps if isinstance(m.get("origin"), dict)]
        uri = _first_identifier(origins, ("source_uri",))
        source_id = _first_identifier(origins, ("source_id",))
        root_id = _first_identifier(origins + maps, ("root_evidence_id",))
        opaque_origin = _first_identifier(maps, ("origin",))
        source = ("uri:" + uri if uri else "source:" + source_id if source_id
                  else "root:" + root_id if root_id else "origin:" + opaque_origin if opaque_origin else "")
    return storage, source


def _stable_key(item: Any) -> str:
    normalized = " ".join(_item_text(item).casefold().split())
    content = _identifier_digest(normalized)
    maps = _identity_maps(item)
    local_id = _first_identifier(maps, ("id",))
    namespace = _record_namespace(item)
    global_id = item.get("global_id") if isinstance(item, dict) else None
    # Fixed-size digest components avoid delimiter ambiguity and URI disclosure.
    if any(namespace):
        parts = ("record", *namespace, local_id or "text:" + content)
    elif (type(global_id) is str and 0 < len(global_id) <= 4096
          and re.fullmatch(r"[^\s\x00-\x1f\x7f-\x9f\ud800-\udfff]+", global_id)):
        # Consume the public producer's opaque record ID without parsing a
        # profile or promoting either field to provenance, ACL or a root vote.
        # Existing explicit namespaces retain precedence; malformed/oversize
        # IDs fall back to the unchanged legacy content/local-ID contract.
        parts = ("global", _identifier_digest(global_id))
    else:
        # Legacy same-ID/same-text and ID-less content duplicates still collapse.
        # A bare local ID with different content is ambiguous, not proof of identity.
        parts = ("legacy", local_id, content)
    return "record:" + hashlib.sha256("|".join(parts).encode("ascii")).hexdigest()


def _root_keys(item: Any) -> Set[str]:
    """Use supplied provenance only to suppress echoes, never to grant trust.

    An origin/root reference takes precedence over a derivative's own source.
    Unknown or malformed provenance cannot earn a corroboration vote.
    """
    maps = _identity_maps(item)
    roots = []
    derived = False
    for mapping in maps:
        for field in ("current_root_evidence", "origin", "transformation"):
            if field in mapping:
                derived = True
                if isinstance(mapping[field], dict):
                    roots.append(mapping[field])
        if _identifier_digest(mapping.get("root_evidence_id")):
            roots.append(mapping)
    if not roots:
        if derived:
            return set()
        roots = maps
    found: Set[str] = set()
    # References are data; bounded mapping traversal, no JSON/eval/getNamespace.
    stack = [(root, 0) for root in roots[:16]]
    visited = 0
    while stack and visited < 16:
        root, depth = stack.pop(0)
        visited += 1
        root_id = _first_identifier([root], ("root_evidence_id",))
        uri = _first_identifier([root], ("source_uri",))
        source_id = _first_identifier([root], ("source_id",))
        storage = _first_identifier([root], ("storage_instance_id", "database_instance_id"))
        if root_id:
            found.add("root:" + root_id)
        if uri:
            found.add("uri:" + uri)
        if source_id and not uri:
            found.add("source:" + storage + ":" + source_id)
        if depth < 3:
            for field in ("current_root_evidence", "origin", "source", "payload"):
                nested = root.get(field)
                if isinstance(nested, dict):
                    stack.append((nested, depth + 1))
    return found


def _jaccard(left: Set[str], right: Set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def memory_context_collapse(
    query: str,
    memory_wiki_hits=None,
    knowledge_hits=None,
    distill_hits=None,
    budget: int = 6,
    **_: Any,
) -> List[Any]:
    """Deduplicate and rank context from independent sources.

    Record identity, content overlap and evidence independence are separate.
    The caller must supply ACL-filtered hits. No store/profile lookup is made;
    returned dictionaries and their confidence/provenance remain unchanged.
    """
    budget = max(0, int(budget or 0))
    if budget == 0:
        return []

    entries: List[Dict[str, Any]] = []
    for source, items in (
        ("memory_wiki", memory_wiki_hits or []),
        ("knowledge", knowledge_hits or []),
        ("distill", distill_hits or []),
    ):
        for item in items:
            text = _item_text(item)
            entries.append(
                {
                    "source": source,
                    "item": item,
                    "key": _stable_key(item),
                    "roots": _root_keys(item),
                    "tokens": collapse_tokenize(text),
                    "text": text,
                }
            )

    unique: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for entry in entries:
        if entry["key"] in seen:
            continue
        seen.add(entry["key"])
        unique.append(entry)

    query_tokens = collapse_tokenize(query)
    scored: List[Tuple[float, int, Any]] = []
    for index, entry in enumerate(unique):
        item = entry["item"]
        salience = 0.5
        confidence = 0.5
        if isinstance(item, dict):
            try:
                salience = max(0.0, min(1.0, float(item.get("salience", 0.5))))
            except (TypeError, ValueError):
                salience = 0.5
            try:
                confidence = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
            except (TypeError, ValueError):
                confidence = 0.5

        query_overlap = _jaccard(query_tokens, entry["tokens"])
        corroborating_sources = set()
        counted_roots = set(entry["roots"])
        for other in unique:
            if other is entry or other["source"] == entry["source"]:
                continue
            if (entry["roots"] and other["roots"]
                    and not counted_roots.intersection(other["roots"])
                    and _jaccard(entry["tokens"], other["tokens"]) >= 0.45):
                corroborating_sources.add(other["source"])
                counted_roots.update(other["roots"])

        score = (
            0.50 * salience
            + 0.25 * confidence
            + 0.20 * query_overlap
            + 0.05 * min(len(corroborating_sources), 2)
        )
        scored.append((score, -index, item))

    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [item for _, _, item in scored[:budget]]
