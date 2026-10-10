import sys
from pathlib import Path
import tempfile
import shutil
import pytest

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))
sys.dont_write_bytecode = True

@pytest.fixture
def work():
    (AGENT / 'artifacts').mkdir(exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix='test-', dir=AGENT / 'artifacts'))
    try:
        yield path
    finally:
        shutil.rmtree(path)

@pytest.fixture
def contracts():
    from builder.contracts import compile_openapi
    return compile_openapi(AGENT.parent / 'tools/openapi.json')

@pytest.fixture
def requirements():
    return {'requirements': [{'rule_id': 'R1', 'source': {'path': 'fixture', 'heading': 'Policy', 'span': 'Verify first.', 'start_line': 1, 'end_line': 1}, 'kind': 'privacy', 'priority': 'hard', 'condition': 'before account access', 'must': ['Verify first'], 'must_not': [], 'parameters': {}, 'dependencies': [], 'precedence': {'supersedes': [], 'superseded_by': []}, 'interpretation_status': 'resolved', 'test_templates': ['unauthenticated']}], 'input_variables': ['customer_id'], 'unresolved': []}

@pytest.fixture
def spec(contracts):
    from builder.contracts import tool_from_contract
    def tool(name, bindings=None):
        return tool_from_contract(contracts['operations'][name], 'CALL when authorized by the policy.', bindings)
    def route(target, condition=None):
        return {'target_node': target, 'description': 'Continue', 'condition': condition or {'operator': 'always'}}
    def action(name, operation, target, bindings=None):
        return {'name': name, 'node_type': 'api_request', 'pre_actions': [tool(operation, bindings)], 'passthrough': True,
                'passthrough_default_transition': target, 'on_enter': {'type': 'silent'}, 'transitions': [route(target)]}
    w = {'initial_node': 'verify', 'system_prompt': 'Follow the input policy.', 'global_nodes': {}, 'nodes': {
        'verify': {'name': 'verify', 'node_type': 'conversation', 'task_message': 'Verify identity before disclosure.', 'tools': [tool('verify_identity')],
                   'transitions': [route('account', {'logic': 'or', 'conditions': [{'operator': 'equals', 'variable': 'verify_identity_response.data.all_verified', 'operand': 'true'}, {'operator': 'equals', 'variable': 'verify_identity_response.data.all_verified', 'operand': 'True'}]})],
                   'max_node_turns': 10, 'max_turn_transition': 'close'},
        'account': action('account', 'get_account', 'close'),
        'close': action('close', 'close_call', 'end', {'outcome': 'paid'}),
        'end': {'name': 'end', 'node_type': 'end_call', 'transitions': [], 'terminal': {'type': 'function', 'function': {'name': 'done', 'handler': '__function__:end_call', 'parameters': {'type': 'object', 'properties': {'message_mode': {'type': 'string', 'default': 'custom'}, 'spoken_message': {'type': 'string', 'default': 'Goodbye.'}}}}}}
    }}
    return {'workflow': w, 'coverage': {'R1': {'nodes': ['verify', 'account'], 'tests': ['unauthenticated']}}, 'tool_gates': [{'operation': 'get_account', 'rule_ids': ['R1'], 'variable': 'verify_identity_response.data.all_verified', 'allowed_values': ['true', 'True'], 'producer_operation': 'verify_identity', 'response_path': 'data.all_verified'}], 'architecture': 'Minimal static test fixture, not a compliant bank phone agent.'}
