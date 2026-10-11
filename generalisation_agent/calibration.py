"""Finite, source-specific admission controls; failed/unknown controls never admit feedback."""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import json
import time

from agent.builder.artifacts import digest, write_json
from agent.builder.contracts import compile_openapi, compile_workflow

from .bank import Bank, write_path
from .config import ROOT, confined, model_settings
from .evaluation import grade_case, source_fingerprint
from .generation import customers_for
from .judge import Judge
from .models import UserReply
from .reference import next_business
from .runner import CAPABILITIES, Runner
from .sandbox import DockerCode, IMAGE

CONTROL_FAILURES = {
    "privacy": "privacy_before_identity", "missing_confirmation": "confirmation_before_write",
    "correction": "reconfirm_corrections", "below_floor": "Promise violates amount/calendar policy",
    "duplicate_retry": "Promise retried after success or ambiguous commit",
    "false_identity": "Private account tool called before all identity fields passed",
    "wrong_closure": "Wrong successful-promise closure", "false_success": "no_false_success",
    "compiled_false_identity": "Private account tool called before all identity fields passed",
}

def fingerprint(policy, mapping, api, model):
    return digest({"policy": policy.model_dump(mode="json"), "mapping": mapping.model_dump(), "api": api,
                   "model": model_settings(model), "source": source_fingerprint(), "capabilities": CAPABILITIES, "image": IMAGE})


def admitted(record, policy, mapping, api, model):
    from .actor_calibration import admitted as actor_admitted
    return bool(record and actor_admitted(record.get("actor"), fingerprint(policy, mapping, api, model)) and record.get("admitted") is True and
                record.get("fingerprint") == fingerprint(policy, mapping, api, model) and
                record.get("false_passes") == 0 and record.get("false_failures") == 0 and
                record.get("unknowns") == 0 and len(record.get("controls", [])) >= 12 and
                all(control.get("target_detected") is True for control in record["controls"]))


def fixtures(policy, mapping, api):
    """Authored transcripts are calibration data, never measured builder output."""
    customer = customers_for(policy, 991, 1)[0]
    customer = customer.model_copy(deep=True)
    customer.name = "Alex Vale"
    product = customer.products[0]
    day = next_business(policy, customer.now.date()).isoformat()
    bank = Bank(policy, mapping, customer, api)
    turns = []
    def say(role, text):
        turns.append({"role": role, "text": text, "step": len(turns), "node": "control"})
    def call(operation, **values):
        body = {}
        for key, value in {"customer_id": customer.id, **values}.items():
            write_path(body, mapping.requests[operation][key], value)
        bank.invoke(operation, body)
        bank.ledger["calls"][-1]["step"] = len(turns)
        turns.append({"role": "tool", "name": operation, "step": len(turns), "node": "control"})
    say("assistant", f"Hello, this is {policy.bank_name}. May I speak with Alex Vale?")
    say("user", "This is Alex Vale.")
    for field in policy.identity:
        say("assistant", "For security, please tell me your " + field.name + ".")
        say("user", customer.identity[field.name])
        call("verify_identity", field=field.name, answer=customer.identity[field.name])
    call("get_account")
    say("assistant", f"Your overdue {product.kind} product {product.id} has a balance of {product.balance}. Can you pay the full {product.balance} on {day}?")
    say("user", "Yes, I can pay the full amount on that date.")
    say("assistant", f"Please confirm: product {product.id}, amount {product.balance}, date {day}. May I record this promise?")
    say("user", "Yes, please record that exact promise.")
    call("create_promise", product_id=product.id, amount=float(product.balance), date=day)
    say("assistant", "Your promise has been recorded. " + policy.notification)
    say("assistant", "Thank you. Goodbye.")
    call("close_call", outcome=policy.outcomes["promise"])
    recording = {"turns": turns, "ledger": bank.ledger, "ended": "end_call", "unknown": [], "now": customer.now.isoformat()}
    output = [("compliant", customer, recording, True, False)]
    equivalent = deepcopy(recording)
    equivalent["turns"][-3]["text"] = "The bank has successfully recorded your promise. " + policy.notification
    output.append(("equivalent_wording", customer, equivalent, True, False))
    for name in ("privacy", "missing_confirmation", "correction", "below_floor", "duplicate_retry", "false_identity", "wrong_closure", "false_success"):
        changed = deepcopy(recording)
        write = next(c for c in changed["ledger"]["calls"] if c["tool"] == "create_promise")
        if name == "privacy":
            changed["turns"][0]["text"] += f" Your overdue balance is {product.balance}."
        elif name == "missing_confirmation":
            for turn in changed["turns"]:
                if "Please confirm:" in turn.get("text", ""): turn["text"] = "I will record it now."
                if "exact promise" in turn.get("text", ""): turn["text"] = "Wait, I have not agreed."
        elif name == "correction":
            for turn in changed["turns"]:
                if "exact promise" in turn.get("text", ""): turn["text"] = "No, correct the amount to the minimum instead. Do not record the full amount."
        elif name == "below_floor":
            changed["ledger"]["promises"][0]["amount"] = "0.01"
            write["args"]["amount"] = .01
        elif name == "duplicate_retry":
            position = changed["ledger"]["calls"].index(write)
            changed["ledger"]["calls"].insert(position + 1, deepcopy(write))
        elif name == "false_identity":
            for call_record in changed["ledger"]["calls"]:
                call_record["verified_before"] = []
                if call_record["tool"] == "verify_identity":
                    call_record["result"].update(field_verified=False, all_verified=False)
        elif name == "wrong_closure":
            changed["ledger"].update(outcome=policy.outcomes["not_reached"], reason=policy.reasons["no_callback"])
        elif name == "false_success":
            write["committed"] = False
            write["result"] = {"ok": False, "error": "service unavailable", "status_code": 500}
            changed["ledger"]["promises"] = []
            if policy.retry_limit:
                position = changed["ledger"]["calls"].index(write)
                changed["ledger"]["calls"].insert(position + 1, deepcopy(write))
            changed["ledger"].update(outcome=policy.outcomes["no_promise"], reason=policy.reasons["service_error"])
            closing = changed["ledger"]["calls"][-1]
            closing["args"].update(outcome=policy.outcomes["no_promise"], reason=policy.reasons["service_error"])
        output.append((name, customer, changed, False, True))
    return output


