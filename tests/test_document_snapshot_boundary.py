#!/usr/bin/env python3
"""Regression: document ingestion snapshots a no-follow validated source file."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_document_snapshot_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_is_immutable_and_static_symlinks_are_rejected() -> None:
    previous = {
        key: os.environ.get(key)
        for key in (
            "HERMES_HOME",
            "MEMORY_WIKI_DOCUMENT_CACHE_DIR",
            "HERMES_DOCUMENT_CACHE_DIR",
            "MEMORY_WIKI_DOCUMENT_ROOTS",
        )
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-doc-snapshot-") as tmp:
            home = Path(tmp)
            docs = home / "cache" / "documents"
            docs.mkdir(parents=True)
            source = docs / "report.txt"
            source.write_text("original safe content", encoding="utf-8")
            os.environ["HERMES_HOME"] = str(home)
            for key in ("MEMORY_WIKI_DOCUMENT_CACHE_DIR", "HERMES_DOCUMENT_CACHE_DIR", "MEMORY_WIKI_DOCUMENT_ROOTS"):
                os.environ.pop(key, None)
            module = load_module()

            snapshot, metadata = module._snapshot_allowed_file(source, max_bytes=1024)
            try:
                assert snapshot != source
                assert snapshot.suffix == ".txt"
                assert metadata["size_bytes"] == len("original safe content".encode("utf-8"))
                source.write_text("source changed after open", encoding="utf-8")
                assert snapshot.read_text(encoding="utf-8") == "original safe content"
            finally:
                snapshot.unlink(missing_ok=True)

            link = docs / "inside-link.txt"
            try:
                os.symlink(source, link)
            except OSError:
                # The snapshot path is still tested on Windows installations where
                # symlink creation is not granted to the test process.
                return
            try:
                try:
                    module._allowed_path(link)
                except ValueError:
                    pass
                else:
                    raise AssertionError("symlink within an allowed root was accepted")

                target_dir = docs / "target-dir"
                target_dir.mkdir()
                nested = target_dir / "nested.txt"
                nested.write_text("nested", encoding="utf-8")
                linked_dir = docs / "linked-dir"
                os.symlink(target_dir, linked_dir, target_is_directory=True)
                for unsafe in (linked_dir / "nested.txt", linked_dir):
                    try:
                        if unsafe.is_dir():
                            module._scan_root({"root": str(unsafe)})
                        else:
                            module._allowed_path(unsafe)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError(f"intermediate symlink was accepted: {unsafe}")
            finally:
                link.unlink(missing_ok=True)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_snapshot_is_immutable_and_static_symlinks_are_rejected()
    print("PASS test_snapshot_is_immutable_and_static_symlinks_are_rejected")
