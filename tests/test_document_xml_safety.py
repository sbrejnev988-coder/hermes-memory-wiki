#!/usr/bin/env python3
"""Regression: document XML rejects DTD/entity declarations before parsing."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import zipfile
from pathlib import Path


EXTRACTORS = Path(__file__).resolve().parents[1] / "document_extractors.py"


def load_extractors(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, EXTRACTORS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_zip_xml_rejects_entity_declarations() -> None:
    module = load_extractors("memory_wiki_xml_entity_test")
    payload = b'<?xml version="1.0"?><!DOCTYPE root [<!ENTITY x "expanded">]><root>&x;</root>'
    with tempfile.TemporaryDirectory(prefix="mw-xml-entity-") as tmp:
        archive = Path(tmp) / "document.zip"
        with zipfile.ZipFile(archive, "w") as writer:
            writer.writestr("word/document.xml", payload)
        with zipfile.ZipFile(archive) as reader:
            try:
                module._read_zip_xml(reader, "word/document.xml")
            except ValueError as exc:
                assert "DTD/entity" in str(exc)
            else:
                raise AssertionError("DTD/entity declaration was accepted")


if __name__ == "__main__":
    test_zip_xml_rejects_entity_declarations()
    print("PASS test_zip_xml_rejects_entity_declarations")