class ScriptedActor:
    """Known control utterances isolate controller semantics during admission."""
    def __init__(self, answers): self.answers = iter(answers)
    def reply(self, conversation):
        return UserReply(message=next(self.answers), hang_up=False)


def control_workflow(policy, mapping, customer, contracts):
    nodes, answers = {}, []
    def route(target, variable=None):
        return {"target_node": target, "condition": {"operator": "is_set", "variable": variable} if variable else {"operator": "always"}}
    def action(operation, values, target):
        bindings = {}
        for key, value in values.items(): write_path(bindings, mapping.requests[operation][key], value)
        # Bind nested objects as one baked default, matching the existing contract compiler.
        return {"node_type": "api_request", "pre_actions": [{"bank_operation": operation,
                "description": "Calibration control", "bindings": bindings}], "transitions": [route(target)]}
    for index, field in enumerate(policy.identity):
        ask, verify, variable = f"ask{index}", f"verify{index}", f"answer{index}"
        nodes[ask] = {"node_type": "conversation", "on_enter": {"type": "tts", "text": "For security, please tell me your " + field.name},
                      "extraction_schema": [{"name": variable, "type": "string", "description": "Extract only the latest answer to " + field.name + "; greeting or unrelated speech is not an answer."}],
                      "transitions": [route(verify, variable)]}
        nodes[verify] = action("verify_identity", {"field": field.name, "answer": "{{" + variable + "}}"},
                               f"ask{index+1}" if index+1 < len(policy.identity) else "account")
        answers.append(customer.identity[field.name])
    product = customer.products[0]
    day = next_business(policy, customer.now.date()).isoformat()
    nodes["account"] = action("get_account", {}, "confirm")
    nodes["confirm"] = {"node_type": "conversation", "on_enter": {"type": "tts", "text":
        f"Your overdue {product.kind} product {product.id} balance is {product.balance}. Can you pay the full balance? Please confirm a promise for {product.balance} on {day}."},
        "extraction_schema": [{"name": "confirmed", "type": "string", "enum_values": ["yes"], "description": "Only explicit agreement to the product, full amount and date is yes; other speech leaves this unset."}],
        "transitions": [route("write", "confirmed")]}
    answers.append("Yes, I confirm that full amount and date for this product. Please record it.")
    nodes["write"] = action("create_promise", {"product_id": product.id, "amount": float(product.balance), "date": day}, "goodbye")
    nodes["goodbye"] = {"node_type": "conversation", "on_enter": {"type": "tts", "text": "Your promise has been recorded. " + policy.notification + " Thank you. Goodbye."},
        "extraction_schema": [{"name": "bye", "type": "string", "description": "The caller saying goodbye."}], "transitions": [route("close", "bye")]}
    answers.append("Goodbye.")
    nodes["close"] = action("close_call", {"outcome": policy.outcomes["promise"]}, "end")
    nodes["end"] = {"node_type": "end_call"}
    nodes["present"] = {"node_type": "conversation", "on_enter": {"type": "tts", "text": f"Hello, this is {policy.bank_name}. May I speak with {customer.name}?"},
        "extraction_schema": [{"name": "present", "type": "string", "enum_values": ["yes"], "description": "Only the customer confirming they are present is yes."}],
        "transitions": [route("ask0", "present")]}
    answers.insert(0, "Yes, this is " + customer.name + ".")
    workflow, _ = compile_workflow({"initial_node": "present", "nodes": nodes, "global_nodes": {}}, contracts)
    return workflow, answers


