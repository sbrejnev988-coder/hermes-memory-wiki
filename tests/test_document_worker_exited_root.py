"""Real exited-root pipe ownership; caller observes cleanup before any safety teardown."""
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import time

import pytest

ROOT=Path(__file__).resolve().parents[1]

def load_module():
    sys.path.insert(0,str(ROOT))
    source=Path(os.environ.get('WORKER_TEST_SOURCE',str(ROOT/'document_knowledge_graph.py')))
    assert source.resolve().is_relative_to(ROOT)
    spec=importlib.util.spec_from_file_location('exited_root_regression',source)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

class PinnedProcesses:
    def __init__(self,folder):
        self.folder=folder;self.handles={};self.pids={};self.errors=[]
        self.stop=threading.Event()
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes as w
            self.k=ctypes.WinDLL('kernel32',use_last_error=True)
            for name,args,ret in [('OpenProcess',[w.DWORD,w.BOOL,w.DWORD],w.HANDLE),('WaitForSingleObject',[w.HANDLE,w.DWORD],w.DWORD),('CloseHandle',[w.HANDLE],w.BOOL)]:
                f=getattr(self.k,name);f.argtypes=args;f.restype=ret
        self.thread=threading.Thread(target=self.run,name='regression-pin-monitor',daemon=True)
        self.thread.start()
    def run(self):
        try:
            while not self.stop.is_set():
                p=self.folder/'pids.json'
                if p.exists():
                    try: pids=json.loads(p.read_text())
                    except json.JSONDecodeError: continue
                    for name,pid in pids.items():
                        if name not in self.handles:
                            h=self.k.OpenProcess(0x100000|0x1000,False,pid) if os.name=='nt' else os.pidfd_open(pid)
                            assert h,('unable to pin',name,pid)
                            self.handles[name]=h;self.pids[name]=pid
                    if len(self.handles)==len(pids): (self.folder/'pinned.gate').touch()
                time.sleep(.002)
        except BaseException as exc:self.errors.append(repr(exc))
    def observe(self):
        if os.name=='nt':return {n:{'pid':self.pids[n],'wait':self.k.WaitForSingleObject(h,0),'stopped':self.k.WaitForSingleObject(h,0)==0} for n,h in self.handles.items()}
        return {n:{'pid':self.pids[n],'pidfd_signalled':bool(select.select([h],[],[],0)[0]),'stopped':bool(select.select([h],[],[],0)[0])} for n,h in self.handles.items()}
    def close(self):
        self.stop.set();self.thread.join(1)
        for h in self.handles.values():
            if os.name=='nt':self.k.CloseHandle(h)
            else:os.close(h)

@pytest.mark.parametrize('blocked',[False,True],ids=['small','blocked'])
def test_exited_root_terminates_inherited_pipe_owners(tmp_path,monkeypatch,blocked):
    m=load_module();monkeypatch.setattr(m,'__file__',str(tmp_path/'document_knowledge_graph.py'))
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT','10')
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_OUTPUT_MB','8')
    code='''import json,os,sys,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parent
'''
    if not blocked: code+='sys.stdin.buffer.read()\n'
    code+='''child_code="import os,json,time; from pathlib import Path; p=Path("+repr(str(tmp_path/'child.json'))+"); p.write_text(json.dumps({'pid':os.getpid()})); time.sleep(90)"
child=subprocess.Popen([sys.executable,'-c',child_code])
while not (root/'child.json').exists(): time.sleep(.002)
pids={'root_actual':os.getpid(),'root_launcher':os.getppid() if os.name=='nt' else os.getpid(),'descendant_launcher':child.pid,'descendant_actual':json.loads((root/'child.json').read_text())['pid']}
(root/'pids.json').write_text(json.dumps(pids))
while not (root/'pinned.gate').exists(): time.sleep(.002)
sys.stdout.buffer.write(b'{"ok":true,"document":{"status":"ok"}}')
sys.stdout.buffer.flush()
'''
    # Embed only this synthetic fixture's scratch path.
    code=code.replace("str(tmp_path/'child.json')",repr(str(tmp_path/'child.json')))
    (tmp_path/'document_worker.py').write_text(code,encoding='utf-8')
    pins=PinnedProcesses(tmp_path);before=set(threading.enumerate());started=time.monotonic();result={}
    try:
        try:result['document']=m._extract(tmp_path/'fixture.txt',{'ocr_language':'Я✓'*(128*1024)} if blocked else {})
        except Exception as exc:result.update(exception=type(exc).__name__,message=str(exc))
        result.update(elapsed=time.monotonic()-started,processes_before_outer_cleanup=pins.observe(),pin_errors=pins.errors,new_threads=[t.name for t in threading.enumerate() if t not in before])
        (tmp_path/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
        assert not result['pin_errors']
        assert result['elapsed']<2.2
        assert result['processes_before_outer_cleanup']
        assert all(row['stopped'] for row in result['processes_before_outer_cleanup'].values())
        assert result['new_threads']==[]
        if blocked:assert result.get('exception')=='BrokenPipeError',result
        else:assert result.get('document')=={'status':'ok'},result
    finally:pins.close()
