"""Bounded OpenRouter reader and transparent accounting for public QA probes.

The caller supplies retrieved public benchmark text. This module has no access
to Hermes homes or credentials on disk. Dollar limits are soft because an API
reports actual usage only after a request; the request count is a hard cap.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from http_safety import urlopen_no_redirect

MAX_RESPONSE_BYTES = 1_000_000
_ABSTAIN = re.compile(
    r"\b(?:i (?:do not|don't) know|unknown|cannot determine|can't determine|"
    r"no information available|not mentioned|"
    r"not enough (?:information|evidence)|insufficient (?:information|evidence)|"
    r"information (?:is|was) (?:not|never) (?:provided|available))\b",
    re.IGNORECASE,
)


def looks_like_abstention(answer: str) -> bool:
    """An openly labelled heuristic, never an official answer-quality score."""
    return bool(_ABSTAIN.search(answer))


def safe_outbound_evidence(
    scanner: Callable[[str], dict[str, Any]],
    question: str,
    context: list[tuple[str, str]],
    question_date: str = "",
) -> bool:
    """Check complete untrusted inputs before any reader truncation or request.

    A missing or failing plugin scanner fails closed. This includes citation
    labels and dates, which are also sent in the OpenRouter request.
    """
    try:
        values = [question, question_date]
        values.extend(part for pair in context for part in pair)
        return not any(scanner(str(value)).get("raw_secret", True) for value in values)
    except Exception:
        return False


def _nonnegative_number(value: object, *, integer: bool = False) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or (integer and int(value) != value):
        return None
    return int(value) if integer else float(value)


def answer_openrouter(
    *, api_key: str, model: str, question: str, context: list[tuple[str, str]],
    max_tokens: int, context_chars: int, question_date: str = "",
    unsupported_answer: str = "I don't know",
) -> tuple[str, dict[str, int | float | None], float]:
    if not api_key or not model or not 1 <= max_tokens <= 256 or not 256 <= context_chars <= 10000:
        raise ValueError("invalid bounded reader configuration")
    if unsupported_answer not in {"I don't know", "No information available"}:
        raise ValueError("invalid unsupported-answer phrase")
    remaining = context_chars
    evidence: list[str] = []
    for evidence_id, value in context:
        if remaining <= 0:
            break
        line = f"[{str(evidence_id)[:80]}] " + " ".join(str(value).split())
        excerpt = line[:min(remaining, 1600)]
        if excerpt:
            evidence.append(excerpt)
            remaining -= len(excerpt)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Answer using only the supplied memory evidence. If the answer is unsupported, say " + unsupported_answer + ". Keep the answer concise."},
            {"role": "user", "content": "Question date: " + question_date[:80] + "\nQuestion: " + question[:2000]
             + "\nMemory evidence:\n" + ("\n".join(evidence) if evidence else "(none)")},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen_no_redirect(request, timeout=45) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("OpenRouter answer response exceeds byte limit")
        reply = json.loads(body.decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenRouter answer request returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"OpenRouter answer request failed: {type(exc).__name__}") from None
    elapsed_ms = (time.perf_counter() - started) * 1000
    choices = reply.get("choices") if isinstance(reply, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("OpenRouter answer response has no choice")
    message = choices[0].get("message") or {}
    answer = message.get("content") if isinstance(message, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("OpenRouter answer response has no text")
    usage = reply.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    reported = {
        "prompt_tokens": _nonnegative_number(usage.get("prompt_tokens"), integer=True),
        "completion_tokens": _nonnegative_number(usage.get("completion_tokens"), integer=True),
        "total_tokens": _nonnegative_number(usage.get("total_tokens"), integer=True),
        "cost": _nonnegative_number(usage.get("cost")),
        "context_chars": context_chars - remaining,
    }
    return answer.strip(), reported, round(elapsed_ms, 2)


@dataclass
class AnswerBudget:
    max_requests: int
    cost_soft_cap_usd: float | None = None
    attempted: int = 0
    reported_cost_usd: float = 0.0
    cost_coverage: int = 0
    unknown_cost: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.max_requests, bool) or not isinstance(self.max_requests, int) or not 0 <= self.max_requests <= 1_000_000:
            raise ValueError("answer request budget must be 0..1000000")
        if self.cost_soft_cap_usd is not None and (
            isinstance(self.cost_soft_cap_usd, bool)
            or not isinstance(self.cost_soft_cap_usd, (int, float))
            or not math.isfinite(self.cost_soft_cap_usd)
            or self.cost_soft_cap_usd <= 0
        ):
            raise ValueError("answer cost soft cap must be positive")

    def skip_reason(self) -> str | None:
        if self.attempted >= self.max_requests:
            return "request_budget"
        if self.cost_soft_cap_usd is not None:
            if self.unknown_cost:
                return "unreported_cost"
            if self.reported_cost_usd >= self.cost_soft_cap_usd:
                return "reported_cost_soft_cap"
        return None

    def begin(self) -> None:
        reason = self.skip_reason()
        if reason:
            raise RuntimeError(f"reader budget exhausted: {reason}")
        self.attempted += 1

    def record(self, usage: dict[str, int | float | None]) -> None:
        cost = usage.get("cost")
        if isinstance(cost, (int, float)) and math.isfinite(cost) and cost >= 0:
            self.reported_cost_usd += cost
            self.cost_coverage += 1
        else:
            self.unknown_cost = True

    def summary(self) -> dict[str, int | float | bool | None]:
        return {
            "max_requests": self.max_requests,
            "attempted_requests": self.attempted,
            "reported_cost_coverage": self.cost_coverage,
            "reported_cost_usd": round(self.reported_cost_usd, 8) if self.cost_coverage == self.attempted else None,
            "cost_soft_cap_usd": self.cost_soft_cap_usd,
            "cost_cap_is_hard": False,
        }
