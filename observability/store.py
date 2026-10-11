"""Read-only artifact store: discovers runs, parses artifacts, builds projections.

Every field served downstream comes from files on disk. Missing data stays
null and is labeled "derived" when we reconstructed it rather than recorded it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_ARTIFACT_BYTES = 10 * 1024 * 1024  # OBS_MAX_ARTIFACT_READ_BYTES default
DENY_TOP_LEVEL = {"synthetic", ".env", ".runtime", "__pycache__"}
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


LIVE_SECONDS = 600
# Candidate kinds of the fix loop: one batch of fixes per round, wording committed unmeasured,
# and a branch that drops a blamed fix.
FIX_KINDS = {"fixes": "Fixes", "wording": "Wording only (not simulated)", "revert_branch": "Branch without the blamed fix"}


class ArtifactForbidden(Exception):
    pass


class ArtifactMissing(Exception):
    pass


class RunNotFound(Exception):
    pass


class _Cache:
    """mtime+size keyed cache so live runs re-read only changed files."""

    def __init__(self) -> None:
        self._d: dict[str, tuple[tuple[int, int], Any]] = {}

    def get(self, path: Path, load):
        try:
            st = path.stat()
        except OSError:
            self._d.pop(str(path), None)
            return None
        key = (st.st_mtime_ns, st.st_size)
        hit = self._d.get(str(path))
        if hit and hit[0] == key:
            return hit[1]
        try:
            val = load(path)
        except (OSError, ValueError):
            return None
        self._d[str(path)] = (key, val)
        return val


def _load_json(path: Path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # trailing partial line until writer completes it
    return out


def _safe_int(v):
    return v if isinstance(v, (int, float)) else None


class Store:
    def __init__(self, artifacts_dir: str | os.PathLike) -> None:
        self.root = Path(artifacts_dir).resolve()
        self._cache = _Cache()

    # ------------------------------------------------------------- discovery

    def run_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        out = []
        for child in sorted(self.root.iterdir()):
            if not child.is_dir() or not _RUN_ID_RE.match(child.name):
                continue
            if child.name.startswith(".") or child.name in DENY_TOP_LEVEL:
                continue
            if (child / "manifest.json").is_file() or (child / "build_trace.log").is_file():
                out.append(child.name)
        return out

    def run_dir(self, run_id: str) -> Path:
        if not _RUN_ID_RE.match(run_id):
            raise RunNotFound(run_id)
        d = self.root / run_id
        if not d.is_dir():
            raise RunNotFound(run_id)
        return d

    # ------------------------------------------------------------- run level

    def list_runs(self) -> list[dict]:
        runs = [self.run_summary(r) for r in self.run_ids()]
        # sort by recorded activity, newest first; run_id as tiebreak
        runs.sort(key=lambda r: (r["last_activity_at"] or "", r["run_id"]), reverse=True)
        return runs

    def run_summary(self, run_id: str) -> dict:
        d = self.run_dir(run_id)
        manifest = self._cache.get(d / "manifest.json", _load_json) or {}
        report = self._cache.get(d / "report.json", _load_json) or {}
        trace = self.trace_events(run_id)
        started = manifest.get("start") or report.get("start") or next((e.get("at") for e in trace if e.get("event") == "run_start"), None)
        ended = report.get("end")
        last_ev = trace[-1]["at"] if trace else started
        status = report.get("status") or ("completed" if ended else "interrupted")
        if not report and last_ev:
            # No report yet. A build writes a trace line at least every model-call timeout, so recent
            # activity means it is still going; only a silent run was interrupted.
            try:
                idle = (datetime.now(timezone.utc) - datetime.fromisoformat(last_ev)).total_seconds()
                status = "running" if idle < LIVE_SECONDS else "interrupted"
            except (TypeError, ValueError):
                pass
        warnings = []
        if not manifest:
            warnings.append("manifest.json missing or unreadable")
        if not report:
            warnings.append("report.json missing; final status unknown")
        return {
            "run_id": run_id,
            "status": status,
            "started_at": started,
            "ended_at": ended,
            "last_activity_at": last_ev,
            "mode": manifest.get("config", {}).get("mode") or report.get("mode"),
            "builder_model": manifest.get("config", {}).get("builder_model"),
            "brief_hash": manifest.get("brief_hash"),
            "openapi_hash": manifest.get("openapi_hash"),
            "candidate_count": self._candidate_count(run_id),
            "champion_candidate_id": report.get("candidate_id"),
            "final_score": _safe_int(report.get("final_score")),
            "strict_pass_rate": _safe_int(report.get("strict_pass_rate")),
            "evaluation_type": report.get("evaluation_type"),
            "error": report.get("error"),
            "duration_seconds": _safe_int(report.get("seconds")),
            "warnings": warnings,
        }

    def _candidate_count(self, run_id: str) -> int:
        cdir = self.run_dir(run_id) / "candidates"
        return sum(1 for c in cdir.iterdir() if c.is_dir()) if cdir.is_dir() else 0

    # ------------------------------------------------------------- raw docs

    def manifest(self, run_id: str) -> dict:
        return self._cache.get(self.run_dir(run_id) / "manifest.json", _load_json) or {}

    def report(self, run_id: str) -> dict:
        return self._cache.get(self.run_dir(run_id) / "report.json", _load_json) or {}

    # ------------------------------------------------------------- events

    def trace_events(self, run_id: str) -> list[dict]:
        """build_trace.log lines in file order; seq is position, not invented time."""
        return self._cache.get(self.run_dir(run_id) / "build_trace.log", _load_jsonl) or []

    def lineage_events(self, run_id: str) -> tuple[list[dict], bool]:
        """(events, recorded). Falls back to a derived projection from candidates/."""
        path = self.run_dir(run_id) / "lineage.jsonl"
        ev = self._cache.get(path, _load_jsonl)
        if ev is not None:
            return ev, True
        return self._derived_lineage(run_id), False

    def _derived_lineage(self, run_id: str) -> list[dict]:
        cdir = self.run_dir(run_id) / "candidates"
        out = []
        if not cdir.is_dir():
            return out
        for i, cdir_child in enumerate(sorted(cdir.iterdir())):
            if not cdir_child.is_dir():
                continue
            wf = cdir_child / "workflow.json"
            rec = {
                "event": "candidate_created",
                "candidate_id": cdir_child.name,
                "parent_id": None,
                "generation": None,
                "mutation_kind": None,
                "derived": True,
            }
            if wf.is_file():
                data = self._cache.get(wf, _load_json)
                if data:
                    rec["workflow_sha256"] = _sha256(json.dumps(data, sort_keys=True).encode())
            out.append(rec)
        return out

    # ------------------------------------------------------------- lineage tree

    def effective_parents(self, run_id: str) -> dict:
        """candidate -> (parent, derived?). The builder records a compile repair without a parent
        although it rewrites the candidate created just before it; link those so changes are visible."""
        out, previous = {}, None
        for e in self.lineage_events(run_id)[0]:
            if e.get("event") != "candidate_created" or not e.get("candidate_id"):
                continue
            parent, derived = e.get("parent_id"), False
            if not parent and e.get("mutation_kind") == "compile_repair" and previous:
                parent, derived = previous, True
            out[e["candidate_id"]] = (parent, derived)
            previous = e["candidate_id"]
        return out

    def _candidate_stats(self, run_id: str, cid: str, parent: str | None) -> dict:
        base = self.run_dir(run_id)
        out: dict = {}
        wf_path = base / "candidates" / cid / "workflow.json"
        wf = self._cache.get(wf_path, _load_json) if wf_path.is_file() else None
        if isinstance(wf, dict):
            every = [n for g in ("nodes", "global_nodes") for n in (wf.get(g) or {}).values() if isinstance(n, dict)]
            out["steps"] = len(every)
            out["tools"] = sum(len(n.get("tools") or []) + len(n.get("pre_actions") or []) for n in every)
        val_path = base / "candidates" / cid / "validation.json"
        val = self._cache.get(val_path, _load_json) if val_path.is_file() else None
        if isinstance(val, dict):
            out["warning_count"] = len(val.get("warnings") or [])
        ev_root = base / "evaluations"
        if ev_root.is_dir():
            tests = []
            for d in sorted((d for d in ev_root.iterdir() if d.is_dir() and d.name.startswith(cid)), key=lambda d: d.stat().st_mtime):
                out["deployed"] = True
                score = self._cache.get(d / "core_score.json", _load_json) if (d / "core_score.json").is_file() else None
                if isinstance(score, dict):
                    tests.append({"passed": score.get("passed"), "total": score.get("total"), "failed": score.get("failed"),
                                  "unknown": score.get("unknown"), "complete": score.get("complete"),
                                  "hard_fail_count": score.get("hard_fail_count"), "evidence": score.get("evidence_type")})
            if tests:
                out["test"] = tests[-1]
        if parent and isinstance(wf, dict):
            pw_path = base / "candidates" / parent / "workflow.json"
            pw = self._cache.get(pw_path, _load_json) if pw_path.is_file() else None
            if isinstance(pw, dict):
                from . import diff as diffmod
                d = diffmod.diff_workflows(pw, wf)
                added = sorted(set(wf.get("nodes") or {}) - set(pw.get("nodes") or {}))
                removed = sorted(set(pw.get("nodes") or {}) - set(wf.get("nodes") or {}))
                changed = [n for n in d["changed_nodes"] if n not in added and n not in removed]
                out["changes"] = {"added": added, "removed": removed, "changed": changed, "identical": d["identical"],
                                  "total": len(d["changes"])}
        return out

    def tree(self, run_id: str) -> dict:
        ev, recorded = self.lineage_events(run_id)
        nodes: dict[str, dict] = {}
        warnings: list[str] = []
        order: list[str] = []
        validation: dict[str, dict] = {}
        champion = self.report(run_id).get("candidate_id")

        for e in ev:
            kind = e.get("event")
            cid = e.get("candidate_id")
            if kind == "candidate_created" and cid:
                order.append(cid)
                nodes[cid] = {
                    "candidate_id": cid,
                    "parent_id": e.get("parent_id"),
                    "generation": e.get("generation"),
                    "mutation_kind": e.get("mutation_kind") or "unknown",
                    "workflow_sha256": e.get("workflow_sha256"),
                    "created_at": e.get("created_at") or e.get("at"),
                    "duplicate_of": e.get("duplicate_of"),
                    "derived": bool(e.get("derived")),
                    "valid": None,
                    "validation_evidence": None,
                    "errors": [],
                    "score": None,
                    "champion": cid == champion if champion else False,
                }
            elif kind in ("validation", "code_probe_rejected", "code_probe_completed") and cid:
                v = validation.setdefault(cid, {})
                if kind == "validation":
                    v["valid"] = bool(e.get("valid"))
                    v["evidence_type"] = e.get("evidence_type")
                    v["errors"] = e.get("errors") or []
                else:
                    v["probe_errors"] = e.get("errors") or []
                    v["probe_evidence"] = e.get("evidence_type")

        parents = self.effective_parents(run_id)
        repairs = 0
        for cid, n in nodes.items():
            v = validation.get(cid)
            if v:
                n["valid"] = v.get("valid")
                n["validation_evidence"] = v.get("evidence_type")
                n["errors"] = (v.get("errors") or []) + (v.get("probe_errors") or [])
            parent, derived = parents.get(cid, (n["parent_id"], False))
            if derived:
                n["parent_id"], n["parent_derived"] = parent, True
            kind = n["mutation_kind"]
            if kind in ("compile_repair", "compile_fix"):
                repairs += 1
                n["label"] = f"Compiler fix {repairs}" if kind == "compile_fix" else f"Repair {repairs}"
            elif kind in ("baseline", "design"):
                n["label"], repairs = "First design", 0
            elif kind in FIX_KINDS:
                n["label"] = FIX_KINDS[kind]
            else:
                n["label"] = "Mutation: " + str(kind).replace("_", " ")
            n.update(self._candidate_stats(run_id, cid, n["parent_id"]))

        # graph integrity
        for cid, n in nodes.items():
            p = n["parent_id"]
            if p is not None and p not in nodes:
                warnings.append(f"orphan candidate {cid}: parent {p} not found")
                n["orphan"] = True
        roots = [cid for cid, n in nodes.items() if n["parent_id"] not in nodes]
        # cycle guard: walk parents, cap at len(nodes)
        for start in nodes:
            seen = set()
            cur = start
            while cur is not None and cur in nodes:
                if cur in seen:
                    warnings.append(f"cycle detected at {start}")
                    nodes[start]["cycle"] = True
                    break
                seen.add(cur)
                cur = nodes[cur]["parent_id"]

        children: dict[str | None, list[str]] = {}
        for cid in order:
            n = nodes[cid]
            p = n["parent_id"] if n["parent_id"] in nodes else None
            children.setdefault(p, []).append(cid)

        report = self.report(run_id)
        return {
            "run_id": run_id,
            "recorded": recorded,
            "nodes": [nodes[c] for c in order],
            "children": {k or "": v for k, v in children.items()},
            "roots": roots,
            "champion_candidate_id": champion,
            "warnings": warnings,
            "final_score": _safe_int(report.get("final_score")),
            "evaluation_type": report.get("evaluation_type"),
        }

    # ------------------------------------------------------------- candidate

    def candidate_ids(self, run_id: str) -> list[str]:
        cdir = self.run_dir(run_id) / "candidates"
        if not cdir.is_dir():
            return []
        return sorted(c.name for c in cdir.iterdir() if c.is_dir())

    def candidate(self, run_id: str, candidate_id: str) -> dict:
        d = self.run_dir(run_id) / "candidates" / candidate_id
        if not d.is_dir():
            raise ArtifactMissing(f"candidate {candidate_id}")
        _, recorded = self.lineage_events(run_id)
        created = None
        parent_id = None
        for e in self.lineage_events(run_id)[0]:
            if e.get("candidate_id") == candidate_id and e.get("event") == "candidate_created":
                created, parent_id = e.get("created_at") or e.get("at"), e.get("parent_id")
        parent_derived = False
        if not parent_id:
            parent_id, parent_derived = self.effective_parents(run_id).get(candidate_id, (None, False))
        report = self.report(run_id)
        out = {
            "run_id": run_id,
            "candidate_id": candidate_id,
            "recorded_lineage": recorded,
            "created_at": created,
            "parent_candidate_id": parent_id,
            "parent_derived": parent_derived,
            "champion": report.get("candidate_id") == candidate_id,
            "score": _safe_int(report.get("final_score")) if report.get("candidate_id") == candidate_id else None,
            "files": {},
        }
        for name in ("workflow", "validation", "proposal", "code_probes", "mutation"):
            p = d / f"{name}.json"
            if p.is_file():
                data = self._cache.get(p, _load_json)
                if data is not None:
                    out["files"][name] = {
                        "ref": f"candidates/{candidate_id}/{name}.json",
                        "sha256": _sha256(json.dumps(data, sort_keys=True).encode()),
                        "data": data,
                    }
        return out

    # ------------------------------------------------------------- spans (derived)

    def spans(self, run_id: str) -> dict:
        """Derive a span list from build_trace.log + model_calls/. All derived.

        ADKModelCall_end carries no call_id (producer limitation), so ends are
        paired to open starts in order and flagged derived.
        """
        events = self.trace_events(run_id)
        mdir = self.run_dir(run_id) / "model_calls"
        usage: dict[str, dict] = {}
        open_starts: list[dict] = []
        spans: list[dict] = []
        groups: list[dict] = []  # open deploy / practice-test spans; platform calls fold into them
        eval_root = self.run_dir(run_id) / "evaluations"
        eval_dirs = sorted((d for d in eval_root.iterdir() if d.is_dir() and not d.name.startswith("held_out")),
                           key=lambda d: d.stat().st_mtime) if eval_root.is_dir() else []
        tests_seen = 0

        def child(e, label):
            groups[-1]["children"].append({"at": e.get("at"), "label": label})

        def close(sp, end_ev):
            sp["end_at"] = end_ev.get("at")
            sp["status"] = "failed" if end_ev.get("event", "").endswith("_error") else "succeeded"
            if end_ev.get("error") or end_ev.get("message"):
                sp["error"] = end_ev.get("error") or end_ev.get("message")

        for seq, e in enumerate(events):
            kind = e.get("event")
            at = e.get("at")
            if kind == "run_start":
                spans.append({"span_id": f"seq_{seq}", "kind": "run", "name": "Builder run start",
                              "start_at": at, "status": "succeeded", "seq": seq, "detail": e})
            elif kind == "run_end":
                spans.append({"span_id": f"seq_{seq}", "kind": "run", "name": "Builder run end",
                              "start_at": at, "status": e.get("status") or "succeeded",
                              "seq": seq, "detail": e})
            elif kind in ("build_failed", "search_stopped"):
                spans.append({"span_id": f"seq_{seq}", "kind": "error", "name": kind,
                              "start_at": at, "status": "failed",
                              "error": e.get("message") or e.get("error"), "seq": seq, "detail": e})
            elif kind == "ADKModelCall_start":
                sp = {"span_id": e.get("call_id") or f"seq_{seq}", "kind": "llm",
                      "name": e.get("role") or "ModelCall", "start_at": at, "status": "running",
                      "model": e.get("model"), "purpose": e.get("purpose"),
                      "prompt_version": e.get("prompt_version"),
                      "prompt_hash": e.get("prompt_hash"), "call_id": e.get("call_id"),
                      "seq": seq, "derived": True, "detail": e}
                open_starts.append(sp)
                spans.append(sp)
            elif kind == "model_usage" and e.get("call_id"):
                usage[e["call_id"]] = e
                for sp in spans:
                    if sp.get("call_id") == e["call_id"] and sp["kind"] == "llm":
                        toks = e.get("tokens") or []
                        if toks and isinstance(toks, list):
                            sp["tokens"] = toks[-1]
                        sp["estimated_cost"] = e.get("estimated_cost")
            elif kind in ("ADKModelCall_end", "ADKModelCall_error"):
                if open_starts:
                    close(open_starts.pop(0), e)  # ordered pairing, mark derived
            elif kind in ("requirements_resumed", "proposal_resumed"):
                spans.append({"span_id": f"seq_{seq}", "kind": "resume", "name": kind,
                              "start_at": at, "status": "succeeded",
                              "source": e.get("source"), "seq": seq, "detail": e})
            elif kind == "FreyaDeploy_start":
                sp = {"span_id": f"seq_{seq}", "kind": "deploy", "name": "Deploy to Freya", "start_at": at,
                      "status": "running", "workflow_hash": e.get("workflow_hash"), "slot": e.get("slot"),
                      "children": [], "seq": seq, "derived": True, "detail": e}
                groups.append(sp)
                spans.append(sp)
            elif kind == "OfficialBenchmark_start":
                folder = e.get("evaluation_folder")
                if not folder and eval_dirs:  # older traces: pair tests with evaluation folders in order
                    if not e.get("repetition"):
                        tests_seen += 1
                    folder = eval_dirs[min(tests_seen, len(eval_dirs)) - 1].name
                sp = {"span_id": f"seq_{seq}", "kind": "benchmark", "name": "Practice test", "start_at": at,
                      "status": "running", "repetition": e.get("repetition") or 0, "evaluation_folder": folder,
                      "children": [], "seq": seq, "derived": True, "detail": e}
                groups.append(sp)
                spans.append(sp)
            elif kind in ("FreyaDeploy_end", "FreyaDeploy_error", "OfficialBenchmark_end", "OfficialBenchmark_error"):
                want = "deploy" if kind.startswith("FreyaDeploy") else "benchmark"
                for sp in reversed(groups):
                    if sp["kind"] == want:
                        if kind.endswith("_error"):
                            sp["failed"], sp["error"] = True, e.get("message") or e.get("error")
                        else:
                            sp["end_at"] = at
                            sp["status"] = "failed" if sp.get("failed") else "succeeded"
                            groups.remove(sp)
                        break
            elif kind == "candidate_published" and groups:
                g = groups[-1]
                g.update({k: e.get(k) for k in ("workflow_id", "agent_id", "version", "steps", "tools")})
                g["name"] = f"Deploy to Freya · v{e.get('version')}" + (f" · {e.get('steps')} steps, {e.get('tools')} tools" if e.get("steps") is not None else "")
            elif kind == "official_result":
                target = groups[-1] if groups else next((s for s in reversed(spans) if s["kind"] == "benchmark"), None)
                if target is not None:
                    target["passed"], target["total"] = e.get("passed"), e.get("total")
                    target["name"] = f"Practice test · {e.get('passed')}/{e.get('total')} passed"
            elif kind in ("freya_api", "workflow_export"):
                label = f"{e.get('method')} {e.get('path')}" if kind == "freya_api" else "export workflow"
                if groups:
                    child(e, label)
                elif kind == "workflow_export" and spans and spans[-1]["kind"] == "freya":
                    spans[-1].update({"name": "Export workflow from Freya", "path": e.get("path")})
                else:
                    name = "Freya dry-run (schema check)" if label == "POST /api/v2/workflow" else "freya " + label
                    spans.append({"span_id": f"seq_{seq}", "kind": "freya", "name": name,
                                  "start_at": at, "status": "succeeded", "seq": seq, "detail": e})
            elif kind == "static_validation":
                errors, warns = e.get("errors") or [], e.get("warnings") or []
                spans.append({"span_id": f"seq_{seq}", "kind": "validation", "start_at": at, "seq": seq, "detail": e,
                              "name": f"Validation · {'passed' if e.get('valid') else str(len(errors)) + ' error' + ('' if len(errors) == 1 else 's')}"
                                      + (f", {len(warns)} warnings" if warns else ""),
                              "status": "succeeded" if e.get("valid") else "failed", "candidate_id": e.get("candidate_id"),
                              "errors": errors, "warnings": warns})
            elif kind in ("best_effort_root", "search_skipped", "evaluation_skipped", "benchmark_incomplete", "held_out_skipped",
                          "champion_fallback_to_root", "repair_unavailable", "diagnosis_unavailable", "proposal_normalized",
                          "cached_export_fallback"):
                spans.append({"span_id": f"seq_{seq}", "kind": "note", "name": kind.replace("_", " "), "start_at": at,
                              "status": "succeeded" if kind == "proposal_normalized" else "warning",
                              "error": e.get("message") or e.get("reason"), "seq": seq, "detail": e})
            elif kind == "structured_output_retry":
                spans.append({"span_id": f"seq_{seq}", "kind": "retry", "name": "structured_output_retry",
                              "start_at": at, "status": "warning", "role": e.get("role"),
                              "seq": seq, "detail": e})

        for sp in spans:
            if sp["kind"] in ("deploy", "benchmark") and sp["status"] == "running":
                sp["status"] = "failed" if sp.get("failed") else "running"
            if sp["kind"] == "benchmark" and sp.get("evaluation_folder"):
                folder = eval_root / sp["evaluation_folder"]
                raw = self._cache.get(folder / "raw_runner.json", _load_json) if (folder / "raw_runner.json").is_file() else None
                rows = (raw or {}).get("all_rows") or []
                if sp["repetition"] < len(rows):
                    sp["results"] = rows[sp["repetition"]]
                    sims = (raw or {}).get("simulations") or []
                    if sp["repetition"] < len(sims):
                        sp["simulation"] = sims[sp["repetition"]]
                    if sp.get("passed") is None:
                        sp["passed"], sp["total"] = sum(1 for r in sp["results"] if r.get("pass")), len(sp["results"])
                        sp["name"] = f"Practice test · {sp['passed']}/{sp['total']} passed"
                if (folder / f"calls_{sp['repetition']}.json").is_file():
                    sp["transcripts"] = f"evaluations/{sp['evaluation_folder']}/calls_{sp['repetition']}.json"
                live_path = folder / f"live_{sp['repetition']}.json"
                if not sp.get("results") and live_path.is_file():
                    # Provisional per-customer progress published by the builder while the simulation runs.
                    live = self._cache.get(live_path, _load_json) or {}
                    rows = live.get("rows") or []
                    done = [r for r in rows if r.get("state") == "finished"]
                    sp["live"] = {"updated_at": live.get("updated_at"), "rows": rows}
                    sp["name"] = f"Practice test · {len(done)}/{len(rows)} finished, {sum(1 for r in done if r.get('pass'))} passing"
                    if (folder / f"live_calls_{sp['repetition']}.json").is_file():
                        sp["transcripts"] = f"evaluations/{sp['evaluation_folder']}/live_calls_{sp['repetition']}.json"
                        sp["transcripts_live"] = True
                if (folder / "diagnostics.json").is_file():
                    sp["diagnostics"] = f"evaluations/{sp['evaluation_folder']}/diagnostics.json"
            if sp["kind"] == "llm":
                u = usage.get(sp.get("call_id") or "")
                if u and not sp.get("tokens"):
                    toks = u.get("tokens") or []
                    if toks:
                        sp["tokens"] = toks[-1]
                cid = sp.get("call_id")
                if cid and mdir.is_dir():
                    for suffix in ("prompt", "raw_response", "response"):
                        p = mdir / f"{cid}.{suffix}.json"
                        if p.is_file():
                            sp.setdefault("artifacts", {})[suffix] = f"model_calls/{p.name}"
                if sp["status"] == "running":
                    sp["status"] = "running" if self.run_summary(run_id)["status"] == "running" else "interrupted"

        # durations where both ends recorded
        from datetime import datetime

        def ts(s):
            if not s:
                return None
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None

        for sp in spans:
            a, b = ts(sp.get("start_at")), ts(sp.get("end_at"))
            if a and b:
                sp["duration_ms"] = int((b - a).total_seconds() * 1000)
        spans.sort(key=lambda s: (s.get("start_at") or "", s["seq"]))
        report = self.report(run_id)
        return {
            "run_id": run_id,
            "recorded_events": len(events),
            "spans": spans,
            "warnings": ["ADKModelCall_end paired by order (no call_id in producer)"]
            if events else [],
            "status": report.get("status"),
        }

    def model_call(self, run_id: str, call_id: str) -> dict:
        """Prompt/response payload for one model call, joined from model_calls/."""
        if not re.match(r"^[A-Za-z0-9_-]+$", call_id):
            raise ArtifactForbidden("bad call id")
        d = self.run_dir(run_id) / "model_calls"
        out: dict = {"call_id": call_id}
        for suffix, key in (("prompt", "prompt"), ("response", "response"), ("raw_response", "raw_response")):
            p = d / f"{call_id}.{suffix}.json"
            if p.is_file():
                out[key] = self._cache.get(p, _load_json)
        if not any(k in out for k in ("prompt", "response")):
            raise ArtifactMissing(call_id)
        return out

    # ------------------------------------------------------------- artifact access

    def artifact(self, run_id: str, relpath: str) -> tuple[bytes, str]:
        """Serve an allowlisted file inside the run dir. Never escapes the root."""
        if relpath.startswith("/") or "\\" in relpath:
            raise ArtifactForbidden(relpath)
        base = self.run_dir(run_id).resolve()
        p = (base / relpath).resolve()
        if base not in p.parents:
            raise ArtifactForbidden(relpath)
        rel = p.relative_to(base)
        if any(part.startswith(".") for part in rel.parts):
            raise ArtifactForbidden(relpath)
        if rel.parts and rel.parts[0] in DENY_TOP_LEVEL:
            raise ArtifactForbidden(relpath)
        if p.suffix not in (".json", ".jsonl", ".log", ".txt", ".md", ".lock"):
            raise ArtifactForbidden(relpath)
        if not p.is_file():
            raise ArtifactMissing(relpath)
        data = p.read_bytes()
        if len(data) > MAX_ARTIFACT_BYTES:
            data = data[:MAX_ARTIFACT_BYTES]
        return data, p.suffix.lstrip(".")
