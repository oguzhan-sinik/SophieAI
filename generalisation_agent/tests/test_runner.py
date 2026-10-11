from copy import deepcopy
from datetime import datetime
import json
from types import SimpleNamespace

import pytest

from agent.builder.config import Deadline
from agent.builder.contracts import compile_workflow
from agent.builder.artifacts import digest
from generalisation_agent.generation import customers_for, openapi_for, sample_mapping, sample_policy
from generalisation_agent.judge import Judge, validated_checks
from generalisation_agent.models import CORE_RULES, UserReply
from generalisation_agent.runner import Runner, capability_errors, condition_matches, merged_routes, parameters, substitute
from generalisation_agent.sandbox import DockerCode, Unsupported


def test_baked_defaults_cannot_be_overridden_and_nested_fields_bind():
    schema = {"type": "object", "properties": {"url": {"default": "https://fixed.invalid"},
              "body": {"type": "object", "properties": {"id": {"default": "{{customer_id}}"}, "amount": {"type": "number"}}, "required": ["id", "amount"]}}}
    args = parameters(schema, {"url": "https://bad.invalid", "body": {"id": "bad", "amount": 123}}, {"customer_id": "right"})
    assert args == {"url": "https://fixed.invalid", "body": {"id": "right", "amount": 123}}
    with pytest.raises(Unsupported): substitute("Hello {{unset}}", {})


def test_route_grouping_and_boolean_strings_are_explicit():
    condition = {"logic": "or", "conditions": [{"variable": "ok", "operator": "equals", "operand": "true"}]}
    assert condition_matches(condition, {"ok": "true"}, {})
    assert not condition_matches(condition, {"ok": "false"}, {})
    routes = merged_routes([{"target_node": "same", "condition": condition}, {"target_node": "same", "condition": {"operator": "always"}}])
    assert len(routes) == 1 and condition_matches(routes[0]["condition"], {}, {})


def workflow_for(policy, mapping, customer):
    api = openapi_for(policy, mapping, "runner-fixture")
    contracts = {"operations": {op: {"name": op, "method": "POST", "url": api["servers"][0]["url"] + path,
                     "body": methods["post"]["requestBody"]["content"]["application/json"]["schema"], "responses": methods["post"]["responses"]}
                 for path, methods in api["paths"].items() for op in [methods["post"]["operationId"]]}}
    source = {"initial_node": "hello", "system_prompt": "Fictional fixture.", "nodes": {
        "hello": {"name": "hello", "node_type": "conversation", "on_enter": {"type": "tts", "text": "Are you {{first_name}}?"},
                  "extraction_schema": [{"name": "present", "type": "string"}],
                  "transitions": [{"target_node": "close", "condition": {"logic": "or", "conditions": [{"variable": "present", "operator": "equals", "operand": "yes"}]}}]},
        "close": {"name": "close", "node_type": "api_request", "pre_actions": [{"bank_operation": "close_call", "description": "Close fixture.",
                  "bindings": {mapping.requests["close_call"]["outcome"]: policy.outcomes["not_verified"], mapping.requests["close_call"]["reason"]: policy.reasons["declined"]}}],
                  "transitions": [{"target_node": "end", "condition": {"operator": "always"}}]},
        "end": {"name": "end", "node_type": "end_call", "terminal": {"type": "function", "function": {"name": "end", "handler": "__function__:end_call",
                "parameters": {"type": "object", "properties": {"message_mode": {"default": "custom"}, "spoken_message": {"default": "Goodbye."}}}}}, "transitions": []},
    }}
    return compile_workflow(source, contracts)[0], api


def test_actual_compiled_graph_executes_and_records_bank_call():
    policy, mapping = sample_policy(42), sample_mapping()
    customer = customers_for(policy, 42)[0]
    workflow, api = workflow_for(policy, mapping, customer)
    class Roles:
        def ask(self, role, purpose, instruction, payload, schema, **kwargs):
            if role == "proxy_extractor": return {"values": {"present": "yes"} if len(payload["conversation"]) > 1 else {}, "uncertain": []}
            raise AssertionError(role)
    actor = SimpleNamespace(reply=lambda history: UserReply(message="Yes, that is me.", hang_up=False))
    recording = Runner(workflow, policy, mapping, customer, Roles(), Deadline(60), api, actor=actor).run()
    assert recording["ended"] == "end_call" and recording["unknown"] == []
    assert recording["ledger"]["calls"][-1]["tool"] == "close_call"
    assert any(t.get("text") == "Goodbye." for t in recording["turns"])
    assert any(t.get("name") == "present" and t.get("value") == "yes" for t in recording["turns"])


def test_unsupported_features_abstain_before_model_calls():
    p, m = sample_policy(42), sample_mapping()
    c = customers_for(p, 42)[0]
    w, api = workflow_for(p, m, c)
    w["nodes"]["hello"]["on_enter"] = {"type": "audio", "asset_id": "x"}
    recording = Runner(w, p, m, c, None, Deadline(30), api).run()
    assert recording["ended"] is None and "audio" in recording["unknown"][0]
    assert recording["ledger"]["calls"] == []


def checks(turn=0, quote="Hello", fail=None):
    return {"confirmations": [], "checks": [{"rule": rule, "verdict": "fail" if fail == rule else "pass" if rule in {"privacy_before_identity", "end_close_last"} else "not_applicable", "reason": "fixture",
                        "evidence": [{"turn": turn, "quote": quote}] if fail == rule or rule in {"privacy_before_identity", "end_close_last"} else []} for rule in CORE_RULES]}


def test_judge_rejects_fabricated_evidence():
    with pytest.raises(ValueError, match="verbatim"):
        validated_checks(checks(quote="Invented", fail="no_false_success"), [{"text": "Hello"}])


def test_blind_judge_disagreement_is_unknown():
    class Roles:
        def ask(self, role, *args, **kwargs):
            return checks(fail="no_false_success" if role == "synthetic_transcript_judge" else None)
    recording = {"turns": [{"text": "Hello"}], "ledger": {"calls": []}, "unknown": []}
    result = Judge(Roles()).grade(sample_policy(42), recording)
    assert not result["failed"] and result["unknown"]


def test_sandbox_forbids_capabilities_before_launch(monkeypatch):
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Must not launch")))
    with pytest.raises(Unsupported, match="forbidden"):
        DockerCode(Deadline(30)).run("try:\n vars['x'] = open('/etc/passwd').read()\nexcept Exception:\n pass", {})


def test_container_flags_and_cleanup_are_enforced(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "run":
            assert not any(arg.startswith(("--mount", "--volume", "--env")) for arg in command)
            for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534", "--pull=never"):
                assert flag in command
            return SimpleNamespace(returncode=0, stdout=json.dumps({"vars": {"x": 2}, "config": {}, "result": {}}), stderr="")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("subprocess.run", run)
    assert DockerCode(Deadline(30)).run("try:\n vars['x'] = 2\nexcept Exception:\n vars['x'] = 0", {})["vars"]["x"] == 2
    assert calls[-1][1:3] == ["rm", "-f"]
