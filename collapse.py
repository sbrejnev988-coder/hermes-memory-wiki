#!/usr/bin/env python3
"""Cross-source context collapse for Hermes Memory Wiki.

The public API intentionally returns the original item dictionaries so callers
can consume the result without understanding this module's internal wrappers.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Set, Tuple

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


def _stable_key(item: Any) -> str:
    if isinstance(item, dict) and item.get("id"):
        return f"id:{item['id']}"
    normalized = " ".join(_item_text(item).casefold().split())
    return "text:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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

    Cross-source corroboration is awarded only when the content actually
    overlaps. The old implementation boosted every item merely because other
    sources had unrelated items in the candidate set.
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
        for other in unique:
            if other is entry or other["source"] == entry["source"]:
                continue
            if _jaccard(entry["tokens"], other["tokens"]) >= 0.45:
                corroborating_sources.add(other["source"])

        score = (
            0.50 * salience
            + 0.25 * confidence
            + 0.20 * query_overlap
            + 0.05 * min(len(corroborating_sources), 2)
        )
        scored.append((score, -index, item))

    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [item for _, _, item in scored[:budget]]
