"""Controller tests use explicit fakes; their scores are not real Freya evidence."""
from contextlib import contextmanager
from copy import deepcopy
import json
import multiprocessing
import time

from conftest import route
from builder import runtime
from builder.artifacts import digest, write_json
from builder.build import Builder
from builder.config import KIT, Config, Deadline
from builder.freya_adapter import file_lock

BRIEF = [KIT / 'briefs/brief-a.md']
CASES = ['PUB-01', 'PUB-02', 'PUB-03']


class FakeFreya:
    """Deploys nothing. `outcomes(workflow)` decides, per customer, whether the call passes and which stages it visits."""
    outcomes = staticmethod(lambda workflow: {})

    def __init__(self, cfg, deadline, trace):
        self.cfg, self.deadline, self.trace = cfg, deadline, trace
        self.deployment, self.exporting, self.version, self.simulated = None, False, 0, []
    @contextmanager
    def workspace(self):
        yield self
    def validate_remote(self, workflow):
        return None
    def deploy(self, slot, workflow):
        self.version += 1
        self.deployment = {'workflow_id': 'FAKE-workflow', 'agent_id': 'FAKE-agent', 'version': self.version, 'workflow_hash': digest(workflow), 'workflow': workflow}
        return self.deployment
    def export(self, workflow, path):
        write_json(path, {'workflow_id': 'FAKE-workflow', 'agent_id': 'FAKE-agent', 'workflow': workflow, 'test_only': True})
        return str(path)
    def evaluate(self, cases, suite, folder):
        results = self.outcomes(self.deployment['workflow'])
        self.simulated.append(self.deployment['workflow_hash'])
        rows = [{'id': c, 'pass': results.get(c, (True, []))[0], 'failed': [] if results.get(c, (True, []))[0] else [f'{c} did not end as expected']} for c in suite.case_ids]
        write_json(folder / 'calls_0.json', {c: {'call_id': c, 'turns': [{'role': 'assistant', 'node': stage, 'text': 'spoken'} for stage in results.get(c, (True, []))[1]]} for c in suite.case_ids})
        raw = {'all_rows': [rows], 'simulations': []}
        write_json(folder / 'raw_runner.json', raw)
        return raw


def roles(spec, requirements, patches, seen):
    """Analyst and designer return fixtures; each fix call returns the next scripted patch."""
    patches = list(patches)
    class FakeRoles:
        def __init__(self, cfg, deadline, trace, root):
            self.calls = 0
        def ask(self, role, purpose, instruction, payload, schema, max_tokens=None):
            self.calls += 1
            seen.append((role, deepcopy(payload)))
            if role == 'BriefAnalystAgent':
                bundle = deepcopy(requirements)
                doc = payload['documents'][0]
                bundle['requirements'][0]['source'].update(path=doc['path'], start_line=1, end_line=len(doc['text'].splitlines()), span=doc['text'].strip())
                return bundle
            if role == 'ADASDesignerAgent':
                return deepcopy(spec)
            if role == 'FixAgent':
                patch = patches.pop(0) if patches else {'fixes': []}
                if isinstance(patch, Exception):
                    raise patch
                return deepcopy(patch)
            raise AssertionError(role)
    return FakeRoles


def fix(*edits, problem='fixture', cases=()):
    return {'problem': problem, 'cases': list(cases), 'edits': [{'op': op, 'stage': stage, 'field': field, 'value': value} for op, stage, field, value in edits]}


def code(marker):
    return f"try:\n    vars['{marker}'] = 'set'\nexcept Exception:\n    vars['{marker}'] = ''\n"


def chain(spec):
    """account -> step_a -> step_b -> close, so two fixes can touch two different stages."""
    nodes = spec['workflow']['nodes']
    nodes['account']['transitions'] = [route('step_a')]
    nodes['step_a'] = {'name': 'step_a', 'node_type': 'code', 'code': code('a'), 'transitions': [route('step_b')]}
    nodes['step_b'] = {'name': 'step_b', 'node_type': 'code', 'code': code('b'), 'transitions': [route('close')]}
    return spec


