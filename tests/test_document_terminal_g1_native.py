"""One native G1 terminal-queue regression, with connected controls.

Uses the frozen eight-case fixture helpers; no old test body is changed/run here.
"""
from pathlib import Path
import hashlib, importlib.util, sys, unittest

if 'g1_regressions' not in sys.modules:
    spec = importlib.util.spec_from_file_location('g1_regressions', Path(__file__).with_name('test_document_state_g1_native.py'))
    g = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = g
    spec.loader.exec_module(g)
else:
    g = sys.modules['g1_regressions']


class DocumentTerminalG1(unittest.TestCase):
    setUpClass = classmethod(g.DocumentStateG1.setUpClass.__func__)
    setUp = g.DocumentStateG1.setUp
    close_fixture = g.DocumentStateG1.close_fixture
    ingest = g.DocumentStateG1.ingest
    chunks = g.DocumentStateG1.chunks
    embed = g.DocumentStateG1.embed
    observe = g.DocumentStateG1.observe

    def test_multiple_permanent_collisions_limit_one_reopen_and_recovery(self):
        def reopen():
            self.db.close()
            self.p._conn = None
            self.p = self.m.MemoryWikiProvider()
            self.p.initialize('g1-fixture-session', hermes_home=str(self.home),
                              bot_id='g1-fixture-bot', project_id='g1-fixture-project')
            self.db = self.p._connect()

        def seed(text, path):
            doc = self.ingest(text, path)
            self.assertEqual(self.embed(doc['source_id'])['created'], 2)
            rows = self.chunks(doc['revision_id'])
            self.assertEqual(len(rows), 2)
            self.assertEqual(len({row['embedding_claim_id'] for row in rows}), 2)
            with self.db:
                for index, row in enumerate(rows):
                    self.db.execute("UPDATE document_chunks SET embedding_claim_id='',updated_at=? WHERE chunk_id=?",
                                    (index + 1, row['chunk_id']))
            return doc, rows

        paragraphs = g.distinct_authored('TERMINALBOOK', 6).split('\n\n')
        a, rows = seed('\n\n'.join(paragraphs[:2]), self.path)
        ids = [row['embedding_claim_id'] for row in rows]
        with self.db:
            self.db.executemany("UPDATE claims SET status='archived' WHERE id=?", [(cid,) for cid in ids])
        protected = {cid: tuple(self.db.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone()) for cid in ids}
        first = self.embed(a['source_id'], 1)
        self.assertEqual((first['status'], first['processed'], first['remaining'], first['retryable']),
                         ('pending', 1, 2, True), first)
        reopen()
        second = self.embed(a['source_id'], 1)
        self.assertEqual((second['status'], second['processed'], second['remaining'], second['retryable']),
                         ('blocked', 1, 2, False), second)
        reopen()
        terminal = self.embed(a['source_id'], 1)
        self.assertEqual((terminal['status'], terminal['processed'], terminal['remaining'], terminal['retryable']),
                         ('blocked', 0, 2, False), terminal)
        self.assertEqual((terminal['blocked_remaining'], terminal['runnable_remaining']), (2, 0), terminal)
        self.assertEqual(terminal['skipped_reasons']['archived_hash_collision'], 2)
        self.assertTrue(all(not row['embedding_claim_id'] for row in self.chunks(a['revision_id'])))
        for cid, before in protected.items():
            self.assertEqual(tuple(self.db.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone()), before)
        markers = [row['value'] for row in self.db.execute("SELECT value FROM document_graph_meta WHERE key LIKE 'embedding_block:%'")]
        self.assertEqual(len(markers), 2)
        self.assertTrue(all(not any(cid in marker for cid in ids) for marker in markers))
        self.assertTrue(all(not any(row['embedding_text'] in marker for row in rows) for marker in markers))

        # Only explicit owner reactivation plus genuine current visible evidence
        # can release this block. The document code itself never reactivates it.
        with self.db:
            self.db.execute("UPDATE claims SET status='active' WHERE id=?", (ids[0],))
        recovered_active = self.embed(a['source_id'], 1)
        self.assertEqual((recovered_active['reused'], recovered_active['remaining'], recovered_active['retryable']),
                         (1, 1, False), recovered_active)
        self.assertEqual(self.chunks(a['revision_id'])[0]['embedding_claim_id'], ids[0])
        self.assertFalse(self.chunks(a['revision_id'])[1]['embedding_claim_id'])
        with self.db:
            # Native replay retires active rows only (privacy_erasure.py:271-276).
            # Model a separate explicit owner activation before the erasure;
            # do not call document embedding between activation and erase.
            self.db.execute("UPDATE claims SET status='active' WHERE id=?", (ids[1],))
            self.p._privacy_erasure.append(self.p, self.m.normalize_claim(rows[1]['embedding_text']),
                claim_ids=[ids[1]], event_ids=[], episode_ids=[], episode_surface='')
        self.p._privacy_erasure.replay(self.p, self.m)
        self.assertEqual(self.db.execute('SELECT status FROM claims WHERE id=?', (ids[1],)).fetchone()[0], 'retired')
        with self.db:
            self.db.execute('DELETE FROM claims WHERE id=?', (ids[1],))
        ledger = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.p._privacy_erasure.dir.iterdir() if p.is_file()}
        self.assertTrue(ledger)
        reopen()
        erased = self.embed(a['source_id'], 1)
        self.assertEqual((erased['status'], erased['processed'], erased['retryable']), ('blocked', 0, False), erased)
        self.assertIsNone(self.db.execute('SELECT id FROM claims WHERE id=?', (ids[1],)).fetchone())
        self.assertFalse(self.chunks(a['revision_id'])[1]['embedding_claim_id'])
        self.assertEqual(ledger, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.p._privacy_erasure.dir.iterdir() if p.is_file()})

        mixed, mixed_rows = seed('\n\n'.join(paragraphs[2:4]), self.path.with_name('mixed.txt'))
        archived = mixed_rows[0]['embedding_claim_id']
        with self.db:
            self.db.execute("UPDATE claims SET status='archived' WHERE id=?", (archived,))
        before = tuple(self.db.execute('SELECT * FROM claims WHERE id=?', (archived,)).fetchone())
        collision = self.embed(mixed['source_id'], 1)
        self.assertEqual((collision['status'], collision['pending_after'], collision['retryable']), ('pending', 2, True), collision)
        reopen()
        following = self.embed(mixed['source_id'], 1)
        self.assertEqual((following['reused'], following['status'], following['pending_after'], following['retryable']),
                         (1, 'blocked', 1, False), following)
        self.assertEqual(tuple(self.db.execute('SELECT * FROM claims WHERE id=?', (archived,)).fetchone()), before)
        self.assertFalse(self.chunks(mixed['revision_id'])[0]['embedding_claim_id'])

        transient = self.ingest('\n\n'.join(paragraphs[4:]), self.path.with_name('transient.txt'))
        transient_rows = self.chunks(transient['revision_id'])
        self.assertEqual(len(transient_rows), 2)
        marker = self.m.normalize_claim(transient_rows[0]['embedding_text']).replace("'", "''")
        with self.db:
            for index, row in enumerate(transient_rows):
                self.db.execute('UPDATE document_chunks SET updated_at=? WHERE chunk_id=?', (index + 1, row['chunk_id']))
            self.db.execute("CREATE TRIGGER g1_terminal_transient BEFORE INSERT ON claims WHEN NEW.normalized_claim='" + marker + "' BEGIN SELECT RAISE(ABORT,'synthetic transient writer unavailable'); END")
        failed = self.embed(transient['source_id'], 1)
        self.assertEqual((failed['status'], failed['failed'], failed['pending_after'], failed['retryable']), ('retry', 1, 2, True), failed)
        reopen()
        next_work = self.embed(transient['source_id'], 1)
        self.assertEqual((next_work['created'], next_work['pending_after']), (1, 1), next_work)
        with self.db:
            self.db.execute('DROP TRIGGER g1_terminal_transient')
        success = self.embed(transient['source_id'], 1)
        self.assertEqual((success['created'], success['status'], success['pending_after'], success['retryable']), (1, 'completed', 0, False), success)
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.observe(first=first, second=second, terminal=terminal, owner_recovery=recovered_active,
                     erased=erased, collision=collision, following=following, transient_failure=failed,
                     next_work=next_work, success=success, ledger_hashes=ledger)
