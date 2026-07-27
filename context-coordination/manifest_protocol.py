"""Coverage Manifest Protocol v2.0 — P1 deduplication between Code Shrinker and Memory Wiki.

Code Shrinker publishes a coverage_manifest of symbols/files/diagnostics it has already
injected into context. Memory Wiki classifies its claims against this manifest to avoid
re-injecting semantic duplicates of current code state.

Claims are NEVER deleted — only classified. All 88 tools remain fully accessible.
"""

import hashlib, json, time, re
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

MAX_COVERAGE_ENTRIES = 5000
MAX_COVERAGE_STRING = 2048

# ═══════════════════════════════════════════════════════════════
# PROTOCOL V2: Coverage Manifest (Code Shrinker → Memory Wiki)
# ═══════════════════════════════════════════════════════════════

class CoverageKind(Enum):
    EXACT_SOURCE = "exact_source"
    CONTRACT = "contract"
    DIAGNOSTIC = "diagnostic"
    TEST = "test"
    PROJECT_MAP = "project_map"
    CALL_GRAPH = "call_graph"

class ClaimClass(Enum):
    NOVEL = "novel"             # Знание, которого нет в Code Shrinker — включается
    SUPPORTING = "supporting"   # Подтверждает код + причинная связь — включается компактно
    DUPLICATE = "duplicate"     # Только пересказывает переданный код — не передаётся повторно
    STALE = "stale"             # Относится к предыдущей ревизии символа — не включается
    CONFLICTING = "conflicting" # Противоречие между старым знанием и текущим кодом — обязательно

@dataclass
class CoverageEntry:
    kind: str
    file_path: Optional[str] = None
    symbol_id: Optional[str] = None
    revision: Optional[str] = None
    content_hash: Optional[str] = None
    diagnostic_hash: Optional[str] = None
    token_count: int = 0
    hash_algorithm: str = "sha256"
    canonicalization: str = "utf8-raw"
    content_kind: str = ""

@dataclass
class CoverageManifest:
    protocol_version: int = 2
    turn_id: str = ""
    packet_id: str = ""
    repository_id: str = ""
    commit_sha: str = ""
    covered: List[CoverageEntry] = field(default_factory=list)
    created_at: int = 0
    phase_sep_version: str = "2"
    
    def to_dict(self) -> dict:
        return {
            "protocol_version": self.protocol_version,
            "turn_id": self.turn_id,
            "packet_id": self.packet_id,
            "repository_id": self.repository_id,
            "commit_sha": self.commit_sha,
            "covered": [asdict(c) for c in self.covered],
            "created_at": self.created_at,
            "phase_sep_version": self.phase_sep_version
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> 'CoverageManifest':
        if not isinstance(d, dict):
            raise ValueError("coverage_manifest must be an object")
        allowed = {
            "kind", "file_path", "symbol_id", "revision", "content_hash",
            "diagnostic_hash", "token_count", "hash_algorithm",
            "canonicalization", "content_kind",
        }
        raw_entries = d.get("covered", []) or []
        if not isinstance(raw_entries, list):
            raise ValueError("coverage_manifest.covered must be an array")
        if len(raw_entries) > MAX_COVERAGE_ENTRIES:
            raise ValueError(
                f"coverage_manifest.covered exceeds {MAX_COVERAGE_ENTRIES} entries"
            )
        entries = []
        for raw in raw_entries:
            if not isinstance(raw, dict):
                raise ValueError("coverage_manifest.covered entries must be objects")
            item = {k: raw[k] for k in allowed if k in raw}
            if not str(item.get("kind") or "").strip():
                raise ValueError("coverage entry kind is required")
            for key in (
                "kind", "file_path", "symbol_id", "revision", "content_hash",
                "diagnostic_hash", "hash_algorithm", "canonicalization", "content_kind",
            ):
                if key in item and item[key] is not None:
                    value = str(item[key])
                    if len(value) > MAX_COVERAGE_STRING:
                        raise ValueError(f"coverage entry {key} is too long")
                    item[key] = value
            try:
                item["token_count"] = max(0, min(int(item.get("token_count", 0) or 0), 10_000_000))
            except (TypeError, ValueError) as exc:
                raise ValueError("coverage entry token_count must be an integer") from exc
            entries.append(CoverageEntry(**item))
        return cls(
            protocol_version=int(d.get("protocol_version", 1) or 1),
            turn_id=str(d.get("turn_id", "") or ""),
            packet_id=str(d.get("packet_id", "") or ""),
            repository_id=str(d.get("repository_id", "") or "").strip(),
            commit_sha=str(d.get("commit_sha", "") or ""),
            covered=entries,
            created_at=int(d.get("created_at", 0) or 0),
            phase_sep_version=str(d.get("phase_sep_version", "1") or "1"),
        )

# ═══════════════════════════════════════════════════════════════
# CLASSIFICATION ENGINE (Memory Wiki)
# ═══════════════════════════════════════════════════════════════

@dataclass
class ClassifiedClaim:
    claim_id: str
    classification: ClaimClass
    reason: str = ""
    covered_by: str = ""         # symbol_id@revision для DUPLICATE
    current_revision: str = ""   # для STALE/CONFLICTING
    estimated_tokens: int = 0
    summary: str = ""            # компактный вывод для SUPPORTING
    
    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "classification": self.classification.value,
            "reason": self.reason,
            "covered_by": self.covered_by,
            "current_revision": self.current_revision,
            "estimated_tokens": self.estimated_tokens,
            "summary": self.summary
        }

