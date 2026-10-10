"""Prepared cold child derived from ci_child.py; NOT native launch admission.

Separate strict/legacy/recovery processes only, through an independently
admitted existing recorder/bootstrap. Current COLD_LANES blocks all three.
No new CI job, controller, SDK substitute, or selection filter is introduced.
"""
from pathlib import Path
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import sys


def cold_plan():
    # A JSON plan is NOT authority. Even a finalized plan needs separate real
    # native admission and the existing independently admitted bootstrap.
    plan = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    stage = sys.argv[1]
    if stage not in ('strict', 'legacy', 'legacy-recovery'):
        raise RuntimeError('No universal FULL mode; use separate cold lanes')
    if plan['needs_final_rebind']:
        raise RuntimeError('BLOCKED: final product/test composition not rebound')
    lane = plan['cold_processes'][stage]
    required = lane['core']
    if any(required[key] is None for key in ('selected_revision', 'origin', 'resolved_closure')):
        raise RuntimeError('BLOCKED: actual core selection/origin/dependency closure missing')
    if not getattr(sys, '_memory_wiki_ci_configured', False) or not hasattr(sys, '_memory_wiki_ci_recorder'):
        raise RuntimeError('BLOCKED: existing admitted native bootstrap/recorder required')
    revision = required['selected_revision']
    if not isinstance(revision, str) or len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
        raise RuntimeError('Qualified revision must be literal lowercase 40-hex')
    if sys._memory_wiki_ci_recorder.config['core_sha'] != revision:
        raise RuntimeError('Bootstrap selected a different native target')
    if os.environ['HERMES_SECURITY_STRICT'] != lane['HERMES_SECURITY_STRICT']:
        raise RuntimeError('Wrong cold import security mode')
    if Path(os.environ['MW_CI_CORE']).resolve(strict=True) != Path(required['origin']).resolve(strict=True):
        raise RuntimeError('Core origin is not the qualified target')
    if stage == 'strict':
        trust = lane['trust_core']
        if trust['public_delivery_origin'] is None or trust['sha256'] is None:
            raise RuntimeError('BLOCKED: genuine public trust-core delivery/API not qualified')
    elif 'hermes_trust_core' in sys.modules or importlib.util.find_spec('hermes_trust_core') is not None:
        raise RuntimeError('Legacy requires genuine trust-core absence; no import hiding/substitutes')
    targets = lane['targets']
    expected = ([row['path'] for row in plan['partition'] if row['lane'] == stage]
                if stage != 'legacy-recovery' else ['tests/ci_owned/recovery_cases.py'])
    if targets != expected or not targets or len(set(targets)) != len(targets):
        raise RuntimeError('Cold lane target union is incomplete or overlapping')
    return plan, stage, targets


