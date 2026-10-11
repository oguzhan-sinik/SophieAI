from datetime import date, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import uuid

import pytest

from generalisation_agent.bank import Bank, write_path
from generalisation_agent.config import ROOT, Settings, confined
from generalisation_agent.generation import customers_for, openapi_for, sample_mapping, sample_policy
from generalisation_agent.models import CORE_RULES, Policy
from generalisation_agent.oracle import grade_ledger
from generalisation_agent.packs import generate_packs, load_pack, render_checked
from generalisation_agent.reference import deadline, floor, legal_promise, money, next_business


@pytest.fixture
def work():
    private = ROOT / "private" / ("test-" + uuid.uuid4().hex)
    private.mkdir(parents=True)
    public = ROOT / "artifacts" / private.name
    try:
        yield private
    finally:
        shutil.rmtree(private)
        if public.exists(): shutil.rmtree(public)


class Roles:
    cfg = SimpleNamespace(builder_model="fixture", models={"hard": "fixture"})
    trace = SimpleNamespace(event=lambda *args, **kwargs: None)

    def __init__(self, mismatch=False):
        self.policy = None
        self.mismatch = mismatch

    def ask(self, role, purpose, instruction, payload, schema, **kwargs):
        if role == "synthetic_brief_writer":
            self.policy = payload["policy"]
            self.mapping = payload["mapping"]
            return {"markdown": "# Synthetic fixture\n" + "A grounded rendered policy. " * 8}
        policy = dict(self.policy)
        if self.mismatch: policy["wrong_answer_limit"] += 1
        return {"policy": policy, "mapping": self.mapping, "unresolved": [], "supported_core_rules": list(CORE_RULES)}


def request(mapping, operation, **args):
    result = {}
    for key, value in args.items():
        write_path(result, mapping.requests[operation][key], value)
    return result


def verified_bank(index=0, case_index=0):
    policy, mapping = sample_policy(42, index), sample_mapping(index)
    customer = customers_for(policy, 42)[case_index]
    bank = Bank(policy, mapping, customer)
    for field in policy.identity:
        bank.invoke("verify_identity", request(mapping, "verify_identity", customer_id=customer.id,
                                              field=field.name, answer=customer.identity[field.name]))
    return policy, mapping, customer, bank


def close(policy, mapping, customer, bank, outcome, reason=None):
    values = {"customer_id": customer.id, "outcome": policy.outcomes[outcome]}
    if reason: values["reason"] = policy.reasons[reason]
    bank.invoke("close_call", request(mapping, "close_call", **values))


def test_switches_are_strict_and_read_once(monkeypatch):
    monkeypatch.setenv("GENERALISATION_ENABLED", "false")
    settings = Settings.from_env()
    monkeypatch.setenv("GENERALISATION_ENABLED", "true")
    assert settings.enabled is False
    with pytest.raises(ValueError, match="disabled"): settings.require("briefs")
    assert Settings.from_env().enabled is True
    monkeypatch.setenv("GENERALISATION_USERS_ENABLED", "yes")
    with pytest.raises(ValueError, match="true or false"): Settings.from_env()


def test_output_paths_reject_escape_and_symlink(tmp_path, work):
    with pytest.raises(ValueError): confined(tmp_path)
    (work / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError): confined(work / "escape" / "file.json")
    from agent.builder.config import writable
    assert writable(work) == work
    with pytest.raises(ValueError): writable(tmp_path)


def test_generation_is_seeded_different_and_within_budget():
    a, b = sample_policy(42), sample_policy(42, 1)
    assert a == sample_policy(42)
    assert a != b and sample_mapping() != sample_mapping(1)
    assert customers_for(a, 42) == customers_for(a, 42)
    cases = customers_for(a, 42)
    assert len(cases) == 10 and len({c.family for c in cases}) == 10
    assert len({c.style for c in cases}) == 5 and len({c.now for c in cases}) > 1
    with pytest.raises(ValueError): customers_for(a, 42, 11)


def test_checked_packs_compile_and_detect_tampering(work):
    from agent.builder.contracts import compile_openapi
    top = generate_packs(Settings(True), Roles(), work)
    manifest = json.loads(top.read_text())
    assert [p["split"] for p in manifest["packs"]] == ["development", "holdout"]
    for pack in manifest["packs"]:
        assert len(compile_openapi(pack["openapi"])["operations"]) == 7
        m, policy, mapping, cases = load_pack(Path(pack["brief"]).parent / "manifest.json")
        assert len(cases) == 10 and m["complete_pack"]
        assert not (Path(pack["brief"]).parent / "users.json").exists()
    Path(manifest["packs"][0]["brief"]).write_text("Changed deadline")
    with pytest.raises(ValueError, match="changed"): load_pack(Path(manifest["packs"][0]["brief"]).parent / "manifest.json")


