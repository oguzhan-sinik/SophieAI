"""Unattended build: design a phone agent from a brief, fix it, measure it, improve it, export it."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'builder'

from .adk import ADKRoles
from .artifacts import Archive, Trace, digest, now, write_json
from .config import AGENT, KIT, Config, Deadline, missing_credentials, writable
from .contracts import compile_openapi, compile_workflow, source_documents, validate_requirements
from .freya_adapter import FreyaAdapter, contains_definition, public_suite
from . import prompts
from .schemas import Patch, RequirementsBundle, WorkflowSpec
from .scoring import score, verdicts
from .validation import apply_fix, edited_stages, is_wording, validate

FIX_SECONDS = 150        # time a fix call may need; a round is not started with less
FIRST_SIMULATION = 240   # assumed length of a simulation until one has been observed
BROKEN = (ValueError, KeyError, TypeError, AttributeError)


def source_manifest(documents, api_path):
    paths = [Path(d['path']) for d in documents] + [api_path]
    paths += [KIT / f for f in ('README.md', 'VERSION', 'docs/api.md', 'docs/workflow-format.md', 'docs/tools-and-code.md', 'freya.py', 'tools/run_cases.py', 'tools/score.py')]
    return [{'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]


def call_records(folder, raw, limit=80):
    """What happened in a measured run: each failed call step by step, and the stages every call visited."""
    failed, visited = {}, {}
    for repetition, rows in enumerate(raw.get('all_rows', [])):
        path = Path(folder) / f'calls_{repetition}.json'
        recorded = json.loads(path.read_text()) if path.exists() else {}
        for row in rows:
            call = recorded.get(row.get('id'))
            if not isinstance(call, dict):
                continue
            # Simulator agendas/validator inputs are private, never repair instructions.
            call = {key: value for key, value in call.items() if key != 'actor_quality'}
            turns = call.get('turns', [])
            visited.setdefault(row['id'], set()).update(turn['node'] for turn in turns if turn.get('node'))
            if row.get('pass') is not True and row['id'] not in failed:
                # A stuck call repeats itself; its start and its end carry the information.
                failed[row['id']] = call if len(turns) <= limit else {**call, 'turns': turns[:limit // 2] + turns[-(limit // 2):], 'turns_omitted': len(turns) - limit}
    return failed, visited


class Builder:
    def __init__(self, cfg, briefs, openapi, *, roles_factory=ADKRoles, adapter_factory=FreyaAdapter, resume=None, only=None, style='', public_brief=None, evaluation_provider=None, deadline=None, submission_dir=None):
        self.cfg = cfg
        self.deadline = deadline or Deadline(cfg.max_wall_seconds, cfg.reserve)
        self.run_id = time.strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8]
        self.root = writable(cfg.artifacts / self.run_id)
        self.root.mkdir(parents=True)
        self.documents = source_documents(briefs)
        self.openapi_path = Path(openapi).resolve()
        self.contracts = compile_openapi(self.openapi_path)
        self.brief_hash = digest([d['text'] for d in self.documents])
        self.trace = Trace(self.root / 'build_trace.log', {'run_id': self.run_id, 'brief_hash': self.brief_hash, 'openapi_hash': self.contracts['sha256']}, cfg.tracing)
        self.archive = Archive(self.root)
        self.roles = roles_factory(cfg, self.deadline, self.trace, self.root)
        self.adapter_factory, self.adapter = adapter_factory, None
        self.resume = writable(resume) if resume else None
        self.suite, self.cases = public_suite(self.documents, self.contracts['sha256'], public_brief, only, style, cfg.repetitions) if cfg.official else (None, [])
        self.evaluation_provider = evaluation_provider
        if evaluation_provider:
            self.suite, self.cases = evaluation_provider.bind(self.suite, self.cases)
        # One Freya workflow per brief, updated in place on every run.
        self.slot = 'builder-' + Path(self.documents[-1]['path']).stem
        self.submission_dir = writable(submission_dir or AGENT / 'out')
        self.requirements = None
        self.static = {}     # candidate -> result of the static checks
        self.measured = {}   # candidate -> its simulation result, in the order measured
        self.exports = {}    # candidate -> a verified real export of it
        self.wording = {}    # measured candidate -> its wording-only child, committed without a simulation
        self.history = []    # every fix of the improvement loop and what became of it
        self.simulations, self.slowest, self.best_effort = 0, 0.0, False
        self.started = now()
        self.start_clock = time.monotonic()
        write_json(self.root / 'manifest.json', {'run_id': self.run_id, 'start': self.started, 'config': asdict(cfg), 'sources': source_manifest(self.documents, self.openapi_path), 'brief_hash': self.brief_hash, 'openapi_hash': self.contracts['sha256'], 'suite': asdict(self.suite) if self.suite else None, 'evaluation_provider': evaluation_provider.manifest() if evaluation_provider else None, 'code_sha256': digest({str(p.relative_to(AGENT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((AGENT / 'builder').rglob('*.py'))})})
        write_json(self.root / 'sources.json', [{'path': d['path'], 'text': d['text']} for d in self.documents], immutable=True)
        write_json(self.root / 'tool_contracts.json', self.contracts, immutable=True)
        write_json(self.root / 'openapi.input.json', json.loads(self.openapi_path.read_text()), immutable=True)
        for source in (AGENT / 'builder').rglob('*.py'):
            destination = self.root / 'source_code' / source.relative_to(AGENT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        for name in ('requirements.txt', 'requirements.lock'):
            (self.root / 'source_code' / name).write_bytes((AGENT / name).read_bytes())

    # ------------------------------------------------------------------ model calls

    @staticmethod
    def docs():
        return {name: (KIT / 'docs' / name).read_text() for name in ('workflow-format.md', 'tools-and-code.md')}

    def extract_rules(self):
        """A checklist for the designer. Useful, never required: raw bank material may not compile cleanly."""
        errors = []
        for attempt in range(2):
            try:
                proposal = self.roles.ask('BriefAnalystAgent', "Extract the brief's rules with their source lines", prompts.ANALYST,
                                          {'documents': self.documents, 'contracts': self.contracts, 'compiler_errors': errors}, RequirementsBundle,
                                          max_tokens=24000)
                requirements = validate_requirements(proposal, self.documents)
                write_json(self.root / 'requirements.json', requirements, immutable=True)
                return requirements
            except (ValueError, TimeoutError) as exc:
                errors = [self.trace.redact(str(exc))[:600]]
                self.trace.event('requirements_rejected', attempt=attempt + 1, message=errors[0])
                if isinstance(exc, TimeoutError):
                    break   # a second try would take the time the designer needs
        self.trace.event('requirements_unavailable', reason='the designer reads the brief without an extracted rule list')
        return None

    def design(self):
        if self.resume:
            try:
                saved = json.loads((self.resume / 'pinned_root.json').read_text())
                if saved['brief_hash'] != self.brief_hash or saved['openapi_hash'] != self.contracts['sha256']:
                    raise ValueError('its brief or tool API differs from this run')
                self.requirements = saved.get('requirements')
                self.trace.event('root_resumed', source=str(self.resume))
                return WorkflowSpec.model_validate(saved['spec']).model_dump()
            except (OSError, KeyError, ValueError) as exc:
                raise ValueError(f'Cannot resume from {self.resume}: {exc}') from exc
        self.requirements = self.extract_rules()
        payload = {'documents': self.documents, 'contracts': self.contracts, 'runtime_docs': self.docs()}
        if self.requirements:
            payload['requirements'] = self.requirements
        return self.roles.ask('ADASDesignerAgent', 'Design the phone agent workflow from the brief', prompts.DESIGN, payload, WorkflowSpec,
                              max_tokens=32000)

    def fix(self, purpose, source, problems, hints=(), calls=None, wording_only=False, docs=False):
        """The one way a workflow is changed after its design: a patch of small edits to its source."""
        payload = {'documents': [{'path': d['path'], 'text': d['text']} for d in self.documents], 'contracts': self.contracts, 'workflow': source['workflow'],
                   'problems': problems, 'hints': list(hints)[:20], 'history': self.history[-30:], 'wording_only': wording_only}
        if calls:
            payload['calls'] = calls
        if docs:
            payload['runtime_docs'] = self.docs()
        return self.roles.ask('FixAgent', purpose, prompts.FIX, payload, Patch, max_tokens=20000)

    # ------------------------------------------------------------------ candidates

    def check(self, source, remote=True):
        """Compile a source and run the static checks; optionally let Freya validate the result too."""
        try:
            workflow, notes = compile_workflow(source.get('workflow'), self.contracts)
            if notes:
                self.trace.event('source_normalized', notes=notes[:20])
            result = validate(workflow, self.contracts)
        except BROKEN as exc:
            return None, {'valid': False, 'errors': [str(exc) if isinstance(exc, ValueError) else f'{type(exc).__name__}: {exc}'], 'warnings': [], 'evidence_type': 'static'}
        if result['valid'] and remote and self.adapter:
            try:
                self.adapter.validate_remote(workflow)
            except TimeoutError:
                pass   # no answer is not a rejection; deploying validates it again
            except Exception as exc:
                result = {**result, 'valid': False, 'errors': ['Freya dry-run rejected: ' + self.trace.redact(str(exc))[:600]], 'evidence_type': 'platform_schema'}
        return workflow, result

    def record(self, source, workflow, result, parent=None, patch=None, kind='design'):
        candidate = self.archive.add(source, workflow if workflow is not None else source.get('workflow'), parent=parent, patch=patch, mutation_kind=kind,
                                     brief_sha256=self.brief_hash, openapi_sha256=self.contracts['sha256'])
        cid = candidate['candidate_id']
        self.static[cid] = result
        write_json(self.root / 'candidates' / cid / 'validation.json', result, immutable=True)
        self.archive.event('validation', candidate_id=cid, **result)
        self.trace.event('static_validation', candidate_id=cid, candidate_kind=kind, valid=result['valid'], errors=result['errors'][:40], warnings=result['warnings'][:40])
        return cid

    def apply_fixes(self, source, fixes, allowed=None, wording_only=False):
        """Apply fixes one at a time. A fix that cannot be applied is dropped alone, with the reason.

        `allowed` is the static errors the source already has: a fix may not add to them."""
        applied, rejected = [], []
        for fix in fixes:
            try:
                candidate = apply_fix(source, fix)
                if wording_only and not is_wording(source, candidate):
                    raise ValueError('it changes more than wording, and only wording is committed without a simulation')
                if allowed is not None:
                    errors = validate(compile_workflow(candidate['workflow'], self.contracts)[0], self.contracts)['errors']
                    if len(errors) > len(allowed):
                        raise ValueError('it adds compiler errors: ' + '; '.join([e for e in errors if e not in allowed][:3]))
            except BROKEN as exc:
                rejected.append((fix, self.trace.redact(str(exc))[:500]))
                continue
            source = candidate
            applied.append(fix)
        return source, applied, rejected

    def note(self, fix, status, why=''):
        self.history.append({'problem': fix['problem'], 'cases': fix['cases'], 'edits': [f"{e['op']} {e['stage']}{'.' + e['field'] if e['field'] else ''}" for e in fix['edits']], 'status': status, 'note': why})

    # ------------------------------------------------------------------ root

    def build_root(self):
        source = self.design()
        workflow, result = self.check(source)
        cid = self.record(source, workflow, result)
        tried, carried = [(cid, workflow, result)], []
        for attempt in range(2):
            if result['valid']:
                break
            try:
                patch = self.fix('Fix what the compiler rejects', source, {'compiler': carried + result['errors']}, hints=result['warnings'], docs=True)
            except (ValueError, TimeoutError) as exc:
                self.trace.event('fix_unavailable', error=type(exc).__name__, message=self.trace.redact(str(exc))[:300])
                break
            fixed, applied, rejected = self.apply_fixes(source, patch['fixes'])
            carried = [f"Your fix '{fix['problem'][:120]}' was not applied: {why}" for fix, why in rejected] or ([] if applied else ['Your last patch contained no fixes; every problem listed still stands.'])
            self.trace.event('fixes_applied', stage='compile', applied=[fix['problem'][:160] for fix in applied], rejected=carried[:10])
            if not applied:
                continue
            source = fixed
            workflow, result = self.check(source)
            cid = self.record(source, workflow, result, parent=cid, patch={'fixes': applied}, kind='compile_fix')
            tried.append((cid, workflow, result))
        if not result['valid']:
            # No candidate passed every check. A phone agent the platform accepts still beats none:
            # ship the least-flawed one, labelled as such.
            for _, _, cid, workflow in sorted((len(r['errors']), i, c, w) for i, (c, w, r) in enumerate(tried) if w is not None):
                try:
                    self.adapter and self.adapter.validate_remote(workflow)
                except TimeoutError:
                    pass
                except Exception as exc:
                    self.archive.event('remote_validation_rejected', candidate_id=cid, errors=['Freya dry-run rejected: ' + self.trace.redact(str(exc))[:600]])
                    continue
                self.best_effort = True
                self.trace.event('best_effort_root', candidate_id=cid, unresolved=len(self.static[cid]['errors']))
                break
            else:
                raise ValueError('No workflow that Freya accepts: ' + '; '.join(result['errors'][:5]))
        write_json(self.root / 'pinned_root.json', {'brief_hash': self.brief_hash, 'openapi_hash': self.contracts['sha256'], 'requirements': self.requirements, 'spec': self.archive.source(cid)}, immutable=True)
        return cid

    # ------------------------------------------------------------------ measuring

    def simulation_fits(self, extra=0):
        """Never start a simulation that cannot finish inside the build budget."""
        units = getattr(self.evaluation_provider, 'simulations_per_measure', 1)
        return bool(self.suite) and self.simulations + units * self.suite.repetitions <= self.cfg.max_simulations and \
            self.deadline.remaining() >= extra + 1.2 * (self.slowest or (self.evaluation_provider.seconds_per_repetition if self.evaluation_provider else FIRST_SIMULATION)) * self.suite.repetitions

    def deploy(self, cid):
        """Publish a candidate and keep a verified export of it, so a later outage cannot leave the build with nothing."""
        workflow = self.archive.workflow(cid)
        if cid not in self.exports or not self.adapter.deployment or self.adapter.deployment.get('workflow_hash') != digest(workflow):
            self.adapter.deploy(self.slot, workflow)
            self.exports[cid] = self.adapter.export(workflow, self.root / 'candidates' / cid / 'deployed.workflow.json')

    def measure(self, cid):
        """Deploy a candidate, run the practice customers once and freeze the score. True when the result is complete."""
        folder = self.root / 'evaluations' / (cid + '_' + uuid.uuid4().hex[:6])
        raw = {'all_rows': []}
        try:
            self.deploy(cid)
            self.simulations += getattr(self.evaluation_provider, 'simulations_per_measure', 1) * self.suite.repetitions
            raw = self.evaluation_provider.evaluate(self.archive.workflow(cid), self.adapter, folder, self.roles, self.deadline) if self.evaluation_provider else self.adapter.evaluate(self.cases, self.suite, folder)
        except Exception as exc:
            self.trace.event('benchmark_incomplete', candidate_id=cid, error=type(exc).__name__, message=self.trace.redact(str(exc))[:300])
            saved = folder / 'raw_runner.json'
            raw = json.loads(saved.read_text()) if saved.exists() else raw
        self.slowest = max([self.slowest] + [float(s.get('seconds') or 0) for s in raw.get('simulations', [])])
        frozen = score(raw, self.suite)
        write_json(folder / 'core_score.json', asdict(frozen), immutable=True)
        self.archive.event('core_score_frozen', candidate_id=cid, **asdict(frozen))
        failed, visited = call_records(folder, raw)
        findings = {row['id']: row.get('failed', []) for rows in raw.get('all_rows', []) for row in rows if row.get('pass') is not True}
        # The evidence stays with the candidate it was observed on: a fix is only ever shown calls of the workflow it edits.
        self.measured[cid] = {'score': frozen, 'verdicts': verdicts(raw, self.suite), 'visited': visited, 'failed_calls': failed, 'findings': findings}
        if self.evaluation_provider and hasattr(self.evaluation_provider, 'feedback'):
            feedback = self.evaluation_provider.feedback(digest(self.archive.workflow(cid)))
            for key in ('verdicts', 'visited', 'failed_calls', 'findings'):
                self.measured[cid][key].update(feedback.get(key, {}))
        self.checkpoint(cid)
        return frozen.complete

    def champion(self, root_id):
        """The best measured candidate, later one on a tie, with its wording-only child when it has one."""
        complete = [cid for cid, result in self.measured.items() if result['score'].complete and not self.vetoed(cid)]
        if not complete:
            return None if self.vetoed(root_id) else root_id
        best = max(complete, key=lambda cid: (self.measured[cid]['score'].passed, complete.index(cid)))
        return self.wording.get(best, best)

    def vetoed(self, cid):
        return bool(self.evaluation_provider and self.evaluation_provider.vetoed(digest(self.archive.workflow(cid))))

    def checkpoint(self, root_id):
        self.archive.checkpoint(champion_id=self.champion(root_id), active_deployment_id=self.adapter.deployment if self.adapter else None)

    # ------------------------------------------------------------------ improving

    def improve(self, root_id):
        """A chain of batches. Each round applies every fix at once, measures once, and keeps or blames each fix alone."""
        evidence = lambda cid: tuple(dict(self.measured[cid][key]) for key in ('verdicts', 'failed_calls', 'findings'))
        base = root_id                               # the candidate the next fixes are applied to
        known, calls, findings = evidence(root_id)   # what is known about `base`: verdict, failed call and finding per customer
        barren = 0
        while not all(known.values()):
            simulate = self.simulation_fits(FIX_SECONDS)
            if not simulate and self.evaluation_provider:
                break
            if not simulate:
                # No simulation fits any more. Wording can still be committed, onto what will be exported.
                if self.deadline.remaining() < FIX_SECONDS:
                    break
                base = self.champion(root_id)
                known, calls, findings = evidence(base)
            failed = [case for case, ok in known.items() if not ok and (ok is not None or not self.evaluation_provider)]
            if not failed:
                break
            source = self.archive.source(base)
            try:
                patch = self.fix('Fix the causes of the failed practice calls', source,
                                 {'failed_calls': [{'case': case, 'findings': findings.get(case, [])} for case in failed], 'passing': [case for case, ok in known.items() if ok]},
                                 hints=self.static[base]['warnings'], calls={case: calls[case] for case in failed if case in calls}, wording_only=not simulate)
            except (ValueError, TimeoutError) as exc:
                self.trace.event('fix_unavailable', error=type(exc).__name__, message=self.trace.redact(str(exc))[:300])
                break
            fixed, applied, rejected = self.apply_fixes(source, patch['fixes'], allowed=self.static[base]['errors'], wording_only=not simulate)
            workflow = result = None
            if applied:
                workflow, result = self.check(fixed)
                added = [error for error in result['errors'] if error not in self.static[base]['errors']]
                if len(result['errors']) > len(self.static[base]['errors']):
                    rejected, applied = rejected + [(fix, (added or result['errors'])[0][:500]) for fix in applied], []
            for fix, why in rejected:
                self.note(fix, 'rejected', why)
            self.trace.event('fixes_applied', stage='improve', base=base, applied=[fix['problem'][:160] for fix in applied], rejected=[f"{fix['problem'][:100]}: {why[:200]}" for fix, why in rejected][:10])
            if not applied:
                barren += 1
                if barren == 2 or not rejected or not simulate:
                    break
                continue
            barren = 0
            wording = is_wording(source, fixed)
            child = self.record(fixed, workflow, result, parent=base, patch={'fixes': applied}, kind='wording' if wording else 'fixes')
            if wording and base in self.measured and not self.evaluation_provider:
                # Decided for this build: a change to what the agent is told or says is committed onto a
                # measured agent without spending a simulation on it. Nothing new is learned without a
                # simulation, so this is where improving ends.
                for fix in applied:
                    self.note(fix, 'untested', 'wording only: committed without a simulation')
                self.wording[base] = child
                break
            if not self.measure(child):
                for fix in applied:
                    self.note(fix, 'unmeasured', 'its simulation did not complete')
                break
            after, visited = self.measured[child]['verdicts'], self.measured[child]['visited']
            regressed = [case for case in known if known[case] and after[case] is False]
            touches = lambda fix, case: edited_stages(fix) is None or case not in visited or bool(edited_stages(fix) & visited[case])
            blamed = [fix for fix in applied if any(touches(fix, case) for case in regressed)]
            kept, branch = [fix for fix in applied if fix not in blamed], None
            if blamed:
                # Branch from the parent with the fixes that broke nothing. The branch is unmeasured as a
                # whole: it can be built on, but it is never exported before a simulation has seen it.
                branch, kept, _ = self.apply_fixes(source, kept, allowed=self.static[base]['errors'])
            for fix in applied:
                if fix in blamed:
                    self.note(fix, 'blamed', 'broke ' + ', '.join(c for c in regressed if touches(fix, c)) + ', which passed before; taken out again')
                elif fix in kept:
                    self.note(fix, 'kept', 'now passing: ' + (', '.join(c for c in fix['cases'] if after.get(c)) or 'none of its customers yet'))
                else:
                    self.note(fix, 'rejected', 'it does not apply without a fix that was taken out')
            self.archive.event('fixes_judged', candidate_id=child, parent_id=base, regressed=regressed, kept=[fix['problem'][:160] for fix in kept], blamed=[fix['problem'][:160] for fix in blamed])
            self.trace.event('fixes_judged', candidate_id=child, passed=self.measured[child]['score'].passed, regressed=regressed, kept=len(kept), blamed=len(blamed))
            if not blamed:
                base, (known, calls, findings) = child, evidence(child)
                continue
            # What the branch is expected to do: a customer a blamed fix broke passes again, and one that
            # passed only on the child counts as passing only if a kept fix touched its call.
            undone = {case for fix in blamed for case in regressed if touches(fix, case)}
            known = {case: True if case in undone else bool(after[case]) and (known[case] or any(touches(fix, case) for fix in kept)) for case in after}
            calls.update(self.measured[child]['failed_calls'])
            findings.update(self.measured[child]['findings'])
            if kept:
                workflow, result = self.check(branch, remote=False)
                base = self.record(branch, workflow, result, parent=base, patch={'fixes': kept}, kind='revert_branch')

    # ------------------------------------------------------------------ run

    def run(self):
        status, error, exported, restored, root_id, champion = 'failed', None, None, False, None, None
        try:
            self.adapter = self.adapter_factory(self.cfg, self.deadline, self.trace)
            root_id = champion = self.build_root()
            with self.adapter.workspace():
                try:
                    self.deploy(root_id)
                    if not self.simulation_fits():
                        self.trace.event('measurement_skipped', reason='no simulation fits the budget' if self.suite else 'this brief has no practice customers; the design is exported after compiler fixes only')
                    elif self.measure(root_id):
                        self.improve(root_id)
                    status = 'exported'
                except (Exception, KeyboardInterrupt) as exc:
                    error = self.trace.redact(str(exc) or type(exc).__name__)
                    status = 'terminated_by_budget' if isinstance(exc, TimeoutError) else 'exported_with_errors'
                    self.trace.event('improvement_stopped', error=type(exc).__name__, message=error)
                finally:
                    champion = self.champion(root_id)
                    if champion is None:
                        raise ValueError('No eligible candidate: calibrated critical failures vetoed all tested candidates; exports retained for inspection')
                    self.adapter.exporting = True
                    workflow = self.archive.workflow(champion)
                    try:
                        self.adapter.deploy(self.slot, workflow)
                        exported = self.adapter.export(workflow, self.root / 'champion.workflow.json')
                        restored = not getattr(self.adapter, "local", False)
                    except Exception as exc:
                        # Freya is unreachable. A measured candidate was exported when it was deployed:
                        # submit that verified file, and say plainly that the live workflow was not restored.
                        measured = [cid for cid in self.measured if cid in self.exports and self.measured[cid]['score'].complete and not self.vetoed(cid)]
                        fallback = champion if champion in self.exports else max(measured, key=lambda cid: self.measured[cid]['score'].passed) if measured else None
                        if not fallback:
                            raise
                        champion = fallback
                        cached = json.loads(Path(self.exports[champion]).read_text())
                        contains_definition(self.archive.workflow(champion), cached['workflow'])
                        write_json(self.root / 'champion.workflow.json', cached)
                        exported = str(self.root / 'champion.workflow.json')
                        status, error = 'exported_cached', self.trace.redact(str(exc) or type(exc).__name__)
                        self.trace.event('cached_export_fallback', candidate_id=champion, remote_restored=False, source=self.exports[champion], error=error)
                    if status == 'exported' and self.best_effort and not self.static[champion]['valid']:
                        status = 'exported_best_effort'
                    write_json(writable(self.submission_dir / (Path(self.documents[-1]['path']).stem + '.workflow.json')), json.loads(Path(exported).read_text()))
                    self.checkpoint(root_id)
        except (Exception, KeyboardInterrupt) as exc:
            error = self.trace.redact(str(exc) or type(exc).__name__)
            status = 'failed'
            self.trace.event('build_failed', error=type(exc).__name__, message=error)
        finally:
            deployment = self.adapter.deployment if self.adapter else None
            # A wording-only champion was never simulated itself; the score reported is its measured parent's.
            scored = champion if champion in self.measured else next((cid for cid, child in self.wording.items() if child == champion), None)
            final = self.measured[scored]['score'] if scored else None
            statuses = [entry['status'] for entry in self.history]
            result = {'run_id': self.run_id, 'workflow_id': deployment.get('workflow_id') if deployment else None, 'agent_id': deployment.get('agent_id') if deployment else None,
                      'candidate_id': champion, 'root_candidate_id': root_id, 'export_path': exported, 'remote_restored': restored,
                      'export_type': 'local_compiled' if getattr(self.adapter, 'local', False) else 'freya_export',
                      'evaluation_type': final.evidence_type if final else 'unknown', 'strict_pass_rate': final.strict_pass_rate if final else None,
                      'root_score': asdict(self.measured[root_id]['score']) if root_id in self.measured else None, 'final_score': asdict(final) if final else None,
                      'synthetic_evidence': self.evaluation_provider.manifest() if self.evaluation_provider else None,
                      'wording_untested': bool(champion) and champion not in self.measured and scored is not None,
                      'status': status if exported else 'failed', 'best_effort_root': self.best_effort, 'error': error, 'start': self.started, 'end': now(),
                      'seconds': round(time.monotonic() - self.start_clock, 2), 'simulations': self.simulations, 'candidates': len(self.static),
                      'fixes': {name: statuses.count(name) for name in ('kept', 'blamed', 'rejected', 'untested', 'unmeasured')}, 'model_calls': self.roles.calls}
            write_json(self.root / 'report.json', result)
            self.trace.close(**result)
            self.archive.db.close()
        return result


def inputs(paths, openapi=None):
    """Split the command line into the brief documents and the one tool API file that belongs to them.

    Every final brief comes with its own tool API. Falling back to the kit's file for an unknown brief
    would build an agent for the wrong bank without a word, so only the kit's own briefs default to it."""
    def is_api(path):
        # Told apart by content: a brief document may be JSON too (a code list).
        try:
            document = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            return False
        return isinstance(document, dict) and 'openapi' in document
    apis = {str(Path(p).resolve()) for p in [*(p for p in paths if is_api(p)), *([openapi] if openapi else [])]}
    briefs = [p for p in paths if not is_api(p)]
    if not briefs:
        raise ValueError('No brief document given')
    if len(apis) > 1:
        raise ValueError('More than one tool API file given: ' + ', '.join(sorted(apis)))
    if not apis and any(Path(p).resolve().parent != KIT / 'briefs' for p in briefs):
        raise ValueError('This brief needs its own tool API file: give it after the brief, or with --openapi')
    return briefs, apis.pop() if apis else str(KIT / 'tools/openapi.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('briefs', nargs='+', help='The brief documents in reading order; the tool API file may be given among them')
    parser.add_argument('--openapi', help="The brief's tool API file. Only the kit's own briefs default to the kit's file")
    parser.add_argument('--resume-run', help='Reuse the rules and root design of an earlier run on the same brief and tool API')
    parser.add_argument('--public-brief', choices=['A', 'B'])
    parser.add_argument('--only', help='Comma-separated public case IDs; defines a distinct suite')
    parser.add_argument('--style', default='', choices=['', 'pieces', 'corrects', 'talkative', 'asks_back', 'in_words'])
    args = parser.parse_args(argv)
    try:
        cfg = Config.from_env()
        missing = missing_credentials(cfg)
        if missing:
            raise ValueError("Missing credentials (set them in env.sh): " + ", ".join(missing))
        briefs, openapi = inputs(args.briefs, args.openapi)
        builder = Builder(cfg, briefs, openapi, resume=args.resume_run, only=args.only.split(',') if args.only else None, style=args.style, public_brief=args.public_brief)
        result = builder.run()
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({'status': 'invalid_input', 'error': str(exc)}))
        return 2
    print(json.dumps(result))
    return 0 if result['export_path'] else 3 if not result['candidate_id'] else 4


if __name__ == '__main__':
    raise SystemExit(main())
