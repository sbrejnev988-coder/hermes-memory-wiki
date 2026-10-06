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
from pathlib import Path
from typing import Any

try:
    from .extractor import (
        ExtractionSettings, _codex_content, _lexical_sentence_spans, _negation_spans,
        _LEXICAL_DENIAL_RE, _lexical_assertions, _lexical_terms,
    )
except ImportError:  # pragma: no cover - standalone plugin loading
    from extractor import (
        ExtractionSettings, _codex_content, _lexical_sentence_spans, _negation_spans,
        _LEXICAL_DENIAL_RE, _lexical_assertions, _lexical_terms,
    )


def read_graph_extraction_settings(
    home: Path, *, model_override: str | None = None,
) -> ExtractionSettings | None:
    """Read graph-only owner YAML; absent section retains the explicit legacy route."""
    home = Path(home).expanduser().resolve()
    path = home / "config.yaml"
    if not path.exists():
        return None
    try:
        import hermes_yaml as yaml
    except ImportError:  # Standalone legacy installations.
        import yaml
    section = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    missing = object()
    for key in ("plugins", "entries", "memory-wiki", "settings", "graph_extraction"):
        if not isinstance(section, dict):
            raise ValueError("invalid graph extraction settings")
        section = section.get(key, missing)
        if section is missing:
            return None
    if not isinstance(section, dict) or set(section) - {
            "enabled", "provider", "model", "timeout", "reasoning_effort"}:
        raise ValueError("invalid graph extraction settings")
    section = dict(section)
    if model_override is not None:
        section["model"] = model_override
    settings = ExtractionSettings(home=home, max_tokens=700, **section)
    model_pattern = (r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}" if settings.provider == "openai-codex"
                     else r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}")
    if (type(settings.enabled) is not bool or settings.provider not in {"openai-codex", "openrouter"}
            or (settings.enabled and not {"provider", "model"} <= set(section))
            or not isinstance(settings.model, str) or not re.fullmatch(model_pattern, settings.model)
            or type(settings.timeout) not in {int, float} or not 1 <= settings.timeout <= 60
            or settings.reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}):
        raise ValueError("invalid graph extraction settings")
    return settings

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


def _relation_span_positive(text: str, lower: int, left: Any, verb: Any, right: Any) -> bool | None:
    """None means another lexical action/actor intervenes, not a grounded edge."""
    all_cues = "|".join(cue for cues in _PREDICATE_CUES.values() for cue in cues)
    prefix = text[left.end():verb.start()]
    gap = text[verb.end():right.start()]
    upper = next((end for start, end in _lexical_sentence_spans(text)
                  if start <= right.start() < end), len(text))
    tail = text[right.end():upper]
    if _LEXICAL_DENIAL_RE.search(tail) or re.search(
            r"(?:,\s*|\b(?:and|or|but|и|или|но)\s+)(?:not|never|не|ни)\s+(?:on\s+|на\s+)?"
            + re.escape(right.group()) + r"(?!\w)", tail, re.I):
        return False
    if re.search(all_cues, gap, re.I) or re.search(r"\b(?:but|however|но|зато)\b", gap, re.I):
        return None
    scope_start = lower
    before_subject = text[lower:left.start()]
    # An explicit subject immediately after a comma starts its own assertion.
    if before_subject.rstrip().endswith(','):
        scope_start = left.start()
    if re.search(all_cues, prefix, re.I):
        contrasts = list(re.finditer(r"\b(?:but(?:\s+also)?|however|но(?:\s+и)?|зато)\b", prefix, re.I))
        if not contrasts:
            return None  # and/or with shared negation is ambiguous: fail closed.
        contrast = contrasts[-1]
        bridge = prefix[contrast.end():].strip(' ,')
        if not re.fullmatch(
                r"(?:(?:do|does|did|is|are|was|were|can|cannot|not|never|only|also|"
                r"не|никогда|только|и|также)\s*)*", bridge, re.I):
            return None  # A different named subject is not inherited.
        scope_start = left.end() + contrast.end()
    return not _negation_spans(text[scope_start:right.end()])


