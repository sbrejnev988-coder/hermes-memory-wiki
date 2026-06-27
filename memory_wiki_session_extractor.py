"""
memory_wiki_session_extractor.py — LLM-powered session extraction for memory-wiki.
Adapted from Memory OS (ClaudioDrews/memory-os) icarus/hooks.py, MIT License.

At session end, builds transcript from exchanges, sends to LLM (DeepSeek via local
proxy :18089), extracts structured claims as {type, summary, content, training_value},
and feeds them into memory_wiki_add_claim.

No Docker/Redis/Qdrant required. Uses local DeepSeek proxy.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────
EXTRACTION_MODEL = os.environ.get(
    "MW_EXTRACTION_MODEL",
    os.environ.get("ICARUS_EXTRACTION_MODEL", "deepseek-v4-pro"),
)
EXTRACTION_MAX_TOKENS = int(os.environ.get(
    "MW_EXTRACTION_MAX_TOKENS",
    os.environ.get("ICARUS_EXTRACTION_MAX_TOKENS", "4096"),
))
# Use local DeepSeek proxy by default
EXTRACTION_BASE_URL = os.environ.get(
    "MW_EXTRACTION_BASE_URL",
    os.environ.get("ICARUS_ENDPOINT", "http://127.0.0.1:18089/v1/chat/completions"),
)
EXTRACTION_API_KEY = (
    os.environ.get("MW_EXTRACTION_API_KEY")
    or os.environ.get("DEEPSEEK_API_KEY")
    or os.environ.get("OPENROUTER_API_KEY")
    or "godmode-internal-key"  # default for local DS2API/proxy
)
# Disable extraction entirely
EXTRACTION_ENABLED = os.environ.get(
    "MW_EXTRACTION_ENABLED", "1"
).strip().lower() not in ("0", "no", "false", "off")

EXTRACTION_TIMEOUT = int(os.environ.get("MW_EXTRACTION_TIMEOUT", "45"))


# ── JSON parsing (robust — handles markdown fences, trailing commas) ──

def _parse_json_robust(raw: str) -> Any:
    """Extract JSON array/object from LLM output with markdown tolerances."""
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    # Strip markdown code fences
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):].lstrip()
        if text.endswith("```"):
            text = text[:-3].rstrip()
    # Find first JSON structure character
    for start_char in ("[", "{"):
        idx = text.find(start_char)
        if idx != -1:
            text = text[idx:]
            break
    # Attempt parse; progressively strip trailing characters on failure
    for _ in range(20):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if text:
                text = text[:-1]
            continue
    return None


# ── Transcript builder ─────────────────────────────────────────────────

def _build_transcript(exchanges: list[dict]) -> str:
    """Build a compact transcript from session exchanges for LLM analysis."""
    lines = []
    for i, ex in enumerate(exchanges):
        user = (ex.get("user") or "").strip()
        assistant = (ex.get("assistant") or "").strip()
        if user:
            lines.append(f"[Turn {i + 1} — User]\n{user[:500]}")
        if assistant:
            lines.append(f"[Turn {i + 1} — Agent]\n{assistant[:800]}")
    return "\n\n".join(lines)


# ── Session scoring ────────────────────────────────────────────────────

_DECISION_RE = re.compile(
    r"(?i)\b(decided|resolved|completed|fixed|deployed|shipped|"
    r"reviewed|approved|rejected|built|created|configured|установил|"
    r"исправил|настроил|создал|задеплоил|починил|решил)\b"
)
_OUTCOME_RE = re.compile(
    r"(?i)(result:|outcome:|conclusion:|because|root cause|instead of|"
    r"результат:|причина:|из-за|вместо|вывод:|итог:)"
)
_COMPLETION_RE = re.compile(
    r"(?i)\b(completed|finished|done|shipped|deployed|resolved|closed|"
    r"merged|fixed|готово|сделано|выполнено|завершено|пофикшено)\b"
)


def score_session(exchanges: list[dict]) -> dict[str, float]:
    """Score session significance: 0-1. Below 0.2 → skip extraction."""
    if not exchanges:
        return {"total": 0.0}

    decisions = 0
    outcomes = 0
    completions = 0
    total_chars = 0
    substantive_turns = 0

    for ex in exchanges:
        user = (ex.get("user") or "")
        assistant = (ex.get("assistant") or "")
        total_chars += len(assistant)
        if _DECISION_RE.search(assistant):
            decisions += 1
        if _OUTCOME_RE.search(assistant):
            outcomes += 1
        if _COMPLETION_RE.search(assistant):
            completions += 1
        if len(user.strip()) > 50 and len(assistant.strip()) > 200:
            substantive_turns += 1

    score = 0.0
    score += min(0.3, decisions * 0.15)
    score += min(0.25, outcomes * 0.12)
    score += min(0.2, completions * 0.1)
    score += min(0.15, substantive_turns * 0.05)
    score += min(0.1, total_chars / 20000)

    return {
        "total": round(score, 2),
        "decisions": decisions,
        "outcomes": outcomes,
        "completions": completions,
        "substantive_turns": substantive_turns,
        "total_chars": total_chars,
    }


# ── LLM extraction ─────────────────────────────────────────────────────

_EXTRACTION_PROMPT = (
    "You are a session archivist for an AI agent. Analyze this agent session "
    "transcript and extract ONLY significant entries worth preserving in a "
    "cross-agent knowledge base. Skip trivial sessions, greetings, and routine chatter.\n\n"
    "For each significant entry, provide:\n"
    "- type: \"decision\" (technical decision with rationale), "
    "\"resolution\" (bug fix or problem solved), "
    "or \"note\" (discovery or learning)\n"
    "- summary: one line, max 80 chars, in the original language of the session\n"
    "- content: structured markdown with ## Context, ## Action/Decision, and ## Outcome. "
    "Include concrete details: commands, paths, error messages, decisions made.\n"
    "- training_value: \"high\" (outcome verified, artifact produced, decision with evidence), "
    "\"normal\" (useful context or progress), "
    "or \"low\" (marginal, but not zero)\n\n"
    "If the session contains NOTHING worth preserving across sessions, "
    "return an empty array: []\n\n"
    "Return ONLY valid JSON array, no other text:\n"
    '[{"type": "decision", "summary": "...", "content": "...", "training_value": "high"}, ...]'
)


def _llm_extract_entries(transcript: str) -> list[dict]:
    """Use LLM to extract significant entries from session transcript.

    Returns list of dicts: {type, summary, content, training_value}
    Returns empty list on failure or if nothing worth preserving.
    """
    payload = json.dumps({
        "model": EXTRACTION_MODEL,
        "messages": [
            {"role": "system", "content": _EXTRACTION_PROMPT},
            {"role": "user", "content": transcript[:8000]},
        ],
        "max_tokens": EXTRACTION_MAX_TOKENS,
        "temperature": 0.2,
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {EXTRACTION_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        req = urllib.request.Request(
            EXTRACTION_BASE_URL,
            data=payload,
            headers=headers,
        )
        resp = urllib.request.urlopen(req, timeout=EXTRACTION_TIMEOUT)
        body = json.loads(resp.read().decode("utf-8"))
        raw = body["choices"][0]["message"]["content"]

        if raw is None:
            logger.warning("memory_wiki: LLM extraction returned content:null")
            return []

        extracted = _parse_json_robust(raw)
        if isinstance(extracted, dict):
            # Unwrap {entries: [...]} or {results: [...]}
            for key in ("entries", "results", "items"):
                if key in extracted and isinstance(extracted[key], list):
                    extracted = extracted[key]
                    break
            else:
                if "type" in extracted:
                    extracted = [extracted]
                else:
                    extracted = []

        if not isinstance(extracted, list):
            logger.warning("memory_wiki: LLM extraction returned non-list: %s", type(extracted))
            return []

        allowed_types = {"decision", "resolution", "note"}
        valid = []
        for entry in extracted:
            if not isinstance(entry, dict):
                continue
            etype = entry.get("type", "")
            summary = entry.get("summary", "")
            content = entry.get("content", "")
            if etype not in allowed_types:
                continue
            if len(summary) < 10 or len(content) < 60:
                continue
            valid.append({
                "type": etype,
                "summary": summary[:80],
                "content": content[:2000],
                "training_value": entry.get("training_value", "normal"),
            })

        return valid

    except (urllib.error.URLError, json.JSONDecodeError, KeyError,
            IndexError, ValueError, ConnectionError, TimeoutError,
            OSError) as e:
        logger.warning("memory_wiki: LLM extraction failed (%s)", type(e).__name__)
        return []


# ── Main entry point ───────────────────────────────────────────────────

def extract_session_claims(
    exchanges: list[dict],
    session_id: str = "",
    *,
    add_claim_callback: Any = None,
) -> dict:
    """Extract structured claims from session exchanges via LLM.

    Args:
        exchanges: List of {user, assistant} dicts from the session
        session_id: Session identifier for source tracking
        add_claim_callback: Function(claim, topic, evidence, source, confidence, salience)
                            called for each extracted entry

    Returns:
        {extracted: N, entries: [...], error: None} or {extracted: 0, error: "..."}
    """
    if not EXTRACTION_ENABLED:
        return {"extracted": 0, "entries": [], "error": "disabled"}

    if not exchanges or len(exchanges) < 2:
        return {"extracted": 0, "entries": [], "error": "too few exchanges"}

    scores = score_session(exchanges)
    if scores["total"] < 0.2:
        return {
            "extracted": 0, "entries": [],
            "score": scores["total"],
            "reason": "score below threshold",
        }

    transcript = _build_transcript(exchanges)
    entries = _llm_extract_entries(transcript)

    if not entries:
        logger.info(
            "memory_wiki: extraction produced nothing for session %s (score=%.2f, %d exchanges)",
            session_id or "?", scores["total"], len(exchanges),
        )
        return {"extracted": 0, "entries": [], "score": scores["total"]}

    # Map training_value → confidence/salience
    tv_map = {"high": (0.90, 0.85), "normal": (0.78, 0.70), "low": (0.60, 0.50)}

    added = []
    for entry in entries:
        conf, sal = tv_map.get(entry.get("training_value", "normal"), (0.78, 0.70))
        if add_claim_callback:
            try:
                cid = add_claim_callback(
                    claim=f"[{entry['type']}] {entry['summary']}: {entry['content'][:400]}",
                    topic="session-extract",
                    evidence=f"LLM-extracted from session {session_id}: {entry['content'][:200]}",
                    source=f"extractor:{session_id}",
                    confidence=conf,
                    salience=sal,
                )
                added.append({"id": cid, **entry})
            except Exception as e:
                logger.warning("memory_wiki: claim add failed: %s", e)

    logger.info(
        "memory_wiki: extracted %d entries from session %s (score=%.2f)",
        len(added), session_id or "?", scores["total"],
    )
    return {
        "extracted": len(added),
        "entries": added,
        "score": scores["total"],
    }
