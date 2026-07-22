#!/usr/bin/env python3
"""memory-wiki collapse — cross-source claim collapse/deduplication."""
from __future__ import annotations
import re, hashlib
from collections import Counter
from typing import Any, Dict, List, Optional, Set

_STOP = frozenset(["a","an","the","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","will","would","shall","should",
    "may","might","must","can","could","of","in","to","for","on","with",
    "at","by","from","as","into","through","during","before","after",
    "above","below","between","under","and","but","or","not","no","nor",
    "so","if","then","else","when","where","why","how","all","each",
    "every","both","few","more","most","other","some","such","only",
    "own","same","very","just","than","too","also","now","here","there"])
_WORD_RE = re.compile(r'[a-z0-9]+')

def collapse_tokenize(text: str) -> Set[str]:
    """Tokenize text to a set of lowercase words."""
    return {w.group(0) for w in _WORD_RE.finditer(text.lower()) if len(w.group(0))>5}

def _simhash(text: str, bits: int = 64) -> int:
    """SimHash fingerprint for near-duplicate detection."""
    tokens = list(_WORD_RE.findall(text.lower()))
    if not tokens: return 0
    v = [0] * bits
    for tok in tokens:
        h = int(hashlib.md5(tok.encode()).hexdigest()[:16], 16)
        for i in range(bits):
            if h & (1 << i): v[i] += 1
            else: v[i] -= 1
    result = 0
    for i in range(bits):
        if v[i] > 0: result |= (1 << i)
    return result

def _load_claims(cursor, topic: Optional[str] = None, limit: int = 500, exclude_id: Optional[str] = None):
    """Load active claims for comparison."""
    sql = "SELECT id, normalized_claim, claim, topic, source FROM claims WHERE status='active' AND normalized_claim IS NOT NULL"
    params = []
    if topic:
        sql += " AND topic=?"
        params.append(topic)
    if exclude_id:
        sql += " AND id!=?"
        params.append(exclude_id)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    return cursor.execute(sql, params).fetchall()

def memory_context_collapse(query: str, memory_wiki_hits=None, knowledge_hits=None, distill_hits=None, budget=6, **kw):
    """Cross-source collapse: deduplicate and rank items for context injection."""
    all_items: List[Dict[str, Any]] = []
    for source, items in [("mw",memory_wiki_hits or []),("kb",knowledge_hits or []),("dt",distill_hits or [])]:
        for item in items:
            all_items.append({"source":source,"item":item,"id":item.get("id","") if isinstance(item,dict) else str(item)})
    seen = set()
    unique = []
    for entry in all_items:
        key = entry["id"] or hashlib.md5(str(entry["item"]).encode()).hexdigest()[:12]
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    scored = []
    for entry in unique:
        source_count = sum(1 for e in unique if e["source"]==entry["source"])
        cross_source = sum(1 for e in unique if e["source"]!=entry["source"])
        salience = float(entry["item"].get("salience",0.5)) if isinstance(entry["item"],dict) else 0.5
        score = salience * (1.0 + 0.3 * min(cross_source,3))
        scored.append((score, entry))
    scored.sort(key=lambda x: -x[0])
    return [entry for _,entry in scored[:budget]]
