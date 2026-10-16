"""SQL-policy UNIT; real graph predicate/SQLite, authored metadata/actor values.

This is not a provider/lifecycle/native authorization test. The complete
current-provider regression is separately exercised by the RI-R03 component
packet. No SDK class, trust guard, HTTP result or configuration file is faked.
"""
from contextlib import closing
from types import SimpleNamespace
import sqlite3

import pytest
from memory_wiki import document_knowledge_graph as graph


@pytest.mark.parametrize('actor,expected', [
    ('bot-own', ['owned', 'plain', 'twice-owned']),
    ('bot-foreign', ['foreign', 'plain']),
    ('', ['plain']),
    (' bot-own ', ['plain', 'raw-padded']),
    ('   ', ['plain']),
], ids=['owned-actor', 'foreign-actor', 'empty-actor', 'padded-actor', 'blank-actor'])
def test_connector_domain_matches_terminal_active_owner_policy(actor, expected):
    source_ids = ['plain', 'owned', 'foreign', 'disabled-own', 'disabled-foreign',
                  'deleted-own', 'ownerless', 'null-owner', 'null-status', 'mixed',
                  'twice-owned', 'raw-padded', 'mixed-disabled-own', 'mixed-disabled-foreign']
    links = [
        ('owned', 'bot-own', 'active'),
        ('foreign', 'bot-foreign', 'active'),
        ('disabled-own', 'bot-own', 'disabled'),
        ('disabled-foreign', 'bot-foreign', 'disabled'),
        ('deleted-own', 'bot-own', 'deleted'),
        ('ownerless', '', 'active'),
        ('null-owner', None, 'active'),
        ('null-status', 'bot-own', None),
        ('mixed', 'bot-own', 'active'),
        ('mixed', 'bot-foreign', 'active'),
        ('twice-owned', 'bot-own', 'active'),
        ('twice-owned', 'bot-own', 'active'),
        ('raw-padded', ' bot-own ', 'active'),
        ('mixed-disabled-own', 'bot-own', 'active'),
        ('mixed-disabled-own', 'bot-own', 'disabled'),
        ('mixed-disabled-foreign', 'bot-own', 'active'),
        ('mixed-disabled-foreign', 'bot-foreign', 'disabled'),
    ]
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.execute('CREATE TABLE sources(source_id TEXT PRIMARY KEY)')
        # Deliberately nullable malformed-row negatives; not a production DDL.
        conn.execute('CREATE TABLE external_sources(document_source_id TEXT, owner_bot_id TEXT, status TEXT)')
        conn.executemany('INSERT INTO sources VALUES(?)', [(sid,) for sid in source_ids])
        conn.executemany('INSERT INTO external_sources VALUES(?,?,?)', links)
        before = conn.execute('SELECT * FROM external_sources ORDER BY rowid').fetchall()
        predicate, params = graph._connector_visibility_clause(
            conn, SimpleNamespace(bot_id=actor), 's.source_id')
        actual = conn.execute('SELECT s.source_id FROM sources s WHERE ' + predicate +
                              ' ORDER BY s.source_id', params).fetchall()
        assert [row[0] for row in actual] == expected
        # Eligibility is applied before a small limit, not a post-cutoff filter.
        limited = conn.execute('SELECT s.source_id FROM sources s WHERE ' + predicate +
                               ' ORDER BY s.source_id LIMIT 1', params).fetchall()
        assert [row[0] for row in limited] == expected[:1]
        assert conn.execute('SELECT * FROM external_sources ORDER BY rowid').fetchall() == before
        assert conn.execute('SELECT COUNT(*) FROM sources').fetchone()[0] == len(source_ids)


def test_absent_connector_table_keeps_ordinary_unlinked_document_domain():
    with closing(sqlite3.connect(':memory:')) as conn:
        assert graph._connector_visibility_clause(conn, SimpleNamespace(bot_id='bot-own'),
                                                   's.source_id') == ('', [])
