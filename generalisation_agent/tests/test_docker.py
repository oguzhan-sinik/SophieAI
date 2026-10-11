import os
import pytest

from agent.builder.config import Deadline
from generalisation_agent.sandbox import DockerCode, Unsupported

pytestmark = pytest.mark.skipif(os.getenv("GENERALISATION_TEST_DOCKER") != "true", reason="Explicit Docker integration test")


def test_real_container_dates_and_noisy_code():
    code = DockerCode(Deadline(90))
    code.ready()
    result = code.run("try:\n from datetime import date, timedelta\n print('untrusted output')\n vars['tomorrow'] = (date.fromisoformat(vars['now']) + timedelta(days=1)).isoformat()\nexcept Exception:\n vars['tomorrow'] = 'unknown'", {"now": "2028-12-31"})
    assert result["vars"]["tomorrow"] == "2029-01-01"


def test_real_container_cpu_limit_abstains():
    code = DockerCode(Deadline(90))
    with pytest.raises(Unsupported, match="container failed or exceeded its resource limit"):
        code.run("try:\n while True:\n  pass\nexcept Exception:\n pass", {})


@pytest.mark.parametrize('bad_identity', [False, True])
def test_compiled_controller_runs_actual_docker_and_changed_api_mapping(bad_identity):
    from types import SimpleNamespace
    from generalisation_agent.bank import operations_for
    from generalisation_agent.calibration import control_workflow, ScriptedActor
    from generalisation_agent.generation import customers_for, openapi_for, sample_mapping, sample_policy
    from generalisation_agent.oracle import grade_ledger
    from generalisation_agent.runner import Runner
    policy, mapping = sample_policy(42, 1), sample_mapping(1)
    customer = customers_for(policy, 991, 1)[0]
    api = openapi_for(policy, mapping, "docker-controller")
    workflow, answers = control_workflow(policy, mapping, customer, {"operations": operations_for(api)})
    if bad_identity:
        body = workflow['nodes']['verify0']['pre_actions'][0]['function']['parameters']['properties']['body']
        body['properties'][mapping.requests['verify_identity']['answer']]['default'] = 'incorrect-control-answer'
    class Roles:
        def ask(self, role, purpose, instruction, payload, schema, **kwargs):
            assert role == "proxy_extractor"
            field = payload["schema"][0]
            spoken = [t for t in payload["conversation"] if t["role"] in {"assistant", "user"}]
            last = spoken[-1]
            question = next((t["text"] for t in reversed(spoken) if t["role"] == "assistant"), "")
            name = field["name"]
            eligible = name == "present" and "May I speak" in question or name == "confirmed" and "Please confirm" in question or name == "bye" and "Goodbye" in question
            if name.startswith("answer"):
                index = int(name.removeprefix("answer"))
                eligible = policy.identity[index].name in question
            value = "yes" if name in {"present", "confirmed"} else last["text"]
            return {"values": {name: value} if eligible and last["role"] == "user" else {}, "uncertain": []}
    recording = Runner(workflow, policy, mapping, customer, Roles(), Deadline(90), api,
                       actor=ScriptedActor(answers)).run()
    assert recording["ended"] == "end_call" and not recording["unknown"]
    result = grade_ledger(policy, customer, recording["ledger"])
    if bad_identity:
        assert 'Private account tool called before all identity fields passed' in result['hard_failures']
    else:
        assert result['ledger_pass']
    assert len(recording["ledger"]["promises"]) == (0 if bad_identity else 1)


def test_human_speech_helpers_execute_in_restricted_docker():
    from agent.builder.runtime import DATE_HELPERS
    code = DATE_HELPERS + '''
try:
 vars['digits'] = ctl_digits('zero three five eight')
 vars['birth'] = ctl_identity_date('14 March nineteen eighty eight')
 vars['partial_birth'] = ctl_identity_date('14 March')
 first = ctl_proposal(vars, 'loan', '20.05', '2028-12-22')
 ctl_consent(vars, 'loan', first, True)
 vars['before'] = ctl_write_ready(vars, 'loan', '20.05', '2028-12-22')
 ctl_proposal(vars, 'loan', '21.05', '2028-12-22')
 vars['after'] = ctl_write_ready(vars, 'loan', '21.05', '2028-12-22')
except Exception:
 vars['error'] = 'helper failed'
'''
    result = DockerCode(Deadline(90)).run(code, {})['vars']
    assert result['digits'] == '0358' and result['before'] is True and result['after'] is False
    assert result['birth'] == '1988-03-14' and result['partial_birth'] == ''
