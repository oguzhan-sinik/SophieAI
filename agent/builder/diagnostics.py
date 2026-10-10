"""Accept only referee hypotheses that cite evidence actually supplied to the role."""


def evidence_at(raw, reference):
    path = reference.removeprefix('raw_runner.json#').removeprefix('evidence.')
    parts = path.lstrip('/').split('/') if '/' in path else path.split('.')
    value = raw
    try:
        for part in parts:
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return value is not None


def grounded_diagnoses(diagnoses, raw, requirements, workflow, case_ids):
    rules = {r['rule_id'] for r in requirements['requirements']}
    return [d for d in diagnoses
            if d['case_id'] in case_ids and d['rule_ids'] and set(d['rule_ids']) <= rules
            and d['evidence_refs'] and all(evidence_at(raw, ref) for ref in d['evidence_refs'])
            and d['likely_workflow_nodes'] and set(d['likely_workflow_nodes']) <= set(workflow['nodes'])
            and d['confidence'] >= .6]
