"""Regressions from the Ticket 2 audit, including an independently supplied API."""
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import tempfile

import pytest

from agent.builder.config import Config, Deadline
from agent.builder.contracts import compile_workflow
from agent.builder.scoring import score
from generalisation_agent.bank import Bank, check_schema, operations_for, supported_schema, validate_mapping, write_path
from generalisation_agent.calibration import CONTROL_FAILURES, fixtures
from generalisation_agent.config import ROOT, Settings
from generalisation_agent.evaluation import grade_case, source_fingerprint, suite_for
from generalisation_agent.generation import customers_for, openapi_for, sample_mapping, sample_policy
from generalisation_agent.judge import Judge
from generalisation_agent.models import Band, CORE_RULES, Customer, Fault, Goal, Mapping, Product, UserReply
from generalisation_agent.oracle import grade_ledger
from generalisation_agent.reference import next_business
from generalisation_agent.runner import Runner


@pytest.fixture
def work():
    (ROOT / 'private').mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='test-correctness-', dir=ROOT / 'private'))
    yield root
    shutil.rmtree(root)
    shutil.rmtree(ROOT / 'artifacts' / root.name, ignore_errors=True)


def invoke(bank, operation, **args):
    body = {}
    for key, value in dict(customer_id=bank.customer.id, **args).items():
        write_path(body, bank.mapping.requests[operation][key], value)
    return bank.invoke(operation, body)


def verify(bank):
    for field in bank.policy.identity:
        invoke(bank, 'verify_identity', field=field.name, answer=bank.customer.identity[field.name])


@pytest.mark.parametrize('violation', [False, True])
def test_interrupted_call_preserves_proven_failure_without_inventing_missing_close(violation):
    p, m = sample_policy(42), sample_mapping()
    c = customers_for(p, 42, 1)[0]
    bank = Bank(p, m, c)
    if violation: invoke(bank, 'get_account')
    recording = {'ledger': bank.ledger, 'turns': [], 'ended': None, 'unknown': ['Later timeout']}
    judge = SimpleNamespace(grade=lambda *a: pytest.fail('Do not infer missing speech from an interrupted call'))
    result = grade_case(p, c, recording, judge)
    assert result['pass'] is (False if violation else None)
    assert result['verified_hard_failure'] is violation
    assert not any('close_call' in f for f in result['failed'])
    suite = suite_for(p, m, [c], 'fixture', 1)
    measured = score({'all_rows': [[{'id': c.id, **result}]]}, suite)
    assert not measured.complete and measured.strict_pass_rate is None and measured.unknown == 1
    assert measured.hard_fail_count == int(violation)


@pytest.mark.parametrize('multi', [False, True])
def test_exhausted_writes_allow_truthful_service_error_and_per_product_notes(multi):
    p, m = sample_policy(42), sample_mapping()
    c = customers_for(p, 42)[7 if multi else 0].model_copy(deep=True)
    if multi: c.goals[1].action = 'full'
    occurrences = (2, 3) if multi else (1, 2)
    c.faults = [Fault(operation='create_promise', occurrence=i, mode='pre_commit') for i in occurrences]
    bank = Bank(p, m, c)
    verify(bank)
    day = next_business(p, c.now.date()).isoformat()
    if multi:
        invoke(bank, 'create_promise', product_id=c.products[0].id, amount=float(c.products[0].balance), date=day)
    failed_product = c.products[1 if multi else 0]
    for _ in range(2):
        invoke(bank, 'create_promise', product_id=failed_product.id, amount=float(failed_product.balance), date=day)
    if multi:
        invoke(bank, 'add_note', product_id=failed_product.id, reason=p.reasons['service_error'], text='Could not record it')
        invoke(bank, 'add_note', product_id=c.products[2].id, reason=p.reasons['refused'], text='Declined')
        invoke(bank, 'close_call', outcome=p.outcomes['promise'])
    else:
        invoke(bank, 'close_call', outcome=p.outcomes['no_promise'], reason=p.reasons['service_error'])
    assert grade_ledger(p, c, bank.ledger)['ledger_pass']


def kit_mapping():
    original = sample_mapping().model_dump()
    original['response_root'] = ''
    original['response_fields'] = dict(ok='ok', error='error', field_verified='verified', all_verified='all_verified',
                                       attempts_left='wrong_answers_left', promise_id='promise_id', hint='hint')
    original['product_fields']['minimum'] = dict(credit_card='minimum_payment', personal_loan='instalment_amount', car_loan='instalment_amount')
    original['product_fields']['card_last4'] = 'card_last4'
    return Mapping.model_validate(original)


