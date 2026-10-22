"""Один будущий SOURCE packet public PDF/OCR options, не native provider.

Collection инертна: target/peer reads, exec и fixtures начинаются только после
main admission и штатного source_bootstrap audit fence. Pytest не выбирает класс;
фактическая collection NOT_RUN. Старые peer cases не выбираются и не повторяются.
Schema carriers — точные owning-method spans, не SDK/provider stand-ins. Их полные
originating Git blob/raw/span/AST pins приведены ниже и в lane PREPARE.json.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

__test__ = False

CASE_IDS = (
    "test_full_ingest_scan_schemas_and_unrelated_preservation",
    "test_legacy_no_args_and_trusted_environment_defaults",
    "test_explicit_forwarding_and_owner_ceiling_inverses",
    "test_invalid_types_enums_psm_and_canonical_bounds",
    "test_native_capabilities_not_public_or_request_forwarded",
    "test_actual_effective_dict_and_fingerprint_same_vs_different",
    "test_scan_and_ingest_owner_wiring_STATIC",
)
ENUM_SPECS = {
    "pdf_parser": ("auto", "pymupdf", "pypdf"),
    "pdf_mode": ("blocks", "pages"),
    "pdf_reading_order": ("layout", "source"),
    "pdf_table_strategy": ("lines", "lines_strict", "text"),
}
INTEGER_SPECS = {
    "pdf_max_blocks_per_page": (2000, 1, 20000),
    "pdf_max_tables_per_page": (32, 1, 1000),
    "ocr_min_chars": (8, 1, 10000), "ocr_dpi": (200, 72, 400),
    "ocr_max_pixels": (20000000, 1000000, 100000000),
    "ocr_max_pages": (100, 1, 10000), "ocr_max_tsv_rows": (100000, 1, 1000000),
    "ocr_min_native_chars": (40, 0, 10000),
    "max_units": (100000, 1, 1000000), "max_cells": (500000, 1, 5000000),
    "max_pages": (10000, 1, 100000), "max_chars": (100000000, 1000, 500000000),
    "external_timeout": (90, 1, 900),
}
PUBLIC_TYPES = {**{key: str for key in ENUM_SPECS},
                **{key: int for key in INTEGER_SPECS},
                "pdf_tables": bool, "pdf_native_fallback": bool, "ocr_psm": str}
LEGACY_DEFAULTS = {
    **{key: values[0] for key, values in ENUM_SPECS.items()},
    **{key: values[0] for key, values in INTEGER_SPECS.items()},
    "pdf_tables": True, "pdf_native_fallback": True,
    "max_bytes": 134217728, "zip_max_entries": 50000, "zip_expansion_factor": 8,
    "zip_max_ratio": 200, "zip_max_member": 16777216,
    "ocr": False, "ocr_language": "eng+rus", "ocr_psm": "3",
    "tesseract_bin": "tesseract", "tika_url": "",
}
# prefix + raw origin[span_bytes[0]:span_bytes[1]], without dedent/unparse.
SCHEMA_PREFIX = b"from __future__ import annotations\n\nclass MemoryWikiProvider:\n"
SCHEMA_PINS = {'baseline': {'origin_path': '__init__.py', 'origin_B': 1521084, 'origin_sha256': 'f7c896a12a43dff50de99d45b02c496ccf1eabe00c9afc834a8b6d2f59182985', 'origin_blob': '68fc7b56cb497e695cb53437d76317a5253cb1d6', 'owner': 'MemoryWikiProvider.get_tool_schemas', 'class_line': 7330, 'lines': [10144, 10276], 'columns': [4, 1242], 'span_bytes': [517473, 561486], 'span_sha256': '7c23c0661f55f8a50b6090cf767ec413316b16048f245f10b08236e2a931cac8', 'ast_sha256': 'ed6795539c5927ca15be39dd5aa8c3f51ac2c4f68063131ec7e52c78e0e4f2ea', 'carrier_B': 44075, 'carrier_sha256': 'd8d0439e62c8190871aac9f22dc80471b7c29c35be7ea563d44a0c9284541f24', 'carrier_prefix_lines': 3}, 'candidate': {'origin_path': '__init__.py', 'origin_B': 1523853, 'origin_sha256': '88bc9bf4b48fe21d42e529838ee0e34bc7682abffdc03b0a8bc6e17ecc96578d', 'origin_blob': 'a1ed6307800b54a104756155b54104e06e97d922', 'owner': 'MemoryWikiProvider.get_tool_schemas', 'class_line': 7330, 'lines': [10144, 10307], 'columns': [4, 1242], 'span_bytes': [517473, 564255], 'span_sha256': 'e0ba28117fd6bb50b44e6b54cfe7760f62b5896501ea1f975c2be44eb5561ee3', 'ast_sha256': '37704dffe8ffbe23b37d19f995b323ca9c5d890c3b1bc60e2dc9a92deabc687a', 'carrier_B': 46844, 'carrier_sha256': '0e66cb8e6f11043a8b0554e01bc500cb26c0bd5424c8b5f129bd1906ed251efd', 'carrier_prefix_lines': 3}}


class DocumentPublicOptionsSourceTests(unittest.TestCase):
    __test__ = False

    @classmethod
    def setUpClass(cls):
        # main has checked the original bound reader and own scratch BEFORE
        # this first product read/exec. Reuse the shipped peer loader unchanged.
        cls.inputs = globals()["DEVTOOLS_INPUTS"]
        cls.scratch = Path(globals()["DEVTOOLS_SCRATCH"])
        cls.observations = {}
        names = ("spreadsheet_formulas", "document_extractors", "guard",
                 "document_knowledge_graph", "public_options_baseline_schema",
                 "public_options_candidate_schema")
        if any(name in sys.modules for name in names):
            raise RuntimeError("fresh_source_namespaces_required")
        cls.addClassCleanup(cls.peer.MODULES.clear)
        for name in names:
            cls.addClassCleanup(sys.modules.pop, name, None)
        cls.e = cls.peer.load_source(cls.peer.EXTRACTOR, "document_extractors")
        cls.guard = cls.peer.load_source(Path(cls.inputs["guard.py"]), "guard")
        cls.g = cls.peer.load_source(Path(cls.inputs["document_knowledge_graph.py"]),
                                     "document_knowledge_graph")
        cls.schema_modules = {
            role: cls.peer.load_source(Path(cls.inputs["public_options_" + role + "_schema.py"]),
                                       "public_options_" + role + "_schema")
            for role in ("baseline", "candidate")
        }
        if cls.e.evaluate_cells is not sys.modules["spreadsheet_formulas"].evaluate_cells:
            raise RuntimeError("real_bound_formula_helper_required")
        if cls.g._sanitize_untrusted_text is not cls.guard.sanitize_context_text:
            raise RuntimeError("real_bound_guard_required")
        if cls.g._sanitize_extracted_json is not cls.e.sanitize_json:
            raise RuntimeError("real_bound_extractor_required")

    def setUp(self):
        # Only the admitted sterile child environment is touched, never .env.
        def owned_key(key):
            return key.startswith("MEMORY_WIKI_DOCUMENT_") or key in {
                "MEMORY_WIKI_TESSERACT_BIN", "MEMORY_WIKI_OCR_PSM", "MEMORY_WIKI_TIKA_URL"}
        saved = {key: value for key, value in os.environ.items() if owned_key(key)}
        def restore():
            for key in list(os.environ):
                if owned_key(key):
                    os.environ.pop(key)
            os.environ.update(saved)
        self.addCleanup(restore)
        for key in saved:
            os.environ.pop(key)
        self.observations[self._testMethodName] = {"cleanup_complete": False}
        self.addCleanup(self.observations[self._testMethodName].__setitem__, "cleanup_complete", True)
        self.assertIsNone(self.g._DOCUMENT_PROFILE_SCOPE.get())

    def schemas(self, role="candidate"):
        # A plain object deliberately has no provider state or SDK authority.
        return self.schema_modules[role].MemoryWikiProvider.get_tool_schemas(object())

    def test_full_ingest_scan_schemas_and_unrelated_preservation(self):
        for role, pin in SCHEMA_PINS.items():
            path = self.inputs["public_options_" + role + "_schema.py"]
            raw = devtools_read_bound(path)
            self.assertEqual(len(raw), pin["carrier_B"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), pin["carrier_sha256"])
            self.assertTrue(raw.startswith(SCHEMA_PREFIX))
            span = raw[len(SCHEMA_PREFIX):]
            self.assertEqual(len(span), pin["span_bytes"][1] - pin["span_bytes"][0])
            self.assertEqual(hashlib.sha256(span).hexdigest(), pin["span_sha256"])
            tree = ast.parse(raw, filename=path)
            owners = [n for n in tree.body if isinstance(n, ast.ClassDef)]
            self.assertEqual([n.name for n in owners], ["MemoryWikiProvider"])
            methods = [n for n in owners[0].body if isinstance(n, ast.FunctionDef)]
            self.assertEqual([n.name for n in methods], ["get_tool_schemas"])
            method = methods[0]
            self.assertEqual(hashlib.sha256(ast.dump(method, include_attributes=False).encode()).hexdigest(),
                             pin["ast_sha256"])
            self.assertEqual(method.lineno, pin["carrier_prefix_lines"] + 1)
            self.assertEqual(method.end_lineno - method.lineno, pin["lines"][1] - pin["lines"][0])
            self.assertEqual([method.col_offset, method.end_col_offset], pin["columns"])
            self.assertFalse(any(isinstance(n, ast.Name) and n.id == "self" and isinstance(n.ctx, ast.Load)
                                 for n in ast.walk(method)))
        before, after = self.schemas("baseline"), self.schemas()
        self.assertEqual([row["name"] for row in after], [row["name"] for row in before])
        self.assertEqual(len({row["name"] for row in after}), len(after))
        documents = {"memory_wiki_document_ingest", "memory_wiki_document_scan"}
        for old, new in zip(before, after):
            if old["name"] not in documents:
                self.assertEqual(new, old, old["name"])
                continue
            restored = copy.deepcopy(new)
            original_props = old["parameters"]["properties"]
            props = restored["parameters"]["properties"]
            added = set(PUBLIC_TYPES) | ({"ocr_language"} if old["name"].endswith("_scan") else set())
            self.assertEqual(set(props) - set(original_props), added)
            for key in set(props) - set(original_props):
                del props[key]
            self.assertEqual(restored, old)
        entries = {row["name"]: row for row in after}
        shared = set(PUBLIC_TYPES) | {"ocr", "ocr_language"}
        ingest = entries["memory_wiki_document_ingest"]["parameters"]["properties"]
        scan = entries["memory_wiki_document_scan"]["parameters"]["properties"]
        self.assertEqual({key: ingest[key] for key in shared}, {key: scan[key] for key in shared})
        for key, expected_type in PUBLIC_TYPES.items():
            spec = ingest[key]
            self.assertEqual(spec["type"], {str: "string", int: "integer", bool: "boolean"}[expected_type], key)
            self.assertIs(type(spec["default"]), expected_type, key)
            self.assertEqual(spec["default"], LEGACY_DEFAULTS[key], key)
        for key, (default, low, high) in INTEGER_SPECS.items():
            self.assertEqual((ingest[key]["default"], ingest[key]["minimum"], ingest[key]["maximum"]),
                             (default, low, high), key)
        for key, values in ENUM_SPECS.items():
            self.assertEqual(ingest[key]["enum"], list(values), key)
        self.assertEqual(ingest["ocr_psm"]["enum"], [str(n) for n in range(14)])

    def test_legacy_no_args_and_trusted_environment_defaults(self):
        self.assertEqual(self.g._worker_options({}), LEGACY_DEFAULTS)
        os.environ.update({
            "MEMORY_WIKI_DOCUMENT_MAX_BYTES": "2000000",
            "MEMORY_WIKI_DOCUMENT_MAX_UNITS": "321", "MEMORY_WIKI_DOCUMENT_MAX_CELLS": "654",
            "MEMORY_WIKI_DOCUMENT_MAX_PAGES": "12", "MEMORY_WIKI_DOCUMENT_MAX_CHARS": "12345",
            "MEMORY_WIKI_DOCUMENT_ZIP_MAX_ENTRIES": "23", "MEMORY_WIKI_DOCUMENT_ZIP_EXPANSION": "3",
            "MEMORY_WIKI_DOCUMENT_ZIP_MAX_RATIO": "8", "MEMORY_WIKI_DOCUMENT_ZIP_MAX_MEMBER_BYTES": "1048576",
            "MEMORY_WIKI_DOCUMENT_OCR": "1", "MEMORY_WIKI_DOCUMENT_OCR_LANGUAGE": "rus+eng",
            "MEMORY_WIKI_DOCUMENT_OCR_MIN_NATIVE_CHARS": "17",
            "MEMORY_WIKI_DOCUMENT_EXTERNAL_TIMEOUT": "11",
            "MEMORY_WIKI_TESSERACT_BIN": "owner-tesseract", "MEMORY_WIKI_OCR_PSM": "6",
            "MEMORY_WIKI_TIKA_URL": "http://127.0.0.1:9998/tika",
        })
        expected = {**LEGACY_DEFAULTS, "max_bytes": 2000000, "max_units": 321, "max_cells": 654,
                    "max_pages": 12, "max_chars": 12345, "zip_max_entries": 23, "zip_expansion_factor": 3,
                    "zip_max_ratio": 8, "zip_max_member": 1048576, "ocr": True, "ocr_language": "rus+eng",
                    "ocr_min_native_chars": 17, "external_timeout": 11, "ocr_psm": "6",
                    "tesseract_bin": "owner-tesseract", "tika_url": "http://127.0.0.1:9998/tika"}
        self.assertEqual(self.g._worker_options({}), expected)
        self.assertEqual(self.g._worker_options({"ocr": False, "ocr_language": ""}), {**expected, "ocr": False})
        # Real existing profile-local ENV reader, no profile file or provider fake.
        token = self.g._DOCUMENT_PROFILE_SCOPE.set({"home": self.scratch / "home", "strict": True,
                                                   "settings": {"MEMORY_WIKI_DOCUMENT_MAX_UNITS": "222"}})
        try:
            local = self.g._worker_options({"max_units": 999})
            self.assertEqual(local["max_units"], 222)
            self.assertEqual(local["max_cells"], LEGACY_DEFAULTS["max_cells"])
            self.assertEqual(local["tika_url"], "")
        finally:
            self.g._DOCUMENT_PROFILE_SCOPE.reset(token)

    def test_explicit_forwarding_and_owner_ceiling_inverses(self):
        self.assertEqual(self.g._PUBLIC_EXTRACTION_OPTION_TYPES, PUBLIC_TYPES)
        supplied = {"pdf_parser": "pypdf", "pdf_mode": "pages", "pdf_reading_order": "source",
                    "pdf_tables": False, "pdf_native_fallback": False, "pdf_table_strategy": "text",
                    "pdf_max_blocks_per_page": 3, "pdf_max_tables_per_page": 2,
                    "ocr_min_chars": 9, "ocr_dpi": 300, "ocr_max_pixels": 2000000,
                    "ocr_max_pages": 2, "ocr_max_tsv_rows": 31, "ocr_min_native_chars": 0,
                    "ocr_psm": "6", "max_units": 17, "max_cells": 19, "max_pages": 3,
                    "max_chars": 3000, "external_timeout": 1}
        self.assertEqual(set(supplied), set(PUBLIC_TYPES))
        self.assertEqual(self.g._worker_options(supplied), {**LEGACY_DEFAULTS, **supplied})
        ceilings = {"max_units": 150, "max_cells": 240, "max_pages": 7, "max_chars": 12000,
                    "external_timeout": 9}
        for key, ceiling in ceilings.items():
            env = "MEMORY_WIKI_DOCUMENT_" + key.upper()
            os.environ[env] = str(ceiling)
        owned = self.g._worker_options({})
        self.assertEqual(owned, {**LEGACY_DEFAULTS, **ceilings})
        lower = {"max_units": 10, "max_cells": 20, "max_pages": 2, "max_chars": 3000, "external_timeout": 1}
        self.assertEqual(self.g._worker_options(lower), {**owned, **lower})
        for key, ceiling in ceilings.items():
            self.assertEqual(self.g._worker_options({key: ceiling}), owned, key)
            self.assertEqual(self.g._worker_options({key: ceiling + 1}), owned, key)
            self.assertEqual(self.g._worker_options({key: 10 ** 50}), owned, key)
            low = INTEGER_SPECS[key][1]
            self.assertEqual(self.g._worker_options({key: -1}), {**owned, key: low}, key)

    def test_invalid_types_enums_psm_and_canonical_bounds(self):
        for key, expected_type in PUBLIC_TYPES.items():
            invalid = (False, True, "1", 1.0, None) if expected_type is int else (
                (0, 1, "false", None) if expected_type is bool else (False, 1, [], None))
            for value in invalid:
                with self.assertRaisesRegex(ValueError, "^invalid " + key + "$"):
                    self.g._worker_options({key: value})
        for key in ENUM_SPECS:
            with self.assertRaisesRegex(ValueError, "^invalid " + key + "$"):
                self.g._worker_options({key: "imaginary"})
        for value in ("14", "-1", "03", "6\n", ""):
            with self.assertRaisesRegex(ValueError, "^invalid ocr_psm$"):
                self.g._worker_options({"ocr_psm": value})
        for n in range(14):
            self.assertEqual(self.g._worker_options({"ocr_psm": str(n)})["ocr_psm"], str(n))
        for key, (_, low, high) in INTEGER_SPECS.items():
            self.assertEqual(self.g._worker_options({key: low - 1})[key], low, key)
            wanted = min(high, LEGACY_DEFAULTS[key]) if key.startswith("max_") or key == "external_timeout" else high
            self.assertEqual(self.g._worker_options({key: high + 1})[key], wanted, key)
        for language in ("../private", "eng\nrus", "x" * 257):
            with self.assertRaisesRegex(ValueError, "^invalid ocr_language$"):
                self.g._worker_options({"ocr_language": language})
        self.assertEqual(self.g._worker_options({"ocr_language": "script/Latin+eng"})["ocr_language"],
                         "script/Latin+eng")

    def test_native_capabilities_not_public_or_request_forwarded(self):
        forbidden = {"tesseract_bin": "request-executable", "tika_url": "http://remote.invalid/tika",
                     "max_bytes": 1, "zip_max_entries": 1, "zip_expansion_factor": 100,
                     "zip_max_ratio": 10000, "zip_max_member": 999999999,
                     "worker_timeout": 999, "worker_memory_mb": 999,
                     "embedding_model": "request-route", "owner_bot_id": "foreign"}
        for row in self.schemas():
            if row["name"] in {"memory_wiki_document_ingest", "memory_wiki_document_scan"}:
                self.assertTrue(set(forbidden).isdisjoint(row["parameters"]["properties"]))
        self.assertEqual(self.g._worker_options(forbidden), LEGACY_DEFAULTS)
        os.environ["MEMORY_WIKI_TESSERACT_BIN"] = "trusted-owner-executable"
        os.environ["MEMORY_WIKI_TIKA_URL"] = "http://127.0.0.1:9998/tika"
        self.assertEqual(self.g._worker_options(forbidden),
                         {**LEGACY_DEFAULTS, "tesseract_bin": "trusted-owner-executable",
                          "tika_url": "http://127.0.0.1:9998/tika"})

    def test_actual_effective_dict_and_fingerprint_same_vs_different(self):
        e, g = self.e, self.g
        defaults = g._worker_options({})
        explicit = g._worker_options({key: LEGACY_DEFAULTS[key] for key in PUBLIC_TYPES})
        self.assertEqual(explicit, defaults)
        self.assertEqual(e.effective_extraction_options(explicit), explicit)
        for suffix in (".pdf", ".png", ".xlsx", ".txt"):
            path = self.scratch / ("not-opened" + suffix)
            self.assertEqual(e.extraction_options_fingerprint(path, explicit),
                             e.extraction_options_fingerprint(path, defaults))
        pdf, image, text = (self.scratch / ("not-opened" + ext) for ext in (".pdf", ".png", ".txt"))
        fp = e.extraction_options_fingerprint(pdf, defaults)
        changes = {"pdf_parser": "pypdf", "pdf_mode": "pages", "pdf_reading_order": "source",
                   "pdf_tables": False, "pdf_native_fallback": False, "pdf_table_strategy": "text",
                   "pdf_max_blocks_per_page": 3, "pdf_max_tables_per_page": 2,
                   "ocr_min_native_chars": 0, "max_units": 17, "max_cells": 19,
                   "max_pages": 3, "max_chars": 3000}
        for key, value in changes.items():
            options = g._worker_options({key: value})
            self.assertNotEqual(options, defaults, key)
            self.assertNotEqual(e.extraction_options_fingerprint(pdf, options), fp, key)
        for path, axes in ((pdf, {"ocr_min_chars": 9, "ocr_dpi": 300, "ocr_max_pixels": 2000000,
                                  "ocr_max_pages": 2, "ocr_language": "rus+eng"}),
                           (image, {"ocr_psm": "6", "ocr_max_tsv_rows": 31,
                                    "ocr_min_chars": 9, "ocr_language": "eng"})):
            enabled = g._worker_options({"ocr": True})
            for key, value in axes.items():
                changed = g._worker_options({"ocr": True, key: value})
                self.assertNotEqual(e.extraction_options_fingerprint(path, changed),
                                    e.extraction_options_fingerprint(path, enabled), key)
        timed = g._worker_options({"external_timeout": 1})
        self.assertNotEqual(timed, defaults)
        self.assertEqual(e.extraction_options_fingerprint(pdf, timed), fp)
        irrelevant = g._worker_options({"pdf_mode": "pages", "ocr": True})
        self.assertEqual(e.extraction_options_fingerprint(text, irrelevant),
                         e.extraction_options_fingerprint(text, defaults))
        equivalent = g._worker_options({"ocr_dpi": 9999})
        self.assertEqual(equivalent, g._worker_options({"ocr_dpi": 400}))
        self.assertEqual(e.extraction_options_fingerprint(pdf, equivalent), fp)  # OCR disabled

    def test_scan_and_ingest_owner_wiring_STATIC(self):
        raw = devtools_read_bound(self.inputs["document_knowledge_graph.py"])
        tree = ast.parse(raw)
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        scan = functions["scan_documents"]
        assignments = [n for n in scan.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "stat_fast_path" for t in n.targets)]
        self.assertEqual(len(assignments), 1)
        expected = ast.parse('bool(args.get("stat_fast_path", False)) and '
                             '_env_bool("MEMORY_WIKI_DOCUMENT_ALLOW_STAT_FAST_PATH", False) and '
                             'not any(key in args for key in (*_PUBLIC_EXTRACTION_OPTION_TYPES, "ocr", "ocr_language"))',
                             mode="eval").body
        self.assertEqual(ast.dump(assignments[0].value), ast.dump(expected))
        # Presence, not truthiness: this STATIC expression covers False/0/default too.
        loop = next(n for n in scan.body if isinstance(n, ast.For) and isinstance(n.target, ast.Name)
                    and n.target.id == "path")
        checks = [n for n in ast.walk(loop) if isinstance(n, ast.If) and isinstance(n.test, ast.BoolOp)
                  and isinstance(n.test.values[0], ast.Name) and n.test.values[0].id == "stat_fast_path"]
        self.assertEqual(len(checks), 1)
        veto = ast.parse('path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx"}', mode="eval").body
        self.assertTrue(any(ast.dump(n) == ast.dump(veto) for n in checks[0].test.values))
        source = ast.unparse(scan)
        self.assertIn("item_args = dict(args)", source)
        self.assertIn("item_args['path'] = str(path)", source)
        self.assertIn("ingest_document(provider, item_args)", source)
        ingest = functions["ingest_document"]
        calls = {name: [n for n in ast.walk(ingest) if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name) and n.func.id == name]
                 for name in ("_allowed_path", "_document_access_scope", "_worker_options",
                              "extraction_options_fingerprint", "_extract")}
        self.assertTrue(all(len(nodes) == 1 for nodes in calls.values()))
        self.assertLess(calls["_allowed_path"][0].lineno, calls["_worker_options"][0].lineno)
        self.assertLess(calls["_document_access_scope"][0].lineno, calls["_worker_options"][0].lineno)
        self.assertEqual(ast.unparse(calls["_worker_options"][0]), "_worker_options(args)")
        self.assertEqual(ast.unparse(calls["extraction_options_fingerprint"][0]),
                         "extraction_options_fingerprint(path, options)")
        self.assertEqual(ast.unparse(calls["_extract"][0]),
                         "_extract(snapshot, {**args, '_effective_extraction_options': options})")
        for guard in ("_assert_connector_owner", "_assert_ingest_source_scope", "_assert_ingest_path_alias_owner"):
            guards = [n for n in ast.walk(ingest) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Name) and n.func.id == guard]
            self.assertTrue(any(n.lineno < calls["_worker_options"][0].lineno for n in guards), guard)
        self.assertIn("args.get('_effective_extraction_options') or _worker_options(args)",
                      ast.unparse(functions["_extract"]))
        normalizers = [n for n in ast.walk(functions["_worker_options"]) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Name) and n.func.id == "effective_extraction_options"]
        self.assertEqual(len(normalizers), 1)
        self.observations[self._testMethodName]["qualification"] = "STATIC: SQL/owner/scan/worker NOT_RUN"


def main():
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        raise RuntimeError("original_isolated_source_bootstrap_required")
    required = ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound", "devtools_case_started")
    if any(key not in globals() for key in required):
        raise RuntimeError("finite_source_admission_and_original_bound_reader_required")
    scratch = Path(DEVTOOLS_SCRATCH)
    if not scratch.is_absolute() or not scratch.is_dir():
        raise RuntimeError("own_absolute_scratch_required")
    for key in ("HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HERMES_HOME", "TEMP", "TMP", "TMPDIR"):
        if not Path(os.environ[key]).is_relative_to(scratch):
            raise RuntimeError("sterile_child_environment_required")
    name = "public_options_original_bound_peer"
    if name in sys.modules:
        raise RuntimeError("fresh_bound_peer_required")
    path = DEVTOOLS_INPUTS["test_document_parser_pdf_ocr.py"]
    before_path, before_env = list(sys.path), dict(os.environ)
    spec = importlib.util.spec_from_file_location(name, path)
    peer = importlib.util.module_from_spec(spec)
    for key in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound"):
        peer.__dict__[key] = globals()[key]
    try:
        sys.modules[name] = peer
        raw = devtools_read_bound(path)
        exec(compile(raw, path, "exec", dont_inherit=True), peer.__dict__)
        DocumentPublicOptionsSourceTests.peer = peer
        reporters = [n for n in ast.walk(ast.parse(raw, filename=path))
                     if isinstance(n, ast.ClassDef) and n.name == "PacketResult"]
        if len(reporters) != 1:
            raise RuntimeError("unique_original_peer_reporter_required")
        namespace = {"__name__": "public_options_bound_reporter", "unittest": unittest,
                     "devtools_case_started": devtools_case_started}
        exec(compile(ast.Module(body=reporters, type_ignores=[]), path, "exec", dont_inherit=True), namespace)
        result = namespace["PacketResult"]()
        unittest.TestSuite(DocumentPublicOptionsSourceTests(case) for case in CASE_IDS).run(result)
    finally:
        sys.modules.pop(name, None)
    released = all(key not in sys.modules for key in (
        name, "spreadsheet_formulas", "document_extractors", "guard", "document_knowledge_graph",
        "public_options_baseline_schema", "public_options_candidate_schema"))
    observations = DocumentPublicOptionsSourceTests.observations
    clean = released and sys.path == before_path and dict(os.environ) == before_env
    clean = clean and len(observations) == len(CASE_IDS) and all(v["cleanup_complete"] for v in observations.values())
    complete = [row["id"] for row in result.rows] == list(CASE_IDS)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": result.rows,
        "observations": observations, "lifecycle": {"source_modules_released": released,
        "environment_and_path_restored": sys.path == before_path and dict(os.environ) == before_env},
        "qualification": "6 SOURCE callable mains +1 STATIC wiring main; no scan/ingest SQL, SDK, native, engine, full-suite or installed proof"},
        separators=(",", ":")))
    return 0 if result.wasSuccessful() and clean and complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
