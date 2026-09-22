"""Create a fail-closed provenance record for the full LongMemEval probe.

The output deliberately contains repository-relative source names and stable
placeholders instead of local dataset, result, repository, or interpreter
paths.  It never copies arbitrary result metadata into the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FORMAT_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONFIG_KEYS = {
    "top_k",
    "episode_slots",
    "episode_query_max_results",
    "episode_query_max_chars",
    "episode_query_mode",
}
_GUARD_MODES = {
    "strict shared guard",
    "non-strict local guard; shared core unavailable",
}
_RETRIEVAL_MODES = {
    "offline FTS; no OpenRouter/Qdrant or answer generation",
}
_PRODUCTION_DATA_FILES = (
    "graph_stats.json",
    "plugin.yaml",
    "pyproject.toml",
    "rerank-rules.json",
    "schema.sql",
    "uv.lock",
)


class ProvenanceError(ValueError):
    """The supplied benchmark artifact cannot be attested safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ProvenanceError("required input could not be read") from exc
    return digest.hexdigest()


def _load_result(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError("result is not a readable UTF-8 JSON document") from exc
    if not isinstance(value, dict):
        raise ProvenanceError("result root must be a JSON object")
    return value, hashlib.sha256(payload).hexdigest()


def _required_int(value: Any, name: str, lower: int, upper: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise ProvenanceError(f"invalid {name} in benchmark result")
    return value


def _safe_result_metadata(result: dict[str, Any]) -> dict[str, Any]:
    config = result.get("effective_config")
    if not isinstance(config, dict) or set(config) != _CONFIG_KEYS:
        raise ProvenanceError("effective_config has missing or unexpected fields")
    safe_config = {
        "top_k": _required_int(config.get("top_k"), "top_k", 2, 50),
        "episode_slots": _required_int(config.get("episode_slots"), "episode_slots", 1, 49),
        "episode_query_max_results": _required_int(
            config.get("episode_query_max_results"), "episode_query_max_results", 1, 50
        ),
        "episode_query_max_chars": _required_int(
            config.get("episode_query_max_chars"), "episode_query_max_chars", 350, 12000
        ),
    }
    if safe_config["episode_slots"] >= safe_config["top_k"]:
        raise ProvenanceError("episode_slots must be smaller than top_k")
    query_mode = config.get("episode_query_mode")
    if query_mode not in {"auto", "fts", "semantic", "hybrid"}:
        raise ProvenanceError("invalid episode_query_mode in benchmark result")
    safe_config["episode_query_mode"] = query_mode

    guard_mode = result.get("guard_mode")
    retrieval_mode = result.get("retrieval_mode")
    if guard_mode not in _GUARD_MODES:
        raise ProvenanceError("unrecognized guard_mode in benchmark result")
    if retrieval_mode not in _RETRIEVAL_MODES:
        raise ProvenanceError("unrecognized retrieval_mode in benchmark result")
    dataset_questions = _required_int(
        result.get("dataset_questions"), "dataset_questions", 1, 1_000_000
    )
    evaluated_questions = _required_int(
        result.get("evaluated_questions"), "evaluated_questions", 1, dataset_questions
    )
    official_match = result.get("official_oracle_sha256_match")
    if not isinstance(official_match, bool):
        raise ProvenanceError("official_oracle_sha256_match must be boolean")
    return {
        "dataset_questions": dataset_questions,
        "evaluated_questions": evaluated_questions,
        "official_oracle_sha256_match": official_match,
        "effective_config": safe_config,
        "guard_mode": guard_mode,
        "retrieval_mode": retrieval_mode,
    }


def _source_candidates(repo_root: Path) -> list[Path]:
    candidates = list(repo_root.glob("*.py"))
    candidates.extend(repo_root / name for name in _PRODUCTION_DATA_FILES)
    candidates.extend((repo_root / "benchmarks").glob("*.py"))
    return sorted({path for path in candidates if path.is_file()}, key=lambda item: item.as_posix())


def _source_hashes(repo_root: Path) -> dict[str, str]:
    try:
        resolved_root = repo_root.resolve(strict=True)
    except OSError as exc:
        raise ProvenanceError("repository root could not be resolved") from exc
    first_paths = _source_candidates(resolved_root)
    if not first_paths:
        raise ProvenanceError("no production or benchmark source files found")

    def one_pass(paths: list[Path]) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for source in paths:
            try:
                resolved = source.resolve(strict=True)
                relative = resolved.relative_to(resolved_root).as_posix()
            except (OSError, ValueError) as exc:
                raise ProvenanceError("source file resolves outside the repository") from exc
            hashes[relative] = _sha256(resolved)
        return dict(sorted(hashes.items()))

    first = one_pass(first_paths)
    second_paths = _source_candidates(resolved_root)
    second = one_pass(second_paths)
    if first != second:
        raise ProvenanceError("source files changed while provenance was being generated")
    required = {
        "__init__.py",
        "episodic_memory.py",
        "schema.sql",
        "benchmarks/full_oracle_episode_probe.py",
        "benchmarks/episodic_fallback_probe.py",
        "benchmarks/longmemeval_adapter.py",
        "benchmarks/benchmark_provenance.py",
    }
    if not required <= set(first):
        raise ProvenanceError("required production or runner source is missing")
    return first


def _tree_sha256(source_hashes: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative, file_hash in sorted(source_hashes.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _git_state(repo_root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            completed = subprocess.run(
                ["git", *args], cwd=repo_root, check=True, capture_output=True,
                text=True, encoding="utf-8", errors="strict", timeout=15,
            )
        except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
            raise ProvenanceError("Git state could not be read") from exc
        return completed.stdout.strip()

    head = run("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", head):
        raise ProvenanceError("Git HEAD is not a commit hash")
    dirty = bool(run("status", "--porcelain=v1", "--untracked-files=all"))
    return {"head": head.lower(), "dirty": dirty}


def _runtime() -> dict[str, Any]:
    return {
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "sqlite": {
            "runtime_version": sqlite3.sqlite_version,
            "threadsafety": sqlite3.threadsafety,
        },
    }


def build_provenance(
    result_path: Path,
    dataset_path: Path,
    *,
    repo_root: Path = ROOT,
    progress_every: int = 25,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Validate the inputs and return a path-free provenance document."""
    progress_every = _required_int(progress_every, "progress_every", 0, 1_000_000)
    result, result_sha256 = _load_result(result_path)
    metadata = _safe_result_metadata(result)
    declared_dataset_sha256 = result.get("dataset_sha256")
    if not isinstance(declared_dataset_sha256, str) or not _SHA256_RE.fullmatch(
        declared_dataset_sha256
    ):
        raise ProvenanceError("result dataset_sha256 is missing or invalid")
    actual_dataset_sha256 = _sha256(dataset_path)
    if actual_dataset_sha256 != declared_dataset_sha256:
        raise ProvenanceError("dataset SHA-256 does not match the benchmark result")

    source_hashes = _source_hashes(repo_root)
    run_source_hash = result.get("source_tree_sha256")
    if not isinstance(run_source_hash, str) or not _SHA256_RE.fullmatch(run_source_hash):
        raise ProvenanceError("result source_tree_sha256 is missing or invalid")
    if run_source_hash != _tree_sha256(source_hashes):
        raise ProvenanceError("benchmark source changed since the measured run")
    # Bind the manifest to stable inputs even if another process replaces a
    # benchmark artifact while the source tree is being hashed.
    if _sha256(result_path) != result_sha256 or _sha256(dataset_path) != actual_dataset_sha256:
        raise ProvenanceError("benchmark input changed while provenance was being generated")
    config = metadata["effective_config"]
    argv = [
        "python",
        "benchmarks/full_oracle_episode_probe.py",
        "--dataset",
        "<DATASET_JSON>",
        "--limit",
        str(metadata["evaluated_questions"]),
        "--top-k",
        str(config["top_k"]),
        "--episode-slots",
        str(config["episode_slots"]),
        "--progress-every",
        str(progress_every),
    ]
    command = " ".join(argv) + " > <RESULT_JSON>"
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "format": "memory-wiki-benchmark-provenance",
        "format_version": FORMAT_VERSION,
        "generated_at": generated_at,
        "artifacts": {
            "dataset": {
                "sha256": actual_dataset_sha256,
                "declared_sha256": declared_dataset_sha256,
                "matches_result_declaration": True,
                "official_oracle_sha256_match": metadata["official_oracle_sha256_match"],
            },
            "result": {"sha256": result_sha256},
        },
        "benchmark": {
            "dataset_questions": metadata["dataset_questions"],
            "evaluated_questions": metadata["evaluated_questions"],
            "effective_config": config,
            "guard_mode": metadata["guard_mode"],
            "retrieval_mode": metadata["retrieval_mode"],
        },
        "reproduction": {
            "command": command,
            "argv": argv,
            "stdout": "<RESULT_JSON>",
            "environment": {
                "MEMORY_WIKI_EPISODIC_QUERY_MAX_RESULTS": str(
                    config["episode_query_max_results"]
                ),
                "MEMORY_WIKI_EPISODIC_QUERY_MAX_CHARS": str(
                    config["episode_query_max_chars"]
                ),
                "MEMORY_WIKI_EPISODIC_QUERY_MODE": str(config["episode_query_mode"]),
            },
        },
        "runtime": _runtime(),
        "git": _git_state(repo_root),
        "sources": {
            "selection": (
                "repository-root *.py and production data/config files; benchmarks/*.py"
            ),
            "tree_sha256": _tree_sha256(source_hashes),
            "files": source_hashes,
        },
    }


def write_provenance(output: Path, manifest: dict[str, Any], *, force: bool = False) -> None:
    """Atomically write a manifest, refusing replacement unless requested."""
    if output.exists() and not force:
        raise ProvenanceError("output already exists; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = build_provenance(
            args.result,
            args.dataset,
            repo_root=args.repo_root,
            progress_every=args.progress_every,
        )
        write_provenance(args.output, manifest, force=args.force)
    except ProvenanceError as exc:
        parser.error(str(exc))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
