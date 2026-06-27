"""
memory_wiki_decay.py — Exponential decay scoring for memory-wiki claims.
Adapted from Memory OS (ClaudioDrews/memory-os) scripts/decay_scanner.py, MIT License.

Computes decay_score for claims based on age, confidence, and salience.
Pure SQLite-based — no Qdrant/Docker/Redis required.

Formula: decay_score = exp(-ln(2) * age_days / half_life)
  - high-confidence/high-salience claims → 180d half-life
  - medium → 90d
  - low → 30d

CLI usage:
  python3 memory_wiki_decay.py --dry-run
  python3 memory_wiki_decay.py --threshold 0.15 --archive
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

__all__ = [
    "calculate_decay_score",
    "scan_decay",
    "archive_stale_claims",
    "get_decay_stats",
]

# ── Config ──────────────────────────────────────────────────────────────
MEMORY_WIKI_DB = Path(os.environ.get(
    "MEMORY_WIKI_DB",
    os.path.expanduser("~/.hermes/memory-wiki/memory_wiki.db"),
))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def calculate_decay_score(
    last_accessed_at: str | None,
    confidence: float = 0.5,
    salience: float = 0.5,
) -> float:
    """Calculate exponential decay score for a claim.

    Args:
        last_accessed_at: ISO timestamp of last access
        confidence: Claim confidence (0-1, from memory-wiki)
        salience: Claim salience (0-1)

    Returns:
        Decay score: 1.0 = fresh, <0.05 = should be archived
    """
    if not last_accessed_at:
        return 0.0  # never accessed → fully decayed

    try:
        last = datetime.fromisoformat(last_accessed_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return 0.5  # invalid timestamp → neutral

    now = datetime.now(timezone.utc)
    age_days = max(0, (now - last).total_seconds() / 86400)

    # Half-life based on confidence × salience composite
    composite = confidence * salience
    if composite >= 0.7:
        half_life = 180   # very important → 6 months
    elif composite >= 0.4:
        half_life = 90    # medium → 3 months
    else:
        half_life = 30    # low → 1 month

    decay = math.exp(-math.log(2) * age_days / half_life)
    return decay


def scan_decay(db_path: str | None = None, threshold: float = 0.1) -> list[dict]:
    """Scan all active claims and compute decay scores.

    Args:
        db_path: Path to memory_wiki.db (default: MEMORY_WIKI_DB)
        threshold: Decay score below which claims are flagged

    Returns:
        List of {claim_id, claim, topic, decay_score, confidence, salience, age_days}
    """
    db = Path(db_path or MEMORY_WIKI_DB)
    if not db.exists():
        print(f"[decay] DB not found: {db}", file=sys.stderr)
        return []

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    try:
        # Get claims that aren't already archived
        rows = conn.execute("""
            SELECT
                id, claim, topic, confidence, salience,
                last_accessed_at, created_at
            FROM claims
            WHERE archived = 0 OR archived IS NULL
            ORDER BY confidence ASC, salience ASC
        """).fetchall()
    except sqlite3.OperationalError as e:
        # Table might not have these columns yet
        print(f"[decay] Schema error: {e}", file=sys.stderr)
        conn.close()
        return []
    finally:
        conn.close()

    results = []
    for r in rows:
        last_acc = r["last_accessed_at"] or r["created_at"]
        conf = float(r["confidence"] or 0.5)
        sal = float(r["salience"] or 0.5)

        decay = calculate_decay_score(last_acc, conf, sal)

        if decay < threshold:
            # Calculate age
            try:
                last_dt = datetime.fromisoformat(
                    (last_acc or "").replace("Z", "+00:00")
                )
                age_days = (datetime.now(timezone.utc) - last_dt).days
            except (ValueError, TypeError):
                age_days = 0

            results.append({
                "claim_id": r["id"],
                "claim": (r["claim"] or "")[:100],
                "topic": r["topic"] or "",
                "decay_score": round(decay, 4),
                "confidence": round(conf, 2),
                "salience": round(sal, 2),
                "age_days": age_days,
            })

    return results


def archive_stale_claims(
    db_path: str | None = None,
    threshold: float = 0.05,
    dry_run: bool = True,
) -> dict:
    """Archive claims with decay_score below threshold.

    Low-confidence (>90d old) + low-salience claims are candidates for archival.
    High-confidence claims (conf ≥ 0.7) are NEVER archived — only flagged for review.

    Args:
        threshold: Decay score below which to archive
        dry_run: If True, only report — don't modify

    Returns:
        {archived: N, alerted: N, skipped_high_conf: N, scanned: N}
    """
    db = Path(db_path or MEMORY_WIKI_DB)
    if not db.exists():
        return {"error": f"DB not found: {db}"}

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    stats = {"archived": 0, "alerted": 0, "skipped_high_conf": 0, "scanned": 0}

    try:
        rows = conn.execute("""
            SELECT id, claim, confidence, salience, last_accessed_at, created_at
            FROM claims
            WHERE archived = 0 OR archived IS NULL
        """).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return {"error": "Schema missing archived/last_accessed_at columns"}

    stats["scanned"] = len(rows)
    to_archive: list[str] = []
    alerts: list[dict] = []

    for r in rows:
        last_acc = r["last_accessed_at"] or r["created_at"]
        conf = float(r["confidence"] or 0.5)
        sal = float(r["salience"] or 0.5)
        decay = calculate_decay_score(last_acc, conf, sal)

        if decay >= threshold:
            continue

        # HIGH confidence protection: never auto-archive, only alert
        if conf >= 0.7:
            stats["alerted"] += 1
            alerts.append({
                "id": r["id"],
                "claim": (r["claim"] or "")[:80],
                "decay": round(decay, 4),
                "confidence": round(conf, 2),
                "reason": "high confidence + low decay — manual review recommended",
            })
            continue

        stats["archived"] += 1
        to_archive.append(r["id"])

    # Apply archival
    if not dry_run and to_archive:
        conn.execute("""
            UPDATE claims SET archived = 1 WHERE id IN ({})
        """.format(",".join("?" for _ in to_archive)), to_archive)
        conn.commit()

    conn.close()
    return {**stats, "alerts_detail": alerts[:10]}


def get_decay_stats(db_path: str | None = None) -> dict:
    """Get summary decay statistics for memory-wiki claims."""
    db = Path(db_path or MEMORY_WIKI_DB)
    if not db.exists():
        return {"error": f"DB not found: {db}"}

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    try:
        total = conn.execute("SELECT COUNT(*) as n FROM claims").fetchone()["n"]
        active = conn.execute(
            "SELECT COUNT(*) as n FROM claims WHERE archived = 0 OR archived IS NULL"
        ).fetchone()["n"]
        archived = conn.execute(
            "SELECT COUNT(*) as n FROM claims WHERE archived = 1"
        ).fetchone()["n"]
    except sqlite3.OperationalError:
        conn.close()
        return {"total": 0, "active": 0, "archived": 0, "note": "Schema migration needed"}

    conn.close()

    return {
        "total": total,
        "active": active,
        "archived": archived,
        "archival_rate": round(archived / max(total, 1) * 100, 1),
    }


# ── CLI ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Memory-Wiki Decay Scanner — exponential decay for claims"
    )
    parser.add_argument("--db", default=None, help="Path to memory_wiki.db")
    parser.add_argument("--threshold", type=float, default=0.15,
                       help="Decay score threshold (default: 0.15)")
    parser.add_argument("--archive", action="store_true",
                       help="Archive stale claims (default: dry-run only)")
    parser.add_argument("--dry-run", action="store_true", default=True,
                       help="Scan only, no modifications (default)")
    parser.add_argument("--stats", action="store_true",
                       help="Show decay statistics")
    parser.add_argument("--json", action="store_true",
                       help="Output as JSON")
    args = parser.parse_args()

    if args.stats:
        stats = get_decay_stats(args.db)
        if args.json:
            print(json.dumps(stats, indent=2, ensure_ascii=False))
        else:
            print(f"Total: {stats.get('total', 0)}")
            print(f"Active: {stats.get('active', 0)}")
            print(f"Archived: {stats.get('archived', 0)}")
            if stats.get("note"):
                print(f"Note: {stats['note']}")
        return

    dry_run = not args.archive

    candidates = scan_decay(args.db, args.threshold)
    if args.json:
        print(json.dumps(candidates, indent=2, ensure_ascii=False))
        return

    print(f"=== Memory-Wiki Decay Scanner ===")
    print(f"Threshold: {args.threshold} | Dry-run: {dry_run}")
    print(f"Stale candidates: {len(candidates)}")
    print()

    for c in candidates[:20]:
        print(f"  [{c['decay_score']:.4f}] {c['claim']}")
        print(f"       conf={c['confidence']} sal={c['salience']} age={c['age_days']}d")
        print()

    if dry_run and candidates:
        print(f"Use --archive to archive {len(candidates)} stale claims.")

    # Optionally archive
    if not dry_run:
        result = archive_stale_claims(args.db, args.threshold, dry_run=False)
        print(f"\nArchive result: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
