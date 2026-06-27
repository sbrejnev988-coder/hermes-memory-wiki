"""
guard.py — Safe context injection guard for memory-wiki.

Provides:
  - Social closer detection (skip search for trivial messages)
  - Prompt injection sanitization (regex-based pattern stripping)
  - Context text sanitization (truncation + normalization)

Pure functions, zero dependencies.
"""

from __future__ import annotations

import re
from typing import Optional

__all__ = [
    "is_social_close",
    "sanitize_context_text",
    "SOCIAL_CLOSERS_RU",
    "SOCIAL_CLOSERS_EN",
]

# ── Social closers (messages that shouldn't trigger memory search) ─────

SOCIAL_CLOSERS_RU = frozenset({
    "ок", "окей", "спс", "спасибо", "понял", "принял", "ясно",
    "хорошо", "ладно", "добро", "давай", "ага", "угу", "отлично",
    "супер", "заебись", "пиздато", "красава", "топ", "огонь",
    "👍", "👌", "✅", "🔥", "💯", "🙏", "❤️", "🤝",
    "сделано", "готово", "выполнено", "принято",
})

SOCIAL_CLOSERS_EN = frozenset({
    "ok", "okay", "thanks", "thank you", "thx", "tks", "got it",
    "understood", "clear", "sure", "fine", "good", "great",
    "perfect", "awesome", "done", "ack", "acknowledged",
    "👍", "👌", "✅", "🔥", "💯", "🙏", "❤️", "🤝",
})


def is_social_close(text: str) -> bool:
    """Return True if message is a social closer that shouldn't trigger search.

    Avoids wasting tokens/embeddings on trivial messages like "ok", "👍", "спс".
    """
    if not text:
        return False
    stripped = text.strip()
    # Exact match against known closers
    if stripped.lower() in SOCIAL_CLOSERS_RU or stripped.lower() in SOCIAL_CLOSERS_EN:
        return True
    # Very short ASCII-only without technical markers
    if len(stripped) < 6 and stripped.isascii() and not any(
        c in stripped for c in "://.@#$_?"
    ):
        return True
    # Very short Cyrillic without technical markers
    if len(stripped) < 8 and all(
        ord(c) < 128 or 0x0400 <= ord(c) <= 0x04FF or c.isspace()
        for c in stripped
    ) and not any(c in stripped for c in "://.@#$_?!"):
        return True
    return False


# ── Prompt injection sanitization ──────────────────────────────────────

_INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "ignore all previous/prior instructions/directives"
    (re.compile(
        r"(?i)\bignore\s+all\s+(previous|prior)\s+"
        r"(instructions|directives|commands|messages|prompts|context)"
    ), "[REDACTED]"),
    # "you are/will now become/act/acting as (a/an) AI/assistant..."
    (re.compile(
        r"(?i)\byou\s+(are|will\s+now)\s+(now\s+)?(become|act|acting)\s+as\s+"
        r"(a\s+|an\s+)?(AI\s+assistant|assistant|AI|agent|LLM|chatbot|model|system)"
    ), "[REDACTED]"),
    # "new instructions/directives/commands follow/above/below"
    (re.compile(
        r"(?i)\bnew\s+(instructions|directives|commands)\s+(follow|above|below)"
    ), "[REDACTED]"),
    # Template injection: {{...}}, ${...}
    (re.compile(r"\{\{.*?\}\}|\$\{.*?\}"), "[REDACTED]"),
    # Triple-backtick code fences
    (re.compile(r"```"), "[code]"),
    # Markdown/javascript data: URLs in links and images
    (re.compile(r"(?i)(javascript|data)\s*:"), "sanitized:"),
    # XML/HTML injection: <script>, event handlers, iframes
    (re.compile(r"<\s*script[\s>]|on\w+\s*=|<s*iframe[\s>]"), "[sanitized]"),
    # Known system prefixes
    (re.compile(r"(?i)\[IMPORTANT:.*?\]|\[SYSTEM:.*?\]|\[OVERRIDE:.*?\]"), "[REDACTED]"),
    # "GODMODE" / "UNCHAINED" injection attempts in retrieved context
    (re.compile(r"(?i)\b(GODMODE|UNCHAINED|UNRESTRICTED)\s+(ACTIVATED|ENABLED|MODE)\b"),
     "[REDACTED]"),
    # Control characters (keep newlines and tabs)
    (re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"), ""),
    # Zero-width and invisible Unicode
    (re.compile(r"[\u200b-\u200f\u2028-\u202f\u2060-\u2064\ufeff]"), ""),
]


def _validate_safe_content(text: str) -> str:
    """Catch unknown attack patterns via heuristic: high density of imperative
    language in a short span. Returns text or [SANITIZED] placeholder.
    """
    if not text or len(text) < 20:
        return text
    try:
        directives = len(re.findall(
            r"(?i)\b(ignore|forget|disregard|override|replace|pretend|"
            r"act\s+as|you\s+(are|must|will|shall))\b",
            text,
        ))
        if directives >= 3 and directives / max(len(text), 1) > 0.02:
            return "[SANITIZED]"
        return text
    except Exception:
        return text


def sanitize_context_text(text: str, max_len: int = 600) -> str:
    """Sanitize retrieved text before it enters the agent's context.

    Strips known injection patterns, validates safety heuristic, truncates
    to max_len. Fail-open: returns truncated original on error.

    Args:
        text: Raw text from memory source (wiki claim, KB hit, distill capsule)
        max_len: Maximum characters to return (default: 600)

    Returns:
        Sanitized, truncated text ready for context injection
    """
    if not text:
        return ""
    try:
        result = str(text)
        for pattern, replacement in _INJECTION_PATTERNS:
            result = pattern.sub(replacement, result)
        # Safety heuristic catch
        result = _validate_safe_content(result)
        # Normalize excessive whitespace
        result = re.sub(r"\n{4,}", "\n\n\n", result)
        result = re.sub(r" {2,}", " ", result)
        # Truncate
        if len(result) > max_len:
            result = result[:max_len - 3] + "..."
        return result.strip()
    except Exception:
        return str(text)[:max_len]


# ── Convenience: batch sanitize ─────────────────────────────────────────

def sanitize_context_batch(
    items: list[dict],
    text_key: str = "text",
    max_len: int = 400,
    label: str = "",
) -> list[str]:
    """Sanitize a batch of memory items for context injection.

    Args:
        items: List of dicts with a text field
        text_key: Key for the text field (default: "text")
        max_len: Max chars per item
        label: Optional source label to prefix (e.g. "[memory-wiki]")

    Returns:
        List of sanitized strings, one per item, with optional label prefix
    """
    out = []
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        raw = item.get(text_key, "")
        clean = sanitize_context_text(raw, max_len=max_len)
        if not clean:
            continue
        prefix = f"{label} " if label else ""
        out.append(f"{prefix}{clean}")
    return out
