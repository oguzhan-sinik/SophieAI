"""Explicit release measurement after the existing build/feedback/freeze/export rehearsal."""
import json
from pathlib import Path
from agent.builder.artifacts import digest, write_json
from .config import ROOT, confined
from .evaluation import evaluate_workflow, read_workflow, source_fingerprint
from .packs import load_pack, model_context


def run_campaign(manifest_path, seconds, *, workers=1):
    if seconds < 180 * 120:
        raise ValueError('Release preflight estimates 180 calls × 120 seconds; declare at least 21600 seconds outside builder timing')
    manifest_path = confined(manifest_path)
    top = json.loads(manifest_path.read_text())
    rehearsal = json.loads((manifest_path.parent/'rehearsal.json').read_text())
    if rehearsal['source_fingerprint'] != source_fingerprint():
        raise ValueError('Source changed since rehearsal; regenerate and remeasure the matched exports')
    packs = top['packs']
    if len(packs)!=2 or [p['split'] for p in packs]!=['development','holdout'] or len(rehearsal['results'])!=2:
        raise ValueError('Release requires the complete development/holdout rehearsal')
    prepared = []
    for item,result in zip(packs,rehearsal['results'],strict=True):
        pack = load_pack(Path(item['brief']).parent/'manifest.json')
        if pack[0]!=item or len(pack[3])!=30 or not item.get('campaign') or not result.get('export_path'):
            raise ValueError('Release needs frozen thirty-customer packs and both exact exports')
        workflow = read_workflow(confined(result['export_path']))
        expected_hash = result.get('workflow_sha256') or result.get('workflow_hash')
        if not expected_hash or expected_hash != digest(workflow):
            raise ValueError('Rehearsal export lacks matching measured workflow identity')
        prepared.append((pack,workflow))
    roles,trace,deadline,root = model_context(seconds=seconds,campaign=True)
    reports = []
    try:
        for index,((item,policy,mapping,customers),workflow) in enumerate(prepared):
            from .calibration import calibrate
            api = json.loads(Path(item['openapi']).read_text())
            calibration = calibrate(policy,mapping,api,roles,deadline,root/f'calibration-{index}')
            report,_ = evaluate_workflow(workflow,policy,mapping,customers,roles,deadline,root/f'pack-{index}',3,
                                        api=api,calibration=calibration,split=item["split"],workers=workers)
            reports.append(report)
        result = {'backend':'local_proxy','official':False,'source_fingerprint':source_fingerprint(),
                  'complete':all(r['score']['complete'] for r in reports),'reports':reports,
                  'release_accepted':False,'pending':(['model-backed actor admission'] if any(not r['selection_eligible'] for r in reports) else []) + ['live parity','human quality review','arbitrary generated-pack live backend'],
                  'budget_seconds':seconds, 'build_budget_includes_campaign':False}
        target = ROOT/'artifacts'/root.name/'campaign.json'
        write_json(target,result,immutable=True)
        trace.close(status='complete' if result['complete'] else 'incomplete')
        return {'report':str(target),'complete':result['complete'],'release_accepted':False}
    except Exception:
        trace.close(status='failed')
        raise