def build(work, spec, requirements, patches=(), freya=FakeFreya, outcomes=None, only=CASES, briefs=BRIEF, **config):
    seen = []
    adapter = type('Freya', (freya,), {'outcomes': staticmethod(outcomes)}) if outcomes else freya
    builder = Builder(Config(artifacts=work, tracing=False, **config), briefs, KIT / 'tools/openapi.json', roles_factory=roles(spec, requirements, patches, seen), adapter_factory=adapter, only=only)
    builder.submission_dir = work / 'out'  # tests never overwrite the real submission output
    return builder, builder.run(), seen


def lineage(builder):
    return [json.loads(line) for line in (builder.root / 'lineage.jsonl').read_text().splitlines()]


def kinds(builder):
    return [e['mutation_kind'] for e in lineage(builder) if e['event'] == 'candidate_created']


def created(builder, cid):
    """A candidate's archive record, read from the lineage file (the database is closed after a run)."""
    return next(e for e in lineage(builder) if e['event'] == 'candidate_created' and e['candidate_id'] == cid)


def fixes_seen(seen):
    return [payload for role, payload in seen if role == 'FixAgent']


# ------------------------------------------------------------------ root

def test_compiler_errors_are_fixed_by_patch_and_a_brief_without_customers_is_exported(work, spec, requirements):
    policy = work / 'policy.md'
    policy.write_text('Verify first.\n')
    spec['workflow']['nodes']['verify']['max_turn_transition'] = 'end'  # skips close_call
    patch = {'fixes': [fix(('set_field', 'verify', 'max_turn_transition', 'close'), problem='verify can end the call without close_call')]}
    builder, result, seen = build(work, spec, requirements, [patch], only=None, briefs=[policy])
    assert result['status'] == 'exported' and result['export_path'] and result['simulations'] == 0 and result['strict_pass_rate'] is None
    assert kinds(builder) == ['design', 'compile_fix'] and builder.static[result['candidate_id']]['valid']
    asked = fixes_seen(seen)
    assert len(asked) == 1 and 'close_call' in asked[0]['problems']['compiler'][0] and 'runtime_docs' in asked[0] and 'calls' not in asked[0]
    # The model is shown the compact source, never the compiled workflow.
    shown = json.dumps(asked[0]['workflow'])
    assert 'bank_operation' in shown and runtime.START not in shown and '__function__:api_call' not in shown
    exported = json.loads((builder.root / 'champion.workflow.json').read_text())['workflow']
    assert exported['nodes']['verify']['max_turn_transition'] == 'close' and '__function__:api_call' in json.dumps(exported)
    assert 'measurement_skipped' in (builder.root / 'build_trace.log').read_text()


def test_unusable_patches_are_reported_back_and_the_least_flawed_design_ships(work, spec, requirements):
    spec['workflow']['nodes']['verify']['max_turn_transition'] = 'end'
    garbled = {'fixes': [fix(('set_field', 'nowhere', 'task_message', 'x'), problem='wrong stage')]}
    builder, result, seen = build(work, spec, requirements, [garbled, {'fixes': []}], max_simulations=0)
    asked = fixes_seen(seen)
    assert len(asked) == 2 and "Your fix 'wrong stage' was not applied" in asked[1]['problems']['compiler'][0] and 'no such stage' in asked[1]['problems']['compiler'][0]
    assert result['status'] == 'exported_best_effort' and result['best_effort_root'] and result['candidate_id'] == result['root_candidate_id']
    assert kinds(builder) == ['design']


def test_design_that_freya_rejects_is_never_pinned(work, spec, requirements):
    class RejectingFreya(FakeFreya):
        def validate_remote(self, workflow):
            raise ValueError('Platform rejected a documented field')
        def deploy(self, slot, workflow):
            raise AssertionError('A rejected design must not be deployed')
    reword = lambda n: {'fixes': [fix(('set_workflow_field', '', 'system_prompt', f'Follow the input policy. Attempt {n}.'))]}
    builder, result, seen = build(work, spec, requirements, [reword(1), reword(2)], freya=RejectingFreya)
    assert result['status'] == 'failed' and not result['export_path'] and not (builder.root / 'pinned_root.json').exists()
    asked = fixes_seen(seen)
    assert len(asked) == 2 and 'Freya dry-run rejected' in asked[0]['problems']['compiler'][0]


