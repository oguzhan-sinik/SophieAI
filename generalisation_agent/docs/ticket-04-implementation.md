# Ticket 04 implementation status

The deterministic implementation is available. Final ticket acceptance remains open: the user
explicitly excluded live LLM tests during implementation, and arbitrary generated-pack live bank
fixtures still have no verified lawful backend.

Implemented:

- Immutable customer facts and explicit seeded baseline/ordinary/stress behaviour plans; willingness
  ceilings, terminal wrong-answer sequences, fragment/date cursors, bounded interruptions and
  per-product corrections. The actor receives speech only, without graph/tool/oracle state.
- Separate listener, permitted-act realizer and conformance validator, with exact evidence,
  deterministic digit/year leak checks, one bounded repair and private before/after state audits.
- Separate authored actor calibration, including semantic bad-actor controls, alongside oracle
  calibration. Cached authority binds effective role models, endpoint settings, source, API,
  customer plans and compiled workflow identity.
- All-three scoring with distinct actor validity/coverage and original denominators. Missing or
  blocked behaviour prevents a positive result; proven prefix violations survive later unknowns.
  Safe reports include profile/paired comparisons, declared revision counts and coverage gaps.
- Ten-case default packs and explicit 30-case matched release packs, two briefs and three repeats.
  The existing build/feedback/holdout/export path precedes a separately budgeted campaign.
- Builder instructions and injected helpers for leading zeros, complete birth years, incomplete
  slots/provenance, exact cents and product-specific tuple revisions/consent. Uncertain/invalid
  proxy extraction clears stale date/completeness values. Simulator agendas/audits never enter
  designer/fixer call evidence.
- Complete external Actor chat plumbing on three authored public fixture translations; native
  call/ledger/version evidence, stable session IDs, bounded turns and reserved cleanup. Persona
  diagnostics preserve all original public scripts and add bounded plans, actual transcript
  coverage, independent source-policy/honesty checks and distinct diagnostic suite identities.
- Human-review input validation and aggregate gate for 30 hashed calls/two reviewers. This is a
  review gate, not proof that a simulator represents the real customer population.

Deterministic controls cover fragment + question + remaining digits on an actual compiled graph
through security, a single promise and bank closure; wrong answers; split birth years; stale
readback/consent; scoped corrections; bounded failed realization; third-party knowledge; pack
immutability; fresh repetitions; critical-prefix retention; live cleanup/version failure; prompt-only
coverage rejection; review prerequisites and budgets. Provider/Freya roles in these controls are
fakes. Restricted Docker tests additionally exercise the injected speech helpers.

Verification on 11 October 2026: **275 regression tests passed**, with five explicit Docker tests
skipped in the ordinary run. **All five Docker controls passed separately**; the speech-helper
control was rechecked after adding complete-year identity parsing. `git diff --check` passed.
Two live-builder attempts reached OpenRouter but stopped before Freya deployment or any customer
call: the key limit rejected the hard-model designer requests. The first attempt used the old
60,000-token reservation; the second was rejected while other requests were in flight. The
designer cap is now 32,000 tokens. A read-only key check found insufficient remaining allowance
for a complete design, repair and validation run, so paid retries stopped.

A new `live-build` command now stages the supplied ten-case official Freya suite before a
separate ten-case synthetic persona diagnostic on the same published candidate, then feeds
both failures into the existing repair loop under one 30-minute deadline. This path has
deterministic controls but still needs a completed live run. Offline case evaluation supports
opt-in bounded concurrency with isolated traces and customer state.

Remaining acceptance evidence:

- Real model-backed actor/oracle admission and clean/raw generated-workflow campaigns (HUM-17).
- Real full Freya chat/persona runs, native version availability, parity and all applicable observed
  coverage (HUM-18/19). A B06 scenario is only valid when a genuine customer-turn opportunity exists
  before commitment; it is exercised by an authored control, never fabricated in generated runs.
- Authored external Actor translations for the other practice scripts. Persona diagnostics already
  retain those original scripts; this does not establish stateful Actor parity.
- A permitted, reachable arbitrary generated-pack bank fixture/backend (HUM-20). The implementation
  refuses to substitute generated `.synthetic.invalid` endpoints into the practice live path.
- Actual human ratings, complete release coverage/timing, and attached live/export acceptance
  evidence (HUM-21–24). `release_accepted` remains false until these requirements are satisfied.

Regenerate older packs: version 3 changes the saved customer/behaviour contract. Existing measured
scores and calibration must not be inherited by changed plans, models, source or workflow wording.
