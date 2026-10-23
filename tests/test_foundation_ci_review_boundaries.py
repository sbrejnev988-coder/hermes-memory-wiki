"""CI-C01/C02/O01 SOURCE regressions, not SDK/provider lifetime qualification.

Collection controls execute whole test declarations only. Lifetime/order controls
read typed AST; no fake SDK, provider, authority or SQL connection is constructed.
This additive file is also safe to collect/run in a genuine native pytest process.
"""
from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import socket
import sqlite3  # stdlib declaration prerequisite only; never connect here
import sys
import unittest
from unittest.mock import patch
import urllib.error
import xml.etree.ElementTree
from email.message import Message

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'scripts/ci_owned'))
from fixture_prerequisites import SOURCE_SUITES, native_pytest_args, suite_case_ids
from source_suites import run_unittest

EXEC = builtins.exec
G4 = (
    ('tests/test_p2_g4_identity_errors.py', 'G4Tests', '_audit',
     'e144f0f3783cae05a2162aca6cb6e7b4ba4d6b2b5081db6a938296ea0fd302b5'),
    ('tests/test_p2_g4_repair01.py', 'RepairTests', 'audit',
     '495867ac92c71e7edab54d5467fe55772b466950964005b5baed25a353085443'),
)


def tree(relative):
    return ast.parse((SOURCE / relative).read_bytes())


def function(nodes, name):
    matches = [n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) != 1:
        raise AssertionError('exact_function_identity')
    return matches[0]