def test_a_dry_run_that_gets_no_answer_is_not_a_rejection(work, spec, requirements):
    class SlowFreya(FakeFreya):
        def validate_remote(self, workflow):
            raise TimeoutError('Freya operation exceeded remaining budget')
    builder, result, seen = build(work, spec, requirements, freya=SlowFreya, max_simulations=0)
    assert result['status'] == 'exported' and builder.static[result['candidate_id']]['valid'] and not fixes_seen(seen)


def test_rule_extraction_failure_is_not_fatal(work, spec, requirements):
    requirements['requirements'][0]['precedence']['supersedes'] = ['R404']  # refers to a rule that does not exist
    builder, result, seen = build(work, spec, requirements, max_simulations=0)
    assert result['status'] == 'exported' and [role for role, _ in seen] == ['BriefAnalystAgent', 'BriefAnalystAgent', 'ADASDesignerAgent']
    assert 'requirements' not in seen[-1][1] and 'requirements_unavailable' in (builder.root / 'build_trace.log').read_text()


def test_resume_reuses_the_root_without_model_calls(work, spec, requirements):
    first, a, _ = build(work, spec, requirements, max_simulations=0)
    seen = []
    builder = Builder(Config(artifacts=work, tracing=False, max_simulations=0), BRIEF, KIT / 'tools/openapi.json', roles_factory=roles(spec, requirements, [], seen), adapter_factory=FakeFreya, resume=first.root)
    builder.submission_dir = work / 'out'
    b = builder.run()
    assert not seen and b['status'] == 'exported' and created(builder, b['candidate_id'])['source_sha256'] == created(first, a['candidate_id'])['source_sha256']


# ------------------------------------------------------------------ improving

def test_each_fix_is_kept_or_blamed_alone_and_a_blamed_one_is_branched_away(work, spec, requirements):
    def outcomes(workflow):
        a, b = (json.dumps(workflow['nodes'][key]) for key in ('step_a', 'step_b'))
        return {'PUB-01': ('B_FIX' not in b, ['verify', 'account', 'step_b', 'close']),          # passes until fix B breaks it
                'PUB-02': ('A_FIX' in a, ['verify', 'account', 'step_a', 'close']),              # repaired by fix A
                'PUB-03': ('B_FIX' in b or 'C_FIX' in b, ['verify', 'account', 'step_b', 'close'])}  # repaired by B, or properly by C
    first = {'fixes': [fix(('set_field', 'step_a', 'code', code('A_FIX')), problem='A', cases=['PUB-02']), fix(('set_field', 'step_b', 'code', code('B_FIX')), problem='B', cases=['PUB-03'])]}
    second = {'fixes': [fix(('set_field', 'step_b', 'code', code('C_FIX')), problem='C', cases=['PUB-03'])]}
    builder, result, seen = build(work, chain(spec), requirements, [first, second], outcomes=outcomes)
    assert kinds(builder) == ['design', 'fixes', 'revert_branch', 'fixes']
    assert [(h['problem'], h['status']) for h in builder.history] == [('A', 'kept'), ('B', 'blamed'), ('C', 'kept')]
    assert result['status'] == 'exported' and result['strict_pass_rate'] == 1 and result['simulations'] == 3 and result['fixes']['blamed'] == 1
    exported = json.dumps(json.loads((builder.root / 'champion.workflow.json').read_text())['workflow'])
    assert 'A_FIX' in exported and 'C_FIX' in exported and 'B_FIX' not in exported
    asked = fixes_seen(seen)
    # Round one sees only the failed calls; round two is told what was blamed and still owes PUB-03.
    assert sorted(asked[0]['calls']) == ['PUB-02', 'PUB-03'] and asked[0]['problems']['passing'] == ['PUB-01'] and asked[0]['history'] == []
    assert [c['case'] for c in asked[1]['problems']['failed_calls']] == ['PUB-03'] and 'PUB-01' in asked[1]['history'][1]['note'] and asked[1]['history'][1]['status'] == 'blamed'
    assert 'A_FIX' in json.dumps(asked[1]['workflow']) and 'B_FIX' not in json.dumps(asked[1]['workflow'])
    judged = [e for e in lineage(builder) if e['event'] == 'fixes_judged']
    assert judged[0]['blamed'] == ['B'] and judged[0]['kept'] == ['A'] and judged[0]['regressed'] == ['PUB-01']


