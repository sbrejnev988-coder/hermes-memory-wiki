"""Source-owned finite проверки до правки и финальное sealing/replay; ревью только parent."""
from pathlib import Path
import ast
import datetime
import difflib
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cycle04_runner import B, E, N, OLD, REG, composite, digest, full_resources, install_guard, inventory, save

ADDED = {'scripts/ci_owned/cycle04_control.py', 'scripts/ci_owned/cycle04_runner.py',
         'scripts/ci_owned/cycle04_proof.py', 'tests/ci_owned/entry_cases.py'}
LABELS = ['exit-before-red', 'exit-partial-green', 'entry-red', 'entry-green', 'final-green']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def junit(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter('testcase'))
    counts = {'tests': len(cases), 'failures': sum(case.find('failure') is not None for case in cases),
              'errors': sum(case.find('error') is not None for case in cases),
              'skipped': sum(case.find('skipped') is not None for case in cases)}
    counts['passed'] = counts['tests'] - counts['failures'] - counts['errors'] - counts['skipped']
    groups = list(root.iter('testsuite'))
    assert all(sum(int(group.attrib[key]) for group in groups) == counts[key] for key in ('tests', 'failures', 'errors', 'skipped'))
    assert len({case.attrib['name'] for case in cases}) == len(cases)
    return counts, cases


def check_gate(label):
    root = E / 'gates' / label
    command, result = read(root / 'command.json'), read(root / 'result.json')
    counts, cases = junit(root / 'junit.xml')
    assert command['complete'] and not command['timed_out'] and command['source_unchanged']
    assert command['actual_exit'] == command['control_returncode'] == result['unit_result_code']
    assert command['command'] == result['command']
    assert counts == command['JUnit_counts'] == result['counts']
    assert command['source_files_before'] == result['source_files']
    assert composite(result['source_files']) == command['source_fingerprint'] == result['source_fingerprint']
    for name, key in [('result.json', 'result'), ('junit.xml', 'JUnit'), ('tests.log', 'tests_log'), ('stdout.log', 'stdout'), ('stderr.log', 'stderr')]:
        assert digest(root / name) == command[key]
    assert digest(root / 'tests.log') == result['tests_log'] and digest(root / 'junit.xml') == result['JUnit']
    assert command['credential_environment_inherited'] is False
    assert result['actual_test_command_launches'] == 0 and result['native_runtime_MRO_proof'] is False
    assert result['source_files']['tests/ci_owned/exit_cases.py'] == REG['baseline_files']['tests/ci_owned/exit_cases.py']
    return command, result, cases


def preedit():
    install_guard(E, extra_read_files=[E.parent / 'parent-5b9ea852-readback-20261004.json'])
    commands = {}
    for label in LABELS[:3]:
        commands[label], _, _ = check_gate(label)
    assert commands['exit-before-red']['actual_exit'] == 1
    assert commands['exit-before-red']['JUnit_counts'] == {'tests': 7, 'failures': 5, 'errors': 0, 'skipped': 0, 'passed': 2}
    assert commands['exit-partial-green']['actual_exit'] == 0
    assert commands['exit-partial-green']['JUnit_counts'] == {'tests': 7, 'failures': 0, 'errors': 0, 'skipped': 0, 'passed': 7}
    red = read(E / 'gates/entry-red/result.json')
    counts, cases = junit(E / 'gates/entry-red/junit.xml')
    assert counts == {'tests': 14, 'failures': 4, 'errors': 4, 'skipped': 0, 'passed': 6}
    errors = [case.find('error').text for case in cases if case.find('error') is not None]
    assert all('ValueError: A reviewed synthetic worker file under this runroot is required' in text and 'in expectation' in text for text in errors)
    current = inventory(N)
    for relative, expected in REG['baseline_files'].items():
        assert current[relative] == expected
    assert current['tests/ci_owned/entry_cases.py'] == red['source_files']['tests/ci_owned/entry_cases.py']
    save(E / 'pre-edit-verified.json', {'schema': 'ci-cycle04-source-owned-pre-edit-v1',
         'actual_before_ci_process': digest(N / 'scripts/ci_owned/ci_process.py'),
         'actual_before_memory_wiki_ci': digest(N / 'scripts/ci_owned/memory_wiki_ci.py'),
         'entry_test': current['tests/ci_owned/entry_cases.py'], 'actual_RED_exit': commands['entry-red']['actual_exit'],
         'complete_JUnit_counts': counts, 'setup_or_collection_errors': 0,
         'semantic_call_failure_events': red['assertion_failure_events'], 'semantic_call_error_events': red['assertion_error_events'],
         'classification_ru': '4 failure-method доказывают неправильное принятие dataarg; 4 error-method — прежний ValueError для legitimate scripts/options. Нет setup/collection ошибок.',
         'EXIT_finite_before_RED_and_partial_GREEN_verified': True, 'source_fingerprint_before_edit': composite(current),
         'preserved_transport_failure': digest(E / 'pre-edit-transport-failure.json'),
         'production_cycle': 4, 'remaining_automatic_cycles': 0, 'release_accepted': False})
    print(json.dumps({'preedit': 'verified', 'actual_RED_exit': 1, 'counts': counts,
                      'production_source_unchanged': True, 'source_fingerprint': composite(current)}))