@dataclass
class SuppressionManifest:
    protocol_version: int = 2
    memory_pack_id: str = ""
    included_claim_ids: List[str] = field(default_factory=list)
    suppressed: List[ClassifiedClaim] = field(default_factory=list)
    conflicts: List[ClassifiedClaim] = field(default_factory=list)
    total_saved_tokens: int = 0
    created_at: int = 0
    
    def to_dict(self) -> dict:
        return {
            "protocol_version": self.protocol_version,
            "memory_pack_id": self.memory_pack_id,
            "included_claim_ids": self.included_claim_ids,
            "suppressed": [c.to_dict() for c in self.suppressed],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "total_saved_tokens": self.total_saved_tokens,
            "created_at": self.created_at
        }

def canonical_sha256(value: Any) -> str:
    value = str(value or "").strip().lower()
    if value.startswith("sha256:"):
        value = value[7:]
    return value if re.fullmatch(r"[0-9a-f]{64}", value) else ""


def canonical_repo_path(value: Any) -> str:
    import posixpath
    import unicodedata
    raw = unicodedata.normalize("NFC", str(value or "").strip()).replace("\\", "/")
    if not raw:
        return ""
    normalized = posixpath.normpath(raw)
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if (
        not normalized or normalized in {".", ".."}
        or normalized.startswith("../") or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
    ):
        return ""
    return normalized


NON_SUPPRESSIBLE_TYPES = {
    "decision", "constraint", "known_failure", "patch_outcome",
    "security", "user_requirement", "compatibility_requirement",
    "architecture_decision", "api_contract", "breaking_change"
}

