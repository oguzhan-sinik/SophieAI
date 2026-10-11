from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import uuid

import pytest

from agent.builder.artifacts import digest, write_json
from agent.builder.build import Builder
from agent.builder.config import Config, Deadline
from agent.builder.freya_adapter import FreyaAdapter
from agent.builder.scoring import Suite
from generalisation_agent.bank import Bank, operations_for, validate_mapping
from generalisation_agent.calibration import admitted, fingerprint, fixtures
from generalisation_agent.config import ROOT
from generalisation_agent.generation import customers_for, openapi_for, sample_mapping, sample_policy
from generalisation_agent.integration import GeneratedProvider
from generalisation_agent.oracle import grade_ledger


@pytest.fixture
def work():
    root = ROOT / "private" / ("test-integration-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    yield root
    shutil.rmtree(root)


def test_operation_urls_and_verification_response_names_are_source_bound():
    p, m = sample_policy(42, 1), sample_mapping(1)
    api = openapi_for(p, m, "bindings")
    api["paths"]["/security/challenge"] = api["paths"].pop("/verify_identity")
    bank = Bank(p, m, customers_for(p, 42)[0], api)
    assert bank.operations["verify_identity"]["url"].endswith("/security/challenge")
    assert m.response_fields["field_verified"] == "verified"
    broken = deepcopy(api)
    schema = broken["paths"]["/security/challenge"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema["properties"][m.response_root]["properties"].pop("verified")
    with pytest.raises(ValueError, match="response binding"):
        validate_mapping(p, m, operations_for(broken))


def test_authored_ledger_controls_detect_critical_failures():
    p, m = sample_policy(42), sample_mapping()
    controls = {name: (customer, recording) for name, customer, recording, _, _ in fixtures(p, m, openapi_for(p, m, "controls"))}
    for name in ("compliant", "equivalent_wording"):
        customer, recording = controls[name]
        assert grade_ledger(p, customer, recording["ledger"])["ledger_pass"]
    for name in ("below_floor", "duplicate_retry", "false_identity", "wrong_closure"):
        customer, recording = controls[name]
        assert grade_ledger(p, customer, recording["ledger"])["hard_failures"], name


def test_calibration_invalidates_model_mapping_and_incomplete_controls():
    p, m = sample_policy(42), sample_mapping()
    api = openapi_for(p, m, "fingerprint")
    record = {"admitted": True, "fingerprint": fingerprint(p, m, api, "fixture"), "false_passes": 0,
              "false_failures": 0, "unknowns": 0, "controls": [{"target_detected": True}] * 12}
    assert not admitted(record, p, m, api, "fixture")
    record["actor"] = {"fingerprint": record["fingerprint"], "admitted": True, "controls": [{"passed": True}] * 9}
    assert admitted(record, p, m, api, "fixture")
    assert not admitted(record, p, m, api, "other-model")
    assert not admitted({**record, "unknowns": 1}, p, m, api, "fixture")
    assert not admitted({**record, "controls": [{}]}, p, m, api, "fixture")
    renamed = m.model_copy(deep=True)
    renamed.response_fields["field_verified"] = "changed"
    assert not admitted(record, p, renamed, api, "fixture")


def test_official_ranking_is_separate_and_only_calibrated_exact_hash_can_veto():
    p, m = sample_policy(42), sample_mapping()
    api, customers = openapi_for(p, m, "selection"), customers_for(p, 42, 1)
    record = {"admitted": True, "fingerprint": fingerprint(p, m, api, "fixture"), "false_passes": 0,
              "false_failures": 0, "unknowns": 0, "controls": [{"target_detected": True}] * 12}
    record["actor"] = {"fingerprint": record["fingerprint"], "admitted": True, "controls": [{"passed": True}] * 9}
    provider = GeneratedProvider(p, m, api, customers, "fixture", 1, record)
    official = Suite(("PUB-01",), "official", "official_public", 1)
    assert provider.bind(official, ["PUB-01"]) == (official, ["PUB-01"])
    provider.results["exact"] = {"critical_failures": [customers[0].id], "calibration_fingerprint": record["fingerprint"]}
    assert provider.vetoed("exact") and not provider.vetoed("wording-child")
    provider.calibrated = False
    assert not provider.vetoed("exact")
    assert provider.bind(None, []) == (None, [])


def test_lock_failure_never_enters_mutation_body(monkeypatch, work):
    @contextmanager
    def no_lock(*args): yield False
    monkeypatch.setattr("agent.builder.freya_adapter.file_lock", no_lock)
    adapter = FreyaAdapter.__new__(FreyaAdapter)
    adapter.deadline = Deadline(60)
    adapter.runtime = work
    adapter.trace = SimpleNamespace(event=lambda *a, **k: None)
    with pytest.raises(TimeoutError, match="Workspace lock"):
        with adapter.workspace():
            raise AssertionError("Must not deploy or simulate without lock")


class FakeAdapter:
    def __init__(self, *args): self.deployment = None
    @contextmanager
    def workspace(self): yield self
    def deploy(self, slot, workflow):
        self.deployment = {"workflow_hash": digest(workflow), "workflow_id": "fixture", "agent_id": "fixture"}
    def export(self, workflow, path):
        write_json(path, {"workflow": workflow, "test_only": True})
        return str(path)


class FixtureProvider:
    seconds_per_repetition = 1
    def __init__(self, veto=False): self.reject = veto
    def bind(self, suite, cases): return Suite(("case",), "fixed", "generated", 1), []
    def manifest(self): return {"fixture": True}
    def vetoed(self, workflow_hash): return self.reject
    def evaluate(self, workflow, adapter, folder, roles, deadline):
        return {"all_rows": [[{"id": "case", "pass": not self.reject}]], "simulations": []}


def fixture_builder(work, provider):
    brief, api = work / "brief.md", work / "openapi.json"
    brief.write_text("Fictional integration fixture.")
    p, m = sample_policy(42), sample_mapping()
    write_json(api, openapi_for(p, m, "build-fixture"))
    class Roles:
        def __init__(self, *args): self.calls = 0
    builder = Builder(Config(artifacts=work / "builds", tracing=False, official=False, max_simulations=1),
                      [brief], api, roles_factory=Roles, adapter_factory=FakeAdapter,
                      evaluation_provider=provider, submission_dir=work / "out")
    workflow = {"initial_node": "end", "nodes": {"end": {"node_type": "end_call"}}, "global_nodes": {}}
    builder.build_root = lambda: builder.record(workflow, workflow, {"valid": True, "errors": [], "warnings": []}, kind="design")
    return builder


def test_all_vetoed_build_retains_tested_export_without_submission(work):
    builder = fixture_builder(work, FixtureProvider(veto=True))
    result = builder.run()
    assert result["status"] == "failed" and result["export_path"] is None
    assert "No eligible candidate" in result["error"]
    assert builder.exports and not (work / "out").exists()


def test_tested_candidate_exports_at_its_own_hash(work):
    builder = fixture_builder(work, FixtureProvider())
    result = builder.run()
    assert result["status"] == "exported" and result["final_score"]["complete"]
    exported = json.loads(Path(result["export_path"]).read_text())["workflow"]
    assert builder.adapter.deployment["workflow_hash"] == digest(exported)
    assert not result["wording_untested"]


def test_master_off_delegates_without_loading_model_context(monkeypatch):
    from generalisation_agent.__main__ import main
    monkeypatch.setenv("GENERALISATION_ENABLED", "false")
    seen = []
    monkeypatch.setattr("agent.builder.build.main", lambda argv: seen.append(argv) or 7)
    monkeypatch.setattr("generalisation_agent.packs.model_context", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No synthetic work")))
    assert main(["build", "brief.md", "--openapi", "api.json"]) == 7
    assert seen == [["brief.md", "--openapi", "api.json"]]


def test_higher_official_score_can_be_vetoed_without_score_merging():
    builder = Builder.__new__(Builder)
    builder.archive = SimpleNamespace(workflow=lambda cid: {"candidate": cid})
    builder.measured = {"a": {"score": SimpleNamespace(complete=True, passed=13)},
                        "b": {"score": SimpleNamespace(complete=True, passed=12)}}
    builder.wording = {}
    rejected = {digest({"candidate": "a"})}
    builder.evaluation_provider = SimpleNamespace(vetoed=lambda workflow_hash: workflow_hash in rejected)
    assert builder.champion("a") == "b"
    rejected.add(digest({"candidate": "b"}))
    assert builder.champion("a") is None


def test_local_adapter_exports_compiled_json_without_platform_claims(work):
    from generalisation_agent.local_adapter import LocalAdapter
    adapter = LocalAdapter(Config(), Deadline(60), SimpleNamespace(event=lambda *a, **k: None))
    workflow = {"nodes": {"end": {"node_type": "end_call"}}}
    with adapter.workspace():
        adapter.deploy("local", workflow)
        exported = adapter.export(workflow, work / "compiled.json")
    value = json.loads(Path(exported).read_text())
    assert value["workflow"] == workflow and value["platform_export"] is False
    assert not adapter.deployment.get("workflow_id")
    with pytest.raises(ValueError): adapter.evaluate([], None, work)


def test_synthetic_wording_change_is_measured_and_does_not_inherit_score(work):
    from dataclasses import replace
    class Provider(FixtureProvider):
        def __init__(self): super().__init__(); self.hashes = []
        def evaluate(self, workflow, adapter, folder, roles, deadline):
            self.hashes.append(digest(workflow))
            return {"all_rows": [[{"id": "case", "pass": len(self.hashes) > 1}]], "simulations": []}
    provider = Provider()
    builder = fixture_builder(work, provider)
    builder.cfg = replace(builder.cfg, max_simulations=2)
    workflow = {"initial_node": "end", "system_prompt": "Original", "nodes": {"end": {"node_type": "end_call"}}, "global_nodes": {}}
    valid = {"valid": True, "errors": [], "warnings": []}
    builder.build_root = lambda: builder.record({"workflow": workflow}, workflow, valid, kind="design")
    patch = {"problem": "Change wording", "cases": ["case"], "edits": [{"op": "set_workflow_field", "stage": "", "field": "system_prompt", "value": "Changed"}]}
    builder.fix = lambda *a, **k: {"fixes": [patch]}
    def apply(source, fixes, **kwargs):
        child = deepcopy(source)
        child["workflow"]["system_prompt"] = "Changed"
        return child, fixes, []
    builder.apply_fixes = apply
    builder.check = lambda source, **kwargs: (source["workflow"], valid)
    result = builder.run()
    assert len(set(provider.hashes)) == 2 and result["simulations"] == 2
    assert not result["wording_untested"] and result["final_score"]["passed"] == 1
    assert digest(json.loads(Path(result["export_path"]).read_text())["workflow"]) == provider.hashes[-1]


def test_holdout_users_only_enter_post_build_evaluation(monkeypatch, work):
    import generalisation_agent.integration as integration
    from generalisation_agent.config import Settings
    p, m = sample_policy(42), sample_mapping()
    customers = customers_for(p, 42, 1)
    brief, api = work / "brief.md", work / "openapi.json"
    brief.write_text("Supplied holdout brief.")
    write_json(api, openapi_for(p, m, "holdout"))
    monkeypatch.setattr(integration, "missing_credentials", lambda cfg: [])
    trace = SimpleNamespace(close=lambda **k: None)
    roles = SimpleNamespace(cfg=Config(builder_model="fixture"))
    monkeypatch.setattr(integration, "model_context", lambda *a, **k: (roles, trace, Deadline(1800), work))
    monkeypatch.setattr(integration, "interpret_source", lambda *a: (_ for _ in ()).throw(AssertionError("No holdout preparation")))
    monkeypatch.setattr(integration, "calibrate", lambda *a: (_ for _ in ()).throw(AssertionError("No holdout case feedback")))
    built = []
    class Builder:
        slot = "fixture"
        def __init__(self, cfg, briefs, api_path, **kwargs):
            assert not cfg.official and kwargs["evaluation_provider"] is None
            from generalisation_agent.local_adapter import LocalAdapter
            assert kwargs["adapter_factory"] is LocalAdapter
        def run(self):
            built.append(True)
            write_json(work / "export.json", {"workflow": {"nodes": {}}})
            return {"export_path": str(work / "export.json"), "seconds": 0, "status": "exported"}
    def evaluate(workflow, policy, mapping, cases, *args, **kwargs):
        assert built and cases == customers
        return {"score": {"complete": False}, "backend": "local_proxy"}, {}
    monkeypatch.setattr(integration, "evaluate_workflow", evaluate)
    try:
        result = integration.run_build(Settings(True), [brief], api, pack=({}, p, m, customers), holdout=True,
                                       cfg=Config(builder_model="fixture"), builder_factory=Builder)
        assert result["holdout"] and result["export_type"] == "local_compiled"
    finally:
        shutil.rmtree(ROOT / "artifacts" / work.name, ignore_errors=True)


def test_calibration_abstention_blocks_admission(monkeypatch, work):
    import generalisation_agent.calibration as calibration
    p, m = sample_policy(42), sample_mapping()
    api = openapi_for(p, m, "abstention")
    _, customer, recording, _, _ = calibration.fixtures(p, m, api)[0]
    monkeypatch.setattr(calibration.DockerCode, "ready", lambda self: None)
    class Runner:
        def __init__(self, *a, **k): pass
        def run(self): return recording
    judge = SimpleNamespace(grade=lambda *a: {"failed": [], "unknown": ["independent judges disagree"], "hard_failures": []})
    roles = SimpleNamespace(cfg=SimpleNamespace(builder_model="fixture", models={"hard": "fixture"}))
    result = calibration.calibrate(p, m, api, roles, Deadline(60), work / "calibration", runner_factory=Runner, judge=judge)
    assert not result["admitted"] and result["unknowns"] >= 1
    assert len(result["controls"]) == 12


def test_confirmation_proofs_must_precede_the_exact_write():
    from generalisation_agent.judge import Judge
    from generalisation_agent.models import CORE_RULES
    p = sample_policy(42)
    turns = [{"role": "assistant", "text": "Read back 100 on 2028-12-20 for p1", "step": 1},
             {"role": "user", "text": "Yes", "step": 2}]
    def reading(amount):
        return {"checks": [{"rule": rule, "verdict": "pass", "reason": "fixture", "evidence": [{"turn": 0, "quote": "Read back"}]} for rule in CORE_RULES],
                "confirmations": [{"product_id": "p1", "amount": amount, "date": "2028-12-20", "readback": {"turn": 0, "quote": "Read back"},
                                   "agreement": {"turn": 1, "quote": "Yes"}, "corrections": []}]}
    class Roles:
        amount = "100"
        def ask(self, *a, **k): return reading(self.amount)
    roles = Roles()
    recording = {"turns": turns, "ledger": {"calls": [{"tool": "create_promise", "args": {"product_id": "p1", "amount": 100, "date": "2028-12-20"}, "step": 3}]}}
    assert not Judge(roles).grade(p, recording)["unknown"]
    roles.amount = "99.99"
    assert Judge(roles).grade(p, recording)["unknown"]
    roles.amount = "100"
    recording["ledger"]["calls"][0]["step"] = 2
    assert Judge(roles).grade(p, recording)["unknown"]


def test_calibrated_development_failures_reach_fixer_without_changing_primary_score(work):
    class Provider(FixtureProvider):
        def feedback(self, workflow_hash):
            return {"verdicts": {"SYN_dev": False}, "findings": {"SYN_dev": ["Verified disclosure"]},
                    "failed_calls": {"SYN_dev": {"turns": []}}, "visited": {"SYN_dev": {"end"}}}
    builder = fixture_builder(work, Provider())
    seen = []
    builder.fix = lambda *a, **k: seen.append((a, k)) or {"fixes": []}
    from dataclasses import replace
    builder.cfg = replace(builder.cfg, max_simulations=2)
    result = builder.run()
    measured = builder.measured[result["candidate_id"]]
    assert measured["score"].passed == 1 and measured["score"].total == 1
    assert measured["verdicts"]["SYN_dev"] is False
    assert seen and "SYN_dev" in str(seen[0])
