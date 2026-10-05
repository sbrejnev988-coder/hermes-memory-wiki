"""Disposable offline CI hooks; importing this file does NOT import the SDK."""
import ipaddress
import atexit
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import uuid


def durable_json(path, value):
    # Lazy CI-helper import keeps original network-only stdlib units standalone.
    from ci_process import durable_json as publish
    publish(path, value)


def publish_failure(receipt, target, state, exc):
    """Publish the actual failure before exit; never leave a clean startup record."""
    receipt.update(state=state, finished=False, error_type=type(exc).__name__)
    receipt.setdefault('violations', []).append(state)
    durable_json(target, receipt)


def finalize_receipt(receipt, target, scan, exit_func=os._exit):
    """Pure publication seam. Synthetic fault tests do not load a native core."""
    try:
        receipt['plugin_classes'] = scan()
        if any(cls['native_MRO'] is not True for cls in receipt['plugin_classes']):
            receipt['violations'].append('plugin_native_origin_or_MRO')
        if receipt.get('plugin_attempted') and not receipt['plugin_classes']:
            receipt['violations'].append('plugin_attempted_without_MRO')
        if receipt['role'] == 'nonplugin_worker' and receipt['plugin_classes']:
            receipt['violations'].append('nonplugin_role_loaded_plugin')
        receipt.update(finished=True, state='violation' if receipt['violations'] else 'finished')
        durable_json(target, receipt)
    except BaseException as exc:
        try:
            publish_failure(receipt, target, 'finalize_failed', exc)
        finally:
            exit_func(86)
        return
    if receipt['violations']:
        exit_func(86)


def plugin_audit(event, args, config, receipt, target):
    attempted = event == 'import' and (args[0] == 'memory_wiki' or args[0].startswith('memory_wiki.'))
    if event == 'exec':
        filename = args[0].co_filename
        if not filename.startswith('<'):
            path = Path(filename).resolve()
            attempted = (path == Path(config['source_origin']) or
                         (path.is_relative_to(Path(config['runroot'])) and path.is_file()
                          and hashlib.sha256(path.read_bytes()).hexdigest() == config['source_sha256']))
    if attempted:
        receipt['plugin_attempted'] = True
        if receipt['role'] == 'nonplugin_worker':
            receipt['violations'].append('nonplugin_plugin_execution_denied')
        durable_json(target, receipt)
        if receipt['role'] == 'nonplugin_worker':
            raise PermissionError('Explicit non-plugin worker cannot execute Memory Wiki')


