from pathlib import Path
from types import SimpleNamespace
import shutil
import tempfile

import pytest

from agent.builder.config import Deadline
from generalisation_agent.config import ROOT
from generalisation_agent.evaluation import evaluate_workflow, grade_case
from generalisation_agent.generation import customers_for, sample_mapping, sample_policy


def test_unsupported_execution_cannot_turn_into_a_failed_or_passing_suite():
    class Runner:
        def __init__(self, *args, **kwargs): pass
        def run(self): return {"ended": None, "unknown": ["Unsupported audio"], "turns": [], "ledger": {"calls": []}}
    policy = sample_policy(42)
    roles = SimpleNamespace(cfg=SimpleNamespace(builder_model="fixture"))
    (ROOT / "private").mkdir(exist_ok=True)
    path = Path(tempfile.mkdtemp(dir=ROOT / "private", prefix="test-eval-"))
    try:
        report, raw = evaluate_workflow({"nodes": {}}, policy, sample_mapping(), customers_for(policy, 42, 2), roles,
                                        Deadline(60), path, 3, runner_factory=Runner)
        assert report["score"]["unknown"] == 2 and report["score"]["strict_pass_rate"] is None
        assert not report["score"]["complete"] and not report["selection_eligible"]
        assert len(raw["all_rows"]) == 3 and all(len(rows) == 2 for rows in raw["all_rows"])
    finally:
        shutil.rmtree(path)


def test_observed_policy_failure_survives_judge_abstention():
    from generalisation_agent.bank import Bank, write_path
    policy, mapping = sample_policy(42), sample_mapping()
    customer = customers_for(policy, 42)[0]
    bank = Bank(policy, mapping, customer)
    body = {}
    write_path(body, mapping.requests["get_account"]["customer_id"], customer.id)
    bank.invoke("get_account", body)
    judge = SimpleNamespace(grade=lambda *args: {"failed": [], "unknown": ["judge unavailable"], "hard_failures": []})
    result = grade_case(policy, customer, {"ended": "end_call", "unknown": [], "turns": [], "ledger": bank.ledger}, judge)
    assert result["pass"] is False and result["verified_hard_failure"] and result["unknown"]
