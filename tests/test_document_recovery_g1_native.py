"""One connected native G1 recovery counterexample, never a live store.

Direct SQL is fixture-owner authority, not a public lifecycle grant. The unchanged
helper's parser seam calls the real extractor without an external worker process.
"""
from pathlib import Path
import hashlib, importlib.util, json, sys, unittest

if 'g1_regressions' not in sys.modules:
    spec = importlib.util.spec_from_file_location('g1_regressions', Path(__file__).with_name('test_document_state_g1_native.py'))
    g = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = g
    spec.loader.exec_module(g)
else:
    g = sys.modules['g1_regressions']


class DocumentRecoveryG1(unittest.TestCase):
    setUpClass = classmethod(g.DocumentStateG1.setUpClass.__func__)
    setUp = g.DocumentStateG1.setUp
    close_fixture = g.DocumentStateG1.close_fixture
    ingest = g.DocumentStateG1.ingest
    chunks = g.DocumentStateG1.chunks
    embed = g.DocumentStateG1.embed
    observe = g.DocumentStateG1.observe

    def test_visible_recovery_evidence_survives_foreign_candidate_crowding(self):
        def reopen():
            self.db.close()
            self.p._conn = None
            self.p = self.m.MemoryWikiProvider()
            self.p.initialize('g1-fixture-session', hermes_home=str(self.home),
                              bot_id='g1-fixture-bot', project_id='g1-fixture-project')
            self.db = self.p._connect()

        def markers():
            return dict(self.db.execute("SELECT key,value FROM document_graph_meta WHERE key LIKE 'embedding_block:%'"))

        def fingerprint(sql, args=()):
            rows = [list(row) for row in self.db.execute(sql, args)]
            return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

        def blocked(out, remaining):
            self.assertEqual((out['status'], out['processed'], out['reused'], out['created'],
                              out['remaining'], out['blocked_remaining'], out['runnable_remaining'], out['retryable']),
                             ('blocked', 0, 0, 0, remaining, remaining, 0, False), out)
            self.assertEqual(out['failed'], 0, out)
            self.assertEqual(out['errors'], [], out)
            self.assertEqual(out['skipped_reasons'], {'archived_hash_collision': remaining}, out)

        doc = self.ingest(g.distinct_authored('RECOVERYBOOK', 2))
        self.assertEqual(self.embed(doc['source_id'])['created'], 2)
        rows = self.chunks(doc['revision_id'])
        self.assertEqual(len(rows), 2)
        ids = [row['embedding_claim_id'] for row in rows]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(self.p.project_scope, 'g1-fixture-project')
        self.assertTrue(self.db.execute("SELECT 1 FROM sqlite_master WHERE name='document_chunks_fts'").fetchone())
        evidence = [self.db.execute('SELECT evidence FROM claims WHERE id=?', (cid,)).fetchone()[0] for cid in ids]
        keys = ['document_chunk_ref:' + self.d._evidence_ref(f"{row['source_id']}\0{row['content_hash']}") for row in rows]
        self.assertTrue(all(key in ev for key, ev in zip(keys, evidence)))
        with self.db:
            for index, row in enumerate(rows):
                self.db.execute("UPDATE document_chunks SET embedding_claim_id='',updated_at=? WHERE chunk_id=?",
                                (index + 1, row['chunk_id']))
                self.db.execute("UPDATE claims SET status='archived' WHERE id=?", (ids[index],))
        initial = self.embed(doc['source_id'], 2)
        self.assertEqual((initial['status'], initial['processed'], initial['blocked_remaining'], initial['retryable']),
                         ('blocked', 2, 2, False), initial)
        original_markers = markers()
        self.assertEqual(len(original_markers), 2)
        other_marker = 'embedding_block:' + rows[1]['chunk_id']
        recovered_marker = 'embedding_block:' + rows[0]['chunk_id']
        archived_peer = fingerprint('SELECT * FROM claims WHERE id=?', (ids[1],))
        archived_chunk = fingerprint('SELECT * FROM document_chunks WHERE chunk_id=?', (rows[1]['chunk_id'],))

        # Synthetic producer owns these declarations; no ambient user/project IDs.
        template = dict(self.db.execute('SELECT * FROM claims WHERE id=?', (ids[0],)).fetchone())
        columns = list(template)
        insert = 'INSERT INTO claims (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')'
        foreign_ids = []
        foreign_texts = []
        count = 105
        self.assertGreaterEqual(count, 100)
        latest = max(self.db.execute('SELECT updated_at FROM claims WHERE id=?', (cid,)).fetchone()[0] for cid in ids)
        with self.db:
            for index in range(count):
                row = dict(template)
                cid = f'g1-recovery-foreign-{index:03d}'
                text = f'FOREIGN_ONLY_RECOVERY_SENTINEL_{index:03d}: synthetic project evidence unavailable to the caller.'
                row.update(id=cid, claim=text, normalized_claim=text, hash=hashlib.sha256(cid.encode()).hexdigest(),
                           status='active', evidence='; '.join(keys), visibility_scope='project', scope='project',
                           project_id='g1-recovery-foreign-project', origin_bot_id='g1-recovery-foreign-author',
                           origin_session_id='g1-recovery-foreign-session', origin_chat_hash='g1-recovery-foreign-chat',
                           source='artifact:synthetic-fixture-owner', updated_at=latest + index + 1)
                # Match native startup metadata before taking the peer snapshot;
                # reopening must not repair copied quality/type/source fields.
                row['quality'] = self.m.claim_quality(text, row['topic'])
                row['type'] = self.m.infer_claim_type(text, row['topic'])
                row['source_type'] = self.m.infer_source_type(row['source'])
                self.db.execute(insert, [row[name] for name in columns])
                foreign_ids.append(cid)
                foreign_texts.append(text)
        peer_sql = 'SELECT * FROM claims WHERE project_id=? ORDER BY id'
        peer_args = ('g1-recovery-foreign-project',)
        peers_before = fingerprint(peer_sql, peer_args)
        for key in keys:
            crowded = self.db.execute("SELECT id,visibility_scope,origin_bot_id,origin_chat_hash,origin_session_id,project_id "
                "FROM claims WHERE topic=? AND status='active' AND evidence LIKE ? ORDER BY updated_at DESC LIMIT 100",
                (self.d._TOPIC, f'%{key}%')).fetchall()
            self.assertEqual(len(crowded), 100)
            self.assertTrue(all(row['id'] in foreign_ids and not self.p._claim_visible(row) for row in crowded))
        reopen()
        all_hidden = self.embed(doc['source_id'], 1)
        blocked(all_hidden, 2)
        self.assertEqual(markers(), original_markers)
        self.assertEqual(fingerprint(peer_sql, peer_args), peers_before)

        # Only an explicit fixture owner activates the exact own canonical claim.
        with self.db:
            self.db.execute("UPDATE claims SET status='active' WHERE id=?", (ids[0],))
        own_active = fingerprint('SELECT * FROM claims WHERE id=?', (ids[0],))
        own_row = self.db.execute('SELECT * FROM claims WHERE id=?', (ids[0],)).fetchone()
        self.assertTrue(self.p._claim_visible(own_row))
        self.assertLessEqual(own_row['updated_at'], latest)
        sql, parameters = self.p._claim_visibility_sql(include_all_projects=False)
        visible = self.db.execute("SELECT id FROM claims WHERE topic=? AND status='active' AND evidence LIKE ? AND " + sql +
                                 ' ORDER BY updated_at DESC LIMIT 100', [self.d._TOPIC, f'%{keys[0]}%', *parameters]).fetchall()
        self.assertEqual([row[0] for row in visible], [ids[0]])
        reopen()
        recovered = self.embed(doc['source_id'], 1)
        # Decisive assertion: frozen repair01 loses the legal row behind LIMIT100.
        self.assertEqual((recovered['reused'], recovered['created'], recovered['processed'], recovered['remaining'],
                          recovered['blocked_remaining'], recovered['runnable_remaining'], recovered['retryable']),
                         (1, 0, 1, 1, 1, 0, False), recovered)
        self.assertEqual(self.chunks(doc['revision_id'])[0]['embedding_claim_id'], ids[0])
        self.assertFalse(self.chunks(doc['revision_id'])[1]['embedding_claim_id'])
        self.assertNotIn(recovered_marker, markers())
        self.assertEqual(markers(), {other_marker: original_markers[other_marker]})
        self.assertEqual(fingerprint(peer_sql, peer_args), peers_before)
        self.assertEqual(fingerprint('SELECT * FROM claims WHERE id=?', (ids[0],)), own_active)
        self.assertEqual(fingerprint('SELECT * FROM claims WHERE id=?', (ids[1],)), archived_peer)
        self.assertEqual(fingerprint('SELECT * FROM document_chunks WHERE chunk_id=?', (rows[1]['chunk_id'],)), archived_chunk)
        reopen()
        other_archived = self.embed(doc['source_id'], 1)
        blocked(other_archived, 1)

        # Real native privacy replay affects active rows: fixture activation first,
        # never document embedding between activation and erasure.
        with self.db:
            self.db.execute("UPDATE claims SET status='active' WHERE id=?", (ids[1],))
            self.p._privacy_erasure.append(self.p, self.m.normalize_claim(rows[1]['embedding_text']),
                claim_ids=[ids[1]], event_ids=[], episode_ids=[], episode_surface='')
        self.p._privacy_erasure.replay(self.p, self.m)
        self.assertEqual(self.db.execute('SELECT status FROM claims WHERE id=?', (ids[1],)).fetchone()[0], 'retired')
        ledger = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.p._privacy_erasure.dir.iterdir() if p.is_file()}
        self.assertTrue(ledger)
        reopen()
        erased = self.embed(doc['source_id'], 1)
        blocked(erased, 1)
        self.assertEqual(markers(), {other_marker: original_markers[other_marker]})
        with self.db:
            self.db.execute('DELETE FROM claims WHERE id=?', (ids[1],))
        reopen()
        missing = self.embed(doc['source_id'], 1)
        blocked(missing, 1)
        self.assertIsNone(self.db.execute('SELECT id FROM claims WHERE id=?', (ids[1],)).fetchone())
        self.assertFalse(self.chunks(doc['revision_id'])[1]['embedding_claim_id'])
        self.assertEqual(markers(), {other_marker: original_markers[other_marker]})
        sql, parameters = self.p._claim_visibility_sql(include_all_projects=False)
        self.assertEqual(self.db.execute("SELECT id FROM claims WHERE topic=? AND status='active' AND evidence LIKE ? AND " + sql,
                                        [self.d._TOPIC, f'%{keys[1]}%', *parameters]).fetchall(), [])
        self.assertEqual(ledger, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.p._privacy_erasure.dir.iterdir() if p.is_file()})
        self.assertEqual(fingerprint(peer_sql, peer_args), peers_before)
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])
        outputs = (initial, all_hidden, recovered, other_archived, erased, missing)
        rendered = json.dumps(outputs, sort_keys=True)
        self.assertTrue(all(cid not in rendered for cid in foreign_ids))
        self.assertTrue(all(text not in rendered for text in foreign_texts))
        self.assertNotIn('g1-recovery-foreign-project', rendered)
        self.assertTrue(all(out['remaining'] <= 2 and out['blocked_remaining'] <= 2
                            and out['pending_before'] <= 2 and out['pending_after'] <= 2 for out in outputs))
        self.observe(all_hidden=all_hidden, recovered=recovered, other_archived=other_archived,
                     erased=erased, missing=missing, peers_unchanged=True,
                     erased_marker_retained=True, foreign_identifiers_and_text_absent=True,
                     native_ledger_hashes=ledger)
