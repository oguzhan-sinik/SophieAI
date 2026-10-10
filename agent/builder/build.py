"""Unattended brief-first build, evaluate, evolve and export CLI."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import sys
import time
import uuid

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'builder'

from .adk import ADKRoles
from .artifacts import Archive, Trace, digest, now, write_json
from .config import AGENT, KIT, Config, Deadline, missing_credentials, writable
from .contracts import compile_openapi, compile_tools, normalize_spec, source_documents, validate_requirements
from .freya_adapter import FreyaAdapter, public_suite
from .diagnostics import grounded_diagnoses
from . import prompts
from .schemas import CodeProbes, Diagnostics, MutationGroup, RequirementsBundle, WorkflowSpec
from .scenarios import run_probes, validate_probe_targets
from .scoring import FeedbackAdapter, Suite, choose_champion, group_advantages, score, select_beam
from .validation import apply_mutation, validate


def source_manifest(documents, api_path):
    paths = [Path(d['path']) for d in documents] + [api_path]
    paths += [KIT / f for f in ('README.md', 'VERSION', 'docs/api.md', 'docs/workflow-format.md', 'docs/tools-and-code.md', 'freya.py', 'tools/run_cases.py', 'tools/score.py')]
    return [{'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]


class Builder:
    def __init__(self, cfg, briefs, openapi, *, roles_factory=ADKRoles, adapter_factory=FreyaAdapter, pinned=None, resume=None, only=None, style='', public_brief=None):
        self.cfg = cfg
        self.deadline = Deadline(cfg.max_wall_seconds, cfg.reserve)
        self.run_id = time.strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8]
        self.root = writable(cfg.artifacts / self.run_id)
        self.root.mkdir(parents=True)
        self.documents = source_documents(briefs)
        self.openapi_path = Path(openapi).resolve()
        self.contracts = compile_openapi(self.openapi_path)
        self.brief_hash = digest([d['text'] for d in self.documents])
        self.trace = Trace(self.root / 'build_trace.log', {'run_id': self.run_id, 'mode': cfg.mode, 'brief_hash': self.brief_hash, 'openapi_hash': self.contracts['sha256']}, cfg.tracing)
        self.archive = Archive(self.root)
        self.roles = roles_factory(cfg, self.deadline, self.trace, self.root)
        self.adapter_factory = adapter_factory
        self.pinned = Path(pinned).resolve() if pinned else None
        self.resume = writable(resume) if resume else None
        if self.resume:
            old = json.loads((self.resume / 'manifest.json').read_text())
            if old['brief_hash'] != self.brief_hash or old['openapi_hash'] != self.contracts['sha256']:
                raise ValueError('Resume inputs differ from original run')
            if not self.pinned and (self.resume / 'pinned_root.json').exists():
                self.pinned = self.resume / 'pinned_root.json'
        self.suite, self.cases = public_suite(self.documents, self.contracts['sha256'], public_brief, only, style, cfg.repetitions, cfg.seed) if cfg.official else (None, [])
        self.scores, self.feedback, self.valid, self.kinds, self.advantages = {}, {}, {}, {}, {}
        self.exports = {}
        self.champion = self.best_official = self.best_proxy = None
        self.simulations = 0
        self.baseline_raw = self.baseline_suite = None
        self.probes = {'probes': []}
        self.held_out_score = None
        self.best_effort = False
        self.feedback_adapter = FeedbackAdapter(cfg.mode)
        self.adapter = None
        self.submission_dir = AGENT / 'out'
        self.started = now()
        self.start_clock = time.monotonic()
        self.random = random.Random(cfg.seed)
        write_json(self.root / 'manifest.json', {'run_id': self.run_id, 'start': self.started, 'config': asdict(cfg), 'sources': source_manifest(self.documents, self.openapi_path), 'brief_hash': self.brief_hash, 'openapi_hash': self.contracts['sha256'], 'suite': asdict(self.suite) if self.suite else None, 'code_sha256': digest({str(p.relative_to(AGENT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((AGENT / 'builder').rglob('*.py'))})})
        write_json(self.root / 'sources.json', [{'path': d['path'], 'text': d['text']} for d in self.documents], immutable=True)
        write_json(self.root / 'tool_contracts.json', self.contracts, immutable=True)
        write_json(self.root / 'openapi.input.json', json.loads(self.openapi_path.read_text()), immutable=True)
        for source in (AGENT / 'builder').rglob('*.py'):
            destination = self.root / 'source_code' / source.relative_to(AGENT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        for name in ('requirements.txt', 'requirements.lock'):
            (self.root / 'source_code' / name).write_bytes((AGENT / name).read_bytes())

    def compile(self):
        spec = None
        self.requirements = None
        if self.pinned:
            pinned = json.loads(self.pinned.read_text())
            if pinned['brief_hash'] != self.brief_hash or pinned['openapi_hash'] != self.contracts['sha256']:
                raise ValueError('Pinned root does not match current brief/OpenAPI')
            self.requirements = validate_requirements(pinned['requirements'], self.documents)
            self.probes = pinned.get('code_probes', {'probes': []})
            spec = pinned['spec']
        elif self.resume:
            # Analyst outputs contain source compilation only, never benchmark feedback.
            paths = [self.resume / 'requirements.json'] + sorted((self.resume / 'model_calls').glob('*.response.json'), reverse=True)
            for path in paths:
                if not path.exists():
                    continue
                proposal = json.loads(path.read_text())
                if not {'requirements', 'input_variables', 'unresolved'} <= set(proposal):
                    continue
                try:
                    self.requirements = validate_requirements(proposal, self.documents)
                    self.trace.event('requirements_resumed', source=str(path), source_hash=digest(proposal))
                    break
                except ValueError:
                    continue
            if self.requirements is not None:
                for path in sorted((self.resume / 'model_calls').glob('*.response.json'), reverse=True):
                    try:
                        spec = WorkflowSpec.model_validate_json(path.read_text()).model_dump()
                    except ValueError:
                        continue
                    self.trace.event('proposal_resumed', source=str(path), source_hash=digest(spec))
                    break
                if spec is None and (self.resume / 'lineage.jsonl').exists():
                    for line in reversed((self.resume / 'lineage.jsonl').read_text().splitlines()):
                        record = json.loads(line)
                        if record.get('event') != 'candidate_created' or record.get('parent_id') or record.get('mutation_kind') not in {'baseline', 'compile_repair'}:
                            continue
                        path = self.resume / 'candidates' / record['candidate_id'] / 'proposal.json'
                        spec = WorkflowSpec.model_validate_json(path.read_text()).model_dump()
                        if digest(spec['workflow']) != record['workflow_sha256']:
                            raise ValueError('Resumed proposal snapshot was modified')
                        self.trace.event('proposal_resumed', source=str(path), source_hash=digest(spec))
                        break
        if self.requirements is None:
            errors = []
            for attempt in range(2):
                proposal = self.roles.ask('BriefAnalystAgent', 'Extract atomic rules with provenance and precedence', prompts.ANALYST,
                                          {'documents': self.documents, 'contracts': self.contracts, 'compiler_errors': errors}, RequirementsBundle)
                try:
                    self.requirements = validate_requirements(proposal, self.documents)
                    break
                except ValueError as exc:
                    write_json(self.root / f'requirements_rejected_{attempt}.json', proposal)
                    errors = [str(exc)]
            if self.requirements is None:
                raise ValueError('Policy compilation failed: ' + str(errors))
        write_json(self.root / 'requirements.json', self.requirements, immutable=True)
        if spec is None:
            payload = {'documents': self.documents, 'requirements': self.requirements, 'contracts': self.contracts,
                       'runtime_docs': {name: (KIT / 'docs' / name).read_text() for name in ('workflow-format.md', 'tools-and-code.md')}}
            spec = self.roles.ask('ADASDesignerAgent', 'Design and generate source-driven Freya root', prompts.DESIGNER, payload, WorkflowSpec)
        fallbacks = []
        for attempt in range(3):
            # The model keeps seeing its own compact proposal; only the archived copy is expanded.
            compact, compiled_ok = spec, False
            try:
                compact, notes = normalize_spec(spec, self.contracts)
                if notes:
                    self.trace.event('proposal_normalized', count=len(notes), notes=notes[:20])
                spec = {**compact, 'workflow': compile_tools(compact['workflow'], self.contracts)}
                validation = validate(spec, self.contracts, self.requirements)
                compiled_ok = True
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                validation = {'valid': False, 'errors': [f'{type(exc).__name__}: {exc}'], 'evidence_type': 'static'}
            candidate = self.archive.add(spec, mutation_kind='baseline' if attempt == 0 else 'compile_repair', brief_sha256=self.brief_hash, openapi_sha256=self.contracts['sha256'])
            cid = candidate['candidate_id']
            self.record_validation(cid, validation)
            self.trace.event('static_validation', candidate_id=cid, valid=validation['valid'], errors=validation['errors'][:40], warnings=validation.get('warnings', [])[:40])
            if compiled_ok and not validation['valid']:
                fallbacks.append((len(validation['errors']), attempt, cid))
            if validation['valid']:
                self.prepare_probes(spec)
                probe_result = run_probes(spec, self.probes, self.requirements, self.deadline)
                write_json(self.root / 'candidates' / cid / 'code_probes.json', probe_result)
                if any(not row['pass'] for row in probe_result['results']):
                    validation = {'valid': False, 'errors': ['Source-derived code probe failed: ' + json.dumps(probe_result)], 'evidence_type': 'local_code_only'}
                    self.valid[cid] = False
                    fallbacks.append((sum(not row['pass'] for row in probe_result['results']), attempt, cid))
                    self.archive.event('code_probe_rejected', candidate_id=cid, **validation)
            if validation['valid'] and self.adapter:
                try:
                    self.adapter.validate_remote(spec['workflow'])
                except Exception as exc:
                    validation = {'valid': False, 'errors': ['Freya dry-run rejected: ' + self.trace.redact(str(exc))], 'evidence_type': 'platform_schema'}
                    self.valid[cid] = False
                    self.archive.event('remote_validation_rejected', candidate_id=cid, **validation)
            if validation['valid']:
                self.champion = cid
                self.kinds[cid] = 'baseline'
                write_json(self.root / 'pinned_root.json', {'brief_hash': self.brief_hash, 'openapi_hash': self.contracts['sha256'], 'requirements': self.requirements, 'spec': spec, 'code_probes': self.probes}, immutable=True)
                write_json(self.root / 'reports/coverage.json', spec['coverage'])
                return cid
            if self.pinned:
                raise ValueError('No valid baseline: ' + '; '.join(validation['errors']))
            if attempt == 2:
                break
            try:
                spec = self.roles.ask('WorkflowCompilerAgent', 'Repair static workflow violations', prompts.DESIGNER,
                                      {'documents': self.documents, 'requirements': self.requirements, 'contracts': self.contracts,
                                       'runtime_docs': {name: (KIT / 'docs' / name).read_text() for name in ('workflow-format.md', 'tools-and-code.md')},
                                       'proposal': compact, 'compiler_errors': validation['errors'],
                                       'advisory_warnings': validation.get('warnings', [])}, WorkflowSpec)
            except (ValueError, TimeoutError) as exc:
                self.trace.event('repair_unavailable', error=type(exc).__name__, message=self.trace.redact(str(exc))[:300])
                break
        # No candidate passed every local gate. A phone agent the platform accepts still beats none:
        # ship the least-flawed compiled candidate, clearly labelled, never as a validated root.
        for count, _, cid in sorted(fallbacks):
            try:
                if self.adapter:
                    self.adapter.validate_remote(self.archive.spec(cid)['workflow'])
            except Exception as exc:
                self.archive.event('remote_validation_rejected', candidate_id=cid, errors=['Freya dry-run rejected: ' + self.trace.redact(str(exc))])
                continue
            self.champion, self.best_effort = cid, True
            self.kinds[cid] = 'baseline'
            self.trace.event('best_effort_root', candidate_id=cid, unresolved_local_findings=count)
            return cid
        raise ValueError('No valid baseline: ' + '; '.join(validation['errors']))

    def prepare_probes(self, spec):
        if self.probes['probes'] or self.pinned or not any(n.get('node_type') == 'code' for n in spec['workflow']['nodes'].values()):
            return
        code_nodes = {key: node for key, node in spec['workflow']['nodes'].items() if node.get('node_type') == 'code'}
        errors = []
        for attempt in range(2):
            saved_probes = self.resume / 'code_probe_suite.json' if self.resume else None
            if attempt == 0 and saved_probes and saved_probes.exists():
                probes = json.loads(saved_probes.read_text())
            else:
                probes = self.roles.ask('ScenarioPlannerAgent', 'Generate source-grounded deterministic code probes',
                'Create at most six independent code-node probes. Give synthetic input vars and expected output vars grounded in cited rule IDs. Cover date boundaries, changed call now, amount floors and malformed inputs where present. Target only supplied code nodes. expected must contain only variables actually written by that node, never oracle descriptions or explanatory notes; put explanations in rationale. Do not test API hooks. Do not use real customer data or claim these tests prove bank behavior. Use source parameters rather than code implementation as the expectation oracle.',
                {'requirements': self.requirements, 'code_nodes': code_nodes, 'probe_errors': errors}, CodeProbes)
            try:
                validate_probe_targets(spec, probes)
                probes = self.roles.ask('ScenarioRefereeAgent', 'Independently verify source-derived test expectations',
                    'Audit each proposed test using ONLY source policy and its synthetic inputs. Return corrected CodeProbes. Recalculate expected dates step by step: identify weekdays, exclude every listed holiday, and count the exact number of business days. Put calculation in rationale, never expected. Reject or remove tests whose expected behavior is not prescribed by a source rule. Preserve node/output variable names. Do not invent fallback behavior for malformed inputs unless prescribed. You cannot see implementation outputs; do not infer expected results from them.',
                    {'documents': self.documents, 'requirements': self.requirements, 'proposed_probes': probes}, CodeProbes, self.cfg.referee_model)
                validate_probe_targets(spec, probes)
                self.probes = probes
                break
            except ValueError as exc:
                errors = [str(exc)]
        if not self.probes['probes']:
            raise ValueError('Invalid generated code probes: ' + str(errors))
        write_json(self.root / 'code_probe_suite.json', self.probes)

    def record_validation(self, cid, result):
        self.valid[cid] = result['valid']
        write_json(self.root / 'candidates' / cid / 'validation.json', result, immutable=True)
        self.archive.event('validation', candidate_id=cid, **result)

    def checkpoint(self):
        self.archive.checkpoint(champion_id=self.champion, best_official_id=self.best_official, best_proxy_id=self.best_proxy,
                                active_deployment_id=self.adapter.deployment if self.adapter else None)

    def evaluate(self, cid):
        if not self.suite or self.simulations + self.suite.repetitions > self.cfg.max_simulations or self.deadline.remaining() < 60:
            self.trace.event('evaluation_skipped', candidate_id=cid, reason='no_authorized_suite_or_budget')
            return
        folder = self.root / 'evaluations' / (cid + '_' + uuid.uuid4().hex[:6])
        spec = self.archive.spec(cid)
        try:
            self.adapter.deploy(self.slot, spec['workflow'])
            self.exports[cid] = self.adapter.export(spec['workflow'], folder / 'deployed.workflow.json')
            if self.baseline_raw is not None and self.kinds.get(cid) == 'baseline':
                if self.baseline_suite != self.suite.key:
                    raise ValueError('Shared baseline suite mismatch')
                raw = self.baseline_raw
                write_json(folder / 'raw_runner.json', self.trace.redact(raw))
                self.trace.event('shared_baseline_measurement', suite_key=self.suite.key)
            else:
                self.simulations += self.suite.repetitions
                raw = self.adapter.evaluate(self.cases, self.suite, folder)
        except (Exception, KeyboardInterrupt) as exc:
            self.trace.event('benchmark_incomplete', candidate_id=cid, error=type(exc).__name__, message=str(exc))
            path = folder / 'raw_runner.json'
            raw = json.loads(path.read_text()) if path.exists() else {'all_rows': []}
            if isinstance(exc, KeyboardInterrupt):
                raise
        frozen = score(raw, self.suite)
        self.scores[cid] = frozen
        write_json(folder / 'core_score.json', asdict(frozen), immutable=True)
        self.archive.event('core_score_frozen', candidate_id=cid, **asdict(frozen))
        diagnoses = []
        if self.cfg.mode == 'scoring_with_diagnostics' and frozen.failed and self.deadline.remaining() > 30:
            try:
                result = self.roles.ask('DiagnosisAgent', 'Diagnose frozen failures without changing score', prompts.DIAGNOSIS,
                                        {'core_score': asdict(frozen), 'evidence': self.trace.redact(raw), 'requirements': self.requirements,
                                         'workflow': spec['workflow']}, Diagnostics, self.cfg.referee_model)
                diagnoses = grounded_diagnoses(result['diagnoses'], raw, self.requirements, spec['workflow'], set(self.suite.case_ids))
                write_json(folder / 'diagnostics.json', diagnoses, immutable=True)
            except Exception as exc:
                self.trace.event('diagnosis_unavailable', error=type(exc).__name__)
        self.feedback[cid] = self.feedback_adapter.for_optimizer(frozen, diagnoses)
        if frozen.hard_fail_count and self.champion == cid:
            self.champion = None
        self.champion = choose_champion(self.champion, cid, self.scores, self.valid)
        if self.champion and self.scores.get(self.champion) and self.scores[self.champion].complete:
            self.best_official = self.champion
        self.checkpoint()

    def search(self, root_id):
        beam, count, diversify = [root_id], 1, False
        for depth in range(1, self.cfg.max_depth + 1):
            if count >= self.cfg.max_candidates or self.deadline.remaining() < 30:
                break
            children = []
            for parent_id in beam:
                self.deadline.require(20)
                group = 'group_' + uuid.uuid4().hex[:8]
                parent = self.archive.spec(parent_id)
                limit = min(self.cfg.group_size, self.cfg.max_candidates - count)
                if limit <= 0:
                    break
                feedback = self.feedback.get(parent_id, {'strict_pass_rate': None, 'complete': False, 'unknown_count': len(self.cases), 'evidence_type': 'unknown'})
                proposals = self.roles.ask('MutationDesignerAgent', 'Generate diverse typed sibling workflow patches', prompts.MUTATOR + prompts.DESIGNER,
                                            {'parent_id': parent_id, 'parent': parent, 'requirements': self.requirements, 'contracts': self.contracts,
                                             'feedback': feedback, 'number_of_proposals': limit, 'diversify': diversify, 'seed': self.random.randrange(2**31)}, MutationGroup, self.cfg.mutator_model)['proposals']
                for proposal in proposals[:limit]:
                    count += 1
                    try:
                        if not proposal.get('target_rule_ids') or not set(proposal['target_rule_ids']) <= {r['rule_id'] for r in self.requirements['requirements']}:
                            raise ValueError('Mutation must target known source requirements')
                        child = apply_mutation(parent, proposal, parent_id)
                        child['workflow'] = compile_tools(child['workflow'], self.contracts)
                        validation = validate(child, self.contracts, self.requirements)
                        if validation['valid'] and self.probes['probes']:
                            probe_result = run_probes(child, self.probes, self.requirements, self.deadline)
                            if any(not row['pass'] for row in probe_result['results']):
                                validation = {'valid': False, 'errors': ['Fixed source-derived code suite failed'], 'evidence_type': 'local_code_only'}
                    except Exception as exc:
                        child = parent
                        validation = {'valid': False, 'errors': [str(exc)], 'evidence_type': 'static'}
                    record = self.archive.add(child, parent=parent_id, mutation=proposal, group=group, mutation_kind=proposal.get('mutation_type', 'other'), brief_sha256=self.brief_hash, openapi_sha256=self.contracts['sha256'])
                    cid = record['candidate_id']
                    self.kinds[cid] = proposal.get('mutation_type', 'other')
                    self.record_validation(cid, validation)
                    children.append(cid)
                    if validation['valid'] and not record['duplicate_of']:
                        self.evaluate(cid)
                    self.checkpoint()
                sibling_scores = {cid: self.scores.get(cid) for cid in children if self.archive.get(cid)['sibling_group_id'] == group}
                advantages, summaries = group_advantages(sibling_scores, {cid: parent_id for cid in sibling_scores})
                self.advantages.update(advantages)
                diversify = not summaries or any(s['diversify'] for s in summaries)
                self.archive.event('relative_rank', group_id=group, advantages=advantages, summaries=summaries, diversify=diversify)
            beam = select_beam(beam + children, self.scores, self.valid, self.kinds, self.advantages, self.cfg.beam_width)
            if not beam:
                break

    def revalidate_finalist(self):
        repetitions = self.cfg.final_repetitions
        if not self.champion or not self.suite or self.simulations + repetitions > self.cfg.max_simulations or self.deadline.remaining() < 60 * repetitions:
            self.trace.event('held_out_skipped', reason='suite_or_simulation_or_wall_budget')
            return
        # A fixed unused speaking style is withheld from every optimizer call.
        style = 'corrects' if self.suite.style != 'corrects' else 'in_words'
        held_out = Suite(self.suite.case_ids, self.suite.suite_hash, self.suite.evidence_type, repetitions, style, self.suite.seed)
        folder = self.root / 'evaluations' / ('held_out_' + self.champion)
        try:
            self.adapter.deploy(self.slot, self.archive.spec(self.champion)['workflow'])
            self.simulations += repetitions
            raw = self.adapter.evaluate(self.cases, held_out, folder)
        except Exception as exc:
            self.trace.event('held_out_incomplete', error=type(exc).__name__)
            path = folder / 'raw_runner.json'
            raw = json.loads(path.read_text()) if path.exists() else {'all_rows': []}
        frozen = score(raw, held_out)
        self.held_out_score = asdict(frozen)
        write_json(folder / 'core_score.json', self.held_out_score, immutable=True)
        # Held-out results never go to a mutator. A verified safety regression vetoes export.
        if frozen.hard_fail_count:
            self.valid[self.champion] = False
            self.champion = None
            for candidate in self.scores:
                self.champion = choose_champion(self.champion, candidate, self.scores, self.valid)
        self.checkpoint()

    def run(self):
        status, error, exported, restored = 'failed', None, None, False
        root_id = None
        self.slot = 'ticket01-' + Path(self.documents[-1]['path']).stem + '-' + self.cfg.mode
        try:
            self.adapter = self.adapter_factory(self.cfg, self.deadline, self.trace)
            root_id = self.compile()
            with self.adapter.workspace():
                try:
                    workflow = self.archive.spec(root_id)['workflow']
                    self.adapter.deploy(self.slot, workflow)
                    self.exports[root_id] = self.adapter.export(workflow, self.root / 'root.workflow.json')
                    self.checkpoint()
                    self.evaluate(root_id)
                    if self.best_effort:
                        self.trace.event('search_skipped', reason='best_effort_root_has_unresolved_local_findings')
                    else:
                        self.search(root_id)
                        self.revalidate_finalist()
                    status = 'exported_best_effort' if self.best_effort else 'exported'
                except (Exception, KeyboardInterrupt) as exc:
                    error = self.trace.redact(str(exc) or type(exc).__name__)
                    status = 'terminated_by_budget' if isinstance(exc, TimeoutError) else 'exported_with_errors'
                    self.trace.event('search_stopped', error=type(exc).__name__, message=error)
                finally:
                    if not self.champion and root_id:
                        # A measured failure vetoes promotion, not submission: an imperfect agent outscores none.
                        self.champion = root_id
                        self.trace.event('champion_fallback_to_root', candidate_id=root_id)
                    if self.champion:
                        self.adapter.exporting = True
                        workflow = self.archive.spec(self.champion)['workflow']
                        try:
                            self.adapter.deploy(self.slot, workflow)
                            exported = self.adapter.export(workflow, self.root / 'champion.workflow.json')
                            restored = True
                        except Exception as exc:
                            cached = self.exports.get(self.champion)
                            if not cached:
                                raise
                            from .freya_adapter import contains_definition
                            cached_export = json.loads(Path(cached).read_text())
                            contains_definition(workflow, cached_export['workflow'])
                            write_json(self.root / 'champion.workflow.json', cached_export)
                            exported = str(self.root / 'champion.workflow.json')
                            status, error = 'exported_cached', self.trace.redact(str(exc) or type(exc).__name__)
                            self.trace.event('cached_export_fallback', candidate_id=self.champion, remote_restored=False, source=cached, error=error)
                        submission = writable(self.submission_dir / (Path(self.documents[-1]['path']).stem + '.workflow.json'))
                        write_json(submission, json.loads(Path(exported).read_text()))
                        self.checkpoint()
        except (Exception, KeyboardInterrupt) as exc:
            error = self.trace.redact(str(exc) or type(exc).__name__)
            status = 'failed'
            self.trace.event('build_failed', error=type(exc).__name__, message=error)
        finally:
            final_score = self.scores.get(self.champion)
            deployment = self.adapter.deployment if self.adapter else None
            result = {'run_id': self.run_id, 'workflow_id': deployment.get('workflow_id') if deployment else None,
                      'agent_id': deployment.get('agent_id') if deployment else None, 'candidate_id': self.champion,
                      'root_candidate_id': root_id, 'root_hash': self.archive.get(root_id)['workflow_sha256'] if root_id else None,
                      'champion_hash': self.archive.get(self.champion)['workflow_sha256'] if self.champion else None,
                      'export_path': exported, 'remote_restored': restored, 'mode': self.cfg.mode, 'evaluation_type': final_score.evidence_type if final_score else 'unknown',
                      'strict_pass_rate': final_score.strict_pass_rate if final_score else None,
                      'root_score': asdict(self.scores[root_id]) if root_id in self.scores else None,
                      'final_score': asdict(final_score) if final_score else None, 'held_out_score': self.held_out_score,
                      'status': status if exported else 'failed', 'best_effort_root': self.best_effort, 'error': error, 'start': self.started, 'end': now(),
                      'seconds': round(time.monotonic() - self.start_clock, 2), 'simulations': self.simulations,
                      'valid_candidates': sum(self.valid.values()), 'invalid_candidates': sum(not v for v in self.valid.values()), 'model_calls': self.roles.calls}
            write_json(self.root / 'report.json', result)
            self.trace.close(**result)
            self.archive.db.close()
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('briefs', nargs='+')
    parser.add_argument('--openapi', default=str(KIT / 'tools/openapi.json'))
    parser.add_argument('--mode', choices=['scoring_only', 'scoring_with_diagnostics'])
    parser.add_argument('--pinned-root')
    parser.add_argument('--resume-run', help='Reuse source-matched analyst/root artifacts after an interrupted build')
    parser.add_argument('--public-brief', choices=['A', 'B'])
    parser.add_argument('--only', help='Comma-separated public case IDs; defines a distinct suite')
    parser.add_argument('--style', default='', choices=['', 'pieces', 'corrects', 'talkative', 'asks_back', 'in_words'])
    args = parser.parse_args(argv)
    try:
        cfg = Config.from_env(args.mode)
        missing = missing_credentials(cfg)
        if missing:
            raise ValueError("Missing credentials (set them in env.sh): " + ", ".join(missing))
        builder = Builder(cfg, args.briefs, args.openapi, pinned=args.pinned_root, resume=args.resume_run, only=args.only.split(',') if args.only else None, style=args.style, public_brief=args.public_brief)
        result = builder.run()
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({'status': 'invalid_input', 'error': str(exc)}))
        return 2
    print(json.dumps(result))
    return 0 if result['export_path'] else 3 if not result['candidate_id'] else 4


if __name__ == '__main__':
    raise SystemExit(main())
