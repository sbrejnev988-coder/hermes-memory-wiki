"""Native fault rollback and positive handle ownership for suspended launch."""
from pathlib import Path
import os,json,sys,time,threading
from test_document_worker_admission import load_graph,offline_probe_source
import pytest

@pytest.mark.skipif(os.name!='nt',reason='Windows native handles')
@pytest.mark.parametrize('fault',['nojob','CreateJobObjectW','SetInformationJobObject','CreateProcess','AssignProcessToJobObject','IsProcessInJob','false_membership','ResumeThread'])
def test_failed_admission_runs_no_usercode_and_closes_all_handles(tmp_path,monkeypatch,fault):
    import _winapi,ctypes,gc
    from ctypes import wintypes as w
    from types import SimpleNamespace
    m=load_graph();monkeypatch.setattr(m,'__file__',str(tmp_path/'document_knowledge_graph.py'))
    worker=tmp_path/'document_worker.py'
    worker.write_text('from pathlib import Path\nimport os,sys,subprocess,time\nr=Path(__file__).resolve().parent\n(r/"usercode.marker").touch()\np=subprocess.Popen([sys.executable,"-c","import time;time.sleep(90)"])\n(r/"child.marker").write_text(str(p.pid))\ntime.sleep(90)\n')
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT','10');monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_OUTPUT_MB','8')
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    for name,args,ret in [('GetProcessHandleCount',[w.HANDLE,ctypes.POINTER(w.DWORD)],w.BOOL),('WaitForSingleObject',[w.HANDLE,w.DWORD],w.DWORD),('GetHandleInformation',[w.HANDLE,ctypes.POINTER(w.DWORD)],w.BOOL)]:
        fn=getattr(k,name);fn.argtypes=args;fn.restype=ret
    def count():
        value=w.DWORD();assert k.GetProcessHandleCount(_winapi.GetCurrentProcess(),ctypes.byref(value));return value.value
    if hasattr(m,'_launch_windows_worker'):
        job=m._assign_windows_worker_job(None);m._close_windows_worker_job(job)
    gc.collect();before=count();threads_before=set(threading.enumerate());created=[];pins=[];calls=[]
    real_create=_winapi.CreateProcess;real_dll=ctypes.WinDLL
    def create(*args):
        calls.append('CreateProcess')
        if fault=='CreateProcess':raise OSError(5,'synthetic creation denial')
        hp,ht,pid,tid=real_create(*args)
        pin=_winapi.DuplicateHandle(_winapi.GetCurrentProcess(),hp,_winapi.GetCurrentProcess(),0,False,_winapi.DUPLICATE_SAME_ACCESS)
        created.append({'hp':hp,'ht':ht,'pid':pid,'flags':args[5]});pins.append(pin)
        return hp,ht,pid,tid
    class FaultFunction:
        def __init__(self,name):self.name=name
        def __call__(self,*args):
            calls.append(self.name);ctypes.set_last_error(5)
            if fault=='false_membership':return 1
            return 0xFFFFFFFF if self.name=='ResumeThread' else 0
    class DLLProxy:
        def __init__(self,dll):self.dll=dll
        def __getattr__(self,name):
            if name==fault or (fault=='false_membership' and name=='IsProcessInJob'):return FaultFunction(name)
            return getattr(self.dll,name)
    with monkeypatch.context() as patch:
        patch.setattr(_winapi,'CreateProcess',create)
        patch.setattr(ctypes,'WinDLL',lambda *a,**kw:DLLProxy(real_dll(*a,**kw)))
        if fault=='nojob':patch.setattr(m,'_assign_windows_worker_job',lambda proc:None)
        began=time.monotonic()
        try:m._extract(tmp_path/'fixture.txt',{})
        except Exception as exc:exception=type(exc).__name__;message=str(exc)
        else:pytest.fail('failed admission accepted')
    waits=[k.WaitForSingleObject(h,1000) for h in pins]
    after=count()
    result={'fault':fault,'exception':exception,'message':message,'elapsed':time.monotonic()-began,'usercode':(tmp_path/'usercode.marker').exists(),'child':(tmp_path/'child.marker').exists(),'created':created,'calls':calls,'native_waits_before_outer_cleanup':waits,'handle_count_before':before,'handle_count_after_with_pins':after,'new_threads':[t.name for t in threading.enumerate() if t not in threads_before]}
    for h in pins:_winapi.CloseHandle(h)
    result['handle_count_after_pin_close']=count()
    (tmp_path/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    assert not result['usercode'] and not result['child'],result
    assert 'unable to establish Windows document worker sandbox' in message
    assert waits==[0]*len(pins)
    assert not result['new_threads']
    assert after==before+len(pins) and result['handle_count_after_pin_close']==before,result
    assert all(row['flags']&4 for row in created)

@pytest.mark.skipif(os.name!='nt',reason='Windows inherited handles')
def test_normal_worker_preserves_venv_quotes_and_closes_owned_process_handle(tmp_path,monkeypatch):
    import _winapi,ctypes
    from ctypes import wintypes as w
    m=load_graph();folder=tmp_path/'worker space Я';folder.mkdir()
    monkeypatch.setattr(m,'__file__',str(folder/'document_knowledge_graph.py'))
    monkeypatch.setenv('UNRELATED_SECRET_SENTINEL','synthetic-not-a-user-secret')
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    for name,args,ret in [('CreateEventW',[w.LPVOID,w.BOOL,w.BOOL,w.LPCWSTR],w.HANDLE),('WaitForSingleObject',[w.HANDLE,w.DWORD],w.DWORD)]:
        f=getattr(k,name);f.argtypes=args;f.restype=ret
    sentinel=k.CreateEventW(None,True,False,None);assert sentinel
    os.set_handle_inheritable(sentinel,True)
    code=offline_probe_source('''import json,sys,os,socket,ctypes
from ctypes import wintypes as w
request=json.loads(sys.stdin.buffer.read())
k=ctypes.WinDLL('kernel32',use_last_error=True);k.SetEvent.argtypes=[w.HANDLE];k.SetEvent.restype=w.BOOL
inherited=bool(k.SetEvent(SENTINEL))
try:socket.getaddrinfo('localhost',443)
except PermissionError:network_denied=True
else:network_denied=False
sys.stdout.buffer.write(json.dumps({'ok':True,'document':{'prefix':sys.prefix,'executable':sys.executable,'language':request['options']['ocr_language'],'unexpected_handle_inherited':inherited,'unexpected_env_inherited':'UNRELATED_SECRET_SENTINEL' in os.environ,'network_denied':network_denied}},ensure_ascii=False).encode('utf-8'))
'''.replace('SENTINEL)',str(sentinel)+')'))
    (folder/'document_worker.py').write_text(code,encoding='utf-8')
    procs=[];real=m._launch_windows_worker
    def launched(*a,**kw):
        proc,job=real(*a,**kw);procs.append(proc);return proc,job
    monkeypatch.setattr(m,'_launch_windows_worker',launched)
    try:
        result=m._extract(folder/'quoted fixture.txt',{'ocr_language':'Я✓'*1024})
        assert result=={'prefix':sys.prefix,'executable':sys.executable,'language':'Я✓'*1024,'unexpected_handle_inherited':False,'unexpected_env_inherited':False,'network_denied':True}
        assert k.WaitForSingleObject(sentinel,0)==258
        assert len(procs)==1 and procs[0].returncode==0
        assert procs[0].stdin.closed and procs[0].stdout.closed and procs[0].stderr.closed
        assert procs[0]._handle.closed,'normal _extract retained its owned native process handle'
    finally:_winapi.CloseHandle(sentinel)
