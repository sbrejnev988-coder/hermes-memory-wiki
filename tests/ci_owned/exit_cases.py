"""CI-BIND-EXIT-01: synthetic dictionaries; no native objects or processes.

Fake PID/native-origin/MRO values are unit data, never external observations.
The production binding/aggregate predicates below are executed unchanged.
"""
import copy
import unittest
from binding_cases import fixtures, load

OBSERVATIONS = []


def origins(contract):
    return {'native_MRO': True, 'modules': {'agent.memory_provider': {
        'origin': contract['memory_provider_origin'],
        'sha256': contract['memory_provider_sha256']}}}


class OrdinaryExitContract(unittest.TestCase):
    def setUp(self):
        self.module = load('memory_wiki_ci')
        self.contract, self.launches, self.bindings = fixtures()

    def proof(self, label):
        report = self.module.verify_lane_bindings(self.launches, self.bindings,
                                                  self.contract, origins(self.contract))
        OBSERVATIONS.append({'case': label, 'synthetic_only': True,
                             'returncodes': [r['returncode'] for r in self.launches],
                             'roles': [r['role'] for r in self.launches],
                             'proof': copy.deepcopy(report)})
        return report

    def test_finished_plugin_capable_child_requires_zero_exit_even_without_plugin_classes(self):
        for code in (1, 7, -9, 86):
            for has_plugin in (False, True):
                with self.subTest(code=code, has_plugin=has_plugin):
                    self.launches[1]['returncode'] = code
                    self.bindings[1]['plugin_classes'] = copy.deepcopy(self.bindings[0]['plugin_classes']) if has_plugin else []
                    self.assertFalse(self.proof('ordinary_child')['verified'],
                                     'CI-BIND-EXIT-01: finished atexit receipt is not successful child exit')

    def test_plugin_role_and_primary_require_zero_exit(self):
        for index in (0, 1):
            for code in (1, 7, -9, 86):
                with self.subTest(index=index, code=code):
                    self.contract, self.launches, self.bindings = fixtures()
                    self.launches[index]['role'] = self.bindings[index]['role'] = 'plugin'
                    self.launches[index]['returncode'] = code
                    self.assertFalse(self.proof('plugin_or_primary')['verified'])

    def test_recomputed_full_sixteen_lane_matrix_cannot_hide_failed_child(self):
        for code in (1, 7, -9):
            with self.subTest(code=code):
                self.launches[1]['returncode'] = code
                proof = self.proof('matrix_failed_child')
                records = []
                for platform in ('linux', 'win32'):
                    for version in ('3.11', '3.12', '3.13', '3.14'):
                        for stage in ('full', 'recovery'):
                            records.append({'platform': platform, 'python': version, 'stage': stage,
                                            'source_sha': self.contract['source_sha'], 'source_digest': 'synthetic-identical-bytes',
                                            'core_sha': self.module.CORE_SHA, 'complete': True,
                                            'bindings_verified': proof['verified'], 'collected': ['synthetic-case'],
                                            'passed': ['synthetic-case'], 'skipped': [], 'failed': [], 'errors': []})
                # A forged positive downloaded boolean is replaced by actual proof,
                # as production aggregate does. No hosted lanes were executed.
                with self.assertRaises(RuntimeError):
                    self.module.matrix_coverage(records, self.contract['source_sha'])

    def test_lifecycle_labels_do_not_exempt_ordinary_failed_child(self):
        self.launches[1].update(returncode=7, lifecycle='may_terminate',
                                expectation={'explicit': True, 'reason': 'synthetic nonplugin-looking label',
                                             'command_sha256': self.launches[1]['command_sha256']})
        self.bindings[1].update(nonplugin_guard_armed=True, plugin_classes=[])
        self.assertFalse(self.proof('no_automatic_worker_or_plugin_failure_role')['verified'])

    def test_finished_nonplugin_nonzero_is_not_the_existing_unfinished_termination_exception(self):
        self.launches[1].update(role='nonplugin_worker', lifecycle='may_terminate', returncode=7,
                                expectation={'explicit': True, 'reason': 'synthetic lifecycle',
                                             'command_sha256': self.launches[1]['command_sha256']})
        self.bindings[1].update(role='nonplugin_worker', plugin_classes=[], nonplugin_guard_armed=True)
        self.assertFalse(self.proof('finished_nonplugin_failure')['verified'])

    def test_zero_exit_plugin_and_no_plugin_loaded_child_remain_positive(self):
        self.assertTrue(self.proof('zero_with_plugin')['verified'])
        self.bindings[1]['plugin_classes'] = []
        self.assertTrue(self.proof('zero_without_plugin')['verified'])

    def test_explicit_native_ready_nonplugin_termination_contract_is_unchanged(self):
        self.launches[1].update(role='nonplugin_worker', lifecycle='may_terminate',
                                expectation={'explicit': True, 'reason': 'synthetic deliberate termination',
                                             'command_sha256': self.launches[1]['command_sha256']})
        self.bindings[1].update(role='nonplugin_worker', plugin_classes=[], nonplugin_guard_armed=True,
                               finished=False, state='native_ready')
        for code in (1, 7, -9):
            self.launches[1]['returncode'] = code
            report = self.proof('explicit_nonplugin_termination')
            self.assertTrue(report['verified'])
            self.assertEqual(report['explicit_nonplugin_terminations'], [self.launches[1]['launch_id']])
        self.launches[1]['returncode'] = 86
        self.assertFalse(self.proof('bootstrap_86_never_exempt')['verified'])


if __name__ == '__main__':
    unittest.main()