class ClassificationEngine:
    """Classifies Memory Wiki claims against a Code Shrinker coverage manifest."""
    
    def classify_claims(
        self,
        claims: List[dict],
        coverage: CoverageManifest,
        repository_id: str = ""
    ) -> SuppressionManifest:
        """Classify each claim as NOVEL/SUPPORTING/DUPLICATE/STALE/CONFLICTING."""
        
        expected_repo = str(repository_id or "").strip()
        manifest_repo = str(coverage.repository_id or "").strip()
        if coverage.covered and not manifest_repo:
            raise ValueError("coverage repository_id is required when covered entries are present")
        if expected_repo and not manifest_repo:
            raise ValueError("coverage repository_id is required")
        if expected_repo and manifest_repo and expected_repo != manifest_repo:
            raise ValueError(
                f"coverage repository mismatch: {manifest_repo} != {expected_repo}"
            )
        included = []
        suppressed = []
        conflicts = []
        
        # A symbol may have both exact-source and contract coverage. Keep all
        # entries so the later contract cannot overwrite the exact source hash.
        covered_symbols: Dict[str, List[dict]] = {}
        covered_files = set()
        for c in coverage.covered:
            if c.symbol_id:
                covered_symbols.setdefault(c.symbol_id, []).append({
                    "revision": c.revision or "",
                    "content_hash": canonical_sha256(c.content_hash),
                    "kind": c.kind,
                    "hash_algorithm": c.hash_algorithm,
                    "canonicalization": c.canonicalization,
                    "content_kind": c.content_kind,
                })
            canonical_file = canonical_repo_path(c.file_path)
            if canonical_file:
                covered_files.add(canonical_file)

        effective_repo = expected_repo or manifest_repo or ""
        
        for claim in claims:
            cid = claim.get("id", "")
            claim_repo = (claim.get("repository_id") or "").strip()
            
            # Code memory from another repository must never enter this pack.
            if effective_repo and claim_repo and claim_repo != effective_repo:
                suppressed.append(ClassifiedClaim(
                    claim_id=cid,
                    classification=ClaimClass.STALE,
                    reason="foreign_repository",
                    covered_by=effective_repo,
                    estimated_tokens=len(str(claim.get("claim", ""))) // 3,
                ))
                continue
            claim_text = str(claim.get("claim", claim.get("text", "")))
            claim_repo = claim.get("repository_id", "")
            claim_symbol = claim.get("symbol_id", "")
            claim_revision = claim.get("symbol_revision", "")
            claim_file = canonical_repo_path(claim.get("file_path", ""))
            claim_type = claim.get("claim_type", "")
            
            if effective_repo and claim_type == "code_claim" and not claim_repo:
                suppressed.append(ClassifiedClaim(
                    claim_id=cid,
                    classification=ClaimClass.STALE,
                    reason="missing_repository_id",
                    covered_by=effective_repo,
                    estimated_tokens=len(claim_text) // 3,
                ))
                continue

            # Only classify code-linked claims against coverage manifest
            if claim_type != "code_claim" or not claim_symbol:
                # Non-code claims are always NOVEL
                included.append(cid)
                continue
            
            # Check: does this claim's symbol overlap with covered symbols?
            if claim_symbol in covered_symbols:
                entries = covered_symbols[claim_symbol]
                claim_hash = canonical_sha256(claim.get("content_hash", ""))
                # Exact-source hash wins; otherwise prefer matching revision,
                # then exact-source, then the first available entry.
                cov = next((e for e in entries
                            if claim_hash and e["kind"] == "exact_source"
                            and e["content_hash"] == claim_hash), None)
                if cov is None:
                    cov = next((e for e in entries
                                if claim_revision and e["revision"] == claim_revision), None)
                if cov is None:
                    cov = next((e for e in entries if e["kind"] == "exact_source"), entries[0])
                cov_rev = cov["revision"]
                
                # Never suppress valuable claim types
                if claim.get("claim_type","") in NON_SUPPRESSIBLE_TYPES:
                    included.append(cid)
                    continue
                
                # Same revision, same symbol → check hash + supporting info
                if claim_revision and cov_rev and claim_revision == cov_rev:
                    # Exact content hash match → true duplicate
                    claim_hash = canonical_sha256(claim.get("content_hash", ""))
                    cov_hash = canonical_sha256(cov.get("content_hash", ""))
                    hash_compatible = (
                        coverage.protocol_version >= 2
                        and cov.get("kind") == "exact_source"
                        and str(cov.get("hash_algorithm", "")).lower() == "sha256"
                        and str(cov.get("canonicalization", "")) == "utf8-raw"
                        and str(cov.get("content_kind", "")) == "source"
                    )
                    if hash_compatible and claim_hash and cov_hash and claim_hash == cov_hash:
                        suppressed.append(ClassifiedClaim(
                            claim_id=cid,
                            classification=ClaimClass.DUPLICATE,
                            reason="exact_content_hash_match",
                            covered_by=f"{claim_symbol}@{cov_rev}",
                            estimated_tokens=len(claim_text)//3
                        ))
                        continue
                    # Same revision is not proof of semantic duplication. Without an
                    # exact compatible content hash, preserve the claim to avoid losing
                    # rationale, platform constraints or security findings.
                    included.append(cid)
                    continue
                
                # Different revision → STALE or CONFLICTING
                if claim_revision and cov_rev and claim_revision != cov_rev:
                    # Check for conflict signals in claim
                    conflict_keywords = ["no longer", "changed", "now uses", "instead of",
                                         "заменён", "перешёл", "больше не", "deprecated",
                                         "breaking change", "atomic", "transaction"]
                    is_conflicting = any(kw in claim_text.lower() for kw in conflict_keywords)
                    
                    if is_conflicting:
                        conflicts.append(ClassifiedClaim(
                            claim_id=cid,
                            classification=ClaimClass.CONFLICTING,
                            reason="revision_mismatch_with_conflict_signal",
                            current_revision=cov_rev,
                            estimated_tokens=len(claim_text) // 3,
                            summary=claim_text[:200]
                        ))
                        # Conflicts are ALWAYS included
                        included.append(cid)
                        continue
                    else:
                        suppressed.append(ClassifiedClaim(
                            claim_id=cid,
                            classification=ClaimClass.STALE,
                            reason=f"claim_revision_{claim_revision}_vs_current_{cov_rev}",
                            current_revision=cov_rev,
                            estimated_tokens=len(claim_text) // 3
                        ))
                        continue
            
            # Check: does this claim's file overlap with covered files?
            if claim_file and claim_file in covered_files:
                # File-level overlap alone → SUPPORTING (not DUPLICATE)
                # May contain multi-symbol constraints, race conditions, or platform specifics
                included.append(cid)
                continue
            
            # No overlap → NOVEL
            included.append(cid)
        
        total_saved = sum(s.estimated_tokens for s in suppressed)
        
        return SuppressionManifest(
            memory_pack_id=f"mem-{int(time.time())}",
            included_claim_ids=included,
            suppressed=suppressed,
            conflicts=conflicts,
            total_saved_tokens=total_saved,
            created_at=int(time.time())
        )
    
    def _has_supporting_info(self, text: str) -> bool:
        """Check if claim contains causal/contextual info beyond code description."""
        signals = ["because", "caused", "resulted in", "to avoid", "required for",
                   "потому что", "привело к", "чтобы избежать", "необходимо для", "из-за", "по причине", "во избежание",
                   "previous attempt", "known failure", "decision", "constraint",
                   "предыдущая попытка", "решение", "ограничение"]
        return any(sig in text.lower() for sig in signals)

