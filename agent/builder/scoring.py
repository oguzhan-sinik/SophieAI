"""Strict scoring of one measured suite. Verdicts come from the runner and are never re-judged."""
from dataclasses import asdict, dataclass

from .artifacts import digest


@dataclass(frozen=True)
class Suite:
    case_ids: tuple[str, ...]
    suite_hash: str
    evidence_type: str
    repetitions: int
    style: str = ""

    def __post_init__(self):
        if not self.case_ids or len(set(self.case_ids)) != len(self.case_ids) or self.repetitions < 1:
            raise ValueError("Suite needs unique cases and positive repetitions")
        # official_public: the kit's practice customers on the kit's bank. generated: customers the
        # builder wrote itself, which are never reported as an official result.
        if self.evidence_type not in {"official_public", "generated", "freya_chat_diagnostic", "freya_persona_diagnostic"}:
            raise ValueError("Unknown evidence type")

    @property
    def key(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class ScoreRecord:
    suite_key: str
    suite_hash: str
    evidence_type: str
    repetitions: int
    total: int
    passed: int
    failed: int
    unknown: int
    strict_pass_rate: float | None
    coverage_ratio: float
    hard_fail_count: int
    complete: bool


def verdicts(raw, suite):
    """Per customer: True when every repetition passed, False when one failed, None when a result is missing."""
    all_rows = raw.get("all_rows", [])
    out = {}
    for case_id in suite.case_ids:
        seen = []
        for repetition in range(suite.repetitions):
            matches = [row for row in (all_rows[repetition] if repetition < len(all_rows) else []) if row.get("id") == case_id]
            verdict = matches[0].get("pass") if len(matches) == 1 else None
            seen.append(verdict if type(verdict) is bool else None)
        out[case_id] = False if any(v is False for v in seen) else True if all(v is True for v in seen) else None
    return out


def score(raw, suite):
    """A missing result cannot pass, and an incomplete suite has no pass rate."""
    all_rows = raw.get("all_rows", [])
    by_case = verdicts(raw, suite)
    observed = sum(type(row.get("pass")) is bool and not row.get("unknown") for rows in all_rows[:suite.repetitions] for row in rows if row.get("id") in by_case)
    shape = len(all_rows) == suite.repetitions and all(len(rows) == len(suite.case_ids) and {r.get("id") for r in rows} == set(suite.case_ids) for rows in all_rows)
    total = len(suite.case_ids) * suite.repetitions
    outcomes = list(by_case.values())
    unknown = sum(verdict is None or any(row.get("unknown") for rows in all_rows[:suite.repetitions] for row in rows if row.get("id") == case_id) for case_id, verdict in by_case.items())
    complete = bool(shape and observed == total and unknown == 0)
    return ScoreRecord(suite.key, suite.suite_hash, suite.evidence_type, suite.repetitions, len(outcomes), outcomes.count(True), outcomes.count(False), unknown,
                       outcomes.count(True) / len(outcomes) if complete else None, observed / total,
                       sum(row.get("verified_hard_failure") is True for rows in all_rows for row in rows), complete)