def make_patch(before, after, selected):
    lines = []
    for relative in sorted(selected):
        old, new = before.get(relative, b''), after[relative]
        if old == new:
            continue
        assert old.endswith(b'\n') or not old
        assert new.endswith(b'\n') and b'\r\n' not in new
        lines.append('diff --git a/' + relative + ' b/' + relative + '\n')
        if not old:
            lines.append('new file mode 100644\n')
        lines.extend(difflib.unified_diff(old.decode('utf-8').splitlines(keepends=True),
                                        new.decode('utf-8').splitlines(keepends=True),
                                        fromfile='a/' + relative if old else '/dev/null', tofile='b/' + relative))
    return ''.join(lines)


def replay(text, baseline, allowed):
    files = dict(baseline)
    changed = []
    groups = re.split(r'^diff --git a/[^\n]+ b/[^\n]+\n', text, flags=re.M)[1:]
    for group in groups:
        lines = group.splitlines(keepends=True)
        old_name = next(line[4:].rstrip('\n') for line in lines if line.startswith('--- '))
        new_name = next(line[4:].rstrip('\n') for line in lines if line.startswith('+++ '))
        assert new_name.startswith('b/')
        relative = new_name[2:]
        assert relative in allowed and relative not in changed
        changed.append(relative)
        assert old_name == '/dev/null' and relative not in files or old_name == 'a/' + relative and relative in files
        old = files.get(relative, b'').decode('utf-8').splitlines(keepends=True)
        output, cursor = [], 0
        index = next(i for i, line in enumerate(lines) if line.startswith('@@ '))
        while index < len(lines):
            match = re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n', lines[index])
            assert match
            old_start, old_count, new_start, new_count = [int(value) if value is not None else 1 for value in match.groups()]
            position = old_start - 1 if old_count else old_start
            assert position >= cursor
            output.extend(old[cursor:position])
            cursor = position
            assert len(output) == (new_start - 1 if new_count else new_start)
            consumed = emitted = 0
            index += 1
            while index < len(lines) and not lines[index].startswith('@@ '):
                line = lines[index]
                assert line[:1] in (' ', '+', '-')
                if line[:1] in (' ', '-'):
                    assert cursor < len(old) and old[cursor] == line[1:]
                    cursor += 1
                    consumed += 1
                if line[:1] in (' ', '+'):
                    output.append(line[1:])
                    emitted += 1
                index += 1
            assert (consumed, emitted) == (old_count, new_count)
        output.extend(old[cursor:])
        files[relative] = ''.join(output).encode('utf-8')
    return files


def exact_root_cause_only(before, after):
    replacements = [
        ("return [], False, False\n", "return [], False, False, None\n"),
        ("        return command, same, site_enabled\n",
         "        if index < len(command) and command[index] == '--':\n            index += 1\n        script = command[index] if index < len(command) and command[index] not in ('-c', '-m', '-') else None\n        return command, same, site_enabled, script\n"),
        ("        command, same, site = self._shape(command)\n", "        command, same, site, operand = self._shape(command)\n"),
        ("            scripts = [Path(arg).resolve() for arg in command[1:] if arg.endswith('.py')]\n            if len(scripts) != 1 or not scripts[0].is_relative_to(Path(self.config['runroot']).resolve()) or not scripts[0].is_file():\n                raise ValueError('A reviewed synthetic worker file under this runroot is required')\n            expected.update(script=str(scripts[0]), script_sha256=hashlib.sha256(scripts[0].read_bytes()).hexdigest())\n",
         "            script = Path(operand).resolve() if operand and operand.endswith('.py') else None\n            if script is None or not script.is_relative_to(Path(self.config['runroot']).resolve()) or not script.is_file():\n                raise ValueError('A reviewed synthetic worker file under this runroot is required')\n            expected.update(script=str(script), script_sha256=hashlib.sha256(script.read_bytes()).hexdigest())\n"),
        ("        command, same, site = self._shape(command, executable, shell)\n", "        command, same, site, _operand = self._shape(command, executable, shell)\n")]
    expected = before.decode('utf-8')
    for old, new in replacements:
        assert expected.count(old) == 1
        expected = expected.replace(old, new)
    assert expected.encode('utf-8') == after, 'Production delta выходит за один operand root cause'


