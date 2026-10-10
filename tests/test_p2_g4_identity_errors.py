"""Eight offline G4 cases against actual modules; no fake SDK/provider boot."""
from __future__ import annotations

import ast
import copy
import hashlib
import http.client
import importlib
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
from email.message import Message

SOURCE = Path(__file__).resolve().parents[1]
FIX = Path(os.environ['G4_FIXTURE'])
assert Path(os.environ['HERMES_HOME']) == FIX / 'app'
assert Path(os.environ['USERPROFILE']) == FIX / 'user'
sys.path.insert(0, str(SOURCE))
NETWORK_EVENTS = []
NETWORK_EXPECTED = False

class NetworkDenied(RuntimeError):
    pass

def _audit(event, args):
    if event.startswith('socket.'):
        NETWORK_EVENTS.append({'event': event, 'expected': NETWORK_EXPECTED})
        raise NetworkDenied('offline_network_denied')
    if event in {'subprocess.Popen', '_winapi.CreateProcess', 'os.system'}:
        raise RuntimeError('offline_process_denied')

sys.addaudithook(_audit)
collapse = importlib.import_module('collapse')
drive = importlib.import_module('google_drive_source_adapter')
assert Path(collapse.__file__).resolve() == SOURCE / 'collapse.py'
assert Path(drive.__file__).resolve() == SOURCE / 'google_drive_source_adapter.py'
assert 'agent.memory_provider' not in sys.modules

TEXT = 'Маршрутизация сохраняет текущие данные источника безопасно'
FILE_A = 'file_abcdefgh123456'
FILE_B = 'file_ijklmnop123456'
URL = 'https://www.googleapis.com/drive/v3/files/'

class Body(io.BytesIO):
    def __init__(self, raw, read_failure=False, close_failure=False):
        super().__init__(raw)
        self.reads = []
        self.closes = 0
        self.read_failure = read_failure
        self.close_failure = close_failure
    def read(self, size=-1):
        self.reads.append(size)
        if self.read_failure:
            raise OSError('synthetic-private-provider-detail')
        return super().read(size)
    def close(self):
        self.closes += 1
        super().close()
        if self.close_failure and self.closes == 1:
            raise OSError('synthetic-private-close-detail')

class ResponseSocket:
    def __init__(self, body):
        raw = b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body
        self.stream = Body(raw)
    def makefile(self, mode):
        return self.stream

def response(raw):
    sock = ResponseSocket(raw)
    result = http.client.HTTPResponse(sock)
    result.begin()
    return result, sock.stream

def google_error(reason=None, status=None):
    error = {'code': 403, 'message': 'DO_NOT_PRINT https://private.invalid/?token=authored-secret'}
    if reason is not None:
        error['errors'] = [{'domain': 'global', 'reason': reason, 'message': 'authored-secret'}]
    if status is not None:
        error['status'] = status
    return json.dumps({'error': error}).encode()

def http_error(code=403, raw=None, retry=None, **kwargs):
    body = Body(google_error('insufficientFilePermissions') if raw is None else raw, **kwargs)
    headers = Message()
    if retry is not None:
        headers['Retry-After'] = retry
    error = urllib.error.HTTPError(URL + FILE_A, code, 'synthetic-private-reason', headers, body)
    return error, body

def metadata(file_id):
    return json.dumps({'id': file_id, 'name': 'authored-note.txt', 'mimeType': 'text/plain',
                       'size': '0', 'version': '123', 'trashed': False,
                       'capabilities': {'canDownload': True}}).encode()

def record(local_id=42, **values):
    return {'id': local_id, 'content': TEXT, 'salience': 0.5, 'confidence': 0.5, **values}

