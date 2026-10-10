"""Runnable checks for the observability studio. `python -m pytest observability/tests -q`"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from observability import diff as diffmod
from observability.demo import main as demo_main
from observability.server import Studio
from observability.store import ArtifactForbidden, ArtifactMissing, RunNotFound, Store


def make_store(tmp_path: Path) -> Store:
    out = tmp_path / "demo_run"
    demo_main(["--out", str(out)])
    return Store(tmp_path)


def test_discovery_and_summary(tmp_path):
    s = make_store(tmp_path)
    assert s.run_ids() == ["demo_run"]
    summ = s.run_summary("demo_run")
    assert summ["status"] == "succeeded"
    assert summ["champion_candidate_id"] == "cand_good"
    assert summ["final_score"] == 0.75
    assert summ["candidate_count"] == 3


def test_tree_records_all_candidates_and_edges(tmp_path):
    s = make_store(tmp_path)
    t = s.tree("demo_run")
    ids = {n["candidate_id"] for n in t["nodes"]}
    assert {"cand_root", "cand_bad", "cand_good"} <= ids
    assert t["recorded"] is True
    bad = next(n for n in t["nodes"] if n["candidate_id"] == "cand_bad")
    assert bad["valid"] is False and "response_mapping" in bad["errors"][0]
    assert t["champion_candidate_id"] == "cand_good"


def test_derived_lineage_when_no_jsonl(tmp_path):
    s = make_store(tmp_path)
    (s.run_dir("demo_run") / "lineage.jsonl").unlink()
    t = s.tree("demo_run")
    assert t["recorded"] is False
    assert len(t["nodes"]) == 3
    assert all(n["derived"] for n in t["nodes"])


def test_orphan_and_cycle_warnings(tmp_path):
    s = make_store(tmp_path)
    p = s.run_dir("demo_run") / "lineage.jsonl"
    events = [
        {"event": "candidate_created", "candidate_id": "a", "parent_id": "ghost",
         "created_at": "2026-10-10T18:00:00+00:00"},
        {"event": "candidate_created", "candidate_id": "b", "parent_id": "b",
         "created_at": "2026-10-10T18:00:01+00:00"},
    ]
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    t = s.tree("demo_run")
    assert any("orphan" in w for w in t["warnings"])
    assert any("cycle" in w for w in t["warnings"])
    assert len(t["nodes"]) == 2  # nothing silently dropped


def test_partial_trailing_jsonl_line_ignored(tmp_path):
    s = make_store(tmp_path)
    p = s.run_dir("demo_run") / "lineage.jsonl"
    p.write_text(p.read_text() + '{"event": "candidate_created", "candidate_id": "par')
    assert len(s.tree("demo_run")["nodes"]) == 3


def test_spans_pairing_and_payload_join(tmp_path):
    s = make_store(tmp_path)
    sp = s.spans("demo_run")
    llm = [x for x in sp["spans"] if x["kind"] == "llm"]
    assert len(llm) == 1
    call = llm[0]
    assert call["call_id"] == "model_001_demo"
    assert call["status"] == "succeeded"           # closed by ordered ADKModelCall_end
    assert call["tokens"]["total_token_count"] == 150
    assert call["duration_ms"] == 55000
    assert "prompt" in call["artifacts"]
    mc = s.model_call("demo_run", "model_001_demo")
    assert "instruction" in mc["prompt"]


def test_missing_prompt_is_none_not_invented(tmp_path):
    s = make_store(tmp_path)
    (s.run_dir("demo_run") / "model_calls/model_001_demo.prompt.json").unlink()
    mc = s.model_call("demo_run", "model_001_demo")
    assert "prompt" not in mc


def test_artifact_security(tmp_path):
    s = make_store(tmp_path)
    for bad in ("../../.env", "candidates/../../.env", ".env", "../x.json",
                "candidates/../manifest.json/../.env.example"):
        try:
            s.artifact("demo_run", bad)
            raise AssertionError(f"should have forbidden: {bad}")
        except (ArtifactForbidden, RunNotFound):
            pass
    try:
        s.artifact("demo_run", "candidates/cand_root/workflow.json")
    except ArtifactForbidden:
        raise AssertionError("legit artifact denied")
    # synthetic/ dir denied
    syn = s.run_dir("demo_run") / "synthetic"
    syn.mkdir()
    (syn / "holdout.json").write_text("{}")
    try:
        s.artifact("demo_run", "synthetic/holdout.json")
        raise AssertionError("synthetic served")
    except ArtifactForbidden:
        pass


def test_semantic_diff(tmp_path):
    s = make_store(tmp_path)
    parent = json.loads((s.run_dir("demo_run") / "candidates/cand_root/workflow.json").read_text())
    child = json.loads((s.run_dir("demo_run") / "candidates/cand_good/workflow.json").read_text())
    d = diffmod.diff_workflows(parent, child)
    assert not d["identical"]
    assert any("/nodes/verify_id" == c["path"] and c["op"] == "added" for c in d["changes"])
    assert "greeting" in d["changed_nodes"]  # transition retarget touches greeting
    assert d["summary"]["nodes_added"] == 1
    # greeting's transition retargeted
    assert any("greeting/transitions" in c["path"] for c in d["changes"])
    assert diffmod.diff_workflows(parent, json.loads(json.dumps(parent)))["identical"]


def test_diff_missing_parent_handled(tmp_path):
    s = make_store(tmp_path)
    cand = s.candidate("demo_run", "cand_good")
    cand["parent_candidate_id"] = "cand_root"
    # server route covers missing snapshot; direct: diff with unreadable bytes
    d = diffmod.diff_from_files(b"not json", b"{}")
    assert d["error"]


def test_api_routes_and_errors(tmp_path):
    st = Studio(str(tmp_path))
    make_store(tmp_path)
    status, body, _ = st.handle("GET", "/api/runs", {})
    assert status == 200 and body and json.loads(body)["count"] == 1
    status, body, _ = st.handle("GET", "/api/runs/demo_run/tree", {})
    assert status == 200 and json.loads(body)["roots"] == ["cand_root"]
    status, body, _ = st.handle("GET", "/api/runs/nope/tree", {})
    assert status == 404 and json.loads(body)["error"] == "RUN_NOT_FOUND"
    status, body, _ = st.handle("GET", "/api/runs/demo_run/candidates/ghost", {})
    assert status == 404 and json.loads(body)["error"] == "ARTIFACT_MISSING"
    status, body, _ = st.handle("GET", "/api/runs/demo_run/artifact", {"path": ["../../.env"]})
    assert status == 403 and json.loads(body)["error"] == "ARTIFACT_RESTRICTED"
    status, body, _ = st.handle("GET", "/api/runs/demo_run/candidates/cand_good/diff", {})
    assert status == 200 and json.loads(body)["summary"]["nodes_added"] == 1
    status, body, _ = st.handle("GET", "/api/runs/demo_run/metrics", {})
    m = json.loads(body)
    assert m["candidates"]["invalid"] == 1 and m["candidates"]["valid"] == 2


def test_run_isolation(tmp_path):
    """Two runs with the same candidate id stay isolated."""
    make_store(tmp_path)
    demo_main(["--out", str(tmp_path / "demo_run2")])
    st = Studio(str(tmp_path))
    _, body, _ = st.handle("GET", "/api/runs", {})
    assert json.loads(body)["count"] == 2
    # mutate run2's champion to prove no cross-run bleed
    p = tmp_path / "demo_run2/report.json"
    rep = json.loads(p.read_text()); rep["candidate_id"] = "cand_bad"; p.write_text(json.dumps(rep))
    _, b1, _ = st.handle("GET", "/api/runs/demo_run", {})
    _, b2, _ = st.handle("GET", "/api/runs/demo_run2", {})
    assert json.loads(b1)["champion_candidate_id"] == "cand_good"
    assert json.loads(b2)["champion_candidate_id"] == "cand_bad"


if __name__ == "__main__":
    import tempfile

    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as td:
                try:
                    fn(Path(td))
                    print(f"PASS {name}")
                except Exception as e:  # noqa: BLE001
                    fails += 1
                    print(f"FAIL {name}: {type(e).__name__}: {e}")
    raise SystemExit(1 if fails else 0)


def test_run_without_report_is_running_until_it_goes_quiet(tmp_path):
    from datetime import datetime, timedelta, timezone
    for name, age in (("live", 30), ("dead", 3600)):
        d = tmp_path / name
        d.mkdir()
        at = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
        (d / "manifest.json").write_text(json.dumps({"run_id": name, "start": at}))
        (d / "build_trace.log").write_text(json.dumps({"at": at, "event": "run_start"}) + "\n")
    s = Store(tmp_path)
    assert s.run_summary("live")["status"] == "running"
    assert s.run_summary("dead")["status"] == "interrupted"