def test_render_mismatch_is_not_admitted():
    p, m = sample_policy(42), sample_mapping()
    with pytest.raises(ValueError, match="preserve"):
        render_checked(p, m, openapi_for(p, m, "fixture"), "clean", Roles(mismatch=True))


def test_render_attempts_are_inspectable(work):
    from agent.builder.artifacts import Trace
    p, m = sample_policy(42), sample_mapping()
    roles = Roles()
    roles.trace = Trace(work / "trace.log", {}, remote=False)
    renders = work / "pack-x" / "renders"
    render_checked(p, m, openapi_for(p, m, "fixture"), "clean", roles, renders)
    check = json.loads((renders / "attempt-1.check.json").read_text())
    assert check["policy_matches"] and not check["unresolved"]
    assert (renders / "final.brief.md").read_text().startswith("# Synthetic fixture")
    events = [json.loads(line)["event"] for line in roles.trace.path.read_text().splitlines() if line.strip()]
    assert "synthetic_render_accepted" in events


def test_render_retry_uses_review_and_still_requires_complete_semantics():
    class RepairRoles(Roles):
        writes = 0
        def ask(self, role, purpose, instruction, payload, schema, **kwargs):
            if role == "synthetic_brief_writer":
                self.writes += 1
                if self.writes == 2:
                    assert payload["previous_review"]["missing_core_rules"] == ["decimal_half_up"]
                    assert payload["previous_review"]["previous_brief"].startswith("# Synthetic fixture")
                return super().ask(role, purpose, instruction, payload, schema, **kwargs)
            result = super().ask(role, purpose, instruction, payload, schema, **kwargs)
            if self.writes == 1:
                result["supported_core_rules"].remove("decimal_half_up")
            return result
    p, m = sample_policy(42), sample_mapping()
    roles = RepairRoles()
    assert render_checked(p, m, openapi_for(p, m, "fixture"), "clean", roles).startswith("# Synthetic fixture")
    assert roles.writes == 2


def test_render_review_carries_field_level_differences():
    class DiffRoles(Roles):
        writes = 0
        def ask(self, role, purpose, instruction, payload, schema, **kwargs):
            if role == "synthetic_brief_writer":
                self.writes += 1
                if self.writes == 2:
                    differences = payload["previous_review"]["policy_differences"]
                    assert any("wrong_answer_limit" in d for d in differences), differences
                return super().ask(role, purpose, instruction, payload, schema, **kwargs)
            result = super().ask(role, purpose, instruction, payload, schema, **kwargs)
            if self.writes == 1:
                result["policy"]["wrong_answer_limit"] += 1
            return result
    p, m = sample_policy(42), sample_mapping()
    roles = DiffRoles()
    assert render_checked(p, m, openapi_for(p, m, "fixture"), "clean", roles).startswith("# Synthetic fixture")


def test_render_gets_three_attempts():
    class LateRoles(Roles):
        writes = 0
        def ask(self, role, purpose, instruction, payload, schema, **kwargs):
            if role == "synthetic_brief_writer":
                self.writes += 1
            result = super().ask(role, purpose, instruction, payload, schema, **kwargs)
            if role != "synthetic_brief_writer" and self.writes < 3:
                result["policy"]["wrong_answer_limit"] += 1
            return result
    p, m = sample_policy(42), sample_mapping()
    roles = LateRoles()
    assert render_checked(p, m, openapi_for(p, m, "fixture"), "clean", roles).startswith("# Synthetic fixture")
    assert roles.writes == 3


def test_disabled_generation_does_not_call_model(work):
    class NoModel:
        def ask(self, *args, **kwargs): raise AssertionError("Disabled model call")
    with pytest.raises(ValueError, match="disabled"):
        generate_packs(Settings(False), NoModel(), work)
    assert list(work.iterdir()) == []


def test_users_disabled_produces_explicit_partial_pack(work):
    top = generate_packs(Settings(True, True, False), Roles(), work)
    assert all(p["case_count"] == 0 and not p["complete_pack"] for p in json.loads(top.read_text())["packs"])


def test_calendar_and_cent_boundaries_have_reference_values():
    policy = sample_policy(42)
    product = customers_for(policy, 42)[0].products[0]
    now = datetime(2028, 12, 22, 11)
    assert next_business(policy, date(2028, 12, 23)) == date(2028, 12, 26)
    assert deadline(policy, product, now) == date(2029, 1, 11)
    limit = deadline(policy, product, now)
    assert legal_promise(policy, product, floor(policy, product), limit, now)
    assert not legal_promise(policy, product, floor(policy, product) - Decimal(".01"), limit, now)
    assert not legal_promise(policy, product, product.balance, date(2028, 12, 25), now)
    with pytest.raises(ValueError): money("NaN")
    with pytest.raises(ValueError): money("10.001")


