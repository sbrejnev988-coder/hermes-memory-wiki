"""Поддерживаемый native provider startup/save/recall gate; не host/loaded proof.

Вызывается существующим packaging/run_native_regressions.py после genuine SDK,
registry/trust origin и MRO проверок. SOURCE tests не вызывают эту функцию и не
подменяют её зависимости. Никакой direct SQL insertion вместо public save.
"""
from __future__ import annotations

import json
from pathlib import Path

CLAIM = 'User prefers the Atlas foundation observatory copper telescope in the east dome.'
SESSION = 'foundation-startup-session'
BOT = 'foundation-startup-bot'


def run(plugin, home):
    home = Path(home).resolve()
    from agent.memory_provider import MemoryProvider
    from tools import registry
    import hermes_trust_core as trust
    assert plugin.MemoryWikiProvider.__bases__ == (MemoryProvider,)
    assert plugin.tool_error is registry.tool_error and plugin.tool_result is registry.tool_result
    assert plugin._INJECTION_GUARD_AVAILABLE and plugin._sanitize_recalled is trust.sanitize_recalled
    assert not plugin.SEMANTIC_ENABLED
    cid = None
    steps = []
    for reopened in (False, True):
        provider = plugin.MemoryWikiProvider()
        try:
            provider.initialize(SESSION, hermes_home=str(home), bot_id=BOT, agent_context='test')
            assert provider.home.resolve() == home
            assert provider.db_path.resolve().is_relative_to(home)
            assert provider._lifecycle_state == 'ready' and provider._transaction_quarantine is None
            assert provider._background_worker is None
            steps.append('reopen' if reopened else 'startup')
            if not reopened:
                saved = json.loads(provider.handle_tool_call('memory_wiki_add_claim', {
                    'claim': CLAIM, 'topic': 'foundation-atlas',
                    'evidence': 'Authored credential-free startup acceptance fixture.',
                    'confidence': .8, 'salience': .8,
                }))
                assert not saved.get('error')
                # Pending review is not saved/recallable acceptance.
                assert saved.get('state') == 'stored' and saved.get('immediately_recallable') is True
                cid = saved['id']
                assert isinstance(cid, str) and cid.startswith('c_')
                steps.append('public_save')
            row = provider._connect().execute('SELECT claim FROM claims WHERE id=?', (cid,)).fetchone()
            assert row is not None and row[0] == CLAIM
            answer = json.loads(provider.handle_tool_call('memory_wiki_query', {
                'query': 'Atlas copper telescope east dome', 'mode': 'fts', 'limit': 5,
            }))
            assert not answer.get('error') and answer.get('disclosure_status') != 'withheld'
            assert any(item.get('id') == cid and item.get('claim') == CLAIM for item in answer.get('claims', []))
            assert provider._transaction_quarantine is None and not provider._conn.in_transaction
            steps.append('durable_public_recall' if reopened else 'public_recall')
        finally:
            provider.shutdown()
            assert provider._conn is None and provider._owned_conn is None
            assert provider._background_worker is None
            steps.append('shutdown')
    return {'schema': 'memory-stack.provider-startup/v1', 'scope': 'native_provider_component',
            'steps': steps, 'passed': True, 'host_bootstrap_executed': False,
            'models_network_vectors_executed': False, 'installed_loaded_proof': False}
