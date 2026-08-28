#!/usr/bin/env python3
"""Regression: every native text/email emission respects the document unit ceiling."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_extractors.py"


def load_module():
    spec = importlib.util.spec_from_file_location("memory_wiki_document_extended_budget_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_plain_and_email_extractors_never_exceed_max_units() -> None:
    module = load_module()
    plain = module.extract_plain(Path("notes.md"), b"# One\n\nparagraph\n\n# Two\n\nmore", 1)
    assert len(plain.units) <= 1
    message = EmailMessage()
    message["Subject"] = "Budget"
    message.set_content("plain body")
    message.add_alternative("<p>html body</p>", subtype="html")
    with tempfile.TemporaryDirectory(prefix="mw-unit-budget-email-") as tmp:
        path = Path(tmp) / "message.eml"
        path.write_bytes(message.as_bytes())
        extracted = module.extract_eml(path, path.read_bytes(), 1)
    assert len(extracted.units) <= 1


if __name__ == "__main__":
    test_plain_and_email_extractors_never_exceed_max_units()
    print("PASS test_plain_and_email_extractors_never_exceed_max_units")
