from copy import deepcopy
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import pytest
from builder.artifacts import Archive, Redactor, Trace, digest, write_json
from builder.config import Config, Deadline, writable
from builder.contracts import compile_openapi, compile_tools, source_documents, validate_requirements
from builder.freya_adapter import contains_definition, public_suite, time_limit
from builder.scoring import Suite, FeedbackAdapter, score, group_advantages, choose_champion
from builder.validation import validate, code_errors, apply_mutation


def test_scope_and_config(work, monkeypatch):
    with pytest.raises(ValueError): writable(work.parent.parent.parent / 'outside.json')
    with pytest.raises(ValueError): Config(mode='both')
    with pytest.raises(ValueError): Config(max_wall_seconds=1801)
    with pytest.raises(ValueError): Config(reserve=1800)
    with pytest.raises(ValueError): Config(group_size=0)
    monkeypatch.setenv('BENCHMARK_MODE', 'wrong')
    with pytest.raises(ValueError): Config.from_env()


def test_static_good(spec, contracts, requirements):
    result = validate(spec, contracts, requirements)
    assert result['valid'], result['errors']
    assert not result['policy_proven']


def test_gate_accepts_declared_alias_and_canonical_response(spec, contracts, requirements):
    gate = spec['tool_gates'][0]
    canonical = gate['variable']
    gate['variable'] = 'verified_alias'
    node = spec['workflow']['nodes']['verify']
    node['tools'][0]['response_mapping'] = [{'path': 'data.all_verified', 'variable': 'verified_alias'}]
    node['transitions'][0]['condition']['conditions'][0]['variable'] = 'verified_alias'
    assert validate(spec, contracts, requirements)['valid']
    spec['workflow']['test_variables'] = {canonical: 'true'}
    assert not validate(spec, contracts, requirements)['valid']


def test_model_tool_name_string_is_rejected_without_crashing(spec, contracts, requirements):
    spec['workflow']['nodes']['verify']['tools'] = ['verify_identity']
    result = validate(spec, contracts, requirements)
    assert not result['valid'] and 'array of objects' in result['errors'][0]


@pytest.mark.parametrize('fault', ['placement', 'null', 'unsupported', 'passthrough', 'mapping', 'schema', 'retry', 'ungated', 'gate_or', 'after_close', 'skip_close', 'unreachable', 'url', 'required', 'loop_prompt'])
def test_static_rejects(fault, spec, contracts, requirements):
    nodes = spec['workflow']['nodes']
    if fault == 'placement': nodes['verify']['pre_actions'] = []
    elif fault == 'loop_prompt': nodes['verify']['loop_prompt'] = 'Repeat security question.'
    elif fault == 'null': nodes['verify']['role_message'] = None
    elif fault == 'unsupported': nodes['account']['pre_actions'][0]['function']['name'] = 'steal_data'
    elif fault == 'passthrough': nodes['account']['transitions'] = []
    elif fault == 'mapping': nodes['account']['pre_actions'][0]['response_mapping'] = [{'path': 'ok', 'variable': 'x'}]
    elif fault == 'schema': nodes['close']['pre_actions'][0]['function']['parameters']['properties']['body']['properties']['outcome']['enum'] = ['invented']
    elif fault == 'retry': nodes['close']['pre_actions'][0]['config']['maxRetries'] = 2
    elif fault == 'ungated': spec['workflow']['initial_node'] = 'account'
    elif fault == 'gate_or': nodes['verify']['transitions'][0]['condition']['conditions'].append({'operator': 'always'})
    elif fault == 'after_close': nodes['close']['transitions'][0]['target_node'] = 'account'
    elif fault == 'skip_close': nodes['verify']['max_turn_transition'] = 'end'
    elif fault == 'unreachable': nodes['unused'] = {**deepcopy(nodes['end']), 'name': 'unused'}
    elif fault == 'url': nodes['account']['pre_actions'][0]['function']['parameters']['properties']['url']['default'] = 'https://evil.invalid'
    elif fault == 'required': nodes['close']['pre_actions'][0]['function']['parameters']['properties']['body']['required'] = []
    assert not validate(spec, contracts, requirements)['valid']