def test_a_regression_no_fix_touched_is_noise_and_the_measured_best_is_exported(work, spec, requirements):
    def outcomes(workflow):
        fixed = 'A_FIX' in json.dumps(workflow['nodes']['step_a'])
        return {'PUB-01': (not fixed, ['verify', 'close']),                      # fails on the child without visiting an edited stage
                'PUB-02': (False, ['verify', 'account', 'step_a', 'close']),
                'PUB-03': (not fixed, ['verify', 'close'])}
    patch = {'fixes': [fix(('set_field', 'step_a', 'code', code('A_FIX')), problem='A', cases=['PUB-02'])]}
    builder, result, seen = build(work, chain(spec), requirements, [patch], outcomes=outcomes)
    assert [(h['problem'], h['status']) for h in builder.history] == [('A', 'kept')]
    # The child scored lower, so the root stays the export even though nothing could be blamed.
    assert result['candidate_id'] == result['root_candidate_id'] and result['final_score']['passed'] == 2 and result['simulations'] == 2


def test_wording_is_committed_without_a_simulation(work, spec, requirements):
    patch = {'fixes': [fix(('set_field', 'verify', 'task_message', 'Ask for the date of birth first.'), problem='unclear instruction', cases=['PUB-01'])]}
    builder, result, seen = build(work, spec, requirements, [patch], outcomes=lambda workflow: {'PUB-01': (False, ['verify'])})
    assert kinds(builder) == ['design', 'wording'] and result['simulations'] == 1 and len(fixes_seen(seen)) == 1
    assert result['candidate_id'] != result['root_candidate_id'] and result['wording_untested'] and result['strict_pass_rate'] == 2 / 3
    assert builder.history[0]['status'] == 'untested'
    assert 'Ask for the date of birth first.' in (builder.root / 'champion.workflow.json').read_text()


def test_without_room_for_a_simulation_only_wording_is_committed(work, spec, requirements):
    patch = {'fixes': [fix(('set_field', 'step_a', 'code', code('A_FIX')), problem='logic'), fix(('set_field', 'verify', 'task_message', 'Ask once.'), problem='wording')]}
    builder, result, seen = build(work, chain(spec), requirements, [patch], outcomes=lambda workflow: {'PUB-01': (False, ['verify'])}, max_simulations=1)
    assert fixes_seen(seen)[0]['wording_only'] is True and result['simulations'] == 1
    assert [(h['problem'], h['status']) for h in builder.history] == [('logic', 'rejected'), ('wording', 'untested')] and 'only wording' in builder.history[0]['note']
    exported = (builder.root / 'champion.workflow.json').read_text()
    assert 'Ask once.' in exported and 'A_FIX' not in exported


def test_wording_for_the_export_is_written_from_the_calls_of_the_exported_agent(work, spec, requirements):
    def outcomes(workflow):
        fixed = 'A_FIX' in json.dumps(workflow['nodes']['step_a'])
        return {'PUB-01': (not fixed, ['verify', 'close']),   # lost on the child, without visiting the edited stage
                'PUB-02': (False, ['verify', 'account', 'step_b' if fixed else 'step_a'])}
    first = {'fixes': [fix(('set_field', 'step_a', 'code', code('A_FIX')), problem='A', cases=['PUB-02'])]}
    second = {'fixes': [fix(('set_field', 'verify', 'task_message', 'Ask once.'), problem='wording', cases=['PUB-02'])]}
    builder, result, seen = build(work, chain(spec), requirements, [first, second], outcomes=outcomes, max_simulations=2)
    asked = fixes_seen(seen)
    # The child scored lower, so the root is what will be exported; the wording round is shown the root and the root's own call.
    assert asked[1]['wording_only'] is True and 'A_FIX' not in json.dumps(asked[1]['workflow'])
    assert [c['case'] for c in asked[1]['problems']['failed_calls']] == ['PUB-02']
    assert [turn['node'] for turn in asked[1]['calls']['PUB-02']['turns']] == ['verify', 'account', 'step_a']
    exported = (builder.root / 'champion.workflow.json').read_text()
    assert result['wording_untested'] and 'Ask once.' in exported and 'A_FIX' not in exported


