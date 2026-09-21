"""Deterministic memory-intent classification and bounded query expansion.

The planner is deliberately local and side-effect free.  It improves recall for
multi-clause and temporal questions without placing an LLM call on the prompt
critical path.  Callers remain responsible for ACL filtering and content guards.
"""
from __future__ import annotations

import re
from typing import Any


_SPACE_RE = re.compile(r"\s+")
_CLAUSE_RE = re.compile(
    r"(?:[;!?]+|\s+(?:and|also|plus|then|while|but|as well as|и|а также|затем|потом|но)\s+)",
    re.IGNORECASE,
)
_TEMPORAL_RE = re.compile(
    r"\b(?:today|yesterday|tomorrow|current|currently|latest|recent|recently|"
    r"before|after|since|until|when|first|last|previous|now|"
    r"сегодня|вчера|завтра|текущ(?:ий|ая|ее|ие)|последн(?:ий|яя|ее|ие)|"
    r"недавн(?:о|ий|яя|ее)|до|после|с|когда|сначала|раньше|сейчас)\b",
    re.IGNORECASE,
)
_CURRENT_STATE_RE = re.compile(
    r"\b(?:current|currently|latest|now|still|active|today|"
    r"текущ(?:ий|ая|ее|ие)|последн(?:ий|яя|ее|ие)|сейчас|актуальн(?:ый|ая|ое|ые)|ещ[её])\b",
    re.IGNORECASE,
)
_PREFERENCE_RE = re.compile(
    r"\b(?:prefer|preference|like|dislike|favorite|favourite|always|never|"
    r"предпочита\w*|нравит\w*|любим\w*|не люблю|всегда|никогда)\b",
    re.IGNORECASE,
)
_PROCEDURE_RE = re.compile(
    r"\b(?:how|steps?|procedure|workflow|runbook|install|configure|fix|deploy|"
    r"как|шаг|процедур|процесс|инструкц|настро|установ|исправ|развер)\w*",
    re.IGNORECASE,
)
_NEGATIVE_PREMISE_RE = re.compile(
    r"\b(?:didn['’]?t|did not|never|isn['’]?t|is not|wasn['’]?t|was not|"
    r"не делал|не было|никогда не|разве не|точно ли)\b",
    re.IGNORECASE,
)
_QUESTION_PREFIX_RE = re.compile(
    r"^\s*(?:(?:please\s+)?(?:tell|remind|show)\s+me\s+|"
    r"(?:do\s+you\s+remember|what\s+do\s+you\s+remember\s+about|"
    r"what\s+did\s+i\s+(?:say|tell\s+you)\s+about|"
    r"can\s+you\s+recall)\s+|"
    r"(?:пожалуйста[, ]+)?(?:напомни|расскажи|покажи)\s+(?:мне\s+)?|"
    r"(?:ты\s+)?помнишь\s+|что\s+(?:я\s+)?(?:говорил|рассказывал)\s+(?:тебе\s+)?(?:о|про)\s+)",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r"[\"“”«»]([^\"“”«»]{3,160})[\"“”«»]")


def _clean(value: str, max_chars: int = 500) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip(" \t\r\n,.;:!?-")[:max_chars]


def classify_memory_intent(query: str) -> dict[str, Any]:
    """Classify retrieval intent with transparent multilingual rules."""
    text = _clean(query)
    clauses = [part for part in (_clean(v) for v in _CLAUSE_RE.split(text)) if len(part) >= 3]
    temporal = bool(_TEMPORAL_RE.search(text))
    current_state = bool(_CURRENT_STATE_RE.search(text))
    preference = bool(_PREFERENCE_RE.search(text))
    procedure = bool(_PROCEDURE_RE.search(text))
    negative_premise = bool(_NEGATIVE_PREMISE_RE.search(text))
    multi_hop = len(clauses) > 1 or len(_QUOTED_RE.findall(text)) > 1
    if preference:
        primary = "preference"
    elif procedure:
        primary = "procedural"
    elif current_state:
        primary = "current_state"
    elif temporal:
        primary = "temporal"
    elif multi_hop:
        primary = "multi_hop"
    else:
        primary = "factual"
    return {
        "primary": primary,
        "temporal": temporal,
        "current_state": current_state,
        "multi_hop": multi_hop,
        "preference": preference,
        "procedural": procedure,
        "negative_premise": negative_premise,
        "deep_recommended": bool(multi_hop or temporal or negative_premise),
    }


def expand_memory_queries(query: str, mode: str = "auto", max_queries: int | None = None) -> list[str]:
    """Return stable, de-duplicated retrieval queries under a hard size cap.

    ``fast`` keeps the original only. ``auto`` adds up to two useful variants,
    while ``deep`` may add clause and quoted-phrase variants.  Expansion never
    invents entities or facts that are absent from the caller's query.
    """
    mode = str(mode or "auto").strip().lower()
    if mode not in {"fast", "auto", "deep"}:
        raise ValueError("mode must be one of: fast, auto, deep")
    original = _clean(query)
    if not original:
        return []
    cap = max_queries if max_queries is not None else {"fast": 1, "auto": 3, "deep": 5}[mode]
    cap = max(1, min(int(cap), 8))
    values: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        normalized = _clean(value)
        key = normalized.casefold()
        if len(normalized) >= 3 and key not in seen and len(values) < cap:
            seen.add(key)
            values.append(normalized)

    add(original)
    if mode == "fast" or len(values) >= cap:
        return values

    content = _clean(_QUESTION_PREFIX_RE.sub("", original))
    if content and content.casefold() != original.casefold():
        add(content)

    intent = classify_memory_intent(original)
    if intent["multi_hop"] or mode == "deep":
        for clause in _CLAUSE_RE.split(content or original):
            clause = _clean(clause)
            # Very short fragments make broad FTS OR queries and hurt precision.
            if len(clause) >= 5:
                add(clause)

    if mode == "deep":
        for quoted in _QUOTED_RE.findall(original):
            add(quoted)

    return values
