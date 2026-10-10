"""Source-derived deterministic code checks; never evidence of bank-state success."""
import json
import ast
from pathlib import Path
import subprocess
import sys
from .config import AGENT
from .schemas import CodeProbes
from .validation import code_errors


def validate_probe_targets(spec, proposals):
    probes = CodeProbes.model_validate(proposals).probes
    if not probes:
        raise ValueError('Code probes cannot be empty')
    for probe in probes:
        node = spec['workflow']['nodes'].get(probe.node_id, {})
        if node.get('node_type') != 'code':
            raise ValueError(f'{probe.probe_id}: target must be a supplied code node')
        written = set()
        for tool in node['pre_actions']:
            tree = ast.parse(tool['function']['parameters']['properties']['code']['default'])
            for item in ast.walk(tree):
                if isinstance(item, ast.Subscript) and isinstance(item.ctx, ast.Store) and isinstance(item.value, ast.Name) and item.value.id == 'vars' and isinstance(item.slice, ast.Constant):
                    written.add(item.slice.value)
                if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and isinstance(item.func.value, ast.Name) and item.func.value.id == 'vars':
                    if item.func.attr == 'update' and item.args and isinstance(item.args[0], ast.Dict):
                        written.update(k.value for k in item.args[0].keys if isinstance(k, ast.Constant))
                    if item.func.attr == 'setdefault' and item.args and isinstance(item.args[0], ast.Constant):
                        written.add(item.args[0].value)
        if not probe.expected or not set(probe.expected) <= written:
            raise ValueError(f'{probe.probe_id}: expected keys must be actual written variables: {sorted(written)}')


def reconcile_probes(proposals, calculations):
    """Make the calculator's results, not the referee's copy of them, the expected dates.

    A referee has been seen to compute the right day and leave the planner's wrong one in
    `expected`. Where it names the calculated variables the controller writes the returned value
    itself; a probe that used the calculator without saying where the result belongs is dropped."""
    kept, notes = [], []
    for probe in CodeProbes.model_validate(proposals).model_dump()['probes']:
        inputs = [v for v in probe['variables'].values() if isinstance(v, str)]
        deadlines = set()
        for record in calculations or []:
            arguments, result = record.get('arguments') or {}, record.get('result') or {}
            result = result.get('result', result) if isinstance(result, dict) else {}
            anchor = str(arguments.get('anchor', ''))[:10]
            if anchor and isinstance(result, dict) and result.get('deadline') and any(v.startswith(anchor) for v in inputs):
                deadlines.add(result['deadline'])
        named = {key: value for key, value in probe.pop('calculated', {}).items() if key in probe['expected']}
        if deadlines and (not named or not set(named.values()) <= deadlines):
            notes.append(f"{probe['probe_id']}: dropped, calculator results {sorted(deadlines)} were not tied to its expectations")
            continue
        for key, value in named.items() if deadlines else []:
            if probe['expected'][key] != value:
                notes.append(f"{probe['probe_id']}: {key} corrected from {probe['expected'][key]} to calculated {value}")
                probe['expected'][key] = value
        kept.append(probe)
    return {'probes': kept}, notes


def run_probes(spec, proposals, requirements, deadline):
    probes = CodeProbes.model_validate(proposals).probes
    rule_ids = {r['rule_id'] for r in requirements['requirements']}
    results = []
    for probe in probes:
        result = {'id': probe.probe_id, 'rule_ids': probe.rule_ids, 'node_id': probe.node_id, 'variables': probe.variables,
                  'rationale': probe.rationale, 'evidence_type': 'local_code_only', 'pass': False}
        try:
            if not probe.rule_ids or not set(probe.rule_ids) <= rule_ids or not probe.expected:
                raise ValueError('Probe requires grounded rules and nonempty expectations')
            node = spec['workflow']['nodes'].get(probe.node_id)
            if not isinstance(node, dict) or node.get('node_type') != 'code':
                # A repair may rename or remove the stage a probe was written for; that is not a failed check.
                result.update(skipped=True, error='target stage no longer exists')
                results.append(result)
                continue
            code = [t['function']['parameters']['properties']['code']['default'] for t in node['pre_actions']]
            errors = [error for source in code for error in code_errors(source)]
            if errors:
                raise ValueError('; '.join(errors))
            payload = {'code': code, 'variables': probe.variables}
            completed = subprocess.run([sys.executable, '-I', str(Path(__file__).with_name('probe_worker.py'))],
                                       input=json.dumps(payload), capture_output=True, text=True, cwd=AGENT,
                                       timeout=deadline.timeout(4))
            if completed.returncode:
                raise ValueError('Code probe failed: ' + completed.stderr[-500:])
            actual = json.loads(completed.stdout)
            result['pass'] = all(key in actual and actual[key] == value for key, value in probe.expected.items())
            result['observed'] = {key: actual.get(key) for key in probe.expected}
            result['expected'] = probe.expected
        except (Exception, KeyboardInterrupt) as exc:
            if isinstance(exc, KeyboardInterrupt): raise
            result['error'] = str(exc)
        results.append(result)
    return {'evidence_type': 'local_code_only', 'results': results, 'complete': bool(results),
            'passed': sum(r['pass'] for r in results), 'total': len(results), 'bank_policy_proven': False}