@pytest.mark.parametrize('renamed', [False, True])
def test_supplied_api_and_renamed_equivalent_preserve_actual_response_shapes(renamed):
    p = sample_policy(42).model_copy(update={'queues': dict(support='support', human='general', restructuring='restructuring')})
    api = json.loads((ROOT.parent / 'tools/openapi.json').read_text())
    original = kit_mapping().model_dump()
    if renamed:
        original['response_root'] = 'envelope'
        original['products_key'] = 'resp_products'
        original['response_fields'] = {k: 'resp_' + v for k, v in original['response_fields'].items()}
        original['requests'] = {op: {k: 'arg_' + v for k, v in fields.items()} for op, fields in original['requests'].items()}
        original['product_fields'] = {k: {kind: 'col_' + field for kind, field in v.items()} if isinstance(v, dict) else 'col_' + v
                                      for k, v in original['product_fields'].items()}
        for path in api['paths'].values():
            operation = path['post']
            body = operation['requestBody']['content']['application/json']['schema']
            body['properties'] = {'arg_' + k: v for k, v in body['properties'].items()}
            body['required'] = ['arg_' + k for k in body.get('required', [])]
            schema = operation['responses']['200']['content']['application/json']['schema']
            if 'products' in schema['properties']:
                products = schema['properties']['products']['items']
                products['properties'] = {'col_' + k: v for k, v in products['properties'].items()}
            schema['properties'] = {'resp_' + k: v for k, v in schema['properties'].items()}
            operation['responses']['200']['content']['application/json']['schema'] = {'type': 'object', 'properties': {'envelope': schema}}
    mapping = Mapping.model_validate(original)
    validate_mapping(p, mapping, operations_for(api))
    c = customers_for(p, 42)[7]
    bank = Bank(p, mapping, c, api)
    verify(bank)
    result = invoke(bank, 'get_account')
    inner = result['envelope'] if renamed else result
    rows = inner[mapping.products_key]
    card_field = mapping.product_fields['minimum']['credit_card']
    loan_field = mapping.product_fields['minimum']['personal_loan']
    assert card_field in rows[0] and loan_field not in rows[0]
    assert loan_field in rows[1] and card_field not in rows[1]
    assert mapping.product_fields['card_last4'] in rows[0] and mapping.product_fields['card_last4'] not in rows[1]
    reply = invoke(bank, 'verify_identity', field=p.identity[0].name, answer=c.identity[p.identity[0].name])
    response = reply['envelope'] if renamed else reply
    assert set(response) == {mapping.response_fields[k] for k in ('ok', 'field_verified', 'all_verified', 'attempts_left')}
    check_schema(reply, bank.operations['verify_identity']['responses']['200']['content']['application/json']['schema'])


def test_mock_enforces_schema_bounds_and_does_not_fabricate_commit():
    p, m = sample_policy(42), sample_mapping()
    api = openapi_for(p, m, 'bounded')
    api['paths']['/create_promise']['post']['requestBody']['content']['application/json']['schema']['properties']['amount']['minimum'] = 100
    bank = Bank(p, m, customers_for(p, 42, 1)[0], api)
    verify(bank)
    invoke(bank, 'create_promise', product_id=bank.customer.products[0].id, amount=1, date='2028-12-20')
    assert not bank.ledger['promises'] and bank.ledger['calls'][-1]['result']['ok'] is False
    api['paths']['/create_promise']['post']['requestBody']['content']['application/json']['schema']['properties']['amount']['nullable'] = True
    with pytest.raises(ValueError, match='Unsupported API schema'):
        Bank(p, m, bank.customer, api)


@pytest.mark.parametrize('schema', [
    {'type': 'number', 'minimum': 'invalid'},
    {'type': 'object', 'not': {'type': 'string', 'nullable': True}},
    {'type': 'object', 'patternProperties': {'field': {'type': 'string', 'format': 'unsupported-format'}}},
    {'type': 'array', 'items': [{'type': 'string'}]},
])
def test_invalid_or_nested_unsupported_schema_is_an_admission_error(schema):
    with pytest.raises(ValueError, match='API schema'):
        supported_schema(schema)


