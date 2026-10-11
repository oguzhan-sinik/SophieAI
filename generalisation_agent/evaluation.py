"""Fixed-suite local evidence, with unknowns and exact workflow/source fingerprints."""
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time

from agent.builder.adk import ADKRoles
from agent.builder.artifacts import Trace, digest, write_json
from agent.builder.scoring import Suite, score

from .config import ROOT, confined, model_settings
from .judge import Judge
from .oracle import grade_ledger
from .runner import CAPABILITIES, Runner
from .sandbox import IMAGE


def source_fingerprint():
    files = sorted(ROOT.glob("*.py"))
    files += sorted((ROOT.parent / "agent" / "builder").glob("*.py"))
    files += sorted((ROOT / "fixtures").glob("**/*.*"))
    files += [ROOT.parent / name for name in ("freya.py", "public-test-set.json", "tools/run_cases.py",
              "tools/score.py", "tools/openapi.json", "briefs/brief-a.md", "briefs/brief-b.md")]
    return digest({str(path.relative_to(ROOT.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files})


def suite_for(policy, mapping, customers, model, repetitions, api=None):
    if not customers or not 1 <= repetitions <= 3:
        raise ValueError("Evaluation needs users and one to three repetitions")
    return Suite(tuple(c.id for c in customers), digest({"policy": policy.model_dump(mode="json"),
                 "mapping": mapping.model_dump(), "customers": [c.model_dump(mode="json") for c in customers],
                 "api": api, "model": model_settings(model), "source": source_fingerprint(), "capabilities": CAPABILITIES, "image": IMAGE}),
                 "generated", repetitions)


def grade_case(policy, customer, recording, judge):
    execution_unknown = list(recording.get("unknown", []))
    quality = recording.get("actor_quality")
    if recording.get("actor_required") and not quality:
        execution_unknown.append("Actor quality evidence missing")
    if quality:
        if quality.get("validity") != "valid":
            execution_unknown.append("Simulator-invalid customer speech/state")
        missing = [key for key, value in quality.get("coverage", {}).items() if value != "observed"]
        if missing:
            execution_unknown.append("Required actor behaviour not observed: " + ", ".join(missing))
    complete = not execution_unknown and recording.get("ended") is not None
    ledger = grade_ledger(policy, customer, recording["ledger"], complete=complete)
    try:
        spoken = judge.grade(policy, recording) if complete or recording.get("turns") else {"failed": [], "unknown": [], "hard_failures": []}
    except (ValueError, TimeoutError, RuntimeError) as exc:
        spoken = {"failed": [], "unknown": ["Transcript judgement unavailable: " + str(exc)[:300]], "hard_failures": []}
    failed = ledger["failed"] + spoken["failed"]
    unknown = execution_unknown + ledger["unknown"] + spoken["unknown"]
    return {"pass": False if failed else None if unknown else True, "failed": failed, "unknown": unknown,
            "verified_hard_failure": bool(ledger["hard_failures"] or spoken["hard_failures"]),
            "hard_failures": ledger["hard_failures"] + spoken["hard_failures"], "judge": spoken,
            "actor_quality": {key: quality[key] for key in ("validity", "coverage") if key in quality} if quality else None}


def evaluate_workflow(workflow, policy, mapping, customers, roles, deadline, root, repetitions=3,
                      api=None, runner_factory=Runner, judge=None, calibration=None, split="development", workers=1):
    if not 1 <= workers <= 4:
        raise ValueError("Offline worker count must be between one and four")
    if workers > 1 and (not isinstance(roles, ADKRoles) or judge is not None):
        raise ValueError("Parallel offline cases need isolated ADK roles and their own judges")
    root = confined(root)
    if not root.is_relative_to(ROOT / "private"):
        raise ValueError("Customer recordings and oracles must stay under private/")
    root.mkdir(parents=True, exist_ok=True)
    suite = suite_for(policy, mapping, customers, roles.cfg.models, repetitions, api)
    judge = judge or Judge(roles)
    from .quality import save_sample
    samples = []
    raw = {"all_rows": [], "simulations": [], "suite": suite.key, "workflow_sha256": digest(workflow),
           "backend": "local_proxy", "model": roles.cfg.models, "source_fingerprint": source_fingerprint(),
           "capabilities": CAPABILITIES, "calibration": calibration, "official": False}

    def one_case(index, customer, repetition):
        worker_roles, worker_judge, worker_trace = roles, judge, None
        if workers > 1:
            worker_root = root / "workers" / f"{repetition}-{index}"
            worker_root.mkdir(parents=True, exist_ok=False)
            worker_trace = Trace(worker_root / "trace.jsonl", {"component":"offline_case", "repetition":repetition,
                                                                  "case_index":index}, remote=False)
            worker_roles = ADKRoles(roles.cfg, deadline, worker_trace, worker_root)
            worker_judge = Judge(worker_roles)
        recording = None
        try:
            deadline.require()
            recording = runner_factory(workflow, policy, mapping, customer, worker_roles, deadline, api=api,
                                       repetition=repetition).run()
            recording["actor_required"] = True
            result = grade_case(policy, customer, recording, worker_judge)
        except (ValueError, TimeoutError, RuntimeError) as exc:
            result = {"pass": None, "failed": [], "unknown": [str(exc)[:300]], "verified_hard_failure": False}
        finally:
            if worker_trace:
                worker_trace.close(status="complete" if recording is not None else "incomplete")
        return customer, recording, result, worker_roles.calls if workers > 1 else 0

    for rep in range(repetitions):
        started = time.monotonic()
        rows, calls = [], {}
        raw["all_rows"].append(rows)
        executor = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
        try:
            outcomes = executor.map(lambda item: one_case(item[0], item[1], rep), enumerate(customers)) if executor else (
                one_case(index, customer, rep) for index, customer in enumerate(customers))
            for customer, recording, result, worker_calls in outcomes:
                if workers > 1:
                    roles.calls += worker_calls
                if recording is not None:
                    calls[customer.id] = recording
                    sample = save_sample(root,customer.id,rep,recording,customer.plan.profile if customer.plan else "legacy",split,"local_proxy")
                    if sample: samples.append(sample)
                row = {"id": customer.id, "family": customer.family, "call_id": customer.id, "repetition": rep, "profile": customer.plan.profile if customer.plan else "legacy",
                       "pair_id": customer.id.rsplit('_', 1)[0] if customer.plan and customer.id.endswith('_' + customer.plan.profile) else customer.id,
                       "semantic_revision": bool(customer.plan and any(e.kind == 'correction' for e in customer.plan.events)), **result}
                rows.append(row)
                write_json(root / f"calls_{rep}.json", calls)
                write_json(root / "progress.json", raw)
        finally:
            if executor: executor.shutdown(wait=True)
        raw["simulations"].append({"seconds": time.monotonic() - started, "backend": "local_proxy", "repetition": rep})
    from .calibration import admitted
    eligible = admitted(calibration, policy, mapping, api, roles.cfg.models)
    frozen = score(raw, suite)
    write_json(root / "review_samples.json", samples, immutable=True)
    write_json(root / "raw_runner.json", raw, immutable=True)
    report = {"suite": asdict(suite), "score": asdict(frozen), "backend": "local_proxy", "official": False,
              "workflow_sha256": digest(workflow), "source_fingerprint": raw["source_fingerprint"],
              "selection_eligible": eligible and frozen.complete, "three_run_evidence": repetitions == 3 and frozen.complete,
              "calibration": calibration_summary(calibration), "limitations": CAPABILITIES["limitations"],
              "customer_quality": quality_summary(raw), "human_review": "pending", "live_parity": "not_measured"}
    write_json(root / "report.json", report, immutable=True)
    return report, raw


def read_workflow(path):
    value = json.loads(path.read_text())
    workflow = value.get("workflow", value)
    if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), dict):
        raise ValueError("Expected compiled workflow or exported workflow envelope")
    return workflow


