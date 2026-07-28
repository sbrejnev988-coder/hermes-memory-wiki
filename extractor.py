#!/usr/bin/env python3
"""Session claim extraction for Hermes Memory Wiki.

Heuristic extraction is local. Optional LLM extraction is disabled by default
because it can transmit session text to the configured endpoint.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any, Callable, Dict, List, Optional

EXTRACTION_ENABLED = os.environ.get("MW_EXTRACTION_ENABLED", "0").strip().lower() in {
    "1", "true", "yes", "on"
}
EXTRACTION_MODEL = os.environ.get("MW_EXTRACTION_MODEL", "deepseek-v4-pro")
EXTRACTION_BASE_URL = os.environ.get(
    "MW_EXTRACTION_BASE_URL", "http://127.0.0.1:18089/v1/chat/completions"
)
EXTRACTION_API_KEY = os.environ.get("MW_EXTRACTION_API_KEY") or os.environ.get(
    "OPENROUTER_API_KEY", ""
)
EXTRACTION_TIMEOUT = max(1, min(120, int(os.environ.get("MW_EXTRACTION_TIMEOUT", "60"))))

_PATTERN_REMEMBER = re.compile(
    r"(?:запомни|remember|note this|store this|keep in mind)[:\s]*(.+?)(?:\.|$)", re.I
)
_PATTERN_PREFERENCE = re.compile(
    r"(?:я (?:всегда|никогда|предпочитаю|люблю|ненавижу)|I (?:always|never|prefer|love|hate))\s+(.+?)(?:\.|$)",
    re.I,
)
_PATTERN_DECISION = re.compile(
    r"(?:решено|реш(?:ил|или)|decision|decided)[:\s]*(.+?)(?:\.|$)", re.I
)
_PATTERN_FACT = re.compile(r"(?:факт|fact|note|важно)[:\s]*(.+?)(?:\.|$)", re.I)
_VALID_TYPES = {"fact", "preference", "decision", "procedure"}


def _normalize_exchanges(exchanges: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Accept both role/content messages and legacy user/assistant pairs."""
    normalized: List[Dict[str, str]] = []
    for exchange in exchanges or []:
        if not isinstance(exchange, dict):
            continue
        if "role" in exchange or "content" in exchange:
            role = str(exchange.get("role") or "user").casefold()
            content = str(exchange.get("content") or "").strip()
            if content:
                normalized.append(
                    {"role": "assistant" if role == "assistant" else "user", "content": content}
                )
            continue
        user = str(exchange.get("user") or "").strip()
        assistant = str(exchange.get("assistant") or "").strip()
        if user:
            normalized.append({"role": "user", "content": user})
        if assistant:
            normalized.append({"role": "assistant", "content": assistant})
    return normalized


def _heuristic_extract(text: str) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    for pattern, claim_type in (
        (_PATTERN_REMEMBER, "preference"),
        (_PATTERN_PREFERENCE, "preference"),
        (_PATTERN_DECISION, "decision"),
        (_PATTERN_FACT, "fact"),
    ):
        for match in pattern.findall(text or ""):
            claim = " ".join(str(match).split()).strip()
            if 10 < len(claim) <= 2000:
                claims.append(
                    {
                        "claim": claim,
                        "type": claim_type,
                        "topic": "general",
                        "source": "extractor:heuristic",
                    }
                )
    return claims


def _extract_json_object(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    parsed = json.loads(text[start : end + 1])
    return parsed if isinstance(parsed, dict) else {}


def _normalize_entry(entry: Any, source: str) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    claim = " ".join(str(entry.get("claim") or "").split()).strip()
    if not (10 < len(claim) <= 2000):
        return None
    claim_type = str(entry.get("type") or "fact").casefold()
    if claim_type not in _VALID_TYPES:
        claim_type = "fact"
    topic = " ".join(str(entry.get("topic") or "general").split())[:120] or "general"
    return {"claim": claim, "type": claim_type, "topic": topic, "source": source}


def _llm_extract(exchanges: List[Dict[str, str]], session_id: str = "") -> Dict[str, Any]:
    if not EXTRACTION_ENABLED:
        return {"extracted": 0, "entries": [], "error": "extraction disabled"}
    if not EXTRACTION_API_KEY:
        return {"extracted": 0, "entries": [], "error": "extraction key missing"}

    messages = [
        {
            "role": "system",
            "content": (
                "Extract only durable facts, preferences, decisions and procedures. "
                'Return JSON: {"claims":[{"claim":"...","type":"fact|preference|decision|procedure","topic":"..."}]}.'
            ),
        }
    ]
    for exchange in exchanges[-12:]:
        messages.append(
            {
                "role": exchange["role"],
                "content": exchange["content"][:2000],
            }
        )

    try:
        body = json.dumps(
            {
                "model": EXTRACTION_MODEL,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 2000,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            EXTRACTION_BASE_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {EXTRACTION_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=EXTRACTION_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        result = _extract_json_object(content)
        entries = [
            normalized
            for raw_entry in result.get("claims", [])
            if (normalized := _normalize_entry(raw_entry, "extractor:llm")) is not None
        ]
        return {"extracted": len(entries), "entries": entries, "session_id": session_id}
    except Exception as exc:
        return {"extracted": 0, "entries": [], "error": str(exc)[:300]}


def extract_session_claims(
    exchanges: List[Dict[str, Any]],
    session_id: str = "",
    add_claim_callback: Optional[Callable[..., Any]] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Extract and optionally persist durable claims."""
    messages = _normalize_exchanges(exchanges)
    user_text = " ".join(
        message["content"] for message in messages if message["role"] == "user"
    )
    entries = _heuristic_extract(user_text[-8000:])
    llm_result = _llm_extract(messages, session_id) if EXTRACTION_ENABLED else {
        "extracted": 0,
        "entries": [],
    }
    entries.extend(llm_result.get("entries", []))

    persisted_ids: List[str] = []
    errors: List[str] = []
    if add_claim_callback is not None:
        for entry in entries:
            try:
                claim_id = add_claim_callback(
                    entry["claim"],
                    topic=entry.get("topic") or "general",
                    source=entry.get("source") or "extractor",
                    confidence=0.78 if entry.get("source") == "extractor:llm" else 0.72,
                    salience=0.72,
                )
                if claim_id:
                    persisted_ids.append(str(claim_id))
            except Exception as exc:
                errors.append(str(exc)[:300])

    return {
        "extracted": len(entries),
        "persisted": len(persisted_ids),
        "persisted_ids": persisted_ids,
        "entries": entries,
        "session_id": session_id,
        "heuristic_only": not EXTRACTION_ENABLED,
        "errors": errors,
        "error": llm_result.get("error", ""),
    }


def extractor_score_session(exchanges: List[Dict[str, Any]]) -> Dict[str, float]:
    messages = _normalize_exchanges(exchanges)
    user_text = " ".join(
        message["content"] for message in messages if message["role"] == "user"
    )
    signals = sum(
        1
        for pattern in (
            _PATTERN_REMEMBER,
            _PATTERN_PREFERENCE,
            _PATTERN_DECISION,
            _PATTERN_FACT,
        )
        if pattern.search(user_text)
    )
    substantive = min(0.3, len(user_text) / 20000.0)
    return {"total": min(1.0, signals * 0.25 + substantive)}
