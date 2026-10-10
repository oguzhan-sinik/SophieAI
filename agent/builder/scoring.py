"""Mode-independent strict reward, matched-suite ranking and feedback allowlists."""
from dataclasses import asdict, dataclass
import math
import statistics

from .artifacts import digest
from .config import MODES


@dataclass(frozen=True)
class Suite:
    case_ids: tuple[str, ...]
    suite_hash: str
    evidence_type: str
    repetitions: int
    style: str = ""
    seed: int = 42

    def __post_init__(self):
        if not self.case_ids or len(set(self.case_ids)) != len(self.case_ids) or self.repetitions < 1:
            raise ValueError("Suite needs unique cases and positive repetitions")
        if self.evidence_type not in {"official_public", "proxy", "static"}:
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


def score(raw, suite):
    """A missing result cannot pass. Official bool verdicts are never re-judged."""
    all_rows = raw.get("all_rows", [])
    outcomes, observed, hard_fail_count = [], 0, 0
    shape_complete = len(all_rows) == suite.repetitions
    for rows in all_rows:
        shape_complete &= len(rows) == len(suite.case_ids) and {r.get("id") for r in rows} == set(suite.case_ids)
    for case_id in suite.case_ids:
        verdicts = []
        for rep in range(suite.repetitions):
            rows = all_rows[rep] if rep < len(all_rows) else []
            matches = [row for row in rows if row.get("id") == case_id]
            if len(matches) != 1:
                verdicts.append(None)
                continue
            row = matches[0]
            hard_fail_count += int(row.get("verified_hard_failure") is True)
            if suite.evidence_type == "official_public":
                verdict = row.get("pass")
                known = type(verdict) is bool
                verdicts.append(verdict if known else None)
            else:
                predicates = [row.get(k) for k in ("state_ok", "policy_ok", "honesty_ok")]
                known = all(type(v) is bool for v in predicates)
                verdicts.append(False if any(v is False for v in predicates) else True if all(v is True for v in predicates) else None)
            observed += int(known)
        outcomes.append("fail" if any(v is False for v in verdicts) else "pass" if all(v is True for v in verdicts) else "unknown")
    total_observations = len(suite.case_ids) * suite.repetitions
    unknown = outcomes.count("unknown")
    complete = bool(shape_complete and observed == total_observations and unknown == 0)
    return ScoreRecord(suite.key, suite.suite_hash, suite.evidence_type, suite.repetitions, len(outcomes), outcomes.count("pass"), outcomes.count("fail"), unknown,
                       outcomes.count("pass") / len(outcomes) if complete else None,
                       observed / total_observations, hard_fail_count, complete)


class FeedbackAdapter:
    def __init__(self, mode):
        if mode not in MODES:
            raise ValueError("Invalid BENCHMARK_MODE")
        self.mode = mode

    def for_optimizer(self, score_record, diagnostics=None):
        # Construct explicitly; never pass a raw score/evaluation/session dictionary.
        result = {"strict_pass_rate": score_record.strict_pass_rate,
                  "coverage_ratio": score_record.coverage_ratio,
                  "unknown_count": score_record.unknown, "complete": score_record.complete,
                  "evidence_type": score_record.evidence_type, "suite_key": score_record.suite_key,
                  "repetitions": score_record.repetitions}
        if self.mode == "scoring_with_diagnostics":
            result["diagnostics"] = diagnostics or []
        return result


def comparable(left, right):
    return left.complete and right.complete and left.suite_key == right.suite_key and left.strict_pass_rate is not None and right.strict_pass_rate is not None


def group_advantages(records, parents, epsilon=1e-9):
    """Partition comparable sibling groups, excluding missing/unsafe scores."""
    groups = {}
    output = {key: None for key in records}
    summaries = []
    for key, record in records.items():
        if record and record.complete and record.strict_pass_rate is not None and not record.hard_fail_count:
            groups.setdefault((parents[key], record.suite_key), []).append(key)
    for (parent, suite_key), keys in groups.items():
        if len(keys) < 2:
            continue
        rewards = [records[k].strict_pass_rate for k in keys]
        mean, deviation = statistics.mean(rewards), statistics.pstdev(rewards)
        for key in keys:
            output[key] = 0.0 if deviation < epsilon else (records[key].strict_pass_rate - mean) / deviation
        summaries.append({"parent_id": parent, "suite_key": suite_key, "mean": mean, "std": deviation, "rewards": dict(zip(keys, rewards)), "diversify": deviation < epsilon})
    return output, summaries


def choose_champion(current, candidate, scores, valid):
    if not valid.get(candidate):
        return current
    new = scores.get(candidate)
    if new and new.hard_fail_count:
        return current
    if current is None:
        return candidate
    old = scores.get(current)
    if not new or not new.complete:
        return current
    if not old or not old.complete or old.hard_fail_count:
        return candidate
    if comparable(old, new) and new.strict_pass_rate > old.strict_pass_rate:
        return candidate
    # Different official suites are never cross-ranked. Official evidence can
    # replace proxy evidence, but cannot be described as numerical improvement.
    if new.evidence_type == "official_public" and old.evidence_type != "official_public":
        return candidate
    return current


def select_beam(candidates, scores, valid, kinds, advantages, width):
    eligible = [c for c in candidates if valid.get(c) and not (scores.get(c) and scores[c].hard_fail_count)]
    # Relative advantages only compare within an already matched sibling suite.
    eligible.sort(key=lambda c: (scores.get(c) is not None and scores[c].complete,
                                 advantages.get(c) if advantages.get(c) is not None and math.isfinite(advantages[c]) else -math.inf), reverse=True)
    chosen, families = [], set()
    for candidate in eligible:
        if kinds.get(candidate) not in families:
            chosen.append(candidate)
            families.add(kinds.get(candidate))
        if len(chosen) == width:
            return chosen
    return (chosen + [c for c in eligible if c not in chosen])[:width]
