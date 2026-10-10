from types import SimpleNamespace
from copy import deepcopy
import pytest
from builder.artifacts import Trace, digest, write_json
from builder.config import Config, Deadline
from builder.freya_adapter import FreyaAdapter


def adapter_fixture(work, workflow, published=True, stale=False):
    adapter = FreyaAdapter.__new__(FreyaAdapter)
    adapter.cfg = Config(tracing=False)
    adapter.deadline = Deadline(60)
    adapter.trace = Trace(work / 'trace.log', {'run_id': 'adapter-test'}, False)
    adapter.runtime = work
    adapter.exporting = False
    adapter.deployment = None
    adapter.events = []
    def api(method, path, body=None, **params):
        adapter.events.append((method, path))
        if '/versions/' in path:
            return {'versions': [{'versionNumber': 3 if stale else 2, 'isPublished': published, 'id': 'v'}]}
        return {'workflow': {'workflow': deepcopy(workflow)}}
    adapter.api = api
    def save(slot, definition, state_file):
        assert str(work) in state_file
        adapter.events.append(('SAVE', slot))
        return {'workflow_id': 'w', 'agent_id': 'a'}
    def update(wid, definition):
        adapter.events.append(('UPDATE_AND_PUBLISH', wid))
        return 2
    def export(wid, path):
        write_json(path, {'workflow_id': wid, 'workflow': workflow})
    adapter.client = SimpleNamespace(validate_workflow=lambda *args: adapter.events.append(('DRY_RUN', '')), save_workflow=save,
                                     update_workflow=update, workspace_id=lambda: 'ws', export_workflow=export)
    return adapter


def test_create_publishes_and_checks_roundtrip(work, spec):
    adapter = adapter_fixture(work, spec['workflow'])
    result = adapter.deploy('slot', spec['workflow'])
    assert result['version'] == 2
    assert any(event[0] == 'UPDATE_AND_PUBLISH' for event in adapter.events)
    path = adapter.export(spec['workflow'], work / 'final.json')
    assert path.endswith('final.json')


@pytest.mark.parametrize('published,stale', [(False, False), (True, True)])
def test_stale_publish_rejected(work, spec, published, stale):
    adapter = adapter_fixture(work, spec['workflow'], published, stale)
    with pytest.raises(ValueError, match='published'): adapter.deploy('slot', spec['workflow'])
    assert adapter.deployment is None


def test_export_wrong_candidate_rejected(work, spec):
    adapter = adapter_fixture(work, spec['workflow'])
    adapter.deploy('slot', spec['workflow'])
    different = deepcopy(spec['workflow']); different['system_prompt'] = 'changed'
    with pytest.raises(ValueError, match='active'): adapter.export(different, work / 'wrong.json')
