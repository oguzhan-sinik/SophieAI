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
import threading
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
    """Hold the lock while the block runs. Yields False, without the lock, when the budget ran out
    waiting for it: the caller still owns its export reserve and must be able to use it."""
    path = writable(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        held = False
        while not held and deadline.remaining() > 0:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
            except BlockingIOError:
                time.sleep(min(0.2, deadline.remaining()))
        try:
            yield held
        finally:
            if held:
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


def compact_call(call):
    """Readable record of one simulated call: speech, steps, tool calls and routes; no variable tables."""
    turns = []
    for message in call.get("messages", []):
        role, text, at = message.get("role"), message.get("message"), message.get("secondsFromStart")
        if role in ("assistant", "user"):
            turns.append({"t": at, "role": role, "node": message.get("nodeId"), "text": text})
            continue
        try:
            event = json.loads(text)
        except (TypeError, ValueError):
            continue
        kind = event.get("event")
        if kind == "node_enter":
            turns.append({"t": at, "role": "step", "node": event.get("node"), "from": event.get("from_node"), "text": event.get("reason", "")})
        elif kind == "function_call_start":
            turns.append({"t": at, "role": "tool_call", "node": message.get("nodeId"), "tool": event.get("function"),
                          "url": (event.get("args") or {}).get("url"), "body": (event.get("args") or {}).get("body")})
        elif kind == "function_call_complete":
            result = event.get("result") or {}
            turns.append({"t": at, "role": "tool_result", "node": message.get("nodeId"), "tool": event.get("function"),
                          "status_code": result.get("status_code"), "data": result.get("data")})
        elif kind == "variable_extracted":
            turns.append({"t": at, "role": "extracted", "node": event.get("source_node"), "name": event.get("name"), "value": event.get("value")})
    return {"call_id": call.get("id"), "ended": call.get("endedReason"), "duration": call.get("duration"),
            "judge": (call.get("successCriteriaResult") or {}).get("reason"), "turns": turns}


class FreyaAdapter:
    def __init__(self, cfg, deadline, trace):
        self.cfg, self.deadline, self.trace = cfg, deadline, trace
        self.runtime = writable(cfg.runtime)
        self.runtime.mkdir(exist_ok=True)
        if not os.getenv("FREYA_API_KEY"):
            raise ValueError("FREYA_API_KEY is required for real deployment")
        self.client = load_module("freya", KIT / "freya.py")
        self.original_api = self.client.api
        self.client.api = self.api
        self.exporting = False
        self.deployment = None
        self.current_simulation = None

    def api(self, method, path, body=None, **params):
        # A platform outage is not a verdict on the workflow. 503 means the request was not
        # processed, so it is safe to repeat; 502/504 are repeated only for reads.
        for attempt in range(6):
            try:
                with time_limit(self.deadline.timeout(self.cfg.request_timeout, self.exporting)):
                    result = self.original_api(method, path, body, **params)
                break
            except RuntimeError as exc:
                text = str(exc)
                transient = "-> 503:" in text or (method == "GET" and ("-> 502:" in text or "-> 504:" in text))
                if not transient or attempt == 5 or self.deadline.remaining(self.exporting) < 30:
                    raise
                self.trace.event("freya_retry", method=method, path=path, attempt=attempt + 1, message=text[:160])
                time.sleep(min(5 * (attempt + 1), 20))
        self.trace.event("freya_api", method=method, path=path)
        if method == "POST" and path == "/api/v2/simulations":
            self.current_simulation = (result.get("simulation") or result)["id"]
        return result

    @contextmanager
    def workspace(self):
        """One build at a time on this machine: builds share the slots file and Freya's single simulation.

        Nothing here waits for a simulation an earlier build left running. The kit client already
        waits at the moment it starts one, and a build that starts none must not wait at all."""
        with file_lock(AGENT / ".runtime" / "workspace.lock", self.deadline) as held:
            if not held:
                self.trace.event("workspace_lock_unavailable", reason="another build held it until this build's budget ran out")
                raise TimeoutError("Workspace lock unavailable; no deployment or simulation permitted")
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

    def watch(self, stop, folder, repetition, cases, persona_ids, customers, scorer, ledger_http):
        """Publish per-customer progress while the simulation runs. Read-only and best effort:
        it never touches the frozen score, and any failure here only leaves the live view stale."""
        by_persona = {persona: case_id for case_id, persona in persona_ids.items()}
        by_id = {case["id"]: case for case in cases}
        transcripts, finished = {}, set()
        while not stop.wait(12):
            try:
                sim_id = self.current_simulation
                if not sim_id:
                    continue
                listing = self.original_api("GET", f"/api/v2/simulations/{sim_id}/iterations")
                listing = listing.get("iterations") or listing.get("items") or listing
                if not listing:
                    continue
                runs = self.original_api("GET", f"/api/v2/simulations/{sim_id}/iterations/{listing[0]['id']}", limit=100, offset=0).get("runs", [])
                rows = []
                for run in runs:
                    case_id = by_persona.get(run.get("personaId"))
                    if not case_id:
                        continue
                    outcome = run.get("outcome")
                    # "analyzing": the call is over and the judge has not ruled yet.
                    state = outcome if outcome in ("queued", "running", "analyzing") else "finished"
                    row = {"id": case_id, "family": by_id[case_id].get("family"), "level": by_id[case_id].get("level"), "state": state,
                           "judge": outcome if state == "finished" else None, "judge_reason": run.get("reason") if state == "finished" else None,
                           "turns": run.get("turnCount"), "call_id": run.get("callId")}
                    if run.get("callId") and case_id not in finished:
                        transcripts[case_id] = compact_call(self.original_api("GET", f"/api/v2/call/{run['callId']}")["call"])
                    if state != "queued" and customers.get(case_id):
                        ledger = ledger_http("/v1/practice/ledger/" + customers[case_id])
                        row["tools"] = [call["tool"] for call in ledger.get("calls", [])]
                        if state == "finished":
                            bank = scorer.score_ledger(by_id[case_id], ledger)
                            row["bank_failed"] = bank["failed"]
                            row["pass"] = bank["pass"] and outcome == "pass"
                            finished.add(case_id)
                    rows.append(row)
                write_json(folder / f"live_{repetition}.json", self.trace.redact({"simulation_id": sim_id, "updated_at": time.strftime("%H:%M:%S", time.gmtime()), "rows": rows}))
                write_json(folder / f"live_calls_{repetition}.json", self.trace.redact(transcripts))
            except Exception:
                continue

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
        customers = {}
        def captured_http(path, body=None):
            result = original_http(path, body)
            if "/ledger/" in path:
                ledgers[path.rsplit("/", 1)[-1]] = result
            elif path.endswith("/practice/sessions") and isinstance(body, dict) and isinstance(result, dict):
                customers[body.get("case")] = (result.get("variables") or {}).get("customer_id")
            return result
        runner.http = captured_http
        calls = {}
        original_call = self.client.get_call
        def captured_call(call_id):
            result = original_call(call_id)
            calls[call_id] = result
            return result
        self.client.get_call = captured_call
        try:
            for repetition in range(suite.repetitions):
                self.deadline.require(20)
                output = io.StringIO()
                self.current_simulation = None
                stop = threading.Event()
                watcher = threading.Thread(target=self.watch, args=(stop, folder, repetition, cases, ids, customers, scorer, original_http), daemon=True)
                watcher.start()
                try:
                    with self.trace.span("OfficialBenchmark", repetition=repetition, suite_key=suite.key, evaluation_folder=folder.name), time_limit(self.deadline.remaining()), redirect_stdout(output):
                        rows, sim_id, iteration_id, status, seconds, median = runner.run_once(self.deployment["agent_id"], cases, ids)
                finally:
                    stop.set()
                    watcher.join(timeout=20)
                for row in rows:
                    ledger = ledgers.get(row.get("customer_id"), {})
                    row["verified_hard_failure"] = any(c.get("tool") in {"get_account", "create_promise"} and c.get("result", {}).get("error") == "identity not verified" for c in ledger.get("calls", []))
                raw["all_rows"].append(rows)
                raw["simulations"].append({"id": sim_id, "iteration_id": iteration_id, "status": status, "seconds": seconds, "median_slowest_turn": median})
                # Only supplied synthetic practice data enters local evidence; secrets redacted.
                write_json(folder / "raw_runner.json", self.trace.redact(raw))
                write_json(folder / f"iteration_{repetition}.json", self.trace.redact(iterations[-1]))
                write_json(folder / f"ledgers_{repetition}.json", self.trace.redact(list(ledgers.values())))
                write_json(folder / f"calls_{repetition}.json", self.trace.redact({row["id"]: compact_call(calls[row["call_id"]]) for row in rows if row.get("call_id") in calls}))
                self.trace.event("official_result", suite_key=suite.key, repetition=repetition, passed=sum(r["pass"] for r in rows), total=len(rows), status=status)
            return raw
        finally:
            self.client.get_iteration = original_iteration
            self.client.get_call = original_call
            runner.http = original_http
            write_json(folder / "raw_runner.json", self.trace.redact(raw))


def public_suite(documents, openapi_hash, brief=None, only=None, style="", repetitions=1):
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
    suite = Suite(tuple(c["id"] for c in cases), digest({"cases": cases, "runner": (KIT / "tools/run_cases.py").read_text(), "scorer": (KIT / "tools/score.py").read_text(), "policy": [d["text"] for d in documents], "openapi": openapi_hash}), "official_public", repetitions, style)
    return suite, cases
