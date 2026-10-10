"""Two source-only pure-product regressions; no SDK, files, SQL or transport.

AST-load exact product helpers without importing the plugin package. The L1
receipt covers cache admission, not a native ingest/parser/cleanup execution.
Caller AST verifies the unchanged real-extraction and snapshot finally branch.
"""
import ast
import copy
import hashlib
import json
import os
import re
import unittest
import urllib.parse
import ipaddress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def helpers(root=ROOT):
    # Read only explicit source; executing no package imports or module setup.
    ns = dict(json=json, re=re, hashlib=hashlib, os=os,
              urllib=__import__("urllib"), ipaddress=ipaddress)
    wanted = {
        "document_extractors.py": {
            "EXTRACTOR_VERSION", "SECRET_POLICY_VERSION", "_SECRET_ASSIGN_RE",
            "_PRIVATE_KEY_RE", "_URL_CREDENTIAL_RE", "_PROVIDER_SECRET_PATTERNS",
            "OOXML_EXTENSIONS", "ODF_EXTENSIONS", "EBOOK_EXTENSIONS",
            "PDF_EXTENSIONS", "IMAGE_EXTENSIONS", "SUPPORTED_EXTENSIONS",
            "TEXT_EXTENSIONS", "EMAIL_EXTENSIONS", "LEGACY_OFFICE_EXTENSIONS",
            "GOOGLE_POINTER_EXTENSIONS", "redact_secret_text", "clean_text",
            "sanitize_json", "sha256_bytes", "effective_extraction_options",
            "_is_loopback_http_url", "_tika_request_identity",
            "extraction_options_fingerprint",
        },
        "document_knowledge_graph.py": {
            "_sha", "_json", "_cached_extraction_payload",
        },
    }
    for rel, names in wanted.items():
        tree = ast.parse((root / rel).read_text(encoding="utf-8"), filename=str(root / rel))
        selected = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
                selected.append(node)
            elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in names for target in node.targets
            ):
                selected.append(node)
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(root / rel), "exec"), ns)
    ns["_EXTRACTOR_VERSION"] = ns["EXTRACTOR_VERSION"]
    ns["_CURRENT_PARSER_VERSION"] = f"{ns['EXTRACTOR_VERSION']}:secret-policy-{ns['SECRET_POLICY_VERSION']}"
    ns["_sanitize_extracted_json"] = ns["sanitize_json"]
    return ns


class CacheRequestRepair(unittest.TestCase):
    def test_non_dict_and_nested_cache_are_misses(self):
        n = helpers()
        fp, file_hash = "a" * 64, "b" * 64
        version = n["_CURRENT_PARSER_VERSION"]
        payload = {
            "parser": "authored-text", "parser_version": version,
            "extractor_version": n["EXTRACTOR_VERSION"], "status": "ok",
            "file_hash": file_hash, "title": "Authored", "mime_type": "text/plain",
            "file_name": "authored.txt", "extension": ".txt", "path": "authored.txt",
            "file_size": 16, "mtime_ns": 1, "secret_redactions": 0,
            "secret_categories": {}, "metadata": {}, "warnings": [],
            "units": [{"kind": "text", "anchor": "line:1", "text": "Authored real text",
                       "title": "", "parent_anchor": "", "ordinal": 1,
                       "locator": {}, "metadata": {}}], "edges": [],
        }
        def envelope(value):
            return n["_json"]({"extraction_fingerprint": fp, "extraction_payload": value,
                               "extraction_payload_hash": n["_sha"](n["_json"](value))})
        def admit(raw):
            return n["_cached_extraction_payload"](raw, extraction_fp=fp, file_hash=file_hash,
                                                  parser="authored-text", parser_version=version)
        self.assertEqual(admit(envelope(payload)), payload)
        for raw in ("[]", "null", "17", '"scalar"', "true"):
            with self.subTest(top_level=raw):
                self.assertIsNone(admit(raw))
        for key, value in (("units", None), ("units", [None]), ("edges", [0]),
                           ("metadata", []), ("warnings", [None])):
            bad = copy.deepcopy(payload); bad[key] = value
            with self.subTest(field=key):
                self.assertIsNone(admit(envelope(bad)))
        bad = copy.deepcopy(payload); bad["units"][0]["locator"] = None
        self.assertIsNone(admit(envelope(bad)))
        bad = copy.deepcopy(payload); bad["units"][0]["text"] = "password=authored_dummy_value"
        self.assertIsNone(admit(envelope(bad)))  # Correct hash cannot bless an unsanitized cache.
        bad = copy.deepcopy(payload); bad["file_hash"] = "c" * 64
        self.assertIsNone(admit(envelope(bad)))
        tree = ast.parse((ROOT / "document_knowledge_graph.py").read_text(encoding="utf-8"))
        ingest = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "ingest_document")
        scope = next(x for x in ingest.body if isinstance(x, ast.Try) and x.finalbody)
        fallback = next(x for x in scope.body if isinstance(x, ast.If) and ast.unparse(x.test) == "payload is None")
        self.assertEqual(ast.unparse(fallback.body[0].value.func), "_extract")
        self.assertEqual(ast.unparse(fallback.body[0].value.args[0]), "snapshot")
        self.assertTrue(any(isinstance(x, ast.Call) and ast.unparse(x.func) == "snapshot.unlink"
                            for x in ast.walk(ast.Module(body=scope.finalbody, type_ignores=[]))))

    def test_query_sensitive_fingerprint_has_no_plaintext_material(self):
        n = helpers()
        base = {"tika_url": "http://127.0.0.1:9998/tika?lang=A&token=authored_dummy_value",
                "tesseract_bin": "tesseract", "ocr_psm": "3"}
        changed = {**base, "tika_url": base["tika_url"].replace("lang=A", "lang=B")}
        first = n["extraction_options_fingerprint"](Path("authored.doc"), base)
        second = n["extraction_options_fingerprint"](Path("authored.doc"), changed)
        self.assertNotEqual(first, second)
        self.assertEqual(first, n["extraction_options_fingerprint"](Path("authored.doc"), dict(base)))
        identity = n["_tika_request_identity"](base["tika_url"])
        self.assertEqual(identity, hashlib.sha256(base["tika_url"].encode()).hexdigest())
        self.assertRegex(identity, r"^[0-9a-f]{64}$")
        material = json.dumps({"tika_parser": identity, "extraction_fingerprint": first})
        for literal in ("authored_dummy_value", "token=", "lang=A", base["tika_url"]):
            self.assertNotIn(literal, material)
        tree = ast.parse((ROOT / "document_extractors.py").read_text(encoding="utf-8"))
        fp = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "extraction_options_fingerprint")
        assignment = next(x for x in ast.walk(fp) if isinstance(x, ast.Assign)
                          and any(ast.unparse(t) == "material['tika_parser']" for t in x.targets))
        self.assertEqual(ast.unparse(assignment.value), "_tika_request_identity(o['tika_url'])")
        tika = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "extract_tika")
        self.assertIn("_tika_request_identity(tika_url)", ast.unparse(tika))
        for invalid in ("http://example.invalid/tika?token=authored_dummy_value",
                        "http://127.0.0.1:bad/tika?token=authored_dummy_value",
                        "http://127.0.0.1/tika?" + "x" * 8192):
            with self.assertRaises(ValueError) as exc:
                n["_tika_request_identity"](invalid)
            self.assertEqual(str(exc.exception), "invalid loopback Tika request URL")


if __name__ == "__main__":
    unittest.main()
