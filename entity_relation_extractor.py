"""Explicit, source-bound relation extraction from one claim.

The provider gates this operation and owns persistence. This module only
calls the configured chat endpoint and validates candidate relations.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any


def _appears_as_phrase(phrase: str, source: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", source, re.IGNORECASE))


def extract_relations(
    claim_text: str,
    *,
    endpoint: str,
    api_key: str,
    model: str,
    predicates: frozenset[str],
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Return up to eight strictly validated, text-grounded relation rows."""
    try:
        parsed_endpoint = urllib.parse.urlsplit(endpoint)
        endpoint_port = parsed_endpoint.port
        endpoint_host = parsed_endpoint.hostname
    except (TypeError, ValueError):
        raise ValueError("invalid graph extraction endpoint") from None
    allowed_https = parsed_endpoint.scheme == "https" and bool(endpoint_host)
    allowed_loopback = (parsed_endpoint.scheme == "http"
                        and endpoint_host in {"127.0.0.1", "localhost"}
                        and endpoint_port is not None)
    if (not (allowed_https or allowed_loopback)
            or parsed_endpoint.username is not None
            or parsed_endpoint.password is not None):
        raise ValueError("graph extraction endpoint must use HTTPS or local loopback")
    if not api_key or not model:
        raise ValueError("graph extraction API key and model are required")
    source = str(claim_text or "")[:4000]
    if not source.strip():
        raise ValueError("source claim is empty")
    allowed = sorted(predicates - {"related_to"})
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 700,
        "messages": [
            {"role": "system", "content": (
                "Extract explicit directed relations from the supplied fact only. "
                "Return exactly one JSON object with a relations array (0 to 8 entries). "
                "Each entry must contain only subject, predicate, object, evidence, confidence. "
                "Subject, object, and evidence must be verbatim substrings of the fact. "
                "Do not infer unstated links. Allowed predicates: " + ", ".join(allowed)
            )},
            {"role": "user", "content": source},
        ],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=max(1.0, min(timeout, 60.0))) as response:
        envelope = json.loads(response.read(1_000_001).decode("utf-8"))
    content = envelope["choices"][0]["message"]["content"]
    if not isinstance(content, str) or len(content) > 100_000:
        raise ValueError("invalid graph extraction response")
    parsed = json.loads(content)
    if not isinstance(parsed, dict) or set(parsed) != {"relations"} or not isinstance(parsed["relations"], list):
        raise ValueError("graph extraction response must contain only a relations array")
    if len(parsed["relations"]) > 8:
        raise ValueError("graph extraction returned too many relations")
    output: list[dict[str, Any]] = []
    for item in parsed["relations"]:
        if not isinstance(item, dict) or set(item) != {"subject", "predicate", "object", "evidence", "confidence"}:
            raise ValueError("invalid relation fields")
        subject = item["subject"]
        predicate = item["predicate"]
        obj = item["object"]
        evidence = item["evidence"]
        confidence = item["confidence"]
        if not all(isinstance(value, str) for value in (subject, predicate, obj, evidence)):
            raise ValueError("relation text fields must be strings")
        if not (1 <= len(subject) <= 120 and 1 <= len(obj) <= 120 and 1 <= len(evidence) <= 500):
            raise ValueError("invalid relation text length")
        if predicate not in allowed or isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
            raise ValueError("invalid relation predicate or confidence")
        if not all(_appears_as_phrase(value, source) for value in (subject, obj, evidence)):
            raise ValueError("relation is not grounded in the source claim")
        output.append({"subject": subject, "predicate": predicate, "object": obj,
                       "evidence": evidence, "confidence": float(confidence)})
    return output