@pytest.mark.parametrize("index", [0, 1])
def test_mock_is_permissive_but_oracle_fails_illegal_promise(index):
    p, m, c, bank = verified_bank(index)
    bank.invoke("create_promise", request(m, "create_promise", customer_id=c.id, product_id=c.products[0].id,
                                         amount=1.00, date="2028-12-25"))
    close(p, m, c, bank, "promise")
    assert len(bank.ledger["promises"]) == 1
    result = grade_ledger(p, c, bank.ledger)
    assert "Promise violates amount/calendar policy" in result["hard_failures"]


def test_identity_failure_and_bank_isolation():
    p, m = sample_policy(42), sample_mapping()
    c = customers_for(p, 42)[2]
    a, b = Bank(p, m, c), Bank(p, m, c)
    for _ in range(p.wrong_answer_limit):
        a.invoke("verify_identity", request(m, "verify_identity", customer_id=c.id, field=p.identity[0].name, answer="1991-07-12"))
    result = a.invoke("verify_identity", request(m, "verify_identity", customer_id=c.id,
                                                field=p.identity[0].name, answer=c.identity[p.identity[0].name]))
    assert result[m.response_root]["locked"] is True
    assert not b.wrong and not b.ledger["calls"]
    a.invoke("get_account", request(m, "get_account", customer_id=c.id))
    close(p, m, c, a, "not_verified", "failed")
    assert "Private account tool called before all identity fields passed" in grade_ledger(p, c, a.ledger)["hard_failures"]


def test_precommit_and_lost_reply_have_distinct_state_and_retry_verdicts():
    for index in (0, 1):
        p, m, c, bank = verified_bank(index, 8)
        args = request(m, "create_promise", customer_id=c.id, product_id=c.products[0].id,
                       amount=float(c.products[0].balance), date=next_business(p, c.now.date()).isoformat())
        first = bank.invoke("create_promise", args)[m.response_root]
        assert first["ok"] is False
        assert bool(bank.ledger["promises"]) == bool(index)
        bank.invoke("create_promise", args)
        close(p, m, c, bank, "promise")
        verdict = grade_ledger(p, c, bank.ledger)
        assert ("Promise retried after success or ambiguous commit" in verdict["hard_failures"]) == bool(index)


def test_third_party_actor_cannot_see_identity_or_grading_keys():
    from generalisation_agent.actors import customer_payload
    c = customers_for(sample_policy(42), 42)[1]
    payload = customer_payload(c)
    assert not {"identity", "products", "goals", "faults", "expected", "checks"}.intersection(payload)


def test_disabled_cli_exits_without_creating_synthetic_run():
    before = set((ROOT / "private").glob("*"))
    result = subprocess.run([sys.executable, "-B", "-m", "generalisation_agent", "generate"],
                            env={**os.environ, "GENERALISATION_ENABLED": "false"},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 2 and "disabled" in result.stderr
    assert set((ROOT / "private").glob("*")) == before


def test_legal_promise_passes_ledger_checks():
    p, m, c, bank = verified_bank()
    bank.invoke("create_promise", request(m, "create_promise", customer_id=c.id, product_id=c.products[0].id,
                                         amount=float(c.products[0].balance), date=c.now.date().isoformat()))
    close(p, m, c, bank, "promise")
    assert grade_ledger(p, c, bank.ledger)["ledger_pass"] is True
    assert bank.invoke("get_account", request(m, "get_account", customer_id=c.id))[m.response_root]["error"] == "call closed"


def test_identity_order_violation_is_caught_even_if_bank_allows_it():
    p, m = sample_policy(42), sample_mapping()
    c = customers_for(p, 42)[0]
    bank = Bank(p, m, c)
    for field in reversed(p.identity):
        bank.invoke("verify_identity", request(m, "verify_identity", customer_id=c.id, field=field.name, answer=c.identity[field.name]))
    close(p, m, c, bank, "no_promise", "refused")
    assert "Identity questions checked out of policy order" in grade_ledger(p, c, bank.ledger)["hard_failures"]


def test_request_shape_errors_commit_nothing():
    p, m, c, bank = verified_bank(1)
    result = bank.invoke("create_promise", {"customer_id": c.id, "sum_due": 100, "due_on": "20281225"})
    assert not result[m.response_root]["ok"] and not bank.ledger["promises"]