def test_a_kept_fix_that_stood_on_a_blamed_one_is_not_reported_as_kept(work, spec, requirements):
    def outcomes(workflow):
        return {'PUB-01': ('extra' not in workflow['nodes'], ['verify', 'account', 'step_b', 'close']),
                'PUB-02': (False, ['verify'])}
    patch = {'fixes': [fix(('set_stage', 'extra', '', {'node_type': 'code', 'code': code('x'), 'transitions': [route('close')]}), ('set_field', 'step_b', 'transitions', [route('extra')]), problem='B', cases=['PUB-02']),
                       fix(('set_field', 'extra', 'code', code('D_FIX')), problem='D', cases=['PUB-02'])]}
    builder, result, seen = build(work, chain(spec), requirements, [patch], outcomes=outcomes)
    assert {h['problem']: h['status'] for h in builder.history} == {'B': 'blamed', 'D': 'rejected'} and kinds(builder) == ['design', 'fixes']
    assert result['candidate_id'] == result['root_candidate_id'] and 'D_FIX' not in (builder.root / 'champion.workflow.json').read_text()


def test_a_fix_that_cannot_be_applied_is_dropped_alone(work, spec, requirements):
    def outcomes(workflow):
        return {'PUB-01': ('A_FIX' in json.dumps(workflow['nodes']['step_a']), ['verify', 'account', 'step_a'])}
    patch = {'fixes': [fix(('set_field', 'nowhere', 'code', 'x'), problem='lost'), fix(('set_field', 'step_a', 'code', code('A_FIX')), problem='A', cases=['PUB-01']),
                       fix(('set_field', 'verify', 'max_turn_transition', 'end'), problem='breaks close')]}
    builder, result, seen = build(work, chain(spec), requirements, [patch], outcomes=outcomes)
    assert {h['problem']: h['status'] for h in builder.history} == {'lost': 'rejected', 'breaks close': 'rejected', 'A': 'kept'}
    assert 'adds compiler errors' in next(h['note'] for h in builder.history if h['problem'] == 'breaks close')
    assert result['strict_pass_rate'] == 1 and result['simulations'] == 2


def test_a_crash_while_improving_still_exports_the_root(work, spec, requirements):
    builder, result, seen = build(work, spec, requirements, [RuntimeError('forced failure')], outcomes=lambda workflow: {'PUB-01': (False, ['verify'])})
    assert result['status'] == 'exported_with_errors' and result['candidate_id'] == result['root_candidate_id'] and result['export_path']
    assert digest(json.loads((builder.root / 'champion.workflow.json').read_text())['workflow']) == created(builder, result['root_candidate_id'])['workflow_sha256']


def test_cached_real_export_survives_restore_outage(work, spec, requirements):
    class RestoreOutage(FakeFreya):
        def deploy(self, slot, workflow):
            if self.exporting:
                raise ConnectionError('forced restore outage')
            return super().deploy(slot, workflow)
    builder, result, seen = build(work, spec, requirements, freya=RestoreOutage, max_simulations=0)
    assert result['status'] == 'exported_cached' and result['remote_restored'] is False and result['export_path'] and result['strict_pass_rate'] is None


# ------------------------------------------------------------------ workspace

def lock_worker(path, queue):
    with file_lock(path, Deadline(10)):
        start = time.monotonic()
        time.sleep(.05)
        queue.put((start, time.monotonic()))


def test_workspace_lock_serializes(work):
    context = multiprocessing.get_context('fork')
    queue = context.Queue()
    processes = [context.Process(target=lock_worker, args=(work / 'lock', queue)) for _ in range(2)]
    for process in processes: process.start()
    intervals = sorted(queue.get(timeout=3) for _ in processes)
    for process in processes:
        process.join(3)
        assert process.exitcode == 0
    assert intervals[1][0] >= intervals[0][1]
