#!/usr/bin/env python3
"""memory-wiki guard — write firewall, social closer detection, context sanitization.

P0 #3 fix: _safe_recall_text now routes through sanitize_context_text
from guard module, adding prompt-injection detection to all memory recall paths.
"""
from __future__ import annotations
import re
from typing import List, Optional

_INJECTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above|the\s+above)\s+(?:instructions?|directives?|commands?|context|conversation)", re.I),
    re.compile(r"(?:disregard|forget|override|bypass|skip)\s+(?:all\s+)?(?:previous|prior|above|earlier|existing)\s+(?:instructions?|directives?|rules?|constraints?|guidelines?)", re.I),
    re.compile(r"you\s+(?:are|must|should|shall|will)\s+(?:now|henceforth|from\s+now\s+on)\s+(?:act|behave|operate|function|respond)\s+(?:as|like)\s+(?:an?|the)\s", re.I),
    re.compile(r"(?:system\s*(?:prompt|message|instruction|directive)|developer\s*(?:prompt|message|note))\s*(?:is|was|has\s+been|:)\s*", re.I),
    re.compile(r"(?:new|updated|revised|changed|overridden)\s+(?:system\s*(?:prompt|message|instruction)|instructions?|directives?|rules?)", re.I),
    re.compile(r"(?:pretend|imagine|simulate|role-?play|act\s+as\s+if)\s+(?:you\s+(?:are|were)|that\s+you\s+(?:are|were))", re.I),
    re.compile(r"(?:DAN|jailbreak|prompt\s*(?:injection|hack|leak)|system\s*prompt\s*(?:leak|reveal|show|display|print))", re.I),
    re.compile(r"(?:from\s+now\s+on|starting\s+now|beginning\s+now|effective\s+immediately)\s+(?:you\s+(?:are|will|must|should))", re.I),
    re.compile(r"<\|?\s*(?:system|instruction|directive|command|prompt)\s*\|?>", re.I),
    re.compile(r"\[\s*(?:system|instruction|override|directive)\s*\]", re.I),
    re.compile(r"(?:do\s+not\s+follow|break\s+free\s+from|escape\s+(?:from|your))", re.I),
]

_SOCIAL_PATTERNS = re.compile(
    r"(?i)^(?:ok+\s*$|yes\s*$|no\s*$|thanks?\s*$|thank\s*you|good\s*(?:morning|night|evening|afternoon)|hello|hi|hey|bye|see\s*you|lol|lmao|rofl|haha+|nice|good|great|cool|awesome|perfect|sure|alright|fine|okay|got\s*it|understood|makes?\s*sense|will\s*do|on\s*it|working|sounds?\s*good|alrighty|kk|np|nvm|idk|btw|ttyl|brb)")

def is_social_close(text: str) -> bool:
    """Detect social/turn-closing messages that shouldn't trigger memory search."""
    return bool(_SOCIAL_PATTERNS.search(text.strip()))

def sanitize_context_text(text: str, max_len: int = 600) -> str:
    """Sanitize text for injection patterns before context injection."""
    if not text or not text.strip():
        return ""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return f"[filtered: injection pattern detected]"
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
