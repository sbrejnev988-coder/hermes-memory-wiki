"""Claim→graph original admission: genuine SOURCE, not native host/network.

Producer/validator are real SPI/file-backed SQLite/ACL/erasure. Opener and SDK
MockTransport responses are authored inputs. The SDK hook test does NOT claim
native Codex adapter bootstrap, auth/YAML compatibility or atomic wire lease.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time

import pytest

_SPEC = importlib.util.spec_from_file_location('graph_extraction_fixture',
    Path(__file__).parent / 'ci_owned/graph_extraction_fixture.py')
f = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = f
_SPEC.loader.exec_module(f)
graph_case = f.graph_case


def test_prepared_withdrawal(graph_case):
    with f.Fixture('prepared') as case:
        case.on_prepare = lambda: f.withdraw(case)
        out = case.call()
        # Exact same assertion on pristine c325 and candidate. A late error
        # alone is not prevention: the actual HTTP sink must remain empty.
        case._emit(dict(event='prepared_withdrawal_outcome', requests=len(case.posts), out=out))
        assert case.posts == [], 'withdrawn_original_claim_reached_actual_HTTP_sink'
        f.denied(out)
        assert case.conn.execute('SELECT COUNT(*) FROM relations').fetchone()[0] == 0


@pytest.mark.parametrize('apply', [False, True])
def test_healthy_http(graph_case, apply):
    with f.Fixture('healthy') as case:
        # Manual graph is not recall: preserve low quality/artifact/old TTL.
        case.conn.execute("UPDATE claims SET quality=0,type='source_artifact',expires_at=1 WHERE id=?", (f.CID,))
        case.conn.commit()
        before = tuple(case.conn.execute('SELECT * FROM claims WHERE id=?', (f.CID,)).fetchone())
        with f.schedule(case, 'unused', lambda: None):
            out = case.call(apply=apply)
        assert out['proposals'] == [f.PROPOSAL] and out['applied'] == int(apply)
        assert len(case.posts) == 1
        assert tuple(case.conn.execute('SELECT * FROM claims WHERE id=?', (f.CID,)).fetchone()) == before
        assert case.fences and all(x.graph_attempt.cancel is case.fences[0].graph_attempt.cancel for x in case.fences)
        own = case.fences[0].graph_changes
        assert own == (6 if apply else 0)  # 2 vertices + 1 edge + 3 exact mutation rows, no triggers.
        assert case.conn.execute('SELECT COUNT(*) FROM relations').fetchone()[0] == int(apply)
        if apply:
            rid = out['relation_ids'][0]
            assert case.conn.execute('SELECT source_claim_id FROM relations WHERE id=?', (rid,)).fetchone()[0] == f.CID
            events = list(case.p._iter_journal_events())
            assert [e['phase'] for e in events if e['op'] == 'memory_wiki_add_relation'] == ['before', 'after']
        assert case.p._transaction_quarantine is None and not case.conn.in_transaction
        if not apply:
            case.empty = True
            empty = case.call(direct=True)
            assert empty['proposals'] == [] and empty['applied'] == 0 and len(case.posts) == 2
            assert case.conn.execute('SELECT COUNT(*) FROM relations').fetchone()[0] == 0


@pytest.mark.parametrize('mode', ['disabled', 'foreign'])
def test_initial_denial(graph_case, mode):
    with f.Fixture('initial') as case:
        if mode == 'disabled':
            # Actual call-time ENV reader, not a guard/identity override.
            case._mp.setenv('MEMORY_WIKI_GRAPH_EXTRACT_ENABLED', '0')
        else:
            case.conn.execute("UPDATE claims SET visibility_scope='private',origin_bot_id='foreign' WHERE id=?", (f.CID,))
            case.conn.commit()
        out = case.call()
        f.denied(out)
        assert case.posts == []


@pytest.mark.parametrize('mode', ['ABA', 'owner', 'erasure'])
def test_original_authority(graph_case, mode):
    with f.Fixture('authority') as case:
        case.on_prepare = lambda: f.withdraw(case, mode)
        out = case.call(apply=True)
        assert case.posts == []
        f.denied(out)
        assert case.conn.execute('SELECT COUNT(*) FROM relations').fetchone()[0] == 0


@pytest.mark.parametrize('seam', ['response', 'validation', 'serialization', 'cleanup', 'journal', 'mutation'])
def test_upper_return(graph_case, seam):
    with f.Fixture('upper') as case:
        action = lambda: f.withdraw(case, 'session' if seam == 'journal' else 'status')
        if seam == 'mutation':
            def action():
                before = tuple(case.conn.execute('SELECT * FROM claims WHERE id=?', (f.CID,)).fetchone())
                case.conn.execute("UPDATE claims SET origin_bot_id='foreign' WHERE id=?", (f.CID,))
                case.conn.execute('UPDATE claims SET origin_bot_id=? WHERE id=?', (case.bot_id, f.CID))
                assert tuple(case.conn.execute('SELECT * FROM claims WHERE id=?', (f.CID,)).fetchone()) == before
        case.empty = seam == 'cleanup'
        if seam == 'response':
            case.on_response = action
            out = case.call()
        else:
            with f.schedule(case, seam, action) as seen:
                out = case.call(apply=seam in {'journal', 'mutation'})
            assert seen == [seam], 'required_late_callback_not_reached'
        assert len(case.posts) == 1
        f.denied(out)
        # A journal-after withdrawal detects already committed own effects;
        # it is not a fabricated rollback/atomic batch guarantee.
        assert case.conn.execute('SELECT COUNT(*) FROM relations').fetchone()[0] == int(seam == 'journal')


def test_original_stop_and_primary(graph_case):
    with f.Fixture('stop') as case:
        for mode in ('cancel', 'deadline'):
            event = threading.Event()
            deadline = time.monotonic() + (.3 if mode == 'deadline' else 3)
            def stop():
                if mode == 'cancel':
                    event.set()
                else:
                    time.sleep(max(0, deadline - time.monotonic()) + .01)
            case.on_prepare = stop
            with case.m._prefetch_budget(3, event, deadline=deadline):
                out = case.call()
                assert case.m._PREFETCH_LOCAL.cancel_event is event
                assert case.m._PREFETCH_LOCAL.deadline == deadline
            f.denied(out)
            assert not case.posts
        primary = BaseException('authored_graph_transport_primary')
        case.failure = primary
        with pytest.raises(BaseException) as caught:
            case.call(direct=True)
        assert caught.value is primary and len(case.posts) == 1
        assert case.p._transaction_quarantine is None


def test_primary_unknown(graph_case):
    with f.Fixture('UNKNOWN') as case:
        primary = BaseException('authored_graph_owner_primary')
        def abort():
            case.conn.set_authorizer(lambda a, b, c, d, e:
                sqlite3.SQLITE_DENY if a == sqlite3.SQLITE_TRANSACTION and b == 'ROLLBACK' else sqlite3.SQLITE_OK)
            raise primary
        with f.schedule(case, 'mutation', abort) as seen:
            with pytest.raises(BaseException) as caught:
                case.call(apply=True, direct=True)
        assert seen and caught.value is primary
        p, c = case.p, case.conn
        assert p._transaction_quarantine is c and p._transaction_primary is primary
        assert p._owned_conn is c is p._claim_tx_connection and c.in_transaction
        assert p._claim_tx_graph_stage[2]
        denied = case.call()
        f.denied(denied)
        assert len(case.posts) == 1 and p._transaction_primary is primary
        case._emit(dict(event='original_primary_UNKNOWN_retained', same_primary=True,
                        same_owner=True, stage_retained=True, new_call_refused=True))
        # Exact-owned fixture safety cleanup only. Do not clear quarantine or
        # reclassify it as production recovery; the fixture closes its handle.
        case.safety_close_unknown = True


def test_synchronous_auto(graph_case):
    with f.Fixture('sync-auto') as case:
        # Real heuristic → _add_claim/evidence → new-ID selectors → graph.
        case.p._extract_session_claims([dict(role='user', content='Remember ' + f.AUTO_TEXT)])
        rows = case.conn.execute("SELECT id,claim,source FROM claims WHERE source='extractor:heuristic'").fetchall()
        assert len(rows) == 1 and rows[0]['id'].startswith('c_') and rows[0]['claim'].rstrip('.') == f.AUTO_TEXT.rstrip('.')
        evidence = case.conn.execute('SELECT text FROM evidence WHERE claim_id=?', (rows[0]['id'],)).fetchone()
        assert json.loads(evidence[0])['session_id'] == 'session-own'
        assert len(case.posts) == 1
        assert case.conn.execute('SELECT COUNT(*) FROM relations WHERE source_claim_id=?', (rows[0]['id'],)).fetchone()[0] == 1


def test_public_sdk_final_hook(graph_case):
    if importlib.util.find_spec('httpx') is None:
        pytest.skip('BLOCKED: registered read-only environment lacks genuine HTTPX; no SDK/adapter stand-in')
    with f.Fixture('sdk-hook') as case:
        import httpx
        import openai
        ex = __import__(case._namespace + '.extractor', fromlist=['_codex_http_client'])
        assert Path(openai.__file__).is_relative_to(Path(sys.prefix))
        assert Path(httpx.__file__).is_relative_to(Path(sys.prefix))
        sinks, order = [], []
        for revoke in (False, True):
            fence = case.m._DisclosureFence(case.p, case.conn)
            raw = fence.watch('claims', 'id', [f.CID])
            fence.claims(raw, purpose='graph_extract')
            attempt = case.m._GraphExtraction(fence, threading.Event(), time.monotonic()+3)
            def receive(request):
                sinks.append(json.loads(request.content))
                order.append('transport')
                return httpx.Response(200, json=dict(id='resp_authored', object='response', model='gpt-authored',
                    created_at=0, output=[], parallel_tool_calls=True, tool_choice='auto', tools=[]))
            transport = httpx.MockTransport(receive)
            def admit():
                order.append('original_admission')
                return attempt.admit()
            http = ex._codex_http_client(attempt.deadline, _admit=admit, transport=transport)
            # A per-client late hook BEFORE product's final hook is a genuine
            # HTTPX encoding-to-admission seam, not a mocked dispatcher success.
            def prepared(request):
                body = json.loads(request.content)
                assert body['input'] == f.TEXT and body['store'] is False
                order.append('SDK_encoded')
                if revoke:
                    f.withdraw(case)
            http.event_hooks['request'].insert(0, prepared)
            with openai.OpenAI(api_key='authored-header-only', base_url='https://chatgpt.com/backend-api/codex',
                               http_client=http, max_retries=0, organization='', project='') as sdk:
                if revoke:
                    with pytest.raises(openai.APIConnectionError):
                        sdk.responses.create(model='gpt-authored', input=f.TEXT, store=False)
                else:
                    sdk.responses.create(model='gpt-authored', input=f.TEXT, store=False)
        assert len(sinks) == 1 and order == ['SDK_encoded', 'original_admission', 'transport',
                                           'SDK_encoded', 'original_admission']
        case._emit(dict(event='public_SDK_HTTPX_hook_proof', actual_sink_count=1, order=order,
                        native_Codex_adapter_auth_owner_YAML='BLOCKED_bootstrap_import_not_executed'))
