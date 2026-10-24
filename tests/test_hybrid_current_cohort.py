"""Explicit SOURCE compatibility controls; no G4/EOL/native test-body replay.

Complete current bytes and retained prior transports are supplied by the existing
SOURCE packet. Collection is inert. AST gold remains parser-specific; only the
single current G4 literal is inverted before the original fingerprint producer.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
import unittest

__test__ = False
G4 = 'tests/test_p2_g4_identity_errors.py'
EOL = 'tests/test_ci_checkout_eol.py'
PREREQ = 'tests/test_foundation_ci_prerequisites.py'
REVIEW = 'tests/test_foundation_ci_review_boundaries.py'
HYBRID = 'tests/test_hybrid_budget_observability_source.py'
SELF = 'tests/test_hybrid_current_cohort.py'
OLD_PIN = '8007b015f204a0b673e7cf41410fe609f60b8151bd39d9042a53336de7fdaf09'
CURRENT_PIN = '44cdca1b753f13650fcb9c9fb9bdec9192a9f7c11cdffbe91163abe64dd02805'
OLD_CRLF = '6c1de6f456837b6c8e0bebe1e54e7030771c811bfd2191af4857cfee0e102479'
CURRENT_CRLF = 'cdf6ccc05ece2d823522203656308581dd9b0db4829f963c7b499d285aacb5dc'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def assignment(raw, name):
    nodes = [n for n in ast.parse(raw).body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    if len(nodes) != 1:
        raise ValueError('exact_assignment_required')
    return ast.literal_eval(nodes[0].value)


def methods(raw):
    return [ast.dump(n, include_attributes=False) for n in ast.walk(ast.parse(raw))
            if isinstance(n, ast.FunctionDef) and n.name.startswith('test')]


class HybridCurrentCohortTests(unittest.TestCase):
    __test__ = False
    context = None

    @classmethod
    def setUpClass(cls):
        if cls.context is None:
            raise RuntimeError('explicit_current_and_retained_inputs_required')
        cls.inputs, cls.retained, cls.original, cls.cold, cls.hybrid_entry = cls.context

    def setUp(self):
        self.plan = copy.deepcopy(self.original)
        self.raw = dict(self.inputs)

    def row(self, path):
        return next(r for r in self.plan['partition'] if r['path'] == path)

    def refresh(self):
        self.plan['file_count'] = len(self.plan['partition'])
        self.plan['input_inventory_sha256'] = self.cold.partition_digest(self.plan['partition'])
        self.plan['source_explicit_targets'] = [r['path'] for r in self.plan['partition'] if r['lane'] == 'source-explicit']
        for lane in ('strict', 'legacy'):
            self.plan['cold_processes'][lane]['targets'] = [r['path'] for r in self.plan['partition'] if r['lane'] == lane]

    def reject(self, message):
        with self.assertRaisesRegex(ValueError, '^' + message + '$'):
            self.cold.validate_partition(self.plan, self.raw)

    def recipe(self):
        # Execute only these two genuine pure test-owned recipes. No module
        # collection, product imports, SQL or full historical G4 test execution.
        tree = ast.parse(self.raw[PREREQ])
        names = {'historical_method_dumps', 'original_tests_for_runtime'}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual({n.name for n in nodes}, names)
        namespace = {'ast': ast, 'copy': copy}
        for name in ('ORIGINAL_TESTS', 'ORIGINAL_TESTS_311', 'ORIGINAL_TESTS_312'):
            namespace[name] = assignment(self.raw[PREREQ], name)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<genuine-current-pin-inverse>', 'exec'), namespace)
        return namespace

    def test_01_current_LF_and_CRLF_pins_use_exact_accepted_runtime(self):
        raw = self.raw['__init__.py']
        public = assignment(self.raw[EOL], 'PUBLIC')
        self.assertNotIn(b'\r', raw)
        self.assertEqual(sha(raw), CURRENT_PIN)
        self.assertEqual(sha(raw.replace(b'\n', b'\r\n')), CURRENT_CRLF)
        self.assertEqual(public['__init__.py'], (CURRENT_PIN, CURRENT_CRLF))
        self.assertNotEqual(public['__init__.py'], assignment(self.retained[EOL], 'PUBLIC')['__init__.py'])

    def test_02_G4_literal_inverse_preserves_whole_raw_and_network_tail(self):
        raw = self.raw[G4]
        self.assertEqual(raw.count(CURRENT_PIN.encode()), 1)
        inverse = raw.replace(CURRENT_PIN.encode(), OLD_PIN.encode(), 1)
        self.assertEqual(inverse, self.retained[G4])
        restored = self.recipe()['historical_method_dumps'](ast.parse(raw), G4.split('/')[-1])
        self.assertEqual(restored, methods(self.retained[G4]))
        self.assertIn(b'socket.socket()', inverse)
        self.assertIn(b"self.assertNotIn('agent.memory_provider',sys.modules)", inverse)

    def test_03_EOL_and_review_inverses_keep_every_other_byte(self):
        for path in (EOL, REVIEW):
            with self.subTest(path=path):
                raw = self.raw[path]
                self.assertEqual(raw.count(CURRENT_PIN.encode()), 1)
                inverse = raw.replace(CURRENT_PIN.encode(), OLD_PIN.encode(), 1)
                if path == EOL:
                    self.assertEqual(raw.count(CURRENT_CRLF.encode()), 1)
                    inverse = inverse.replace(CURRENT_CRLF.encode(), OLD_CRLF.encode(), 1)
                self.assertEqual(inverse, self.retained[path])

    def test_04_historical_gold_and_original_profile_literals_unchanged(self):
        for name in ('ORIGINAL_TESTS', 'ORIGINAL_TESTS_311', 'ORIGINAL_TESTS_312'):
            self.assertEqual(assignment(self.raw[PREREQ], name), assignment(self.retained[PREREQ], name))
        public = assignment(self.raw[EOL], 'PUBLIC')
        old = assignment(self.retained[EOL], 'PUBLIC')
        for path in ('tests/fixtures/g4_original_boundary_gold.txt', 'tests/fixtures/g4_metadata_scope.txt'):
            self.assertEqual(public[path], old[path])
            self.assertEqual(sha(self.raw[path]), public[path][0])
            self.assertEqual(sha(self.raw[path].replace(b'\n', b'\r\n')), public[path][1])

    def test_05_original_fingerprint_producer_after_typed_inverse(self):
        recipe = self.recipe()
        gold = recipe['original_tests_for_runtime'](sys.implementation.name, tuple(sys.version_info[:2]))
        for name, expected in gold.items():
            with self.subTest(file=name):
                current = ast.parse(self.raw['tests/' + name])
                dumps = recipe['historical_method_dumps'](current, name)
                actual = sha(json.dumps(sorted(dumps), ensure_ascii=True).encode())
                self.assertEqual(actual, expected)
        # Caller retains the original sort/ASCII/default separators/SHA recipe.
        owner = next(n for n in ast.parse(self.raw[PREREQ]).body if isinstance(n, ast.ClassDef) and n.name == 'PrerequisiteControls')
        method = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'test_historical_test_bodies_are_byte_semantic_preserved')
        text = ast.unparse(method)
        self.assertIn("methods = historical_method_dumps(tree('tests/' + name), name)", text)
        self.assertIn('hashlib.sha256(json.dumps(sorted(methods), ensure_ascii=True).encode()).hexdigest()', text)
        self.assertIn('self.assertEqual(actual, expected)', text)

    def test_06_unknown_pin_expression_and_parser_are_explicit_refusals(self):
        recipe = self.recipe()
        inverse = recipe['historical_method_dumps']
        for replacement in (repr(OLD_PIN), repr('0' * 64), 'str(' + repr(CURRENT_PIN) + ')'):
            with self.subTest(replacement=replacement):
                raw = self.raw[G4].decode().replace(repr(CURRENT_PIN), replacement, 1)
                with self.assertRaisesRegex(RuntimeError, '^g4_current_literal_pin$'):
                    inverse(ast.parse(raw), G4.split('/')[-1])
        for version in ((3, 10), (3, 15), (3, True), [3, 14]):
            with self.assertRaisesRegex(RuntimeError, '^unsupported_ast_gold_runtime$'):
                recipe['original_tests_for_runtime']('cpython', version)

    def test_07_complete_current_census_and_explicit_factory_closure(self):
        tests = sorted(p for p in self.raw if p.startswith('tests/') and p.endswith('.py'))
        self.assertEqual(len(tests), 357)
        self.assertEqual(tests, [r['path'] for r in self.plan['partition']])
        self.assertEqual(set(tests) - {p for p in self.retained if p.startswith('tests/') and p.endswith('.py')}, {HYBRID, SELF})
        self.assertEqual(self.row(HYBRID)['entry'], self.cold.hybrid_source_entry())
        self.assertEqual(self.row(SELF)['entry'], self.cold.cohort_source_entry())
        for path, owner in ((HYBRID, 'HybridBudgetObservabilitySource'), (SELF, 'HybridCurrentCohortTests')):
            cls = next(n for n in ast.parse(self.raw[path]).body if isinstance(n, ast.ClassDef) and n.name == owner)
            actual = sorted(n.name for n in cls.body if isinstance(n, ast.FunctionDef) and n.name.startswith('test_'))
            groups = self.row(path)['case_groups']
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]['owner'], owner)
            self.assertEqual(groups[0]['methods'], actual)
            self.assertEqual(len(actual), len(set(actual)))
        self.assertTrue(self.cold.validate_partition(self.plan, self.raw)['source_inputs_verified'])

    def test_08_recounted_new_suite_omissions_are_not_hidden(self):
        for path in (HYBRID, SELF):
            with self.subTest(path=path):
                self.plan = copy.deepcopy(self.original)
                self.plan['partition'] = [r for r in self.plan['partition'] if r['path'] != path]
                for row in self.plan['partition']:
                    row['peers'] = [p for p in row['peers'] if p != path]
                self.refresh()
                self.reject('partition_source_input_membership')

    def test_09_source_only_contract_survives_false_absence_and_native_roles(self):
        for path in (HYBRID, SELF):
            self.plan = copy.deepcopy(self.original)
            self.row(path).update(role='pytest', lane='legacy', requires_sdk_absent=False,
                                  requires=['exact_source_inputs', 'native_legacy'],
                                  entry={'kind': 'pytest', 'invocation': 'pytest ' + path, 'callables': {}})
            self.refresh()
            self.reject('partition_hybrid_source_contract:' + path.replace('.', r'\.'))

    def test_10_missing_or_redirected_loader_bindings_are_refused(self):
        for field, bad in (('factory', 'unbound_main'), ('source_inputs', [HYBRID]),
                           ('loader_roles', {})):
            self.plan = copy.deepcopy(self.original)
            self.row(HYBRID)['entry']['binding'][field] = bad
            self.reject('partition_hybrid_source_contract:' + HYBRID.replace('.', r'\.'))
        self.plan = copy.deepcopy(self.original)
        self.plan['source_pins'] = [r for r in self.plan['source_pins'] if r['path'] != 'semantic_io.py']
        self.reject('partition_hybrid_source_inputs')
        self.plan = copy.deepcopy(self.original)
        path = 'scripts/ci_owned/hybrid_source.py'
        self.assertEqual(self.raw[path].count(b'make_suite(test_loader,'), 1)
        self.raw[path] = self.raw[path].replace(b'make_suite(test_loader,', b'make_suite(unbound_loader,', 1)
        next(r for r in self.plan['source_pins'] if r['path'] == path)['sha256'] = sha(self.raw[path])
        self.reject('partition_hybrid_factory_signature')

    def test_11_factory_is_lazy_and_returns_original_19_case_lifecycle(self):
        reads = []
        def provider():
            reads.append('provider')
            return self.raw['__init__.py']
        def semantic():
            reads.append('semantic')
            return self.raw['semantic_io.py']
        suite = self.hybrid_entry.make_suite(lambda: self.raw[HYBRID], test_sha256=sha(self.raw[HYBRID]),
            test_filename=HYBRID, source_loader=provider, expected_sha256=CURRENT_PIN, filename='bound-provider.py',
            semantic_loader=semantic, semantic_sha256=sha(self.raw['semantic_io.py']), semantic_filename='semantic_io.py')
        expected = assignment(self.raw[HYBRID], 'CASE_METHODS')
        self.assertEqual(len(expected), 19)
        self.assertEqual([case._testMethodName for case in suite], list(expected))
        self.assertTrue(all(isinstance(case, unittest.TestCase) for case in suite))
        self.assertEqual(reads, [])  # Collection cannot read or execute product.

    def test_12_bad_test_loader_bytes_and_hash_refuse_before_declarations(self):
        for raw, digest, message in ((self.raw[HYBRID], '0' * 64, 'test_source_sha256_mismatch'),
                                     ('not bytes', sha(self.raw[HYBRID]), 'test_source_bytes_or_size')):
            with self.assertRaisesRegex(ValueError, '^' + message + '$'):
                self.hybrid_entry.make_suite(lambda: raw, test_sha256=digest, test_filename=HYBRID,
                    source_loader=lambda: None, expected_sha256=CURRENT_PIN, filename='bound-provider.py',
                    semantic_loader=lambda: None, semantic_sha256='0' * 64, semantic_filename='semantic_io.py')

    def test_13_actual_direct_producer_cannot_bind_standalone_source_suite(self):
        producer = ast.parse(self.raw['scripts/ci_owned/source_suites.py'])
        run = next(n for n in producer.body if isinstance(n, ast.FunctionDef) and n.name == 'run_suites')
        self.assertIn("command = [sys.executable, '-I', '-B', '-S', str(entry)]", ast.unparse(run))
        self.assertEqual(list(assignment(self.raw['scripts/ci_owned/fixture_prerequisites.py'], 'SOURCE_SUITES').values()),
                         [('G4Tests', 8), ('RepairTests', 2), ('PrerequisiteControls', 10)])
        main = next(n for n in ast.parse(self.raw[HYBRID]).body if isinstance(n, ast.If))
        self.assertTrue(any(isinstance(n, ast.Raise) for n in main.body))


    def test_14_native_prerequisites_and_historical_observations_stay_unqualified(self):
        self.assertIs(self.plan['native_sdk_execution_admitted'], False)
        for lane in self.plan['cold_processes'].values():
            self.assertEqual(lane['core'], {'selected_revision': None, 'origin': None, 'resolved_closure': None})
        self.assertIsNone(self.plan['cold_processes']['strict']['trust_core']['public_delivery_origin'])
        self.assertNotIn('agent.memory_provider', sys.modules)
        self.assertNotIn('memory_wiki', sys.modules)
        native = {p for lane in self.plan['cold_processes'].values() for p in lane['targets']}
        self.assertTrue({HYBRID, SELF}.isdisjoint(native))
        self.assertTrue(set(self.plan['source_explicit_targets']).isdisjoint(native))


def make_suite(inputs, retained_inputs, plan, cold_module, hybrid_entry):
    HybridCurrentCohortTests.context = (inputs, retained_inputs, plan, cold_module, hybrid_entry)
    return unittest.defaultTestLoader.loadTestsFromTestCase(HybridCurrentCohortTests)


if __name__ == '__main__':
    raise RuntimeError('explicit_current_and_retained_SOURCE_packet_required')
