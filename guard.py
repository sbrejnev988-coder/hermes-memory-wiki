#!/usr/bin/env python3
"""memory-wiki guard — write firewall, social closer detection, context sanitization.

P0 #3 fix: _safe_recall_text now routes through sanitize_context_text
from guard module, adding prompt-injection detection to all memory recall paths.
"""
from __future__ import annotations
import re
import unicodedata
from typing import List

_INJECTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above|the\s+above)\s+(?:instructions?|directives?|commands?|context|conversation)", re.I),
    re.compile(r"(?:disregard|forget|override|bypass|skip)\s+(?:all\s+)?(?:previous|prior|above|earlier|existing)\s+(?:instructions?|directives?|rules?|constraints?|guidelines?)", re.I),
    re.compile(r"you\s+(?:are|must|should|shall|will)\s+(?:now|henceforth|from\s+now\s+on)\s+(?:act|behave|operate|function|respond)\s+(?:as|like)\s+(?:an?|the)\s", re.I),
    re.compile(r"(?:system\s*(?:prompt|message|instruction|directive)|developer\s*(?:prompt|message|note))\s*(?:is|was|has\s+been|:)\s*", re.I),
    re.compile(r"(?:new|updated|revised|changed|overridden)\s+(?:system\s*(?:prompt|message|instruction)|instructions?|directives?|rules?)", re.I),
    re.compile(r"(?:pretend|imagine|simulate|role-?play|act\s+as\s+if)\s+(?:you\s+(?:are|were)|that\s+you\s+(?:are|were))", re.I),
    re.compile(r"(?:\bDAN\s+(?:mode|persona|prompt|jailbreak)\b|\b(?:enable|activate|use)\s+DAN\b|\bdo\s+anything\s+now\b|jailbreak|prompt\s*(?:injection|hack|leak)|system\s*prompt\s*(?:leak|reveal|show|display|print))", re.I),
    re.compile(r"(?:from\s+now\s+on|starting\s+now|beginning\s+now|effective\s+immediately)\s+(?:you\s+(?:are|will|must|should))", re.I),
    re.compile(r"<\|?\s*(?:system|instruction|directive|command|prompt)\s*\|?>", re.I),
    re.compile(r"\[\s*(?:system|instruction|override|directive)\s*\]", re.I),
    re.compile(r"(?:do\s+not\s+follow|break\s+free\s+from|escape\s+(?:from|your))", re.I),
]

# Orthogonal local rejection: never grant admission or change the term grammar.
_RUSSIAN_OVERRIDE_PATTERN = re.compile(
    r"\bигнорируй(?:те)?\s+(?:все\s+)?предыдущие\s+(?:инструкции|указания|команды|правила)\b", re.I,
)
_CONTEXT_PROTOCOL_PATTERN = re.compile(
    r"(?:<\s*/?\s*memory-context(?:\s+[^<>]*)?\s*/?>|<\|\s*(?:im_start|im_end)\s*\|>)", re.I,
)

# Only a complete, closed descriptive sentence can exempt a bare term match.
# Keep the original deny patterns above: unknown commands remain rejected.
_TERM_GRAMMAR = r"(?:jailbreak|prompt (?:injection|hack|leak))"
_TERM_MENTION = re.compile(_TERM_GRAMMAR, re.I | re.A)
_DESCRIPTION_SUBJECT = r"(?:the )?(?:documentation|report|article|audit|glossary|lesson)"
_DESCRIPTIVE_TERM_INPUT = re.compile(
    rf"(?:{_DESCRIPTION_SUBJECT} (?:discusses|describes|lists|reviews) {_TERM_GRAMMAR} (?:risks?|prevention|defenses|terminology)"
    rf"|{_DESCRIPTION_SUBJECT} (?:defines|describes) {_TERM_GRAMMAR} as a (?:security threat|threat to (?:data|trust) boundaries)"
    rf"|(?:we|researchers|the authors|dan and jordan) (?:discussed|studied|reviewed) (?:defenses against {_TERM_GRAMMAR}|{_TERM_GRAMMAR} (?:risks?|prevention|defenses))"
    rf'|the (?:report|article|glossary|lesson) quoted the term "{_TERM_GRAMMAR}" without issuing an instruction'
    rf"|the words '{_TERM_GRAMMAR}' name a security threat"
    rf"|atlas notes describe {_TERM_GRAMMAR} defenses)\.",
    re.I | re.A,
)

