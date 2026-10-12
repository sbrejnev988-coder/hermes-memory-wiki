"""Direct native-SPI fixture for MemoryDiff lexical false confirmation.

Authored, credential-free synthetic facts; no source of real user claims.
"""
import json
import os
from pathlib import Path

import pytest
import memory_wiki as wiki

OUT=Path(os.environ['RECOVERY_DIAGNOSTIC_OUT'])

@pytest.fixture(scope='module')
def provider():
    p=wiki.MemoryWikiProvider()
    p.initialize('synthetic-diff-polarity',hermes_home=str(OUT/'home'),agent_context='test',bot_id='synthetic-diff-bot',project_id='synthetic-diff')
    assert p.db_path.resolve().is_relative_to(OUT.resolve())
    assert p.__class__.__bases__ == (wiki.MemoryProvider,)
    yield p
    p._shutdown_lifecycle(render=False)
    assert p._conn is None and p._owned_conn is None

def seed(provider,text,index):
    c=provider._connect();cid='diff-polarity-'+str(index)
    with provider._claim_transaction(c):
        c.execute("INSERT INTO claims(id,hash,claim,normalized_claim,topic,type,scope,visibility_scope,status,risk,quality,trust_class,confidence,salience,freshness_at,updated_at,created_at) VALUES(?,?,?,?,?,?,'global','global','active','low',1,'fact',0.9,0.9,?,?,?)",(cid,wiki.sha(cid),text,text,'synthetic-diff','fact',wiki.now(),wiki.now(),wiki.now()))
    row=dict(c.execute('SELECT * FROM claims WHERE id=?',(cid,)).fetchone())
    assert provider._claim_visible(row)
    return row

CASES=[
 ('Mira одобряет, Lev не одобряет.','Mira не одобряет, Lev одобряет.',False),
 ('Mira approves the plan, Lev does not approve it.','Mira does not approve the plan, Lev approves it.',False),
 ('Alice follows Bob.','Bob follows Alice.',False),
 ('I prefer Go, Li prefers Python.','Li prefers Go, I prefer Python.',False),
 ('Mira does not approve PlanA; Lev approves PlanB.','Mira approves PlanA; Lev does not approve PlanB.',False),
 ('Mira approves the plan.','Mira approves the plan.',True),
 ('Mira одобряет план.','  mira  одобряет  план.  ',True),
 ('Service atlas listens on port 443.','Service atlas listens on port 443.',True),
 ('Mira does not approve the plan.','Mira does not approve the plan.',True),
 ('Mira не одобряет PlanA, Lev одобряет PlanB.','Mira не одобряет PlanA, Lev одобряет PlanB.',True),
 ('Mira approves, not Lev.','Mira approves not, Lev.',False),
 ('Mira не только одобряет план.','Mira не только одобряет план.',True),
 ('Mira approves the plan.','Mira approves the plan',True),
 ('Mira approves PlanA. Lev approves PlanB.','Lev approves PlanB. Mira approves PlanA.',False),
]
@pytest.mark.parametrize('memory,current,confirmed',CASES)
def test_direct_diff_polarity(provider,memory,current,confirmed):
    idx=CASES.index((memory,current,confirmed));row=seed(provider,memory,idx)
    result=provider._memory_diff('synthetic-diff',verified_facts=[current],preselected_rows=[row])
    assert len(result['remembered'])==1, {
        'row_safe': provider._model_safe_row(row) is not None,
        'guard_refused_fields':[(key,decision['status']) for key,value in row.items() if isinstance(value,str) and value for decision in [provider._inspect_recall_text(value,source='memory_wiki:'+key,mem_type='claim',audit=False,max_len=len(value))] if decision['status']!='safe' or (key in {'id','project_id','visibility_scope','origin_bot_id','origin_session_id','origin_chat_hash'} and decision.get('content')!=value)],
    }
    assert [x['claim_id'] for x in result['confirmed']] == ([row['id']] if confirmed else [])
    if not confirmed:
        assert len(result['changed_or_conflicting'])==1
        assert result['changed_or_conflicting'][0]['claim_id']==row['id']
        assert result['changed_or_conflicting'][0]['kind'] in ('conflict','related_changed_or_needs_review')
        assert 'Prefer verified_now' in result['answer_basis']
    assert result['verified_now']
    assert provider._transaction_quarantine is None and provider._lifecycle_state=='ready'
