#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, json, os, sys
from pathlib import Path

os.environ["MEMORY_WIKI_RERANK_ENABLED"] = "0"
os.environ["MEMORY_WIKI_RERANK_API_KEY"] = "x"
os.environ["MEMORY_WIKI_RERANK_MIN_CANDIDATES"] = "5"
os.environ["MEMORY_WIKI_RERANK_TOP_K"] = "12"
plugin = Path(__file__).resolve().parents[1] / "__init__.py"
spec = importlib.util.spec_from_file_location("memory_wiki_rerank_test", plugin, submodule_search_locations=[str(plugin.parent)])
mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)

def rows():
    return [{"id":f"c_{i:02d}","claim":f"Durable memory claim {i} about SQLite Qdrant indexing","topic":"memory-wiki","type":"environment","status":"active","risk":"low","quarantined_at":0,"trust_class":"fact","updated_at":i,"score":float(100-i),"score_parts":{"exact":0.0,"bm25":0.2}} for i in range(12)]

class Response:
    def __init__(self,p): self.p=p
    def __enter__(self): return self
    def __exit__(self,*_): return False
    def read(self): return json.dumps(self.p).encode()

calls=[]
def fake(req,timeout=0):
    body=json.loads(req.data.decode()); calls.append(body); n=len(body["documents"])
    return Response({"results":[{"index":i,"relevance_score":(n-rank)/n} for rank,i in enumerate(reversed(range(n)))],"usage":{"search_units":1,"cost":0.0025}})

p=mod.MemoryWikiProvider(); base=rows(); mod.urllib.request.urlopen=fake
# Public default/explicit zero: no egress and original order.
out=p._rerank_rows("Find relevant memory indexing details",base,"semantic")
assert [r["id"] for r in out]==[r["id"] for r in base] and not calls
# Enable in-process for isolated tests.
mod.RERANK_ENABLED=True; mod._RERANK_CACHE.clear()
base=rows(); base[5]["risk"]="secret"
ranked=p._rerank_rows("Find relevant memory indexing details",base,"semantic")
assert ranked[0]["id"]!=base[0]["id"] and len(calls)==1
assert all("claim 5 " not in d for d in calls[0]["documents"])
cached=p._rerank_rows("Find relevant memory indexing details",base,"semantic")
assert [r["id"] for r in cached]==[r["id"] for r in ranked] and len(calls)==1
technical=rows(); technical[0]["score_parts"]={"exact":0.35,"bm25":1.0}
assert [r["id"] for r in p._rerank_rows("config.yaml",technical,"technical")]==[r["id"] for r in technical] and len(calls)==1
mod.urllib.request.urlopen=lambda *_a,**_k: (_ for _ in ()).throw(TimeoutError("synthetic timeout"))
failed=rows(); assert [r["id"] for r in p._rerank_rows("Different semantic query for timeout",failed,"semantic")]==[r["id"] for r in failed]
status=p._rerank_status(); assert status["successes"]==1 and status["cache_hits"]==1 and status["failures"]==1
print(json.dumps({"ok":True,"disabled_http_calls":0,"paid_mock_calls":len(calls),"status":status}))
