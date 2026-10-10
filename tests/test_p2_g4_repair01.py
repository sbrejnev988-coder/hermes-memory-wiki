"""Two G4 repair counterexamples; stdlib transport / AST public boundary only."""
from __future__ import annotations
import ast
import hashlib
import http.client
import importlib
import io
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import xml.etree.ElementTree as ET
from email.message import Message

SOURCE = Path(__file__).resolve().parents[1]
FIX = Path(os.environ['G4_REPAIR_FIXTURE']).resolve()
assert Path(os.environ['HERMES_HOME']).resolve() == FIX/'app'
assert Path(os.environ['USERPROFILE']).resolve() == FIX/'user'
assert not any(any(x in k.upper() for x in ('TOKEN','SECRET','PASSWORD','API_KEY','CREDENTIAL')) for k in os.environ)
VIOLATIONS = []
READ_ROOTS = (SOURCE, FIX, Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve())
WRITES = {FIX/'junit.xml', FIX/'receipt.json'}

def audit(event, args):
    denied = event.startswith('socket.') or event in {'subprocess.Popen','_winapi.CreateProcess','os.system','sqlite3.connect'}
    if event == 'open':
        target, mode, flags = args
        if not isinstance(target, (str, bytes, os.PathLike)):
            denied = True
        else:
            q = Path(os.fsdecode(target)).resolve()
            writing = any(c in (mode or '') for c in 'wax+') or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            denied = (q not in WRITES) if writing else not any(q.is_relative_to(r) for r in READ_ROOTS)
    if denied:
        VIOLATIONS.append(event)
        raise RuntimeError('isolated_boundary_refused')

sys.addaudithook(audit)
sys.path.insert(0, str(SOURCE))
NATIVE_METHODS = tuple(getattr(http.client.HTTPResponse, n) for n in ('read','_get_chunk_left','_read_next_chunk_size','_read_and_discard_trailer'))
drive = importlib.import_module('google_drive_source_adapter')
assert Path(drive.__file__).resolve() == SOURCE/'google_drive_source_adapter.py'
assert 'agent.memory_provider' not in sys.modules
PUBLIC_RAW = (SOURCE/'__init__.py').read_bytes()
PUBLIC_TREE = ast.parse(PUBLIC_RAW)
SELECTED = []
for name in ['_PUBLIC_VALIDATION_ERRORS','_safe_exception_label','_public_tool_error']:
    nodes = [n for n in PUBLIC_TREE.body if (isinstance(n, ast.FunctionDef) and n.name==name) or (isinstance(n, ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))]
    assert len(nodes) == 1
    SELECTED.append(nodes[0])
PUBLIC = {'re':re,'urllib':urllib,'__builtins__':__builtins__}
exec(compile(ast.Module(body=SELECTED,type_ignores=[]),str(SOURCE/'__init__.py'),'exec'),PUBLIC)
public_error = PUBLIC['_public_tool_error']
BOUND = {getattr(n,'name',n.targets[0].id if isinstance(n,ast.Assign) else ''):{'line':n.lineno,'end_line':n.end_lineno,'AST_SHA256':hashlib.sha256(ast.dump(n,include_attributes=True).encode()).hexdigest()} for n in SELECTED}
OBSERVATIONS = []
URL='https://www.googleapis.com/drive/v3/files/'
FILE_A='file_abcdefgh123456'
FILE_B='file_ijklmnop123456'
PRIVATE='local-fixture-private-marker'

class Body(io.BytesIO):
    def __init__(self, raw, fail_close=False):
        super().__init__(raw)
        self.read_sizes=[]
        self.closes=0
        self.fail_close=fail_close
    def read(self, size=-1):
        self.read_sizes.append(size)
        if size < 0:
            raise AssertionError('unbounded_fixture_read')
        return super().read(size)
    def close(self):
        self.closes+=1
        super().close()
        if self.fail_close:
            raise OSError(PRIVATE)

class MemorySocket:
    def __init__(self, raw, fail_close=False):
        self.stream=Body(raw,fail_close)
    def makefile(self, mode):
        assert mode=='rb'
        return self.stream

def google(reason, code=403):
    return json.dumps({'error':{'code':code,'message':PRIVATE,'errors':[{'reason':reason,'message':PRIVATE}]}}).encode()

