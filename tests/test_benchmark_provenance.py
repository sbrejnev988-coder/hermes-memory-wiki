"""Provenance for the full LongMemEval artifact must be complete and fail closed."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "benchmark_provenance.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("benchmark_provenance_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _result(dataset: Path, **changes):
    module = _load_module()
    value = {
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "source_tree_sha256": module._tree_sha256(module._source_hashes(ROOT)),
        "official_oracle_sha256_match": False,
        "dataset_questions": 7,
        "evaluated_questions": 7,
        "guard_mode": "non-strict local guard; shared core unavailable",
        "retrieval_mode": "offline FTS; no OpenRouter/Qdrant or answer generation",
        "effective_config": {
            "top_k": 8,
            "episode_slots": 5,
            "episode_query_max_results": 8,
            "episode_query_max_chars": 2400,
            "episode_query_mode": "auto",
        },
    }
    value.update(changes)
    return value


def test_manifest_rejects_result_from_other_source_tree(tmp_path):
    module = _load_module()
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]", encoding="utf-8")
    result = tmp_path / "result.json"
    result.write_text(json.dumps(_result(dataset, source_tree_sha256="0" * 64)), encoding="utf-8")
    with pytest.raises(module.ProvenanceError, match="source changed"):
        module.build_provenance(result, dataset, repo_root=ROOT)


def test_manifest_hashes_inputs_sources_and_contains_no_local_paths(tmp_path):
    module = _load_module()
    dataset = tmp_path / "private-user-dataset.json"
    dataset.write_text("[]\n", encoding="utf-8")
    result = tmp_path / "private-user-result.json"
    result.write_text(json.dumps(_result(dataset)), encoding="utf-8")

    manifest = module.build_provenance(
        result, dataset, repo_root=ROOT, progress_every=17,
        generated_at="2026-09-21T00:00:00Z",
    )

    assert manifest["artifacts"]["dataset"]["sha256"] == hashlib.sha256(
        dataset.read_bytes()
    ).hexdigest()
    assert manifest["artifacts"]["result"]["sha256"] == hashlib.sha256(
        result.read_bytes()
    ).hexdigest()
    assert manifest["artifacts"]["dataset"]["matches_result_declaration"] is True
    assert manifest["reproduction"]["command"] == (
        "python benchmarks/full_oracle_episode_probe.py --dataset <DATASET_JSON> "
        "--limit 7 --top-k 8 --episode-slots 5 --progress-every 17 > <RESULT_JSON>"
    )
    files = manifest["sources"]["files"]
    assert "__init__.py" in files
    assert "episodic_memory.py" in files
    assert "benchmarks/full_oracle_episode_probe.py" in files
    assert "benchmarks/benchmark_provenance.py" in files
    assert all(len(digest) == 64 for digest in files.values())
    serialized = json.dumps(manifest)
    assert str(tmp_path) not in serialized
    assert dataset.name not in serialized
    assert result.name not in serialized
    assert set(manifest["git"]) == {"head", "dirty"}
    assert set(manifest["runtime"]) == {"python", "platform", "sqlite"}


def test_cli_fails_closed_on_dataset_hash_mismatch_without_writing_output(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]", encoding="utf-8")
    result = tmp_path / "result.json"
    payload = _result(dataset)
    payload["dataset_sha256"] = "0" * 64
    result.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "provenance.json"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--result", str(result), "--dataset", str(dataset),
         "--output", str(output), "--repo-root", str(ROOT)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )

    assert completed.returncode != 0
    assert "does not match" in completed.stderr
    assert not output.exists()


def test_unexpected_result_metadata_is_rejected_instead_of_copied(tmp_path):
    module = _load_module()
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]", encoding="utf-8")
    payload = _result(dataset)
    payload["effective_config"]["api_key"] = "must-not-appear"
    result = tmp_path / "result.json"
    result.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(module.ProvenanceError, match="unexpected fields"):
        module.build_provenance(result, dataset, repo_root=ROOT)


def test_atomic_writer_refuses_to_replace_existing_manifest(tmp_path):
    module = _load_module()
    output = tmp_path / "provenance.json"
    output.write_text("original", encoding="utf-8")

    with pytest.raises(module.ProvenanceError, match="already exists"):
        module.write_provenance(output, {"new": True})

    assert output.read_text(encoding="utf-8") == "original"