def _grounded_relation_clause(
    subject: str, predicate: str, obj: str, evidence: str, *, source: str | None = None,
) -> bool:
    """Require actor/action/object to belong to the same lexical assertion.

    Every citation occurrence is checked against its actual source. Unknown
    bridges cannot borrow a verb or object from a different actor/assertion.
    """
    cues = _PREDICATE_CUES.get(predicate, ())
    if not cues or not evidence:
        return False
    text = evidence if source is None else source
    occurrences = list(re.finditer(re.escape(evidence), text, re.I))
    if not occurrences:
        return False
    subject_spans = list(re.finditer(r"(?<!\w)" + re.escape(subject) + r"(?!\w)", text, re.I))
    object_spans = list(re.finditer(r"(?<!\w)" + re.escape(obj) + r"(?!\w)", text, re.I))
    all_cues = "|".join(cue for values in _PREDICATE_CUES.values() for cue in values)
    protected = [match.span() for match in subject_spans + object_spans]
    assertions = _lexical_assertions(text, all_cues, protected)
    sentences = _lexical_sentence_spans(text, protected)
    target = _lexical_terms(obj)
    target_scopes = [(row['object_name'], row['qualifier']) for row in assertions
                     if row['object'] == target]
    for occurrence in occurrences:
        # Do not discard an uncertain/negative repetition of the same bound
        # edge in the cited sentence, including one outside a cropped quote.
        cited_scopes = [(a, b) for a, b in sentences
                        if a < occurrence.end() and occurrence.start() < b]
        for row in assertions:
            # Compare endpoint plus scope, not capitalization or name alone.
            same_object = (row['object'] == target
                           or any(name and (row['object'] == name
                                  or target == row['object_name']
                                  or (row['object_name'] == name
                                      and (row['qualifier'] == qualifier
                                           or not row['qualifier'] or not qualifier)))
                                  for name, qualifier in target_scopes))
            if (row['actor'] == _lexical_terms(subject) and same_object
                    and any(a <= row['action_start'] < b for a, b in cited_scopes)
                    and any(re.fullmatch(cue, text[row['action_start']:row['action_end']], re.I) for cue in cues)
                    and (row['negative'] is not False or row['residue'])):
                return False
        grounded = []
        for row in assertions:
            if (row['actor'] != _lexical_terms(subject) or row['object'] != _lexical_terms(obj)
                    or row['residue'] or row['negative'] is None
                    or not any(re.fullmatch(cue, text[row['action_start']:row['action_end']], re.I) for cue in cues)):
                continue
            left = next((match for match in reversed(subject_spans)
                         if occurrence.start() <= match.start() and match.end() <= row['action_start']), None)
            right = next((match for match in object_spans
                          if row['object_start'] <= match.start() < match.end() <= min(row['end'], occurrence.end())), None)
            if left is None or right is None:
                continue
            # Keep the established source-frame/denial refusal after binding.
            verb = next(match for match in re.finditer('(?:' + '|'.join(cues) + ')', text, re.I)
                        if match.start() == row['action_start'] and match.end() == row['action_end'])
            lower = next(start for start, end in sentences if start <= row['action_start'] < end)
            positive = _relation_span_positive(text, lower, left, verb, right)
            if positive is not None:
                grounded.append(row['negative'] is False and positive)
        if not grounded or not all(grounded):
            return False
    return True


def extract_relations(
    claim_text: str,
    *,
    endpoint: str,
    api_key: str,
    model: str,
    predicates: frozenset[str],
    timeout: float = 30.0,
    extraction_settings: ExtractionSettings | None = None,
) -> list[dict[str, Any]]:
    """Return up to eight strictly validated, text-grounded relation rows."""
    is_codex = extraction_settings is not None and extraction_settings.provider == "openai-codex"
    if not is_codex:
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
    if is_codex:
        content = _codex_content(extraction_settings, payload["messages"])
    else:
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
        if not _grounded_relation_clause(subject, predicate, obj, evidence, source=source):
            raise ValueError("relation endpoints and predicate are not grounded in one evidence clause")
        output.append({"subject": subject, "predicate": predicate, "object": obj,
                       "evidence": evidence, "confidence": float(confidence)})
    return output