def native(code, body, framing='cl', declared=None, malformed_chunk=False, fail_close=False):
    if framing=='cl':
        headers=b'Content-Length: '+str(len(body) if declared is None else declared).encode()+b'\r\n'
        wire=body
    elif framing=='chunk':
        headers=b'Transfer-Encoding: chunked\r\n'
        wire=format(len(body),'x').encode()+b'\r\n'+body+b'\r\n0\r\n'+(b'' if malformed_chunk else b'\r\n')
    else:
        headers=b'Connection: close\r\n'
        wire=body
    sock=MemorySocket(b'HTTP/1.1 '+str(code).encode()+b' Fixture\r\n'+headers+b'\r\n'+wire,fail_close)
    response=http.client.HTTPResponse(sock)
    response.begin()
    return response,sock.stream

def error(code, raw, **kw):
    response,body=native(code,raw,**kw)
    headers=response.headers
    headers['Retry-After']='7'
    return urllib.error.HTTPError(URL+FILE_A,code,PRIVATE,headers,response),response,body

class RepairTests(unittest.TestCase):
    def refusal(self, err, expected, owner=None):
        owner=owner or SimpleNamespace()
        def transport(*args,**kwargs):
            raise err
        with patch.object(drive,'_open',transport):
            with self.assertRaises(ValueError) as cm:
                drive._request(owner,URL+FILE_A,'fixture-only',4096)
        self.assertTrue(str(cm.exception)==expected,'wrong_typed_refusal')
        self.assertTrue(cm.exception.__suppress_context__ and cm.exception.__cause__ is None,'private_context_not_suppressed')
        self.assertTrue(PRIVATE not in str(cm.exception),'private_exception_leak')
        return owner,cm.exception
    def closed(self,response,body):
        self.assertTrue(response.closed and body.closed,'native_owned_response_not_closed')
        self.assertEqual(body.closes,1)
        self.assertTrue(all(isinstance(n,int) and n>=0 for n in body.read_sizes),'unbounded_read')

    def test_01_parsable_prefix_is_not_complete_quota_evidence(self):
        raw=google('rateLimitExceeded')
        err,response,body=error(403,raw,declared=len(raw)+17)
        owner,_=self.refusal(err,'drive_http_error:403')
        self.assertEqual(getattr(owner,'_drive_rate_limit_until',0),0)
        self.assertEqual(response.length,17)
        self.closed(response,body)
        OBSERVATIONS.append('short_CL_403_unknown_no_cooldown')
        response,body=native(200,b'{"ok":true}',declared=40)
        with patch.object(drive,'_open',lambda *a,**k:response):
            with self.assertRaises(ValueError) as cm:
                drive._request(SimpleNamespace(),URL+FILE_A,'fixture-only',4096)
        self.assertTrue(str(cm.exception)=='drive_http_error','success_prefix_admitted')
        self.closed(response,body)
        OBSERVATIONS.append('short_CL_200_refused')
        err,response,body=error(403,raw,framing='chunk',malformed_chunk=True)
        owner,_=self.refusal(err,'drive_http_error:403')
        self.assertEqual(getattr(owner,'_drive_rate_limit_until',0),0)
        self.closed(response,body)
        OBSERVATIONS.append('chunk_trailer_EOF_unknown_no_cooldown')
        # Small positive controls, not a Cartesian rerun of old8.
        for reason,framing in [('rateLimitExceeded','cl'),('storageQuotaExceeded','chunk')]:
            with self.subTest(control=framing):
                err,response,body=error(403,google(reason),framing=framing)
                owner,_=self.refusal(err,'drive_rate_limited:retry_after_seconds=7')
                self.assertTrue(owner._drive_rate_limit_until>drive.time.time(),'valid_rate_lost')
                self.closed(response,body)
        err,response,body=error(403,google('invalidCredentials'),framing='eof')
        owner,_=self.refusal(err,'drive_auth_failed')
        self.assertEqual(getattr(owner,'_drive_rate_limit_until',0),0)
        self.closed(response,body)
        err,response,body=error(429,b'incomplete',declared=120)
        owner,_=self.refusal(err,'drive_rate_limited:retry_after_seconds=7')
        self.assertTrue(owner._drive_rate_limit_until>drive.time.time(),'status_429_lost')
        self.assertEqual(body.read_sizes,[])
        self.closed(response,body)
        raw_body=Body(google('dailyLimitExceeded'))
        hdr=Message();hdr['Retry-After']='99999999999999999999'
        err=urllib.error.HTTPError(URL+FILE_A,403,PRIVATE,hdr,raw_body)
        owner,_=self.refusal(err,'drive_rate_limited:retry_after_seconds=86400')
        self.assertTrue(raw_body.closed and raw_body.closes==1)
        OBSERVATIONS.append('complete_CL_chunk_EOF_BytesIO_rate_auth_429_preserved')

    def test_02_exact_permission_public_code_without_exception_passthrough(self):
        err,response,body=error(403,google('insufficientFilePermissions'))
        owner,exc=self.refusal(err,'drive_permission_denied')
        self.closed(response,body)
        self.assertEqual(getattr(owner,'_drive_rate_limit_until',0),0)
        self.assertEqual(public_error(exc),'drive_permission_denied')
        # A permission failure for A does not trip B's _metadata request.
        meta=json.dumps({'id':FILE_B,'mimeType':'text/plain','size':'0','version':'2','trashed':False,'capabilities':{'canDownload':True}}).encode()
        response,body=native(200,meta)
        with patch.object(drive,'_open',lambda *a,**k:response):
            actual=drive._metadata(owner,FILE_B,'fixture-only')
        self.assertTrue(actual['id']==FILE_B,'permission_A_blocked_B')
        self.closed(response,body)
        for text in [PRIVATE,'drive_new_code','drive_permission_denied:'+PRIVATE,'drive_permission_denied '+PRIVATE,'drive_rate_limited:retry_after_seconds=0','drive_rate_limited:retry_after_seconds=86401','drive_http_error:600']:
            self.assertEqual(public_error(ValueError(text)),'ValueError')
        self.assertEqual(public_error(RuntimeError('drive_permission_denied')),'RuntimeError')
        self.assertEqual(public_error(ValueError('drive_auth_failed')),'drive_auth_failed')
        self.assertEqual(public_error(ValueError('drive_rate_limited:retry_after_seconds=7')),'drive_rate_limited:retry_after_seconds=7')
        self.assertEqual(public_error(ValueError('drive_http_error:403')),'drive_http_error:403')
        no_body=urllib.error.HTTPError('https://local.invalid/'+PRIVATE,403,PRIVATE,Message(),None)
        try:
            self.assertEqual(public_error(no_body),'HTTPError(status=403)')
        finally:
            no_body.close()
        err,response,body=error(403,google('insufficientFilePermissions'))
        owned_close=err.close
        def cleanup_refusal():
            owned_close()
            raise OSError(PRIVATE)
        # Inject only this fixture's final owner-close failure, not an earlier
        # native framing-read failure or a class/global SDK monkeypatch.
        with patch.object(err,'close',side_effect=cleanup_refusal) as closer:
            _,exc=self.refusal(err,'drive_permission_denied')
            self.assertEqual(closer.call_count,1)
        self.assertEqual(public_error(exc),'drive_permission_denied')
        self.assertEqual(exc.__notes__,['drive_http_error_body_close_failed'])
        self.closed(response,body)
        OBSERVATIONS.append('ASTUNIT_exact_code_permission_isolation_privacy_cleanup')

