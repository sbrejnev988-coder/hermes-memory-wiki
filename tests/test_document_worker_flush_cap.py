"""A flushed cap+1 byte must be observed while its pipe stays open."""
import json
import os
import threading
import time
import pytest
from test_document_worker_exited_root import load_module,PinnedProcesses

@pytest.mark.parametrize('channel',['stdout','stderr'])
def test_flushed_cap_plus_one_is_not_hidden_by_buffered_read(tmp_path,monkeypatch,channel):
    m=load_module();monkeypatch.setattr(m,'__file__',str(tmp_path/'document_knowledge_graph.py'))
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT','10')
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_OUTPUT_MB','8')
    (tmp_path/'document_worker.py').write_text('import os,sys,json,time\nfrom pathlib import Path\nroot=Path(__file__).resolve().parent\n(root/"pids.json").write_text(json.dumps({"root_actual":os.getpid(),"root_launcher":os.getppid() if os.name=="nt" else os.getpid()}))\nwhile not (root/"pinned.gate").exists():time.sleep(.002)\nsys.stdin.buffer.read()\nsys.'+channel+'.buffer.write(b"x"*(8*1024*1024+1))\nsys.'+channel+'.buffer.flush()\n(root/"flushed.marker").touch()\ntime.sleep(90)\n',encoding='utf-8')
    pins=PinnedProcesses(tmp_path);before=set(threading.enumerate());started=time.monotonic();result={}
    try:
        try:m._extract(tmp_path/'fixture.txt',{})
        except Exception as exc:result.update(exception=type(exc).__name__,message=str(exc))
        result.update(elapsed=time.monotonic()-started,processes_before_outer_cleanup=pins.observe(),pin_errors=pins.errors,new_threads=[t.name for t in threading.enumerate() if t not in before])
        (tmp_path/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
        assert result.get('exception')=='RuntimeError' and 'output exceeds configured limit' in result.get('message','')
        assert result['elapsed']<2.2
        assert result['processes_before_outer_cleanup'] and all(p['stopped'] for p in result['processes_before_outer_cleanup'].values())
        assert not result['pin_errors'] and not result['new_threads']
    finally:pins.close()
