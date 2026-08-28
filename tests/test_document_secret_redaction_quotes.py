#!/usr/bin/env python3
"""Regression: labelled document secrets redact quoted and Bearer values fully."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_extractors.py"


def load_module(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_labelled_quoted_and_bearer_secrets_are_fully_redacted() -> None:
    module = load_module("memory_wiki_document_secret_quotes_test")
    cases = [
        ('password = "alpha bravo charlie delta"', "alpha bravo charlie delta"),
        ("token: 'red green blue yellow'", "red green blue yellow"),
        ("Authorization: Bearer opaque-test-value-123456", "opaque-test-value-123456"),
    ]

    for raw, sensitive_value in cases:
        redacted, findings = module.redact_secret_text(raw)
        assert sensitive_value not in redacted
        assert "<REDACTED>" in redacted
        assert any(item["category"] == "labelled_secret" for item in findings)


if __name__ == "__main__":
    test_labelled_quoted_and_bearer_secrets_are_fully_redacted()
    print("PASS test_labelled_quoted_and_bearer_secrets_are_fully_redacted")
