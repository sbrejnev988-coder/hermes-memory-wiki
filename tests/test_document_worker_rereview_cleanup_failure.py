"""Independent Windows cleanup partial-failure on a real contained worker."""
from pathlib import Path
import json,os,threading,time
import pytest
from test_document_worker_admission import load_graph

@pytest.mark.skipif(os.name!='nt',reason='Windows native Job cleanup')
def test_query_failure_still_reaps_root_and_joins_pipe_owners(tmp_path,monkeypatch):
    # Own the timeout instead of relying on defaults in an outer test harness.
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT','10')
    import ctypes,_winapi
    from ctypes import wintypes as w
    m=load_graph();monkeypatch.setattr(m,'__file__',str(tmp_path/'document_knowledge_graph.py'))
    (tmp_path/'document_worker.py').write_text('import os,time\nos.close(0)\ntime.sleep(90)\n')
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    for name,args,ret in [('WaitForSingleObject',[w.HANDLE,w.DWORD],w.DWORD),('CloseHandle',[w.HANDLE],w.BOOL)]:
        f=getattr(k,name);f.argtypes=args;f.restype=ret
    real_launch=m._launch_windows_worker;real_dll=ctypes.WinDLL
    procs=[];pins=[];calls=[]
    def launch(*args,**kwargs):
        proc,job=real_launch(*args,**kwargs)
        procs.append(proc)
        pins.append(_winapi.DuplicateHandle(_winapi.GetCurrentProcess(),proc._handle,_winapi.GetCurrentProcess(),0,False,_winapi.DUPLICATE_SAME_ACCESS))
        return proc,job
    monkeypatch.setattr(m,'_launch_windows_worker',launch)
    class QueryFault:
        def __call__(self,*args):
            calls.append('QueryInformationJobObject');ctypes.set_last_error(5);return 0
    class DLLProxy:
        def __init__(self,dll):self.dll=dll
        def __getattr__(self,name):
            if name=='QueryInformationJobObject':return QueryFault()
            return getattr(self.dll,name)
    # Admission calls are native and unaffected; only the cleanup query fails.
    monkeypatch.setattr(ctypes,'WinDLL',lambda *a,**kw:DLLProxy(real_dll(*a,**kw)))
    before=set(threading.enumerate());began=time.monotonic();result={}
    try:
        try:m._extract(tmp_path/'fixture.txt',{'ocr_language':'x'*(256*1024)})
        except Exception as exc:
            result.update(exception=type(exc).__name__,message=str(exc),context_type=type(exc.__context__).__name__ if exc.__context__ else None,cause_type=type(exc.__cause__).__name__ if exc.__cause__ else None)
        else:result['unexpected_success']=True
        result.update(elapsed=time.monotonic()-began,fault_calls=calls,processes=[{'pid':p.pid,'returncode':p.returncode,'owned_handle_closed':p._handle.closed,'stdin_closed':p.stdin.closed,'stdout_closed':p.stdout.closed,'stderr_closed':p.stderr.closed} for p in procs],native_waits_before_outer_cleanup=[k.WaitForSingleObject(h,0) for h in pins],new_threads_before_safety_cleanup=[t.name for t in threading.enumerate() if t not in before])
    finally:
        # Record before waiting; this reviewer wait must not count as production cleanup.
        result['reviewer_cleanup_waits']=[k.WaitForSingleObject(h,3000) for h in pins]
        for t in list(threading.enumerate()):
            if t not in before:t.join(timeout=1)
        result['new_threads_after_reviewer_cleanup']=[t.name for t in threading.enumerate() if t not in before]
        for h in pins:k.CloseHandle(h)
        (tmp_path/'independent-result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
    assert result['fault_calls'],result
    assert result['exception']=='RuntimeError' and result['message']=='document worker exceeded timeout (10s)',result
    assert result['cause_type']=='PermissionError',result
    assert result['native_waits_before_outer_cleanup']==[0],result
    assert 10<=result['elapsed']<11.5,result
    assert result['processes'] and all(p['returncode'] is not None for p in result['processes']),result
    assert not result['new_threads_before_safety_cleanup'],result
    assert all(p['stdin_closed'] and p['stdout_closed'] and p['stderr_closed'] for p in result['processes']),result
