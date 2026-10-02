"""Windows admission invariant: no executable instruction before verified containment."""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]

def offline_probe_source(code):
    """Fixture-owned offline supervision; a Windows Job is not a network sandbox."""
    return (
        "import sys\n"
        "def _deny_fixture_network(event,args):\n"
        "    if event in ('socket.getaddrinfo','socket.connect','socket.connect_ex','socket.sendto'):\n"
        "        raise PermissionError('fixture network denied')\n"
        "sys.addaudithook(_deny_fixture_network)\n"
    )+code

def load_graph():
    sys.path.insert(0,str(ROOT))
    source=Path(os.environ.get('WORKER_TEST_SOURCE',str(ROOT/'document_knowledge_graph.py')))
    assert source.resolve().is_relative_to(ROOT)
    spec=importlib.util.spec_from_file_location('admission_regression_graph',source)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def wait_json(path,budget=3):
    end=time.monotonic()+budget
    while True:
        try:return json.loads(path.read_text())
        except (FileNotFoundError,json.JSONDecodeError):
            assert time.monotonic()<end,path
            time.sleep(.002)

def membership_probe(case,mode):
    """Called in a fresh interpreter, with no ctypes import before worker launch."""
    m=load_graph()
    if mode=='warm-forced':
        import ctypes
        from ctypes import wintypes
    cold={n:n in sys.modules for n in ('ctypes','ctypes.wintypes','_ctypes')}
    if mode!='warm-forced':assert not any(cold.values()),cold
    worker=case/'document_worker.py'
    worker.write_text(offline_probe_source('''import json,os,subprocess,sys,time,socket
from pathlib import Path
root=Path(__file__).resolve().parent
try:socket.getaddrinfo('localhost',443)
except PermissionError:network_denied=True
else:raise AssertionError('child network allowed')
(root/'actual.json').write_text(json.dumps({'pid':os.getpid(),'ppid':os.getppid(),'prefix':sys.prefix,'executable':sys.executable,'network_denied':network_denied}))
child_code="import os,json,time; from pathlib import Path; p=Path("+repr(str(root/'child.json'))+"); p.write_text(json.dumps({'pid':os.getpid(),'ppid':os.getppid()})); time.sleep(90)"
child=subprocess.Popen([sys.executable,'-c',child_code])
(root/'child-launcher.json').write_text(json.dumps({'pid':child.pid}))
time.sleep(90)
'''),encoding='utf-8')
    delayed=[]
    if hasattr(m,'_launch_windows_worker'):
        admit=m._admit_windows_worker
        def controlled(proc,job):
            if mode in ('forced','warm-forced'):
                time.sleep(.15)
                assert not (case/'actual.json').exists(),'usercode ran before assignment'
                delayed.append({'no_usercode_before_assignment':True,'launcher_returncode':proc.poll()})
            return admit(proc,job)
        m._admit_windows_worker=controlled
        proc,job=m._launch_windows_worker([sys.executable,str(worker)],**m._worker_launch_kwargs(worker))
    else:
        # Exact prior _extract launch/assignment sequence, not a simulated response.
        proc=subprocess.Popen([sys.executable,str(worker)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**m._worker_launch_kwargs(worker))
        if mode in ('forced','warm-forced'):wait_json(case/'child.json')
        job=m._assign_windows_worker_job(proc)
    actual=wait_json(case/'actual.json');child=wait_json(case/'child.json');child_launcher=wait_json(case/'child-launcher.json')
    import ctypes
    from ctypes import wintypes as w
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    for name,args,ret in [('OpenProcess',[w.DWORD,w.BOOL,w.DWORD],w.HANDLE),('WaitForSingleObject',[w.HANDLE,w.DWORD],w.DWORD),('CloseHandle',[w.HANDLE],w.BOOL),('IsProcessInJob',[w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)],w.BOOL),('QueryInformationJobObject',[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD,w.LPVOID],w.BOOL)]:
        fn=getattr(k,name);fn.argtypes=args;fn.restype=ret
    pids={'launcher':proc.pid,'actual_python':actual['pid'],'descendant_launcher':child_launcher['pid'],'descendant_actual':child['pid']}
    handles={name:k.OpenProcess(0x100000|0x1000,False,pid) for name,pid in pids.items()};assert all(handles.values())
    def observe(h):
        member=w.BOOL();assert k.IsProcessInJob(h,job[0],ctypes.byref(member))
        return {'member':bool(member.value),'wait':k.WaitForSingleObject(h,0)}
    before={n:observe(h) for n,h in handles.items()}
    limitbuf=ctypes.create_string_buffer(144);assert k.QueryInformationJobObject(job[0],9,limitbuf,len(limitbuf),None)
    # Verify named limits through the graph's public config and native offsets
    # independently checked against installed x64 JOBOBJECT layout.
    limits={'flags':int.from_bytes(limitbuf.raw[16:20],'little'),'process_time_100ns':int.from_bytes(limitbuf.raw[0:8],'little'),'process_memory_bytes':int.from_bytes(limitbuf.raw[112:120],'little')}
    threads=[];errors=[]
    def reader(stream):
        try:
            while stream.read1(65536):pass
        except Exception as exc:errors.append(type(exc).__name__)
        finally:stream.close()
    def writer():
        try:proc.stdin.write(b'x'*(512*1024));proc.stdin.close()
        except OSError:pass
    for s in (proc.stdout,proc.stderr):
        t=threading.Thread(target=reader,args=(s,),daemon=True);t.start();threads.append(t)
    t=threading.Thread(target=writer,daemon=True);t.start();threads.append(t)
    time.sleep(.02)
    m._close_windows_worker_job(job)
    proc.wait(timeout=1)
    for t in threads:t.join(.2)
    # Job termination is asynchronous: prove each pinned native handle signals
    # within one shared budget BEFORE the outer safety Job is touched.
    until=time.monotonic()+1.0
    after={n:k.WaitForSingleObject(h,max(0,int((until-time.monotonic())*1000))) for n,h in handles.items()}
    result={'mode':mode,'cold_before_launch':cold,'pids':pids,'before_inner_cleanup':before,'after_inner_cleanup_waits':after,'threads_alive':[t.name for t in threads if t.is_alive()],'reader_errors':errors,'controlled_scheduling':delayed,'native_limits':limits,'expected_limits':m._windows_worker_limit_config(),'actual_identity':actual,'parent_identity':{'prefix':sys.prefix,'executable':sys.executable},'root_returncode':proc.returncode,'contract_passed':all(r['member'] for r in before.values()) and all(v==0 for v in after.values()) and not any(t.is_alive() for t in threads)}
    expected=m._windows_worker_limit_config()
    assert limits=={'flags':expected['limit_flags'],'process_time_100ns':expected['process_time_100ns'],'process_memory_bytes':expected['process_memory_bytes']}
    assert actual['prefix']==sys.prefix and actual['executable']==sys.executable and actual['network_denied']
    for h in handles.values():k.CloseHandle(h)
    if getattr(proc,'_handle',None):proc._handle.Close()
    return result


