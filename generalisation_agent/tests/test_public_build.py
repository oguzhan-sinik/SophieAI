"""The live builder keeps official ranking and persona repair evidence separate."""
import json
from pathlib import Path
from types import SimpleNamespace

from agent.builder.artifacts import digest
from agent.builder.config import KIT
from agent.builder.scoring import Suite
from generalisation_agent import public_build


def test_official_runs_first_and_persona_failures_feed_repairs(tmp_path, monkeypatch):
    cases = [case for case in json.loads((KIT / 'public-test-set.json').read_text()) if case['brief'] == 'A']
    suite = Suite(tuple(case['id'] for case in cases), 'official', 'official_public', 1)
    provider = public_build.PublicPersonaProvider()
    provider.bind(suite, cases)
    monkeypatch.setattr(public_build, 'ROOT', tmp_path)
    order = []

    class Adapter:
        def evaluate(self, cases, suite, folder):
            order.append('official')
            folder.mkdir(parents=True)
            rows = [{'id': case['id'], 'pass':case['id'] != 'PUB-01',
                     'failed':['official failure'] if case['id'] == 'PUB-01' else []} for case in cases]
            return {'all_rows':[rows], 'simulations':[{'seconds':11}]}

    def personas(adapter, cases, customers, roles, folder, repetitions):
        order.append('persona')
        folder.mkdir(parents=True)
        rows = [{'id':case['id'], 'pass':case['id'] != 'PUB-02',
                 'failed':['persona failure'] if case['id'] == 'PUB-02' else [],
                 'verified_hard_failure':case['id'] == 'PUB-02'} for case in cases]
        (folder / 'raw_runner.json').write_text(json.dumps({'all_rows':[rows], 'simulations':[{'seconds':17}]}))
        (folder / 'calls_0.json').write_text(json.dumps({'PUB-02':{'turns':[{'role':'assistant','node':'offer','text':'Offer'}]}}))
        return {'suite':{'case_ids':[case['id'] for case in cases], 'suite_hash':'persona',
                         'evidence_type':'freya_persona_diagnostic','repetitions':1,'style':''},
                'score':{'complete':True}}

    monkeypatch.setattr(public_build, 'evaluate_personas', personas)
    workflow = {'nodes':{}}
    raw = provider.evaluate(workflow, Adapter(), tmp_path / 'run' / 'evaluations' / 'candidate', SimpleNamespace(), None)
    assert order == ['official', 'persona']
    assert raw['simulations'][0]['seconds'] == 28
    feedback = provider.feedback(digest(workflow))
    assert feedback['verdicts']['PUB-01'] is False
    assert feedback['verdicts']['PUB-02'] is False
    assert feedback['verdicts']['PUB-03'] is True
    assert feedback['findings']['PUB-01'] == ['official failure']
    assert feedback['findings']['PUB-02'] == ['persona failure']
    assert provider.vetoed(digest(workflow))