class G4Tests(unittest.TestCase):
    def refused(self, error, expected, provider=None):
        owner = provider or SimpleNamespace()
        attempts = []
        def transport(request, timeout):
            attempts.append(request.full_url)
            raise error
        with patch.object(drive, '_open', transport):
            with self.assertRaises(ValueError) as cm:
                drive._request(owner, URL + FILE_A, 'authored-fixture-token', 64)
        self.assertEqual(str(cm.exception), expected)
        self.assertTrue(cm.exception.__suppress_context__)
        self.assertIsNone(cm.exception.__cause__)
        self.assertNotIn('authored-secret', str(cm.exception))
        self.assertEqual(len(attempts), 1)
        return owner, cm.exception

    def test_01_namespaced_records_and_bounded_keys(self):
        first = record(storage_instance_id='store-a', source_uri='urn:source:a')
        second = record(storage_instance_id='store-b', source_uri='urn:source:a')
        third = record(storage_instance_id='store-a', source_uri='urn:source:b')
        result = collapse.memory_context_collapse(TEXT, [first, second, third], budget=10)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(any(item is original for item in result) for original in [first, second, third]))
        updated = {**first, 'content': 'different version of this same record'}
        self.assertEqual(collapse.memory_context_collapse(TEXT, [first, updated], budget=10), [first])
        nested = record(payload={'source': {'database_instance_id': 'store-a', 'source_uri': 'urn:source:a'}})
        self.assertEqual(collapse._stable_key(first), collapse._stable_key(nested))
        other_domain = record(storage_instance_id='store-a', source_id='urn:source:a')
        self.assertNotEqual(collapse._stable_key(first), collapse._stable_key(other_domain))
        huge = 'urn:private:?token=' + '\u0416' * 100000
        a = record(storage_instance_id=huge, source_uri=huge+'a')
        b = record(storage_instance_id=huge, source_uri=huge+'b')
        self.assertEqual(len(collapse._stable_key(a)), 71)
        self.assertNotEqual(collapse._stable_key(a), collapse._stable_key(b))
        self.assertNotIn('token', collapse._stable_key(a))
        self.assertNotEqual(collapse._stable_key(record(origin='urn:origin:a')),
                            collapse._stable_key(record(origin='urn:origin:b')))

    def test_02_root_copy_no_votes_and_independent_positive(self):
        original = record(storage_instance_id='store-a', source_uri='urn:root:one')
        rival = record(900, salience=0.56)
        copied = record(43, storage_instance_id='store-b', source_uri='urn:copy:two',
                        origin={'source_uri': 'urn:root:one'}, salience=0.1)
        snapshot = copy.deepcopy([original, rival, copied])
        result = collapse.memory_context_collapse(TEXT, [original, rival], [copied], budget=1)
        self.assertIs(result[0], rival)
        transformed = record(44, source_uri='urn:copy:three', salience=0.1,
                             transformation={'source': {'source_uri': 'urn:root:one'}})
        current = record(45, source_uri='urn:copy:four', salience=0.1,
                         current_root_evidence={'source_uri': 'urn:root:one', 'note': 'getNamespace is DATA'})
        result = collapse.memory_context_collapse(TEXT, [original, rival], [copied, transformed], [current], budget=1)
        self.assertIs(result[0], rival)
        self.assertEqual([original, rival, copied], snapshot)
        independent = record(46, source_uri='urn:independent:root', salience=0.1)
        self.assertIs(collapse.memory_context_collapse(TEXT, [original, rival], [independent], budget=1)[0], original)
        # Same fact delivered in many messages is one root, not extra votes.
        echoes = [record(100+i, root_evidence_id='same-root', source_uri='urn:copy:'+str(i), salience=0.1)
                  for i in range(3)]
        rooted = record(99, root_evidence_id='same-root', source_uri='urn:origin')
        self.assertIs(collapse.memory_context_collapse(TEXT, [rooted, rival], echoes[:2], echoes[2:], budget=1)[0], rival)
        unknown = record(55, source_uri='urn:looks-independent', origin={'note': 'instructions are only data'}, salience=0.1)
        self.assertIs(collapse.memory_context_collapse(TEXT, [original, rival], [unknown], budget=1)[0], rival)

    def test_03_legacy_and_real_fts_acl_hidden_count_negative(self):
        first = record()
        duplicate = record()
        different = record(content='Другой независимый факт без namespace')
        self.assertEqual(len(collapse.memory_context_collapse(TEXT, [first], [duplicate], budget=10)), 1)
        self.assertEqual(len(collapse.memory_context_collapse(TEXT, [first], [different], budget=10)), 2)
        self.assertEqual(collapse.memory_context_collapse(TEXT, [{'content': TEXT}], [{'content': TEXT}], budget=10), [{'content': TEXT}])
        # Execute unchanged actual product predicate, not a invented ACL implementation.
        tree = ast.parse((SOURCE/'__init__.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MemoryWikiProvider')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_claim_visibility_sql')
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE/'__init__.py'), 'exec'), namespace)
        identity = SimpleNamespace(bot_id='owner', session_id='current', project_scope='project-a',
                                   _chat_hash=lambda sid: 'hash-'+sid)
        predicate, params = namespace['_claim_visibility_sql'](identity)
        db = sqlite3.connect(':memory:')
        try:
            db.execute('CREATE VIRTUAL TABLE claims USING fts5(id UNINDEXED,content,storage_instance_id UNINDEXED,source_uri UNINDEXED,visibility_scope UNINDEXED,origin_bot_id UNINDEXED,origin_chat_hash UNINDEXED,origin_session_id UNINDEXED,project_id UNINDEXED)')
            def insert(storage, visibility='global', bot='owner', sid='current'):
                db.execute('INSERT INTO claims VALUES(?,?,?,?,?,?,?,?,?)', (42,TEXT,storage,'urn:'+storage,visibility,bot,'hash-'+sid,sid,'project-a'))
            def fetch():
                rows = db.execute('SELECT id,content,storage_instance_id,source_uri FROM claims WHERE claims MATCH ? AND '+predicate, ['маршрутизация',*params]).fetchall()
                hits = [dict(zip(('id','content','storage_instance_id','source_uri'),row)) for row in rows]
                return collapse.memory_context_collapse(TEXT, hits, budget=10)
            insert('a'); insert('b')
            before = fetch()
            insert('FOREIGN', 'private', 'other-owner', 'other-session')
            after = fetch()
            self.assertEqual(after, before)
            self.assertEqual(len(after), 2)
            self.assertNotIn('FOREIGN', json.dumps(after))
            self.assertNotIn('count', json.dumps(after))
            with self.assertRaises(ValueError):
                namespace['_claim_visibility_sql'](identity, prefix='untrusted.sql')
        finally:
            db.close()

    def test_04_permission_403_then_B_metadata_still_attempts(self):
        owner = SimpleNamespace()
        error, body = http_error(retry='99999')
        good, stream = response(metadata(FILE_B))
        attempts = []
        def transport(request, timeout):
            attempts.append(request.full_url)
            if len(attempts) == 1:
                raise error
            return good
        with patch.object(drive, '_open', transport):
            with self.assertRaisesRegex(ValueError, '^drive_permission_denied$'):
                drive._metadata(owner, FILE_A, 'authored-fixture-token')
            self.assertEqual(drive._metadata(owner, FILE_B, 'authored-fixture-token')['id'], FILE_B)
        self.assertEqual(len(attempts), 2)
        self.assertFalse(hasattr(owner, '_drive_rate_limit_until'))
        self.assertEqual(body.reads, [8193])
        self.assertEqual(body.closes, 1)
        self.assertTrue(body.closed and stream.closed)

    def test_05_auth_and_revoked_grant_fail_closed_foreign_scope(self):
        for status, raw in [(403, google_error('authError')), (403, google_error(status='UNAUTHENTICATED')),
                            (403, b'{"error":"invalid_grant"}'), (401, b'authored-secret')]:
            error, body = http_error(status, raw)
            owner, failure = self.refused(error, 'drive_auth_failed')
            self.assertFalse(hasattr(owner, '_drive_rate_limit_until'))
            self.assertTrue(body.closed)
            self.assertEqual(body.closes, 1)
        foreign = SimpleNamespace(home=FIX/'foreign')
        with patch.object(drive, '_open', side_effect=AssertionError('credential escape')):
            with self.assertRaisesRegex(ValueError, '^drive_access_token_required$'):
                drive.sync_file(foreign, {'file_id':FILE_A})

    def test_06_rate_quota_403_429_circuit_retry_bounds(self):
        controls = [(403,'rateLimitExceeded','120',120), (403,'userRateLimitExceeded','0',1),
                    (403,'sharingRateLimitExceeded','999999',86400), (403,'dailyLimitExceeded','bad',60),
                    (403,'storageQuotaExceeded','-5',1), (429,None,None,60)]
        for status, reason, retry, delay in controls:
            error, body = http_error(status, google_error(reason), retry)
            owner = SimpleNamespace()
            attempts = []
            def transport(request, timeout):
                attempts.append(request.full_url)
                raise error
            with patch.object(drive, '_open', transport), patch.object(drive.time, 'time', return_value=1000.0):
                with self.assertRaisesRegex(ValueError, '^drive_rate_limited:retry_after_seconds='+str(delay)+'$'):
                    drive._request(owner, URL+FILE_A, 'authored-fixture-token',64)
                self.assertEqual(owner._drive_rate_limit_until,1000+delay)
                with self.assertRaisesRegex(ValueError,'^drive_rate_limited:'):
                    drive._request(owner, URL+FILE_B, 'authored-fixture-token',64)
            self.assertEqual(len(attempts),1)
            self.assertTrue(body.closed)
            self.assertEqual(body.closes,1)
            self.assertEqual(body.reads, [] if status==429 else [8193])

    def test_07_unknown_malformed_oversize_read_close_bounds(self):
        raws = [b'{bad', b'x'*9000, b'['*2500+b'0'+b']'*2500,
                b'{"error":{"code":200,"errors":[{"reason":"rateLimitExceeded"}]}}',
                b'{"error":{"message":"rateLimitExceeded authored-secret"}}',
                json.dumps({'error':{'errors':[{'reason':'rateLimitExceeded'}]*17}}).encode(),
                google_error('UNRECOGNIZED_REASON')]
        for raw in raws:
            error, body = http_error(raw=raw)
            owner, failure = self.refused(error,'drive_http_error:403')
            self.assertFalse(hasattr(owner,'_drive_rate_limit_until'))
            self.assertEqual(body.reads,[8193])
            self.assertTrue(body.closed)
            self.assertEqual(body.closes,1)
        for flags in [{'read_failure':True}, {'close_failure':True}]:
            error, body = http_error(raw=b'{bad',**flags)
            owner, failure = self.refused(error,'drive_http_error:403')
            self.assertTrue(body.closed)
            self.assertEqual(body.closes,1)
            if flags.get('close_failure'):
                self.assertEqual(failure.__notes__,['drive_http_error_body_close_failed'])
        for status, expected in [(404,'drive_source_unavailable'),(500,'drive_http_error:500')]:
            error, body = http_error(status,b'authored-secret')
            self.refused(error,expected)
            self.assertEqual(body.reads,[])
            self.assertTrue(body.closed)
        # A genuine urllib body backed by native malformed chunked HTTP framing.
        # HTTPException is not OSError; its partial provider body must not escape.
        wire = Body(b'HTTP/1.1 403 Forbidden\r\nTransfer-Encoding: chunked\r\n\r\n10\r\nabc')
        framed = http.client.HTTPResponse(SimpleNamespace(makefile=lambda mode: wire))
        framed.begin()
        error = urllib.error.HTTPError(URL+FILE_A,403,'private framing detail',Message(),framed)
        self.refused(error,'drive_http_error:403')
        self.assertTrue(wire.closed)
        self.assertEqual(wire.closes,1)

    def test_08_direct_boundary_preservation_and_network_denial(self):
        global NETWORK_EXPECTED
        # The cumulative G3/RI-R01 payload intentionally changes sync_file and
        # the provider. The original whole-file BEFORE/trust oracle is retained
        # in g4_original_boundary_gold.txt, not applied to incompatible bytes.
        historical = (SOURCE/'tests/fixtures/g4_original_boundary_gold.txt').read_text(encoding='utf-8')
        self.assertIn("self.assertEqual((baseline/'__init__.py').read_bytes(), (SOURCE/'__init__.py').read_bytes())", historical)
        self.assertIn('9d9b3aac80bea5f1aba6ac289a3647b5b3a1fc9bf9d60e0fd920390b5544638b', historical)
        protected = ast.parse((SOURCE/'tests/fixtures/g4_metadata_scope.txt').read_bytes()).body[0]
        actual = next(n for n in ast.parse((SOURCE/'google_drive_source_adapter.py').read_bytes()).body
                      if isinstance(n, ast.FunctionDef) and n.name == '_metadata')
        self.assertEqual(ast.dump(protected, include_attributes=False), ast.dump(actual, include_attributes=False))
        # Raw current binding, not a claim of native provider initialization.
        self.assertEqual(hashlib.sha256((SOURCE/'__init__.py').read_bytes()).hexdigest(),
                         '6edf7c9bf9b8059f68495f221564a53a67801692fa5b8a4bb825ee2a820113bd')
        NETWORK_EXPECTED = True
        try:
            with self.assertRaises(NetworkDenied):
                socket.socket()
        finally:
            NETWORK_EXPECTED = False
        self.assertEqual(NETWORK_EVENTS,[{'event':'socket.__new__','expected':True}])
        self.assertNotIn('agent.memory_provider',sys.modules)

if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(G4Tests))
    unexpected = [v for v in NETWORK_EVENTS if not v['expected']]
    print(json.dumps({'boundary':'DIRECT_PRODUCT_OFFLINE_NOT_NATIVE_PROVIDER', 'cases':result.testsRun,
                      'failures':len(result.failures),'errors':len(result.errors),
                      'unexpected_network_events':len(unexpected),'network_denial_control':len(NETWORK_EVENTS),
                      'native_SDK_provider_loaded':False,'sourceAccepted':False,'installedloadedlive':False}))
    raise SystemExit(0 if result.wasSuccessful() and result.testsRun==8 and not unexpected else 1)
