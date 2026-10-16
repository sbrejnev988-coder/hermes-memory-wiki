"""Original pack read-set at authored secondary POST and helper publication.

Direct genuine SPI/registry/trust + real file-backed SQLite; synthetic SQL and
bounded authored HTTP streams, not MemoryManager/SDK/network/model execution.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'llm_pack_owned_fixture', Path(__file__).parent / 'ci_owned/llm_pack_egress_fixture.py')
fmod = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = fmod
_SPEC.loader.exec_module(fmod)
llm_pack_case = fmod.llm_pack_case
Fixture, seed, public = fmod.Fixture, fmod.seed, fmod.public
MARKER, FOREIGN_MARKER = fmod.MARKER, fmod.FOREIGN_MARKER


def test_llm_pack_healthy_refinement(llm_pack_case):
    with Fixture('healthy') as f:
        seed(f)
        out = public(f)
        assert out['success'] is True and out['sources']['llm_refined'] is True
        assert out['context'] == fmod.REPLY and MARKER in out['context']
        assert FOREIGN_MARKER not in json.dumps(out)
        assert f.calls['post'] == 1 and MARKER in json.dumps(f.posts[0])
        assert FOREIGN_MARKER not in json.dumps(f.posts)
        fmod.assert_original(f)
        assert f.handoff['original_llm_checks'] >= 2
        assert f.conn.execute('SELECT COUNT(*) FROM claims').fetchone()[0] == 2
        assert f.conn.execute('SELECT recall_count FROM claims WHERE id=?', (fmod.CLAIM,)).fetchone()[0] == 1
        assert f.conn.execute('SELECT recall_count FROM claims WHERE id=?', (fmod.FOREIGN,)).fetchone()[0] == 0


def test_llm_pack_canonical_without_llm(llm_pack_case):
    with Fixture('canonical') as f:
        seed(f)
        f._mp.setenv('MEMORY_WIKI_LLM_PACK', '0')
        out = public(f)
        assert out['success'] is True and out['sources']['llm_refined'] is False
        assert MARKER in out['context'] and FOREIGN_MARKER not in json.dumps(out)
        assert not f.posts and not f.streams
        assert 'structured_pack' not in out and 'results' not in out
        fmod.assert_original(f, checks=False)
        assert f.conn.execute('SELECT recall_count FROM claims WHERE id=?', (fmod.CLAIM,)).fetchone()[0] == 1


def test_llm_pack_initial_ineligible_rows_never_egress(llm_pack_case):
    with Fixture('initial') as f:
        seed(f)
        fmod.changed(f, 'status')
        out = public(f)
        assert out['success'] is True
        assert MARKER not in json.dumps(out) and FOREIGN_MARKER not in json.dumps(out)
        assert MARKER not in json.dumps(f.posts) and FOREIGN_MARKER not in json.dumps(f.posts)
        # Existing pack policy/plan can still be refined; do not invent a new
        # empty-pool blanket refusal. No ineligible row reaches that request.
        assert f.calls['post'] == 1
        assert f.conn.execute('SELECT COUNT(*) FROM claims').fetchone()[0] == 2
        assert f.conn.execute('SELECT SUM(recall_count) FROM claims').fetchone()[0] == 0
        assert f.conn.execute('SELECT COUNT(*) FROM recall_events').fetchone()[0] == 0
        assert f.handoff['same_original_at_llm'] and f.handoff['original_llm_checks'] >= 2


@pytest.mark.parametrize('action', ['status', 'owner', 'ABA', 'lifecycle'])
def test_llm_pack_late_change_before_POST(llm_pack_case, action):
    with Fixture('prepared-' + action) as f:
        seed(f)
        with fmod.schedule(f, 'prepared', action) as seen:
            out = public(f)
        fmod.assert_denied(f, out, seen, posts=0)
        assert not f.posts and not f.streams


@pytest.mark.parametrize('action', ['status', 'owner', 'lifecycle'])
def test_llm_pack_late_change_after_response(llm_pack_case, action):
    with Fixture('response-' + action) as f:
        seed(f)
        with fmod.schedule(f, 'response', action) as seen:
            out = public(f)
        fmod.assert_denied(f, out, seen, posts=1)
        assert MARKER in json.dumps(f.posts[0])
        assert len(f.streams) == 1 and f.streams[0].closed
        assert f.handoff['original_llm_checks'] >= 2


@pytest.mark.parametrize('primary', [BaseException('authored-primary'), asyncio.CancelledError('authored-cancel')],
                         ids=['BaseException', 'cancel'])
def test_llm_pack_guard_unwind_preserves_primary(llm_pack_case, primary):
    with Fixture('primary-' + type(primary).__name__) as f:
        seed(f)
        with fmod.schedule(f, 'guard', primary=primary) as seen:
            with pytest.raises(type(primary)) as caught:
                public(f)
        assert seen and caught.value is primary
        assert not f.original.ok
        assert f.calls['post'] == 0 and not f.posts
        assert f.conn.execute('SELECT SUM(recall_count) FROM claims').fetchone()[0] == 0
        assert f.conn.execute('SELECT COUNT(*) FROM recall_events').fetchone()[0] == 0


def test_llm_pack_transport_error_keeps_canonical_fallback(llm_pack_case):
    with Fixture('transport-error') as f:
        seed(f)
        f.failure = TimeoutError('authored-transport-primary')
        out = public(f)
        assert f.calls['post'] == 1 and not f.streams
        assert out['success'] is True and out['sources']['llm_refined'] is False
        assert MARKER in out['context'] and FOREIGN_MARKER not in json.dumps(out)
        fmod.assert_original(f)
        assert f.conn.execute('SELECT recall_count FROM claims WHERE id=?', (fmod.CLAIM,)).fetchone()[0] == 1


def test_llm_pack_direct_helper_keyfree_privacy(llm_pack_case):
    with Fixture('private-privacy') as f:
        out = f.p._llm_pack_context('Atlas password=correct-horse-92841',
                                    'Atlas is active; api_key=«redacted:sk-…»', 1200)
        assert out == fmod.REPLY
        assert f.calls['post'] == 1
        outbound = json.dumps(f.posts[0], ensure_ascii=False)
        assert 'correct-horse-92841' not in outbound and '«redacted:sk-…»' not in outbound
        assert 'Atlas' in outbound
        f._mp.setenv('MEMORY_WIKI_LLM_BASE_URL', 'http://192.0.2.10/v1')
        assert f.p._llm_pack_context('Atlas', 'Atlas is active', 1200) == ''
        assert f.calls['post'] == 1


@pytest.mark.parametrize('name', [
    'test_actual_secondary_request_cannot_reconstitute_source_role_delimiters',
    'test_actual_secondary_candidate_cap_retains_complete_original_prefix',
], ids=['role-delimiters', 'candidate-cap'])
def test_llm_pack_original_private_boundary_assertions(llm_pack_case, name):
    with Fixture('private-boundary') as f:
        fmod.legacy_boundary(f, name)
        # The old exact test owns its refusing receiver; no successful reply.
        assert f.calls['post'] == 0 and not f.streams
