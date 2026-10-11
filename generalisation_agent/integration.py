"""Optional fixed-suite provider. Official ranking and local veto evidence stay separate."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import time

from agent.builder.artifacts import digest, write_json
from agent.builder.build import Builder, call_records, inputs
from agent.builder.config import Config, missing_credentials
from agent.builder.scoring import verdicts

from .calibration import admitted, calibrate
from .config import ROOT, confined
from .evaluation import evaluate_workflow, read_workflow, source_fingerprint, suite_for
from .generation import customers_for
from .packs import interpret_source, model_context
from .sandbox import DockerCode


class GeneratedProvider:
    def __init__(self, policy, mapping, api, customers, model, repetitions, calibration):
        self.policy, self.mapping, self.api, self.customers = policy, mapping, api, tuple(customers)
        self.model, self.repetitions, self.calibration = model, repetitions, calibration
        self.generated_suite = suite_for(policy, mapping, customers, model, repetitions, api)
        self.calibrated = admitted(calibration, policy, mapping, api, model)
        self.official_suite, self.official_cases = None, []
        self.results, self.feedbacks = {}, {}
        self.seconds_per_repetition = 120 * len(customers)

    def bind(self, official_suite, official_cases):
        self.official_suite, self.official_cases = official_suite, official_cases
        if official_suite:
            self.seconds_per_repetition += 240
            return official_suite, official_cases
        return (self.generated_suite, self.customers) if self.calibrated else (None, [])

    def manifest(self):
        return {"backend": "local_proxy", "calibrated": self.calibrated, "suite": asdict(self.generated_suite),
                "calibration_fingerprint": self.calibration.get("fingerprint"), "official_ranks": bool(self.official_suite),
                "critical_failure_veto": self.calibrated, "results": self.results}

    def vetoed(self, workflow_hash):
        result = self.results.get(workflow_hash, {})
        return self.calibrated and result.get("calibration_fingerprint") == self.calibration.get("fingerprint") and bool(result.get("critical_failures"))

    def feedback(self, workflow_hash):
        return self.feedbacks.get(workflow_hash, {}) if self.calibrated else {}

    def evaluate(self, workflow, adapter, folder, roles, deadline):
        folder = confined(folder)
        official = adapter.evaluate(self.official_cases, self.official_suite, folder) if self.official_suite else None
        report, raw = evaluate_workflow(workflow, self.policy, self.mapping, self.customers, roles, deadline,
                                       folder / "synthetic", self.repetitions, api=self.api, calibration=self.calibration)
        if report["suite"]["suite_hash"] != self.generated_suite.suite_hash:
            raise ValueError("Generated suite changed after freezing; matched measurements required")
        critical = sorted({row["id"] for rows in raw["all_rows"] for row in rows if row.get("verified_hard_failure")})
        self.results[digest(workflow)] = {"score": report["score"], "critical_failures": critical,
                                        "calibration_fingerprint": self.calibration.get("fingerprint"),
                                        "selection_eligible": report["selection_eligible"], "recording_root": str(folder / "synthetic")}
        if self.calibrated:
            failed, visited = call_records(folder / "synthetic", raw)
            self.feedbacks[digest(workflow)] = {"verdicts": verdicts(raw, self.generated_suite),
                "failed_calls": failed, "visited": visited,
                "findings": {row["id"]: row.get("failed", []) for rows in raw["all_rows"] for row in rows if row.get("pass") is False}}
        if official is not None:
            # Runtime estimation accounts for both independent evaluations, without merging their scores.
            durations = sum(s.get("seconds", 0) for s in raw.get("simulations", []))
            if official.get("simulations"):
                for simulation in official["simulations"]:
                    simulation["seconds"] = float(simulation.get("seconds", 0)) + durations / len(official["simulations"])
            return official
        # Existing builder feedback reads calls next to raw_runner.json.
        for path in (folder / "synthetic").glob("calls_*.json"):
            write_json(folder / path.name, json.loads(path.read_text()), immutable=True)
        write_json(folder / "raw_runner.json", raw, immutable=True)
        return raw


def freeze_source(root, cfg, settings):
    """Capture before source interpretation/building, including code the holdout must not change."""
    fingerprint = source_fingerprint()
    write_json(root / "frozen.json", {"source_fingerprint": fingerprint, "config": asdict(cfg), "settings": settings.manifest()}, immutable=True)
    for directory in (ROOT, ROOT.parent / "agent" / "builder"):
        for path in directory.glob("*.py"):
            destination = root / "source_code" / path.relative_to(ROOT.parent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
    return fingerprint


def run_build(settings, brief_paths, api_path=None, *, pack=None, holdout=False, cfg=None, seed=42, users=10,
              builder_factory=Builder):
    if not settings.enabled:
        raise ValueError("Disabled builds must delegate directly to the existing entry point")
    cfg = cfg or Config.from_env()
    if not 1 <= users <= 10: raise ValueError("Live user cap is ten")
    if cfg.repetitions > 3: raise ValueError("Local proxy supports at most three repetitions")
    offline = pack is not None
    missing = [key for key in missing_credentials(cfg) if not offline or not key.startswith("FREYA_")]
    if missing: raise ValueError("Missing credentials: " + ", ".join(missing))
    brief_paths, api_path = inputs(brief_paths, api_path)
    cfg = replace(cfg, artifacts=ROOT / "private" / "builds", runtime=ROOT / ".runtime", official=False if offline else cfg.official)
    roles, trace, deadline, root = model_context(cfg)
    frozen = freeze_source(root, cfg, settings)
    provider, reading, calibration, diagnostic = None, None, None, None
    preparation_error = None
    customers = []
    started = time.monotonic()
    try:
        if settings.users and not holdout:
            try:
                DockerCode(deadline).ready()
            except RuntimeError as exc:
                preparation_error = str(exc)
            api = json.loads(Path(api_path).read_text())
            if preparation_error:
                policy, mapping = None, None
            elif pack:
                _, policy, mapping, customers = pack
            else:
                try:
                    reading = interpret_source("\n\n".join(Path(p).read_text() for p in brief_paths), api, roles)
                    write_json(root / "source_reading.json", reading.model_dump(mode="json"), immutable=True)
                except (ValueError, RuntimeError) as exc:
                    preparation_error = trace.redact(str(exc))[:500]
                policy, mapping, customers = (reading.policy, reading.mapping, []) if reading else (None, None, [])
                if reading and not reading.unresolved and policy and mapping:
                    # Admit the size before freezing; two candidate evaluations must fit the estimated budget.
                    count = min(users, max(1, int(deadline.remaining() / (2.4 * 120 * cfg.repetitions))))
                    customers = customers_for(policy, seed, count)
            if policy and mapping and customers and not (reading and reading.unresolved):
                write_json(root / "users.json", [c.model_dump(mode="json") for c in customers], immutable=True)
                calibration = calibrate(policy, mapping, api, roles, deadline, root / "calibration")
                provider = GeneratedProvider(policy, mapping, api, customers, cfg.builder_model, cfg.repetitions, calibration)
        # A failed admission costs no ranking authority. The original compiler/build path still runs.
        deadline.require()
        from .local_adapter import LocalAdapter
        kwargs = {"adapter_factory": LocalAdapter} if offline else {}
        builder = builder_factory(cfg, brief_paths, api_path, evaluation_provider=provider, deadline=deadline,
                                  submission_dir=ROOT / ("local_out" if offline else "out"), **kwargs)
        if hasattr(builder, "trace"):
            from .progress import publish_progress
            publish_progress(builder.trace)
        if holdout:
            builder.slot += "-holdout"
        result = builder.run()
        if result.get("export_path") and settings.users and (holdout or (provider and not provider.results)):
            if pack:
                _, policy, mapping, customers = pack
                api = json.loads(Path(api_path).read_text())
            if customers:
                kwargs = {}
                estimate = 1.2 * 120 * len(customers) * cfg.repetitions
                if deadline.remaining() < estimate:
                    class BudgetAbstention:
                        def __init__(self, *a, **k):
                            raise TimeoutError("Diagnostic skipped: estimated complete suite does not fit remaining build budget")
                    kwargs["runner_factory"] = BudgetAbstention
                diagnostic, _ = evaluate_workflow(read_workflow(Path(result["export_path"])), policy, mapping, customers,
                                                roles, deadline, root / "final_diagnostic", cfg.repetitions, api=api,
                                                calibration=None if holdout else calibration, **kwargs)
        if frozen != source_fingerprint(): raise ValueError("Builder/evaluator source changed after freezing")
        calibration_summary = {key: calibration[key] for key in ("fingerprint", "admitted", "false_passes", "false_failures", "unknowns", "created") if key in calibration} if calibration else None
        if calibration_summary: calibration_summary["record"] = str(root / "calibration" / "calibration.json")
        result.update(settings=settings.manifest(), preparation_error=preparation_error, synthetic_preparation_seconds=round(time.monotonic()-started-result.get("seconds", 0), 2),
                      calibration=calibration_summary, diagnostic=diagnostic, holdout=holdout, export_type="local_compiled" if offline else "freya_export", source_fingerprint=frozen)
        # Detailed prompts/cases remain private; publish aggregate evidence and exact export only.
        released = ROOT / "artifacts" / root.name
        write_json(released / "report.json", result, immutable=True)
        if result.get("export_path"):
            write_json(released / "workflow.json", json.loads(Path(result["export_path"]).read_text()), immutable=True)
        trace.close(status=result["status"], report=str(released / "report.json"))
        return result
    except Exception as exc:
        trace.close(status="failed", error=type(exc).__name__)
        raise