def configure(config_path):
    """Called by the disposable CI .pth before each site-enabled child's code."""
    if getattr(sys, '_memory_wiki_ci_configured', False):
        return
    sys._memory_wiki_ci_configured = True
    # Even a broken config/bootstrap gets durable orphan evidence. Missing files
    # after a storage failure also fail closed against the launch inventory.
    fallback_id = uuid.uuid4().hex
    target = Path(config_path).parent / 'bindings' / ('bootstrap-failure-' + fallback_id + '.json')
    receipt = {'launch_id': fallback_id, 'pid': os.getpid(), 'ppid': os.getppid(),
               'started': False, 'finished': False, 'state': 'bootstrapping',
               'plugin_classes': [], 'violations': [], 'plugin_attempted': False,
               'nonplugin_guard_armed': False}
    try:
        from ci_process import LaunchRecorder
        config = json.loads(Path(config_path).read_text(encoding='utf-8'))
        identity = os.environ.get('MW_CI_LAUNCH_ID', '')
        if not re.fullmatch('[0-9a-f]{32}', identity):
            raise RuntimeError('Site-enabled child has no admitted launch identity')
        core, source, bindings = (Path(config[k]).resolve(strict=True) for k in ('core', 'source', 'bindings'))
        launch = json.loads((Path(config['runroot']) / 'launches' / (identity + '.json')).read_text(encoding='utf-8'))
        executable = str(Path(sys.executable).resolve())
        if launch['run_id'] != config['run_id'] or launch['executable'] != executable or executable != config['executable']:
            raise RuntimeError('Child launch identity/executable mismatch')
        if launch['role'] not in ('plugin', 'plugin_capable', 'nonplugin_worker') or launch['same_interpreter'] is not True or launch['site_enabled'] is not True:
            raise RuntimeError('Child launch role/shape not admitted')
        target = bindings / (identity + '-' + str(os.getpid()) + '.json')
        receipt.update({k: launch[k] for k in ('launch_id', 'run_id', 'owner_id', 'role', 'command_sha256')})
        receipt.update(executable=executable, source_sha=config['source_sha'], core_sha=config['core_sha'],
                       network_boundary='Python audit hook: loopback only; not OS network containment')
        durable_json(target, receipt)
        for directory in (source, core):
            sys.path.insert(0, str(directory))
        sys.addaudithook(network_audit)
        sys.addaudithook(lambda event, args: plugin_audit(event, args, config, receipt, target))
        recorder = LaunchRecorder(config, identity).install()
        base_module = importlib.import_module('agent.memory_provider')
        base_path = Path(base_module.__file__).resolve(strict=True)
        base_hash = hashlib.sha256(base_path.read_bytes()).hexdigest()
        if str(base_path) != config['memory_provider_origin'] or base_hash != config['memory_provider_sha256']:
            raise RuntimeError('MemoryProvider native origin/hash mismatch')
        base = base_module.MemoryProvider
        if base.__module__ != 'agent.memory_provider':
            raise RuntimeError('Native MemoryProvider module mismatch')
        if receipt['role'] == 'nonplugin_worker':
            expectation = launch['expectation']
            worker = Path(expectation['script']).resolve(strict=True)
            if not expectation['explicit'] or expectation['command_sha256'] != launch['command_sha256'] or not worker.is_relative_to(Path(config['runroot'])) or hashlib.sha256(worker.read_bytes()).hexdigest() != expectation['script_sha256']:
                raise RuntimeError('Non-plugin lifecycle expectation is not command/byte bound')
            # The audit guard was armed before native import and before user code.
            receipt['nonplugin_guard_armed'] = True
        receipt.update(memory_provider_origin=str(base_path), memory_provider_sha256=base_hash,
                       native_class_module=base.__module__, started=True, state='native_ready')
        durable_json(target, receipt)
        def scan():
            classes = []
            for name, module in list(sys.modules.items()):
                if module is None:
                    continue
                cls = vars(module).get('MemoryWikiProvider')
                if not isinstance(cls, type) or cls.__module__ != name:
                    continue
                path = Path(module.__file__).resolve(strict=True)
                plugin_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                source_origin = path == source / '__init__.py'
                installed_byte_copy = path.is_relative_to(Path(config['runroot'])) and plugin_hash == config['source_sha256']
                valid = base in cls.__mro__ and (source_origin or installed_byte_copy)
                classes.append({'module': name, 'origin': str(path), 'native_MRO': valid,
                                'source_sha256': plugin_hash, 'origin_role': 'source' if source_origin else 'synthetic_installed_byte_copy'})
            if sys.modules.get('agent.memory_provider') is not base_module:
                receipt['violations'].append('native_base_module_replaced')
            return classes
        atexit.register(lambda: finalize_receipt(receipt, target, scan))
        # Retain the actual CI recorder, not native SDK/module stand-ins.
        sys._memory_wiki_ci_recorder = recorder
    except BaseException as exc:
        try:
            publish_failure(receipt, target, 'bootstrap_failed', exc)
        finally:
            print('CI native bootstrap refused: ' + type(exc).__name__, file=sys.stderr, flush=True)
            os._exit(86)


def is_loopback(host):
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def network_audit(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.sendto', 'socket.bind'):
        address = args[-1]
        if isinstance(address, tuple) and address and not is_loopback(address[0]):
            raise PermissionError('Synthetic CI permits loopback networking only')
    elif event == 'socket.getaddrinfo' and args[0] is not None and not is_loopback(args[0]):
        raise PermissionError('Synthetic CI denies external DNS')
