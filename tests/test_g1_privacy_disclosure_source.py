"""SOURCE enrollment controls, not native privacy or public-query proof.

The controller supplies the unchanged DisclosureFence.documents owning body.
Watch rows and the access callback below are authored seams; no SQL, provider,
SDK, erasure implementation, finish() or public serialization is substituted
and then represented as native evidence. The original G1 case stays separate.
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

__test__ = False
_DOCUMENTS = None
METHODS = (
    'test_present_links_and_unlinked_chunk_do_not_veto_enrollment',
    'test_missing_retained_link_vetoes_enrollment',
    'test_good_later_batch_cannot_clear_prior_veto',
)


def fence(claims, *, ok=True):
    """Explicit source-only watch/access inputs, never an SDK stand-in."""
    events = []
    item = SimpleNamespace(ok=ok, purposes={})
    item.provider = SimpleNamespace(
        bot_id='owned-source-bot',
        _disclosure_document_access=lambda row: events.append(('access', row['source_id'])),
    )
    tables = {
        'document_sources': [{'source_id': 'source', 'revision_id': 'revision', 'active': 1}],
        'document_revisions': [{'revision_id': 'revision'}],
        'external_sources': [],
        'claims': claims,
    }

    def watch(table, column, ids, optional=False):
        events.append(('watch', table, column, tuple(ids), optional))
        assert table in tables
        return [dict(row) for row in tables[table] if row.get(column) in ids]

    item.watch = watch
    return item, events


def chunk(link):
    return {'source_id': 'source', 'revision_id': 'revision', 'embedding_claim_id': link}


class EnrollmentCases(unittest.TestCase):
    def test_present_links_and_unlinked_chunk_do_not_veto_enrollment(self):
        item, events = fence([{'id': 'present'}])
        _DOCUMENTS(item, [chunk('present'), chunk('')])
        self.assertIs(item.ok, True)
        self.assertEqual(item.purposes, {'present': ('recall', '', False)})
        self.assertTrue(any(event[:3] == ('watch', 'claims', 'id') for event in events))
        self.assertIn(('access', 'source'), events)
        # This proves only absence of this enrollment veto, not finish/access.

    def test_missing_retained_link_vetoes_enrollment(self):
        item, events = fence([{'id': 'present'}])
        _DOCUMENTS(item, [chunk('present'), chunk('erased-missing')])
        self.assertIs(item.ok, False)
        self.assertEqual(item.purposes, {'present': ('recall', '', False)})
        self.assertIn(('watch', 'claims', 'id', ('present', 'erased-missing'), True), events)

    def test_good_later_batch_cannot_clear_prior_veto(self):
        item, _events = fence([{'id': 'present'}], ok=False)
        _DOCUMENTS(item, [chunk('present'), chunk('')])
        self.assertIs(item.ok, False)
        self.assertEqual(item.purposes, {'present': ('recall', '', False)})


def make_suite(documents):
    global _DOCUMENTS
    assert callable(documents)
    _DOCUMENTS = documents
    return unittest.TestSuite(EnrollmentCases(name) for name in METHODS)
