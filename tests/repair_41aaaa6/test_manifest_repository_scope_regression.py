import importlib.util
from pathlib import Path


def load_protocol():
    root = Path(__file__).resolve().parents[2]
    path = root / "context-coordination" / "manifest_protocol.py"
    spec = importlib.util.spec_from_file_location("manifest_protocol_fixed", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_foreign_repository_code_claim_is_hard_excluded():
    m = load_protocol()
    coverage = m.CoverageManifest(repository_id="repo-A", covered=[])
    result = m.ClassificationEngine().classify_claims([{
        "id": "claim-B", "claim": "Implementation detail from repository B",
        "repository_id": "repo-B", "claim_type": "code_claim",
        "symbol_id": "sym_shared", "symbol_revision": "rev1",
    }], coverage)
    assert "claim-B" not in result.included_claim_ids
    assert {x.claim_id for x in result.suppressed} == {"claim-B"}
    assert result.suppressed[0].reason == "foreign_repository"


def test_exact_source_hash_wins_over_later_contract_entry():
    m = load_protocol()
    raw_hash = "A" * 64
    coverage = m.CoverageManifest(
        protocol_version=2,
        repository_id="repo-A",
        covered=[
            m.CoverageEntry(
                kind="exact_source", file_path="src/a.py", symbol_id="sym_shared",
                revision="rev1", content_hash=raw_hash.lower(),
                hash_algorithm="sha256", canonicalization="utf8-raw", content_kind="source",
            ),
            m.CoverageEntry(
                kind="contract", file_path="src/a.py", symbol_id="sym_shared",
                revision="rev1", content_hash="b" * 64,
            ),
        ],
    )
    result = m.ClassificationEngine().classify_claims([{
        "id": "claim-A", "claim": "Duplicate source claim", "repository_id": "repo-A",
        "claim_type": "code_claim", "symbol_id": "sym_shared", "symbol_revision": "rev1",
        "content_hash": "sha256:" + raw_hash,
    }], coverage)
    assert "claim-A" not in result.included_claim_ids
    assert result.suppressed[0].reason == "exact_content_hash_match"


def test_global_non_code_memory_without_repository_is_preserved():
    m = load_protocol()
    coverage = m.CoverageManifest(repository_id="repo-A", covered=[])
    result = m.ClassificationEngine().classify_claims([{
        "id": "pref-1", "claim": "The user prefers concise commit summaries", "claim_type": "preference",
    }], coverage)
    assert result.included_claim_ids == ["pref-1"]
    assert result.suppressed == []
