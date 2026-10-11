"""One 30-minute builder loop: official practice calls, then live persona diagnostics."""
from dataclasses import asdict
import json

from agent.builder.artifacts import digest
from agent.builder.build import call_records
from agent.builder.scoring import verdicts
from .config import ROOT
from .live import evaluate_personas, public_customer
from .progress import mirrored


class PublicPersonaProvider:
    """Keep official ranking authoritative while using persona failures for repair."""

    simulations_per_measure = 2
    seconds_per_repetition = 900

    def __init__(self, profile="ordinary"):
        self.profile = profile
        self.suite = None
        self.cases = []
        self.customers = []
        self.results = {}
        self.feedbacks = {}

    def bind(self, official_suite, official_cases):
        if not official_suite or len(official_cases) != 10:
            raise ValueError("Live builder needs the supplied ten-case official practice suite")
        self.suite, self.cases = official_suite, official_cases
        self.customers = [public_customer(case, self.profile, i, persona_only=True)
                          for i, case in enumerate(official_cases)]
        return official_suite, official_cases

    def manifest(self):
        return {"backend": "freya_persona_diagnostic", "official_ranks": True,
                "profile": self.profile, "case_count": len(self.cases), "results": self.results}

    def vetoed(self, workflow_hash):
        return bool(self.results.get(workflow_hash, {}).get("critical_failures"))

    def feedback(self, workflow_hash):
        return self.feedbacks.get(workflow_hash, {})

    def evaluate(self, workflow, adapter, folder, roles, deadline):
        official = adapter.evaluate(self.cases, self.suite, folder)
        # Its own name: under the official folder's name the dashboard showed the official results twice.
        private = ROOT / "private" / "live_builds" / folder.parent.parent.name / (folder.name + "_personas")
        with mirrored(private, folder.parent / private.name):
            report = evaluate_personas(adapter, self.cases, self.customers, roles, private, self.suite.repetitions)
        diagnostic = json.loads((private / "raw_runner.json").read_text())
        key = digest(workflow)
        official_verdicts = verdicts(official, self.suite)
        persona_verdicts = verdicts(diagnostic, report_suite(report))
        combined = {case: False if False in (official_verdicts[case], persona_verdicts[case])
                    else True if official_verdicts[case] is True and persona_verdicts[case] is True else None
                    for case in official_verdicts}
        failed_calls, visited = call_records(private, diagnostic)
        findings = {}
        for rows in official.get("all_rows", []):
            for row in rows:
                if row.get("pass") is False:
                    findings.setdefault(row["id"], []).extend(row.get("failed", []) or row.get("bank_failed", []))
        for rows in diagnostic.get("all_rows", []):
            for row in rows:
                if row.get("pass") is False:
                    findings.setdefault(row["id"], []).extend(row.get("failed", []) or row.get("bank_failed", []))
        self.feedbacks[key] = {"verdicts": combined, "failed_calls": failed_calls,
                               "visited": visited, "findings": findings}
        critical = sorted({row["id"] for rows in diagnostic.get("all_rows", []) for row in rows
                           if row.get("verified_hard_failure")})
        self.results[key] = {"score": report["score"], "critical_failures": critical,
                             "selection_eligible": report["score"]["complete"]}
        for repetition, simulation in enumerate(official.get("simulations", [])):
            if repetition < len(diagnostic.get("simulations", [])):
                simulation["seconds"] = float(simulation.get("seconds") or 0) + float(diagnostic["simulations"][repetition].get("seconds") or 0)
        return official


def report_suite(report):
    from agent.builder.scoring import Suite
    return Suite(**report["suite"])
