"""Fixed-suite local evidence, with unknowns and exact workflow/source fingerprints."""
from dataclasses import asdict
import hashlib
import json
import time

from agent.builder.artifacts import digest, write_json
from agent.builder.scoring import Suite, score

from .config import ROOT, confined
from .judge import Judge
from .oracle import grade_ledger
from .runner import CAPABILITIES, Runner
from .sandbox import IMAGE


def source_fingerprint():
    files = sorted(ROOT.glob("*.py"))
    files += sorted((ROOT.parent / "agent" / "builder").glob("*.py"))
    return digest({str(path.relative_to(ROOT.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files})


def suite_for(policy, mapping, customers, model, repetitions, api=None):
    if not customers or not 1 <= repetitions <= 3:
        raise ValueError("Evaluation needs users and one to three repetitions")
    return Suite(tuple(c.id for c in customers), digest({"policy": policy.model_dump(mode="json"),
                 "mapping": mapping.model_dump(), "customers": [c.model_dump(mode="json") for c in customers],
                 "api": api, "model": model, "source": source_fingerprint(), "capabilities": CAPABILITIES, "image": IMAGE}),
                 "generated", repetitions)


def grade_case(policy, customer, recording, judge):
    if recording.get("unknown") or recording.get("ended") is None:
        return {"pass": None, "failed": [], "unknown": recording.get("unknown") or ["Call did not finish"], "verified_hard_failure": False}
    ledger = grade_ledger(policy, customer, recording["ledger"])
    try:
        spoken = judge.grade(policy, recording)
    except (ValueError, TimeoutError) as exc:
        spoken = {"failed": [], "unknown": ["Transcript judgement unavailable: " + str(exc)[:300]], "hard_failures": []}
    failed = ledger["failed"] + spoken["failed"]
    unknown = ledger["unknown"] + spoken["unknown"]
    return {"pass": False if failed else None if unknown else True, "failed": failed, "unknown": unknown,
            "verified_hard_failure": bool(ledger["hard_failures"] or spoken["hard_failures"]), "judge": spoken}


def evaluate_workflow(workflow, policy, mapping, customers, roles, deadline, root, repetitions=3,
                      api=None, runner_factory=Runner, judge=None, calibration=None):
    root = confined(root)
    if not root.is_relative_to(ROOT / "private"):
        raise ValueError("Customer recordings and oracles must stay under private/")
    root.mkdir(parents=True, exist_ok=True)
    suite = suite_for(policy, mapping, customers, roles.cfg.builder_model, repetitions, api)
    judge = judge or Judge(roles)
    raw = {"all_rows": [], "simulations": [], "suite": suite.key, "workflow_sha256": digest(workflow),
           "backend": "local_proxy", "model": roles.cfg.builder_model, "source_fingerprint": source_fingerprint(),
           "capabilities": CAPABILITIES, "calibration": calibration, "official": False}
    for rep in range(repetitions):
        started = time.monotonic()
        rows, calls = [], {}
        raw["all_rows"].append(rows)
        for customer in customers:
            try:
                deadline.require()
                recording = runner_factory(workflow, policy, mapping, customer, roles, deadline, api=api).run()
                calls[customer.id] = recording
                result = grade_case(policy, customer, recording, judge)
            except (ValueError, TimeoutError, RuntimeError) as exc:
                result = {"pass": None, "failed": [], "unknown": [str(exc)[:300]], "verified_hard_failure": False}
            row = {"id": customer.id, "family": customer.family, "call_id": customer.id, "repetition": rep, **result}
            rows.append(row)
            write_json(root / f"calls_{rep}.json", calls)
            write_json(root / "progress.json", raw)
        raw["simulations"].append({"seconds": time.monotonic() - started, "backend": "local_proxy", "repetition": rep})
    from .calibration import admitted
    eligible = admitted(calibration, policy, mapping, api, roles.cfg.builder_model)
    frozen = score(raw, suite)
    write_json(root / "raw_runner.json", raw, immutable=True)
    report = {"suite": asdict(suite), "score": asdict(frozen), "backend": "local_proxy", "official": False,
              "workflow_sha256": digest(workflow), "source_fingerprint": raw["source_fingerprint"],
              "selection_eligible": eligible and frozen.complete, "three_run_evidence": repetitions == 3 and frozen.complete,
              "calibration": calibration, "limitations": CAPABILITIES["limitations"]}
    write_json(root / "report.json", report, immutable=True)
    return report, raw


def read_workflow(path):
    value = json.loads(path.read_text())
    workflow = value.get("workflow", value)
    if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), dict):
        raise ValueError("Expected compiled workflow or exported workflow envelope")
    return workflow
