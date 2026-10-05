"""Native integration child. Invoked only by hosted-only memory_wiki_ci.py."""
from pathlib import Path
import hashlib
import importlib
import importlib.util
import json
import os
import sys


def main():
    source = Path(os.environ['MW_CI_SOURCE']).resolve(strict=True)
    core = Path(os.environ['MW_CI_CORE']).resolve(strict=True)
    runroot = Path(os.environ['MW_CI_RUNROOT']).resolve(strict=True)
    stage = sys.argv[1]
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
    target = 'tests' if stage == 'full' else 'tests/ci_owned/recovery_cases.py'
    args = ['-q', target, '--basetemp=' + str(runroot / 'pytest-temp'), '--junitxml=' + str(out / 'junit.xml'), '-o', 'cache_dir=' + str(runroot / 'pytest-cache'), '-o', 'log_file=' + str(out / 'pytest-detail.log')]
    try:
        return int(pytest.main(args, plugins=[recorder]))
    finally:
        (out / 'phases.json').write_text(json.dumps({'collected': recorder.nodes, 'phases': recorder.phases, 'collection_errors': recorder.collection_errors, 'session_finished': recorder.finished, 'exitstatus': getattr(recorder, 'exitstatus', None)}, indent=2) + '\n', encoding='utf-8')

if __name__ == '__main__':
    raise SystemExit(main())
