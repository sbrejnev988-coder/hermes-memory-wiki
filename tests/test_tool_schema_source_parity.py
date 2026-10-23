"""Offline full-dictionary schema parity and release-diagnostic regressions.

Collection is inert. Only the reviewed, self-independent schema method is
executed in setUpClass; the provider package/SDK is never imported here.
Injected native-export results and CompletedProcess records test packaging
control flow, NOT actual native export, process launch or release acceptance.
"""
from __future__ import annotations

import ast
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_SOURCE = ROOT / "__init__.py"


def _script(relative: str) -> types.ModuleType:
    path = ROOT / relative
    module = types.ModuleType("schema_contract_" + path.stem)
    module.__file__ = str(path)
    # Execute the inert packaging module, not the plugin's package initializer.
    exec(compile(path.read_bytes(), str(path), "exec", dont_inherit=True), module.__dict__)
    return module


def _declared_schemas(raw: bytes) -> list[dict]:
    tree = ast.parse(raw)
    owners = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MemoryWikiProvider"]
    if len(owners) != 1:
        raise ValueError("schema owner is not unique")
    methods = [n for n in owners[0].body if isinstance(n, ast.FunctionDef) and n.name == "get_tool_schemas"]
    if len(methods) != 1:
        raise ValueError("schema method is not unique")
    method = methods[0]
    # Fail closed if this pure declaration acquires receiver/global dependencies.
    allowed_names = {"List", "Dict", "Any", "P", "props", "req", "document_options", "list", "range", "str", "n"}
    loaded = {n.id for n in ast.walk(method) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    calls = [n.func for n in ast.walk(method) if isinstance(n, ast.Call)]
    if (method.decorator_list or loaded - allowed_names
            or any(not isinstance(n, ast.Name) or n.id not in {"P", "list", "range", "str"} for n in calls)
            or [type(n) for n in method.body] != [ast.Assign, ast.Assign, ast.Return]):
        raise ValueError("schema declaration is no longer self-independent")
    # Omit the real bases, decorators, class body and all package bootstrap code.
    owner = ast.ClassDef(name="MemoryWikiProvider", bases=[], keywords=[], body=[method], decorator_list=[])
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, owner], type_ignores=[]))
    namespace: dict = {}
    exec(compile(module, "<source-only-schema-method>", "exec", dont_inherit=True), namespace)
    return namespace["MemoryWikiProvider"].get_tool_schemas(object())


class ToolSchemaSourceParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = _declared_schemas(PROVIDER_SOURCE.read_bytes())
        cls.generator = _script("packaging/generate_tool_schemas.py")
        cls.release = _script("packaging/verify_release.py")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="schema-contract-")
        self.addCleanup(temporary.cleanup)
        self.target = Path(temporary.name) / "schemas.json"

    def _generate(self, argv, *, schemas=None, error=None):
        output, errors = io.StringIO(), io.StringIO()
        with (patch.object(self.generator, "TARGET", self.target),
              patch.object(self.generator, "_runtime_schemas", return_value=self.schemas if schemas is None else schemas,
                           side_effect=error), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors)):
            code = self.generator.main(argv)
        return code, output.getvalue(), errors.getvalue()

    def _release_failure(self, record=None, *, error=None):
        errors = io.StringIO()
        with (patch.object(self.release.subprocess, "run", return_value=record, side_effect=error),
              contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as caught):
            self.release._check_schema_cache()
        self.assertEqual(caught.exception.code, 2)
        return errors.getvalue()

    def test_complete_schema_cache_matches_source_and_manifest(self):
        cached_raw = (ROOT / "mcp-wrapper/tool_schemas.json").read_bytes()
        cached = json.loads(cached_raw)
        # Full dictionaries, list order, descriptions and all nested constraints.
        self.assertTrue(cached == self.schemas, "full schema dictionaries differ from the declared source")
        names = [row["name"] for row in self.schemas]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names, self.generator._manifest_tool_names())
        self.assertEqual(cached_raw, self.generator._render(self.schemas).encode("utf-8"))

    def test_document_options_share_full_declared_contract(self):
        by_name = {row["name"]: row for row in self.schemas}
        ingest = by_name["memory_wiki_document_ingest"]["parameters"]
        scan = by_name["memory_wiki_document_scan"]["parameters"]
        keys = {"ocr", "ocr_language", "pdf_parser", "pdf_mode", "pdf_reading_order", "pdf_tables",
                "pdf_native_fallback", "pdf_table_strategy", "pdf_max_blocks_per_page", "pdf_max_tables_per_page",
                "ocr_min_chars", "ocr_dpi", "ocr_max_pixels", "ocr_max_pages", "ocr_max_tsv_rows",
                "ocr_min_native_chars", "ocr_psm", "max_units", "max_cells", "max_pages", "max_chars", "external_timeout"}
        a, b = ingest["properties"], scan["properties"]
        self.assertTrue(keys <= a.keys() and keys <= b.keys())
        self.assertEqual({k: a[k] for k in keys}, {k: b[k] for k in keys})
        self.assertEqual(a["ocr_psm"], {"type": "string", "enum": list(map(str, range(14))), "default": "3"})
        self.assertEqual(a["pdf_parser"]["enum"], ["auto", "pymupdf", "pypdf"])
        self.assertEqual(a["ocr_dpi"], {"type": "integer", "default": 200, "minimum": 72, "maximum": 400})
        self.assertEqual(ingest["required"], ["path"])
        self.assertEqual(scan["required"], [])

    def test_cache_meets_pinned_api_major_contract(self):
        checker = _script("packaging/check_mcp_compatibility.py")
        baseline = json.loads((ROOT / "compatibility/mcp-api-v1.json").read_bytes())
        cached = json.loads((ROOT / "mcp-wrapper/tool_schemas.json").read_bytes())
        self.assertEqual(checker.check_contract(baseline, cached), [])

    def test_render_rejects_empty_name(self):
        with self.assertRaisesRegex(RuntimeError, "empty tool name"):
            self.generator._render([{"name": ""}])

    def test_render_rejects_duplicate_names(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate tool names"):
            self.generator._render([self.schemas[0], self.schemas[0]])

    def test_render_rejects_manifest_order_drift(self):
        with self.assertRaisesRegex(RuntimeError, "plugin.yaml tool list differs"):
            self.generator._render(list(reversed(self.schemas)))

    def test_check_healthy_is_readonly(self):
        raw = self.generator._render(self.schemas).encode("utf-8")
        self.target.write_bytes(raw)
        self.assertEqual(self._generate(["--check"]), (0, f"MCP_SCHEMA_CACHE_OK tools={len(self.schemas)}\n", ""))
        self.assertEqual(self.target.read_bytes(), raw)

    def test_check_detects_nested_drift_readonly(self):
        corrupt = deepcopy(self.schemas)
        tool = next(row for row in corrupt if row["name"] == "memory_wiki_document_ingest")
        tool["parameters"]["properties"]["ocr_dpi"]["maximum"] = 399
        raw = self.generator._render(corrupt).encode("utf-8")
        self.target.write_bytes(raw)
        self.assertEqual(self._generate(["--check"]), (2, "", "MCP_SCHEMA_CACHE_STALE\n"))
        self.assertEqual(self.target.read_bytes(), raw)

    def test_check_missing_cache_is_stale(self):
        self.assertEqual(self._generate(["--check"]), (2, "", "MCP_SCHEMA_CACHE_STALE\n"))
        self.assertFalse(self.target.exists())

    def test_native_export_error_is_not_staleness(self):
        self.target.write_bytes(b"original-cache")
        code, out, err = self._generate(["--check"], error=RuntimeError("synthetic-native-export-failure"))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("MCP_SCHEMA_GENERATION_FAILED stage=native_export", err)
        self.assertIn("RuntimeError: synthetic-native-export-failure", err)
        self.assertNotIn("MCP_SCHEMA_CACHE_STALE", err)
        self.assertEqual(self.target.read_bytes(), b"original-cache")

    def test_schema_validation_error_is_not_staleness(self):
        code, out, err = self._generate(["--check"], schemas=[self.schemas[0], self.schemas[0]])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("MCP_SCHEMA_GENERATION_FAILED stage=schema_validation", err)
        self.assertIn("duplicate tool names", err)
        self.assertNotIn("MCP_SCHEMA_CACHE_STALE", err)
        self.assertFalse(self.target.exists())

    def test_cache_read_error_is_not_staleness(self):
        self.target.write_bytes(b"\xff")
        code, out, err = self._generate(["--check"])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("MCP_SCHEMA_GENERATION_FAILED stage=cache_read", err)
        self.assertIn("UnicodeDecodeError", err)
        self.assertNotIn("MCP_SCHEMA_CACHE_STALE", err)
        self.assertEqual(self.target.read_bytes(), b"\xff")

    def test_cache_write_error_is_not_staleness(self):
        self.target.mkdir()
        code, out, err = self._generate([])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("MCP_SCHEMA_GENERATION_FAILED stage=cache_write", err)
        self.assertNotIn("MCP_SCHEMA_CACHE_STALE", err)
        self.assertTrue(self.target.is_dir())

    def test_write_renders_utf8_lf(self):
        code, out, err = self._generate([])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("MCP_SCHEMA_CACHE_WRITTEN", out)
        self.assertEqual(self.target.read_bytes(), self.generator._render(self.schemas).encode("utf-8"))
        self.assertNotIn(b"\r", self.target.read_bytes())

    def test_release_success_still_requires_native_command(self):
        errors = io.StringIO()
        record = subprocess.CompletedProcess([], 0, "MCP_SCHEMA_CACHE_OK", "")
        with patch.object(self.release.subprocess, "run", return_value=record) as run, contextlib.redirect_stderr(errors):
            self.release._check_schema_cache()
        args, kwargs = run.call_args
        self.assertEqual(args[0], [sys.executable, str(ROOT / "packaging/generate_tool_schemas.py"), "--check"])
        self.assertEqual(kwargs["cwd"], ROOT)
        self.assertTrue(kwargs["capture_output"])
        self.assertFalse(kwargs["check"])
        self.assertEqual(errors.getvalue(), "")

    def test_release_failure_preserves_child_exit_and_streams(self):
        record = subprocess.CompletedProcess([], 1, "synthetic-child-stdout", "MCP_SCHEMA_GENERATION_FAILED stage=native_export\noriginal traceback\n")
        err = self._release_failure(record)
        self.assertIn("MCP_SCHEMA_CHECK_FAILED exit=1", err)
        self.assertIn("MCP_SCHEMA_CHECK_STDOUT:\nsynthetic-child-stdout\n", err)
        self.assertIn("MCP_SCHEMA_CHECK_STDERR:\n" + record.stderr, err)
        self.assertNotIn("cache differs from native provider", err)
        self.assertNotIn("MCP_SCHEMA_CACHE_STALE", err)

    def test_release_stale_preserves_stale_marker(self):
        err = self._release_failure(subprocess.CompletedProcess([], 2, "", "MCP_SCHEMA_CACHE_STALE\n"))
        self.assertIn("MCP_SCHEMA_CHECK_FAILED exit=2", err)
        self.assertIn("MCP_SCHEMA_CHECK_STDERR:\nMCP_SCHEMA_CACHE_STALE\n", err)
        self.assertIn("RELEASE_CONTRACT_FAIL:", err)

    def test_release_launch_failure_does_not_claim_mismatch(self):
        err = self._release_failure(error=OSError("synthetic-launch-failure"))
        self.assertIn("native MCP schema generator could not start (OSError)", err)
        self.assertNotIn("cache differs", err)
        self.assertNotIn("MCP_SCHEMA_CACHE_STALE", err)

    def test_native_gate_wiring_is_unconditional_AST(self):
        release = ast.parse((ROOT / "packaging/verify_release.py").read_bytes())
        main = next(n for n in release.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        direct = [n for n in main.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                  and isinstance(n.value.func, ast.Name) and n.value.func.id == "_check_schema_cache"]
        self.assertEqual(len(direct), 1)
        generator = ast.parse((ROOT / "packaging/generate_tool_schemas.py").read_bytes())
        native = next(n for n in generator.body if isinstance(n, ast.FunctionDef) and n.name == "_runtime_schemas")
        calls = [ast.unparse(n.func) for n in ast.walk(native) if isinstance(n, ast.Call)]
        self.assertIn("spec.loader.exec_module", calls)
        self.assertIn("module.MemoryWikiProvider", calls)
        self.assertIn("module.MemoryWikiProvider().get_tool_schemas", calls)
        self.assertNotIn("--source", (ROOT / "packaging/generate_tool_schemas.py").read_text(encoding="utf-8"))

    def test_extraction_rejects_new_external_dependency_AST(self):
        raw = b'class MemoryWikiProvider:\n def get_tool_schemas(self):\n  return open("not-admitted")\n'
        with self.assertRaisesRegex(ValueError, "no longer self-independent"):
            _declared_schemas(raw)
        raw = b'class MemoryWikiProvider:\n def get_tool_schemas(self):\n  return self.schemas\n'
        with self.assertRaisesRegex(ValueError, "no longer self-independent"):
            _declared_schemas(raw)


if __name__ == "__main__":
    unittest.main()
