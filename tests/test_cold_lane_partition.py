"""Focused stdlib SOURCE regressions for the existing cold entry's metadata.

No pytest, product/Core/SDK imports or native bootstrap flags. File membership,
entry signatures and source bytes are checked; test-body/native coverage is not.
Direct: python -I -B -S tests/test_cold_lane_partition.py (complete checkout).
The permanent SOURCE harness may supply an exact compressed byte census as
transport data to fit its input cardinality/size bounds; it is never executed.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
import zlib


ROOT = Path(__file__).absolute().parents[1]


def current_inputs(plan):
    """Independent no-follow census, not the manifest's list of test files."""
    paths = [ROOT / pin['path'] for pin in plan['source_pins']]
    pending = [ROOT / 'tests']
    while pending:
        directory = pending.pop()
        for part in (directory, *directory.parents):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                raise ValueError('source_link_or_reparse')
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                    raise ValueError('source_link_or_reparse')
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif path.suffix == '.py':
                    paths.append(path)
    result = {}
    for path in paths:
        for part in (path, *path.parents):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                raise ValueError('source_link_or_reparse')
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('source_not_regular')
        result[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    return result


class ColdPartitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if 'DEVTOOLS_INPUTS' in globals():
            cls.original = json.loads(devtools_read_bound(DEVTOOLS_INPUTS['COLD_LANES.json']))
            cls.inputs = {}
            for name in ('COLD_TEST_INPUTS.zlib', 'COLD_ENTRY_INPUTS.zlib'):
                carrier = json.loads(zlib.decompress(devtools_read_bound(DEVTOOLS_INPUTS[name])))
                if cls.inputs.keys() & carrier.keys():
                    raise ValueError('duplicate_fixture_transport_path')
                cls.inputs.update({p: text.encode('utf-8') for p, text in carrier.items()})
            raw = devtools_read_bound(DEVTOOLS_INPUTS['cold_lane_entry.py'])
        else:
            cls.original = json.loads((ROOT / 'docs/COLD_LANES.json').read_bytes())
            cls.inputs = current_inputs(cls.original)
            raw = cls.inputs['tests/cold_lane_entry.py']
        cls.module = types.ModuleType('_cold_partition_source')
        cls.module.__file__ = str(ROOT / 'tests/cold_lane_entry.py')
        exec(compile(raw, cls.module.__file__, 'exec', dont_inherit=True), cls.module.__dict__)

    def setUp(self):
        self.plan = copy.deepcopy(self.original)
        self.raw = dict(self.inputs)

    def row(self, path):
        return next(row for row in self.plan['partition'] if row['path'] == path)

    def refresh(self):
        rows = self.plan['partition']
        self.plan['file_count'] = len(rows)
        self.plan['input_inventory_sha256'] = self.module.partition_digest(rows)
        for lane in ('strict', 'legacy'):
            self.plan['cold_processes'][lane]['targets'] = [r['path'] for r in rows if r['lane'] == lane]
        self.plan['source_explicit_targets'] = [r['path'] for r in rows if r['lane'] == 'source-explicit']

    def reject(self, code, *, raw=True):
        with self.assertRaisesRegex(ValueError, '^' + code):
            self.module.validate_partition(self.plan, self.raw if raw else None)

    def pending_peer_fixture(self):
        # Current B is delivered. These negative controls need a genuinely
        # unbound future input, not a stale claim about the current checkout.
        self.plan['pending_peer_inputs'] = [{
            'path': 'tests/ci_owned/future_unbound_peer.py', 'sha256': None,
            'status': 'PENDING_FINAL_MERGE_REBIND', 'owner': 'owned pending negative fixture'}]
        self.plan['needs_final_rebind'] = True

    def test_current_full_file_and_entry_closure(self):
        result = self.module.validate_partition(self.plan, self.raw)
        self.assertEqual(result['file_count'], len([p for p in self.raw if p.startswith('tests/') and p.endswith('.py')]))
        self.assertEqual(sum(result['role_counts'].values()), result['file_count'])
        self.assertTrue(result['source_inputs_verified'])
        self.assertFalse(result['native_sdk_execution_admitted'])

    def test_metadata_only_is_not_source_or_native_attestation(self):
        result = self.module.validate_partition(self.plan)
        self.assertFalse(result['source_inputs_verified'])
        self.assertFalse(result['native_sdk_execution_admitted'])

    def test_duplicate_partition_path_refused(self):
        self.plan['partition'].append(copy.deepcopy(self.plan['partition'][0]))
        self.reject('partition_duplicate_or_non_test_path', raw=False)

    def test_missing_current_file_refused_even_after_metadata_recount(self):
        path = 'tests/baseline-source_connectors.py'
        self.plan['partition'] = [r for r in self.plan['partition'] if r['path'] != path]
        for row in self.plan['partition']:
            row['peers'] = [p for p in row['peers'] if p != path]
        self.refresh()
        self.reject('partition_source_input_membership')

    def test_unexpected_new_peer_is_not_hidden_by_pending_metadata(self):
        self.pending_peer_fixture()
        pending = self.plan['pending_peer_inputs'][0]['path']
        self.raw[pending] = b'# actual new peer requires final merge rebind\n'
        self.reject('partition_source_input_membership')

    def test_missing_source_input_refused(self):
        del self.raw['tests/cold_lane_entry.py']
        self.reject('partition_source_input_membership')

    def test_stale_provider_bytes_refused(self):
        self.raw['__init__.py'] += b'\n# source drift\n'
        self.reject('partition_stale_source:__init__.py')

    def test_stale_test_bytes_refused(self):
        self.raw['tests/test_runtime_lifecycle_handoff.py'] += b'\n# test drift\n'
        self.reject('partition_stale_source:tests/test_runtime_lifecycle_handoff.py')

    def test_stale_existing_controller_bytes_refused(self):
        self.raw['packaging/run_native_regressions.py'] += b'\n# entry drift\n'
        self.reject('partition_stale_source:packaging/run_native_regressions.py')

    def test_unsupported_role_and_lane_refused(self):
        self.plan['partition'][0]['role'] = 'collected_equals_executed'
        self.reject('partition_role_or_lane', raw=False)
        self.plan = copy.deepcopy(self.original)
        self.plan['partition'][0]['lane'] = 'universal-FULL'
        self.reject('partition_role_or_lane', raw=False)

    def test_typed_fields_do_not_coerce_truthy_values(self):
        self.plan['native_sdk_execution_admitted'] = 0
        self.reject('partition_not_execution_authority', raw=False)
        self.plan = copy.deepcopy(self.original)
        self.plan['file_count'] = True
        self.reject('partition_inventory_digest_or_count', raw=False)
        self.plan = copy.deepcopy(self.original)
        self.plan['partition'][0]['requires_sdk_absent'] = 'false'
        self.reject('partition_absence_type', raw=False)

    def test_invalid_literal_paths_and_hashes_refused(self):
        for path in ('tests/../escape.py', 'tests/NUL.py', 'tests/name.py:stream', 'tests/name. /case.py', 'tests\\case.py', '/tests/case.py'):
            self.plan = copy.deepcopy(self.original)
            self.plan['partition'][0]['path'] = path
            self.reject('partition_path', raw=False)
        self.plan = copy.deepcopy(self.original)
        self.plan['partition'][0]['sha256'] = 'A' * 64
        self.reject('partition_sha256', raw=False)

    def test_sdk_absence_source_targets_cannot_enter_native_preload(self):
        row = self.row('tests/test_p2_g4_identity_errors.py')
        self.assertTrue(row['requires_sdk_absent'])
        row['lane'] = 'legacy'
        self.refresh()
        self.reject('partition_source_native_intersection', raw=False)

    def test_inherited_stage_fixture_uses_actual_absence_lane(self):
        for path in self.module._STAGE_CONSUMERS:
            row = self.row(path)
            self.assertEqual(row['fixture_binding'], {'local': 'stage', 'peer': self.module._STAGE_PEER, 'fixture': 'stage'})
            self.assertEqual((row['role'], row['lane']), ('source-only', 'source-explicit'))
            self.assertIs(row['requires_sdk_absent'], True)
            self.assertIn('source_pytest_absent', row['requires'])
            self.assertIn(path, self.plan['source_explicit_targets'])
            self.assertNotIn(path, self.plan['cold_processes']['legacy']['targets'])
        self.module.validate_partition(self.plan, self.raw)

    def test_inherited_fixture_refuses_native_metadata_even_with_false_absence(self):
        for path in self.module._STAGE_CONSUMERS:
            self.plan = copy.deepcopy(self.original)
            self.row(path).update(role='pytest', lane='legacy', requires_sdk_absent=False,
                                  requires=['exact_source_inputs', 'native_legacy'])
            self.refresh()
            self.reject('partition_fixture_lane:' + path, raw=False)
            self.reject('partition_fixture_lane:' + path)

    def test_inherited_fixture_binding_cannot_be_omitted_or_redirected(self):
        path = 'tests/test_connector_legacy_schema_owner.py'
        for binding in (None, {'local': 'stage', 'peer': 'tests/test_connector_stage_home_compat.py', 'fixture': 'stage'}):
            self.plan = copy.deepcopy(self.original)
            self.row(path)['fixture_binding'] = binding
            self.reject('partition_fixture_binding:' + path, raw=False)

    def test_actual_inherited_fixture_alias_drift_refused_after_rehash(self):
        path = 'tests/test_connector_legacy_schema_owner.py'
        self.assertIn(b'stage = peer.stage', self.raw[path])
        self.raw[path] = self.raw[path].replace(b'stage = peer.stage', b'stage = peer.SCOPE')
        self.row(path)['sha256'] = hashlib.sha256(self.raw[path]).hexdigest()
        self.refresh()
        self.reject('partition_fixture_source_binding:' + path)

    def test_actual_fixture_absence_guard_drift_refused_after_rehash(self):
        path = self.module._STAGE_PEER
        old = b"importlib.util.find_spec('agent') is None"
        self.assertIn(old, self.raw[path])
        self.raw[path] = self.raw[path].replace(old, b"importlib.util.find_spec('agent') is not None")
        self.row(path)['sha256'] = hashlib.sha256(self.raw[path]).hexdigest()
        self.refresh()
        self.reject('partition_fixture_source_guards')

    def test_peer_input_edge_alone_does_not_inherit_fixture_absence(self):
        # Synthetic metadata-only input edge, NOT an exported fixture binding.
        path = 'tests/test_connector_document_domain.py'
        row = self.row(path)
        row['peers'].append(self.module._STAGE_PEER)
        self.assertNotIn('fixture_binding', row)
        self.assertFalse(row['requires_sdk_absent'])
        self.assertEqual(row['lane'], 'legacy')
        self.assertNotIn(b'stage = peer.stage', self.raw[path])
        self.module.validate_partition(self.plan, self.raw)

    def test_isolated_ci_invocation_binds_actual_initial_import(self):
        for path in self.module._CI_ENTRIES:
            row = self.row(path)
            self.assertEqual(row['entry'], self.module.isolated_ci_entry(path))
            self.assertEqual(row['entry']['bootstrap']['argv'][1:5], ['-I', '-B', '-S', '-c'])
            imports = [n for n in ast.parse(self.raw[path]).body if isinstance(n, ast.ImportFrom) and n.module == 'binding_cases']
            self.assertEqual(len(imports), 1)
            self.assertEqual([n.name for n in imports[0].names], ['fixtures', 'load'])
            self.assertIn(self.module._CI_PEER, row['peers'])
            self.assertIn('isolated_ci_peer_binding', row['requires'])
        self.module.validate_partition(self.plan, self.raw)

    def test_isolated_ci_bare_and_mutated_bootstrap_refused(self):
        for path in self.module._CI_ENTRIES:
            self.plan = copy.deepcopy(self.original)
            self.row(path)['entry']['invocation'] = 'python -I -B -S ' + path
            self.reject('partition_ci_bootstrap:' + path, raw=False)
            self.plan = copy.deepcopy(self.original)
            self.row(path)['entry']['bootstrap']['argv'].remove('-S')
            self.reject('partition_ci_bootstrap:' + path, raw=False)
            self.plan = copy.deepcopy(self.original)
            self.row(path)['entry']['bootstrap']['path_binding'] = 'fixture/SDK'
            self.reject('partition_ci_bootstrap:' + path, raw=False)

    def test_isolated_ci_missing_prerequisites_and_peer_refused(self):
        path = 'tests/ci_owned/entry_cases.py'
        for field, value in (('requires', ['exact_source_inputs', 'source_stdlib']), ('peers', [])):
            self.plan = copy.deepcopy(self.original)
            self.row(path)[field] = value
            self.reject('partition_ci_bootstrap_prerequisites:' + path, raw=False)
        self.plan = copy.deepcopy(self.original)
        self.row(path)['entry']['bootstrap']['fixture_env'] = None
        self.reject('partition_ci_bootstrap:' + path, raw=False)
        self.plan = copy.deepcopy(self.original)
        self.plan['source_pins'] = [p for p in self.plan['source_pins'] if p['path'] != 'scripts/ci_owned/ci_bootstrap.py']
        self.reject('partition_ci_bootstrap_inputs', raw=False)

    def test_isolated_ci_actual_initial_import_drift_refused_after_rehash(self):
        path = 'tests/ci_owned/exit_cases.py'
        self.raw[path] = self.raw[path].replace(b'from binding_cases import fixtures, load', b'from another_peer import fixtures, load')
        self.row(path)['sha256'] = hashlib.sha256(self.raw[path]).hexdigest()
        self.refresh()
        self.reject('partition_ci_initial_import:' + path)

    def test_isolated_ci_runpy_executes_path_binding_before_entry(self):
        # Execute the actual declared stdlib bootstrap, not the old suites.
        # The inert target resolves the byte-exact peer without importing it:
        # non-stdlib imports remain denied by the unchanged SOURCE envelope.
        root = Path(tempfile.mkdtemp(prefix='ci-peer-binding-', dir=os.environ['TMPDIR']))
        peer = root / 'binding_cases.py'
        peer.write_bytes(self.raw[self.module._CI_PEER])
        old_argv, old_path = sys.argv, list(sys.path)
        try:
            for path in self.module._CI_ENTRIES:
                entry = root / Path(path).name
                entry.write_text(
                    "from importlib.machinery import PathFinder\n"
                    "from pathlib import Path\nimport sys\n"
                    "assert sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode\n"
                    "spec = PathFinder.find_spec('binding_cases')\n"
                    "assert spec is not None and Path(spec.origin) == Path(__file__).with_name('binding_cases.py')\n"
                    "assert sys.path[0] == str(Path(__file__).parent)\n"
                    "Path(__file__).with_suffix('.witness').write_text(spec.origin, encoding='utf-8')\n",
                    encoding='utf-8')
                bootstrap = self.row(path)['entry']['bootstrap']
                sys.argv = ['-c', str(entry)]
                exec(compile(bootstrap['argv'][5], '<declared isolated stdlib bootstrap>', 'exec'), {})
                self.assertEqual(entry.with_suffix('.witness').read_text(encoding='utf-8'), str(peer))
                self.assertEqual(sys.path, [str(root), *old_path])
                self.assertEqual(peer.read_bytes(), self.raw[self.module._CI_PEER])
                sys.path[:] = old_path
        finally:
            sys.argv = old_argv
            sys.path[:] = old_path

    def test_isolated_ci_runpy_preserves_exact_target_argv(self):
        # The operand selects the script, not a unittest test name. Remaining
        # literal selectors/options must reach the target without coercion.
        old_argv, old_path = sys.argv, list(sys.path)
        try:
            for path in self.module._CI_ENTRIES:
                for tail in ([], ['-q'], ['OwnedCli.test_selected', '-v']):
                    root = Path(tempfile.mkdtemp(prefix='ci-target-argv-', dir=os.environ['TMPDIR']))
                    entry = root / Path(path).name
                    entry.write_text(
                        "import json,sys\nfrom pathlib import Path\n"
                        "assert sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode\n"
                        "Path(__file__).with_suffix('.witness').write_text(json.dumps(sys.argv), encoding='utf-8')\n",
                        encoding='utf-8')
                    sys.argv = ['-c', str(entry), *tail]
                    bootstrap = self.row(path)['entry']['bootstrap']['argv'][5]
                    exec(compile(bootstrap, '<declared isolated stdlib bootstrap>', 'exec'), {})
                    self.assertEqual(json.loads(entry.with_suffix('.witness').read_text(encoding='utf-8')),
                                     [str(entry), *tail])
                    self.assertEqual(sys.argv, ['-c', *tail])
                    self.assertEqual(sys.path, [str(root), *old_path])
                    sys.path[:] = old_path
        finally:
            sys.argv = old_argv
            sys.path[:] = old_path

    def test_isolated_ci_runpy_selects_actual_stdlib_unittest_suite(self):
        # Exercise genuine unittest.main on an inert own module, never the
        # historical CI suites/peer. A lingering script operand selects a
        # failed-name case instead and cannot create this selected witness.
        old_argv, old_path = sys.argv, list(sys.path)
        try:
            for path in self.module._CI_ENTRIES:
                for tail in ([], ['-q'], ['OwnedCli.test_selected', '-q']):
                    root = Path(tempfile.mkdtemp(prefix='ci-unittest-argv-', dir=os.environ['TMPDIR']))
                    entry = root / Path(path).name
                    entry.write_text(
                        "from pathlib import Path\nimport sys,unittest\n"
                        "class OwnedCli(unittest.TestCase):\n"
                        "    def test_selected(self):\n"
                        "        self.assertEqual(sys.argv, [str(Path(__file__)), *" + repr(tail) + "])\n"
                        "        with Path(__file__).with_suffix('.witness').open('a', encoding='utf-8') as stream:\n"
                        "            stream.write('selected\\n')\n"
                        "unittest.main()\n", encoding='utf-8')
                    sys.argv = ['-c', str(entry), *tail]
                    bootstrap = self.row(path)['entry']['bootstrap']['argv'][5]
                    with self.assertRaises(SystemExit) as caught:
                        exec(compile(bootstrap, '<declared isolated stdlib bootstrap>', 'exec'), {})
                    self.assertEqual(caught.exception.code, 0)
                    self.assertEqual(entry.with_suffix('.witness').read_text(encoding='utf-8'), 'selected\n')
                    self.assertEqual(sys.argv, ['-c', *tail])
                    self.assertEqual(sys.path, [str(root), *old_path])
                    sys.path[:] = old_path
        finally:
            sys.argv = old_argv
            sys.path[:] = old_path

    def test_source_only_unittest_cannot_be_native_pytest(self):
        self.row('tests/test_p2_g3_repair01_pure.py')['lane'] = 'strict'
        self.refresh()
        self.reject('partition_source_native_intersection', raw=False)

    def test_native_target_loss_duplication_and_wrong_lane_refused(self):
        targets = self.plan['cold_processes']['legacy']['targets']
        targets.pop()
        self.reject('partition_cold_target_closure', raw=False)
        self.plan = copy.deepcopy(self.original)
        targets = self.plan['cold_processes']['legacy']['targets']
        targets.append(targets[0])
        self.reject('partition_cold_targets', raw=False)
        self.plan = copy.deepcopy(self.original)
        self.plan['cold_processes']['strict']['targets'].append('tests/test_p2_g4_repair01.py')
        self.reject('partition_cold_target_closure', raw=False)

    def test_source_target_loss_refused(self):
        self.plan['source_explicit_targets'].pop()
        self.reject('partition_source_target_closure', raw=False)

    def test_support_is_not_an_executable_test_target(self):
        row = self.row('tests/helpers/provider_lifecycle.py')
        row['entry'] = {'kind': 'pytest', 'invocation': 'pytest', 'callables': {}}
        self.reject('partition_noncase_entry', raw=False)

    def test_static_case_bodies_cannot_be_hidden_as_support(self):
        path = 'tests/test_connector_document_domain.py'
        row = self.row(path)
        row.update(role='support', lane='support', entry=None)
        self.refresh()
        self.reject('partition_hidden_cases:' + path)

    def test_explicit_callable_signature_is_bound_to_actual_source(self):
        entry = self.row('tests/test_runtime_lifecycle_handoff.py')['entry']
        self.assertEqual(entry['callables']['run_lifecycle_packet'], 'provider, root')
        entry['callables']['run_lifecycle_packet'] = 'provider, root, fabricated'
        self.reject('partition_callable_signature:tests/test_runtime_lifecycle_handoff.py')

    def test_explicit_unittest_setup_is_declared_not_counted_as_pytest(self):
        for path in ('tests/test_graph_settings_unavailable.py', 'tests/test_erasure_atomic_bootstrap.py'):
            row = self.row(path)
            self.assertEqual(row['role'], 'unittest-explicit')
            self.assertIn('make_suite', row['entry']['callables'])
            self.assertNotIn(path, self.plan['cold_processes']['legacy']['targets'])
        row = self.row('tests/ci_owned/test_current_sdk_bootstrap.py')
        self.assertIn('carrier_binding', row['requires'])
        self.assertIn('CARRIER', row['entry']['invocation'])

    def test_missing_declared_peer_and_prerequisite_refused(self):
        self.plan['partition'][0]['peers'] = ['tests/not_present.py']
        self.reject('partition_peer_missing', raw=False)
        self.plan = copy.deepcopy(self.original)
        self.plan['partition'][0]['requires'] = ['undelivered_fake_native_grant']
        self.reject('partition_prerequisites_or_peers', raw=False)

    def test_inventory_digest_count_and_provider_pin_cannot_diverge(self):
        self.plan['input_inventory_sha256'] = '0' * 64
        self.reject('partition_inventory_digest_or_count', raw=False)
        self.plan = copy.deepcopy(self.original)
        self.plan['frozen_provider_sha256'] = '0' * 64
        self.reject('partition_provider_pin', raw=False)

    def test_peer_hash_is_null_until_actual_delivery(self):
        self.pending_peer_fixture()
        self.plan['pending_peer_inputs'][0]['sha256'] = '0' * 64
        self.reject('partition_pending_peer', raw=False)
        self.plan = copy.deepcopy(self.original)
        self.pending_peer_fixture()
        self.plan['needs_final_rebind'] = False
        self.reject('partition_pending_rebind', raw=False)

    def test_distinct_core_targets_match_actual_declared_entry_constants(self):
        targets = self.plan['native_targets']
        for key in ('ordinary_cli', 'hosted_full'):
            target = targets[key]
            tree = ast.parse(self.raw[target['entry']])
            assignments = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'CORE_SHA' for t in n.targets)]
            self.assertEqual(len(assignments), 1)
            self.assertEqual(target['declared_revision'], ast.literal_eval(assignments[0].value))
            self.assertIsNone(target['actual_origin'])
            self.assertIsNone(target['resolved_closure'])
        self.assertNotEqual(targets['ordinary_cli']['declared_revision'], targets['hosted_full']['declared_revision'])
        self.assertIsNone(targets['managed_sdk']['declared_revision'])

    def test_wrong_core_pin_is_not_repaired_from_another_target(self):
        self.plan['native_targets']['ordinary_cli']['declared_revision'] = self.plan['native_targets']['hosted_full']['declared_revision']
        self.reject('partition_native_target_pin:packaging/run_native_regressions.py')

    def test_existing_cold_plan_refuses_pending_rebind_and_missing_origins(self):
        self.pending_peer_fixture()
        root = Path(tempfile.mkdtemp(prefix='cold-plan-', dir=os.environ['TMPDIR']))
        path = root / 'plan.json'
        old_argv = sys.argv
        try:
            path.write_text(json.dumps(self.plan), encoding='utf-8')
            sys.argv = [str(self.module.__file__), 'legacy', str(path)]
            with self.assertRaisesRegex(RuntimeError, 'final product/test composition not rebound'):
                self.module.cold_plan()
            self.plan['pending_peer_inputs'] = []
            self.plan['needs_final_rebind'] = False
            path.write_text(json.dumps(self.plan), encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'actual core selection/origin/dependency closure missing'):
                self.module.cold_plan()
        finally:
            sys.argv = old_argv

    def test_current_delivered_ci_dispatch_peer_is_bound(self):
        path = 'tests/ci_owned/collection_dispatch_cases.py'
        row = self.row(path)
        self.assertEqual((row['role'], row['lane']), ('unittest-explicit', 'source-explicit'))
        self.assertEqual(row['sha256'], hashlib.sha256(self.raw[path]).hexdigest())
        self.assertIn(path, self.plan['source_explicit_targets'])
        self.assertIn('tests/helpers/collection_evidence.py', row['peers'])
        self.assertEqual(row['entry']['callables']['run_fixture'], 'kind, *, source, root')
        for lane in ('strict', 'legacy'):
            self.assertNotIn(path, self.plan['cold_processes'][lane]['targets'])
        pins = {pin['path']: pin['sha256'] for pin in self.plan['source_pins']}
        for source in ('scripts/ci_owned/ci_child.py', 'scripts/ci_owned/ci_output_admission.py'):
            self.assertEqual(pins[source], hashlib.sha256(self.raw[source]).hexdigest())
        self.assertEqual(self.plan['pending_peer_inputs'], [])
        self.assertFalse(self.plan['needs_final_rebind'])
        self.assertFalse(self.module.validate_partition(self.plan, self.raw)['native_sdk_execution_admitted'])

    def test_native_and_trust_admission_remain_genuinely_unresolved(self):
        self.assertFalse(self.plan['native_sdk_execution_admitted'])
        for lane in self.plan['cold_processes'].values():
            self.assertEqual(lane['core'], {'selected_revision': None, 'origin': None, 'resolved_closure': None})
        trust = self.plan['cold_processes']['strict']['trust_core']
        self.assertIsNone(trust['public_delivery_origin'])
        self.assertIsNone(trust['sha256'])
        self.assertTrue(self.plan['cold_processes']['legacy']['trust_core']['genuine_absence_required'])
        self.assertNotIn('agent.memory_provider', sys.modules)
        self.assertNotIn('memory_wiki', sys.modules)


def main():
    class Result(unittest.TextTestResult):
        def __init__(self, *args):
            super().__init__(*args)
            self.rows = []

        def startTest(self, test):
            if 'devtools_case_started' in globals():
                devtools_case_started('cold_partition.' + test._testMethodName)
            super().startTest(test)

        def addSuccess(self, test):
            self.rows.append({'id': 'cold_partition.' + test._testMethodName, 'outcome': 'passed'})
            super().addSuccess(test)

        def addFailure(self, test, error):
            self.rows.append({'id': 'cold_partition.' + test._testMethodName, 'outcome': 'failed'})
            super().addFailure(test, error)

        def addError(self, test, error):
            self.rows.append({'id': 'cold_partition.' + test._testMethodName, 'outcome': 'error'})
            super().addError(test, error)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ColdPartitionTests)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2, resultclass=Result).run(suite)
    print(json.dumps({'schema': 'memory-stack.cases/v1', 'scope': 'source', 'cases': result.rows,
                      'counting_unit': 'unique_main_unittest_case_after_setup_call_teardown_cleanups',
                      'file_inventory_is_testcase_coverage': False, 'pytest_native_sdk_executed': False}, separators=(',', ':')))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
