"""Explicit, source-bound relation extraction from one claim.

The provider gates this operation and owns persistence. This module only
calls the configured chat endpoint and validates candidate relations.
"""
from __future__ import annotations

import json
import ipaddress
import re
import urllib.parse
import urllib.request
from typing import Any

try:
    from .http_safety import urlopen_no_redirect as _urlopen_no_redirect
except ImportError:  # pragma: no cover - standalone plugin loading
    from http_safety import urlopen_no_redirect as _urlopen_no_redirect


def _appears_as_phrase(phrase: str, source: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", source, re.IGNORECASE))


_PREDICATE_CUES = {
    "owns": (r"\bowns?\b", r"\bpossesses?\b", r"\bвладе(?:ет|ют|ю)\b", r"\bпринадлежит\b"),
    "owned_by": (r"\bowned\s+by\b", r"\bbelongs?\s+to\b", r"\bпринадлежит\b"),
    "runs_on": (r"\bruns?\s+on\b", r"\bdeployed\s+on\b", r"\bработает\s+на\b", r"\bзапущен[ао]?\s+на\b"),
    "hosts": (r"\bhosts?\b", r"\bразмеща(?:ет|ют)\b", r"\bхостит\b"),
    "depends_on": (r"\bdepends?\s+on\b", r"\brequires?\b", r"\bзависит\s+от\b", r"\bтребует\b"),
    "required_by": (r"\brequired\s+by\b", r"\bneeded\s+by\b", r"\bтребуется\s+для\b"),
    "uses_provider": (r"\buses?\b", r"\busing\b", r"\bvia\b", r"\bprovider\b", r"\bиспользу(?:ет|ют|ю)\b", r"\bчерез\b"),
    "authenticated_by": (r"\bauthenticated\s+by\b", r"\bauthenticates?\s+(?:with|via)\b", r"\bвход\s+через\b", r"\bаутентифиц"),
    "replaces": (r"\breplaces?\b", r"\bsupersedes?\b", r"\bзаменя(?:ет|ют)\b"),
    "replaced_by": (r"\breplaced\s+by\b", r"\bsuperseded\s+by\b", r"\bзамен[её]н[ао]?\b"),
    "valid_until": (r"\bvalid\s+until\b", r"\bexpires?\b", r"\bдействует\s+до\b", r"\bистекает\b"),
    "supports": (r"\bsupports?\b", r"\benables?\b", r"\bподдержива(?:ет|ют)\b"),
    "contradicts": (r"\bcontradicts?\b", r"\bconflicts?\s+with\b", r"\bпротиворечит\b"),
}


def _grounded_relation_clause(subject: str, predicate: str, obj: str, evidence: str) -> bool:
    """Require ordered subject, predicate cue and object in one clause."""
    cues = _PREDICATE_CUES.get(predicate, ())
    if not cues:
        return False
    for clause in re.split(r"(?<=[.!?;])\s+|[\r\n]+", evidence):
        candidate = clause.strip()
        if not candidate:
            continue
        subject_spans = list(re.finditer(
            r"(?<!\w)" + re.escape(subject) + r"(?!\w)", candidate, re.IGNORECASE,
        ))
        object_spans = list(re.finditer(
            r"(?<!\w)" + re.escape(obj) + r"(?!\w)", candidate, re.IGNORECASE,
        ))
        for cue in cues:
            for verb in re.finditer(cue, candidate, re.IGNORECASE):
                if any(left.end() <= verb.start() and verb.end() <= right.start()
                       for left in subject_spans for right in object_spans):
                    return True
    return False


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
        _ = parsed_endpoint.port
        endpoint_host = parsed_endpoint.hostname
    except (TypeError, ValueError):
        raise ValueError("invalid graph extraction endpoint") from None
    normalized_host = str(endpoint_host or "").casefold().rstrip(".")
    loopback = normalized_host == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(normalized_host).is_loopback
        except ValueError:
            loopback = False
    allowed_https = parsed_endpoint.scheme == "https" and bool(endpoint_host)
    allowed_loopback = parsed_endpoint.scheme == "http" and loopback
    if (not (allowed_https or allowed_loopback)
            or parsed_endpoint.username is not None
            or parsed_endpoint.password is not None
            or bool(parsed_endpoint.query)
            or bool(parsed_endpoint.fragment)):
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
    with _urlopen_no_redirect(request, timeout=max(1.0, min(timeout, 60.0))) as response:
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
        if predicate not in allowed or isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not (0.65 <= confidence <= 1.0):
            raise ValueError("invalid relation predicate or confidence")
        if not all(_appears_as_phrase(value, source) for value in (subject, obj, evidence)):
            raise ValueError("relation is not grounded in the source claim")
        if not _grounded_relation_clause(subject, predicate, obj, evidence):
            raise ValueError("relation endpoints and predicate are not grounded in one evidence clause")
        output.append({"subject": subject, "predicate": predicate, "object": obj,
                       "evidence": evidence, "confidence": float(confidence)})
    return output