def test_contract_refs_and_changed_fields(work):
    api = {'openapi': '3.0.3', 'servers': [{'url': 'https://sandbox.invalid/v2'}], 'components': {'schemas': {'Body': {'type': 'object', 'properties': {'tenant': {'type': 'string'}, 'decision': {'type': 'string', 'enum': ['hold', 'release']}}, 'required': ['tenant', 'decision']}}}, 'paths': {'/resolve': {'post': {'operationId': 'resolve', 'requestBody': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Body'}}}}, 'responses': {}}}}}
    path = work / 'api.json'; write_json(path, api)
    c = compile_openapi(path)
    assert c['operations']['resolve']['body']['properties']['decision']['enum'] == ['hold', 'release']
    workflow = {'nodes': {'x': {'tools': [{'bank_operation': 'resolve', 'description': 'CALL when approved.'}]}}}
    compiled = compile_tools(workflow, c)['nodes']['x']['tools'][0]
    assert compiled['function']['parameters']['properties']['url']['default'] == 'https://sandbox.invalid/v2/resolve'
    api['components']['schemas']['Body'] = {'$ref': '#/components/schemas/Body'}
    write_json(path, api)
    with pytest.raises(ValueError): compile_openapi(path)


def test_provenance_override_and_conflict(work, requirements):
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
    result = validate_requirements(bundle, docs)
    assert result['requirements'][0]['precedence']['superseded_by'] == ['R2']
    bundle['requirements'][1]['interpretation_status'] = 'conflicting'
    with pytest.raises(ValueError, match='Unresolved'): validate_requirements(bundle, docs)
    bundle['requirements'][1]['interpretation_status'] = 'resolved'
    bundle['requirements'][0]['source']['span'] = 'invented'
    with pytest.raises(ValueError, match='verbatim'): validate_requirements(bundle, docs)


def test_code_gate():
    assert not code_errors("try:\n    vars['x'] = 'known'\nexcept Exception:\n    vars['x'] = 'unknown'")
    for source in ['import os', "open('/etc/passwd')", "eval('1')", 'import datetime\ndatetime.datetime.now()', "config['url'] = 'https://evil.invalid'"]:
        assert code_errors('try:\n    ' + source.replace('\n', '\n    ') + '\nexcept Exception:\n    pass')


def test_strict_repetitions_unknown():
    suite = Suite(('a', 'b'), 'hash', 'official_public', 3)
    raw = {'all_rows': [[{'id': 'a', 'pass': True}, {'id': 'b', 'pass': True}]] * 3}
    assert score(raw, suite).strict_pass_rate == 1
    raw['all_rows'][2] = [{'id': 'a', 'pass': False}, {'id': 'b', 'pass': True}]
    assert score(raw, suite).strict_pass_rate == .5
    raw['all_rows'].pop()
    result = score(raw, suite)
    assert result.unknown == 2 and result.strict_pass_rate is None and not result.complete
    raw['all_rows'][0][0]['pass'] = 'true'
    assert score(raw, suite).strict_pass_rate is None


def test_mixed_groups_and_champion():
    s = Suite(('a',), 'same', 'official_public', 1)
    good = score({'all_rows': [[{'id': 'a', 'pass': True}]]}, s)
    bad = score({'all_rows': [[{'id': 'a', 'pass': False}]]}, s)
    advantages, summaries = group_advantages({'a': good, 'b': bad, 'missing': None}, {'a': 'p', 'b': 'p', 'missing': 'p'})
    assert advantages == {'a': 1, 'b': -1, 'missing': None}
    equal, summaries = group_advantages({'a': bad, 'b': bad}, {'a': 'p', 'b': 'p'})
    assert equal == {'a': 0, 'b': 0} and summaries[0]['diversify']
    mixed, _ = group_advantages({'a': good, 'b': replace(good, suite_key='different')}, {'a': 'p', 'b': 'p'})
    assert mixed == {'a': None, 'b': None}
    assert choose_champion('a', 'b', {'a': bad, 'b': good}, {'a': True, 'b': True}) == 'b'
    assert choose_champion('a', 'b', {'a': bad, 'b': replace(good, hard_fail_count=1)}, {'a': True, 'b': True}) == 'a'
    assert choose_champion('a', 'b', {'a': bad, 'b': replace(good, suite_key='different')}, {'a': True, 'b': True}) == 'a'


def test_feedback_sentinel():
    record = score({'all_rows': [[{'id': 'a', 'pass': False, 'failed': ['LEAK_TEST_SENTINEL']}]]}, Suite(('a',), 's', 'official_public', 1))
    diagnostics = [{'repair_hypothesis': '[REDACTED TEST FIXTURE: LEAK_TEST_SENTINEL]'}]
    scalar = FeedbackAdapter('scoring_only').for_optimizer(record, diagnostics)
    diagnostic = FeedbackAdapter('scoring_with_diagnostics').for_optimizer(record, diagnostics)
    assert 'LEAK_TEST_SENTINEL' not in json.dumps(scalar)
    assert 'LEAK_TEST_SENTINEL' in json.dumps(diagnostic['diagnostics'])
    assert {k: v for k, v in diagnostic.items() if k != 'diagnostics'} == scalar


def test_archive_immutable_and_patch(work, spec):
    archive = Archive(work / 'archive')
    parent = archive.add(spec)
    mutation = {'parent_id': parent['candidate_id'], 'mutation_type': 'adjust_prompt', 'target_nodes': ['verify'], 'target_rule_ids': ['R1'], 'hypothesis': 'Clarify', 'operations': [{'op': 'set_system_prompt', 'target': '', 'value': 'New policy wording'}], 'expected_effect': 'Clarity', 'risk': 'low', 'coverage': spec['coverage']}
    child = apply_mutation(spec, mutation, parent['candidate_id'])
    record = archive.add(child, parent=parent['candidate_id'], mutation=mutation)
    assert archive.spec(parent['candidate_id']) == spec
    assert record['generation'] == 1 and record['parent_id'] == parent['candidate_id']
    archive.checkpoint(champion_id=parent['candidate_id'])
    assert json.loads((work / 'archive/champion.json').read_text())['champion_id'] == parent['candidate_id']
    path = Path(parent['workflow_snapshot_path']).parent / 'proposal.json'
    altered = deepcopy(spec); altered['workflow']['system_prompt'] = 'tampered'; path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match='modified'): archive.spec(parent['candidate_id'])
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


def test_code_probes_use_source_values(requirements):
    from builder.scenarios import run_probes
    code = "import datetime\ntry:\n    anchor = datetime.date.fromisoformat(vars['now'][:10])\n    vars['next_day'] = (anchor + datetime.timedelta(days=vars['offset'])).isoformat()\nexcept Exception:\n    vars['next_day'] = ''"
    spec = {'workflow': {'nodes': {'calendar': {'node_type': 'code', 'pre_actions': [{'function': {'parameters': {'properties': {'code': {'default': code}}}}}]}}}}
    probes = {'probes': [{'probe_id': 'changed-date', 'rule_ids': ['R1'], 'node_id': 'calendar', 'variables': {'now': '2031-03-02T12:00', 'offset': 3}, 'expected': {'next_day': '2031-03-05'}}]}
    result = run_probes(spec, probes, requirements, Deadline(10))
    assert result['passed'] == 1 and result['evidence_type'] == 'local_code_only'
    probes['probes'][0]['expected']['next_day'] = 'wrong'
    assert run_probes(spec, probes, requirements, Deadline(10))['passed'] == 0


def test_invalid_probe_metadata_never_becomes_workflow_expectation():
    from builder.scenarios import validate_probe_targets
    spec = {'workflow': {'nodes': {'calc': {'node_type': 'code', 'pre_actions': [{'function': {'parameters': {'properties': {'code': {'default': "vars['deadline'] = '2031-03-05'"}}}}}]}}}}
    probes = {'probes': [{'probe_id': 'boundary', 'rule_ids': ['R1'], 'node_id': 'calc', 'variables': {}, 'expected': {'deadline': '2031-03-05'}}]}
    validate_probe_targets(spec, probes)
    probes['probes'][0]['expected']['oracle'] = 'Explanatory prose'
    with pytest.raises(ValueError, match='written variables'):
        validate_probe_targets(spec, probes)
    probes['probes'][0]['node_id'] = 'close_api'
    with pytest.raises(ValueError, match='code node'):
        validate_probe_targets(spec, probes)


def test_failure_with_missing_repeat_not_complete():
    suite = Suite(('a',), 's', 'official_public', 2)
    record = score({'all_rows': [[{'id': 'a', 'pass': False}]]}, suite)
    assert record.failed == 1 and record.strict_pass_rate is None and record.coverage_ratio == .5
    proxy = Suite(('a',), 's', 'proxy', 1)
    record = score({'all_rows': [[{'id': 'a', 'state_ok': False}]]}, proxy)
    assert record.failed == 1 and not record.complete and record.coverage_ratio == 0


def test_hook_cannot_forge_verification(spec, contracts, requirements):
    spec['workflow']['nodes']['verify']['tools'][0]['post_process_code'] = "try:\n    d = result.get('data', {})\n    d['all_verified'] = True\nexcept Exception:\n    pass"
    result = validate(spec, contracts, requirements)
    assert not result['valid']
    assert any('gate response' in e for e in result['errors'])


def test_unknown_tool_binding_rejected(contracts):
    from builder.contracts import tool_from_contract
    with pytest.raises(ValueError, match='Unknown argument'):
        tool_from_contract(contracts['operations']['create_promise'], 'CALL on confirmation', {'not_a_field': 'value'})


def test_diagnostics_need_real_evidence(spec, requirements):
    from builder.diagnostics import grounded_diagnoses
    d = {'case_id': 'case', 'rule_ids': ['R1'], 'evidence_refs': ['all_rows.0.0.failed.0'], 'likely_workflow_nodes': ['verify'], 'confidence': .8}
    raw = {'all_rows': [[{'id': 'case', 'failed': ['Observed failure']}]]}
    assert grounded_diagnoses([d], raw, requirements, spec['workflow'], {'case'}) == [d]
    d['evidence_refs'] = ['all_rows.9.0.failed.0']
    assert grounded_diagnoses([d], raw, requirements, spec['workflow'], {'case'}) == []


def test_adk_does_not_expand_freya_placeholders():
    import asyncio
    from google.adk.agents import LlmAgent
    from builder.adk import literal_instruction
    text = 'Bind {{customer_id}} and {{previously_set_variable}} in Freya.'
    agent = LlmAgent(name='test_literal', model='unused', instruction=literal_instruction(text))
    instruction, bypass = asyncio.run(agent.canonical_instruction(None))
    assert instruction == text and bypass is True


def test_source_parameter_calendar_calculator():
    from builder.adk import business_day_dates
    assert business_day_dates('2028-02-11', [0, 1, 2, 3], ['2028-02-17'], 5) == {
        'dates': ['2028-02-14', '2028-02-15', '2028-02-16', '2028-02-21', '2028-02-22'], 'deadline': '2028-02-22'}
    assert business_day_dates('2028-02-28', list(range(7)), [], 1)['deadline'] == '2028-02-29'
    with pytest.raises(ValueError): business_day_dates('2028-02-11', [], [], 5)


def _helpers():
    from builder import runtime
    scope = {}
    exec(runtime.DATE_HELPERS, scope, scope)
    return scope['ctl_date']


@pytest.mark.parametrize('said,expected', [
    ('tomorrow', '2026-10-15'), ('Maria can be reached tomorrow morning around eleven', '2026-10-15'),
    ('today', '2026-10-14'), ('the day after tomorrow', '2026-10-16'),
    ('this Friday', '2026-10-16'), ('Friday', '2026-10-16'), ('next Friday', '2026-10-23'), ('on wednesday', '2026-10-14'),
    ('Monday the twenty sixth', '2026-10-26'), ('the 26th', '2026-10-26'), ('the twenty-second of October', '2026-10-22'),
    ('6 November', '2026-11-06'), ('November 6th', '2026-11-06'), ('the 3rd', '2026-11-03'), ('january the 5th', '2027-01-05'),
    ('in two weeks', '2026-10-28'), ('in 3 days', '2026-10-17'), ('2026-10-20', '2026-10-20'),
    ('I may pay on the 30th', '2026-10-30'),
    ('the week after next', ''), ('next week', ''), ('end of the month', ''), ('when my salary comes', ''), ('', ''),
])
def test_spoken_days_resolve_against_call_now(said, expected):
    assert _helpers()(said, '2026-10-14T11:00') == expected


def test_weekday_reading_is_a_parameter_not_a_constant():
    resolve = _helpers()
    assert resolve('next Friday', '2026-10-16T09:00') == '2026-10-23'
    assert resolve('next Friday', '2026-10-14T09:00', 'next_occurrence') == '2026-10-16'
    assert resolve('next Friday', '2026-10-16T09:00', 'next_occurrence') == '2026-10-23'


def test_runtime_prelude_resolves_dates_and_is_idempotent(spec, contracts):
    from builder import runtime
    from builder.validation import code_errors
    from builder.contracts import compile_tools
    w = spec['workflow']
    w['nodes']['verify']['extraction_schema'] = [{'name': 'pay_day', 'type': 'date', 'description': 'Day offered.', 'min_confidence': 0.7}]
    w['nodes']['calc'] = {'name': 'calc', 'node_type': 'code', 'passthrough': True, 'passthrough_default_transition': 'close',
                          'transitions': [{'target_node': 'close', 'condition': {'operator': 'always'}}],
                          'pre_actions': [{'type': 'function', 'function': {'name': 'code', 'handler': '__function__:code_exec', 'parameters': {'type': 'object', 'properties': {
                              'code': {'type': 'string', 'default': "try:\n    vars['seen'] = str(vars.get('pay_day'))\nexcept Exception:\n    vars['seen'] = ''\n"}}}}}]}
    once = compile_tools(w, contracts)
    assert compile_tools(once, contracts) == once
    item = once['nodes']['verify']['extraction_schema'][0]
    assert item['type'] == 'string' and runtime.SAID in item['description']
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


def test_loop_guard_routes_a_reentered_stage_to_its_closing_route(spec, contracts, requirements):
    from builder import runtime
    from builder.contracts import compile_tools
    once = compile_tools(spec['workflow'], contracts)
    guard = once['nodes']['verify']['transitions'][0]
    assert guard['description'] == runtime.GUARD and guard['target_node'] == 'close'
    assert guard['condition'] == {'variable': 'verify.total_turns', 'operator': 'greater_than', 'operand': 20}
    assert compile_tools(once, contracts) == once
    assert validate({**spec, 'workflow': once}, contracts, requirements)['valid']


def test_extracted_value_without_route_is_a_dead_end(spec, contracts, requirements):
    node = spec['workflow']['nodes']['verify']
    node['extraction_schema'] = [{'name': 'answer', 'type': 'string', 'enum_values': ['agrees', 'refuses', 'unclear'], 'description': 'What the caller said.', 'min_confidence': 0.7}]
    node['transitions'] += [{'target_node': 'close', 'description': 'Refused', 'condition': {'logic': 'or', 'conditions': [{'variable': 'answer', 'operator': 'equals', 'operand': 'refuses'}]}},
                            {'target_node': 'verify', 'description': 'Stay', 'condition': {'operator': 'always'}}]
    result = validate(spec, contracts, requirements)
    # A stay can be intended, so the finding asks for a repair and never blocks deployment.
    assert result['valid'] and len(result['dead_ends']) == 1 and "verify: answer can be extracted as ['agrees', 'unclear']" in result['dead_ends'][0]
    # An explicit route back to the stage is a decision; an unlisted value is an oversight.
    node['transitions'].insert(1, {'target_node': 'verify', 'description': 'Ask again', 'condition': {'logic': 'or', 'conditions': [{'variable': 'answer', 'operator': 'equals', 'operand': 'unclear'}, {'variable': 'answer', 'operator': 'equals', 'operand': 'agrees'}]}})
    assert not validate(spec, contracts, requirements)['dead_ends']
    # A stage whose unmatched answers move on elsewhere cannot trap the call.
    node['transitions'][1]['condition'] = {'logic': 'or', 'conditions': [{'variable': 'answer', 'operator': 'equals', 'operand': 'unclear'}]}
    assert validate(spec, contracts, requirements)['dead_ends']
    node['transitions'][-1]['target_node'] = 'close'
    assert not validate(spec, contracts, requirements)['dead_ends']
    node['transitions'][-1]['target_node'] = 'verify'
    # A variable the stage only records, without routing on it, is not checked.
    node['transitions'] = node['transitions'][:1] + node['transitions'][-1:]
    assert not validate(spec, contracts, requirements)['dead_ends']


def test_diagnosis_evidence_carries_failed_call_steps(work, spec, requirements):
    from builder.build import call_evidence
    from builder.diagnostics import grounded_diagnoses
    turns = [{'role': 'assistant', 'node': 'verify', 'text': f'turn {i}'} for i in range(100)]
    write_json(work / 'calls_0.json', {'bad': {'call_id': 'c1', 'turns': turns}, 'good': {'call_id': 'c2', 'turns': turns[:2]}})
    raw = {'all_rows': [[{'id': 'bad', 'pass': False, 'failed': ['stuck']}, {'id': 'good', 'pass': True, 'failed': []}], [{'id': 'bad', 'pass': False, 'failed': ['no record']}]]}
    calls = call_evidence(work, raw)
    assert list(calls[0]) == ['bad'] and calls[1] == {}
    assert len(calls[0]['bad']['turns']) == 80 and calls[0]['bad']['turns_omitted'] == 20 and calls[0]['bad']['turns'][-1]['text'] == 'turn 99'
    d = {'case_id': 'bad', 'rule_ids': ['R1'], 'evidence_refs': ['calls.0.bad.turns.3'], 'likely_workflow_nodes': ['verify'], 'confidence': .8}
    assert grounded_diagnoses([d], {**raw, 'calls': calls}, requirements, spec['workflow'], {'bad'}) == [d]


def test_business_day_expectations_are_calculated_by_the_controller():
    from builder.scenarios import reconcile_probes
    # 2031-03-03 is a Monday; with the 5th excluded the fourth business day after it is the 10th.
    entry = {'variable': 'deadline', 'anchor': '2031-03-03T11:00', 'weekdays': [0, 1, 2, 3, 4], 'excluded_dates': ['2031-03-05'], 'count': 4}
    probe = {'probe_id': 'P', 'rule_ids': ['R1'], 'node_id': 'calc', 'variables': {'now': '2031-03-03T11:00', 'asked': '2031-03-20'},
             'expected': {'deadline': '2031-03-07', 'band': 'late', 'echo': '2031-03-20', 'today': '2031-03-03', 'guess': '2031-03-14'}, 'rationale': '', 'calendar': [entry]}
    fixed, notes = reconcile_probes({'probes': [probe]})
    # The model's 7th is replaced, inputs echoed back stay, and a date nobody calculated is not a test.
    assert fixed['probes'][0]['expected'] == {'deadline': '2031-03-10', 'band': 'late', 'echo': '2031-03-20', 'today': '2031-03-03'}
    assert any('set to calculated 2031-03-10' in n for n in notes) and any('guess removed' in n for n in notes)
    # Unusable parameters, or nothing verifiable left: no test rather than a wrong one.
    assert reconcile_probes({'probes': [{**probe, 'calendar': [{**entry, 'weekdays': [9]}]}]})[0] == {'probes': []}
    assert reconcile_probes({'probes': [{**probe, 'calendar': [], 'expected': {'deadline': '2031-03-07'}}]})[0] == {'probes': []}


def test_malformed_proposal_gets_named_errors_not_a_crash(spec, contracts, requirements):
    broken = deepcopy(spec)
    broken['workflow']['nodes']['verify']['tools'] = [True]
    broken['workflow']['nodes']['stray'] = [{'operation': 'get_account'}]
    result = validate({**broken, 'workflow': compile_tools(broken['workflow'], contracts)}, contracts, requirements)
    assert not result['valid'] and any('stray: node must be an object' in e for e in result['errors']) and any('verify: tools must be an array of objects' in e for e in result['errors'])
    broken['workflow']['nodes'] = ['verify']
    with pytest.raises(ValueError, match='workflow.nodes must be an object'):
        compile_tools(broken['workflow'], contracts)


def test_repair_patch_changes_only_what_it_names(spec):
    from builder.validation import apply_patch
    node = deepcopy(spec['workflow']['nodes']['verify'])
    node['task_message'] = 'Ask the security question.'
    patched = apply_patch(spec, {'operations': [{'op': 'set_node', 'target': 'verify', 'value': node}], 'tool_gates': [], 'summary': 'x'})
    assert patched['workflow']['nodes']['verify']['task_message'] == 'Ask the security question.' and spec['workflow']['nodes']['verify']['task_message'] != 'Ask the security question.'
    assert {k: v for k, v in patched['workflow']['nodes'].items() if k != 'verify'} == {k: v for k, v in spec['workflow']['nodes'].items() if k != 'verify'}
    assert patched['tool_gates'] == spec['tool_gates'] and patched['coverage'] == spec['coverage']
    for bad in ([{'op': 'set_node', 'target': 'verify', 'value': spec['workflow']['nodes']['verify']}], [{'op': 'set_node', 'target': 'verify', 'value': {'name': 'other'}}],
                [{'op': 'remove_node', 'target': 'nowhere'}], []):
        with pytest.raises(ValueError):
            apply_patch(spec, {'operations': bad, 'tool_gates': [], 'summary': 'x'})


def test_accepted_offer_that_is_never_applied_is_a_dead_end(spec, contracts, requirements):
    def code(name, source, targets):
        return {'name': name, 'node_type': 'code', 'passthrough': True, 'passthrough_default_transition': targets[-1][0],
                'pre_actions': [{'type': 'function', 'function': {'name': 'run', 'handler': '__function__:code_exec', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string', 'default': source}}}}}],
                'transitions': [{'target_node': t, 'description': 'next', 'condition': c} for t, c in targets]}
    always = {'operator': 'always'}
    nodes = spec['workflow']['nodes']
    nodes['account']['transitions'] = [{'target_node': 'check', 'description': 'Check the day', 'condition': always}]
    nodes['account']['passthrough_default_transition'] = 'check'
    nodes['check'] = code('check', "try:\n    vars['status'] = 'ok' if vars.get('day') == 'x' else 'late'\n    vars['offer'] = 'y'\nexcept Exception:\n    vars['status'] = 'late'",
                          [('close', {'logic': 'or', 'conditions': [{'variable': 'status', 'operator': 'equals', 'operand': 'ok'}]}), ('offer_day', always)])
    nodes['offer_day'] = {'name': 'offer_day', 'node_type': 'conversation', 'task_message': 'The status is {{status}}. Offer {{offer}} instead.', 'max_node_turns': 3, 'max_turn_transition': 'close',
                          'extraction_schema': [{'name': 'reply', 'type': 'string', 'enum_values': ['accept', 'refuse'], 'description': 'Answer.', 'min_confidence': 0.7}],
                          'transitions': [{'target_node': 'check', 'description': 'Accepted', 'condition': {'logic': 'or', 'conditions': [{'variable': 'reply', 'operator': 'equals', 'operand': 'accept'}]}},
                                          {'target_node': 'close', 'description': 'Refused', 'condition': {'logic': 'or', 'conditions': [{'variable': 'reply', 'operator': 'equals', 'operand': 'refuse'}]}},
                                          {'target_node': 'close', 'description': 'Otherwise', 'condition': always}]}
    result = validate(spec, contracts, requirements)
    assert result['valid'], result['errors']
    assert len(result['dead_ends']) == 1 and "offer_day: offers ['offer']" in result['dead_ends'][0]
    # Applying the accepted offer before the check runs again is what makes the round trip progress.
    nodes['apply_offer'] = code('apply_offer', "try:\n    vars['day'] = vars.get('offer', '')\nexcept Exception:\n    vars['day'] = ''", [('check', always)])
    nodes['offer_day']['transitions'][0]['target_node'] = 'apply_offer'
    result = validate(spec, contracts, requirements)
    assert result['valid'] and not result['dead_ends'], result


def test_vague_period_is_not_extracted_as_a_day(contracts):
    from builder import runtime
    workflow = {'nodes': {'ask': {'name': 'ask', 'node_type': 'conversation', 'extraction_schema': [{'name': 'pay_day', 'type': 'date', 'description': 'The day the customer will pay.', 'min_confidence': 0.7}], 'transitions': []}}, 'global_nodes': {}}
    once = runtime.apply(deepcopy(workflow), contracts)
    item = once['nodes']['ask']['extraction_schema'][0]
    assert item['type'] == 'string' and runtime.SINGLE_DAY in item['description']
    assert runtime.apply(deepcopy(once), contracts) == once


def test_simulations_go_first_to_mutations_aimed_at_failed_customers():
    from builder.build import Builder
    feedback = {'diagnostics': [{'case_id': 'a', 'likely_workflow_nodes': ['ask_day']}, {'case_id': 'b', 'likely_workflow_nodes': ['ask_day', 'confirm']}, {'case_id': 'c', 'likely_workflow_nodes': ['close']}]}
    edit = lambda *nodes: {'operations': [{'op': 'set_node', 'target': n, 'value': {}} for n in nodes]}
    assert [Builder.failed_cases_addressed(feedback, edit(*n)) for n in (['ask_day'], ['close'], ['greeting'], ['confirm', 'close'])] == [2, 1, 0, 2]
    assert Builder.failed_cases_addressed({'strict_pass_rate': 0.5}, edit('ask_day')) == 0
