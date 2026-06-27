"""
memory_wiki_collapse.py — Cross-source salience ranking for memory-wiki.
Adapted from Memory OS (ClaudioDrews/memory-os) icarus/collapse.py, MIT License.

Unifies recall candidates from multiple sources (memory_wiki_query, knowledge_search,
distill_pack_context) into a single salience-ranked survivor list with Hebbian
cross-source corroboration amplification.

Pure functions, zero dependencies, ~15KB. No Docker/Redis/Qdrant required.
"""

from __future__ import annotations

import re
from typing import Iterable

__all__ = [
    "tokenize", "salience", "score_all", "collapse",
    "DEFAULTS", "SOURCE_PRIOR",
]

# ── Stopwords (English + Russian) ───────────────────────────────────────
_STOPWORDS = frozenset(
    "the a an is was are to of in for on with it and or not i you can do this "
    "that what how please help me my your we our they them then than over such "
    "be been being have has had will would could should about into only also "
    "just like very from at as by if"
    " и в не на я мы ты он она оно они что как где когда "
    "по к с от из за до для без под над или но а также это "
    "быть был была были будет буду есть нет уже ещё чтобы если может могу "
    "меня мне мной тебя тобой себя себе собой нас нам нами вас вам вами".split()
)

# ── Per-source priors (mild nudge, breaks ties only) ───────────────────
SOURCE_PRIOR = {
    "memory-wiki": 1.15,   # durable, curated claims (strongest)
    "knowledge_search": 1.05,  # semantic KB
    "distill": 1.00,          # distilled context capsules
    "session": 1.00,          # prior conversation
    "default": 0.95,
}

DEFAULTS = {
    "budget": 6,             # max survivors injected across ALL sources
    "prune_ratio": 0.35,     # keep candidates with salience >= ratio * max_salience
    "dup_overlap": 0.82,     # token-overlap above this vs a kept survivor => drop
    "overlap_weight": 0.55,  # weight of query-overlap vs base score in salience
    "rank_decay": 0.85,      # geometric decay applied per within-source rank
    # Hebbian cross-source amplify:
    "corroboration_overlap": 0.50,  # cross-source token-overlap that counts as agreement
    "amplify_gain": 0.15,    # salience boost per corroborating other-source candidate
    "amplify_cap": 0.50,     # max total boost fraction (caps runaway amplification)
}

# ── Russian translit helper (regex, handles multi-char mappings) ──────
_RU_MAP = {
    "щ": "shch", "ш": "sh", "ч": "ch", "ц": "ts", "ю": "yu", "я": "ya",
    "ё": "yo", "ж": "zh", "х": "kh",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "ы": "y", "ъ": "", "ь": "", "э": "e",
}
_RU_RE = re.compile("|".join(re.escape(k) for k in sorted(_RU_MAP, key=len, reverse=True)))

def _transliterate_ru(text: str) -> str:
    """Transliterate Cyrillic to Latin for token overlap. Keeps original too."""
    return _RU_RE.sub(lambda m: _RU_MAP[m.group()], text.lower())