class ReviewBoundaryControls(unittest.TestCase):
    def test_collection_executes_no_product_import_extraction_or_hook(self):
        # Preload stdlib/CI infrastructure above; reject nested exec as well as
        # product import and irreversible hooks during whole-module collection.
        for index, (relative, _, _, _) in enumerate(G4):
            with self.subTest(file=relative):
                path = SOURCE / relative
                code = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)
                spec = importlib.util.spec_from_file_location('_ci_inert_' + str(index), path)
                module = importlib.util.module_from_spec(spec)
                before_path = list(sys.path)
                try:
                    with patch.object(importlib, 'import_module', side_effect=AssertionError('collection_product_import')), \
                         patch.object(sys, 'addaudithook', side_effect=AssertionError('collection_hook')), \
                         patch.object(builtins, 'exec', side_effect=AssertionError('collection_nested_exec')):
                        EXEC(code, module.__dict__)
                    self.assertIsNone(module.FIX)
                    self.assertIsNone(module.drive)
                    if hasattr(module, 'collapse'):
                        self.assertIsNone(module.collapse)
                    else:
                        self.assertIsNone(module.PUBLIC_RAW)
                        self.assertIsNone(module.public_error)
                finally:
                    sys.path[:] = before_path

    def test_original_fence_precedes_every_product_setup_operation(self):
        for relative, owner, hook_name, hook_sha in G4:
            with self.subTest(file=relative):
                module = tree(relative)
                hook = function(module.body, hook_name)
                self.assertEqual(hashlib.sha256(ast.dump(hook, include_attributes=False).encode()).hexdigest(), hook_sha)
                cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == owner)
                setup = function(cls.body, 'setUpClass')
                statements = [ast.unparse(n) for n in setup.body]
                armed = statements.index('sys.addaudithook(' + hook_name + ')')
                fixture = next(i for i, s in enumerate(statements) if s.startswith('FIX = source_fixture('))
                product_imports = [i for i, s in enumerate(statements) if 'importlib.import_module(' in s]
                self.assertLess(fixture, armed)
                self.assertTrue(product_imports)
                self.assertTrue(all(armed < i for i in product_imports))
                self.assertIn("assert 'agent.memory_provider' not in sys.modules", statements[:armed])
                self.assertTrue(any('drive.__file__' in s for s in statements[armed + 1:]))
                if owner == 'RepairTests':
                    self.assertIn('READ_ROOTS = (SOURCE, FIX, Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve())', statements[:armed])
                    self.assertIn("WRITES = {FIX / 'junit.xml', FIX / 'receipt.json'}", statements[:armed])
                    for i, s in enumerate(statements):
                        if s.startswith(('PUBLIC_RAW =', 'PUBLIC_TREE =', 'exec(')):
                            self.assertLess(armed, i)
                    self.assertTrue(any(s.startswith('exec(') for s in statements))
                else:
                    self.assertTrue(any('collapse.__file__' in s for s in statements[armed + 1:]))

    def test_diff_fixture_binds_genuine_caller_home_and_empty_secret_scope(self):
        module = tree('tests/test_memory_diff_polarity.py')
        imports = [ast.unparse(n) for n in module.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertIn('from agent import secret_scope', imports)
        self.assertIn('import hermes_constants', imports)
        fixture = function(module.body, 'provider')
        text = ast.unparse(fixture)
        self.assertIn("home = OUT / 'home'", text)
        self.assertIn('home_token = hermes_constants.set_hermes_home_override(home)', text)
        self.assertIn('secret_token = secret_scope.set_secret_scope({}, profile_home=str(home))', text)
        initialize = next(n for n in ast.walk(fixture) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'p.initialize')
        self.assertEqual(ast.unparse(next(k.value for k in initialize.keywords if k.arg == 'hermes_home')), 'str(home)')
        self.assertFalse(any(isinstance(n, ast.Call) and 'patch' in ast.unparse(n.func) for n in ast.walk(fixture)))

    def test_diff_tokens_enclose_initialize_yield_shutdown_and_cleanup_assertions(self):
        fixture = function(tree('tests/test_memory_diff_polarity.py').body, 'provider')
        outer = next(n for n in fixture.body if isinstance(n, ast.Try))
        self.assertEqual([ast.unparse(n) for n in outer.finalbody], ['hermes_constants.reset_hermes_home_override(home_token)'])
        self.assertEqual(ast.unparse(outer.body[0]), 'secret_token = secret_scope.set_secret_scope({}, profile_home=str(home))')
        secret = outer.body[1]
        self.assertIsInstance(secret, ast.Try)
        self.assertEqual([ast.unparse(n) for n in secret.finalbody], ['secret_scope.reset_secret_scope(secret_token)'])
        self.assertEqual(ast.unparse(secret.body[0]), 'p = None')
        lifetime = secret.body[1]
        self.assertIsInstance(lifetime, ast.Try)
        self.assertEqual(ast.unparse(lifetime.body[0]), 'p = wiki.MemoryWikiProvider()')
        self.assertEqual(ast.unparse(lifetime.body[-1]), 'yield p')
        self.assertTrue(any(isinstance(n, ast.Call) and ast.unparse(n.func) == 'p.initialize' for n in ast.walk(ast.Module(body=lifetime.body, type_ignores=[]))))
        cleanup = lifetime.finalbody[0]
        self.assertIsInstance(cleanup, ast.If)
        self.assertEqual(ast.unparse(cleanup.test), 'p is not None')
        self.assertEqual([ast.unparse(n) for n in cleanup.body], ['p._shutdown_lifecycle(render=False)', 'assert p._conn is None and p._owned_conn is None'])
        # Both token resets are outside the potentially throwing cleanup/assert,
        # and home reset also encloses secret-scope establishment/reset failure.
        self.assertEqual(len(lifetime.finalbody), 1)
        self.assertEqual(len(secret.body), 2)
        self.assertEqual(len(outer.body), 2)

    def test_pin_migration_is_literal_and_keeps_original_network_denial_tail(self):
        cls = next(n for n in tree(G4[0][0]).body if isinstance(n, ast.ClassDef) and n.name == 'G4Tests')
        test = function(cls.body, 'test_08_direct_boundary_preservation_and_network_denial')
        calls = [n for n in ast.walk(test) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'self.assertEqual']
        pin = next(n for n in calls if n.args and 'hashlib.sha256' in ast.unparse(n.args[0]))
        self.assertIsInstance(pin.args[1], ast.Constant)
        self.assertEqual(pin.args[1].value, '8007b015f204a0b673e7cf41410fe609f60b8151bd39d9042a53336de7fdaf09')
        text = ast.unparse(test)
        self.assertLess(text.index(pin.args[1].value), text.index('socket.socket()'))
        self.assertIn('with self.assertRaises(NetworkDenied):', text)
        self.assertIn("self.assertEqual(NETWORK_EVENTS, [{'event': 'socket.__new__', 'expected': True}])", text)
        for relative, expected in [
            ('tests/fixtures/g4_original_boundary_gold.txt', 'bea163fe1ccbfd1963946e255abe9affcd73a148d1be9dae1a891b2f6b5476b8'),
            ('tests/fixtures/g4_metadata_scope.txt', '260e167dfccf4abcd129baf18edfe777198ac841147f53df16e237cfa3fb937f'),
        ]:
            self.assertEqual(hashlib.sha256((SOURCE / relative).read_bytes()).hexdigest(), expected)

    def test_non_sql_subset_cannot_authorize_full_source_or_native_continuation(self):
        self.assertEqual(list(SOURCE_SUITES.values()), [('G4Tests', 8), ('RepairTests', 2), ('PrerequisiteControls', 10)])
        # Synthetic validator inputs, not fabricated execution evidence.
        rows = {relative: {'sha256': hashlib.sha256((SOURCE / relative).read_bytes()).hexdigest(),
                          'exit_code': 0, 'total': count, 'passed': count, 'failed': 0, 'errors': 0,
                          'skipped': 0, 'case_ids': suite_case_ids(SOURCE, relative)}
                for relative, (_, count) in SOURCE_SUITES.items()}
        relative = G4[0][0]
        row = rows[relative]
        sql = '__main__.G4Tests.test_03_legacy_and_real_fts_acl_hidden_count_negative'
        self.assertIn(sql, row['case_ids'])
        row['case_ids'].remove(sql)
        row['total'] = row['passed'] = 7
        with self.assertRaisesRegex(RuntimeError, '^source_suite_not_qualified:'):
            native_pytest_args(SOURCE, rows)
        method = function(next(n for n in tree(relative).body if isinstance(n, ast.ClassDef) and n.name == 'G4Tests').body,
                          'test_03_legacy_and_real_fts_acl_hidden_count_negative')
        self.assertIn("sqlite3.connect(':memory:')", ast.unparse(method))
        self.assertEqual(method.decorator_list, [])

    def test_correction_sources_compile_without_sdk_or_sql_execution(self):
        for relative in [*(row[0] for row in G4), 'tests/test_memory_diff_polarity.py',
                         'tests/test_foundation_ci_prerequisites.py', 'tests/test_foundation_ci_review_boundaries.py']:
            with self.subTest(file=relative):
                compile((SOURCE / relative).read_bytes(), str(SOURCE / relative), 'exec', dont_inherit=True)


if __name__ == '__main__':
    raise SystemExit(run_unittest(ReviewBoundaryControls, expected=7))
