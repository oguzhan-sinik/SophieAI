"""Use the inspected kit client/runner, with contained state and bounded calls."""
from contextlib import contextmanager, redirect_stdout
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import sys
import time

from .artifacts import digest, write_json
from .config import AGENT, KIT, writable
from .scoring import Suite


@contextmanager
def time_limit(seconds):
    if seconds <= 0:
        raise TimeoutError("No execution budget remains")
    def expired(signum, frame):
        raise TimeoutError("Freya operation exceeded remaining budget")
    previous = signal.signal(signal.SIGALRM, expired)
    old_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    start = time.monotonic()
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if old_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, old_timer[0] - (time.monotonic() - start)), old_timer[1])


@contextmanager
def file_lock(path, deadline):
    path = writable(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        while True:
            deadline.require()
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(min(0.2, deadline.remaining()))
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def load_module(name, path):
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = old


def contains_definition(expected, actual, location="workflow"):
    """Server may add defaults; it may not drop/change any supplied semantic field."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise ValueError(f"Round-trip type mismatch at {location}")
        for key, value in expected.items():
            if key not in actual:
                # Freya may omit empty optional arrays/maps; no behavior is lost.
                if value in ([], {}) and key not in {"nodes"}:
                    continue
                raise ValueError(f"Round-trip lost field {location}.{key}")
            contains_definition(value, actual[key], location + "." + key)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise ValueError(f"Round-trip list mismatch at {location}")
        for i, value in enumerate(expected):
            contains_definition(value, actual[i], f"{location}[{i}]")
    elif expected != actual:
        raise ValueError(f"Round-trip changed field {location}")


class FreyaAdapter:
    def __init__(self, cfg, deadline, trace):
        self.cfg, self.deadline, self.trace = cfg, deadline, trace
        self.runtime = writable(AGENT / ".runtime")
        self.runtime.mkdir(exist_ok=True)
        if not os.getenv("FREYA_API_KEY"):
            raise ValueError("FREYA_API_KEY is required for real deployment")
        self.client = load_module("freya", KIT / "freya.py")
        self.original_api = self.client.api
        self.client.api = self.api
        self.exporting = False
        self.lease = self.runtime / "simulation.json"
        self.deployment = None

    def api(self, method, path, body=None, **params):
        with time_limit(self.deadline.timeout(self.cfg.request_timeout, self.exporting)):
            result = self.original_api(method, path, body, **params)
        self.trace.event("freya_api", method=method, path=path)
        if method == "POST" and path == "/api/v2/simulations":
            sim_id = (result.get("simulation") or result)["id"]
            write_json(self.lease, {"simulation_id": sim_id})
        return result

    @contextmanager
    def workspace(self):
        # All builds use this common lock, including distinct feedback arms.
        with file_lock(self.runtime / "workspace.lock", self.deadline):
            if self.lease.exists():
                sim_id = json.loads(self.lease.read_text())["simulation_id"]
                while True:
                    response = self.api("GET", f"/api/v2/simulations/{sim_id}")
                    if (response.get("simulation") or response).get("status") in {"completed", "failed", "paused"}:
                        self.lease.unlink()
                        break
                    self.deadline.require(10)
                    time.sleep(10)
            yield self

    def validate_remote(self, workflow):
        self.trace.redact.assert_no_secrets(workflow)
        return self.client.validate_workflow('ticket01-validation', workflow)

    def deploy(self, slot, workflow):
        self.trace.redact.assert_no_secrets(workflow)
        with self.trace.span("FreyaDeploy", workflow_hash=digest(workflow), slot=slot):
            self.client.validate_workflow(slot, workflow)
            deployment = self.client.save_workflow(slot, workflow, state_file=str(self.runtime / "freya-agents.json"))
            # Kit create does not enforce publish/model invariants; update does.
            if "version" not in deployment:
                deployment["version"] = self.client.update_workflow(deployment["workflow_id"], workflow)
            versions = self.api("GET", f"/api/v2/versions/workflow/{deployment['workflow_id']}", workspaceId=self.client.workspace_id())["versions"]
            latest = max(versions, key=lambda item: item["versionNumber"])
            if not latest.get("isPublished") or latest["versionNumber"] != deployment["version"]:
                raise ValueError("Candidate is not the latest published version")
            stored = self.api("GET", f"/api/v2/workflow/{deployment['workflow_id']}", workspaceId=self.client.workspace_id())["workflow"]["workflow"]
            contains_definition(workflow, stored)
            every = list(workflow.get("nodes", {}).values()) + list(workflow.get("global_nodes", {}).values())
            self.deployment = {**deployment, "workflow_hash": digest(workflow), "steps": len(every),
                               "tools": sum(len(n.get("tools", [])) + len(n.get("pre_actions", [])) for n in every)}
            self.trace.event("candidate_published", **self.deployment)
            return self.deployment

    def export(self, workflow, path):
        if not self.deployment or self.deployment["workflow_hash"] != digest(workflow):
            raise ValueError("Requested export is not the active candidate")
        path = writable(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".pending.json")
        self.client.export_workflow(self.deployment["workflow_id"], str(temp))
        result = json.loads(temp.read_text())
        contains_definition(workflow, result["workflow"])
        # Credentials are never compiled into the workflow. Reject unexpected server secrets.
        self.trace.redact.assert_no_secrets(result)
        temp.replace(path)
        self.trace.event("workflow_export", path=str(path), workflow_hash=digest(workflow))
        return str(path)

    def chat_smoke(self, workflow_id, variables):
        call_id = None
        try:
            response = self.api("POST", "/api/v2/chat/message", {"workflowId": workflow_id, "message": "Hello?", "customerVariables": variables})
            call_id = response.get("callId")
            if not response.get("response"):
                raise ValueError("Chat smoke returned no speech")
            return {"status": "started", "call_id": call_id, "response": response["response"], "evidence_type": "smoke_only"}
        finally:
            if call_id:
                self.api("POST", "/api/v2/chat/end", {"callId": call_id})

    def evaluate(self, cases, suite, folder):
        if suite.evidence_type != "official_public":
            raise ValueError("Freya runner only evaluates official public suites")
        if not os.getenv("FREYA_BANK_TEAM_KEY") or len(os.environ["FREYA_BANK_TEAM_KEY"]) < 16:
            raise ValueError("FREYA_BANK_TEAM_KEY must contain at least 16 characters")
        if not self.deployment:
            raise ValueError("No candidate deployed")
        folder = writable(folder)
        folder.mkdir(parents=True, exist_ok=True)
        scorer = load_module("score", KIT / "tools/score.py")
        runner = load_module("kit_public_runner", KIT / "tools/run_cases.py")
        ids = {}
        persona_specs = [runner.persona_for(case, {"identity": case["identity"]}, suite.style or None) for case in cases]
        made = self.client.create_personas(persona_specs)["personas"]
        if len(made) != len(cases):
            raise ValueError("Persona response length mismatch")
        ids.update({case["id"]: persona["id"] for case, persona in zip(cases, made)})
        raw = {"all_rows": [], "simulations": [], "version": self.deployment["version"], "suite": suite.key}
        expected_version = self.deployment["version"]
        original_iteration = self.client.get_iteration
        iterations = []
        def checked_iteration(sim_id, iteration_id):
            result = original_iteration(sim_id, iteration_id)
            runs = result.get("runs", [])
            if result.get("runsTotal", len(runs)) != len(runs):
                raise ValueError("Incomplete iteration pagination")
            if any(run.get("agentVersionNumber") != expected_version for run in runs):
                raise ValueError("Missing or stale agentVersionNumber in simulation runs")
            iterations.append(result)
            return result
        self.client.get_iteration = checked_iteration
        ledgers = {}
        original_http = runner.http
        def captured_http(path, body=None):
            result = original_http(path, body)
            if "/ledger/" in path:
                ledgers[path.rsplit("/", 1)[-1]] = result
            return result
        runner.http = captured_http
        try:
            for repetition in range(suite.repetitions):
                self.deadline.require(20)
                output = io.StringIO()
                with self.trace.span("OfficialBenchmark", repetition=repetition, suite_key=suite.key), time_limit(self.deadline.remaining()), redirect_stdout(output):
                    rows, sim_id, iteration_id, status, seconds, median = runner.run_once(self.deployment["agent_id"], cases, ids)
                for row in rows:
                    ledger = ledgers.get(row.get("customer_id"), {})
                    row["verified_hard_failure"] = any(c.get("tool") in {"get_account", "create_promise"} and c.get("result", {}).get("error") == "identity not verified" for c in ledger.get("calls", []))
                raw["all_rows"].append(rows)
                raw["simulations"].append({"id": sim_id, "iteration_id": iteration_id, "status": status, "seconds": seconds, "median_slowest_turn": median})
                if self.lease.exists():
                    self.lease.unlink()
                # Only supplied synthetic practice data enters local evidence; secrets redacted.
                write_json(folder / "raw_runner.json", self.trace.redact(raw))
                write_json(folder / f"iteration_{repetition}.json", self.trace.redact(iterations[-1]))
                write_json(folder / f"ledgers_{repetition}.json", self.trace.redact(list(ledgers.values())))
                self.trace.event("official_result", suite_key=suite.key, repetition=repetition, passed=sum(r["pass"] for r in rows), total=len(rows), status=status)
            return raw
        finally:
            self.client.get_iteration = original_iteration
            runner.http = original_http
            write_json(folder / "raw_runner.json", self.trace.redact(raw))


def public_suite(documents, openapi_hash, brief=None, only=None, style="", repetitions=1, seed=42):
    """Never silently run practice expectations against an unfamiliar policy/API."""
    cases_path = KIT / "public-test-set.json"
    if not cases_path.exists():
        return None, []
    known = {str((KIT / "briefs" / f"brief-{tag.lower()}.md").resolve()): tag for tag in ("A", "B")}
    tags = []
    for document in documents:
        tag = known.get(document["path"])
        if not tag or Path(document["path"]).read_text() != document["text"]:
            return None, []
        tags.append(tag)
    from .contracts import compile_openapi
    if openapi_hash != compile_openapi(KIT / "tools/openapi.json")["sha256"]:
        return None, []
    selected = brief or tags[-1]
    if selected != tags[-1] or (selected == "B" and tags != ["A", "B"]):
        raise ValueError("Public selector must match the supplied effective A or A+B brief")
    cases = [c for c in json.loads(cases_path.read_text()) if c["brief"] == selected and (not only or c["id"] in only)]
    if only and set(only) != {c["id"] for c in cases}:
        raise ValueError("Unknown or mismatched public case selector")
    if not cases:
        raise ValueError("Public suite is empty")
    suite = Suite(tuple(c["id"] for c in cases), digest({"cases": cases, "runner": (KIT / "tools/run_cases.py").read_text(), "scorer": (KIT / "tools/score.py").read_text(), "policy": [d["text"] for d in documents], "openapi": openapi_hash}), "official_public", repetitions, style, seed)
    return suite, cases
