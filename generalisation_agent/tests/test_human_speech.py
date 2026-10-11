"""Deterministic Ticket 04 controls. No provider or Freya requests."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.builder.artifacts import digest
from agent.builder.config import Deadline
from agent.builder.runtime import DATE_HELPERS
from agent.builder.scoring import Suite, score
from generalisation_agent.actors import Actor, Observation, SimulatorInvalid, TupleValue, customer_payload
from generalisation_agent.actor_calibration import admitted as actor_admitted
from generalisation_agent.evaluation import grade_case, quality_summary
from generalisation_agent.generation import customers_for, plan_for, sample_policy
from generalisation_agent.models import Behaviour, BehaviourPlan
from generalisation_agent.live import chat_call, public_customer, transcript_quality, require_practice_workflow


@pytest.fixture
def work():
    import shutil, tempfile
    from generalisation_agent.config import ROOT
    (ROOT/'private').mkdir(exist_ok=True)
    path=Path(tempfile.mkdtemp(prefix='test-human-',dir=ROOT/'private'))
    yield path
    shutil.rmtree(path)
    shutil.rmtree(ROOT/'artifacts'/path.name,ignore_errors=True)


class Roles:
    def __init__(self, observations=()):
        self.observations = iter(observations)
        self.calls = []
        self.reject = False
        self.leak = False
    def ask(self, role, purpose, prompt, payload, schema, **kwargs):
        self.calls.append((role,payload))
        if role == 'synthetic_customer_listener':
            observation = next(self.observations)
            return {**observation,'quote':payload['conversation'][-1]['text']}
        if role == 'synthetic_customer':
            act = payload['act']
            values = act['values']
            text = ('Why do you need that?' if act['kind']=='question' else
                    'My appointment is Monday; it costs forty pounds.' if act['kind']=='tangent' else
                    'Goodbye.' if act['hang_up'] else
                    'No further verification.' if act['kind']=='refuse_identity' else
                    ' '.join(str(v) for v in values.values()) or 'Right.')
            if self.leak: text = '0358'
            return {'message':text,'hang_up':act['hang_up']}
        if role == 'synthetic_customer_validator':
            return {'valid':not self.reject,'quote':payload['utterance'],'reason':'authored fake control',
                    'observed':payload['act']['events']}
        raise AssertionError('No unexpected model/provider role '+role)


def customer():
    value = customers_for(sample_policy(42),42,1)[0].model_copy(deep=True)
    value.identity['phone_last4'] = '0358'
    value.plan = BehaviourPlan(events=[])
    return value


def obs(kind, field='', tuples=(), products=()):
    return {'kind':kind,'field':field,'tuples':list(tuples),'products':list(products)}


def speak(actor, text='For security, please continue.'):
    return actor.reply([{'role':'assistant','text':text,'node':'SECRET_GRAPH_NODE'},
                        {'role':'tool','text':'SECRET_LEDGER','name':'bank'}])


def test_fragments_question_resume_preserve_zeros_and_cursor():
    value = customer()
    value.wrong_answers = {'phone_last4':['0134']}
    value.plan = BehaviourPlan(events=[Behaviour(id='B01',kind='fragment',trigger='identity',target='phone_last4'),
                                     Behaviour(id='B02',kind='question',trigger='identity',target='phone_last4')])
    roles = Roles([obs('identity','phone_last4')]*4)
    actor = Actor(roles,value)
    assert speak(actor).message == '01'
    assert actor.state['wrong'] == {}
    assert speak(actor).message == 'Why do you need that?'
    assert actor.state['wrong'] == {}
    assert speak(actor).message == '34'
    assert actor.state['wrong']['phone_last4'] == 1
    assert speak(actor).message == '0358'
    assert actor.state['wrong']['phone_last4'] == 2
    assert actor.quality(True)['coverage'] == {'B01':'observed','B02':'observed'}
    assert value.identity['phone_last4'] == '0358'
    assert all('SECRET_' not in json.dumps(payload) for _,payload in roles.calls)


def test_question_does_not_consume_wrong_answer_or_overwrite_new_field():
    value = customer()
    value.wrong_answers = {'phone_last4':['9999']}
    value.plan = BehaviourPlan(events=[Behaviour(id='B10',kind='question',trigger='identity',target='phone_last4')])
    actor = Actor(Roles([obs('identity','phone_last4'),obs('identity','date_of_birth'),obs('identity','phone_last4')]),value)
    assert speak(actor).message.startswith('Why')
    assert speak(actor).message == value.identity['date_of_birth']
    assert speak(actor).message == '9999'
    assert actor.state['wrong']['date_of_birth']==1 and actor.state['wrong']['phone_last4']==1


def test_terminal_wrong_sequence_never_becomes_helpful_correct_answer():
    value = customer()
    value.identity_terminal = True
    value.wrong_answers = {'phone_last4':['1111','2222']}
    actor = Actor(Roles([obs('identity','phone_last4')]*4),value)
    assert [speak(actor).message for _ in range(4)] == ['1111','2222','No further verification.','No further verification.']


def test_readback_correction_requires_matching_new_tuple_and_is_product_scoped():
    value = customers_for(sample_policy(42),42,10)[7].model_copy(deep=True)
    goal = value.goals[0]
    goal.action='full'
    goal.proposed_amount=value.products[0].balance
    value.plan = BehaviourPlan(events=[Behaviour(id='B05',kind='correction',trigger='readback',target=goal.product_id,
                                                amount=Decimal('100.00'))])
    actor = Actor(Roles(),value)
    original = TupleValue(product_id=goal.product_id,amount=str(goal.proposed_amount),date=str(goal.proposed_date))
    act,state = actor.select(Observation(kind='readback',quote='Confirm',tuples=[original]))
    assert act['kind']=='correction' and state['agreed']=={}
    actor.state=state
    stale,_ = actor.select(Observation(kind='readback',quote='Confirm old',tuples=[original]))
    assert stale['kind']=='counteroffer' and stale['values']['amount']=='100.00'
    corrected=original.model_copy(update={'amount':'100.00'})
    agreed,_=actor.select(Observation(kind='readback',quote='Confirm corrected',tuples=[corrected]))
    assert agreed['kind']=='confirm'
    assert set(state['revisions'])=={goal.product_id}
    assert actor.customer.goals[0].proposed_amount == value.products[0].balance


def test_deferred_acknowledgement_cannot_replay_consent_to_a_changed_readback():
    value = customer()
    value.goals[0].accepts_legal_alternative=False
    value.plan = BehaviourPlan(events=[Behaviour(id='B12',kind='backchannel',trigger='readback')])
    actor=Actor(Roles(),value)
    goal=value.goals[0]
    original=TupleValue(product_id=goal.product_id,amount=str(goal.proposed_amount),date=str(goal.proposed_date))
    act,state=actor.select(Observation(kind='readback',quote='Confirm',tuples=[original]))
    assert act['kind']=='backchannel'
    actor.state=state
    changed=original.model_copy(update={'amount':'1.00'})
    act,state=actor.select(Observation(kind='readback',quote='Changed',tuples=[changed]))
    assert act['kind']=='counteroffer' and not state['agreed']


@pytest.mark.parametrize('utterance',['0358','zero three five eight','03 58','zero three eight'])
def test_fragment_leaks_rejected_even_by_cooperative_validator(utterance):
    actor=Actor(Roles(),customer())
    act={'kind':'fragment_first','values':{'phone_last4':'03'},'events':['B01'],'hang_up':False}
    from generalisation_agent.models import UserReply
    with pytest.raises(SimulatorInvalid):
        actor.validate(UserReply(message=utterance,hang_up=False),act,[])


def test_invalid_realization_repairs_are_bounded_and_do_not_commit_state():
    value=customer()
    value.plan=BehaviourPlan(events=[Behaviour(id='B01',kind='fragment',trigger='identity',target='phone_last4')])
    roles=Roles([obs('identity','phone_last4')]);roles.leak=True
    actor=Actor(roles,value); before=deepcopy(actor.state)
    with pytest.raises(SimulatorInvalid): speak(actor)
    assert actor.state==before and actor.quality(True)['validity']=='invalid'
    assert sum(role=='synthetic_customer' for role,_ in roles.calls)==2
    assert actor.quality(True)['coverage']['B01']=='missed_by_actor'


def test_listener_evidence_and_third_party_knowledge_firewall():
    value=customers_for(sample_policy(42),42,10)[1]
    payload=customer_payload(value)
    assert not {'identity','products','goals','wrong_answers','faults','plan','correction'} & payload.keys()
    actor=Actor(Roles([obs('identity','phone_last4')]),value)
    with pytest.raises(SimulatorInvalid): speak(actor)


def test_date_split_retains_birth_year_and_never_uses_call_year():
    value=customer();value.plan=BehaviourPlan(events=[Behaviour(id='B03',kind='date_split',trigger='identity',target='date_of_birth')])
    actor=Actor(Roles([obs('identity','date_of_birth')]*2),value)
    assert speak(actor).message=='14 March'
    assert actor.state['wrong']=={}
    assert speak(actor).message=='1988'
    assert actor.state['wrong']=={'date_of_birth':1}


def test_matched_release_profiles_fresh_repetitions_and_rotated_coverage():
    planned=set()
    for seed in range(7):
        users=customers_for(sample_policy(42),seed,30,campaign=True)
        assert len(users)==30 and len({c.id for c in users})==30
        for index in range(10):
            a,b,c = [users[index+offset] for offset in (0,10,20)]
            assert a.identity==b.identity==c.identity and a.goals==b.goals==c.goals
            assert a.plan.profile=='baseline' and not a.plan.events
        planned.update(e.id for c in users for e in c.plan.events)
    assert set(f'B{i:02d}' for i in range(1,17)) - planned == {'B06'}
    value=users[20]
    a,b=Actor(Roles(),value,0),Actor(Roles(),value,1)
    a.state['turns']=9
    assert b.state['turns']==0 and b.seed==a.seed+1
    assert a.facts_hash==b.facts_hash
    with pytest.raises(ValueError): customers_for(sample_policy(42),42,30)


def test_actor_unknown_keeps_proven_critical_prefix_failure():
    from generalisation_agent.bank import Bank
    from generalisation_agent.generation import sample_mapping
    policy=sample_policy(42);value=customer();bank=Bank(policy,sample_mapping(),value)
    bank.invoke('get_account',{'customer_id':value.id})
    recording={'ended':'end_call','unknown':[],'ledger':bank.ledger,'turns':[],
               'actor_quality':{'validity':'invalid','coverage':{'B01':'missed_by_actor'}}}
    judge=SimpleNamespace(grade=lambda *args:{'failed':[],'unknown':[],'hard_failures':[]})
    result=grade_case(policy,value,recording,judge)
    assert result['pass'] is False and result['verified_hard_failure'] and result['unknown']
    assert 'audits' not in result['actor_quality']


def test_closed_before_trigger_keeps_original_denominator_and_blocks_pass():
    actor=Actor(Roles(),customer());actor.plan=BehaviourPlan(events=[Behaviour(id='B07',kind='words',trigger='offer')])
    quality=actor.quality('end_call')
    assert quality['coverage']=={'B07':'blocked_by_agent'}
    raw={'all_rows':[[{'id':'one','pass':None,'unknown':['blocked'],'actor_quality':quality}]]}
    assert quality_summary(raw)['original_case_count']==1
    assert not score(raw,Suite(('one',),'fixture','generated',1)).complete


def test_runtime_incomplete_slots_and_product_revision_consent():
    ns={};exec(DATE_HELPERS,ns)
    assert ns['ctl_digits']('zero three five eight')=='0358'
    values={}
    assert not ns['ctl_slot'](values,'phone','03','zero three',False,1)
    assert values['phone']=='' and values['phone_complete']=='no' and values['phone_raw']=='zero three'
    assert ns['ctl_slot'](values,'phone','0358','five eight',True,2)
    card=ns['ctl_proposal'](values,'card','100.05','2028-12-22')
    loan=ns['ctl_proposal'](values,'loan','20','2028-12-22')
    assert ns['ctl_consent'](values,'card',card,True)
    assert ns['ctl_consent'](values,'loan',loan,True)
    assert ns['ctl_write_ready'](values,'card','100.05','2028-12-22')
    changed=ns['ctl_proposal'](values,'loan','21','2028-12-22')
    assert changed!=loan and not ns['ctl_write_ready'](values,'loan','21','2028-12-22')
    assert ns['ctl_write_ready'](values,'card','100.05','2028-12-22')
    assert not ns['ctl_consent'](values,'loan',loan,True)
    assert ns['ctl_consent'](values,'loan',changed,True)
    ns['ctl_proposal'](values,'loan','ambiguous','2028-12-22')
    assert not ns['ctl_write_ready'](values,'loan','21','2028-12-22')
    # A corrected slot overwrites the earlier complete value; a removed key would leave it on the platform.
    assert not ns['ctl_slot'](values,'phone','','er',False,3,correction=True) and values['phone']=='' and values['phone_revision']=='1'
    assert ns['ctl_digits']('double four seven one')=='4471' and ns['ctl_digits']('triple oh five')=='0005'
    assert ns['ctl_digits']('it is four four seven one')=='' and ns['ctl_digits']('four double')==''
    # With the wanted length: a whole number said for "the last four", or a second answer after a first.
    assert ns['ctl_digits']('zero seven seven double zero nine double zero four four seven one',4)=='4471'
    assert ns['ctl_digits']('4471 4472',4)=='4472' and ns['ctl_digits']('four four',4)=='44' and ns['ctl_digits']('0358','4')=='0358'
    # Damaged state is no consent, and no helper raises on it.
    for damaged in ('not json','[1]','{"loan": 5}',None):
        broken={'ctl_proposals':damaged}
        assert not ns['ctl_write_ready'](broken,'loan','21','2028-12-22') and not ns['ctl_consent'](broken,'loan','1',True)
        ns['ctl_invalidate'](broken,'loan')
        assert ns['ctl_proposal'](broken,'loan','21','2028-12-22')=='1' and not ns['ctl_write_ready'](broken,'loan','21','2028-12-22')


def test_actor_admission_needs_separate_controls_and_exact_fingerprint():
    assert not actor_admitted(None,'fingerprint')
    record={'fingerprint':'fingerprint','admitted':True,'controls':[{'passed':True}]*9}
    assert actor_admitted(record,'fingerprint')
    assert not actor_admitted(record,'changed')
    record['controls'][0]={'passed':False}
    assert not actor_admitted(record,'fingerprint')


class ChatAdapter:
    def __init__(self, version=7, failure=False):
        self.deployment={'version':7,'workflow_id':'workflow','workflow_hash':'exact'}
        self.deadline=Deadline(60)
        self.requests=[]; self.failure=failure
        self.client=SimpleNamespace(get_call=lambda cid:{'id':cid,'agentVersionNumber':version,'workflowId':'workflow',
                    'endedReason':'end_call','messages':[{'role':'assistant','message':'Goodbye.'}]})
    def api(self,method,path,body):
        self.requests.append((path,body))
        if path.endswith('/end'): return {}
        if self.failure: raise RuntimeError('504')
        return {'callId':'fresh','response':'Goodbye.'}


def test_full_chat_cleanup_version_and_native_evidence_without_network():
    adapter=ChatAdapter()
    actor=Actor(Roles([obs('goodbye')]),customer())
    result=chat_call(adapter,actor,{'customer_id':'practice'},lambda cid:{'calls':[{'tool':'close_call'}]})
    assert result['cleanup'] and result['ended']=='end_call' and not result['unknown']
    assert adapter.requests[-1]==('/api/v2/chat/end',{'callId':'fresh'})
    assert result['workflow_sha256']=='exact' and result['backend']=='freya_chat_diagnostic'
    adapter=ChatAdapter(version=6)
    result=chat_call(adapter,Actor(Roles([obs('goodbye')]),customer()),{'customer_id':'practice'},lambda cid:{})
    assert any('stale' in error for error in result['unknown']) and result['cleanup']


def test_chat_actor_failure_still_cleans_and_retrieves_ledger():
    class Broken:
        def reply(self,c): raise SimulatorInvalid('invalid customer')
        def quality(self,ended,ledger=None,turns=None): return {'validity':'invalid','coverage':{}}
    adapter=ChatAdapter(); retrieved=[]
    result=chat_call(adapter,Broken(),{'customer_id':'practice'},lambda cid:retrieved.append(cid) or {'calls':[]})
    assert result['cleanup'] and retrieved==['practice'] and result['unknown']


def test_chat_no_callid_or_timeout_is_unknown_and_never_retried():
    adapter=ChatAdapter(failure=True)
    result=chat_call(adapter,Actor(Roles(),customer()),{'customer_id':'practice'},lambda cid:{})
    assert result['unknown'] and not result['cleanup'] and len(adapter.requests)==1


def test_practice_fixture_translation_preserves_intended_wrong_sequence():
    cases=json.loads((Path(__file__).resolve().parents[2]/'public-test-set.json').read_text())
    value=public_customer(next(c for c in cases if c['id']=='PUB-12'),'baseline')
    assert value.wrong_answers=={'phone_last4':['4401']}
    assert [g.action for g in value.goals]==['full','refuse','refuse']
    with pytest.raises(ValueError,match='authored'):
        public_customer(next(c for c in cases if c['id']=='PUB-04'))


def test_persona_prompt_is_not_observed_coverage_and_invented_quote_rejected():
    value=customer();value.plan=BehaviourPlan(events=[Behaviour(id='B07',kind='words',trigger='offer')])
    class Validator:
        def ask(self,*a,**k): return {'valid':True,'errors':[],'observed':[]}
    result=transcript_quality(Validator(),value,[{'role':'user','text':'Right.'}])
    assert result['coverage']=={'B07':'unobserved'}
    class Liar:
        def ask(self,*a,**k): return {'valid':True,'errors':[],'observed':[{'id':'B07','turn':0,'quote':'Invented'}]}
    with pytest.raises(ValueError,match='invented'): transcript_quality(Liar(),value,[{'role':'user','text':'Right.'}])


def test_generated_backend_cannot_be_silently_treated_as_live_practice():
    workflow={'nodes':{'write':{'pre_actions':[{'function':{'handler':'__function__:api_call','parameters':{'properties':{'url':{'default':'https://pack.synthetic.invalid/create_promise'}}}}}]}}}
    with pytest.raises(ValueError,match='unavailable'): require_practice_workflow(workflow,[])


def test_live_cli_rejects_untranslated_cases_before_model_setup(monkeypatch):
    from generalisation_agent.__main__ import main
    monkeypatch.setenv('GENERALISATION_ENABLED','true')
    monkeypatch.setenv('GENERALISATION_USERS','true')
    monkeypatch.setattr('generalisation_agent.packs.model_context',lambda *a,**k:pytest.fail('No provider call'))
    with pytest.raises(SystemExit):
        main(['live','missing.json','--cases','PUB-04','--briefs','briefs/brief-a.md'])


def test_post_consent_correction_only_activates_at_a_real_later_readback():
    value=customer();goal=value.goals[0]
    value.plan=BehaviourPlan(events=[Behaviour(id='B06',kind='correction',trigger='readback',target=goal.product_id,amount=Decimal('100'))])
    item=TupleValue(product_id=goal.product_id,amount=str(goal.proposed_amount),date=str(goal.proposed_date))
    roles=Roles([obs('readback',tuples=[item.model_dump()])]*2)
    actor=Actor(roles,value)
    speak(actor,'Please confirm this exact tuple.')
    assert actor.state['agreed'] and 'B06' not in actor.state['emitted']
    speak(actor,'Before I record it, please confirm again.')
    assert not actor.state['agreed'] and actor.state['revisions'][goal.product_id]['amount']=='100'
    assert actor.quality(True)['coverage']['B06']=='observed'


def test_readback_field_cannot_trigger_correction_without_target_tuple():
    value=customer();goal=value.goals[0]
    value.plan=BehaviourPlan(events=[Behaviour(id='B05',kind='correction',trigger='readback',
                                               target=goal.product_id,amount=Decimal('100'))])
    actor=Actor(Roles(),value)
    act,_=actor.select(Observation(kind='readback',quote='Confirm',field=goal.product_id,tuples=[]))
    assert act['kind']=='neutral' and not actor.eligible


def test_actor_calibration_detects_an_overcooperative_semantic_critic(work):
    from generalisation_agent.actor_calibration import calibrate
    values=customers_for(sample_policy(42),991)
    field=next(k for k,v in values[0].identity.items() if v.isdigit())
    roles=Roles([obs('identity',field)]*3)
    record=calibrate(sample_policy(42),values,roles,Deadline(60),work,'fixture')
    assert not record['admitted']
    assert len(record['controls'])==9
    assert not next(c for c in record['controls'] if c['name']=='role_injection')['passed']


def test_campaign_budget_preflight_never_calls_models(monkeypatch):
    from generalisation_agent.campaign import run_campaign
    monkeypatch.setattr('generalisation_agent.campaign.model_context',lambda *a,**k:pytest.fail('No provider setup'))
    with pytest.raises(ValueError,match='preflight'): run_campaign('missing.json',1800)


def test_invalid_goal_limits_and_correction_targets_rejected():
    from generalisation_agent.models import Customer
    value=customer().model_dump(mode='json')
    value['goals'][0]['maximum_amount']='999999.00'
    with pytest.raises(ValueError,match='Willingness'): Customer.model_validate(value)
    value=customer().model_dump(mode='json')
    value['plan']['events']=[{'id':'B05','kind':'correction','trigger':'readback','target':'phone_last4','amount':'1.00'}]
    with pytest.raises(ValueError,match='product'): Customer.model_validate(value)


def test_runtime_helpers_injected_into_compiled_code_stages():
    from agent.builder.contracts import compile_workflow
    from generalisation_agent.bank import operations_for
    from generalisation_agent.generation import openapi_for, sample_mapping
    from agent.builder.validation import code_errors
    api=openapi_for(sample_policy(42),sample_mapping(),'helper-injection')
    source={'initial_node':'check','nodes':{'check':{'node_type':'code','code':"try:\n vars['ready'] = ctl_digits('zero three')\nexcept Exception:\n vars['ready'] = ''",'transitions':[{'target_node':'end','condition':{'operator':'always'}}]},'end':{'node_type':'end_call'}}}
    workflow,_=compile_workflow(source,{'operations':operations_for(api)})
    code=workflow['nodes']['check']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
    assert 'def ctl_digits' in code and not code_errors(code)


def test_failed_call_feedback_never_exposes_customer_agendas(work):
    from agent.builder.artifacts import write_json
    from agent.builder.build import call_records
    write_json(work/'calls_0.json',{'case':{'turns':[{'role':'user','text':'0358','node':'security'}],
                                        'actor_quality':{'plan':'SEALED_GOAL','audits':'PRIVATE_VALIDATOR_INPUT'}}})
    failed,visited=call_records(work,{'all_rows':[[{'id':'case','pass':False}]]})
    assert 'SEALED_GOAL' not in json.dumps(failed) and 'PRIVATE_VALIDATOR_INPUT' not in json.dumps(failed)
    assert failed['case']['turns'][0]['text']=='0358' and visited=={'case':{'security'}}


def test_uncertain_or_invalid_extraction_clears_date_and_completeness_provenance():
    from generalisation_agent.runner import Runner
    runner=Runner.__new__(Runner)
    runner.variables={'day':'2028-12-22','day_said':'Friday','day_iso':'2028-12-22','day_complete':'yes','amount':'20'}
    runner.clear_extracted('day')
    assert runner.variables=={'day_complete':'no','amount':'20'}


class CompiledPartnerRoles(Roles):
    """Authored varying partner/extractor; executes the adaptive actor on compiled nodes."""
    def __init__(self,value,policy):
        super().__init__()
        self.value,self.policy=value,policy
    def ask(self,role,purpose,prompt,payload,schema,**kwargs):
        if role=='synthetic_customer_listener':
            text=payload['conversation'][-1]['text']
            if 'May I speak' in text: value=obs('greeting')
            elif 'Goodbye' in text: value=obs('goodbye')
            elif 'Please confirm' in text:
                goal=self.value.goals[0]
                value=obs('readback',tuples=[{'product_id':goal.product_id,'amount':str(goal.proposed_amount),'date':str(goal.proposed_date)}])
            else:
                field=next(f.name for f in self.policy.identity if f.name in text)
                value=obs('identity',field)
            return {**value,'quote':text}
        if role=='synthetic_customer' and payload['act']['kind']=='confirm':
            return {'message':'Yes, please record that exact promise.','hang_up':False}
        if role=='proxy_extractor':
            item=payload['schema'][0]; name=item['name']
            history=payload['conversation']; last=history[-1]
            question=next((t['text'] for t in reversed(history) if t['role']=='assistant'),'')
            result={}
            uncertain=[]
            if last['role']=='user' and last['text']!='Hello?':
                if name=='present' and 'May I speak' in question: result[name]='yes'
                elif name=='confirmed' and 'Please confirm' in question and last['text'].startswith('Yes'): result[name]='yes'
                elif name=='bye' and 'Goodbye' in question: result[name]=last['text']
                elif name.startswith('answer'):
                    field=self.policy.identity[int(name[-1])].name
                    if field in question:
                        users=[t['text'] for t in history if t['role']=='user' and t.get('node')=='ask'+name[-1]]
                        text=''.join(t for t in users if t.isdigit()) if field=='phone_last4' else last['text']
                        if field=='phone_last4' and len(text)!=4: uncertain=[name]
                        elif not last['text'].endswith('?'): result[name]=text
            return {'values':result,'uncertain':uncertain}
        if role=='proxy_dialogue':
            last=next(t for t in reversed(payload['conversation']) if t['role']=='assistant')['text']
            field=next(f.name for f in self.policy.identity if f.name in last)
            return {'message':f'To protect your account, please continue your {field}.','tool_calls':[],'transition':None}
        return super().ask(role,purpose,prompt,payload,schema,**kwargs)


def compiled_fragment_call(code=None):
    from generalisation_agent.calibration import control_workflow
    from generalisation_agent.generation import openapi_for,sample_mapping
    from generalisation_agent.bank import operations_for
    from generalisation_agent.runner import Runner
    policy=sample_policy(42); mapping=sample_mapping();value=customer()
    value.plan=BehaviourPlan(events=[Behaviour(id='B01',kind='fragment',trigger='identity',target='phone_last4'),
                                     Behaviour(id='B02',kind='question',trigger='identity',target='phone_last4')])
    api=openapi_for(policy,mapping,'compiled-human')
    workflow,_=control_workflow(policy,mapping,value,{'operations':operations_for(api)})
    recording=Runner(workflow,policy,mapping,value,CompiledPartnerRoles(value,policy),Deadline(90),api,code=code).run()
    return policy,value,recording


def test_actual_compiled_graph_fragment_question_bank_closure():
    # This authored control has no Python stage/hooks; code execution would be an error.
    class NoCode:
        def run(self,*a,**k): raise AssertionError('No unexpected code stage')
    policy,value,recording=compiled_fragment_call(NoCode())
    from generalisation_agent.oracle import grade_ledger
    assert recording['ended']=='end_call' and not recording['unknown']
    assert grade_ledger(policy,value,recording['ledger'])['ledger_pass']
    calls=recording['ledger']['calls']
    phone=next(c for c in calls if c['tool']=='verify_identity' and c['args']['field']=='phone_last4')
    assert phone['args']['answer']=='0358'
    assert [t['text'] for t in recording['turns'] if t['role']=='user' and t.get('node')=='ask1']==['03','Why do you need that?','58']
    assert calls[-1]['tool']=='close_call' and len(recording['ledger']['promises'])==1
    assert recording['actor_quality']['coverage']=={'B01':'observed','B02':'observed'}


def test_human_review_requires_two_reviewers_and_zero_consent_violations(work):
    from generalisation_agent.quality import Review, review_quality
    from agent.builder.artifacts import write_json
    samples=[]
    for index in range(30):
        profile=('baseline','ordinary','stress')[index%3]
        backend='local_proxy' if index%2 else 'freya_chat_diagnostic'
        split='development' if index<15 else 'holdout'
        value={'backend':backend,'profile':profile,'split':split,'turns':[{'role':'user','text':f'Fictional sample {index}'}]}
        path=work/f'sample-{index}.json';write_json(path,value)
        samples.append({'recording':str(path),'sha256':digest(value),'profile':profile,'backend':backend,'split':split,
                        'ratings':[{'reviewer':person,'plausible':True,'responsive':True,'facts_correct':True,'consent_correct':True} for person in ('one','two')]})
    path=work/'review.json';write_json(path,{'samples':samples})
    assert review_quality(path)['accepted']
    data={'samples':deepcopy(samples)}
    data['samples'][0]['ratings'][1]['reviewer']='one'
    with pytest.raises(ValueError,match='independent'): Review.model_validate(data)
    # Immutable report identity prevents overwriting a prior release; use a separate test run.
    data={'samples':deepcopy(samples)};data['samples'][0]['ratings'][0]['consent_correct']=False
    review=Review.model_validate(data)
    assert any(not r.consent_correct for sample in review.samples for r in sample.ratings)
    original=json.loads((work/'sample-0.json').read_text());original['turns']=[];write_json(work/'sample-0.json',original)
    with pytest.raises(ValueError,match='changed'): review_quality(path)


def test_three_repetitions_use_fresh_actors_and_missing_quality_never_passes(work):
    from generalisation_agent.evaluation import evaluate_workflow
    from generalisation_agent.generation import sample_mapping
    from generalisation_agent.calibration import fixtures
    policy=sample_policy(42);mapping=sample_mapping();value=customer();value.plan=BehaviourPlan(profile='baseline',events=[])
    _,_,recording,_,_=fixtures(policy,mapping,None)[0]
    seen=[]
    class Runner:
        def __init__(self,*a,**k): seen.append(k['repetition'])
        def run(self): return deepcopy(recording)
    roles=SimpleNamespace(cfg=SimpleNamespace(builder_model='fixture',models={'hard':'fixture'}))
    judge=SimpleNamespace(grade=lambda *a:{'failed':[],'unknown':[],'hard_failures':[]})
    report,raw=evaluate_workflow({'nodes':{}},policy,mapping,[value],roles,Deadline(60),work/'evaluation',3,runner_factory=Runner,judge=judge)
    assert seen==[0,1,2]
    assert not report['score']['complete'] and report['score']['passed']==0
    assert all('Actor quality evidence missing' in rows[0]['unknown'] for rows in raw['all_rows'])


def test_campaign_manifests_freeze_composed_plans_and_detect_plan_tampering(work):
    from generalisation_agent.tests.test_foundation import Roles as Renderer
    from generalisation_agent.config import Settings
    from generalisation_agent.packs import generate_packs,load_pack
    from agent.builder.artifacts import write_json
    top=generate_packs(Settings(True),Renderer(),work,users=30,campaign=True)
    manifest=json.loads(top.read_text())
    assert sum(p['case_count'] for p in manifest['packs'])==60
    for pack in manifest['packs']:
        assert pack['campaign'] and pack['profiles']==['baseline','ordinary','stress']
        loaded=load_pack(Path(pack['brief']).parent/'manifest.json')
        assert len(loaded[3])==30 and pack['behaviour_plan_sha256']==digest([c.plan.model_dump(mode='json') for c in loaded[3]])
    pack=manifest['packs'][0];path=Path(pack['brief']).parent/'manifest.json'
    pack['behaviour_plan_sha256']='tampered'
    write_json(path,pack)
    with pytest.raises(ValueError,match='changed'): load_pack(path)


@pytest.mark.parametrize('words, expected',[
    ('14 March',''),('nineteen eighty eight',''),('14 March 1988','1988-03-14'),
    ('the fourteenth of March nineteen eighty eight','1988-03-14'),
    ('14 March one nine eight eight','1988-03-14'),('1988-03-14','1988-03-14'),
    ('31 February 1988',''),('14 March 1988 or 1989',''),
    # Short month names are read as ctl_date reads them; the words of a year are never taken for a day.
    ('14 Mar 1988','1988-03-14'),('March fourteenth, nineteen eighty eight','1988-03-14'),
    ('March nineteen eighty eight',''),('March 1988',''),('my date of birth is the 14th of March 1988','1988-03-14'),
    # A second answer after a rejected one, or a correction: the latest complete date is the answer.
    ('12 July 1991 21 August 1992','1992-08-21'),('12 July 1991 no sorry 12 June 1991','1991-06-12'),
    ('4 March 1988 the third of April nineteen eighty eight','1988-04-03'),('1991-07-12 1992-08-21','1992-08-21'),
    ('12 July 1991 21 August',''),
])
def test_identity_date_never_defaults_or_guesses_birth_year(words,expected):
    namespace={};exec(DATE_HELPERS,namespace)
    assert namespace['ctl_identity_date'](words)==expected


def test_question_then_fragment_composition_advances_answer_once():
    value=customer();value.plan=BehaviourPlan(events=[Behaviour(id='B10',kind='question',trigger='identity',target='phone_last4'),
                                                     Behaviour(id='B01',kind='fragment',trigger='identity',target='phone_last4')])
    actor=Actor(Roles([obs('identity','phone_last4')]*3),value)
    assert [speak(actor).message for _ in range(3)]==['Why do you need that?','03','58']
    assert actor.state['wrong']=={'phone_last4':1}


def test_terminal_identity_and_nonpay_plans_do_not_require_unreachable_negotiation():
    users=customers_for(sample_policy(42),4200,30,campaign=True)
    for value in users:
        if value.identity_terminal:
            assert all(e.trigger=='identity' for e in value.plan.events)
        if value.plan.profile=='ordinary' and (value.transfer or all(g.action not in {'full','floor'} for g in value.goals)) and not value.third_party:
            assert all(e.trigger=='identity' for e in value.plan.events)


def test_released_calibration_quality_summary_excludes_private_evidence():
    from generalisation_agent.evaluation import calibration_summary
    result=calibration_summary({'fingerprint':'f','admitted':True,'controls':[{'quote':'PRIVATE_SECURITY_VALUE'}],
                                'actor':{'admitted':True,'controls':[{'act':'PRIVATE_AGENDA'}],'error':'PRIVATE_PATH'}})
    assert result['actor_admitted'] and result['oracle_control_count']==1
    assert 'PRIVATE_' not in json.dumps(result)


def test_persona_diagnostics_support_all_original_scripts_without_oracle_leak():
    from generalisation_agent.live import persona_knowledge
    cases=json.loads((Path(__file__).resolve().parents[2]/'public-test-set.json').read_text())
    for case in cases:
        value=public_customer(case,'stress',0,persona_only=True)
        knowledge=persona_knowledge(case)
        assert value.situation==case['script']
        assert 'expected' not in knowledge and 'checks' not in knowledge
        if value.third_party: assert 'identity' not in knowledge and 'products' not in knowledge


def test_live_policy_judges_disagree_unknown_and_cannot_fabricate_evidence():
    from generalisation_agent.live import transcript_checks, practice_prefix_failures
    cases=json.loads((Path(__file__).resolve().parents[2]/'public-test-set.json').read_text())
    class Judges:
        def ask(self,role,purpose,prompt,payload,schema,**kwargs):
            assert 'policy_sources' in payload and 'expected' not in payload
            return {'checks':[{'index':index,'verdict':'pass' if role=='synthetic_live_judge' else 'unknown',
                              'turn':0,'quote':'Hello'} for index in range(len(payload['checks']))]}
    result=transcript_checks(Judges(),cases[0],[{'role':'assistant','text':'Hello'}])
    assert result['unknown'] and not result['failed']
    class Liar:
        def ask(self,*a,**kwargs):
            payload=a[3]
            return {'checks':[{'index':index,'verdict':'pass','turn':0,'quote':'Fabricated'} for index in range(len(payload['checks']))]}
    with pytest.raises(ValueError,match='invented'): transcript_checks(Liar(),cases[0],[{'role':'assistant','text':'Hello'}])
    assert practice_prefix_failures(cases[0],{'calls':[{'tool':'get_account','result':{'error':'identity not verified'}}]})


def test_birth_year_can_be_worded_but_cannot_leak_in_first_fragment():
    from generalisation_agent.models import UserReply
    actor=Actor(Roles(),customer())
    first={'kind':'fragment_first','values':{'date_of_birth':'14 March'},'date_fragment':True,'split_year':'1988','events':['B03'],'hang_up':False}
    with pytest.raises(SimulatorInvalid,match='year'):
        actor.validate(UserReply(message='14 March nineteen eighty eight',hang_up=False),first,[])
    rest={'kind':'fragment_rest','values':{'date_of_birth':'1988'},'date_fragment':True,'split_year':'1988','events':[],'hang_up':False}
    assert actor.validate(UserReply(message='nineteen eighty eight',hang_up=False),rest,[]).valid


def test_release_campaign_uses_both_exact_exports_thirty_users_and_three_runs(monkeypatch,work):
    import shutil
    from generalisation_agent import campaign
    from generalisation_agent.tests.test_foundation import Roles as Renderer
    from generalisation_agent.config import ROOT,Settings
    from generalisation_agent.packs import generate_packs
    from agent.builder.artifacts import write_json
    top=generate_packs(Settings(True),Renderer(),work,users=30,campaign=True)
    exports=[]
    for index in range(2):
        workflow={'nodes':{'end':{'node_type':'end_call'}},'initial_node':'end','fixture':index}
        path=work/f'export-{index}.json';write_json(path,{'workflow':workflow})
        exports.append({'export_path':str(path),'workflow_sha256':digest(workflow)})
    write_json(top.parent/'rehearsal.json',{'source_fingerprint':campaign.source_fingerprint(),'results':exports})
    run_root=work/(work.name+'-campaign');run_root.mkdir()
    trace=SimpleNamespace(close=lambda **kwargs:None)
    monkeypatch.setattr(campaign,'model_context',lambda **kwargs:(SimpleNamespace(),trace,Deadline(kwargs['seconds']),run_root))
    monkeypatch.setattr('generalisation_agent.calibration.calibrate',lambda *args:{'admitted':True})
    seen=[]
    def measure(workflow,policy,mapping,customers,roles,deadline,root,repetitions,**kwargs):
        seen.append((digest(workflow),len(customers),repetitions,kwargs['split']))
        return {'score':{'complete':True},'selection_eligible':True},{}
    monkeypatch.setattr(campaign,'evaluate_workflow',measure)
    try:
        result=campaign.run_campaign(top,21600)
        assert seen==[(exports[0]['workflow_sha256'],30,3,'development'),(exports[1]['workflow_sha256'],30,3,'holdout')]
        assert result['complete'] and not result['release_accepted']
        report=json.loads(Path(result['report']).read_text())
        assert 'live parity' in report['pending'] and not report['build_budget_includes_campaign']
    finally:
        shutil.rmtree(ROOT/'artifacts'/run_root.name,ignore_errors=True)


def test_private_review_samples_bind_strata_and_recording_hash(work):
    from generalisation_agent.quality import save_sample
    value={'turns':[{'role':'user','text':'Fictional customer'}]}
    sample=save_sample(work,'SYN_fixture',2,value,'stress','holdout','local_proxy')
    saved=json.loads(Path(sample['recording']).read_text())
    assert sample['sha256']==digest(saved) and saved['split']=='holdout'
    with pytest.raises(ValueError): save_sample(work,'../escape',0,value,'stress','holdout','local_proxy')


def test_digital_question_and_tangent_facts_are_explicit_controlled_acts():
    value=customer();value.plan=BehaviourPlan(events=[Behaviour(id='B10',kind='question',trigger='identity',question_topic='digital')])
    actor=Actor(Roles(),value)
    act,state=actor.select(Observation(kind='identity',quote='Security?',field='phone_last4'))
    assert 'digital assistant' in act['instruction'] and state['wrong']=={}
    value.plan=plan_for(value,2)
    event=value.plan.events[0]
    assert event.kind=='tangent' and event.amount==Decimal('17.40') and event.day
    act,_=Actor(Roles(),value).select(Observation(kind='identity',quote='Security?',field='phone_last4'))
    assert act['values']=={'appointment_date':event.day.isoformat(),'unrelated_amount':'17.40'}