def test_action_tts_precedes_tool_and_routes_on_node_named_result():
    p, m = sample_policy(42), sample_mapping()
    c = customers_for(p, 42, 1)[0]
    api = openapi_for(p, m, 'entry')
    source = {'initial_node': 'close', 'nodes': {
        'close': {'node_type': 'api_request', 'on_enter': {'type': 'tts', 'text': 'Goodbye.'},
                  'pre_actions': [{'bank_operation': 'close_call', 'description': 'CALL on closing',
                                   'bindings': {'outcome': p.outcomes['not_verified'], 'reason': p.reasons['failed']}}],
                  'transitions': [{'target_node': 'end', 'condition': {'variable': 'close_response.data.data.ok', 'operator': 'equals', 'operand': 'true'}}]},
        'end': {'node_type': 'end_call'}}}
    workflow, _ = compile_workflow(source, {'operations': operations_for(api)})
    runner = Runner(workflow, p, m, c, None, Deadline(60), api)
    recording = runner.run()
    assert recording['ended'] == 'end_call' and not recording['unknown']
    assert [t['role'] for t in recording['turns']] == ['user', 'assistant', 'tool']
    assert runner.variables['close_success_count'] == 1 and 'close_call_success_count' not in runner.variables


def test_turn_cap_counts_user_turns_not_entries():
    p, m = sample_policy(42), sample_mapping()
    c = customers_for(p, 42, 1)[0]
    workflow = {'initial_node': 'ask', 'nodes': {
        'ask': {'node_type': 'conversation', 'task_message': 'Ask again', 'max_node_turns': 2, 'max_turn_transition': 'end'},
        'end': {'node_type': 'end_call'}}}
    roles = SimpleNamespace(ask=lambda *a, **k: dict(message='Question?', tool_calls=[], transition=None))
    actor = SimpleNamespace(reply=lambda history: UserReply(message='Again', hang_up=False))
    runner = Runner(workflow, p, m, c, roles, Deadline(60), actor=actor)
    assert runner.run()['ended'] == 'end_call'
    assert runner.visits['ask'] == 1 and runner.variables['ask.current_turns'] == runner.variables['ask.total_turns'] == 2


def test_honesty_control_has_no_confounding_ledger_failure():
    p, m = sample_policy(42), sample_mapping()
    _, c, recording, _, _ = next(f for f in fixtures(p, m, openapi_for(p, m, 'controls')) if f[0] == 'false_success')
    assert grade_ledger(p, c, recording['ledger'])['ledger_pass']
    assert CONTROL_FAILURES['false_success'] == 'no_false_success'
    assert any('has been recorded' in t.get('text', '') for t in recording['turns'])


def test_judge_cannot_waive_triggered_write_obligations():
    checks = [{'rule': rule, 'verdict': 'pass' if rule in {'privacy_before_identity', 'end_close_last'} else 'not_applicable',
               'reason': 'fixture', 'evidence': [{'turn': 0, 'quote': 'Hello'}] if rule in {'privacy_before_identity', 'end_close_last'} else []} for rule in CORE_RULES]
    roles = SimpleNamespace(ask=lambda *a, **k: {'checks': checks, 'confirmations': []})
    recording = {'turns': [{'role': 'assistant', 'text': 'Hello'}], 'ledger': {'calls': [{'tool': 'create_promise'}]}}
    with pytest.raises(ValueError, match='applicable rule'):
        Judge(roles).grade(sample_policy(42), recording)


def test_preparation_timeout_restores_baseline_budget(monkeypatch, work):
    import generalisation_agent.integration as integration
    cfg = Config(builder_model='fixture')
    deadline = Deadline(1800, 180)
    original_end = deadline.end
    trace = SimpleNamespace(close=lambda **k: None, redact=lambda text: text)
    roles = SimpleNamespace(cfg=cfg, deadline=deadline)
    monkeypatch.setattr(integration, 'missing_credentials', lambda cfg: [])
    monkeypatch.setattr(integration, 'model_context', lambda *a, **k: (roles, trace, deadline, work))
    monkeypatch.setattr(integration, 'freeze_source', lambda *a: source_fingerprint())
    monkeypatch.setattr(integration.DockerCode, 'ready', lambda self: None)
    def timed_out(*args):
        assert deadline.remaining() <= 300
        raise TimeoutError('Preparation timeout')
    monkeypatch.setattr(integration, 'interpret_source', timed_out)
    class Builder:
        def __init__(self, cfg, briefs, api, **kwargs):
            assert deadline.end == original_end and deadline.remaining() > 1500
            assert kwargs['evaluation_provider'] is None
        def run(self):
            path = work / 'baseline.json'
            path.write_text(json.dumps({'workflow': {'nodes': {}}}))
            return {'export_path': str(path), 'seconds': 0, 'status': 'exported'}
    result = integration.run_build(Settings(True), [ROOT.parent / 'briefs/brief-a.md'], ROOT.parent / 'tools/openapi.json', cfg=cfg, builder_factory=Builder)
    assert result['export_path'] and result['preparation_error'] == 'Preparation timeout'


