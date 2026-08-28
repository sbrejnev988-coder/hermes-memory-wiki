#!/usr/bin/env python3
"""Release contract: package/native/runtime documentation share one verifiable version."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_contract_is_complete_and_version_consistent() -> None:
    pyproject = ROOT / "pyproject.toml"
    assert pyproject.is_file(), "missing pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = data["project"]["version"]
    assert (ROOT / "LICENSE").is_file(), "missing LICENSE"
    assert (ROOT / "uv.lock").is_file(), "missing dependency lockfile"
    assert (ROOT / "packaging" / "generate_sbom.py").is_file(), "missing SBOM generator"
    assert (ROOT / "packaging" / "build_native_bundle.py").is_file(), "missing native bundle builder"
    assert (ROOT / "packaging" / "check_reproducible.py").is_file(), "missing reproducibility gate"
    release_workflow = ROOT / ".github" / "workflows" / "release.yml"
    assert release_workflow.is_file(), "missing release provenance workflow"
    workflow_text = release_workflow.read_text(encoding="utf-8")
    assert "actions/attest-build-provenance@v2" in workflow_text, "missing SLSA provenance attestation"
    assert "actions/attest@v4" in workflow_text, "missing SPDX SBOM attestation"
    manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    runtime = (ROOT / "__init__.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(rf"^version:\s*{re.escape(version)}\s*$", manifest, re.M)
    assert re.search(rf'PLUGIN_VERSION\s*=\s*"{re.escape(version)}"', runtime)
    assert re.search(rf"^# Hermes Memory Wiki v{re.escape(version)}\s*$", readme, re.M)


if __name__ == "__main__":
    test_release_contract_is_complete_and_version_consistent()
    print("PASS test_release_contract_is_complete_and_version_consistent")
