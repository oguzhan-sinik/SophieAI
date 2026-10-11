import json
from pathlib import Path

from agent.builder import artifacts
from generalisation_agent import progress
from observability.server import Studio


def test_dashboard_progress_keeps_evidence_private(monkeypatch, tmp_path):
    monkeypatch.setattr(artifacts, "writable", Path)
    monkeypatch.setattr(progress, "writable", Path)
    monkeypatch.setattr(progress, "AGENT", tmp_path / "agent")
    trace = artifacts.Trace(tmp_path / "private" / "run" / "build_trace.log",
                            {"model": "doubleword/zai-org/GLM-5.3-Flash", "holdout": "SEALED_CASE"}, remote=False)
    progress.publish_progress(trace)
    trace.event("ADKModelCall_start", role="judge", call_id="model_1", prompt="PRIVATE_PROMPT", payload={"customer": "SEALED_CASE"})
    trace.event("model_usage", call_id="model_1", tokens=[{"total_token_count": 123, "thoughts_token_count": 100,
                "unexpected": "PRIVATE_RESPONSE", "prompt_token_count": "PRIVATE_RESPONSE"}])
    trace.event("synthetic_render_rejected", unresolved=["SEALED_CASE"])
    studio = Studio(str(tmp_path / "agent" / "artifacts"))
    status, raw, _ = studio.handle("GET", "/api/runs/synthetic_run/spans", {})
    assert status == 200
    call = next(s for s in json.loads(raw)["spans"] if s["kind"] == "llm")
    assert call["status"] == "running"
    assert call["tokens"] == {"total_token_count": 123, "thoughts_token_count": 100}
    assert "artifacts" not in call
    trace.event("ADKModelCall_error", error="ValidationError", message="PRIVATE_RESPONSE")
    trace.event("ADKModelCall_end")
    trace.close(status="failed", report="PRIVATE_PATH")
    assert studio.store.run_summary("synthetic_run")["status"] == "failed"
    call = next(s for s in studio.store.spans("synthetic_run")["spans"] if s["kind"] == "llm")
    assert call["status"] == "failed" and call["error"] == "ValidationError"
    files = list((tmp_path / "agent" / "artifacts" / "synthetic_run").iterdir())
    published = "".join(p.read_text() for p in files)
    assert all(secret not in published for secret in ("SEALED_CASE", "PRIVATE_PROMPT", "PRIVATE_RESPONSE", "PRIVATE_PATH"))
    assert {p.name for p in files} == {"manifest.json", "build_trace.log", "report.json"}


def test_a_practice_script_diagnostic_is_shown_as_a_test_with_its_customers(monkeypatch, tmp_path):
    monkeypatch.setattr(artifacts, "writable", Path)
    monkeypatch.setattr(progress, "writable", Path)
    monkeypatch.setattr(progress, "AGENT", tmp_path / "agent")
    private = tmp_path / "private" / "run"
    trace = artifacts.Trace(private / "build_trace.log", {"model": "fixture"}, remote=False)
    progress.publish_progress(trace)
    public = tmp_path / "agent" / "artifacts" / "synthetic_run" / "evaluations" / "live"
    with progress.mirrored(private / "live", public):
        trace.event("OfficialBenchmark_start", repetition=0, evaluation_folder="live", suite_key="k", prompt="PRIVATE_PROMPT")
        (private / "live").mkdir()
        (private / "live" / "raw_runner.json").write_text(json.dumps({"all_rows": [[{"id": "PUB-01", "pass": True, "profile": "stress"},
                                                                                     {"id": "PUB-02", "pass": None, "unknown": ["coverage unavailable"]}]], "simulations": []}))
        (private / "live" / "calls_0.json").write_text(json.dumps({"PUB-01": {"turns": [{"role": "assistant", "text": "Hello."}]}}))
        (private / "live" / "review_samples.json").write_text(json.dumps(["SEALED_CASE"]))
        trace.event("official_result", repetition=0, passed=1, total=2, status="completed")
        trace.event("OfficialBenchmark_end")
    studio = Studio(str(tmp_path / "agent" / "artifacts"))
    test = next(s for s in studio.store.spans("synthetic_run")["spans"] if s["kind"] == "benchmark")
    # Its own name, its customers (an undecided one stays undecided) and its conversations.
    assert test["name"] == "Persona test · 1/2 passed" and test["status"] == "succeeded"
    assert [(r["id"], r["pass"]) for r in test["results"]] == [("PUB-01", True), ("PUB-02", None)]
    assert test["transcripts"] == "evaluations/live/calls_0.json"
    # Only what the dashboard reads is copied, and a model call still publishes no message.
    assert {p.name for p in public.iterdir()} == {"raw_runner.json", "calls_0.json"}
    trace.event("ADKModelCall_error", error="ValidationError", message="PRIVATE_RESPONSE")
    published = (tmp_path / "agent" / "artifacts" / "synthetic_run" / "build_trace.log").read_text()
    assert "PRIVATE_RESPONSE" not in published and "PRIVATE_PROMPT" not in published


def test_a_mirror_with_nowhere_to_publish_leaves_the_test_alone(tmp_path):
    with progress.mirrored(tmp_path / "private", tmp_path / "outside" / "evaluations") as public:
        assert public is None
    assert not (tmp_path / "outside").exists()

