"""Small launch recorder for a disposable hosted CI venv; no SDK replacement.

Importing this module never installs hooks or launches a process. The state
methods are independently testable using synthetic identities and dictionaries.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import threading
import uuid


def durable_json(path, value):
    """Flush an atomic replacement; a missing/failed write is never positive proof."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def command_digest(command):
    return hashlib.sha256(json.dumps(list(command), ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


class LaunchRecorder:
    def __init__(self, config, owner_id):
        self.config, self.owner_id = config, owner_id
        self.directory = Path(config['runroot']) / 'launches'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.local = threading.local()

    def persist(self, row):
        durable_json(self.directory / (row['launch_id'] + '.json'), row)

    def _shape(self, command, executable=None, shell=False):
        if shell or not isinstance(command, (list, tuple)) or not command:
            return [], False, False, None
        command = [os.fsdecode(value) for value in command]
        same = Path(executable or command[0]).resolve() == Path(self.config['executable']).resolve() and Path(command[0]).resolve() == Path(self.config['executable']).resolve()
        site_enabled, index = True, 1
        while index < len(command) and command[index].startswith('-'):
            option = command[index]
            if option in ('-c', '-m', '--'):
                break
            if option in ('-W', '-X'):
                index += 2
                continue
            if option.startswith(('-W', '-X')):
                index += 1
                continue
            if not re.fullmatch('-[bBEIsSuOq]+', option):
                site_enabled = False  # Unknown flag cannot implicitly become proof.
                break
            if 'S' in option:
                site_enabled = False
            index += 1
        if index < len(command) and command[index] == '--':
            index += 1
        script = command[index] if index < len(command) and command[index] not in ('-c', '-m', '-') else None
        return command, same, site_enabled, script

    @contextmanager
    def expectation(self, command, role, reason):
        if role not in ('plugin', 'nonplugin_worker') or not reason:
            raise ValueError('Explicit CI role and reason required')
        command, same, site, operand = self._shape(command)
        if not same or not site:
            raise ValueError('Expectation requires the site-enabled CI interpreter')
        expected = {'explicit': True, 'command_sha256': command_digest(command), 'reason': reason, 'role': role, 'used': False}
        if role == 'nonplugin_worker':
            # No ambient exemption, wildcard, -c fixture or filename-only match.
            script = Path(operand).resolve() if operand and operand.endswith('.py') else None
            if script is None or not script.is_relative_to(Path(self.config['runroot']).resolve()) or not script.is_file():
                raise ValueError('A reviewed synthetic worker file under this runroot is required')
            expected.update(script=str(script), script_sha256=hashlib.sha256(script.read_bytes()).hexdigest())
        previous = getattr(self.local, 'expectation', None)
        self.local.expectation = expected
        try:
            yield
        finally:
            self.local.expectation = previous

    def expect_nonplugin(self, command, reason):
        return self.expectation(command, 'nonplugin_worker', reason)

    def expect_primary(self, command):
        return self.expectation(command, 'plugin', 'hosted native integration primary')

    def plan(self, command, env, executable=None, shell=False):
        command, same, site, _operand = self._shape(command, executable, shell)
        digest = command_digest(command)
        expected = getattr(self.local, 'expectation', None)
        explicit = expected is not None and not expected['used'] and expected['command_sha256'] == digest
        role = expected['role'] if explicit else 'plugin_capable'
        if explicit:
            expected['used'] = True
        expectation = {k: v for k, v in expected.items() if k not in ('used', 'role')} if explicit else None
        row = {'launch_id': uuid.uuid4().hex, 'run_id': self.config['run_id'], 'owner_id': self.owner_id,
               'role': role, 'lifecycle': 'may_terminate' if role == 'nonplugin_worker' else 'must_finish',
               'expectation': expectation, 'command_sha256': digest,
               'executable': str(Path(command[0]).resolve()) if command else '',
               'same_interpreter': same, 'site_enabled': site,
               'venv_launcher': sys.platform == 'win32' and sys.prefix != sys.base_prefix,
               'status': 'planned' if same and site else 'refused_shape', 'pid': None, 'returncode': None}
        self.persist(row)  # Before attempting creation, including rejected shapes.
        if not same or not site:
            raise RuntimeError('CI refuses foreign, -S, shell or unrecognized process shape')
        effective = dict(os.environ if env is None else env)
        effective['MW_CI_LAUNCH_ID'] = row['launch_id']
        return row, effective

    def created(self, row, pid):
        row.update(status='created', pid=pid)
        self.persist(row)

    def exited(self, row, returncode):
        if type(returncode) is int:
            row.update(status='exited', returncode=returncode)
            self.persist(row)

    def audit(self, event, args):
        if getattr(self, 'enabled', True) is False:
            return
        creation = event in ('subprocess.Popen', '_winapi.CreateProcess', 'os.posix_spawn', 'os.fork', 'os.forkpty', 'os.system', 'os.exec', 'os.spawn')
        foreign_api = event == 'ctypes.dlsym' and len(args) > 1 and str(args[1]).startswith(('CreateProcess', 'WinExec', 'ShellExecute'))
        if not creation and not foreign_api:
            return
        active = getattr(self.local, 'active', None)
        if active is not None and event == 'subprocess.Popen' and not active['audit_popen_seen']:
            active['audit_popen_seen'] = True
            return
        if active is not None and active['audit_popen_seen'] and event in ('_winapi.CreateProcess', 'os.posix_spawn') and not active['native_create_seen']:
            active['native_create_seen'] = True
            return
        row = {'launch_id': uuid.uuid4().hex, 'run_id': self.config['run_id'], 'owner_id': self.owner_id,
               'role': 'unknown', 'lifecycle': 'must_finish', 'status': 'unrecognized_launch', 'event': event,
               'pid': None, 'returncode': None, 'same_interpreter': False, 'site_enabled': False,
               'executable': '', 'command_sha256': '', 'expectation': None, 'venv_launcher': False}
        self.persist(row)
        raise RuntimeError('CI refuses an unrecorded process launch: ' + event)

    def install(self):
        if not self.config.get('hosted_ephemeral') or sys.prefix == sys.base_prefix:
            raise RuntimeError('Recorder installation is limited to the disposable hosted CI venv')
        if getattr(subprocess, '_memory_wiki_recorder', None) is not None:
            raise RuntimeError('Do not replace another launch recorder')
        recorder, original = self, subprocess.Popen
        self.enabled = True
        self.original = original
        signature = inspect.signature(original.__init__)
        class RecordedPopen(original):
            def __init__(self, *args, **kwargs):
                bound = signature.bind(self, *args, **kwargs)
                command = bound.arguments['args']
                self._mw_row, effective = recorder.plan(command, bound.arguments.get('env'), bound.arguments.get('executable'), bound.arguments.get('shell', False))
                bound.arguments['env'] = effective
                previous = getattr(recorder.local, 'active', None)
                recorder.local.active = {'audit_popen_seen': False, 'native_create_seen': False}
                try:
                    super().__init__(*bound.args[1:], **bound.kwargs)
                    recorder.created(self._mw_row, self.pid)
                except BaseException as exc:
                    self._mw_row.update(status='create_failed', pid=getattr(self, 'pid', None), error_type=type(exc).__name__)
                    recorder.persist(self._mw_row)
                    raise
                finally:
                    recorder.local.active = previous
            def wait(self, *args, **kwargs):
                result = super().wait(*args, **kwargs)
                recorder.exited(self._mw_row, result)
                return result
            def poll(self, *args, **kwargs):
                result = super().poll(*args, **kwargs)
                recorder.exited(self._mw_row, result)
                return result
        subprocess.Popen = RecordedPopen
        self.installed_class = RecordedPopen
        subprocess._memory_wiki_recorder = self
        sys.addaudithook(self.audit)
        return self

    def uninstall(self):
        # Controller-only restoration before read-only post-run git metadata.
        # Audit hooks are not removable, so this recorder is explicitly disabled.
        self.enabled = False
        if subprocess.Popen is not self.installed_class:
            raise RuntimeError('Another component replaced the CI launch recorder')
        subprocess.Popen = self.original
        del subprocess._memory_wiki_recorder
