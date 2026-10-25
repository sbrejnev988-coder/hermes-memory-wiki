"""Prepared document346 metadata regressions, not an execution receipt.

Collection is inert: no product/peer read, import, extraction or exec. The
explicit factory reuses unittest lifecycle and the existing cold validator.
Its complete independent byte census is METADATA, not permission to bind the
oversized provider to SOURCE. No compressed carrier or new runner is created.
Historical inputs are original Git blobs, never current bytes relabelled old.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
import unittest

__test__ = False
SELF = 'tests/test_document_revision_current_witness_source.py'
CITATION = 'tests/test_document_citation_revision_source.py'
G4 = 'tests/test_p2_g4_identity_errors.py'
EOL = 'tests/test_ci_checkout_eol.py'
PREREQ = 'tests/test_foundation_ci_prerequisites.py'
REVIEW = 'tests/test_foundation_ci_review_boundaries.py'
MAIN = '16f06dbffaeccfcce7d34c7180c9929e14d7046fa3d3a1dbf276f35b6007a469'
MAIN_CRLF = '4cd2aeb3d83f996bfc465ca9761ee1e014e37b303f9cf3c5cf056046b5926245'
PRIOR_MAIN = '44cdca1b753f13650fcb9c9fb9bdec9192a9f7c11cdffbe91163abe64dd02805'
PRIOR_CRLF = 'cdf6ccc05ece2d823522203656308581dd9b0db4829f963c7b499d285aacb5dc'
ORIGINAL_MAIN = '8007b015f204a0b673e7cf41410fe609f60b8151bd39d9042a53336de7fdaf09'
CACHE = '674d9e94ca1e7c0bc86561b0d217edb2a7a5d6844f296b69c05a87b43707cd14'
PRIOR_CACHE = '5b13d3ca3f01af8beebd3accd974bb324140f63dc2973014ad54e2c43e9cdefc'
TOOLS = ('memory_wiki_document_unit_context', 'memory_wiki_document_neighbors')
REVISION_PROPERTY = {
    'type': 'string', 'minLength': 35, 'maxLength': 35,
    'pattern': '^docrev_[0-9a-f]{28}$',
    'description': 'Literal revision_id from an admitted citation; stale or malformed pins refuse. Omit for current-coordinate navigation.',
}
DESCRIPTION_SUFFIX = ' Pin expected_revision_id for citation follow-up; omission navigates current coordinates, not historical text.'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def assignment(raw, name):
    nodes = [n for n in ast.parse(raw).body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    if len(nodes) != 1:
        raise ValueError('unique_literal_assignment')
    return ast.literal_eval(nodes[0].value)


def one(nodes, kind, name):
    matches = [n for n in nodes if isinstance(n, kind) and n.name == name]
    if len(matches) != 1:
        raise ValueError('unique_typed_owner:' + name)
    return matches[0]


def methods(raw, owner):
    cls = one(ast.parse(raw).body, ast.ClassDef, owner)
    return {n.name: ast.dump(n, include_attributes=False) for n in cls.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')}


class DocumentCurrentWitnessTests(unittest.TestCase):
    __test__ = False
    context = None

    @classmethod
    def setUpClass(cls):
        if 'agent.memory_provider' in sys.modules or 'memory_wiki' in sys.modules:
            raise RuntimeError('metadata_requires_genuine_SDK_absence')
        if cls.context is None:
            raise RuntimeError('explicit_metadata_context_required')
        cls.inputs, cls.historical, cls.witness_raw, cls.cold, cls.partition, cls.order = cls.context
        cls.witness = json.loads(cls.witness_raw)
        cls.historical_raw = cls.historical['docs/COLD_LANES.json']
        cls.original = cls.partition.document_current_plan(cls.historical_raw, cls.witness_raw)

    def setUp(self):
        self.plan = copy.deepcopy(self.original)
        self.raw = dict(self.inputs)

    def test_01_exact_current_census_self_membership_and_every_source_pin(self):
        rows = self.plan['partition']
        tests = sorted(p for p in self.raw if p.startswith('tests/') and p.endswith('.py'))
        self.assertEqual(len(tests), 359)
        self.assertEqual([r['path'] for r in rows], tests)
        historical = json.loads(self.historical_raw)
        self.assertEqual(historical['file_count'], 357)
        self.assertEqual(set(tests) - {r['path'] for r in historical['partition']}, {CITATION, SELF})
        self.assertEqual(self.plan['frozen_provider_sha256'], MAIN)
        self.assertEqual(self.plan['input_inventory_sha256'], self.cold.partition_digest(rows))
        self.assertTrue(self.cold.validate_partition(self.plan, self.raw)['source_inputs_verified'])
        for row in rows + self.plan['source_pins']:
            self.assertEqual(row['sha256'], sha(self.raw[row['path']]), row['path'])
        for path, owner in ((CITATION, 'DocumentCitationRevisionSource'), (SELF, 'DocumentCurrentWitnessTests')):
            row = next(r for r in rows if r['path'] == path)
            self.assertEqual((row['role'], row['lane'], row['requires_sdk_absent']),
                             ('source-only', 'source-explicit', path == SELF))
            declared = [m for group in row['case_groups'] for m in group['methods']]
            self.assertEqual(len(declared), len(set(declared)))
            self.assertEqual(sorted(declared), sorted(methods(self.raw[path], owner)))
            self.assertTrue(all(group['execution_evidence'] is None for group in row['case_groups']))

    def test_02_historical_authority_roles_and_all_original_gold_are_retained(self):
        self.assertEqual(sha(self.historical_raw),
                         '2e9b8a9f61ef9091734bb197a6be96ea404143cba21d3dd5199f9792bfc83aa4')
        old = json.loads(self.historical_raw)
        current = {r['path']: r for r in self.plan['partition']}
        for row in old['partition']:
            # Only the new schema regression augments an existing case roster.
            before, after = copy.deepcopy(row), copy.deepcopy(current[row['path']])
            before.pop('sha256')
            after.pop('sha256')
            if row['path'] == 'tests/test_tool_schema_source_parity.py':
                before['case_groups'][0]['methods'].append('test_document_lookup_revision_contract_is_optional_and_exact')
                before['case_groups'][0]['methods'].sort()
            self.assertEqual(after, before, row['path'])
        for key in ('before_oracle', 'gold_security_assertions', 'native_targets', 'cold_processes',
                    'native_explicit_packets', 'source_partition_contract'):
            self.assertEqual(self.plan[key], old[key], key)
        for name in ('ORIGINAL_TESTS', 'ORIGINAL_TESTS_311', 'ORIGINAL_TESTS_312'):
            self.assertEqual(assignment(self.raw[PREREQ], name), assignment(self.historical[PREREQ], name))
        cohort = self.raw['tests/test_hybrid_current_cohort.py']
        for name in ('OLD_PIN', 'OLD_CRLF'):
            self.assertEqual(assignment(cohort, name), assignment(self.historical['tests/test_hybrid_current_cohort.py'], name))

    def test_03_current_main_LF_CRLF_and_whole_literal_inverse(self):
        raw = self.raw['__init__.py']
        self.assertNotIn(b'\r', raw)
        self.assertEqual((sha(raw), sha(raw.replace(b'\n', b'\r\n'))), (MAIN, MAIN_CRLF))
        public = assignment(self.raw[EOL], 'PUBLIC')
        self.assertEqual(public['__init__.py'], (MAIN, MAIN_CRLF))
        for path in (G4, EOL, PREREQ):
            current = self.raw[path]
            self.assertEqual(current.count(MAIN.encode()), 1, path)
            inverse = current.replace(MAIN.encode(), PRIOR_MAIN.encode(), 1)
            if path == EOL:
                self.assertEqual(current.count(MAIN_CRLF.encode()), 1)
                inverse = inverse.replace(MAIN_CRLF.encode(), PRIOR_CRLF.encode(), 1)
            self.assertEqual(inverse, self.historical[path], path)
        for path in ('tests/fixtures/g4_original_boundary_gold.txt', 'tests/fixtures/g4_metadata_scope.txt'):
            self.assertEqual(public[path], assignment(self.historical[EOL], 'PUBLIC')[path])
            self.assertEqual(sha(self.raw[path]), public[path][0])
        # Whole G4 inverse also binds the full audit/network denial tail.
        self.assertIn(b'with self.assertRaises(NetworkDenied):', self.raw[G4])
        self.assertIn(b"self.assertEqual(NETWORK_EVENTS,[{'event':'socket.__new__','expected':True}])",
                      self.raw[G4])

    def test_04_original_fingerprint_recipe_after_the_single_typed_G4_inverse(self):
        version = tuple(sys.version_info[:2])
        if sys.implementation.name != 'cpython' or version not in ((3, 11), (3, 12), (3, 13), (3, 14)):
            raise RuntimeError('unsupported_ast_gold_runtime')
        name = 'ORIGINAL_TESTS_311' if version == (3, 11) else 'ORIGINAL_TESTS_312' if version == (3, 12) else 'ORIGINAL_TESTS'
        gold = assignment(self.raw[PREREQ], name)
        for filename, expected in gold.items():
            tree = ast.parse(self.raw['tests/' + filename])
            if filename == G4.split('/')[-1]:
                owner = one(tree.body, ast.ClassDef, 'G4Tests')
                method = one(owner.body, ast.FunctionDef, 'test_08_direct_boundary_preservation_and_network_denial')
                pins = [n for n in ast.walk(method) if isinstance(n, ast.Call)
                        and ast.unparse(n.func) == 'self.assertEqual' and len(n.args) == 2
                        and ast.unparse(n.args[0]) == "hashlib.sha256((SOURCE / '__init__.py').read_bytes()).hexdigest()"]
                self.assertEqual(len(pins), 1)
                self.assertIsInstance(pins[0].args[1], ast.Constant)
                self.assertEqual(pins[0].args[1].value, MAIN)
                pins[0].args[1].value = ORIGINAL_MAIN
            dumps = [ast.dump(n, include_attributes=False) for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name.startswith('test')]
            self.assertEqual(sha(json.dumps(sorted(dumps), ensure_ascii=True).encode()), expected, filename)
        producer = one(ast.parse(self.raw[PREREQ]).body, ast.FunctionDef, 'historical_method_dumps')
        text = ast.unparse(producer)
        self.assertIn(repr(MAIN), text)
        self.assertIn(repr(ORIGINAL_MAIN), text)
        self.assertIn('include_attributes=False', text)

    def test_05_cache_full_two_record_delta_keeps_all_119_others(self):
        current_raw = self.raw['mcp-wrapper/tool_schemas.json']
        prior_raw = self.historical['tool_schemas_before_revision.json']
        self.assertEqual((sha(current_raw), sha(prior_raw)), (CACHE, PRIOR_CACHE))
        current, prior = json.loads(current_raw), json.loads(prior_raw)
        self.assertEqual([r['name'] for r in current], [r['name'] for r in prior])
        self.assertEqual(len(current), 121)
        self.assertEqual([r['name'] for r, old in zip(current, prior) if r != old], list(TOOLS))
        restored = copy.deepcopy(current)
        for row in restored:
            if row['name'] in TOOLS:
                self.assertEqual(row['parameters']['properties'].pop('expected_revision_id'), REVISION_PROPERTY)
                self.assertNotIn('expected_revision_id', row['parameters']['required'])
                self.assertTrue(row['description'].endswith(DESCRIPTION_SUFFIX))
                row['description'] = row['description'][:-len(DESCRIPTION_SUFFIX)]
        self.assertEqual(restored, prior)
        package = self.raw['tests/test_audit_package_contracts_20261003.py']
        self.assertEqual(assignment(package, 'CURRENT_CACHE_SHA256_SOURCE_20261023'), PRIOR_CACHE)
        self.assertEqual(assignment(package, 'CURRENT_CACHE_SHA256_SOURCE_20261025'), CACHE)

    def test_06_complete_runtime_inventory_is_metadata_not_a_native_receipt(self):
        raw = self.raw['tests/ci_owned/document_egress_fixture.py']
        files = assignment(raw, 'SOURCE_FILES')
        self.assertEqual(len(files), len(set(files)))
        self.assertEqual(len(files), 35)
        actual = {name: sha(self.raw[name]) for name in files}
        self.assertEqual(actual, self.witness['runtime_inventory']['sha256_by_path'])
        digest = sha(json.dumps(actual, sort_keys=True, separators=(',', ':')).encode())
        self.assertEqual(digest, assignment(raw, 'CURRENT_SOURCE_INVENTORY_SHA256_20261025'))
        self.assertEqual(digest, self.witness['runtime_inventory']['sha256'])
        self.assertEqual(assignment(raw, 'SOURCE_INVENTORY_SHA256'),
                         assignment(self.historical['tests/ci_owned/document_egress_fixture.py'], 'SOURCE_INVENTORY_SHA256'))
        self.assertEqual(self.witness['qualification']['runtime_inventory_execution'], 'NOT_RUN')

    def test_07_exact_graph_inverse_is_whole_raw_and_typed_preservation(self):
        raw = self.raw['document_knowledge_graph.py']
        prior = self.historical['document_graph_before_revision.py']
        self.assertEqual(self.order.document_revision_inverse(raw), prior)
        current_tree, prior_tree = ast.parse(raw), ast.parse(prior)
        intended = {'_document_lookup_revision', 'document_unit_context', 'document_neighbors'}
        outside = lambda tree: ast.Module(body=[n for n in tree.body
            if not isinstance(n, ast.FunctionDef) or n.name not in intended], type_ignores=tree.type_ignores)
        self.assertEqual(ast.dump(outside(current_tree), include_attributes=False),
                         ast.dump(outside(prior_tree), include_attributes=False))
        for name in ('document_unit_context', 'document_neighbors'):
            current = one(current_tree.body, ast.FunctionDef, name)
            before = one(prior_tree.body, ast.FunctionDef, name)
            loops = lambda node: [ast.dump(n, include_attributes=False) for n in ast.walk(node) if isinstance(n, ast.For)]
            self.assertEqual(loops(current), loops(before), name)

    def test_08_intended_revision_SELECT_predicates_parameters_outputs_and_fences(self):
        tree = ast.parse(self.raw['document_knowledge_graph.py'])
        for name in ('document_unit_context', 'document_neighbors'):
            owner = one(tree.body, ast.FunctionDef, name)
            calls = {label: [n for n in ast.walk(owner) if isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Name) and n.func.id == label]
                     for label in ('_document_disclosure', '_assert_source_access', '_assert_connector_owner',
                                   '_document_lookup_revision', '_disclosed_document_output')}
            self.assertTrue(all(len(v) == 1 for v in calls.values()))
            positions = [calls[label][0].lineno for label in calls]
            self.assertEqual(positions, sorted(positions))
            selects = [n for n in ast.walk(owner) if isinstance(n, ast.Call)
                       and ast.unparse(n.func) == 'conn.execute']
            self.assertEqual(len(selects), 4 if name == 'document_unit_context' else 2)
            for query in selects:
                self.assertIsInstance(query.args[0], ast.Constant)
                sql = query.args[0].value
                self.assertIn('active=1', sql)
                if 'FROM document_sources' in sql:
                    self.assertIn('revision_id FROM document_sources', sql)
                    self.assertEqual(ast.unparse(query.args[1]), '(source_id,)')
                else:
                    self.assertIn('source_id=? AND revision_id=?', sql)
                    self.assertEqual(ast.unparse(query.args[1].elts[1]), 'revision_id')
                    self.assertGreater(query.lineno, calls['_document_lookup_revision'][0].lineno)
            outputs = [n for n in ast.walk(owner) if isinstance(n, ast.Dict)
                       and any(isinstance(k, ast.Constant) and k.value == 'source_id' for k in n.keys)]
            self.assertEqual(len(outputs), 1)
            fields = {k.value: ast.unparse(v) for k, v in zip(outputs[0].keys, outputs[0].values)}
            self.assertEqual(fields['revision_id'], 'revision_id')
        helper = one(tree.body, ast.FunctionDef, '_document_lookup_revision')
        text = ast.unparse(helper)
        self.assertIn("if 'expected_revision_id' in args:", text)
        self.assertIn("type(expected) is not str", text)
        self.assertIn("re.fullmatch('docrev_[0-9a-f]{28}', expected) is None", text)
        self.assertNotIn('.strip()', text)
        self.assertNotIn('str(', text)

    def test_09_graph_drift_or_wrong_version_is_not_masked_by_inverse(self):
        raw = self.raw['document_knowledge_graph.py']
        variants = (raw + b'\n# drift\n', raw.replace(b'revision_id=?', b'revision_id IS NOT NULL', 1),
                    self.historical['document_graph_before_revision.py'], 'not bytes')
        for variant in variants:
            with self.assertRaisesRegex(ValueError, '^exact_document346_graph_required$'):
                self.order.document_revision_inverse(variant)

    def test_10_descriptor_selection_rejects_implicit_migration_and_native_flags(self):
        for raw in (self.historical_raw + b'\n', b'{}', 'not bytes'):
            with self.assertRaisesRegex(ValueError, '^document_witness_historical_binding$'):
                self.partition.document_current_plan(raw, self.witness_raw)
        for key, value in (('native_sdk_execution_admitted', True), ('no_selection_filters', False),
                           ('frozen_provider_sha256', PRIOR_MAIN), ('file_count', 357)):
            witness = copy.deepcopy(self.witness)
            witness['current_plan'][key] = value
            with self.assertRaisesRegex(ValueError, '^document_witness_current_contract$'):
                self.partition.document_current_plan(self.historical_raw, json.dumps(witness).encode())
        self.assertEqual(self.witness['qualification']['all_test_bodies'], 'NOT_RUN')
        self.assertEqual(self.witness['qualification']['genuine_export_SDK_SQL_CI'], 'NOT_RUN')

    def test_11_missing_new_member_and_current_input_drift_are_explicit_refusals(self):
        for path in (CITATION, SELF):
            raw = dict(self.raw)
            del raw[path]
            with self.assertRaisesRegex(ValueError, '^partition_source_input_membership$'):
                self.cold.validate_partition(self.plan, raw)
        for path in ('__init__.py', 'document_knowledge_graph.py', 'mcp-wrapper/tool_schemas.json', G4, SELF):
            raw = dict(self.raw)
            raw[path] += b'\n# authored drift\n'
            with self.assertRaisesRegex(ValueError, '^partition_stale_source:' + path.replace('.', r'\.') + '$'):
                self.cold.validate_partition(self.plan, raw)

    def test_12_original_old41_and_original_schema_regressions_remain_exact(self):
        for path, owner in (('tests/test_cold_lane_partition.py', 'ColdPartitionTests'),
                            ('tests/test_tool_schema_source_parity.py', 'ToolSchemaSourceParity')):
            before = methods(self.historical[path], owner)
            after = methods(self.raw[path], owner)
            for name, body in before.items():
                self.assertEqual(after[name], body, path + ':' + name)
            additions = set(after) - set(before)
            self.assertEqual(additions, set() if owner == 'ColdPartitionTests' else
                             {'test_document_lookup_revision_contract_is_optional_and_exact'})


def make_suite(inputs, historical_inputs, witness_raw, cold_module, partition_module, order_module):
    DocumentCurrentWitnessTests.context = (inputs, historical_inputs, witness_raw, cold_module, partition_module, order_module)
    return unittest.defaultTestLoader.loadTestsFromTestCase(DocumentCurrentWitnessTests)


if __name__ == '__main__':
    raise RuntimeError('explicit_metadata_context_required_no_standalone_SOURCE_or_native_entry')