def tokenize(text: str) -> set:
    """Lowercase alphanumeric tokens, minus stopwords. Handles mixed EN/RU."""
    if not text:
        return set()
    # Lowercase
    t = str(text).lower()
    # Transliterate RU → EN for cross-language matching
    t_ru = _transliterate_ru(t)
    # Extract alphanumeric tokens from both
    words = set(re.findall(r"[a-z0-9]+", t))
    words |= set(re.findall(r"[a-z0-9]+", t_ru))
    return words - _STOPWORDS


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _overlap(a: set, b: set) -> float:
    """Containment overlap: |a∩b| / min(|a|,|b|). 0 if either is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / (min(len(a), len(b)) or 1)


def salience(candidate: dict, query_tokens: set, *,
             overlap_weight: float = DEFAULTS["overlap_weight"],
             rank_decay: float = DEFAULTS["rank_decay"]) -> float:
    """Unified base salience for one candidate, in [0, ~1.2] (pre-amplify).

    Combines query-token overlap, base score (confidence when present;
    neutral prior otherwise), within-source rank decay, and a mild per-source
    prior. Candidate keys: ``text``, ``score`` (float|None), ``rank`` (int, 0-based),
    ``source``.
    """
    text_tokens = tokenize(candidate.get("text", ""))
    overlap = (len(query_tokens & text_tokens) / len(query_tokens)) if query_tokens else 0.0

    score = candidate.get("score")
    base = _clamp01(float(score)) if score is not None else 0.6

    sw = _clamp01(overlap_weight)
    blended = sw * overlap + (1.0 - sw) * base

    rank = int(candidate.get("rank", 0) or 0)
    decay = rank_decay ** max(rank, 0)

    prior = SOURCE_PRIOR.get(candidate.get("source", ""), SOURCE_PRIOR["default"])
    return blended * decay * prior


def score_all(candidates: Iterable[dict], query_tokens: set, *,
              overlap_weight: float = DEFAULTS["overlap_weight"],
              rank_decay: float = DEFAULTS["rank_decay"],
              corroboration_overlap: float = DEFAULTS["corroboration_overlap"],
              amplify_gain: float = DEFAULTS["amplify_gain"],
              amplify_cap: float = DEFAULTS["amplify_cap"]) -> list:
    """Score every candidate with base salience + Hebbian cross-source amplify.

    Returns list of dicts with: ``base`` (pre-amplify), ``corroboration`` (count of
    OTHER-source text-matching candidates), ``salience`` (base * (1+boost)),
    ``candidate`` (the original dict). O(n²) in pool size — trivial for typical
    recall sets (dozens).
    """
    pool = [c for c in candidates if isinstance(c, dict)]
    toks = [tokenize(c.get("text", "")) for c in pool]
    bases = [salience(c, query_tokens,
                      overlap_weight=overlap_weight,
                      rank_decay=rank_decay) for c in pool]

    out = []
    for i, c in enumerate(pool):
        src = c.get("source")
        corro = 0
        if toks[i]:
            for j, c2 in enumerate(pool):
                if i == j or c2.get("source") == src:
                    continue  # Hebbian agreement is CROSS-source only
                if _overlap(toks[i], toks[j]) >= corroboration_overlap:
                    corro += 1
        # Attenuate corroboration by query-local relevance:
        # a globally-important fact in many sources should not get full
        # amplification when the query is only tangential.
        boost = min(corro * amplify_gain * bases[i], amplify_cap)
        out.append({
            "base": bases[i],
            "corroboration": corro,
            "salience": bases[i] * (1.0 + boost),
            "candidate": c,
        })
    return out


def collapse(candidates: Iterable[dict], query_tokens: set, *,
             budget: int = DEFAULTS["budget"],
             prune_ratio: float = DEFAULTS["prune_ratio"],
             dup_overlap: float = DEFAULTS["dup_overlap"],
             overlap_weight: float = DEFAULTS["overlap_weight"],
             rank_decay: float = DEFAULTS["rank_decay"],
             corroboration_overlap: float = DEFAULTS["corroboration_overlap"],
             amplify_gain: float = DEFAULTS["amplify_gain"],
             amplify_cap: float = DEFAULTS["amplify_cap"]) -> list:
    """Collapse a unified candidate pool to a salience-ranked survivor list.

    Non-bijunctive: weak paths pruned relative to strongest (not absolute floor).
    Hebbian: cross-source agreement amplifies salience — a fact two layers both
    surfaced outranks a lone strong hit. Dedup: near-duplicate suppression.

    Returns surviving candidates, strongest first, annotated with ``_salience``
    and ``_corroboration``. Length ≤ budget. Pure function.
    """
    if budget <= 0:
        return []
    scored = score_all(candidates, query_tokens,
                       overlap_weight=overlap_weight, rank_decay=rank_decay,
                       corroboration_overlap=corroboration_overlap,
                       amplify_gain=amplify_gain, amplify_cap=amplify_cap)
    if not scored:
        return []

    max_s = max((r["salience"] for r in scored), default=0.0)

    # PRUNE: relative floor
    floor = max_s * prune_ratio
    kept = [r for r in scored if r["salience"] >= floor]

    # AMPLIFY: strongest first, stable for equal salience
    kept.sort(key=lambda r: r["salience"], reverse=True)

    # Near-duplicate suppression
    survivors: list = []
    survivor_tokens: list = []
    for r in kept:
        if len(survivors) >= budget:
            break
        ctoks = tokenize(r["candidate"].get("text", ""))
        if any(_overlap(ctoks, st) >= dup_overlap for st in survivor_tokens):
            continue
        annotated = dict(r["candidate"])
        annotated["_salience"] = round(r["salience"], 4)
        annotated["_corroboration"] = r["corroboration"]
        survivors.append(annotated)
        survivor_tokens.append(ctoks)

    return survivors


# ── Convenience: collapse from memory-wiki + knowledge_search + distill ──

def memory_context_collapse(
    query: str,
    memory_wiki_hits: list | None = None,
    knowledge_hits: list | None = None,
    distill_hits: list | None = None,
    budget: int = 6,
    **kwargs,
) -> list:
    """Collapse memory-wiki, knowledge_search, and distill results for a query.

    Args:
        query: The user query / task description
        memory_wiki_hits: list of {text, score, source="memory-wiki"}
        knowledge_hits: list of {text, score, source="knowledge_search"}
        distill_hits: list of {text, score, source="distill"}
        budget: max survivors to return
        **kwargs: override DEFAULTS (e.g. prune_ratio=0.3)

    Returns:
        Salience-ranked survivor list, strongest first
    """
    candidates = []
    for rank, hit in enumerate(memory_wiki_hits or []):
        candidates.append({**hit, "source": "memory-wiki", "rank": rank})
    for rank, hit in enumerate(knowledge_hits or []):
        candidates.append({**hit, "source": "knowledge_search", "rank": rank})
    for rank, hit in enumerate(distill_hits or []):
        candidates.append({**hit, "source": "distill", "rank": rank})

    qt = tokenize(query)
    return collapse(candidates, qt, budget=budget, **kwargs)