# ═══════════════════════════════════════════════════════════════
# PROTOCOL CACHE — SQLite-based content-addressed store (P2 readiness)
# ═══════════════════════════════════════════════════════════════

class ManifestCache:
    """SQLite cache for coverage manifests indexed by SHA-256 key."""
    
    def __init__(self, db_path: str = ""):
        import sqlite3
        path = db_path or "/root/.hermes/context-coordination/manifest_cache.db"
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS coverage_cache (
            cache_key TEXT PRIMARY KEY,
            manifest_json TEXT NOT NULL,
            packet_id TEXT,
            created_at INTEGER NOT NULL,
            hit_count INTEGER DEFAULT 1,
            last_hit INTEGER NOT NULL
        )""")
        self.db.commit()
    
    def get_key(self, repository_id: str, commit_sha: str, target_symbols: list, task_type: str) -> str:
        """Build deterministic SHA-256 cache key."""
        raw = json.dumps(
            {
                "repository_id": str(repository_id or ""),
                "commit_sha": str(commit_sha or ""),
                "target_symbols": sorted(str(x) for x in (target_symbols or [])),
                "task_type": str(task_type or ""),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    
    def get(self, cache_key: str) -> Optional[CoverageManifest]:
        row = self.db.execute(
            "SELECT manifest_json, packet_id FROM coverage_cache WHERE cache_key=?",
            (cache_key,)
        ).fetchone()
        if row:
            self.db.execute(
                "UPDATE coverage_cache SET hit_count=hit_count+1, last_hit=? WHERE cache_key=?",
                (int(time.time()), cache_key)
            )
            self.db.commit()
            return CoverageManifest.from_dict(json.loads(row[0]))
        return None
    
    def put(self, cache_key: str, manifest: CoverageManifest):
        self.db.execute(
            "INSERT OR REPLACE INTO coverage_cache(cache_key, manifest_json, packet_id, created_at, hit_count, last_hit) VALUES(?,?,?,?,?,?)",
            (cache_key, json.dumps(manifest.to_dict(), ensure_ascii=False), manifest.packet_id, int(time.time()), 1, int(time.time()))
        )
        self.db.commit()

# Module init
# Manifest Protocol v2.0 loaded (silent — MCP stdio safe)
