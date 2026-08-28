#!/usr/bin/env python3
"""Generate a deterministic SPDX 2.3 SBOM from pyproject.toml and uv.lock."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def created_at() -> str:
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0") or 0)
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def package_spdx_id(name: str, version: str) -> str:
    safe = "".join(char if char.isalnum() else "-" for char in f"{name}-{version}")
    return f"SPDXRef-Package-{safe}".replace("--", "-")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist/sbom.spdx.json")
    args = parser.parse_args()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock_path = ROOT / "uv.lock"
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {"package": []}
    packages = [{"name": project["name"], "version": project["version"], "supplier": "Organization: sbrejnev988-coder"}]
    seen = {(project["name"].lower(), project["version"])}
    for entry in lock.get("package", []):
        name = str(entry.get("name") or "").strip()
        version = str(entry.get("version") or "").strip()
        if not name or not version or (name.lower(), version) in seen:
            continue
        seen.add((name.lower(), version))
        packages.append({"name": name, "version": version, "supplier": "NOASSERTION"})
    namespace_seed = f"{project['name']}:{project['version']}"
    namespace = "https://github.com/sbrejnev988-coder/hermes-memory-wiki/sbom/" + str(uuid.uuid5(uuid.NAMESPACE_URL, namespace_seed))
    spdx_packages = []
    relationships = []
    for item in packages:
        spdx_id = package_spdx_id(item["name"], item["version"])
        spdx_packages.append({
            "SPDXID": spdx_id,
            "name": item["name"],
            "versionInfo": item["version"],
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "supplier": item["supplier"],
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        })
        relationships.append({"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": spdx_id})
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{project['name']}-{project['version']}",
        "documentNamespace": namespace,
        "creationInfo": {"created": created_at(), "creators": ["Tool: hermes-memory-wiki packaging/generate_sbom.py"]},
        "packages": spdx_packages,
        "relationships": relationships,
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(json.dumps({"output": str(output), "sha256": digest, "packages": len(spdx_packages)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
