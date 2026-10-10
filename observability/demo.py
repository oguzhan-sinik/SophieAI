"""Generate a synthetic demo run so the studio works offline (no Freya/LLM).

    python -m observability.demo --out agent/artifacts/demo_run
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

T0 = "2026-10-10T18:00:00+00:00"


def _wf(prompt: str, extra_node: str | None = None) -> dict:
    nodes = {
        "greeting": {"name": "greeting", "node_type": "conversation",
                     "task_message": "Say hello and verify identity.",
                     "transitions": [{"target_node": "lookup", "description": "verified"}]},
        "lookup": {"name": "lookup", "node_type": "conversation",
                   "task_message": prompt,
                   "transitions": [{"target_node": "done", "description": "account found"}]},
        "done": {"name": "done", "node_type": "conversation", "task_message": "Goodbye.",
                 "transitions": []},
    }
    if extra_node:
        nodes["verify_id"] = {"name": "verify_id", "node_type": "conversation",
                              "task_message": "Ask for date of birth and verify.",
                              "transitions": [{"target_node": "lookup", "description": "identity verified"}]}
        nodes["greeting"]["transitions"][0]["target_node"] = "verify_id"
    return {"initial_node": "greeting", "system_prompt": "You are Freya Bank's assistant.",
            "nodes": nodes}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="artifacts/demo_run")
    args = ap.parse_args(argv)
    d = Path(args.out)
    (d / "candidates" / "cand_root").mkdir(parents=True, exist_ok=True)
    (d / "candidates" / "cand_bad").mkdir(parents=True, exist_ok=True)
    (d / "candidates" / "cand_good").mkdir(parents=True, exist_ok=True)
    (d / "model_calls").mkdir(exist_ok=True)

    manifest = {"run_id": d.name, "start": T0,
                "config": {"mode": "scoring_with_diagnostics",
                           "builder_model": "demo/demo-model", "max_wall_seconds": 1800},
                "brief_hash": "0" * 16, "openapi_hash": "1" * 16}
    (d / "manifest.json").write_text(json.dumps(manifest, indent=1))

    trace = [
        {"at": T0, "event": "run_start", "run_id": d.name, "mode": "scoring_with_diagnostics",
         "brief_hash": "0" * 16, "langsmith_enabled": False},
        {"at": "2026-10-10T18:00:05+00:00", "event": "ADKModelCall_start",
         "call_id": "model_001_demo", "role": "ADASDesignerAgent", "model": "demo/demo-model",
         "purpose": "Generate root workflow", "prompt_version": "ticket01-v1",
         "prompt_hash": "a" * 16},
        {"at": "2026-10-10T18:00:45+00:00", "event": "model_usage", "call_id": "model_001_demo",
         "model": "demo/demo-model", "estimated_cost": None,
         "tokens": [{"prompt_token_count": 100, "candidates_token_count": 50, "total_token_count": 150}]},
        {"at": "2026-10-10T18:01:00+00:00", "event": "ADKModelCall_end"},
        {"at": "2026-10-10T18:02:00+00:00", "event": "candidate_created", "candidate_id": "cand_root",
         "parent_id": None, "generation": 0, "mutation_kind": "baseline"},
        {"at": "2026-10-10T18:02:01+00:00", "event": "validation", "candidate_id": "cand_root",
         "valid": True, "evidence_type": "static", "errors": []},
        {"at": "2026-10-10T18:03:00+00:00", "event": "candidate_created", "candidate_id": "cand_bad",
         "parent_id": "cand_root", "generation": 1, "mutation_kind": "change_prompt"},
        {"at": "2026-10-10T18:03:01+00:00", "event": "validation", "candidate_id": "cand_bad",
         "valid": False, "evidence_type": "static",
         "errors": ["node lookup: response_mapping references unknown variable"]},
        {"at": "2026-10-10T18:04:00+00:00", "event": "candidate_created", "candidate_id": "cand_good",
         "parent_id": "cand_root", "generation": 1, "mutation_kind": "add_guard"},
        {"at": "2026-10-10T18:04:01+00:00", "event": "validation", "candidate_id": "cand_good",
         "valid": True, "evidence_type": "static", "errors": []},
        {"at": "2026-10-10T18:06:00+00:00", "event": "run_end", "run_id": d.name, "status": "succeeded",
         "candidate_id": "cand_good", "final_score": 0.75, "strict_pass_rate": 0.75,
         "evaluation_type": "official_public", "simulations": 2, "model_calls": 1,
         "valid_candidates": 2, "invalid_candidates": 1, "seconds": 360},
    ]
    (d / "build_trace.log").write_text(
        "\n".join(json.dumps(e) for e in trace) + "\n")

    lineage = [e for e in trace if e["event"] in ("candidate_created", "validation")]
    (d / "lineage.jsonl").write_text("\n".join(json.dumps(e) for e in lineage) + "\n")

    root_wf = _wf("Look up the account {{account_number}}.")
    good_wf = _wf("Look up the account {{account_number}}.", extra_node=True)
    (d / "candidates/cand_root/workflow.json").write_text(json.dumps(root_wf, indent=1))
    (d / "candidates/cand_bad/workflow.json").write_text(
        json.dumps(_wf("Look up {{wrong_var}}."), indent=1))
    (d / "candidates/cand_good/workflow.json").write_text(json.dumps(good_wf, indent=1))
    for cid in ("cand_root", "cand_bad", "cand_good"):
        valid = cid != "cand_bad"
        (d / f"candidates/{cid}/validation.json").write_text(json.dumps(
            {"valid": valid, "errors": [] if valid else ["bad response_mapping"],
             "evidence_type": "static", "reachable_nodes": 4, "covered_rules": 3,
             "policy_proven": valid}))
    (d / "candidates/cand_root/proposal.json").write_text(json.dumps(
        {"coverage": {"covered": 7}, "architecture": "baseline", "tool_gates": []}, indent=1))

    (d / "model_calls/model_001_demo.prompt.json").write_text(json.dumps(
        {"instruction": "Generate a WorkflowSpec for the supplied policy.",
         "payload": {"brief": "SYNTHETIC DEMO BRIEF"}, "output_schema": {"type": "object"}}))
    (d / "model_calls/model_001_demo.response.json").write_text(
        json.dumps({"workflow": root_wf, "coverage": {"covered": 7}}))
    (d / "model_calls/model_001_demo.raw_response.json").write_text(json.dumps(root_wf))

    (d / "report.json").write_text(json.dumps({
        "run_id": d.name, "status": "succeeded", "candidate_id": "cand_good",
        "final_score": 0.75, "strict_pass_rate": 0.75, "evaluation_type": "official_public",
        "start": T0, "end": "2026-10-10T18:06:00+00:00", "seconds": 360,
        "simulations": 2, "valid_candidates": 2, "invalid_candidates": 1, "model_calls": 1,
    }, indent=1))
    print(f"demo run written to {d}")


if __name__ == "__main__":
    main()