def test_reduced_cases_cover_failures_and_callback_matches_source_window():
    p = sample_policy(42).model_copy(update={'callback_start': '13:00'})
    assert '13:00' in customers_for(p, 42)[1].situation
    small = customers_for(p, 42, 5)
    assert any(c.faults for c in small) and any(len(c.products) == 3 for c in small)
    assert any(c.wrong_answers for c in small)


@pytest.mark.parametrize('case', json.loads((ROOT.parent / 'public-test-set.json').read_text()), ids=lambda c: c['id'])
def test_public_expected_ledgers_conform_to_source_policy_and_mock(case):
    # These facts come from Brief A sections 5/7/8 and Brief B, independently of the generator.
    p = sample_policy(42).model_copy(update={
        'wrong_answer_limit': 3, 'callback_start': '10:00', 'callback_end': '19:00',
        'holidays': [date.fromisoformat(d) for d in ('2026-10-26', '2026-11-11', '2026-11-26', '2026-12-25', '2027-01-01')],
        'bands': [Band(name='early', first=1, last=7, deadline_days=12, attempts=1), Band(name='late', first=8, last=45, deadline_days=7, attempts=2)],
        'queues': dict(support='support', human='general', restructuring='restructuring'),
        'multi_product_notes': case['brief'] == 'B',
    })
    expected = case['expected']
    products = [Product(id=f'p{i+1}', kind=prod['type'], balance=prod['past_due'], days_late=prod['days_late'],
                        minimum=prod.get('minimum_payment', prod.get('instalment_amount')), card_last4=prod.get('card_last4'))
                for i, prod in enumerate(case['products'])]
    promised = {r['product_id']: r for r in expected['promises']}
    noted = {r['product_id']: 'refuse' if r['reason'] == 'refused' else r['reason'] for r in expected['notes']}
    goals = [Goal(product_id=prod.id, action='full' if prod.id in promised else noted.get(prod.id, expected['reason'] if expected['reason'] in {'hardship', 'dispute'} else 'paid' if expected['outcome'] == 'paid' else 'refuse'),
                  proposed_amount=promised.get(prod.id, {}).get('amount'), proposed_date=promised.get(prod.id, {}).get('date'), accepts_legal_alternative=True) for prod in products]
    c = Customer(id=case['id'], name=case['variables']['first_name'] + ' ' + case['variables']['last_name'], family=case['family'],
                 now=datetime.fromisoformat(case['variables']['now']), identity=case['identity'], products=products, goals=goals,
                 third_party=case['family'] == 'Third party', wrong_answers={}, style='pieces', situation=case['script'], correction='',
                 transfer=expected['reason'] if expected['outcome'] == 'transferred' else '',
                 faults=[Fault(operation='create_promise', occurrence=1, mode='pre_commit')] if case.get('faults') else [])
    bank = Bank(p, kit_mapping(), c, json.loads((ROOT.parent / 'tools/openapi.json').read_text()))
    if expected['outcome'] == 'not_verified':
        for _ in range(3): invoke(bank, 'verify_identity', field='date_of_birth', answer='1900-01-01')
    elif not c.third_party:
        verify(bank)
        invoke(bank, 'get_account')
    for promise in expected['promises']:
        invoke(bank, 'create_promise', **promise)
        if case.get('faults'): invoke(bank, 'create_promise', **promise)
    for note in expected['notes']: invoke(bank, 'add_note', **note, text='Fixture note')
    for callback in expected['callbacks']: invoke(bank, 'schedule_callback', **callback)
    for transfer in expected['transfers']: invoke(bank, 'transfer_to_agent', **transfer)
    closing = dict(outcome=expected['outcome'])
    if expected['reason']: closing['reason'] = expected['reason']
    invoke(bank, 'close_call', **closing)
    actual = dict(bank.ledger, promises=[dict(r, amount=float(r['amount'])) for r in bank.ledger['promises']],
                  notes=[{k: r[k] for k in ('product_id', 'reason')} for r in bank.ledger['notes']])
    assert {k: actual[k] for k in expected} == expected
    assert grade_ledger(p, c, bank.ledger)['ledger_pass']


