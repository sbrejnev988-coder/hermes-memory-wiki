"""Passive teardown evidence for only this lane's new regression tests."""
from __future__ import annotations

import __main__
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time

import pytest
import memory_wiki

_HOME = Path(os.environ['HERMES_HOME']).resolve()
_FIXTURES = _HOME.parent / 'fixtures'
_EVENTS = _HOME / 'lifecycle-events.jsonl'
_PROVIDER_SOURCE = os.path.normcase(str(Path(memory_wiki.__file__).resolve()))
_OWNER_SOURCE = os.path.normcase(str(Path(__file__).with_name('provider_lifecycle.py').resolve()))
_SHUTIL_SOURCE = os.path.normcase(str(Path(shutil.__file__).resolve()))


def _metadata(provider):
    if provider is None:
        return {'present': False}
    connection = vars(provider).get('_conn')
    return {'present': True, 'provider_id': id(provider),
            'module': type(provider).__module__,
            'connection_present': connection is not None,
            'connection_id': id(connection) if connection is not None else None}


def _emit(event, node, **values):
    with _EVENTS.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'event': event, 'node': node,
                                 'monotonic': time.monotonic(), **values}) + '\n')


def _inventory(target):
    entries = []
    for parent in [target, *target.parents]:
        if parent.exists():
            info = parent.lstat()
            entries.append({'path': str(parent), 'parent_chain': True,
                            'reparse': bool(getattr(info, 'st_file_attributes', 0) & 0x400),
                            'symlink': parent.is_symlink()})
    pending = [target]
    while pending:
        path = pending.pop()
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        reparse = bool(getattr(info, 'st_file_attributes', 0) & 0x400)
        link = path.is_symlink()
        entries.append({'path': str(path), 'bytes': info.st_size,
                        'reparse': reparse, 'symlink': link})
        if stat.S_ISDIR(info.st_mode) and not reparse and not link:
            pending.extend(Path(entry.path) for entry in os.scandir(path))
    return entries


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    previous = sys.gettrace()
    assert previous is None, 'Passive observer refuses another trace'
    node = item.nodeid

    def trace(frame, event, arg):
        filename = os.path.normcase(frame.f_code.co_filename)
        name = frame.f_code.co_name
        if filename not in {_OWNER_SOURCE, _PROVIDER_SOURCE, _SHUTIL_SOURCE}:
            return None
        if event == 'return' and filename == _OWNER_SOURCE and name == 'release':
            _emit('fixture_release_return', node,
                  provider=_metadata(frame.f_locals.get('provider')))
        if filename == _PROVIDER_SOURCE and name == 'initialize':
            if event == 'return':
                _emit('initialize_return', node,
                      provider=_metadata(frame.f_locals.get('self')))
            elif event == 'exception':
                _emit('initialize_exception', node, error_type=type(arg[1]).__name__)
        if filename == _SHUTIL_SOURCE:
            if name == 'rmtree' and event in {'call', 'return'}:
                raw = frame.f_locals.get('path')
                if isinstance(raw, (str, bytes, os.PathLike)):
                    path = Path(os.fsdecode(raw)).absolute()
                    if path.is_relative_to(_FIXTURES):
                        values = {'target': str(path), 'exists': path.exists(),
                                  'provider': _metadata(getattr(__main__, '_memory_wiki_instance', None))}
                        if event == 'call':
                            values['pre_removal_inventory'] = _inventory(path)
                        _emit('rmtree_' + event, node, **values)
            elif event == 'exception' and isinstance(arg[1], OSError):
                error = arg[1]
                if error.filename and Path(os.fsdecode(error.filename)).absolute().is_relative_to(_FIXTURES):
                    _emit('removal_error', node, errno=error.errno,
                          winerror=getattr(error, 'winerror', None))
        return trace

    sys.settrace(trace)
    try:
        yield
    finally:
        sys.settrace(previous)
        _emit('item_protocol_finished', node)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    _emit('sessionfinish', '', exit_code=int(exitstatus),
          provider=_metadata(getattr(__main__, '_memory_wiki_instance', None)))
