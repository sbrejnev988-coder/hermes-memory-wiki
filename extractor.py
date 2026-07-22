#!/usr/bin/env python3
"""memory-wiki extractor — session claim extraction (disabled by default).

Extracts durable claims from session exchanges using heuristic and optionally
LLM-based methods. Disabled by default (MW_EXTRACTION_ENABLED=0) to avoid
sending transcript data to external LLM endpoints.
"""
from __future__ import annotations
import json, os, re, time, urllib.request, urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EXTRACTION_ENABLED = os.environ.get("MW_EXTRACTION_ENABLED", "0") == "1"
EXTRACTION_MODEL = os.environ.get("MW_EXTRACTION_MODEL", "deepseek-v4-pro")
EXTRACTION_BASE_URL = os.environ.get("MW_EXTRACTION_BASE_URL", "http://127.0.0.1:18089/v1/chat/completions")
EXTRACTION_API_KEY = os.environ.get("MW_EXTRACTION_API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")

_PATTERN_REMEMBER = re.compile(r'(?:запомни|remember|note this|store this|keep in mind)[:\s]*(.+?)(?:\.|$)', re.I)
_PATTERN_PREFERENCE = re.compile(r'(?:я (?:всегда|никогда|предпочитаю|люблю|ненавижу)|I (?:always|never|prefer|love|hate))\s+(.+?)(?:\.|$)', re.I)
_PATTERN_DECISION = re.compile(r'(?:решено|реш(?:ил|или)|decision|decided)[:\s]*(.+?)(?:\.|$)', re.I)
_PATTERN_FACT = re.compile(r'(?:факт|fact|note|важно)[:\s]*(.+?)(?:\.|$)', re.I)

def _heuristic_extract(text: str) -> List[Dict[str, Any]]:
    """Extract claims using regex patterns (no LLM call)."""
    claims = []
    for pattern, claim_type in [(_PATTERN_REMEMBER, "preference"), (_PATTERN_PREFERENCE, "preference"),
                                 (_PATTERN_DECISION, "decision"), (_PATTERN_FACT, "fact")]:
        for match in pattern.findall(text):
            claim = match.strip()
            if len(claim) > 10:
                claims.append({"claim": claim, "type": claim_type, "source": "extractor:heuristic"})
    return claims

def _llm_extract(exchanges: List[Dict[str, Any]], session_id: str = "") -> Dict[str, Any]:
    """Extract claims via LLM (requires EXTRACTION_ENABLED=1)."""
    if not EXTRACTION_ENABLED or not EXTRACTION_API_KEY:
        return {"extracted": 0, "entries": [], "error": "extraction disabled"}
    messages = [{"role": "system", "content": (
        "Extract durable facts, preferences, decisions and procedures from the session. "
        "Return JSON: {\"claims\": [{\"claim\": \"...\", \"type\": \"fact|preference|decision|procedure\", \"topic\": \"...\"}]}"
    )}]
    for ex in exchanges[-12:]:
        role = ex.get("role", "user")
        content = str(ex.get("content", ""))[:2000]
        messages.append({"role": "user" if role == "user" else "assistant", "content": content})
    try:
        body = json.dumps({"model": EXTRACTION_MODEL, "messages": messages, "temperature": 0.3, "max_tokens": 2000}).encode()
        req = urllib.request.Request(EXTRACTION_BASE_URL, data=body,
            headers={"Authorization": f"Bearer {EXTRACTION_API_KEY}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        result = json.loads(content) if isinstance(content, str) else content
        return {"extracted": len(result.get("claims", [])), "entries": result.get("claims", []), "session_id": session_id}
    except Exception as e:
        return {"extracted": 0, "entries": [], "error": str(e)[:200]}

def extract_session_claims(exchanges: List[Dict[str, Any]], session_id: str = "", **kw) -> Dict[str, Any]:
    """Main entry point: heuristic + optional LLM extraction."""
    user_text = " ".join(str(e.get("content","")) for e in exchanges if e.get("role") == "user")
    heuristic = _heuristic_extract(user_text[-8000:])
    llm = _llm_extract(exchanges, session_id) if EXTRACTION_ENABLED else {"extracted": 0, "entries": []}
    return {"extracted": len(heuristic) + llm.get("extracted", 0),
            "entries": heuristic + llm.get("entries", []),
            "session_id": session_id,
            "heuristic_only": not EXTRACTION_ENABLED}

def extractor_score_session(exchanges: List[Dict[str, Any]]) -> Dict[str, float]:
    """Score how likely a session contains extractable durable claims."""
    user_text = " ".join(str(e.get("content","")) for e in exchanges if e.get("role") == "user")
    signals = sum(1 for p in [_PATTERN_REMEMBER, _PATTERN_PREFERENCE, _PATTERN_DECISION, _PATTERN_FACT] if p.search(user_text))
    return {"total": min(1.0, signals * 0.25 + 0.1)}
