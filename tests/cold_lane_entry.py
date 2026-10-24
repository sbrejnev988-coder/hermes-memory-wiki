"""Prepared cold child derived from ci_child.py; NOT native launch admission.

Separate strict/legacy/recovery processes only, through an independently
admitted existing recorder/bootstrap. Current COLD_LANES blocks all three.
No new CI job, controller, SDK substitute, or selection filter is introduced.
"""
from pathlib import Path
import ast
import re
import stat
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import sys


def _source_path(value):
    """Validate literal repository paths; never normalize rejected tokens."""
    if type(value) is not str or not value or '\\' in value:
        raise ValueError('partition_path')
    if any(ord(c) < 32 or c in ':<>"|?*' for c in value):
        raise ValueError('partition_path')
    for part in value.split('/'):
        stem = part.split('.', 1)[0].upper()
        if (part in ('', '.', '..') or part.endswith(('.', ' '))
                or stem in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'}
                or re.fullmatch(r'(?:COM|LPT)[1-9¹²³]', stem)):
            raise ValueError('partition_path')
    return value


def _sha256(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def partition_digest(rows):
    """File identities only, not pytest node IDs or execution coverage."""
    items = sorted([row['path'], row['sha256']] for row in rows)
    return hashlib.sha256(json.dumps(items, ensure_ascii=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


# Explicit contracts for actual bindings, NOT transitive inference from peers.
_STAGE_PEER = 'tests/test_connector_stage_admission.py'
_STAGE_CONSUMERS = ('tests/test_connector_legacy_schema_owner.py',
                    'tests/test_connector_stage_home_compat.py')
_CI_PEER = 'tests/ci_owned/binding_cases.py'
_CI_ENTRIES = ('tests/ci_owned/entry_cases.py', 'tests/ci_owned/exit_cases.py')
_CI_INPUTS = (_CI_PEER, 'scripts/ci_owned/ci_process.py',
              'scripts/ci_owned/ci_bootstrap.py', 'scripts/ci_owned/memory_wiki_ci.py')
_CI_RUNPY = ("import runpy,sys; from pathlib import Path; "
             "entry=Path(sys.argv.pop(1)).absolute(); sys.path.insert(0,str(entry.parent)); "
             "runpy.run_path(str(entry),run_name='__main__')")


def isolated_ci_entry(path):
    """Supported stdlib invocation: bind only the entry's own peer directory.

    Run from the complete source root with MW_CI_UNIT_FIXTURES pointing at an
    existing, empty owned scratch directory. No site/SDK path is introduced.
    binding_cases itself binds scripts/ci_owned for its existing lazy load API.
    """
    if path not in _CI_ENTRIES:
        raise ValueError('partition_ci_bootstrap_path')
    argv = ['python', '-I', '-B', '-S', '-c', _CI_RUNPY, path]
    return {'kind': 'unittest', 'invocation': 'python -I -B -S -c "' + _CI_RUNPY + '" ' + path,
            'callables': {}, 'bootstrap': {'argv': argv, 'path_binding': 'tests/ci_owned',
                                         'peer': _CI_PEER, 'source_inputs': list(_CI_INPUTS),
                                         'fixture_env': 'MW_CI_UNIT_FIXTURES'}}


def validate_partition(plan, source_inputs=None):
    """Pure metadata/bytes validation. Never import tests, provider or SDK.

    source_inputs is an independently enumerated complete tests/**/*.py census,
    plus exactly source_pins. Metadata-only validation cannot attest disk bytes.
    Success grants no bootstrap, recorder, trust or native execution authority.
    """
    if type(plan) is not dict or plan.get('schema') != 'memory-stack.current-source-cold-lanes/v1':
        raise ValueError('partition_schema')
    if (plan.get('native_sdk_execution_admitted') is not False
            or plan.get('no_selection_filters') is not True
            or type(plan.get('needs_final_rebind')) is not bool):
        raise ValueError('partition_not_execution_authority')
    rows, requirements = plan.get('partition'), plan.get('requirements')
    if type(rows) is not list or not rows or type(requirements) is not dict or not requirements:
        raise ValueError('partition_shape')
    if any(type(k) is not str or not k or type(v) is not str or not v for k, v in requirements.items()):
        raise ValueError('partition_requirements')
    by_path = {}
    roles = {'pytest', 'unittest-explicit', 'callable', 'source-only', 'support', 'historical'}
    lanes = {'strict', 'legacy', 'source-explicit', 'native-explicit-packet', 'support', 'historical'}
    for row in rows:
        if type(row) is not dict:
            raise ValueError('partition_row')
        path = _source_path(row.get('path'))
        if not path.startswith('tests/') or not path.endswith('.py') or path in by_path:
            raise ValueError('partition_duplicate_or_non_test_path')
        if not _sha256(row.get('sha256')):
            raise ValueError('partition_sha256')
        role, lane = row.get('role'), row.get('lane')
        if type(role) is not str or role not in roles or type(lane) is not str or lane not in lanes:
            raise ValueError('partition_role_or_lane')
        if type(row.get('reason')) is not str or not row['reason']:
            raise ValueError('partition_reason')
        required, peers = row.get('requires'), row.get('peers')
        if (type(required) is not list or not required or any(type(k) is not str or k not in requirements for k in required)
                or len(set(required)) != len(required) or type(peers) is not list
                or any(type(p) is not str for p in peers) or len(set(peers)) != len(peers)):
            raise ValueError('partition_prerequisites_or_peers')
        if type(row.get('requires_sdk_absent')) is not bool:
            raise ValueError('partition_absence_type')
        if (row['requires_sdk_absent'] or role == 'source-only') and lane != 'source-explicit':
            raise ValueError('partition_source_native_intersection')
        entry = row.get('entry')
        if role in ('support', 'historical'):
            if lane != role or entry is not None:
                raise ValueError('partition_noncase_entry')
        else:
            if (type(entry) is not dict or type(entry.get('kind')) is not str
                    or entry['kind'] not in ('pytest', 'unittest', 'callable', 'source-controller')
                    or type(entry.get('invocation')) is not str or not entry['invocation']
                    or type(entry.get('callables')) is not dict):
                raise ValueError('partition_entry')
            if any(type(k) is not str or not k or type(v) is not str for k, v in entry['callables'].items()):
                raise ValueError('partition_callable')
            expected_kind = {'pytest': 'pytest', 'unittest-explicit': 'unittest', 'callable': 'callable'}
            if role in expected_kind and entry['kind'] != expected_kind[role]:
                raise ValueError('partition_entry_role')
            if lane in ('strict', 'legacy') and (role != 'pytest' or entry['kind'] != 'pytest'):
                raise ValueError('partition_native_not_pytest')
            if lane == 'native-explicit-packet' and role != 'callable':
                raise ValueError('partition_native_packet_role')
            if lane in ('support', 'historical'):
                raise ValueError('partition_case_not_executable')
        by_path[path] = row
    if (type(plan.get('file_count')) is not int or plan['file_count'] != len(rows)
            or not _sha256(plan.get('input_inventory_sha256'))
            or plan['input_inventory_sha256'] != partition_digest(rows)):
        raise ValueError('partition_inventory_digest_or_count')
    for row in rows:
        if any(_source_path(p) not in by_path or p == row['path'] for p in row['peers']):
            raise ValueError('partition_peer_missing')
    # These two modules actually export stage=peer.stage and consume it as a
    # fixture. A false absence flag cannot turn that contract into native pytest.
    for path in (_STAGE_PEER, *_STAGE_CONSUMERS):
        row = by_path.get(path, {})
        if (row.get('role') != 'source-only' or row.get('lane') != 'source-explicit'
                or row.get('requires_sdk_absent') is not True
                or 'source_pytest_absent' not in row.get('requires', [])
                or any(k.startswith('native_') for k in row.get('requires', []))
                or not row.get('entry') or row['entry']['kind'] != 'pytest'):
            raise ValueError('partition_fixture_lane:' + path)
        if path in _STAGE_CONSUMERS:
            binding = {'local': 'stage', 'peer': _STAGE_PEER, 'fixture': 'stage'}
            if row.get('fixture_binding') != binding or _STAGE_PEER not in row['peers']:
                raise ValueError('partition_fixture_binding:' + path)
    for path in _CI_ENTRIES:
        row = by_path.get(path, {})
        if (row.get('role') != 'unittest-explicit' or row.get('lane') != 'source-explicit'
                or row.get('entry') != isolated_ci_entry(path)):
            raise ValueError('partition_ci_bootstrap:' + path)
        if (_CI_PEER not in row['peers']
                or not {'exact_source_inputs', 'source_stdlib', 'isolated_ci_peer_binding'}.issubset(row['requires'])):
            raise ValueError('partition_ci_bootstrap_prerequisites:' + path)
    hybrid = 'tests/test_hybrid_budget_observability_source.py'
    cohort = 'tests/test_hybrid_current_cohort.py'
    for path, expected in ((hybrid, hybrid_source_entry()), (cohort, cohort_source_entry())):
        if path not in by_path:
            continue  # Historical descriptors; current byte census still detects omissions.
        row = by_path.get(path, {})
        if (row.get('role') != 'source-only' or row.get('lane') != 'source-explicit'
                or row.get('requires_sdk_absent') is not True
                or row.get('entry') != expected
                or not {'exact_source_inputs', 'source_stdlib', 'source_controller',
                        'explicit_source_binding'}.issubset(row.get('requires', []))
                or any(k.startswith('native_') for k in row.get('requires', []))):
            raise ValueError('partition_hybrid_source_contract:' + path)
    processes = plan.get('cold_processes')
    if type(processes) is not dict or set(processes) != {'strict', 'legacy', 'legacy-recovery'}:
        raise ValueError('partition_cold_processes')
    selected = set()
    for stage, lane in processes.items():
        if type(lane) is not dict or lane.get('HERMES_SECURITY_STRICT') != ('1' if stage == 'strict' else '0'):
            raise ValueError('partition_cold_mode')
        targets = lane.get('targets')
        if (type(targets) is not list or not targets or any(type(p) is not str for p in targets)
                or len(set(targets)) != len(targets)):
            raise ValueError('partition_cold_targets')
        expected = ([row['path'] for row in rows if row['lane'] == stage]
                    if stage != 'legacy-recovery' else ['tests/ci_owned/recovery_cases.py'])
        if targets != expected or any(p not in by_path or by_path[p]['role'] != 'pytest' for p in targets):
            raise ValueError('partition_cold_target_closure')
        if any(by_path[p]['lane'] == 'source-explicit' or by_path[p]['requires_sdk_absent'] for p in targets):
            raise ValueError('partition_source_native_intersection')
        if stage != 'legacy-recovery':
            if selected.intersection(targets):
                raise ValueError('partition_cold_overlap')
            selected.update(targets)
    source_targets = [row['path'] for row in rows if row['lane'] == 'source-explicit']
    if plan.get('source_explicit_targets') != source_targets:
        raise ValueError('partition_source_target_closure')
    if plan.get('source_entry') not in source_targets:
        raise ValueError('partition_source_entry')
    fixture_inputs = plan.get('source_fixture_inputs')
    if type(fixture_inputs) is not list or any(type(p) is not str or p not in by_path or by_path[p]['role'] != 'support' for p in fixture_inputs):
        raise ValueError('partition_source_fixture')
    packets = plan.get('native_explicit_packets')
    if (type(packets) is not list or any(type(p) is not dict for p in packets)
            or [p.get('path') for p in packets] != [row['path'] for row in rows if row['lane'] == 'native-explicit-packet']):
        raise ValueError('partition_native_packet_closure')
    pins = plan.get('source_pins')
    if type(pins) is not list or not pins:
        raise ValueError('partition_source_pins')
    pin_map = {}
    for pin in pins:
        if type(pin) is not dict:
            raise ValueError('partition_source_pin')
        path = _source_path(pin.get('path'))
        if path in pin_map or path in by_path or not _sha256(pin.get('sha256')):
            raise ValueError('partition_source_pin')
        pin_map[path] = pin['sha256']
    if pin_map.get('__init__.py') != plan.get('frozen_provider_sha256'):
        raise ValueError('partition_provider_pin')
    if any(path not in by_path and path not in pin_map for path in _CI_INPUTS):
        raise ValueError('partition_ci_bootstrap_inputs')
    if (hybrid in by_path or cohort in by_path) and any(path not in pin_map for path in ('scripts/ci_owned/hybrid_source.py', 'semantic_io.py')):
        raise ValueError('partition_hybrid_source_inputs')
    pending = plan.get('pending_peer_inputs')
    if type(pending) is not list or any(type(p) is not dict for p in pending):
        raise ValueError('partition_pending_peer')
    pending_paths = []
    for peer in pending:
        path = _source_path(peer.get('path'))
        if path in by_path or path in pin_map or peer.get('sha256') is not None or peer.get('status') != 'PENDING_FINAL_MERGE_REBIND':
            raise ValueError('partition_pending_peer')
        pending_paths.append(path)
    if len(set(pending_paths)) != len(pending_paths) or pending and not plan['needs_final_rebind']:
        raise ValueError('partition_pending_rebind')
    targets = plan.get('native_targets')
    if type(targets) is not dict or set(targets) != {'ordinary_cli', 'hosted_full', 'managed_sdk'}:
        raise ValueError('partition_native_targets')
    for target in targets.values():
        if type(target) is not dict or type(target.get('entry')) is not str or target['entry'] not in pin_map:
            raise ValueError('partition_native_target_entry')
        revision = target.get('declared_revision')
        if revision is not None and (type(revision) is not str or re.fullmatch('[0-9a-f]{40}', revision) is None):
            raise ValueError('partition_native_target_revision')
    if source_inputs is not None:
        if (type(source_inputs) is not dict or any(type(p) is not str or type(raw) is not bytes for p, raw in source_inputs.items())
                or set(source_inputs) != set(by_path) | set(pin_map)):
            raise ValueError('partition_source_input_membership')
        for path, raw in source_inputs.items():
            expected = by_path[path]['sha256'] if path in by_path else pin_map[path]
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('partition_stale_source:' + path)
        for target in targets.values():
            tree = ast.parse(source_inputs[target['entry']], filename=target['entry'])
            revisions = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id == 'CORE_SHA' for t in n.targets)]
            if revisions != ([] if target['declared_revision'] is None else [target['declared_revision']]):
                raise ValueError('partition_native_target_pin:' + target['entry'])
        if hybrid in by_path or cohort in by_path:
            factory_tree = ast.parse(source_inputs['scripts/ci_owned/hybrid_source.py'])
            factories = [n for n in factory_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'make_suite']
            if (len(factories) != 1 or ast.unparse(factories[0].args) !=
                    'test_loader, *, test_sha256, test_filename, source_loader, expected_sha256, filename, semantic_loader, semantic_sha256, semantic_filename'):
                raise ValueError('partition_hybrid_factory_signature')
        for path, row in by_path.items():
            tree = ast.parse(source_inputs[path], filename=path)
            if path in _STAGE_CONSUMERS:
                assignments = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign)
                               for t in n.targets if isinstance(t, ast.Name)}
                expected = {'stage': 'peer.stage',
                            '_SPEC': "importlib.util.spec_from_file_location(PEER_NAME, Path(__file__).with_name('test_connector_stage_admission.py'))",
                            'peer': 'importlib.util.module_from_spec(_SPEC)'}
                spec = assignments.get('_SPEC')
                # The private module name differs; the exact peer path does not.
                if isinstance(spec, ast.Call) and spec.args and isinstance(spec.args[0], ast.Constant):
                    expected['_SPEC'] = expected['_SPEC'].replace('PEER_NAME', repr(spec.args[0].value))
                actual = {k: ast.unparse(assignments[k]) for k in expected if k in assignments}
                loaded = any(isinstance(n, ast.Expr) and ast.unparse(n.value) == '_SPEC.loader.exec_module(peer)' for n in tree.body)
                consumed = any(isinstance(n, ast.FunctionDef) and n.name.startswith('test_')
                               and any(a.arg == 'stage' for a in n.args.args) for n in tree.body)
                if actual != expected or not loaded or not consumed:
                    raise ValueError('partition_fixture_source_binding:' + path)
            if path == _STAGE_PEER:
                fixtures = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'stage']
                guards = {"importlib.util.find_spec('agent') is None",
                          "importlib.util.find_spec('hermes_trust_core') is None",
                          'module.MemoryProvider.__module__ == module.__name__'}
                if (len(fixtures) != 1 or not any(ast.unparse(d) == 'pytest.fixture' for d in fixtures[0].decorator_list)
                        or not guards.issubset({ast.unparse(n.test) for n in fixtures[0].body if isinstance(n, ast.Assert)})):
                    raise ValueError('partition_fixture_source_guards')
            if path in _CI_ENTRIES:
                imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == 'binding_cases']
                if (len(imports) != 1 or imports[0].level != 0
                        or [(n.name, n.asname) for n in imports[0].names] != [('fixtures', None), ('load', None)]):
                    raise ValueError('partition_ci_initial_import:' + path)
            if path == _CI_PEER:
                functions = {n.name: ast.unparse(n.args) for n in tree.body if isinstance(n, ast.FunctionDef)}
                statements = {ast.unparse(n) for n in tree.body}
                if (functions.get('fixtures') != '' or functions.get('load') != 'name'
                        or "SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts/ci_owned'" not in statements
                        or 'sys.path.insert(0, str(SCRIPTS))' not in statements):
                    raise ValueError('partition_ci_peer_source_binding')
            functions = {n.name: ast.unparse(n.args) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            entry = row['entry']
            if entry and any(functions.get(k) != v for k, v in entry['callables'].items()):
                raise ValueError('partition_callable_signature:' + path)
            test_functions = any(name.startswith('test_') for name in functions)
            test_classes = any(isinstance(n, ast.ClassDef) and any(isinstance(m, ast.FunctionDef) and m.name.startswith('test') for m in n.body) for n in tree.body)
            if row['role'] == 'pytest' and not (test_functions or test_classes):
                raise ValueError('partition_no_collectible_case:' + path)
            if row['role'] in ('support', 'historical') and (test_functions or test_classes):
                raise ValueError('partition_hidden_cases:' + path)
    return {'file_count': len(rows), 'role_counts': {role: sum(row['role'] == role for row in rows) for role in sorted(roles)},
            'source_inputs_verified': source_inputs is not None, 'native_sdk_execution_admitted': False}


def hybrid_source_entry():
    """Explicit two-loader contract; __test__=False is not SDK compatibility."""
    return {'kind': 'source-controller',
            'invocation': 'Existing SOURCE runner -> scripts/ci_owned/hybrid_source.py:make_suite with SHA-bound test/provider/semantic loaders -> unittest.TestSuite',
            'callables': {'source_suite': 'source_loader, *, expected_sha256, filename, semantic_loader, semantic_sha256, semantic_filename'},
            'binding': {'entry': 'scripts/ci_owned/hybrid_source.py', 'factory': 'make_suite',
                        'source_inputs': ['tests/test_hybrid_budget_observability_source.py', '__init__.py', 'semantic_io.py'],
                        'loader_roles': {'test_loader': 'reviewed test declarations',
                                         'source_loader': 'exact provider bytes; lazy setUpClass read',
                                         'semantic_loader': 'exact semantic_io bytes; lazy setUpClass read'}}}


def cohort_source_entry():
    return {'kind': 'source-controller',
            'invocation': 'Existing SOURCE runner -> explicit make_suite with complete current census and retained prior COLD transports; unittest lifecycle',
            'callables': {'make_suite': 'inputs, retained_inputs, plan, cold_module, hybrid_entry'}}


def cold_plan():
    # A JSON plan is NOT authority. Even a finalized plan needs separate real
    # native admission and the existing independently admitted bootstrap.
    plan = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    validate_partition(plan)
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
    # Independently census physical test inputs, not just paths named by JSON.
    # No imports/collection/SDK grants occur during this source-only check.
    source_paths = [source / pin['path'] for pin in plan['source_pins']]
    pending = [source / 'tests']
    while pending:
        directory = pending.pop()
        for component in (directory, *directory.parents):
            info = component.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                raise RuntimeError('Source input link/reparse refused')
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                    raise RuntimeError('Source input link/reparse refused')
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif path.suffix == '.py':
                    if not stat.S_ISREG(info.st_mode):
                        raise RuntimeError('Source input is not regular')
                    source_paths.append(path)
    source_inputs = {}
    for path in source_paths:
        for component in (path, *path.parents):
            info = component.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                raise RuntimeError('Source input link/reparse refused')
        if not stat.S_ISREG(path.lstat().st_mode):
            raise RuntimeError('Source input is not regular')
        source_inputs[path.relative_to(source).as_posix()] = path.read_bytes()
    validate_partition(plan, source_inputs)
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
    reporter = contract.collection_reporter(source, out)
    import pytest
    return run_tests(pytest.main, targets, runroot, reporter)


def run_tests(pytest_main, targets, runroot, reporter):
    """Existing recorder with causal diagnostics; not native launch admission."""
    out = runroot / 'public'
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
    def save_phases():
        reporter.write_phases({'collected': recorder.nodes, 'phases': recorder.phases,
                               'collection_errors': recorder.collection_errors,
                               'session_finished': recorder.finished,
                               'exitstatus': getattr(recorder, 'exitstatus', None)})
    return int(reporter.run(pytest_main, args, plugins=[recorder], finalize=save_phases))

if __name__ == '__main__':
    raise SystemExit(main())