def quality_summary(raw):
    """Aggregate only; no facts, utterances, plans or private paths leave recordings."""
    rows = [row for repetition in raw.get("all_rows", []) for row in repetition]
    coverage, validity, profiles, pairs = {}, {}, {}, {}
    for row in rows:
        quality = row.get("actor_quality") or {"validity": "unknown", "coverage": {}}
        key = quality.get("validity", "unknown")
        validity[key] = validity.get(key, 0) + 1
        profile = row.get("profile", "legacy")
        profiles[profile] = profiles.get(profile, 0) + 1
        pairs.setdefault(row.get("pair_id", row["id"]), {}).setdefault(profile, []).append(row)
        for event, status in quality.get("coverage", {}).items():
            bucket = coverage.setdefault(event, {})
            bucket[status] = bucket.get(status, 0) + 1
    comparisons = {"paired_cases":0, "baseline_pass_stress_fail":0, "baseline_fail_stress_pass":0, "declared_revision_pairs":0}
    for group in pairs.values():
        if 'baseline' not in group or 'stress' not in group: continue
        comparisons['paired_cases'] += 1
        baseline = all(r.get('pass') is True and not r.get('unknown') for r in group['baseline'])
        stress = all(r.get('pass') is True and not r.get('unknown') for r in group['stress'])
        comparisons['baseline_pass_stress_fail'] += int(baseline and any(r.get('pass') is False for r in group['stress']))
        comparisons['baseline_fail_stress_pass'] += int(stress and any(r.get('pass') is False for r in group['baseline']))
        comparisons['declared_revision_pairs'] += int(any(r.get('semantic_revision') for r in group['stress']))
    return {"paired_comparisons": comparisons, "original_case_count": len({row["id"] for row in rows}), "recording_count": len(rows),
            "validity": validity, "profiles": profiles, "coverage": coverage,
            "coverage_gaps": [f"B{i:02d}" for i in range(1,17) if not coverage.get(f"B{i:02d}", {}).get("observed")]}


def calibration_summary(record):
    if not record: return None
    summary = {key:record[key] for key in ('fingerprint','admitted','oracle_admitted','false_passes','false_failures','unknowns') if key in record}
    summary['oracle_control_count'] = len(record.get('controls', []))
    actor = record.get('actor') or {}
    summary['actor_admitted'] = actor.get('admitted') is True
    summary['actor_control_count'] = len(actor.get('controls', []))
    return summary
