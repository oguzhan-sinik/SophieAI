"""Run the unmodified stock workflow smoke; not a policy acceptance test."""
import json
from pathlib import Path
from .artifacts import Trace, write_json
from .config import AGENT, KIT, Config, Deadline
from .freya_adapter import FreyaAdapter, load_module


def main():
    cfg = Config.from_env()
    folder = AGENT / 'artifacts/stock-smoke'
    folder.mkdir(parents=True, exist_ok=True)
    trace = Trace(folder / 'build_trace.log', {'run_id': 'stock-smoke', 'mode': 'smoke_only'}, False)
    adapter = FreyaAdapter(cfg, Deadline(180, 10), trace)
    try:
        with adapter.workspace():
            workflow = json.loads((KIT / 'examples/base-agent.json').read_text())
            # Intentionally preserve stock nulls/legacy fields for this audit only.
            saved = adapter.client.save_workflow('ticket01-stock-smoke', workflow, state_file=str(adapter.runtime / 'freya-agents.json'))
            version = adapter.client.update_workflow(saved['workflow_id'], workflow)
            scorer = load_module('score', KIT / 'tools/score.py')
            variables = scorer.http('/v1/practice/sessions', {'case': 'PUB-01'})['variables']
            result = adapter.chat_smoke(saved['workflow_id'], variables)
            adapter.client.export_workflow(saved['workflow_id'], str(folder / 'stock.workflow.json'))
            write_json(folder / 'smoke.json', trace.redact({**result, 'version': version, **saved}))
            print(json.dumps({'status': result['status'], 'evidence_type': 'stock_smoke_only'}))
    finally:
        trace.close(status='finished')


if __name__ == '__main__':
    main()