# Detection-only projection; never return this rewritten view to a caller.
_DIAGNOSTIC_PROJECTION_VERSION = "r03-conservative-nfkc-casefold-lookalikes-v1"
_PROJECTION_TRANSLATION = str.maketrans({
    "а": "a", "с": "c", "е": "e", "і": "i", "ј": "j",
    "о": "o", "р": "p", "ѕ": "s", "у": "y", "х": "x",
    "\u00ad": None, "\u200b": None, "\u200c": None,
    "\u200d": None, "\u2060": None, "\ufeff": None,
})

def _diagnostic_projection(text: str) -> str:
    """Fold a finite set of known disguises for scanning, not source mutation."""
    return unicodedata.normalize("NFKC", text).casefold().translate(_PROJECTION_TRANSLATION)

_SOCIAL_PATTERNS = re.compile(
    r"(?i)^(?:ok+\s*$|yes\s*$|no\s*$|thanks?\s*$|thank\s*you|good\s*(?:morning|night|evening|afternoon)|hello|hi|hey|bye|see\s*you|lol|lmao|rofl|haha+|nice|good|great|cool|awesome|perfect|sure|alright|fine|okay|got\s*it|understood|makes?\s*sense|will\s*do|on\s*it|working|sounds?\s*good|alrighty|kk|np|nvm|idk|btw|ttyl|brb)")

def is_social_close(text: str) -> bool:
    """Detect social/turn-closing messages that shouldn't trigger memory search."""
    # Keep question marks so ambiguous questions can still trigger search.
    candidate = text.strip().rstrip(".!…").rstrip()
    return bool(_SOCIAL_PATTERNS.fullmatch(candidate))

def sanitize_context_text(text: str, max_len: int = 600) -> str:
    """Sanitize text for injection patterns before context injection."""
    if not text or not text.strip():
        return ""
    # Scan Cyrillic before Latin-lookalike translation; detection only.
    russian = unicodedata.normalize("NFKC", text).casefold()
    if (_RUSSIAN_OVERRIDE_PATTERN.search(text)
            or _RUSSIAN_OVERRIDE_PATTERN.search(russian)):
        return "[filtered: injection pattern detected]"
    projection = _diagnostic_projection(text)
    if any(_CONTEXT_PROTOCOL_PATTERN.search(candidate) for candidate in (text, projection)):
        return "[filtered: injection pattern detected]"
    descriptive = bool(_DESCRIPTIVE_TERM_INPUT.fullmatch(projection))
    for pattern in _INJECTION_PATTERNS:
        for candidate in (text, projection):
            for match in pattern.finditer(candidate):
                if (descriptive and pattern is _INJECTION_PATTERNS[6]
                        and _TERM_MENTION.fullmatch(match.group(0))):
                    continue
                return "[filtered: injection pattern detected]"
    return str(text)[:max_len]

def sanitize_context_batch(items: list, text_key: str = "text", max_len: int = 400, label: str = "") -> list:
    """Sanitize a batch of items for context injection."""
    results = []
    for item in items:
        if isinstance(item, dict):
            text = str(item.get(text_key, ""))
            sanitized = sanitize_context_text(text, max_len)
            if sanitized and not sanitized.startswith("[filtered"):
                results.append({**item, text_key: sanitized})
        elif isinstance(item, str):
            sanitized = sanitize_context_text(item, max_len)
            if sanitized and not sanitized.startswith("[filtered"):
                results.append(sanitized)
    return results
