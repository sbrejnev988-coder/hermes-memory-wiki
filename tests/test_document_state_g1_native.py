"""G1: native Wiki provider + real SQLite/FTS and authored text, no live stores.

The parser transport boundary invokes the unchanged real text extractor in-process.
It does not claim document-worker supervision or remote embedding acceptance.
"""
from __future__ import annotations
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from contextlib import ExitStack
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1]
OBSERVATIONS = []
SNAPSHOT_COUNTS = {}


def load_wiki():
    name = 'g1_native_wiki'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, SOURCE / '__init__.py',
            submodule_search_locations=[str(SOURCE)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    m = sys.modules[name]
    from agent.memory_provider import MemoryProvider
    from tools import registry
    assert m.MemoryWikiProvider.__bases__ == (MemoryProvider,)
    assert m.MemoryProvider is MemoryProvider and m.tool_result is registry.tool_result
    return m, importlib.import_module(name + '.document_knowledge_graph'), importlib.import_module(name + '.document_extractors')


def authored(tag, count=4):
    return '\n\n'.join(
        f'{tag} section {index}: The operations manual records a daily backup schedule, '
        f'a retention period of {20 + index} days, and verification by the reliability team. '
        'This authored document is a synthetic regression fixture, not a user memory.'
        for index in range(1, count + 1))


def distinct_authored(tag, count):
    # Real native SimHash can intentionally merge near-identical paragraphs.
    # Lifecycle fixtures need separate canonical claims, not near-duplicates.
    subjects = (
        'The observatory calibrates optical telescopes, records stellar spectra, aligns mirrors, and measures planetary orbits. Astronomers compare celestial observations with catalogued nebulae and seasonal constellations.',
        'The harbour tracks merchant vessels, container shipments, docking permits, maritime cargo, and coastal tides. Port coordinators maintain shipping manifests and reconcile customs declarations with freight schedules.',
        'The garden cultivates fruit trees, composted soil, flowering shrubs, pollinator habitats, and irrigation channels. Botanists catalogue seed varieties and compare greenhouse germination with outdoor nursery conditions.',
        'The workshop maintains ceramic furnaces, machining lathes, copper fittings, calibrated gauges, and industrial bearings. Technicians document milling tolerances and compare fabricated components with engineering drawings.',
        'The library catalogues medieval manuscripts, printed volumes, archival photographs, bibliography records, and restored bindings. Historians trace provenance and compare annotated editions with scholarly translations.',
        'The expedition maps basalt formations, sedimentary layers, mineral deposits, glacial valleys, and volcanic terrain. Geologists catalogue quartz samples and compare surveyed rock strata with topographic maps.',
    )
    return '\n\n'.join(f'{tag} section {index + 1}: {subjects[index]}' for index in range(count))


def graph_snapshot(db):
    tables = ('document_sources', 'document_revisions', 'document_units', 'document_chunks',
              'document_edges', 'document_units_fts', 'document_chunks_fts', 'document_graph_meta', 'claims')
    result = {}
    for table in tables:
        rows = [list(row) for row in db.execute('SELECT * FROM ' + table)]
        result[table] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
    raw = json.dumps(result, sort_keys=True, separators=(',', ':')).encode()
    # Lossless authored/synthetic before/after snapshots, separate from the
    # compact evidence carrier. No live database enters this function.
    db_path = Path(db.execute('PRAGMA database_list').fetchone()[2])
    directory = db_path.parent / 'g1-snapshots'
    directory.mkdir(exist_ok=True)
    sequence = SNAPSHOT_COUNTS.get(str(directory), 0) + 1
    SNAPSHOT_COUNTS[str(directory)] = sequence
    (directory / f'{sequence:02d}.json').write_bytes(raw)
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'rows': result}


