"""Controller tests use explicit fakes; their scores are not real Freya evidence."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
import multiprocessing
import time

from builder.artifacts import digest, write_json
from builder.build import Builder
from builder.config import AGENT, KIT, Config, Deadline
from builder.freya_adapter import file_lock
from builder.scoring import Suite


class FakeFreya:
    def __init__(self, cfg, deadline, trace):
        self.cfg, self.deadline, self.trace = cfg, deadline, trace
        self.deployment = None
        self.exporting = False
        self.evaluations = 0
        self.version = 0
    @contextmanager
    def workspace(self):
        yield self
    def deploy(self, slot, workflow):
        self.version += 1
        self.deployment = {'workflow_id': 'FAKE-workflow', 'agent_id': 'FAKE-agent', 'version': self.version, 'workflow_hash': digest(workflow)}
        return self.deployment
    def validate_remote(self, workflow):
        return None
    def export(self, workflow, path):
        write_json(path, {'workflow_id': 'FAKE-workflow', 'agent_id': 'FAKE-agent', 'workflow': workflow, 'test_only': True})
        return str(path)
    def evaluate(self, cases, suite, folder):
        self.evaluations += 1
        passed = self.evaluations > 1
        raw = {'all_rows': [[{'id': c, 'pass': passed, 'failed': [] if passed else ['LEAK_TEST_SENTINEL']} for c in suite.case_ids] for _ in range(suite.repetitions)]}
        write_json(folder / 'raw_runner.json', raw)
        return raw


def fake_roles_factory(spec, requirements, seen, crash=False):
    class FakeRoles:
        def __init__(self, cfg, deadline, trace, root):
            self.calls = 0
        def ask(self, role, purpose, instruction, payload, schema, model=None):
            self.calls += 1
            seen.append((role, deepcopy(payload)))
            if role == 'BriefAnalystAgent':
                bundle = deepcopy(requirements)
                doc = payload['documents'][0]
                bundle['requirements'][0]['source'].update(path=doc['path'], start_line=1, end_line=len(doc['text'].splitlines()), span=doc['text'].strip())
                return bundle
            if role == 'ADASDesignerAgent': return deepcopy(spec)
            if role == 'DiagnosisAgent':
                return {'diagnoses': [{'case_id': 'PUB-01', 'rule_ids': ['R1'], 'evidence_refs': ['all_rows.0.0.failed.0'], 'failure_type': 'fixture_failure', 'likely_workflow_nodes': ['verify'], 'repair_hypothesis': '[REDACTED TEST FIXTURE: LEAK_TEST_SENTINEL]', 'confidence': .9, 'counterfactual_test': 'Run corrected input', 'status': 'hypothesis'}]}
            if role == 'MutationDesignerAgent':
                if crash: raise RuntimeError('forced mutation failure')
                proposals = []
                for i, kind in enumerate(['adjust_prompt', 'change_route', 'add_guard']):
                    node = deepcopy(payload['parent']['workflow']['nodes']['verify'])
                    if i == 0: node['task_message'] += ' Ask once more if unclear.'
                    elif i == 1: node['max_node_turns'] = 11
                    else: node['transitions'][0]['description'] = 'Only enter account after verified result.'
                    proposals.append({'parent_id': payload['parent_id'], 'mutation_type': kind, 'target_nodes': ['verify'], 'target_rule_ids': ['R1'], 'hypothesis': f'Fixture change {i}', 'operations': [{'op': 'set_node', 'target': 'verify', 'value': node}], 'expected_effect': 'Test patch handling', 'risk': 'low', 'coverage': spec['coverage']})
                return {'proposals': proposals}
            raise AssertionError(role)
    return FakeRoles


def run_fake(work, spec, requirements, mode, seen, pinned=None, crash=False):
    cfg = Config(mode=mode, artifacts=work, tracing=False, max_candidates=4, max_depth=1, max_simulations=4)
    builder = Builder(cfg, [KIT / 'briefs/brief-a.md'], KIT / 'tools/openapi.json', roles_factory=fake_roles_factory(spec, requirements, seen, crash), adapter_factory=FakeFreya, pinned=pinned, only=['PUB-01'])
    # Do not allow tests to overwrite the real submission output.
    builder.submission_dir = work / 'out'
    result = builder.run()
    return builder, result


def test_paired_isolation_and_lineage(work, spec, requirements):
    first_seen, second_seen = [], []
    first, a = run_fake(work, spec, requirements, 'scoring_only', first_seen)
    second, b = run_fake(work, spec, requirements, 'scoring_with_diagnostics', second_seen, first.root / 'pinned_root.json')
    assert a['status'] == b['status'] == 'exported'
    assert a['root_hash'] == b['root_hash']
    assert a['root_score'] == b['root_score']
    assert a['run_id'] != b['run_id']
    assert a['strict_pass_rate'] == b['strict_pass_rate'] == 1
    assert a['valid_candidates'] == b['valid_candidates'] == 4
    scalar_payloads = [payload for role, payload in first_seen if role == 'MutationDesignerAgent']
    diagnostic_payloads = [payload for role, payload in second_seen if role == 'MutationDesignerAgent']
    assert 'LEAK_TEST_SENTINEL' not in json.dumps(scalar_payloads)
    assert 'LEAK_TEST_SENTINEL' in json.dumps(diagnostic_payloads[0]['feedback']['diagnostics'])
    assert not any(role == 'DiagnosisAgent' for role, _ in first_seen)
    assert json.loads((first.root / 'champion.json').read_text())['champion_id'] == a['candidate_id']
    assert 'relative_rank' in (first.root / 'lineage.jsonl').read_text()


def test_failure_restores_root(work, spec, requirements):
    builder, result = run_fake(work, spec, requirements, 'scoring_only', [], crash=True)
    assert result['status'] == 'exported_with_errors'
    assert result['candidate_id'] == result['root_candidate_id']
    assert result['export_path']
    exported = json.loads((builder.root / 'champion.workflow.json').read_text())['workflow']
    assert digest(exported) == result['root_hash']


def test_resume_revalidates_saved_proposal_without_model_call(work, spec, requirements):
    policy = work / 'policy.md'
    policy.write_text('Verify first.\n')
    requirements['requirements'][0]['source']['path'] = str(policy)
    cfg = Config(artifacts=work, tracing=False, official=False, max_depth=0)
    seen = []
    roles = fake_roles_factory(spec, requirements, seen)
    old = Builder(cfg, [policy], KIT / 'tools/openapi.json', roles_factory=roles)
    write_json(old.root / 'requirements.json', requirements)
    old.archive.add(spec, mutation_kind='baseline')
    old.archive.db.close()
    resumed = Builder(cfg, [policy], KIT / 'tools/openapi.json', roles_factory=roles, resume=old.root)
    try:
        candidate = resumed.compile()
        # The archived candidate is the saved proposal plus controller-owned runtime support only.
        from builder.contracts import compile_openapi, compile_tools
        compiled = compile_tools(spec['workflow'], compile_openapi(KIT / 'tools/openapi.json'))
        assert resumed.archive.spec(candidate) == {**spec, 'workflow': compiled}
        assert not seen
    finally:
        resumed.archive.db.close()


def test_probe_referee_cannot_see_implementation_or_observations(work, requirements):
    builder = Builder.__new__(Builder)
    builder.probes, builder.pinned, builder.resume = {'probes': []}, None, None
    builder.cfg, builder.root = Config(), work
    builder.requirements, builder.documents = requirements, [{'text': 'Source policy'}]
    spec = {'workflow': {'nodes': {'calc': {'node_type': 'code', 'pre_actions': [{'function': {'parameters': {'properties': {'code': {'default': "vars['deadline'] = '2031-03-05'"}}}}}]}}}}
    seen = []
    class Roles:
        def ask(self, role, purpose, instruction, payload, schema, model=None):
            seen.append((role, payload))
            return {'probes': [{'probe_id': 'date', 'rule_ids': ['R1'], 'node_id': 'calc', 'variables': {}, 'expected': {'deadline': '2031-03-05'}, 'rationale': 'Source-derived'}]}
    builder.roles = Roles()
    builder.prepare_probes(spec)
    assert [role for role, _ in seen] == ['ScenarioPlannerAgent', 'ScenarioRefereeAgent']
    assert set(seen[1][1]) == {'documents', 'requirements', 'proposed_probes'}
    assert 'code' not in json.dumps(seen[1][1])


def test_remote_schema_rejection_repairs_before_pinning(work, spec, requirements):
    seen = []
    base = fake_roles_factory(spec, requirements, seen)
    class Roles(base):
        def ask(self, role, purpose, instruction, payload, schema, model=None):
            if role == 'WorkflowCompilerAgent':
                self.calls += 1
                seen.append((role, deepcopy(payload)))
                changed = deepcopy(spec)  # a real repair returns a changed proposal; an unchanged one stops the loop
                changed['workflow']['system_prompt'] += f' Repair {self.calls}.'
                return changed
            return super().ask(role, purpose, instruction, payload, schema, model)
    class RejectingFreya(FakeFreya):
        def validate_remote(self, workflow):
            raise ValueError('Platform rejected a documented field')
        def deploy(self, slot, workflow):
            raise AssertionError('Invalid root must not deploy')
    cfg = Config(artifacts=work, tracing=False, max_depth=0)
    builder = Builder(cfg, [KIT / 'briefs/brief-a.md'], KIT / 'tools/openapi.json', roles_factory=Roles, adapter_factory=RejectingFreya)
    result = builder.run()
    assert result['status'] == 'failed' and result['invalid_candidates'] == 3
    assert not (builder.root / 'pinned_root.json').exists()
    repairs = [payload for role, payload in seen if role == 'WorkflowCompilerAgent']
    assert len(repairs) == 2 and 'Freya dry-run rejected' in repairs[0]['compiler_errors'][0]


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


def test_cached_real_export_survives_restore_outage(work, spec, requirements):
    class RestoreOutage(FakeFreya):
        def deploy(self, slot, workflow):
            if self.exporting:
                raise ConnectionError('forced restore outage')
            return super().deploy(slot, workflow)
    cfg = Config(mode='scoring_only', artifacts=work, tracing=False, max_depth=0, max_simulations=0)
    builder = Builder(cfg, [KIT / 'briefs/brief-a.md'], KIT / 'tools/openapi.json', roles_factory=fake_roles_factory(spec, requirements, []), adapter_factory=RestoreOutage, only=['PUB-01'])
    builder.submission_dir = work / 'out'
    result = builder.run()
    assert result['status'] == 'exported_cached' and result['remote_restored'] is False
    assert result['export_path']
    assert result['strict_pass_rate'] is None