if __name__=='__main__':
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(RepairTests)
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    assert NATIVE_METHODS == tuple(getattr(http.client.HTTPResponse, n) for n in ('read','_get_chunk_left','_read_next_chunk_size','_read_and_discard_trailer'))
    captured=stream.getvalue()
    sys.stderr.write(captured)
    report={'cases':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'violations':VIOLATIONS,'observations':OBSERVATIONS,'transport_boundary':'genuine_HTTPResponse_HTTPError_in_memory','public_boundary':'ASTUNIT_NOT_NATIVE','native_provider_cases':0,'sourceAccepted':False,'nativeAccepted':False,'public_source_SHA256':hashlib.sha256(PUBLIC_RAW).hexdigest(),'public_bindings':BOUND,'source_origin':str(SOURCE)}
    xml=ET.Element('testsuite',name='G4_repair01',tests=str(result.testsRun),failures=str(len(result.failures)),errors=str(len(result.errors)))
    failures={t.id():trace for t,trace in result.failures}
    errors={t.id():trace for t,trace in result.errors}
    for name in unittest.defaultTestLoader.getTestCaseNames(RepairTests):
        el=ET.SubElement(xml,'testcase',classname='RepairTests',name=name)
        key=RepairTests(name).id()
        if key in failures: ET.SubElement(el,'failure',type='AssertionError').text=failures[key]
        if key in errors: ET.SubElement(el,'error',type='Exception').text=errors[key]
    ET.ElementTree(xml).write(FIX/'junit.xml',encoding='utf-8',xml_declaration=True)
    with (FIX/'receipt.json').open('w',encoding='utf-8') as fp:
        json.dump(report,fp,ensure_ascii=True,indent=2)
    print(json.dumps({'cases':report['cases'],'failures':report['failures'],'errors':report['errors'],'violations':len(VIOLATIONS),'public_boundary':report['public_boundary'],'native_provider_cases':0}))
    raise SystemExit(0 if result.wasSuccessful() and result.testsRun==2 and not VIOLATIONS else 1)