class DocumentStateG1(unittest.TestCase):
    fixture_root: Path

    @classmethod
    def setUpClass(cls):
        try:
            from agent.memory_provider import MemoryProvider
        except ImportError as exc:
            raise unittest.SkipTest('G1 requires the genuine native Hermes SDK') from exc
        if not hasattr(cls, 'fixture_root'):
            import tempfile
            owned = tempfile.TemporaryDirectory(prefix='wiki-g1-', dir=os.environ.get('TMPDIR'))
            cls.fixture_root = Path(owned.name)
            cls.addClassCleanup(owned.cleanup)

    def setUp(self):
        from hermes_constants import set_hermes_home_override
        from agent.secret_scope import set_secret_scope
        self.home = self.fixture_root / self._testMethodName
        self.home.mkdir()
        self.stack = ExitStack()
        values = {'HERMES_HOME': str(self.home), 'HOME': str(self.home), 'USERPROFILE': str(self.home),
                  'LOCALAPPDATA': str(self.home), 'TMP': str(self.home), 'TEMP': str(self.home),
                  'TMPDIR': str(self.home), 'MEMORY_WIKI_DOCUMENT_CHUNK_MAX_UNITS': '1'}
        self.stack.enter_context(mock.patch.dict(os.environ, values))
        self.home_token = set_hermes_home_override(self.home)
        self.secret_token = set_secret_scope({}, profile_home=str(self.home))
        self.m, self.d, self.e = load_wiki()
        self.stack.enter_context(mock.patch.object(self.d, '_extract',
            side_effect=lambda path, args: self.e.extract_document(path, self.d._worker_options(args))))
        self.p = self.m.MemoryWikiProvider()
        self.p.initialize('g1-fixture-session', hermes_home=str(self.home),
                          bot_id='g1-fixture-bot', project_id='g1-fixture-project')
        self.db = self.p._connect()
        self.d.install_document_graph_schema(self.db)
        self.db.commit()
        self.path = self.home / 'cache/documents/manual.txt'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.close_fixture)

    def close_fixture(self):
        from hermes_constants import reset_hermes_home_override
        from agent.secret_scope import reset_secret_scope
        if self.p._conn is not None:
            self.p._conn.close(); self.p._conn = None
        reset_secret_scope(self.secret_token)
        reset_hermes_home_override(self.home_token)
        self.stack.close()

    def ingest(self, text, path=None):
        path = path or self.path
        path.write_text(text, encoding='utf-8')
        out = self.d.ingest_document(self.p, {'path': str(path), 'embed': False})
        self.assertEqual(out['status'], 'indexed', out)
        self.assertTrue(out['content_indexed'], out)
        return out

    def chunks(self, revision):
        return [dict(row) for row in self.db.execute(
            'SELECT * FROM document_chunks WHERE revision_id=? ORDER BY start_anchor,chunk_id', (revision,))]

    def embed(self, source, limit=100):
        return self.d.embed_pending_documents(self.p, {'source_id': source, 'limit': limit})

    def visible(self, token, revision):
        out = self.d.query_documents(self.p, {'query': token, 'limit': 20})
        self.assertTrue(out['results'], out)
        self.assertTrue(all(hit['revision_id'] == revision for hit in out['results']), out)
        return out

    def observe(self, **data):
        OBSERVATIONS.append({'id': self.id(), **data})

    def test_aba_exact_identity_history_fts_and_repeat(self):
        a = self.ingest(authored('ALPHABOOK'))
        ids_a = [row['chunk_id'] for row in self.chunks(a['revision_id'])]
        units_a = [tuple(row) for row in self.db.execute(
            'SELECT unit_id,source_id,revision_id,anchor,unit_text,content_hash,locator_json FROM document_units WHERE revision_id=? ORDER BY unit_id', (a['revision_id'],))]
        b = self.ingest(authored('BETABOOK'))
        before_b = self.chunks(b['revision_id'])
        again = self.ingest(authored('ALPHABOOK'))
        self.assertEqual((a['source_id'], a['revision_id'], a['file_hash']),
                         (again['source_id'], again['revision_id'], again['file_hash']))
        self.assertEqual(ids_a, [row['chunk_id'] for row in self.chunks(a['revision_id'])])
        self.assertEqual(units_a, [tuple(row) for row in self.db.execute(
            'SELECT unit_id,source_id,revision_id,anchor,unit_text,content_hash,locator_json FROM document_units WHERE revision_id=? ORDER BY unit_id', (a['revision_id'],))])
        self.assertTrue(all(row['active'] == 1 for row in self.chunks(a['revision_id'])))
        for old, retained in zip(before_b, self.chunks(b['revision_id'])):
            self.assertEqual({k: v for k, v in old.items() if k not in {'active', 'updated_at'}},
                             {k: v for k, v in retained.items() if k not in {'active', 'updated_at'}})
            self.assertEqual(retained['active'], 0)
        self.visible('ALPHABOOK', a['revision_id'])
        self.assertEqual(self.d.query_documents(self.p, {'query': 'BETABOOK'})['results'], [])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM document_revisions').fetchone()[0], 2)
        self.assertEqual(self.db.execute('SELECT status FROM document_revisions WHERE revision_id=?', (b['revision_id'],)).fetchone()[0], 'superseded')
        before = graph_snapshot(self.db)
        out = self.d.ingest_document(self.p, {'path': str(self.path), 'embed': False})
        self.assertEqual(out['status'], 'unchanged')
        self.assertEqual(before, graph_snapshot(self.db))
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                self.db.execute("INSERT INTO document_revisions(revision_id,source_id,file_hash) VALUES('bad-fk','missing-source','bad')")
        self.observe(source=a['source_id'], revision_a=a['revision_id'], revision_b=b['revision_id'],
                     chunk_ids=ids_a, snapshot_sha=before['sha256'], revisions=2)

    def test_aba_partial_embeddings_preserve_archived_retired_erased_authority(self):
        a = self.ingest(distinct_authored('PRIVACYBOOK', 4))
        self.assertEqual(self.embed(a['source_id'], limit=3)['created'], 3)
        linked = [row for row in self.chunks(a['revision_id']) if row['embedding_claim_id']]
        self.assertEqual(len(linked), 3)
        self.assertEqual(len({row['embedding_claim_id'] for row in linked}), 3)
        archive, retire, erase = [row['embedding_claim_id'] for row in linked]
        with self.db:
            self.db.execute("UPDATE claims SET status='archived' WHERE id=?", (archive,))
            self.db.execute("UPDATE claims SET status='retired' WHERE id=?", (retire,))
            self.p._privacy_erasure.append(self.p, self.m.normalize_claim(linked[2]['embedding_text']),
                claim_ids=[erase], event_ids=[], episode_ids=[], episode_surface='')
        self.p._privacy_erasure.replay(self.p, self.m)
        # Native logical erasure retires, rather than physically deleting, a
        # claim. Check that result, then model a retained link whose target
        # was physically removed; the authenticated intent remains authoritative.
        self.assertEqual(self.db.execute('SELECT status FROM claims WHERE id=?', (erase,)).fetchone()[0], 'retired')
        with self.db:
            self.db.execute('DELETE FROM claims WHERE id=?', (erase,))
        self.assertIsNone(self.db.execute('SELECT id FROM claims WHERE id=?', (erase,)).fetchone())
        protected = {cid: tuple(self.db.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone()) for cid in (archive, retire)}
        ledger = {str(p.relative_to(self.home)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.p._privacy_erasure.dir.iterdir() if p.is_file()}
        self.assertTrue(ledger)
        b = self.ingest(authored('OTHERBOOK'))
        self.assertEqual(self.embed(b['source_id'], limit=1)['created'], 1)
        again = self.ingest(distinct_authored('PRIVACYBOOK', 4))
        self.assertEqual(again['embedding_pending'], 1)
        old_links = {row['chunk_id']: row['embedding_claim_id'] for row in linked}
        now = {row['chunk_id']: row['embedding_claim_id'] for row in self.chunks(a['revision_id'])}
        self.assertTrue(all(now[cid] == claim for cid, claim in old_links.items()))
        out = self.embed(a['source_id'], limit=1)
        self.assertEqual((out['processed'], out['created'], out['pending_after']), (1, 1, 0), out)
        self.assertEqual(out['skipped_reasons']['linked_claim_inactive'], 2)
        self.assertEqual(out['skipped_reasons']['linked_claim_missing'], 1)
        for cid, original in protected.items():
            self.assertEqual(tuple(self.db.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone()), original)
        self.assertIsNone(self.db.execute('SELECT id FROM claims WHERE id=?', (erase,)).fetchone())
        self.assertEqual(ledger, {str(p.relative_to(self.home)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.p._privacy_erasure.dir.iterdir() if p.is_file()})
        self.visible('PRIVACYBOOK', a['revision_id'])
        self.observe(revision=a['revision_id'], archived=archive, retired=retire, erased=erase,
                     pending_after=out['pending_after'], skipped=out['skipped_reasons'], ledger_hashes=ledger)

    def test_limit_one_filters_all_permanent_prefixes_before_cutoff(self):
        a = self.ingest(distinct_authored('QUEUEBOOK', 6))
        self.assertEqual(self.embed(a['source_id'])['created'], 6)
        rows = self.chunks(a['revision_id'])
        ids = [row['embedding_claim_id'] for row in rows]
        self.assertEqual(len(set(ids)), 6)
        with self.db:
            self.db.execute("UPDATE claims SET status='archived' WHERE id=?", (ids[0],))
            self.db.execute("UPDATE claims SET status='retired' WHERE id=?", (ids[1],))
            self.db.execute('DELETE FROM claims WHERE id=?', (ids[2],))
            for index, row in enumerate(rows):
                self.db.execute('UPDATE document_chunks SET updated_at=? WHERE chunk_id=?', (index + 1, row['chunk_id']))
            self.db.execute("UPDATE document_chunks SET embedding_claim_id='',repository_id='foreign-fixture-project' WHERE chunk_id=?", (rows[3]['chunk_id'],))
            for row in rows[4:]:
                self.db.execute("UPDATE document_chunks SET embedding_claim_id='' WHERE chunk_id=?", (row['chunk_id'],))
        protected = {cid: tuple(self.db.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone()) for cid in ids[:2]}
        first = self.embed(a['source_id'], 1); second = self.embed(a['source_id'], 1)
        self.assertEqual((first['processed'], first['pending_before'], first['pending_after']), (1, 2, 1), first)
        self.assertEqual((second['processed'], second['pending_before'], second['pending_after']), (1, 1, 0), second)
        # The foreign repository is excluded by the document access filter
        # before diagnostics as well as before LIMIT.
        self.assertEqual(first['skipped_reasons'], {'linked_claim_inactive': 2, 'linked_claim_missing': 1})
        foreign = self.db.execute('SELECT embedding_claim_id,repository_id FROM document_chunks WHERE chunk_id=?', (rows[3]['chunk_id'],)).fetchone()
        self.assertEqual(tuple(foreign), ('', 'foreign-fixture-project'))
        for cid, original in protected.items():
            self.assertEqual(tuple(self.db.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone()), original)
        blocked = self.embed(a['source_id'], 1)
        self.assertEqual((blocked['status'], blocked['processed'], blocked['pending_after'], blocked['retryable']), ('blocked', 0, 0, False))
        self.observe(first=first, second=second, terminal=blocked['status'])

    def test_old_derived_revision_and_inactive_source_cannot_consume_limit(self):
        a = self.ingest(authored('OLDBOOK', 2))
        self.assertEqual(self.embed(a['source_id'], 1)['created'], 1)
        b = self.ingest(authored('CURRENTBOOK', 2))
        with self.db:
            self.db.execute('UPDATE document_chunks SET active=1,updated_at=0 WHERE revision_id=?', (a['revision_id'],))
        inactive_path = self.home / 'cache/documents/inactive.txt'
        other = self.ingest(authored('INACTIVEBOOK', 1), inactive_path)
        with self.db:
            self.db.execute('UPDATE document_sources SET active=0 WHERE source_id=?', (other['source_id'],))
        out = self.d.embed_pending_documents(self.p, {'limit': 1})
        self.assertEqual((out['processed'], out['created'], out['pending_before'], out['pending_after']), (1, 1, 2, 1), out)
        self.assertTrue(any(row['embedding_claim_id'] for row in self.chunks(b['revision_id'])))
        self.assertTrue(all(not row['embedding_claim_id'] for row in self.chunks(other['revision_id'])))
        self.observe(old_revision=a['revision_id'], current_revision=b['revision_id'], result=out)

    def test_extraction_and_late_sql_failure_roll_back_current_search_atomically(self):
        a = self.ingest(authored('ATOMICBOOK', 2)); b = self.ingest(authored('STABLEBOOK', 2))
        before = graph_snapshot(self.db)
        self.path.write_text(authored('ATOMICBOOK', 2), encoding='utf-8')
        with mock.patch.object(self.d, '_extract', side_effect=RuntimeError('synthetic extraction failure')):
            with self.assertRaises(RuntimeError):
                self.d.ingest_document(self.p, {'path': str(self.path)})
        self.assertEqual(before, graph_snapshot(self.db))
        with self.db:
            self.db.execute("CREATE TRIGGER g1_late_failure BEFORE INSERT ON document_revisions BEGIN SELECT RAISE(ABORT,'synthetic late transaction failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.d.ingest_document(self.p, {'path': str(self.path)})
        self.assertEqual(before, graph_snapshot(self.db))
        observer = sqlite3.connect(self.p.db_path); observer.row_factory = sqlite3.Row
        try:
            self.assertEqual(observer.execute('SELECT revision_id FROM document_sources WHERE source_id=?', (a['source_id'],)).fetchone()[0], b['revision_id'])
            self.assertEqual(observer.execute("SELECT COUNT(*) FROM document_units_fts WHERE document_units_fts MATCH 'ATOMICBOOK'").fetchone()[0], 0)
        finally:
            observer.close()
        self.visible('STABLEBOOK', b['revision_id'])
        with self.db:
            self.db.execute('DROP TRIGGER g1_late_failure')
        self.ingest(authored('ATOMICBOOK', 2)); self.visible('ATOMICBOOK', a['revision_id'])
        self.observe(before_sha=before['sha256'], rollback_sha=before['sha256'],
                     committed_sha=graph_snapshot(self.db)['sha256'], revision_old=b['revision_id'], revision_new=a['revision_id'])

    def test_conflicting_primary_identity_is_not_ignored_and_rolls_back(self):
        a = self.ingest(authored('CONFLICTBOOK', 2)); b = self.ingest(authored('SAFEBOOK', 2))
        with self.db:
            self.db.execute("UPDATE document_units SET source_id='foreign-source' WHERE revision_id=?", (a['revision_id'],))
        before = graph_snapshot(self.db)
        self.path.write_text(authored('CONFLICTBOOK', 2), encoding='utf-8')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'identity conflict'):
            self.d.ingest_document(self.p, {'path': str(self.path)})
        self.assertEqual(before, graph_snapshot(self.db))
        self.visible('SAFEBOOK', b['revision_id'])
        self.observe(conflict='explicit identity refusal', snapshot_sha=before['sha256'])

    def test_retry_failure_advances_prefix_survives_restart_then_recovers(self):
        a = self.ingest(authored('RETRYBOOK', 2))
        rows = self.chunks(a['revision_id'])
        with self.db:
            for index, row in enumerate(rows):
                self.db.execute('UPDATE document_chunks SET updated_at=? WHERE chunk_id=?', (index + 1, row['chunk_id']))
            marker = self.m.normalize_claim(rows[0]['embedding_text']).replace("'", "''")
            self.db.execute("CREATE TRIGGER g1_claim_failure BEFORE INSERT ON claims WHEN NEW.normalized_claim='" + marker + "' BEGIN SELECT RAISE(ABORT,'synthetic claim writer unavailable'); END")
        out = self.embed(a['source_id'], 1)
        self.assertEqual((out['status'], out['failed'], out['pending_after'], out['retryable']), ('retry', 1, 2, True), out)
        self.db.close(); self.p._conn = None
        self.p = self.m.MemoryWikiProvider()
        self.p.initialize('g1-fixture-session', hermes_home=str(self.home),
                          bot_id='g1-fixture-bot', project_id='g1-fixture-project')
        self.db = self.p._connect()
        next_out = self.embed(a['source_id'], 1)
        self.assertEqual((next_out['created'], next_out['pending_after']), (1, 1), next_out)
        with self.db:
            self.db.execute('DROP TRIGGER g1_claim_failure')
        recovered = self.embed(a['source_id'], 1)
        self.assertEqual((recovered['created'], recovered['pending_after'], recovered['status']), (1, 0, 'completed'), recovered)
        self.observe(failed=out, following=next_out, recovered=recovered)
        # An unlinked chunk can also collide with a deliberately archived
        # canonical claim. Advancing the cursor must advertise more runnable
        # work, not terminate the job before the following eligible chunk.
        current = self.chunks(a['revision_id'])
        with self.db:
            for index, row in enumerate(current):
                self.db.execute("UPDATE document_chunks SET embedding_claim_id='',updated_at=? WHERE chunk_id=?", (index + 1, row['chunk_id']))
            self.db.execute("UPDATE claims SET status='archived' WHERE id=?", (current[0]['embedding_claim_id'],))
        collision = self.embed(a['source_id'], 1)
        self.assertEqual((collision['status'], collision['retryable'], collision['pending_after']), ('pending', True, 2), collision)
        following = self.embed(a['source_id'], 1)
        self.assertEqual((following['reused'], following['pending_after']), (1, 1), following)
        terminal = self.embed(a['source_id'], 1)
        self.assertEqual((terminal['status'], terminal['retryable'], terminal['failed']), ('blocked', False, 0), terminal)
        self.assertEqual(self.db.execute('SELECT status FROM claims WHERE id=?', (current[0]['embedding_claim_id'],)).fetchone()[0], 'archived')
        with self.db:
            self.db.execute("UPDATE claims SET status='retired' WHERE id=?", (current[0]['embedding_claim_id'],))
        retired = self.embed(a['source_id'], 1)
        self.assertEqual((retired['status'], retired['retryable'], retired['failed']), ('blocked', False, 0), retired)
        self.assertEqual(self.db.execute('SELECT status FROM claims WHERE id=?', (current[0]['embedding_claim_id'],)).fetchone()[0], 'retired')
        self.observe(collision=collision, following_collision=following, terminal_collision=terminal, retired_collision=retired)

    def test_shared_active_claim_link_is_preserved_without_reactivation(self):
        a = self.ingest(authored('SHAREDBOOK', 1))
        self.assertEqual(self.embed(a['source_id'])['created'], 1)
        original = self.chunks(a['revision_id'])[0]
        other = self.ingest(authored('ANCHORBOOK', 1), self.home / 'cache/documents/anchor.txt')
        with self.db:
            self.db.execute('UPDATE document_chunks SET embedding_claim_id=? WHERE revision_id=?', (original['embedding_claim_id'], other['revision_id']))
        before_claim = tuple(self.db.execute('SELECT * FROM claims WHERE id=?', (original['embedding_claim_id'],)).fetchone())
        b = self.ingest(authored('NEWBOOK', 1))
        self.ingest(authored('SHAREDBOOK', 1))
        self.assertEqual(self.chunks(a['revision_id'])[0]['embedding_claim_id'], original['embedding_claim_id'])
        self.assertEqual(tuple(self.db.execute('SELECT * FROM claims WHERE id=?', (original['embedding_claim_id'],)).fetchone()), before_claim)
        out = self.embed(a['source_id'], 1)
        self.assertEqual((out['processed'], out['pending_before'], out['created']), (0, 0, 0), out)
        self.assertEqual(self.db.execute('SELECT status FROM document_revisions WHERE revision_id=?', (b['revision_id'],)).fetchone()[0], 'superseded')
        self.observe(active_link=original['embedding_claim_id'], result=out)