def test_pre_action_failure_counters_and_old_response_are_replaced():
    p, m = sample_policy(42), sample_mapping()
    c = customers_for(p, 42, 1)[0]
    api = openapi_for(p, m, 'counter')
    workflow, _ = compile_workflow({'initial_node': 'lookup', 'nodes': {
        'lookup': {'node_type': 'api_request', 'pre_actions': [{'bank_operation': 'get_account', 'description': 'CALL after identity'}]}
    }}, {'operations': operations_for(api)})
    runner = Runner(workflow, p, m, c, None, Deadline(60), api)
    node = workflow['nodes']['lookup']
    runner.execute_tool(node['pre_actions'][0], {}, node, 'lookup', pre_action=True)
    assert runner.variables['lookup_failure_count'] == 1
    assert 'lookup_response.data.data.error' in runner.variables
    verify(runner.bank)
    runner.execute_tool(node['pre_actions'][0], {}, node, 'lookup', pre_action=True)
    assert runner.variables['lookup_success_count'] == runner.variables['lookup_failure_count'] == 1
    assert 'lookup_response.data.data.error' not in runner.variables


def test_calibration_requires_intended_failure_even_if_another_critical_rule_fails(monkeypatch, work):
    import generalisation_agent.calibration as calibration
    p, m = sample_policy(42), sample_mapping()
    api = openapi_for(p, m, 'target')
    _, c, good, _, _ = calibration.fixtures(p, m, api)[0]
    monkeypatch.setattr(calibration.DockerCode, 'ready', lambda self: None)
    class Runner:
        def __init__(self, *a, **k): pass
        def run(self): return good
    judge = SimpleNamespace(grade=lambda *a: {'failed': ['Some other failure'], 'unknown': [], 'hard_failures': ['privacy_before_identity']})
    result = calibration.calibrate(p, m, api, SimpleNamespace(cfg=Config(builder_model='fixture')), Deadline(60), work / 'calibration', runner_factory=Runner, judge=judge)
    honesty = next(control for control in result['controls'] if control['name'] == 'false_success')
    assert honesty['verified_hard_failure'] and honesty['pass'] is False
    assert not honesty['target_detected'] and not result['admitted']


def test_rehearsal_exports_without_holdout_evidence_return_incomplete(monkeypatch, work):
    import generalisation_agent.integration as integration
    import generalisation_agent.packs as packs
    from generalisation_agent.__main__ import main
    p, m = sample_policy(42), sample_mapping()
    users = customers_for(p, 42, 1)
    items = [dict(split=split, brief=str(work / split / 'brief.md'), openapi=str(work / split / 'api.json'),
                  policy_sha256=str(index), api_sha256=str(index)) for index, split in enumerate(('development', 'holdout'))]
    manifest = work / 'manifest.json'
    manifest.write_text(json.dumps({'packs': items}))
    monkeypatch.setattr(Settings, 'from_env', lambda: Settings(True))
    monkeypatch.setattr(Config, 'from_env', lambda: Config(builder_model='fixture'))
    monkeypatch.setattr(packs, 'load_pack', lambda path: (next(i for i in items if Path(i['brief']).parent == path.parent), p, m, users))
    seen = []
    def build(settings, briefs, api, **kwargs):
        seen.append(kwargs['cfg'])
        return dict(export_path='fixture', holdout=kwargs['holdout'], final_score={'complete': True}, diagnostic={'score': {'complete': False}})
    monkeypatch.setattr(integration, 'run_build', build)
    assert main(['rehearse', '--manifest', str(manifest)]) == 5
    assert seen[0] is seen[1]
    assert json.loads((work / 'rehearsal.json').read_text())['complete'] is False


def test_calibration_fingerprint_changes_with_endpoint_without_saving_keys(monkeypatch):
    from generalisation_agent.calibration import fingerprint
    from generalisation_agent.config import model_settings
    p, m = sample_policy(42), sample_mapping()
    api = openapi_for(p, m, 'endpoint')
    monkeypatch.setenv('QWENCLOUD_BASE_URL', 'https://first.invalid/v1')
    first = fingerprint(p, m, api, 'qwencloud/fixture')
    monkeypatch.setenv('QWENCLOUD_BASE_URL', 'https://second.invalid/v1')
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'sentinel-secret')
    assert first != fingerprint(p, m, api, 'qwencloud/fixture')
    assert 'sentinel-secret' not in json.dumps(model_settings('qwencloud/fixture'))


def test_interrupted_transcript_keeps_confirmed_disclosure_failure():
    p, m = sample_policy(42), sample_mapping()
    c = customers_for(p, 42, 1)[0]
    bank = Bank(p, m, c)
    recording = {'ledger': bank.ledger, 'turns': [{'role': 'assistant', 'text': 'Your overdue balance is 100'}],
                 'ended': None, 'unknown': ['Later unsupported feature']}
    judge = SimpleNamespace(grade=lambda *a: {'failed': ['Observed disclosure'], 'unknown': [], 'hard_failures': ['privacy_before_identity']})
    result = grade_case(p, c, recording, judge)
    assert result['pass'] is False and result['verified_hard_failure'] and result['unknown']
