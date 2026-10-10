"""Restore an archived, validated champion without any new model call."""
import argparse
import json
from pathlib import Path
import uuid

from .artifacts import Archive, Trace
from .config import Config, Deadline, writable
from .freya_adapter import FreyaAdapter
from .validation import validate


def restore(run_path, candidate_id=None):
    root = writable(run_path)
    archive = Archive(root)
    pointer = json.loads((root / 'champion.json').read_text())
    candidate_id = candidate_id or pointer['champion_id']
    spec = archive.spec(candidate_id)
    requirements = json.loads((root / 'requirements.json').read_text())
    contracts = json.loads((root / 'tool_contracts.json').read_text())
    checked = validate(spec, contracts, requirements)
    if not checked['valid']:
        raise ValueError('Archived candidate fails current static validation: ' + str(checked['errors']))
    for path in (root / 'evaluations').glob(candidate_id + '*/core_score.json'):
        if json.loads(path.read_text()).get('hard_fail_count', 0):
            raise ValueError('Cannot restore a candidate with a verified hard failure')
    cfg = Config.from_env()
    recovery = root / ('recovery_' + uuid.uuid4().hex[:8])
    trace = Trace(recovery / 'build_trace.log', {'run_id': root.name, 'candidate_id': candidate_id, 'mode': cfg.mode}, cfg.tracing)
    adapter = FreyaAdapter(cfg, Deadline(min(cfg.max_wall_seconds, 300), 10), trace)
    try:
        sources = json.loads((root / 'sources.json').read_text())
        manifest = json.loads((root / 'manifest.json').read_text())
        slot = 'ticket01-' + Path(sources[-1]['path']).stem + '-' + manifest['config']['mode']
        with adapter.workspace():
            deployment = adapter.deploy(slot, spec['workflow'])
            exported = adapter.export(spec['workflow'], recovery / 'champion.workflow.json')
            archive.event('recovered', candidate_id=candidate_id, export_path=exported, **deployment)
            trace.close(status='exported', export_path=exported)
            return {'candidate_id': candidate_id, 'export_path': exported, 'status': 'exported', **deployment}
    finally:
        archive.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--candidate')
    args = parser.parse_args()
    print(json.dumps(restore(args.run, args.candidate)))


if __name__ == '__main__':
    main()
