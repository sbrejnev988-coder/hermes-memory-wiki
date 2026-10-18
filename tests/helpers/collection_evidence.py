"""Passive collection diagnostics for the existing pytest entries (stdlib only).

A callback fsyncs a whole JSONL event before returning. A run is complete only
with a valid status.json AND the exclusively created complete/ directory AND no
refusal.json. Missing/partial files never mean an empty successful collection.
The declared fixture root must be quiescent and exclusively owned by the caller;
these no-follow checks are not an OS sandbox against concurrent path mutation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys

SCHEMA = 'memory-stack.collection-evidence/v1'
PREFIX = 'MEMORY_WIKI_COLLECTION_EVIDENCE '
JOURNAL_CAP = 2_000_000
EVENT_CAP = 256_000
PHASE_CAP = 1_000_000
STATUS_CAP = 8_192
TAIL_RESERVE = 1_024
UNAVAILABLE_TYPE = '<unavailable>'


class EvidenceRefusal(Exception):
    def __init__(self, code, **facts):
        self.code, self.facts = code, facts
        super().__init__(code)


def json_bytes(value, limit):
    # Pre-bound primitive input before the encoder can allocate a giant escaped
    # string. ASCII JSON is valid UTF-8 and round-trips even lone surrogates.
    pending, characters = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        if depth > 16:
            raise EvidenceRefusal('json_depth_cap', limit=16)
        if type(item) is str:
            characters += len(item)
            if characters > limit:
                raise EvidenceRefusal('json_character_cap', limit=limit,
                                      observed_characters=characters)
        elif type(item) in (dict, list, tuple):
            if len(item) > limit:
                raise EvidenceRefusal('json_cardinality_cap', limit=limit)
            if type(item) is dict:
                if any(type(key) is not str for key in item):
                    raise EvidenceRefusal('json_key_type')
                pending.extend((key, depth + 1) for key in item)
                pending.extend((val, depth + 1) for val in item.values())
            else:
                pending.extend((val, depth + 1) for val in item)
        elif item is not None and type(item) not in (bool, int):
            raise EvidenceRefusal('json_value_type')
    raw = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=True, allow_nan=False, separators=(',', ':'))
    for chunk in encoder.iterencode(value):
        encoded = chunk.encode('utf-8')
        if len(raw) + len(encoded) + 1 > limit:
            raise EvidenceRefusal('serialized_byte_cap', limit=limit,
                                  needed_at_least_bytes=len(raw) + len(encoded) + 1)
        raw.extend(encoded)
    raw.extend(b'\n')
    return bytes(raw)


def _type_name(value):
    # Exception/report metadata is user-controlled, including a metaclass's
    # attribute access. Never call str/repr of the value or concatenate a
    # foreign string subclass during failure reporting.
    try:
        cls = type(value)
        module, name = cls.__module__, cls.__qualname__
        if (type(module) is str and type(name) is str and module and name
                and len(module) + len(name) + 1 <= 200):
            return module + '.' + name
    except BaseException:
        pass
    return UNAVAILABLE_TYPE


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _root_path(value):
    raw = os.fspath(value)
    if (not isinstance(raw, str) or not raw or raw.startswith(('\\\\', '//'))
            or any(ord(c) < 32 or c in '<>"|?*' for c in raw)):
        raise EvidenceRefusal('unsafe_root_token')
    parts = re.split(r'[\\/]+', raw)
    if re.match(r'^[A-Za-z]:', raw):
        if len(raw) < 3 or raw[2] not in '\\/':
            raise EvidenceRefusal('drive_relative_root')
        parts = parts[1:]
    for part in filter(None, parts):
        stem = part.split('.', 1)[0].upper()
        if (part in ('.', '..') or ':' in part or part.endswith(('.', ' '))
                or stem in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'}
                or re.fullmatch(r'(?:COM|LPT)[1-9¹²³]', stem)):
            raise EvidenceRefusal('unsafe_root_token')
    path = Path(raw)
    if not path.is_absolute():
        raise EvidenceRefusal('absolute_root_required')
    return path


def _directory(path):
    info = os.lstat(path)
    if _linked(info) or not stat.S_ISDIR(info.st_mode):
        raise EvidenceRefusal('unsafe_directory')
    return info.st_dev, info.st_ino


class CollectionEvidence:
    def __init__(self, root, *, journal_cap=JOURNAL_CAP, event_cap=EVENT_CAP,
                 phase_cap=PHASE_CAP, stderr=None):
        self.stderr = sys.stderr if stderr is None else stderr
        self.journal_cap, self.event_cap, self.phase_cap = journal_cap, event_cap, phase_cap
        self.root = self.directory = self._journal = None
        self._directories, self._handles = {}, []
        self._journal_usable = False
        self._finished = False
        self.sequence = self.failed_reports = self.saved_reports = self.exception_details = 0
        self.bytes_confirmed_written = self.bytes_fsynced = 0
        self.refusals, self.refusal_count = [], 0
        self.session_finished, self.session_exitstatus = False, None
        self.returned_exitstatus = self.primary_type = None
        self.phase_evidence = 'not_requested'
        try:
            if (type(journal_cap) is not int or not 4_096 <= journal_cap <= JOURNAL_CAP
                    or type(event_cap) is not int or not 128 <= event_cap <= EVENT_CAP
                    or type(phase_cap) is not int or not 128 <= phase_cap <= PHASE_CAP):
                raise EvidenceRefusal('invalid_byte_caps')
            root = _root_path(root)
            # Missing ancestors above the declared root are never manufactured.
            for ancestor in reversed(root.parents):
                self._directories[ancestor] = _directory(ancestor)
            try:
                self._directories[root] = _directory(root)
            except FileNotFoundError:
                os.mkdir(root)
                self._directories[root] = _directory(root)
            self.root = root
            directory = root / 'collection-evidence'
            os.mkdir(directory)  # Exclusive namespace; never adopt old evidence.
            self._directories[directory] = _directory(directory)
            self.directory = directory
            self._journal = self._open(directory / 'errors.jsonl')
            self._journal_usable = True
            self._append({'event': 'started', 'schema': SCHEMA, 'complete': False,
                          'journal_cap': journal_cap, 'event_cap': event_cap,
                          'phase_cap': phase_cap}, terminal=True)
        except BaseException as error:
            self._callback_refusal('start', error)

    def _check_owned(self):
        for path, identity in self._directories.items():
            if _directory(path) != identity:
                raise EvidenceRefusal('directory_identity_changed')

    def _open(self, path):
        self._check_owned()
        # xb is O_EXCL|O_CREAT (and binary on Windows), including dangling links.
        stream = open(path, 'xb', buffering=0)
        self._handles.append(stream)
        try:
            actual, named = os.fstat(stream.fileno()), os.lstat(path)
            if (_linked(named) or not stat.S_ISREG(actual.st_mode)
                    or actual.st_nlink != 1 or named.st_nlink != 1
                    or (actual.st_dev, actual.st_ino) != (named.st_dev, named.st_ino)):
                raise EvidenceRefusal('unsafe_evidence_file')
            self._check_owned()
            return stream
        except BaseException:
            self._close(stream, 'open_cleanup_close')
            raise

    def _problem(self, stage, error):
        self.refusal_count += 1
        facts = error.facts if type(error) is EvidenceRefusal else {}
        row = {'stage': stage, 'sequence': self.sequence,
               'type': _type_name(error)[:200],
               'code': error.code if type(error) is EvidenceRefusal else 'reporting_exception',
               **facts}
        if len(self.refusals) < 8:
            self.refusals.append(row)
        return row

    def _close(self, stream, stage):
        try:
            stream.close()
        except BaseException as error:
            self._problem(stage, error)
        # A failed close is not presumed to have closed the actual resource.
        return stream.closed

    def _write(self, stream, raw, *, journal=False):
        offset = 0
        while offset < len(raw):
            count = stream.write(raw[offset:])
            if type(count) is not int or not 0 < count <= len(raw) - offset:
                raise EvidenceRefusal('write_no_progress_or_invalid_count')
            offset += count
            if journal:
                self.bytes_confirmed_written += count
        stream.flush()
        os.fsync(stream.fileno())
        if journal:
            self.bytes_fsynced = self.bytes_confirmed_written

    def _append(self, row, *, terminal=False):
        if not self._journal_usable or self._finished:
            raise EvidenceRefusal('journal_unavailable')
        self._check_owned()
        raw = json_bytes(row, TAIL_RESERVE if terminal else self.event_cap)
        limit = self.journal_cap if terminal else self.journal_cap - TAIL_RESERVE
        if self.bytes_confirmed_written + len(raw) > limit:
            raise EvidenceRefusal('journal_byte_cap', limit=limit,
                                  needed_bytes=self.bytes_confirmed_written + len(raw))
        try:
            self._write(self._journal, raw, journal=True)
        except BaseException:
            self._journal_usable = False  # Preserve partial bytes; never append a fake repair.
            raise
        return raw

    def _callback_refusal(self, stage, error):
        refusal = self._problem(stage, error)
        row = {'event': 'reporting_refused', 'refusal': refusal,
               'refusal_count': self.refusal_count, 'complete': False}
        # Reserve space for the FIRST refusal independently of accepted payloads.
        # A broken journal cannot be repaired by appending a plausible JSON tail.
        if self.refusal_count == 1 and self._journal_usable:
            try:
                self._append(row, terminal=True)
            except BaseException as secondary:
                self._problem('refusal_journal', secondary)
        self._echo(row)

    def _echo(self, value):
        try:
            raw = json_bytes(value, max(self.event_cap, STATUS_CAP))
            text = PREFIX + raw.decode('utf-8')
            count = self.stderr.write(text)
            if type(count) is not int or count != len(text):
                raise EvidenceRefusal('stderr_short_write')
            self.stderr.flush()
        except BaseException as error:
            self._problem('stderr', error)

    def pytest_collectreport(self, report):
        try:
            if not report.failed:
                return
            self.failed_reports += 1
            self.sequence += 1
            longrepr = report.longreprtext
            if type(report.nodeid) is not str or type(longrepr) is not str:
                raise EvidenceRefusal('collection_text_type')
            row = {'event': 'collection_error', 'sequence': self.sequence,
                   'nodeid': report.nodeid, 'when': 'collect', 'outcome': report.outcome,
                   'report_type': _type_name(report), 'longrepr_type': _type_name(report.longrepr),
                   'longrepr': longrepr}
            self._append(row)
            self.saved_reports += 1
            self._echo(row)  # Future ordinary CI also retains full bounded text in its log.
        except BaseException as error:
            self._callback_refusal('collectreport', error)

    def pytest_exception_interact(self, node, call, report):
        # CollectReport has no public excinfo field. The real pytest hook supplies
        # its CallInfo before collectreport; never parse/invent a type from text.
        try:
            if report.when != 'collect' or not report.failed:
                return
            self.sequence += 1
            error = call.excinfo.value
            row = {'event': 'collection_exception', 'sequence': self.sequence,
                   'nodeid': report.nodeid, 'exception_type': _type_name(error),
                   'message': str(error)}
            self._append(row)
            self.exception_details += 1
            self._echo(row)
        except BaseException as error:
            self._callback_refusal('exception_interact', error)

    def pytest_sessionfinish(self, session, exitstatus):
        try:
            self.session_finished = True
            self.session_exitstatus = self._exitstatus(exitstatus)
            self._append({'event': 'sessionfinish', 'exitstatus': self.session_exitstatus}, terminal=True)
        except BaseException as error:
            self._callback_refusal('sessionfinish', error)

    @staticmethod
    def _exitstatus(value):
        if not isinstance(value, int) or isinstance(value, bool):
            raise EvidenceRefusal('exitstatus_type')
        return int(value)

    def _artifact(self, path, value, cap):
        raw = json_bytes(value, cap)
        stream = None
        try:
            stream = self._open(path)
            self._write(stream, raw)
        finally:
            if stream is not None:
                self._close(stream, 'artifact_close')

    def write_phases(self, value):
        # Kept at the existing cold consumer path/schema; collisions now refuse.
        self.phase_evidence = 'refused'
        before = self.refusal_count
        try:
            if self.directory is None:
                raise EvidenceRefusal('evidence_namespace_unavailable')
            self._artifact(self.root / 'phases.json', value, self.phase_cap)
            if before == self.refusal_count:
                self.phase_evidence = 'complete'
        except BaseException as error:
            self._problem('phases', error)

    def status(self):
        cleanup = all(stream.closed for stream in self._handles)
        return {'schema': SCHEMA, 'complete': self.refusal_count == 0 and cleanup and self._finished,
                'failed_collect_reports': self.failed_reports, 'saved_collect_reports': self.saved_reports,
                'uncaptured_collect_reports': self.failed_reports - self.saved_reports,
                'exception_details': self.exception_details, 'session_finished': self.session_finished,
                'session_exitstatus': self.session_exitstatus, 'returned_exitstatus': self.returned_exitstatus,
                'primary_type': self.primary_type, 'phase_evidence': self.phase_evidence,
                'journal_bytes_confirmed_written': self.bytes_confirmed_written,
                'journal_bytes_fsynced': self.bytes_fsynced, 'cleanup_complete': cleanup,
                'refusal_count': self.refusal_count, 'refusals': list(self.refusals),
                'refusals_omitted': self.refusal_count - len(self.refusals)}

    def finish(self):
        if self._finished:
            return
        for stream in self._handles:
            if not stream.closed:
                self._close(stream, 'cleanup_close')
        self._journal_usable = False
        self._finished = True
        self._echo({'event': 'terminal', **self.status()})
        before = self.refusal_count
        try:
            if self.directory is None:
                raise EvidenceRefusal('evidence_namespace_unavailable')
            self._artifact(self.directory / 'status.json', self.status(), STATUS_CAP)
            if self.refusal_count == 0:
                self._check_owned()
                os.mkdir(self.directory / 'complete')  # Commit only AFTER successful fsync/close/echo.
        except BaseException as error:
            self._problem('terminal', error)
        if self.refusal_count > before:
            # Preserve the precise late failure independently of an earlier status
            # or its partial write. Never replace/delete someone else's evidence.
            self._echo({'event': 'reporting_refused', **self.status()})
            try:
                if self.directory is not None:
                    self._artifact(self.directory / 'refusal.json', self.status(), STATUS_CAP)
            except BaseException as error:
                self._problem('refusal_artifact', error)
                self._echo({'event': 'reporting_refused', **self.status()})

    def run(self, pytest_main, args, *, plugins=(), finalize=None):
        # The supplied callable is the actual pytest.main at both real entries.
        # Synthetic SOURCE callbacks exercise this boundary, not pytest dispatch.
        try:
            outcome = pytest_main(args, plugins=[*plugins, self])
            try:
                self.returned_exitstatus = self._exitstatus(outcome)
            except BaseException as error:
                self._problem('returned_exitstatus', error)
            return outcome
        except BaseException as primary:
            self.primary_type = _type_name(primary)
            if self.primary_type == UNAVAILABLE_TYPE:
                self._problem('primary_type', EvidenceRefusal('type_metadata_unavailable'))
            raise
        finally:
            if finalize is not None:
                try:
                    finalize()
                except BaseException as error:
                    self._problem('finalize', error)
            # Only diagnostics are caught. The original return/exception above is
            # untouched, including when reporting itself refuses during unwind.
            try:
                self.finish()
            except BaseException as error:
                self._problem('finish', error)
                self._echo({'event': 'reporting_refused', 'complete': False,
                            'refusal_count': self.refusal_count,
                            'refusals': list(self.refusals)})