def seal():
    install_guard(E, extra_read_files=[E.parent / 'parent-5b9ea852-readback-20261004.json'])
    resources_start = full_resources()
    current = inventory(N)
    assert set(current) == set(REG['baseline_files']) | ADDED
    assert len(current) == 14
    source_bytes = {relative: (N / relative).read_bytes() for relative in current}
    baseline_bytes = {relative: (B / relative).read_bytes() for relative in REG['baseline_files']}
    changed = sorted(relative for relative in REG['baseline_files'] if current[relative] != REG['baseline_files'][relative])
    assert changed == ['scripts/ci_owned/ci_process.py']
    exact_root_cause_only(baseline_bytes[changed[0]], source_bytes[changed[0]])
    assert current['scripts/ci_owned/memory_wiki_ci.py']['sha256'] == 'e8ced00c2586cb1464c1bd279c492169a42ab479089eefe385e46ea01e6152c1'
    assert current['tests/ci_owned/exit_cases.py']['sha256'] == 'd476f6e86738c0572989cf43bb5b494dca961ec08d5e16d2d5ead85f3778c7f8'
    for relative in REG['baseline_files']:
        if relative not in changed:
            assert source_bytes[relative] == baseline_bytes[relative]
    parsed = []
    for relative, data in source_bytes.items():
        if relative.endswith('.py'):
            ast.parse(data, filename=relative)
            compile(data, relative, 'exec')
            parsed.append(relative)
    gates = {}
    results = {}
    expected = {'exit-before-red': (1, 7, 5, 0, 0), 'exit-partial-green': (0, 7, 0, 0, 0),
                'entry-red': (1, 14, 4, 4, 0), 'entry-green': (0, 14, 0, 0, 0),
                'final-green': (0, 52, 0, 0, 0)}
    for label in LABELS:
        command, result, _ = check_gate(label)
        counts = command['JUnit_counts']
        assert (command['actual_exit'], counts['tests'], counts['failures'], counts['errors'], counts['skipped']) == expected[label]
        assert len(result['denials']) == 11 and all(row.get('synthetic_event_only') for row in result['denials'])
        gates[label] = {'command': command['command'], 'actual_exit': command['actual_exit'],
                        'counts': counts, 'complete_JUnit': True, 'source_fingerprint': command['source_fingerprint'],
                        'command_receipt': {'path': str(E / 'gates' / label / 'command.json'), **digest(E / 'gates' / label / 'command.json')},
                        'result': digest(E / 'gates' / label / 'result.json'), 'JUnit': command['JUnit'],
                        'tests_log': command['tests_log'], 'assertion_failure_events': result['assertion_failure_events'],
                        'assertion_error_events': result['assertion_error_events']}
        results[label] = result
    for label in ('entry-green', 'final-green'):
        assert results[label]['source_files'] == current
    assert results['entry-red']['source_files']['scripts/ci_owned/ci_process.py'] == REG['baseline_files']['scripts/ci_owned/ci_process.py']
    assert results['entry-red']['source_files']['tests/ci_owned/entry_cases.py'] == current['tests/ci_owned/entry_cases.py']
    assert results['entry-red']['method_ids'] == results['entry-green']['method_ids']
    for label, path, expected_hash in [('exit-before-red', OLD / 'scripts/ci_owned/memory_wiki_ci.py', digest(OLD / 'scripts/ci_owned/memory_wiki_ci.py')),
                                       ('exit-partial-green', N / 'scripts/ci_owned/memory_wiki_ci.py', current['scripts/ci_owned/memory_wiki_ci.py']),
                                       ('entry-green', N / 'scripts/ci_owned/ci_process.py', current['scripts/ci_owned/ci_process.py'])]:
        assert results[label]['executed_source_files'][str(path)] == expected_hash
    old_ids = results['final-green']['method_ids']
    test_count_by_file = {name: sum(method.startswith(name + '.') for method in old_ids) for name in ('contract_cases', 'binding_cases', 'exit_cases', 'entry_cases')}
    assert test_count_by_file == {'contract_cases': 9, 'binding_cases': 22, 'exit_cases': 7, 'entry_cases': 14}
    freeze = read(E / 'input-freeze.json')
    for root, expected_files in freeze['roots'].items():
        assert inventory(Path(root)) == expected_files
    for path, expected_file in freeze['immutable_records'].items():
        assert digest(path) == expected_file
    save(E / 'readonly-readback.json', {'before': digest(E / 'input-freeze.json'),
         'roots': {root: {'files': len(files), 'fingerprint': composite(files), 'all_bytes_preserved': True} for root, files in freeze['roots'].items()},
         'immutable_records': freeze['immutable_records'], 'readonly_file_count': freeze['readonly_file_count'],
         'no_cleanup_reparse_follow_or_legacy_receipt_rewrite': True})
    productions = make_patch(baseline_bytes, source_bytes, changed)
    delta = make_patch(baseline_bytes, source_bytes, current)
    overlay = make_patch({}, source_bytes, current)
    inherited_old = {relative: (OLD / relative).read_bytes() for relative in inventory(OLD)}
    cumulative = make_patch(inherited_old, source_bytes, ['scripts/ci_owned/ci_process.py', 'scripts/ci_owned/memory_wiki_ci.py'])
    assert len(productions.encode()) < 6000 and len(cumulative.encode()) < 8000
    assert replay(productions, baseline_bytes, set(current))['scripts/ci_owned/ci_process.py'] == source_bytes['scripts/ci_owned/ci_process.py']
    assert replay(delta, baseline_bytes, set(current)) == source_bytes
    assert replay(overlay, {}, set(current)) == source_bytes
    cumulative_replay = replay(cumulative, inherited_old, set(current))
    for relative in inherited_old:
        assert cumulative_replay[relative] == source_bytes[relative]
    patches = {}
    for name, text in [('production.patch', productions), ('review-fix.patch', delta), ('overlay.patch', overlay), ('cumulative-production.patch', cumulative)]:
        with (E / name).open('xb') as stream:
            stream.write(text.encode('utf-8'))
        patches[name] = digest(E / name)
    for relative, data in replay(delta, baseline_bytes, set(current)).items():
        target = E / 'patch-replay' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
    assert inventory(E / 'patch-replay') == current
    added_lines = [line[1:] for line in delta.splitlines() if line.startswith('+') and not line.startswith('+++')]
    production_lines = [line[1:] for line in productions.splitlines() if line.startswith('+') and not line.startswith('+++')]
    patterns = {'secret_literal': r'(?i)(?:api_key|secret|password|token|passwd)\s*=\s*[\"\x27][^\"\x27]{6,}[\"\x27]',
                'shell': r'os\.system\(|shell\s*=\s*True', 'eval_exec': r'\b(?:eval|exec)\(',
                'pickle': r'pickle\.loads?\(', 'formatted_sql': r'execute\(f[\"\x27]'}
    scan = {scope: {name: [line for line in lines if re.search(pattern, line)] for name, pattern in patterns.items()}
            for scope, lines in [('production_added', production_lines), ('all_added', added_lines)]}
    whitespace = {relative: [number for number, line in enumerate(source_bytes[relative].decode('utf-8').splitlines(), 1) if line.rstrip(' \t') != line]
                  for relative in ADDED | set(changed)}
    assert not any(whitespace.values())
    assert not any(scan['production_added'].values())
    save(E / 'static-scan.json', {'scope_ru': 'Все added строки review-fix и отдельно production; без scanner approval.',
         'added_lines': len(added_lines), 'production_added_lines': len(production_lines), 'scan': scan,
         'whitespace_on_added_and_changed_files': whitespace, 'AST_compile_files': parsed,
         'known_test_scan_literals_ru': 'Regex/control-event literals в proof/runner не являются исполнением; независимый review обязан проверить их классификацию.'})
    save(E / 'denials.json', {'gates': {label: result['denials'] for label, result in results.items()},
         'EXIT_observations': results['exit-partial-green']['observations'], 'ENTRY_observations': results['entry-green']['observations'],
         'synthetic_events_and_dictionaries_only': True, 'actual_test_argv_executions': 0,
         'native_SDK_MRO_or_containment_proof': False})
    save(E / 'test-manifest.json', {'test_files': {relative: current[relative] for relative in current if relative.startswith('tests/')},
         'executed_method_ids': old_ids, 'executed_counts_by_file': test_count_by_file,
         'same_ENTRY_RED_GREEN_test_sha': current['tests/ci_owned/entry_cases.py'],
         'immutable_old31': True, 'immutable_EXIT7': True, 'recovery6': 'Byte-exact, не выполнялись',
         'five_actual_command_exits_and_counts': gates})
    fingerprint = composite(current)
    save(E / 'overlay-manifest.json', {'schema': 'ci-cycle04-sealed-overlay-v1', 'files': current,
         'raw_file_count': len(current), 'source_root': str(N), 'baseline_root': str(B),
         'baseline_fingerprint': REG['baseline_fingerprint'], 'overlay_fingerprint_sha256': fingerprint,
         'fingerprint_algorithm': 'SHA256(json.dumps(files,sort_keys=True,separators=(comma,colon)).encode(UTF8))',
         'changed_existing_paths': changed, 'added_paths': sorted(ADDED), 'patches': patches,
         'full_raw_replay_verified': True, 'replay_root': str(E / 'patch-replay'),
         'production_cycle': 4, 'release_accepted': False, 'remaining_automatic_cycles': 0})
    save(E / 'verification.json', {'schema': 'ci-cycle04-verified-candidate-v1', 'gates': gates,
         'source_fingerprint': fingerprint, 'source_files': current, 'patches': patches,
         'byte_exact_replay': True, 'production_delta_paths': changed,
         'inherited_EXIT_2line_patch_preserved': True, 'old31_EXIT7_ENTRY14_all_GREEN': True,
         'ENTRY_RED_errors_classified': read(E / 'pre-edit-verified.json'),
         'readonly_inputs_verified': freeze['readonly_file_count'], 'native_guards_docs_workflow_recovery_byte_exact': True,
         'resources_before_final_seal_outputs': resources_start,
         'actual_unit_worker_processes': len(LABELS), 'actual_test_argv_launches': 0, 'native_SDK_or_provider_imports': False,
         'SDK_standins': False, 'recorder_installed': False, 'native_FULL_Job_recovery': False,
         'network_model_publish_dispatch_restart': False, 'profiles_auth_config_data_core_changed': False,
         'transport_failure_preserved': digest(E / 'pre-edit-transport-failure.json'),
         'independent_review_performed': False, 'parent_review_required': True,
         'release_accepted': False, 'remaining_automatic_cycles': 0})
    save(E / 'handoff.json', {'status': 'CI-only candidate GREEN; независимое ревью parent ожидается',
         'summary': 'Сохранена EXIT +2-line правка; минимально исправлен только script-operand binding. Отдельные finite RED/GREEN команды и итоговые 52/52 unit methods подтверждены; release не принят.',
         'source_root': str(N), 'evidence_root': str(E), 'source_fingerprint': fingerprint,
         'per_file_sha_bytes': current, 'gates': gates, 'patches': patches,
         'artifacts': ['overlay-manifest.json', 'test-manifest.json', 'sealed-artifacts.json', 'final-resource-readback.json',
                       'readonly-readback.json', 'verification.json', 'production.patch', 'review-fix.patch', 'overlay.patch',
                       'cumulative-production.patch', 'patch-replay', 'denials.json', 'static-scan.json'],
         'budgets_receipt': 'final-resource-readback.json', 'release_accepted': False,
         'remaining_automatic_cycles': 0,
         'known_limits': ['52/52 — только stdlib preparation; synthetic dictionaries не native/MRO/runtime proof.',
                          'Старый metadata unit использует existing synthetic git-stdout adapter; это не public-repo readback.',
                          'Hosted FULL/recovery/Windows Job, SDK compatibility, publication/dispatch и live acceptance не выполнялись.',
                          'ENTRY RED: 4 failure-method плюс 4 semantic ValueError-method; setup/collection errors отсутствуют.',
                          'Сохранён Bash transport exit2 для отдельной pre-edit metadata команды; source-owned повтор проверки exit0.',
                          'Независимое ревью и release acceptance остаются исключительно у parent; новых automatic cycles нет.']})
    final_manifest_and_resources(current)
    assert inventory(N) == current
    for root, expected_files in freeze['roots'].items():
        assert inventory(Path(root)) == expected_files
    print(json.dumps({'status': 'CI_candidate_sealed_parent_review_pending', 'source_fingerprint': fingerprint,
                      'files': len(current), 'final_counts': gates['final-green']['counts'], 'patches': patches,
                      'resources': read(E / 'final-resource-readback.json'), 'release_accepted': False,
                      'remaining_automatic_cycles': 0}))


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def final_manifest_and_resources(source):
    """Собственный размер resource/manifest замыкается по bytes, затем проверяется read-only."""
    evidence = inventory(E)
    assert 'sealed-artifacts.json' not in evidence and 'final-resource-readback.json' not in evidence
    base = full_resources()
    added = 0
    resource_bytes = manifest_bytes = b''
    for _ in range(12):
        resource = dict(base)
        resource['new_source_evidence_bytes'] = base['new_source_evidence_bytes'] + added
        resource['total_CI_bytes'] = base['total_CI_bytes'] + added
        resource['shared_bytes'] = base['shared_bytes'] + added
        resource['shared_exact_roots'] = [dict(row) for row in base['shared_exact_roots']]
        for row in resource['shared_exact_roots']:
            if Path(row['root']) == N.parents[1]:
                row['bytes'] += added
                row['files'] += 2
        resource['C_free_bytes'] = base['C_free_bytes']
        resource['free_space_measured_before_two_final_receipts'] = True
        resource['logical_totals_include_this_receipt_and_manifest'] = True
        resource['method_ru'] = 'Фиксированная точка размеров двух финальных JSON; после записи exact local/shared read-only totals проверены. Free C измерен отдельно; allocated bytes не заявлены.'
        resource_bytes = encode(resource)
        resource_digest = {'sha256': hashlib.sha256(resource_bytes).hexdigest(), 'bytes': len(resource_bytes)}
        final_evidence = {**evidence, 'final-resource-readback.json': resource_digest}
        manifest = {'schema': 'ci-cycle04-complete-artifact-manifest-v1', 'source_root': str(N), 'evidence_root': str(E),
                    'source_files': source, 'evidence_files': dict(sorted(final_evidence.items())),
                    'source_file_count': len(source), 'evidence_file_count_excluding_self': len(final_evidence),
                    'source_fingerprint': composite(source), 'evidence_fingerprint_excluding_self': composite(final_evidence),
                    'self_exclusion': ['sealed-artifacts.json'],
                    'self_hash_delivery': 'Фактический hash этого manifest возвращён parent отдельно; self-reference невозможна.',
                    'all_failed_receipts_retained': True, 'future_review_reserved_bytes': 1000000,
                    'release_accepted': False, 'remaining_automatic_cycles': 0}
        manifest_bytes = encode(manifest)
        new_added = len(resource_bytes) + len(manifest_bytes)
        if new_added == added:
            break
        added = new_added
    else:
        raise AssertionError('Нет fixedpoint для artifact accounting')
    assert resource['new_source_evidence_bytes'] + 1000000 <= 4000000
    assert resource['total_CI_bytes'] + 1000000 <= 8000000
    assert resource['shared_bytes'] + 1000000 <= 512000000
    for name, data in [('final-resource-readback.json', resource_bytes), ('sealed-artifacts.json', manifest_bytes)]:
        with (E / name).open('xb') as stream:
            stream.write(data)
    actual = full_resources()
    assert actual['new_source_evidence_bytes'] == resource['new_source_evidence_bytes']
    assert actual['total_CI_bytes'] == resource['total_CI_bytes']
    assert actual['shared_bytes'] >= resource['shared_bytes']
    assert actual['C_free_bytes'] >= 9126805504
    for name, expected in final_evidence.items():
        assert digest(E / name) == expected
    assert set(inventory(E)) == set(final_evidence) | {'sealed-artifacts.json'}
    print(json.dumps({'artifact_manifest': digest(E / 'sealed-artifacts.json'),
                      'final_resource_receipt': digest(E / 'final-resource-readback.json'),
                      'logical_local_totals_exact': True, 'shared_after_readback_bytes': actual['shared_bytes'],
                      'C_free_after_readback_bytes': actual['C_free_bytes']}))


if __name__ == '__main__':
    assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
    action = sys.argv[1]
    assert action in ('preedit', 'seal')
    try:
        preedit() if action == 'preedit' else seal()
    except BaseException as exc:
        path = E / ('proof-failure-' + action + '.json')
        if not path.exists():
            save(path, {'error_type': type(exc).__name__, 'error_ru': str(exc),
                        'source_preserved': True, 'release_accepted': False, 'remaining_automatic_cycles': 0})
        raise