def main():
    plan, stage, targets = cold_plan()
    source = Path(os.environ['MW_CI_SOURCE']).resolve(strict=True)
    core = Path(os.environ['MW_CI_CORE']).resolve(strict=True)
    runroot = Path(os.environ['MW_CI_RUNROOT']).resolve(strict=True)
    if hashlib.sha256((source / '__init__.py').read_bytes()).hexdigest() != plan['frozen_provider_sha256']:
        raise RuntimeError('Final provider source drift; rebind before admission')
    closure = plan['cold_processes'][stage]['core']['resolved_closure']
    if not isinstance(closure, dict) or not closure:
        raise RuntimeError('Resolved import closure is missing')
    for package, version in closure.items():
        if importlib.metadata.version(package) != version:
            raise RuntimeError('Resolved dependency differs: ' + package)
    out = runroot / 'public'
    # Native exports are the public baseline CI contract, never SDK/auth stand-ins.
    contract_spec = importlib.util.spec_from_file_location('_native_contract', source / 'packaging/run_native_regressions.py')
    contract = importlib.util.module_from_spec(contract_spec)
    contract_spec.loader.exec_module(contract)
    origins = {}
    for name, exports in {**contract.EXPORTS, 'agent.memory_provider': ('MemoryProvider',)}.items():
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve(strict=True)
        if not path.is_relative_to(core):
            raise RuntimeError('Native export origin mismatch: ' + name)
        for export in exports:
            getattr(module, export)
        origins[name] = {'origin': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'exports': list(exports)}
    spec = importlib.util.spec_from_file_location('memory_wiki', source / '__init__.py', submodule_search_locations=[str(source)])
    plugin = importlib.util.module_from_spec(spec)
    sys.modules['memory_wiki'] = plugin
    spec.loader.exec_module(plugin)
    native_base = importlib.import_module('agent.memory_provider').MemoryProvider
    if plugin.MemoryProvider is not native_base or native_base not in plugin.MemoryWikiProvider.__mro__:
        raise RuntimeError('Memory Wiki fell back to a non-native SDK')
    registry = importlib.import_module('tools.registry')
    if (Path(registry.__file__).resolve(strict=True) != core / 'tools/registry.py'
            or plugin.tool_error is not registry.tool_error or plugin.tool_result is not registry.tool_result):
        raise RuntimeError('Native error/result output functions not actually loaded')
    if stage == 'strict':
        trust = importlib.import_module('hermes_trust_core')
        public = plan['cold_processes'][stage]['trust_core']
        origin = Path(trust.__file__).resolve(strict=True)
        if (origin != Path(public['public_delivery_origin']).resolve(strict=True)
                or hashlib.sha256(origin.read_bytes()).hexdigest() != public['sha256']
                or not plugin._INJECTION_GUARD_AVAILABLE
                or plugin._sanitize_recalled is not trust.sanitize_recalled):
            raise RuntimeError('Genuine public trust-core origin/API mismatch')
    elif plugin._INJECTION_GUARD_AVAILABLE:
        raise RuntimeError('Legacy fallback absence contract changed during import')
    fixture_home = runroot / 'synthetic-home'
    if Path(os.environ['HERMES_HOME']).resolve() != fixture_home / 'hermes':
        raise RuntimeError('CI fixture home mismatch')
    (out / 'native-origins.json').write_text(json.dumps({'modules': origins, 'plugin_origin': str(Path(plugin.__file__).resolve()), 'native_MRO': True, 'executable': sys.executable}, indent=2) + '\n', encoding='utf-8')
    (fixture_home / 'native-origins.json').write_text(json.dumps({'origins': {name: row['origin'] for name, row in origins.items()}}, indent=2) + '\n', encoding='utf-8')
    import pytest
    class Recorder:
        def __init__(self):
            self.nodes, self.phases, self.collection_errors = [], [], []
            self.finished = False
        def pytest_collection_modifyitems(self, session, config, items):
            self.nodes = [item.nodeid for item in items]
        def pytest_collectreport(self, report):
            if report.failed:
                self.collection_errors.append(report.nodeid)
        def pytest_runtest_logreport(self, report):
            self.phases.append({'nodeid': report.nodeid, 'when': report.when, 'outcome': report.outcome, 'wasxfail': bool(getattr(report, 'wasxfail', False))})
        def pytest_sessionfinish(self, session, exitstatus):
            self.finished = True
            self.exitstatus = int(exitstatus)
    recorder = Recorder()
    args = ['-q', *targets, '--basetemp=' + str(runroot / 'pytest-temp'), '--junitxml=' + str(out / 'junit.xml'), '-o', 'cache_dir=' + str(runroot / 'pytest-cache'), '-o', 'log_file=' + str(out / 'pytest-detail.log')]
    try:
        return int(pytest.main(args, plugins=[recorder]))
    finally:
        (out / 'phases.json').write_text(json.dumps({'collected': recorder.nodes, 'phases': recorder.phases, 'collection_errors': recorder.collection_errors, 'session_finished': recorder.finished, 'exitstatus': getattr(recorder, 'exitstatus', None)}, indent=2) + '\n', encoding='utf-8')

if __name__ == '__main__':
    raise SystemExit(main())