def test_windows_cold_and_controlled_admission(tmp_path):
    if os.name!='nt':
        import pytest
        pytest.skip('Windows suspended Job admission')
    # Fresh cold children are each admitted into an OUTER Job before execution.
    import _winapi
    import ctypes
    from ctypes import wintypes as w
    m=load_graph();k=ctypes.WinDLL('kernel32',use_last_error=True)
    for name,args,ret in [('ResumeThread',[w.HANDLE],w.DWORD),('CloseHandle',[w.HANDLE],w.BOOL),('TerminateJobObject',[w.HANDLE,w.UINT],w.BOOL),('WaitForSingleObject',[w.HANDLE,w.DWORD],w.DWORD)]:
        f=getattr(k,name);f.argtypes=args;f.restype=ret
    for mode in ('cold','warm-forced'):
        case=tmp_path/mode;case.mkdir();hp=ht=None;job=None
        try:
            command=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'--probe',str(case),mode]
            hp,ht,pid,tid=_winapi.CreateProcess(sys.executable,subprocess.list2cmdline(command),None,None,False,4,dict(os.environ),str(ROOT),subprocess.STARTUPINFO())
            from types import SimpleNamespace
            job=m._assign_windows_worker_job(SimpleNamespace(_handle=hp))
            assert job
            assert k.ResumeThread(ht)==1;k.CloseHandle(ht);ht=None
            result=wait_json(case/'report.json',8)
            assert result['contract_passed'],result
        finally:
            if job:
                assert k.TerminateJobObject(job[0],99)
                m._close_windows_worker_job(job)
            if ht:k.CloseHandle(ht)
            if hp:
                assert k.WaitForSingleObject(hp,3000)==0
                k.CloseHandle(hp)

if __name__=='__main__':
    assert sys.argv[1]=='--probe'
    case=Path(sys.argv[2]);result=membership_probe(case,sys.argv[3])
    (case/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    time.sleep(90)
