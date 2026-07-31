#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive legacy Memory Wiki .db files without deleting them")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--apply", action="store_true", help="Move candidates into a timestamped archive directory")
    parser.add_argument("--include-recent", action="store_true", help="Allow files modified less than 24 hours ago")
    args = parser.parse_args()

    home = Path(args.hermes_home).expanduser().resolve()
    root = home / "memory-wiki"
    active_names = {
        "memory_wiki.sqlite3",
        "memory_wiki.sqlite3-wal",
        "memory_wiki.sqlite3-shm",
    }
    now = time.time()
    candidates = []
    for path in sorted(root.glob("memory_wiki.db*")):
        if not path.is_file() or path.name in active_names:
            continue
        age = max(0, int(now - path.stat().st_mtime))
        if age < 86400 and not args.include_recent:
            continue
        candidates.append({
            "path": str(path),
            "name": path.name,
            "size": path.stat().st_size,
            "mtime": int(path.stat().st_mtime),
            "age_seconds": age,
            "sha256": sha256(path),
        })

    result = {
        "root": str(root),
        "apply": args.apply,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    if not args.apply or not candidates:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive = root / "legacy-db-archive" / stamp
    archive.mkdir(parents=True, exist_ok=False)
    moved = []
    for item in candidates:
        src = Path(item["path"])
        dst = archive / src.name
        shutil.move(str(src), str(dst))
        moved.append({**item, "archived_to": str(dst)})
    manifest = archive / "MANIFEST.json"
    manifest.write_text(json.dumps({"created_at": stamp, "files": moved}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result.update({"archive": str(archive), "moved": moved, "manifest": str(manifest)})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
