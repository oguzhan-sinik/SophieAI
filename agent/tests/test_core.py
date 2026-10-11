from copy import deepcopy
import json
from pathlib import Path
import pytest
from conftest import action, bank, equals, route
from builder.artifacts import Archive, Redactor, Trace, write_json
from builder.config import Config, writable
from builder.contracts import compile_openapi, compile_workflow, source_documents, tool_from_contract, validate_requirements
from builder.freya_adapter import contains_definition, time_limit
from builder.scoring import Suite, score, verdicts
from builder import runtime
from builder.validation import apply_fix, code_errors, edited_stages, is_wording


def code_stage(name, source, *routes):
    return {'name': name, 'node_type': 'code', 'code': source, 'transitions': [route(target, condition) for target, condition in routes]}


def fix(*edits, problem='fixture', cases=()):
    return {'problem': problem, 'cases': list(cases), 'edits': [{'op': op, 'stage': stage, 'field': field, 'value': value} for op, stage, field, value in edits]}


# ------------------------------------------------------------------ configuration and sources

def test_scope_and_config(work, monkeypatch):
    with pytest.raises(ValueError): writable(work.parent.parent.parent / 'outside.json')
    with pytest.raises(ValueError): Config(max_wall_seconds=1801)
    with pytest.raises(ValueError): Config(reserve=1800)
    with pytest.raises(ValueError): Config(repetitions=0)
    monkeypatch.setenv('LANGSMITH_TRACING', 'maybe')
    with pytest.raises(ValueError): Config.from_env()


