"""Restore an archived candidate to Freya and export it, without any model call."""
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
    candidate_id = candidate_id or json.loads((root / 'champion.json').read_text())['champion_id']
    workflow = archive.workflow(candidate_id)
    checked = validate(workflow, json.loads((root / 'tool_contracts.json').read_text()))
    cfg = Config.from_env()
    recovery = root / ('recovery_' + uuid.uuid4().hex[:8])
    trace = Trace(recovery / 'build_trace.log', {'run_id': root.name, 'candidate_id': candidate_id}, cfg.tracing)
    # A best-effort candidate was shipped with known findings; restoring it is not a new judgement on them.
    trace.event('restore_static_check', valid=checked['valid'], errors=checked['errors'][:20])
    adapter = FreyaAdapter(cfg, Deadline(min(cfg.max_wall_seconds, 300), 10), trace)
    try:
        sources = json.loads((root / 'sources.json').read_text())
        with adapter.workspace():
            deployment = adapter.deploy('builder-' + Path(sources[-1]['path']).stem, workflow)
            exported = adapter.export(workflow, recovery / 'champion.workflow.json')
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
