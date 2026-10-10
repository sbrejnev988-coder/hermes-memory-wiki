"""P2 G3: eight bounded native/offline cases, authored data only.
PDF parser is real and in-process; transport/OCR worker containment is not asserted.
Conditional responses and private extraction callbacks are authored boundary fixtures.
"""
from pathlib import Path
import importlib, importlib.util, json, os, sys, unittest, urllib.error
from unittest import mock
spec = importlib.util.spec_from_file_location("g3_g1_helpers", Path(__file__).with_name("test_document_state_g1_native.py"))
g1 = importlib.util.module_from_spec(spec);sys.modules[spec.name]=g1;spec.loader.exec_module(g1)
CASE_NAMES = ["test_effective_chunk_axes_and_cache", "test_pdf_options_and_isolation", "test_native_config_owner_precedence", "test_scheduler_executor_gate", "test_drive_version_hit", "test_github_304_response", "test_github_304_http_error", "test_p1_aba_and_retired_link"]

class ConditionalResponse:
    status=304
    headers={}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,*args):raise AssertionError("conditional hit must not read a content body")

class G3Tests(g1.DocumentStateG1):
    def setUp(self):
        super().setUp()
        self.c=importlib.import_module(self.m.__name__+'.source_connectors')
        self.gh=importlib.import_module(self.m.__name__+'.github_source_adapter')
        self.dr=importlib.import_module(self.m.__name__+'.google_drive_source_adapter')
        self.bj=importlib.import_module(self.m.__name__+'.background_jobs')
        self.c.install_source_connector_schema(self.db)

    def call_ingest(self, **args):
        return self.d.ingest_document(self.p, {'path':str(self.path),'embed':False,**args})

    def test_effective_chunk_axes_and_cache(self):
        self.path.write_text(g1.distinct_authored('CHUNKAXIS',4),encoding='utf-8')
        with mock.patch.object(self.d,'_extract',side_effect=lambda p,a:self.e.extract_document(p,a['_effective_extraction_options'])) as extract:
            a=self.call_ingest();self.assertEqual(extract.call_count,1)
            with mock.patch.dict(os.environ,{'MEMORY_WIKI_DOCUMENT_CHUNK_MAX_UNITS':'2'}):
                b=self.call_ingest();self.assertNotEqual(a['revision_id'],b['revision_id']);self.assertEqual(extract.call_count,1)
                self.assertLess(b['chunks'],a['chunks'])
            restored=self.call_ingest();self.assertEqual(a['revision_id'],restored['revision_id']);self.assertEqual(extract.call_count,1)
            with mock.patch.dict(os.environ,{'MEMORY_WIKI_EMBED_MODEL':'other-public-model','MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT':'999'}):
                current=self.call_ingest(ocr=True,ocr_language='fra');self.assertEqual(current['status'],'unchanged');self.assertEqual(extract.call_count,1)
            opts=self.d._worker_options({})
            self.assertEqual(self.e.extraction_options_fingerprint(self.path,opts),self.e.extraction_options_fingerprint(self.path,{**opts,'max_pages':-5}))
            for key in self.d._materialization_options():
                self.assertIn(key,{'chunk_chars','chunk_min_chars','chunk_max_units','embed_claim_chars','unit_chars'})
    def test_pdf_options_and_isolation(self):
        self.path=self.path.with_suffix('.pdf')
        self.path.write_bytes(b'%PDF-1.4\n% authored option-dispatch boundary fixture\n%%EOF\n')
        # Optional PyMuPDF is absent in selected PM. Exercise real extract_document
        # dispatch and capture bounded PDF options; no fabricated native parser/OCR claim.
        def pdf_boundary(path,max_units,max_pages,ocr,language,minimum):
            return self.e.ExtractedDocument('pdf-boundary','application/pdf','Authored PDF',
                [self.e.Unit('page','page:1','Authored PDF native-dispatch text '+language,ordinal=1)])
        with mock.patch.dict(os.environ,{'MEMORY_WIKI_DOCUMENT_OCR_MIN_NATIVE_CHARS':'0'}), mock.patch.object(self.e,'_extract_pdf_pymupdf',side_effect=pdf_boundary) as parser, mock.patch.object(self.d,'_extract',side_effect=lambda p,a:self.e.extract_document(p,a['_effective_extraction_options'])) as extract:
            a=self.call_ingest(ocr=True,ocr_language='eng');b=self.call_ingest(ocr=True,ocr_language='rus')
            self.assertNotEqual(a['revision_id'],b['revision_id']);self.assertEqual(parser.call_args.args[4],'rus');self.assertEqual(extract.call_count,2)
            with mock.patch.dict(os.environ,{'MEMORY_WIKI_EMBED_MODEL':'different','MEMORY_WIKI_DOCUMENT_CHUNK_CHARS':'900'}):
                c=self.call_ingest(ocr=True,ocr_language='rus');self.assertNotEqual(b['revision_id'],c['revision_id']);self.assertEqual(extract.call_count,2)
            with mock.patch.dict(os.environ,{'MEMORY_WIKI_DOCUMENT_MAX_PAGES':'1'}):
                self.call_ingest(ocr=True,ocr_language='rus');self.assertEqual(extract.call_count,3)
            own=self.e.extraction_options_fingerprint(self.path,self.d._worker_options({'ocr':True,'ocr_language':'eng'}))
            self.assertNotEqual(own,self.e.extraction_options_fingerprint(self.path,self.d._worker_options({'ocr':True,'ocr_language':'rus'})))

    def save_graph(self, enabled=True, model='gpt-6-luna', provider='openai-codex'):
        cfg={'model':{'default':'unchanged-main'},'plugins':{'entries':{'memory-wiki':{'settings':{'graph_extraction':{'enabled':enabled,'provider':provider,'model':model,'timeout':7,'reasoning_effort':'low'}}}}}}
        (self.home/'config.yaml').write_text(json.dumps(cfg),encoding='utf-8')
        return cfg

    def test_native_config_owner_precedence(self):
        from hermes_cli.plugins import PluginContext, PluginManifest
        from hermes_constants import set_hermes_home_override,reset_hermes_home_override
        (self.home/'.env').write_text('MEMORY_WIKI_GRAPH_AUTO_EXTRACT=1\nMEMORY_WIKI_GRAPH_EXTRACT_ENABLED=0\n',encoding='utf-8')
        cfg=self.save_graph();ctx=PluginContext(PluginManifest(name='memory-wiki',version='0.0.0',description='authored fixture'),None)
        self.assertEqual(ctx.get_config('graph_extraction'),cfg['plugins']['entries']['memory-wiki']['settings']['graph_extraction'])
        with self.assertRaises(ValueError):ctx.get_config('model')
        token=self.m._QDRANT_PROFILE_SCOPE.set({'MEMORY_WIKI_GRAPH_AUTO_EXTRACT':'1','MEMORY_WIKI_GRAPH_EXTRACT_ENABLED':'0'})
        try:
            self.assertEqual(self.p.relevant_graph_extraction_settings(),(True,True))
            self.save_graph(False);self.assertEqual(self.p.relevant_graph_extraction_settings(),(True,False))
            self.save_graph(True,'owner/model','openrouter');settings=self.p._graph_extraction_settings();self.assertEqual((settings.provider,settings.model),('openrouter','owner/model'))
            self.assertEqual(json.loads((self.home/'config.yaml').read_text())['model'],cfg['model'])
        finally:self.m._QDRANT_PROFILE_SCOPE.reset(token)
        foreign=self.home/'foreign';foreign.mkdir();(foreign/'config.yaml').write_text(json.dumps({'plugins':{'entries':{'memory-wiki':{'settings':{'graph_extraction':{'enabled':False}}}}}}),encoding='utf-8')
        old=self.p.home;self.p.home=foreign
        try:self.assertEqual(self.p.relevant_graph_extraction_settings(),(False,False))
        finally:self.p.home=old

    def test_scheduler_executor_gate(self):
        self.save_graph(False)
        (self.home/'.env').write_text('MEMORY_WIKI_GRAPH_AUTO_EXTRACT=1\nMEMORY_WIKI_GRAPH_EXTRACT_ENABLED=1\n',encoding='utf-8')
        token=self.m._QDRANT_PROFILE_SCOPE.set({'MEMORY_WIKI_GRAPH_AUTO_EXTRACT':'1','MEMORY_WIKI_GRAPH_EXTRACT_ENABLED':'1'})
        try:
            self.path.write_text(g1.distinct_authored('GRAPHGATE',1),encoding='utf-8')
            doc=self.call_ingest();self.embed(doc['source_id'])
            cid=self.db.execute("SELECT id FROM claims WHERE status='active' LIMIT 1").fetchone()[0]
            self.assertTrue(cid.startswith('c_'))
            self.bj.enqueue_claim(self.p,cid)
            job=self.db.execute("SELECT * FROM memory_jobs WHERE job_type='enrich_claim_graph'").fetchone()
            with mock.patch.object(type(self.p),'_graph_extract_claim',side_effect=AssertionError('disabled graph reached transport')):
                self.assertEqual(self.bj._run_job(self.p,self.m,job),'')
                stats=self.p._auto_graph_enrich_extracted_claims([cid]);self.assertEqual(stats['attempted'],0)
            # Producer gate is the same call on an actual worker copy; lease/event consumers unchanged.
            source=self.db.execute('SELECT * FROM claims WHERE id=?',(cid,)).fetchone();worker=self.bj._worker_provider(self.p,source)
            self.assertEqual(worker.relevant_graph_extraction_settings(),self.p.relevant_graph_extraction_settings())
            self.save_graph(True);self.assertEqual(worker.relevant_graph_extraction_settings(),(True,True))
        finally:self.m._QDRANT_PROFILE_SCOPE.reset(token)

    def seed_connector(self, branch):
        if branch=='drive':
            args={'file_id':'fixture_file_123','embed':False};uri='https://drive.google.com/file/d/fixture_file_123/view';rev='9';kind='google_drive'
        else:
            args={'owner':'fixture-owner','repo':'fixture-repo','path':'manual.txt','ref':'main','embed':False};uri=self.gh._source_uri('fixture-owner','fixture-repo','manual.txt','main');rev='a'*40;kind='github_public'
        result=self.c.upsert_record(self.p,self.c.SourceRecord(uri=uri,revision=rev,text=g1.distinct_authored('CONNECTOR'+branch,1),title='manual.txt',source_type=kind,embed=False))
        if branch!='drive':self.db.execute('UPDATE external_sources SET etag=? WHERE source_key=?',('"fixture-etag"',result['source_key']));self.db.commit()
        return args,result

    def conditional(self,branch):
        args,seed=self.seed_connector('drive' if branch=='drive' else 'github')
        with mock.patch.object(self.d,'_extract',side_effect=AssertionError('conditional hit reran extraction')):
            if branch=='drive':
                meta={'version':'9','mimeType':self.dr._DOC_MIME,'name':'manual.txt'}
                contexts=[mock.patch.object(self.dr,'_profile_credential',return_value='authored-unused-token'),mock.patch.object(self.dr,'_metadata',return_value=meta),mock.patch.object(self.dr,'_request',side_effect=AssertionError('conditional hit downloaded'))];sync=self.dr.sync_file
            else:
                opening=(mock.patch.object(self.gh,'_open',side_effect=urllib.error.HTTPError('https://api.github.com/fixture',304,'not modified',{},None)) if branch=='error' else mock.patch.object(self.gh,'_open',return_value=ConditionalResponse()))
                contexts=[mock.patch.object(self.gh,'_profile_credential',return_value=''),opening];sync=self.gh.sync_file
            from contextlib import ExitStack
            with ExitStack() as stack:
                for c in contexts:stack.enter_context(c)
                false=sync(self.p,args);self.assertNotIn('embedding',false)
                self.assertEqual(self.db.execute('SELECT COUNT(*) FROM claims WHERE topic=?',('document_index',)).fetchone()[0],0)
                true=sync(self.p,{**args,'embed':True});self.assertIn('embedding',true);self.assertGreater(true['embedding']['created'],0)
                current=sync(self.p,{**args,'embed':True});self.assertEqual(current['embedding']['created'],0)
                ids=[r[0] for r in self.db.execute("SELECT embedding_claim_id FROM document_chunks WHERE source_id=? AND embedding_claim_id<>''",(seed['source_id'],))];self.assertTrue(ids)
                self.db.execute("UPDATE claims SET status='archived' WHERE id=?",(ids[0],));self.db.commit()
                retired=sync(self.p,{**args,'embed':True});self.assertEqual(retired['embedding']['created'],0)
                self.db.execute('DELETE FROM claims WHERE id=?',(ids[0],));self.db.commit()
                erased=sync(self.p,{**args,'embed':True});self.assertEqual(erased['embedding']['created'],0)
                self.assertIsNone(self.db.execute('SELECT id FROM claims WHERE id=?',(ids[0],)).fetchone())
                staged=self.c._record_snapshot_path(self.p,seed['source_key']);staged.write_text('tampered authored cache',encoding='utf-8')
                with self.assertRaises(ValueError):sync(self.p,{**args,'embed':True})
                self.db.execute('UPDATE document_sources SET active=0 WHERE source_id=?',(seed['source_id'],));self.db.commit()
                with self.assertRaises(ValueError):sync(self.p,{**args,'embed':True})
                self.assertEqual(self.db.execute('SELECT active FROM document_sources WHERE source_id=?',(seed['source_id'],)).fetchone()[0],0)

    def test_drive_version_hit(self):self.conditional('drive')
    def test_github_304_response(self):self.conditional('normal')
    def test_github_304_http_error(self):self.conditional('error')
    def test_p1_aba_and_retired_link(self):
        self.test_aba_exact_identity_history_fts_and_repeat()
