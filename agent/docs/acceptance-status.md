# Status against Ticket 1

Ticket 1 specified a beam search over sibling mutations with group-relative ranking and a
score-only / diagnostics experiment. Three live builds showed that machinery never improved the
first design, so it was replaced by a single fix loop (see `agent/README.md`, "How a build works").
This file records what that means for the ticket's acceptance tests.

| Acceptance checks | Now |
|---|---|
| AT-01–04, 18–24: unfamiliar input, workflow shape and safety | Covered by the compiler and static checks; `tests/test_core.py` |
| AT-05, 14, 17, 20, 32: lineage, recovery, export, publishing, trace | Kept: immutable candidates, cached-export fallback, version check, plain-text trace |
| AT-13: one simulation at a time | Kept: workspace lock; the kit client waits for a running simulation before it starts one |
| AT-15–16: telemetry outage, redaction | Kept |
| AT-06–12: sibling groups, relative advantages, feedback modes, paired comparison | Dropped with the beam search. Replaced by per-fix keep/blame on one measured child per round |
| AT-25–30: Brief A/B policy and speaking styles | Only a live simulation shows these; see the run folders under `agent/artifacts/` |

Fake-controller tests show how the loop behaves. They are not evidence that a generated agent
follows a bank's policy.