def test_contract_refs_and_changed_fields(work):
    api = {'openapi': '3.0.3', 'servers': [{'url': 'https://sandbox.invalid/v2'}], 'components': {'schemas': {'Body': {'type': 'object', 'properties': {'tenant': {'type': 'string'}, 'decision': {'type': 'string', 'enum': ['hold', 'release']}}, 'required': ['tenant', 'decision']}}}, 'paths': {'/resolve': {'post': {'operationId': 'resolve', 'requestBody': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Body'}}}}, 'responses': {}}}}}
    path = work / 'api.json'; write_json(path, api)
    c = compile_openapi(path)
    assert c['operations']['resolve']['body']['properties']['decision']['enum'] == ['hold', 'release']
    compiled = compile_workflow({'nodes': {'x': {'tools': [{'bank_operation': 'resolve', 'description': 'CALL when approved.'}]}}}, c)[0]['nodes']['x']['tools'][0]
    assert compiled['function']['parameters']['properties']['url']['default'] == 'https://sandbox.invalid/v2/resolve'
    api['components']['schemas']['Body'] = {'$ref': '#/components/schemas/Body'}
    write_json(path, api)
    with pytest.raises(ValueError): compile_openapi(path)


def test_rules_keep_their_provenance_and_unclear_ones_do_not_stop_the_build(work, requirements):
    first, second = work / 'policy.md', work / 'memo.md'
    first.write_text('1. The limit is 83 units.\n')
    second.write_text('1. Replace the limit with 97 units.\n')
    docs = source_documents([first, second])
    bundle = deepcopy(requirements)
    rule = bundle['requirements'][0]
    rule['source'].update(path=str(first), span=first.read_text().strip())
    overlay = deepcopy(rule); overlay['rule_id'] = 'R2'
    overlay['source'].update(path=str(second), span=second.read_text().strip())
    overlay['precedence']['supersedes'] = ['R1']
    bundle['requirements'].append(overlay)
    assert validate_requirements(bundle, docs)['requirements'][0]['precedence']['superseded_by'] == ['R2']
    # Raw bank material may contradict itself; that is handed to the designer, not a reason to build nothing.
    bundle['requirements'][1]['interpretation_status'] = 'conflicting'
    bundle['unresolved'] = ['Which limit holds?']
    assert validate_requirements(bundle, docs)['unresolved'] == ['Which limit holds?']
    bundle['requirements'][0]['source']['span'] = 'invented'
    with pytest.raises(ValueError, match='verbatim'): validate_requirements(bundle, docs)


def test_probes_stay_grounded_in_extracted_rules(work, requirements):
    first = work / 'policy.md'
    first.write_text('Verify first.\n')
    docs = source_documents([first])
    bundle = deepcopy(requirements)
    rule = bundle['requirements'][0]
    rule['source'].update(path=str(first), start_line=1, end_line=1, span='Verify first.')
    bundle['probes'] = [{'rule_ids': ['R1'], 'title': 'Floor accepted', 'acts': ['I can only pay 83 units.', 'Yes, I confirm.'],
                         'expected': {'outcome': 'promise', 'promises': [{'product': 'p1', 'amount': 83}]}}]
    checked = validate_requirements(bundle, docs)
    assert checked['probes'][0]['expected']['outcome'] == 'promise'
    bundle['probes'][0]['rule_ids'] = ['R404']
    with pytest.raises(ValueError, match='unknown rules'): validate_requirements(bundle, docs)
    bundle['probes'][0]['rule_ids'] = ['R1']
    bundle['probes'][0]['acts'] = ['']
    with pytest.raises(ValueError, match='empty customer act'): validate_requirements(bundle, docs)
    bundle['probes'][0]['acts'] = ['Fine.']
    bundle['probes'][0]['expected']['outcome'] = '  '
    with pytest.raises(ValueError, match='no expected outcome'): validate_requirements(bundle, docs)


def test_unknown_tool_binding_rejected(contracts):
    with pytest.raises(ValueError, match='Unknown argument'):
        tool_from_contract(contracts['operations']['create_promise'], 'CALL on confirmation', {'not_a_field': 'value'})


# ------------------------------------------------------------------ compiling a source

def test_source_compiles_to_a_deployable_workflow(spec, contracts, check):
    compiled, notes = compile_workflow(spec['workflow'], contracts)
    assert check(spec)['valid'], check(spec)['errors']
    account = compiled['nodes']['account']
    tool = account['pre_actions'][0]
    assert tool['function']['handler'] == '__function__:api_call' and tool['config']['maxRetries'] == 0
    assert account['passthrough'] is True and account['passthrough_default_transition'] == 'close' and account['on_enter'] == {'type': 'silent'}
    # The source is untouched, and compiling a compiled workflow changes nothing.
    assert 'bank_operation' in spec['workflow']['nodes']['account']['pre_actions'][0]
    assert compile_workflow(compiled, contracts)[0] == compiled


def test_code_shorthand_gets_its_wrapper_and_the_helpers_it_calls(spec, contracts, check):
    nodes = spec['workflow']['nodes']
    nodes['account']['transitions'] = [route('calc')]
    nodes['calc'] = code_stage('calc', "try:\n    vars['deadline'] = ctl_add_business_days(vars.get('now'), 4, [0, 1, 2, 3, 4], ['2031-03-05'])\nexcept Exception:\n    vars['deadline'] = ''\n", ('close', None))
    assert check(spec)['valid'], check(spec)['errors']
    code = compile_workflow(spec['workflow'], contracts)[0]['nodes']['calc']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
    assert code.count(runtime.START) == 1 and code_errors(code) == []
    scope = {'vars': {'now': '2031-03-03T11:00'}}
    exec(code, scope, scope)
    assert scope['vars']['deadline'] == '2031-03-10'
    nodes['calc']['pre_actions'] = [{'type': 'function'}]
    with pytest.raises(ValueError, match='either code or pre_actions'): compile_workflow(spec['workflow'], contracts)


def test_malformed_source_gets_named_errors_not_a_crash(spec, contracts, check):
    spec['workflow']['nodes']['verify']['tools'] = [True]
    spec['workflow']['nodes']['stray'] = [{'operation': 'get_account'}]
    result = check(spec)
    assert not result['valid'] and any('stray: node must be an object' in e for e in result['errors']) and any('verify: tools must be an array of objects' in e for e in result['errors'])
    spec['workflow']['nodes'] = ['verify']
    with pytest.raises(ValueError, match='workflow.nodes must be an object'): compile_workflow(spec['workflow'], contracts)
    with pytest.raises(ValueError, match='unsupported bank operation steal_data'):
        compile_workflow({'nodes': {'x': {'name': 'x', 'tools': [bank('steal_data')]}}}, contracts)


# ------------------------------------------------------------------ static checks

@pytest.mark.parametrize('fault', ['placement', 'null', 'passthrough', 'mapping', 'schema', 'retry', 'after_close', 'skip_close', 'unreachable', 'url', 'required', 'loop_prompt', 'unbound'])
def test_static_rejects(fault, spec, contracts):
    from builder.validation import validate
    compiled = compile_workflow(spec['workflow'], contracts)[0]
    nodes = compiled['nodes']
    body = lambda key: nodes[key]['pre_actions'][0]['function']['parameters']['properties']
    if fault == 'placement': nodes['verify']['pre_actions'] = []
    elif fault == 'loop_prompt': nodes['verify']['loop_prompt'] = 'Repeat security question.'
    elif fault == 'null': nodes['verify']['role_message'] = None
    elif fault == 'passthrough': nodes['account']['transitions'] = []
    elif fault == 'mapping': nodes['account']['response_mapping'] = [{'path': 'ok', 'variable': 'x'}]
    elif fault == 'schema': body('close')['body']['properties']['outcome']['enum'] = ['invented']
    elif fault == 'retry': nodes['close']['pre_actions'][0]['config']['maxRetries'] = 2
    elif fault == 'after_close': nodes['close']['transitions'][0]['target_node'] = 'account'
    elif fault == 'skip_close': nodes['verify']['max_turn_transition'] = 'end'
    elif fault == 'unreachable': nodes['unused'] = {**deepcopy(nodes['end']), 'name': 'unused'}
    elif fault == 'url': body('account')['url']['default'] = 'https://evil.invalid'
    elif fault == 'required': body('close')['body']['required'] = []
    elif fault == 'unbound': del body('close')['body']['properties']['outcome']['default']
    assert not validate(compiled, contracts)['valid']


def test_identity_is_read_from_the_routes(spec, check):
    nodes = spec['workflow']['nodes']
    assert check(spec)['valid'], check(spec)['errors']
    proven = deepcopy(nodes['check']['transitions'])
    # The identity tool is called but its result is ignored: the error prints the route and the stage to change.
    nodes['check']['transitions'] = [route('account')]
    error = check(spec)['errors'][0]
    assert 'account: get_account can be reached without a tested identity check, by the route verify > check > account' in error
    assert 'After verify_identity in check no transition on that route tests its result' in error
    # What the caller says is not proof, and one spoken alternative in an OR is a way round the real test.
    nodes['verify']['extraction_schema'].append({'name': 'said_done', 'type': 'string', 'description': 'Caller says they are verified.', 'min_confidence': 0.7})
    nodes['check']['transitions'] = [route('account', {'logic': 'or', 'conditions': [{'variable': 'said_done', 'operator': 'equals', 'operand': 'yes'}, {'variable': 'all_verified', 'operator': 'equals', 'operand': 'true'}]}), route('close')]
    assert any('tested identity check' in e for e in check(spec)['errors'])
    # Inside an AND the response test still has to hold, so that is proof.
    nodes['check']['transitions'][0]['condition'] = {'logic': 'or', 'conditions': [{'logic': 'and', 'conditions': [{'variable': 'said_done', 'operator': 'equals', 'operand': 'yes'}, {'variable': 'all_verified', 'operator': 'equals', 'operand': 'true'}]}]}
    assert check(spec)['valid'], check(spec)['errors']
    # A status that code derives from the response is proof too: the design every working build has used.
    nodes['check']['transitions'] = [route('judge')]
    nodes['judge'] = code_stage('judge', "try:\n    vars['identity'] = 'verified' if str(vars.get('all_verified')).lower() == 'true' else 'failed'\nexcept Exception:\n    vars['identity'] = 'failed'\n",
                                ('account', equals('identity', 'verified')), ('close', None))
    assert check(spec)['valid'], check(spec)['errors']
    # No identity call on the way at all.
    spec['workflow']['initial_node'] = 'account'
    for gone in ('verify', 'check', 'judge'): nodes.pop(gone)
    assert 'No stage on that route calls verify_identity' in check(spec)['errors'][0]
    # A second identity call resets the proof: its own result must be tested too.
    spec['workflow']['initial_node'] = 'verify'
    nodes.update(verify={'name': 'verify', 'node_type': 'conversation', 'task_message': 'Ask.', 'max_node_turns': 3, 'max_turn_transition': 'close', 'transitions': [route('check')]},
                 check=action('check', bank('verify_identity', {'all_verified': 'all_verified'}, field='date_of_birth', answer='{{dob}}'), ('account', proven[0]['condition']), 'close'),
                 again=action('again', bank('verify_identity', field='phone_last4', answer='{{phone}}'), 'promise'),
                 promise=action('promise', bank('create_promise', product_id='{{product_id}}', amount='{{amount}}', date='{{day}}'), 'close'))
    nodes['account']['transitions'] = [route('again')]
    assert any('promise: create_promise can be reached' in e and 'After verify_identity in again' in e for e in check(spec)['errors'])


def test_bank_tools_are_run_by_the_engine_never_offered_to_the_dialogue_model(spec, check):
    nodes = spec['workflow']['nodes']
    nodes['verify']['tools'] = [bank('verify_identity', {'all_verified': 'all_verified'})]
    error = next(e for e in check(spec)['errors'] if 'offered to the dialogue model' in e)
    assert error.startswith('verify: verify_identity is offered') and 'api_request stage' in error


def test_hints_never_block(spec, check):
    node = spec['workflow']['nodes']['verify']
    node['extraction_schema'].append({'name': 'answer', 'type': 'string', 'enum_values': ['agrees', 'refuses', 'unclear'], 'description': 'What the caller said.', 'min_confidence': 0.7})
    node['transitions'].insert(1, route('close', equals('answer', 'refuses')))
    result = check(spec)
    assert result['valid'] and len(result['warnings']) == 1 and "verify: answer can be extracted as ['agrees', 'unclear']" in result['warnings'][0]
    # A stage whose unmatched answers move on elsewhere cannot trap the call.
    node['transitions'][-1]['target_node'] = 'close'
    assert check(spec)['warnings'] == []


def test_accepted_offer_that_is_never_applied_is_hinted(spec, check):
    nodes = spec['workflow']['nodes']
    nodes['account']['transitions'] = [route('check_day')]
    nodes['check_day'] = code_stage('check_day', "try:\n    vars['status'] = 'ok' if vars.get('day') == 'x' else 'late'\n    vars['offer'] = 'y'\nexcept Exception:\n    vars['status'] = 'late'",
                                    ('close', equals('status', 'ok')), ('offer_day', None))
    nodes['offer_day'] = {'name': 'offer_day', 'node_type': 'conversation', 'task_message': 'The status is {{status}}. Offer {{offer}} instead.', 'max_node_turns': 3, 'max_turn_transition': 'close',
                          'extraction_schema': [{'name': 'reply', 'type': 'string', 'enum_values': ['accept', 'refuse'], 'description': 'Answer.', 'min_confidence': 0.7}],
                          'transitions': [route('check_day', equals('reply', 'accept')), route('close', equals('reply', 'refuse')), route('close')]}
    result = check(spec)
    assert result['valid'], result['errors']
    assert len(result['warnings']) == 1 and "offer_day: offers ['offer']" in result['warnings'][0]
    nodes['apply_offer'] = code_stage('apply_offer', "try:\n    vars['day'] = vars.get('offer', '')\nexcept Exception:\n    vars['day'] = ''", ('check_day', None))
    nodes['offer_day']['transitions'][0]['target_node'] = 'apply_offer'
    assert check(spec)['valid'] and check(spec)['warnings'] == []


def test_code_gate():
    assert not code_errors("try:\n    vars['x'] = 'known'\nexcept Exception:\n    vars['x'] = 'unknown'")
    for source in ['import os', "open('/etc/passwd')", "eval('1')", 'import datetime\ndatetime.datetime.now()', "config['url'] = 'https://evil.invalid'"]:
        assert code_errors('try:\n    ' + source.replace('\n', '\n    ') + '\nexcept Exception:\n    pass')


# ------------------------------------------------------------------ fixes

def test_fix_changes_only_what_it_names(spec):
    patched = apply_fix(spec, fix(('set_field', 'verify', 'task_message', 'Ask the security question.')))
    assert patched['workflow']['nodes']['verify']['task_message'] == 'Ask the security question.' and spec['workflow']['nodes']['verify']['task_message'] != 'Ask the security question.'
    assert {k: v for k, v in patched['workflow']['nodes'].items() if k != 'verify'} == {k: v for k, v in spec['workflow']['nodes'].items() if k != 'verify'}
    assert {k: v for k, v in patched['workflow']['nodes']['verify'].items() if k != 'task_message'} == {k: v for k, v in spec['workflow']['nodes']['verify'].items() if k != 'task_message'}
    added = apply_fix(spec, fix(('set_stage', 'extra', '', {'node_type': 'code', 'code': 'pass', 'transitions': []}), ('set_workflow_field', '', 'initial_node', 'extra')))
    assert added['workflow']['nodes']['extra']['name'] == 'extra' and added['workflow']['initial_node'] == 'extra'
    assert 'account' not in apply_fix(spec, fix(('remove_stage', 'account', '', None)))['workflow']['nodes']
    for bad in ([('set_field', 'nowhere', 'task_message', 'x')], [('set_field', 'verify', '', 'x')], [('set_field', 'verify', 'task_message', spec['workflow']['nodes']['verify']['task_message'])],
                [('set_stage', 'verify', '', 'not a stage')], [('remove_stage', 'nowhere', '', None)], [('set_workflow_field', '', 'nodes', {})], []):
        with pytest.raises(ValueError): apply_fix(spec, fix(*bad))


def test_wording_is_told_apart_from_logic(spec):
    reworded = apply_fix(spec, fix(('set_field', 'verify', 'task_message', 'Ask kindly.'), ('set_workflow_field', '', 'system_prompt', 'Be brief.')))
    assert is_wording(spec, reworded) and not is_wording(spec, spec)
    spoken = deepcopy(spec); spoken['workflow']['nodes']['verify']['on_enter'] = {'type': 'tts', 'text': 'Hello.'}
    respoken = deepcopy(spoken); respoken['workflow']['nodes']['verify']['on_enter']['text'] = 'Good morning.'
    assert is_wording(spoken, respoken) and not is_wording(spec, spoken)
    rerouted = apply_fix(spec, fix(('set_field', 'verify', 'max_turn_transition', 'end')))
    rebound = deepcopy(spec); rebound['workflow']['nodes']['close']['pre_actions'][0]['bindings']['outcome'] = 'promise'
    assert not is_wording(spec, rerouted) and not is_wording(spec, rebound)
    # The extractor and the routing model decide by descriptions: changing one changes values and routes.
    extracted = deepcopy(spec); extracted['workflow']['nodes']['verify']['extraction_schema'][0]['description'] = 'Any date the caller mentions.'
    intent = deepcopy(spec); intent['workflow']['nodes']['verify']['transitions'][0]['description'] = 'The caller refuses.'
    prompted = deepcopy(spec); prompted['workflow']['nodes']['verify']['routing_prompt'] = 'Leave when a date was given.'
    assert not is_wording(spec, extracted) and not is_wording(spec, intent) and not is_wording(spec, prompted)
    # A stage or a bound field that happens to be called like a wording key is still a stage or a field.
    named = deepcopy(spec); named['workflow']['nodes']['text'] = code_stage('text', 'pass', ('close', None))
    note = deepcopy(spec); note['workflow']['nodes']['close']['pre_actions'][0]['bindings']['text'] = '{{note}}'
    assert not is_wording(spec, named) and not is_wording(spec, note)
    assert edited_stages(fix(('set_field', 'verify', 'task_message', 'x'), ('set_stage', 'new', '', {}))) == {'verify', 'new'}
    assert edited_stages(fix(('set_workflow_field', '', 'system_prompt', 'x'))) is None and edited_stages(fix(('remove_stage', 'account', '', None))) is None


# ------------------------------------------------------------------ inputs, model calls, the workspace lock

def test_a_brief_from_outside_the_kit_is_never_built_against_the_kit_tool_api(work):
    from builder.build import inputs
    from builder.config import KIT
    kit_api, brief_a = str(KIT / 'tools/openapi.json'), str(KIT / 'briefs/brief-a.md')
    assert inputs([brief_a]) == ([brief_a], kit_api)
    policy, codes, api = work / 'policy.md', work / 'codes.json', work / 'bank.json'
    policy.write_text('Verify first.\n'); codes.write_text('{"outcomes": ["paid"]}'); api.write_text(Path(kit_api).read_text())
    with pytest.raises(ValueError, match='needs its own tool API'): inputs([str(policy)])
    # The tool API is recognised by its content wherever it stands; a JSON code list stays a brief.
    assert inputs([str(policy), str(api)]) == ([str(policy)], str(api))
    assert inputs([str(policy), str(codes)], str(api)) == ([str(policy), str(codes)], str(api))
    assert inputs([str(policy), str(api)], str(api))[1] == str(api)
    with pytest.raises(ValueError, match='More than one'): inputs([str(policy), str(api)], kit_api)
    with pytest.raises(ValueError, match='No brief'): inputs([str(api)])


def test_a_provider_error_gets_one_more_try_and_then_fails_like_a_bad_answer(work):
    from builder.adk import ADKRoles
    from builder.config import Deadline
    roles = ADKRoles(Config(artifacts=work, tracing=False), Deadline(60), Trace(work / 'trace.log', {'run_id': 'test'}, False), work)
    def scripted(*outcomes):
        outcomes = list(outcomes)
        def request(*args):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception): raise outcome
            return outcome
        roles._request = request
        return outcomes
    scripted(ConnectionError('reset by peer'), {'ok': True})
    assert roles.ask('R', 'p', 'i', {}, None) == {'ok': True}
    scripted(ConnectionError('reset by peer'), RuntimeError('503 from the provider'))
    with pytest.raises(ValueError, match='failed twice: RuntimeError'): roles.ask('R', 'p', 'i', {}, None)
    left = scripted(TimeoutError('too slow'), {'ok': True})
    with pytest.raises(TimeoutError): roles.ask('R', 'p', 'i', {}, None)
    assert left == [{'ok': True}]  # a timeout is not retried: the time is gone


def test_a_lock_that_never_comes_free_costs_the_budget_not_the_export(work):
    import fcntl
    from builder.config import Deadline
    from builder.freya_adapter import file_lock
    with (work / 'lock').open('a+') as other:
        fcntl.flock(other, fcntl.LOCK_EX)   # another build holds it
        with file_lock(work / 'lock', Deadline(.3)) as held:
            assert held is False
    with file_lock(work / 'lock', Deadline(5)) as held:
        assert held is True


# ------------------------------------------------------------------ scoring and artifacts

def test_strict_repetitions_unknown():
    suite = Suite(('a', 'b'), 'hash', 'official_public', 3)
    raw = {'all_rows': [[{'id': 'a', 'pass': True}, {'id': 'b', 'pass': True}]] * 3}
    assert score(raw, suite).strict_pass_rate == 1 and verdicts(raw, suite) == {'a': True, 'b': True}
    raw['all_rows'][2] = [{'id': 'a', 'pass': False}, {'id': 'b', 'pass': True}]
    assert score(raw, suite).strict_pass_rate == .5 and verdicts(raw, suite) == {'a': False, 'b': True}
    raw['all_rows'].pop()
    result = score(raw, suite)
    assert result.unknown == 2 and result.strict_pass_rate is None and not result.complete
    raw['all_rows'][0][0]['pass'] = 'true'
    assert score(raw, suite).strict_pass_rate is None
    record = score({'all_rows': [[{'id': 'a', 'pass': False}]]}, Suite(('a',), 's', 'official_public', 2))
    assert record.failed == 1 and record.strict_pass_rate is None and record.coverage_ratio == .5
    with pytest.raises(ValueError): Suite(('a',), 's', 'made_up', 1)


def test_archive_keeps_source_and_workflow_immutable(work, spec, contracts):
    archive = Archive(work / 'archive')
    workflow = compile_workflow(spec['workflow'], contracts)[0]
    parent = archive.add(spec, workflow, mutation_kind='design')
    child_source = apply_fix(spec, fix(('set_workflow_field', '', 'system_prompt', 'New policy wording')))
    record = archive.add(child_source, compile_workflow(child_source['workflow'], contracts)[0], parent=parent['candidate_id'], patch={'fixes': []}, mutation_kind='wording')
    assert archive.source(parent['candidate_id']) == spec and archive.workflow(parent['candidate_id']) == workflow
    assert record['generation'] == 1 and record['parent_id'] == parent['candidate_id']
    archive.checkpoint(champion_id=parent['candidate_id'])
    assert json.loads((work / 'archive/champion.json').read_text())['champion_id'] == parent['candidate_id']
    path = Path(parent['workflow_snapshot_path']).parent / 'proposal.json'
    altered = deepcopy(spec); altered['workflow']['system_prompt'] = 'tampered'; path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match='modified'): archive.source(parent['candidate_id'])
    archive.db.close()


def test_redaction_and_telemetry_outage(work, monkeypatch):
    monkeypatch.setenv('FREYA_API_KEY', 'test_secret_123456789')
    redactor = Redactor()
    assert 'test_secret_123456789' not in json.dumps(redactor({'message': 'test_secret_123456789', 'phone_last4': '1234'}))
    with pytest.raises(ValueError): redactor.assert_no_secrets({'x': 'test_secret_123456789'})
    monkeypatch.setenv('LANGSMITH_API_KEY', 'fake')
    import langsmith
    monkeypatch.setattr(langsmith, 'Client', lambda **kw: (_ for _ in ()).throw(RuntimeError('offline')))
    trace = Trace(work / 'trace.log', {'run_id': 'test'})
    trace.event('test', message='test_secret_123456789')
    trace.close(status='done')
    assert 'run_end' in (work / 'trace.log').read_text()
    assert 'test_secret_123456789' not in (work / 'trace.log').read_text()


def test_round_trip():
    contains_definition({'x': 1, 'empty': []}, {'x': 1, 'server_default': True})
    with pytest.raises(ValueError): contains_definition({'x': 1}, {'x': 2})
    with pytest.raises(ValueError): contains_definition({'tools': [{'name': 'required'}]}, {'tools': []})


def test_timeout():
    import time
    with pytest.raises(TimeoutError):
        with time_limit(.01): time.sleep(.1)


def test_adk_does_not_expand_freya_placeholders():
    import asyncio
    from google.adk.agents import LlmAgent
    from builder.adk import literal_instruction
    text = 'Bind {{customer_id}} and {{previously_set_variable}} in Freya.'
    agent = LlmAgent(name='test_literal', model='unused', instruction=literal_instruction(text))
    instruction, bypass = asyncio.run(agent.canonical_instruction(None))
    assert instruction == text and bypass is True


# ------------------------------------------------------------------ runtime support

def helpers():
    scope = {}
    exec(runtime.DATE_HELPERS, scope, scope)
    return scope


@pytest.mark.parametrize('said,expected', [
    ('tomorrow', '2026-10-15'), ('Maria can be reached tomorrow morning around eleven', '2026-10-15'),
    ('today', '2026-10-14'), ('the day after tomorrow', '2026-10-16'),
    ('this Friday', '2026-10-16'), ('Friday', '2026-10-16'), ('next Friday', '2026-10-23'), ('on wednesday', '2026-10-14'),
    ('Monday the twenty sixth', '2026-10-26'), ('the 26th', '2026-10-26'), ('the twenty-second of October', '2026-10-22'),
    ('6 November', '2026-11-06'), ('November 6th', '2026-11-06'), ('the 3rd', '2026-11-03'), ('january the 5th', '2027-01-05'),
    ('in two weeks', '2026-10-28'), ('in 3 days', '2026-10-17'), ('2026-10-20', '2026-10-20'),
    ('I may pay on the 30th', '2026-10-30'), ('05 December 1975', '1975-12-05'), ('14 March 1988', '1988-03-14'),
    # A year said in words is the stated year, never replaced by the call's year.
    ('the fourteenth of March nineteen eighty-eight', '1988-03-14'), ('the fourteenth of March, one nine eight eight', '1988-03-14'),
    ('March fourteenth, nineteen eighty eight', '1988-03-14'), ('the fifth of December nineteen seventy five', '1975-12-05'),
    ('the ninth of September nineteen ninety', '1990-09-09'), ('3 May two thousand and five', '2005-05-03'), ('the first of June two thousand', '2000-06-01'),
    ('twelfth of July nineteen oh five', '1905-07-12'), ('the twenty-second of October twenty twenty-six', '2026-10-22'),
    # Numbers before the day are not a year: an amount said with the day stays an amount.
    ('nineteen fifty on the sixth of November', '2026-11-06'), ('sixty on the 30th', '2026-10-30'),
    ('the week after next', ''), ('next week', ''), ('end of the month', ''), ('when my salary comes', ''), ('', ''),
])
def test_spoken_days_resolve_against_call_now(said, expected):
    assert helpers()['ctl_date'](said, '2026-10-14T11:00') == expected


def test_weekday_reading_is_a_parameter_not_a_constant():
    resolve = helpers()['ctl_date']
    assert resolve('next Friday', '2026-10-16T09:00') == '2026-10-23'
    assert resolve('next Friday', '2026-10-14T09:00', 'next_occurrence') == '2026-10-16'
    assert resolve('next Friday', '2026-10-16T09:00', 'next_occurrence') == '2026-10-23'


def test_business_days_take_their_calendar_from_the_caller():
    h = helpers()
    week, off = [0, 1, 2, 3], ['2028-02-17']  # a four-day week with one excluded date: nothing here is a default
    assert h['ctl_add_business_days']('2028-02-11T09:00', 5, week, off) == '2028-02-22'
    assert h['ctl_add_business_days']('2028-02-28', 1, list(range(7)), []) == '2028-02-29'
    assert [h['ctl_is_business_day'](d, week, off) for d in ('2028-02-16', '2028-02-17', '2028-02-18')] == [True, False, False]
    assert h['ctl_business_day_on_or_after']('2028-02-16', week, off) == '2028-02-16' and h['ctl_business_day_on_or_after']('2028-02-17', week, off) == '2028-02-21'
    assert h['ctl_last_business_day_of_week']('2028-02-14', week, off) == '2028-02-16' and h['ctl_last_business_day_of_week']('2028-02-14', [], off) == ''
    assert h['ctl_add_business_days']('not a day', 3, week, off) == '' and h['ctl_add_business_days']('2028-02-11', 0, week, off) == '' and h['ctl_add_business_days']('2028-02-11', 3, [], off) == ''


def test_runtime_prelude_resolves_dates_and_is_idempotent(spec, contracts):
    w = spec['workflow']
    w['nodes']['verify']['extraction_schema'] = [{'name': 'pay_day', 'type': 'date', 'description': 'Day offered.', 'min_confidence': 0.7}]
    w['nodes']['check']['pre_actions'][0]['bindings']['answer'] = '{{pay_day}}'
    w['nodes']['verify']['transitions'][0]['condition']['conditions'][0]['variable'] = 'pay_day'
    w['nodes']['calc'] = code_stage('calc', "try:\n    vars['seen'] = str(vars.get('pay_day'))\nexcept Exception:\n    vars['seen'] = ''\n", ('close', None))
    once = compile_workflow(w, contracts)[0]
    assert compile_workflow(once, contracts)[0] == once
    item = once['nodes']['verify']['extraction_schema'][0]
    assert item['type'] == 'string' and runtime.SAID in item['description'] and runtime.SINGLE_DAY in item['description']
    # A date bound straight into a request is resolved before the request is built.
    assert runtime.START in once['nodes']['check']['pre_actions'][0]['pre_process_code']
    code = once['nodes']['calc']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
    assert code_errors(code) == [] and code.count(runtime.START) == 1
    scope = {'vars': {'now': '2026-10-14T11:00', 'pay_day': 'tomorrow'}}
    exec(code, scope, scope)
    assert scope['vars']['seen'] == '2026-10-15' and scope['vars']['pay_day_said'] == 'tomorrow'
    exec(code, scope, scope)
    assert scope['vars']['pay_day'] == '2026-10-15'
    scope = {'vars': {'now': '2026-10-14T11:00', 'pay_day': 'sometime next week'}}
    exec(code, scope, scope)
    assert scope['vars']['seen'] == '' and scope['vars']['pay_day_said'] == 'sometime next week'


def test_prelude_variables_can_never_shadow_a_helper():
    """Seen live: a prelude loop variable had the name of a helper function, so every business-day
    call failed once a spoken date had been resolved, and the agent went silent."""
    import ast
    functions = {n.name for n in ast.walk(ast.parse(runtime.DATE_HELPERS)) if isinstance(n, ast.FunctionDef)}
    assigned = set()
    for block in (runtime.DATE_APPLY % '[]', runtime.STRUCTURED_APPLY % '[]', runtime.STRUCTURED_HOOK % '[]'):
        assigned |= {n.id for n in ast.walk(ast.parse(block)) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    assert assigned and not assigned & functions and all(name.startswith('ctlv_') for name in assigned)
    assert all(name.startswith('ctl_') for name in functions)


def test_helpers_work_after_a_spoken_date_was_resolved_in_the_same_stage(spec, contracts):
    w = spec['workflow']
    w['nodes']['account']['pre_actions'][0]['response_mapping'] = [{'path': 'data.products', 'variable': 'products'}]
    w['nodes']['account']['transitions'] = [route('plan')]
    w['nodes']['plan'] = code_stage('plan', """import json
try:
    week, off = [0, 1, 2, 3, 4], ['2026-10-26']
    vars['count'] = len(json.loads(vars.get('products') or '[]'))
    vars['deadline'] = ctl_add_business_days(vars.get('now'), 12, week, off)
    vars['friday'] = ctl_last_business_day_of_week(vars.get('now'), week, off)
    vars['shifted'] = ctl_business_day_on_or_after('2026-10-24', week, off)
    vars['open'] = 'yes' if ctl_is_business_day(vars.get('dob'), week, off) else 'no'
    vars['ready'] = 'yes'
except Exception:
    vars['ready'] = 'no'
""", ('close', None))
    code = compile_workflow(w, contracts)[0]['nodes']['plan']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
    # The state of a real call: a date of birth was said and extracted, the account came back flattened.
    scope = {'vars': {'now': '2026-10-14T11:00', 'dob': '05 December 1975', 'account_response.data.products.0.product_id': 'p1', 'account_response.data.products.0.past_due': 540}}
    for run in range(2):  # a stage can be entered twice in one call
        exec(code, scope, scope)
        out = scope['vars']
        assert out['ready'] == 'yes' and out['dob'] == '1975-12-05' and out['count'] == 1
        assert (out['deadline'], out['friday'], out['shifted'], out['open']) == ('2026-11-02', '2026-10-16', '2026-10-27', 'yes')


def test_loop_guard_routes_a_reentered_stage_to_its_closing_route(spec, contracts, check):
    guard = compile_workflow(spec['workflow'], contracts)[0]['nodes']['verify']['transitions'][0]
    assert guard['description'] == runtime.GUARD and guard['target_node'] == 'close'
    assert guard['condition'] == {'variable': 'verify.total_turns', 'operator': 'greater_than', 'operand': 20}
    assert check(spec)['valid']


def test_negative_identity_and_transport_success_are_not_verification(spec, check):
    for condition in (
        {'variable': 'all_verified', 'operator': 'equals', 'operand': 'false'},
        {'variable': 'all_verified', 'operator': 'is_set'},
        {'variable': 'check_status_code', 'operator': 'equals', 'operand': 200},
        {'variable': 'check_success_count', 'operator': 'greater_than', 'operand': 0},
    ):
        spec['workflow']['nodes']['check']['transitions'][0]['condition'] = condition
        assert any('tested identity check' in error for error in check(spec)['errors'])