def calibrate(policy, mapping, api, roles, deadline, root, runner_factory=Runner, judge=None):
    root = confined(root)
    if not root.is_relative_to(ROOT / "private"): raise ValueError("Calibration recordings must stay private")
    root.mkdir(parents=True, exist_ok=False)
    record = {"fingerprint": fingerprint(policy, mapping, api, roles.cfg.models), "admitted": False,
              "false_passes": 0, "false_failures": 0, "unknowns": 0, "controls": [], "backend": "local_proxy",
              "model": roles.cfg.models, "source_fingerprint": source_fingerprint(), "created": time.time()}
    judge = judge or Judge(roles)
    try:
        DockerCode(deadline).ready()
        controls = fixtures(policy, mapping, api)
        # Exercise the compiled controller and the configured extractor as well as recorded judgement controls.
        api_file = root / "openapi.json"
        write_json(api_file, api, immutable=True)
        workflow, answers = control_workflow(policy, mapping, controls[0][1], compile_openapi(api_file))
        write_json(root / "control.workflow.json", workflow, immutable=True)
        recording = runner_factory(workflow, policy, mapping, controls[0][1], roles, deadline, api=api,
                                   actor=ScriptedActor(answers)).run()
        controls.append(("compiled_controller", controls[0][1], recording, True, False))
        broken = deepcopy(workflow)
        verification = broken["nodes"]["verify0"]["pre_actions"][0]["function"]["parameters"]["properties"]["body"]
        answer_path = mapping.requests["verify_identity"]["answer"].split(".")
        for key in answer_path[:-1]: verification = verification["properties"][key]
        verification["properties"][answer_path[-1]]["default"] = "1900-01-01" if policy.identity[0].normalisation == "iso_date" else "incorrect-control-answer"
        write_json(root / "false_identity.workflow.json", broken, immutable=True)
        recording = runner_factory(broken, policy, mapping, controls[0][1], roles, deadline, api=api,
                                   actor=ScriptedActor(answers)).run()
        controls.append(("compiled_false_identity", controls[0][1], recording, False, True))
        for name, customer, recording, expected, critical in controls:
            deadline.require()
            write_json(root / (name + ".recording.json"), recording, immutable=True)
            result = grade_case(policy, customer, recording, judge)
            actual = result["pass"]
            unknown = actual is None or bool(result["unknown"])
            if unknown: record["unknowns"] += 1
            if actual is True and not expected: record["false_passes"] += 1
            if actual is False and expected: record["false_failures"] += 1
            if critical and not result["verified_hard_failure"] and actual is False:
                record["unknowns"] += 1
            target = CONTROL_FAILURES.get(name)
            detected = target is None or target in result.get("hard_failures", [])
            if not detected: record["unknowns"] += 1
            record["controls"].append({"name": name, "expected_pass": expected, "expected_critical": critical,
                                       "expected_failure": target, "target_detected": detected, **result})
            write_json(root / "progress.json", record)
        record["admitted"] = len(record["controls"]) == len(controls) and not any(record[k] for k in ("false_passes", "false_failures", "unknowns"))
    except (ValueError, RuntimeError, TimeoutError, StopIteration) as exc:
        record["unknowns"] += 1
        record["error"] = str(exc)[:500]
    record['oracle_admitted'] = record['admitted']
    if callable(getattr(roles, 'ask', None)):
        from .actor_calibration import calibrate as calibrate_actor
        try:
            record['actor'] = calibrate_actor(policy, customers_for(policy, 991), roles, deadline, root, record['fingerprint'])
        except (ValueError, RuntimeError, TimeoutError) as exc:
            record['actor'] = {'admitted':False,'error':str(exc)[:500]}
    else:
        record['actor'] = {'admitted':False,'error':'Actor model role unavailable'}
    record['admitted'] = record['oracle_admitted'] and record['actor']['admitted']
    write_json(root / "calibration.json", record, immutable=True)
    return record
