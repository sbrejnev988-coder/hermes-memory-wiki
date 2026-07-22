#!/usr/bin/env python3
"""memory-wiki decay — ACT-R style memory decay scanner."""
from __future__ import annotations
import math, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_DB = Path(__file__).resolve().parent / "memory_wiki.sqlite3"

def _days_since(ts: int) -> float:
    return max(0.0, (int(time.time()) - ts) / 86400.0)

def _decay_factor(days: float, confidence: float = 0.7, salience: float = 0.7, access_count: int = 0) -> float:
    """ACT-R decay: faster for low-confidence, low-salience, unused claims."""
    quality = confidence * salience
    decay_rate = 0.015 / max(0.3, quality)
    access_boost = math.log1p(access_count) * 0.05
    return max(0.0, 1.0 - decay_rate * days + access_boost)

def scan_decay(db_path=None, threshold=0.15):
    """Scan claims and return those below decay threshold."""
    db = sqlite3.connect(str(db_path or DEFAULT_DB))
    db.row_factory = sqlite3.Row
    rows = db.execute("""
        SELECT id, topic, confidence, salience, access_count, status, updated_at, freshness_at
        FROM claims WHERE status='active'
    """).fetchall()
    results = []
    for r in rows:
        days = _days_since(int(r["freshness_at"] or r["updated_at"] or 0))
        factor = _decay_factor(days, float(r["confidence"] or 0.7), float(r["salience"] or 0.7), int(r["access_count"] or 0))
        if factor < threshold:
            results.append(dict(r, days=round(days,1), decay=round(factor,4)))
    db.close()
    return sorted(results, key=lambda x: x["decay"])

def archive_stale_claims(db_path=None, threshold=0.05, dry_run=True):
    """Archive claims below decay threshold."""
    db = sqlite3.connect(str(db_path or DEFAULT_DB))
    stale = scan_decay(db_path, threshold)
    if not dry_run:
        ids = [s["id"] for s in stale]
        if ids:
            db.execute(f"UPDATE claims SET status='archived' WHERE id IN ({','.join('?'*len(ids))})", ids)
            db.commit()
    db.close()
    return {"stale": len(stale), "dry_run": dry_run, "ids": [s["id"] for s in stale[:50]]}

def get_decay_stats(db_path=None):
    """Get decay distribution stats."""
    db = sqlite3.connect(str(db_path or DEFAULT_DB))
    db.row_factory = sqlite3.Row
    rows = db.execute("""
        SELECT count(*) as total,
               avg(confidence) as avg_conf,
               avg(salience) as avg_sal,
               avg(access_count) as avg_access,
               max(freshness_at) as newest,
               min(freshness_at) as oldest
        FROM claims WHERE status='active'
    """).fetchone()
    db.close()
    return dict(rows)
