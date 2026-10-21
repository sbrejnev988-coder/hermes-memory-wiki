"""Native integration child. Invoked only by hosted-only memory_wiki_ci.py."""
from pathlib import Path
import hashlib
import importlib
import importlib.util
import json
import os
import stat
import sys


class Recorder:
    """Keep the existing phases consumer schema; diagnostics live separately."""
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

    def snapshot(self):
        return {'collected': self.nodes, 'phases': self.phases,
                'collection_errors': self.collection_errors,
                'session_finished': self.finished,
                'exitstatus': getattr(self, 'exitstatus', None)}


def collection_reporter(source, out):
    # File-bound stdlib helper, not tests/__init__ or a plugin/SDK import.
    path = Path(source) / 'tests/helpers/collection_evidence.py'
    spec = importlib.util.spec_from_file_location('_ci_collection_evidence', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CollectionEvidence(out)


def _seal_collection(reporter):
    """Attest the helper's empty directory marker in an uploadable small file.

    upload-artifact does not carry empty directories. This is only a transfer
    witness for a quiescent owned snapshot, not authentication or test success.
    A missing/failed seal is rejected by ci_output_admission, never repaired.
    """
    try:
        status = reporter.status()
        if (status['complete'] is not True or status['phase_evidence'] != 'complete'
                or status['session_finished'] is not True):
            return
        reporter._check_owned()
        marker = reporter.directory / 'complete'
        info = os.lstat(marker)
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise RuntimeError('collection_marker_not_owned_directory')
        if any(marker.iterdir()) or (reporter.directory / 'refusal.json').exists():
            raise RuntimeError('collection_marker_not_exclusive')
        members = {}
        for name, cap in (('errors.jsonl', reporter.journal_cap), ('status.json', 8192)):
            path = reporter.directory / name
            if path.stat().st_size > cap:
                raise RuntimeError('collection_transfer_cap')
            raw = path.read_bytes()
            members[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        before = reporter.refusal_count
        reporter._artifact(reporter.directory / 'pending.json',
            {'schema': 'memory-stack.collection-transfer/v1', 'complete': True, 'members': members}, 1024)
        # _artifact records close errors without throwing; do not commit them.
        if reporter.refusal_count != before:
            return
        reporter._check_owned()
        destination = reporter.directory / 'complete.json'
        if destination.exists():
            raise RuntimeError('collection_transfer_collision')
        os.rename(reporter.directory / 'pending.json', destination)
    except BaseException as error:
        # Reporting must never replace pytest's exact return or primary cause.
        try:
            reporter._callback_refusal('transfer', error)
        except BaseException:
            pass  # The absent seal still makes artifact admission fail closed.


def dispatch_pytest(pytest_main, args, *, source, out):
    """The shared real pytest boundary; no native bootstrap bypass in the CLI."""
    recorder = Recorder()
    reporter = collection_reporter(source, out)
    try:
        return reporter.run(pytest_main, args, plugins=[recorder],
            finalize=lambda: reporter.write_phases(recorder.snapshot()))
    finally:
        _seal_collection(reporter)


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
    target = 'tests' if stage == 'full' else 'tests/ci_owned/recovery_cases.py'
    source_args = []
    if stage == 'full':
        from fixture_prerequisites import native_pytest_args
        source_result = json.loads((runroot / 'source-prerequisites/source-results.json').read_text(encoding='utf-8'))
        source_args = native_pytest_args(source, source_result)
    args = ['-q', target, '--confcutdir=' + str(source / 'tests'), *source_args, '--basetemp=' + str(runroot / 'pytest-temp'), '--junitxml=' + str(out / 'junit.xml'), '-o', 'cache_dir=' + str(runroot / 'pytest-cache'), '-o', 'log_file=' + str(out / 'pytest-detail.log')]
    return dispatch_pytest(pytest.main, args, source=source, out=out)

if __name__ == '__main__':
    raise SystemExit(main())
