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
