# TICKET-04 — Human speech simulation and complete live conversation testing

**Status:** Implementation available with deterministic controls; model-backed, live, parity and human-review acceptance remain pending. See [implementation status](../ticket-04-implementation.md).
**Priority:** P0 — final-benchmark readiness.
**Researched:** 11 October 2026.
**Owner:** `generalisation_agent/`, with focused changes to the existing builder/runtime and Freya adapter.
**Depends on:** [canonical Ticket 02](ticket-02.md), especially oracle calibration, immutable suites, source interpretation and export correctness. Extends the existing single fix loop. Ticket 03 consumes released aggregate evidence.

## 1. Outcome

Create believable, adaptive fictional customers whose conversational behaviour is controlled and independently verified. Use them to test the actual generated phone workflow from greeting through final bank closure, locally and on Freya. Make the builder produce agents that preserve meaning through fragmented answers, corrections, distractions and questions back.

Completion requires evidence that **the simulator did the intended thing, the agent handled it correctly, and the tested workflow is the exported workflow**. A style name in a prompt, a generated pack, a single chat response, or a local proxy pass cannot establish all three.

### Authoritative benchmark requirements

Freya's “How customers talk” section explicitly covers numbers split across turns, self-corrections, tangents, questions back and spoken amounts/dates. Final evaluation uses two unfamiliar briefs, 30 customers per brief, up to three products and several call dates. A case must pass all three repetitions, with correct ledger outcome, policy and honesty; there is no partial credit. The bank can accept policy-invalid writes. One brief is a clean specification and one is raw bank material. Conversations are text. These facts were checked directly on the [evaluation page](https://www.freyavoice.ai/hackathon#evaluation).

Phone agents may call only the supplied tool API. Builder runs include tests in their 30-minute limit; simulations are serial per workspace. Agents must be generated without manual edits, and customer data must be synthetic. Preserve those [competition rules](https://www.freyavoice.ai/hackathon#rules).

**Interpretation for this ticket:** conversational interruptions mean textual changes of subject or intent. Audio generation, ASR, TTS and acoustic interruption testing are outside this milestone. They would be a separate project, not a prerequisite for this benchmark.

## 2. Research and why this design

| Primary research | Relevant lesson | Decision here |
|---|---|---|
| [Agenda-based user simulation, Schatzmann et al.](https://aclanthology.org/N07-2038.pdf) | A private goal and pending dialogue agenda give a simulator memory across turns. | A small Python state controller chooses the next permitted conversational act; an LLM expresses it naturally. |
| [τ-bench, Yao et al.](https://arxiv.org/html/2406.12045v1) | Dynamic user dialogue, tool state and policy must be evaluated together; repeated success matters. | Keep customer knowledge separate from tool/oracle state, measure actual ledger effects, and require all three runs. |
| [User Simulation with LLMs for Evaluating Task-Oriented Dialogue, Davidson et al.](https://arxiv.org/abs/2309.13233) | Maximising simulator cooperation/task success is different from reproducing human behaviour. | Validate customer fidelity separately from agent success. Use varied fictional dialogue exemplars and independent human review. |
| [RealUserSim, Zhu et al.](https://arxiv.org/abs/2605.20204) | Unconstrained simulators tend toward formal cooperation; strong style instructions can overshoot into caricature. | Ground speech in concrete preferences, limited knowledge and bounded behaviour events; verify realised behaviour. |

These are engineering inferences from other dialogue domains, not proof of debt-collection realism. Do not import real-user datasets or customer transcripts from those projects. Hand-author fictional examples and use the kit's synthetic practice cases. No fine-tuning, new agent framework, model-provider migration or additional hosted service is required for the core implementation.

## 3. What the current code actually does

The review covered application modules in `generalisation_agent/`, `agent/builder/`, `observability/`, the kit client/tools/examples, tests and public fixtures, plus connected contracts and ticket documentation. Credentials, generated private runs and sealed holdout customer contents are excluded. Existing tests establish useful controller and oracle properties; they do not establish human-like adaptive actors or full live synthetic calls.

| Current implementation | Gap and consequence |
|---|---|
| `actors.py`: five prompt styles; `Actor.reply()` sends customer facts and speech history to one model. | No explicit fragment cursor, wrong-answer cursor, pending question, correction revision or event history. A customer can repeat a mistake indefinitely, forget a fragment or skip the intended stress event. |
| `models.py`: one `Customer.style`; `UserReply` validates message shape and hang-up only. | Valid JSON does not prove consistent facts, appropriate consent, bounded behaviour or plausible speech. Styles cannot be composed explicitly. |
| `generation.py`: `STYLES[index % 5]` on ten fixed family slots. | Speech styles are coupled to business scenarios. No paired clean/stressed controls, reliable compound coverage or independently measured style fulfilment. The “Already paid or dispute” slot currently generates paid, not dispute. |
| `Goal.accepts_legal_alternative` and free-text `Customer.correction`. | Too little structure to verify what a customer actually accepted or changed for each product. A correction can diverge from the static oracle's willingness assumptions. |
| `runner.py`: extraction, routing and dialogue roles execute compiled JSON with supported proxy semantics. | Uncertain extraction leaves existing variables untouched; stale values after corrections need targeted regressions. The proxy is not Freya's extractor. Unsupported features remain unknown. |
| `agent/builder/runtime.py`: spoken-date helpers and guards; `prompts.py`: policy and confirmation instructions. | No common contract for fragment completeness, slot provenance, product-scoped corrections or consent bound to a tuple revision. Date parsing alone cannot resolve a tangent containing several dates. |
| `calibration.py`: authored transcript controls and a compiled controller using `ScriptedActor`. | Calibrates grading/controller behaviour, not the adaptive actor against good and bad conversational partners. |
| `integration.py`: `GeneratedProvider.evaluate()` calls `evaluate_workflow()` locally. | Deployment does not make generated evaluation live. `LocalAdapter` deliberately makes no Freya calls. |
| `freya_adapter.py`: public simulation path and one-turn `chat_smoke()`. | The public path accepts only public suites; chat smoke ends immediately. No complete external-actor live loop or generated-bank live backend exists. |
| `evaluation.py`, `scoring.py`, `progress.py`, Studio. | Strict repetition scoring exists, but actor validity and planned/observed behaviour coverage are absent. Public progress currently exposes only safe model-call metadata. |

Treat stale extraction and mis-scoped normalization as risks to reproduce, not claims that every generated graph currently fails. Preserve the correctness fixes already made in Ticket 02.

## 4. Customer design: private agenda plus natural wording

### Separate four responsibilities

1. **Case specification:** immutable fictional identity/account facts, call `now`, caller relationship, product goals, willingness limits and allowed goal revisions. Generated independently of the candidate workflow.
2. **Behaviour plan and state:** choose eligible acts from the last spoken question and customer history. Track fragments, corrections, interruptions, responses to explanations and pending questions. The controller must not read agent variables, graph nodes, tool events or verdicts to decide what to say.
3. **Language realization:** the existing tool-free model role turns one selected act into a plausible short utterance. It may choose wording, not change facts, willingness or consent scope.
4. **Conformance check:** independently verify the realised utterance and resulting event against the selected act. The policy/outcome grader remains a separate component.

The actor's `reply(conversation)` interface can remain. Return only speech and hang-up to the phone agent; store state and audit records privately. Reuse current Pydantic records, ADK calls, immutable artifacts, deadline and bank interfaces. A few records/functions are enough; do not create a second workflow engine.

### Minimal private contracts

| Record | Required information |
|---|---|
| Behaviour plan | Version; seed; baseline/ordinary/stress profile; required events; semantic triggers; target slot/product; fragment boundaries or proposed-to-corrected values; maximum activations; permitted completion/hang-up conditions. |
| Actor state | Pending question/act; slot and fragment cursor; supplied wrong-answer cursor; emitted event IDs; unresolved clarification; per-product proposed/agreed tuple and revision; patience budget. Fresh for every repetition. |
| Turn audit | Selected act; actual utterance; before/after state hashes; exact turn references; validator result; repair attempts; behaviour opportunity and observed event status. |
| Quality report | Fact/goal fidelity; actor validity; planned, eligible and observed coverage; blocked opportunities; semantic uncertainty; naturalness review; model/prompt/configuration versions. |

The plan records **intent**, not a fixed transcript. A differently phrased or differently ordered agent must still elicit the appropriate response. Triggers use spoken semantics, not candidate node names or expected turn numbers. Confidence uncertainty produces a clarification or recorded unknown, not a fabricated observation.

### Knowledge and fidelity invariants

- The customer sees only what that person could know and what the agent has said. Preserve `customer_payload()`'s third-party exclusion and the exclusion of faults. Also exclude ledger expectations, policy checks, model reasoning, compiled graph and selection feedback.
- Customer preferences express willingness, not omniscient knowledge of bank floors, deadlines or whether a tool committed. Accept an offered alternative only when it is understood and within the private willingness constraints; leave policy legality to the oracle.
- Keep identity and account facts immutable. Mistaken speech and its correction are explicit events over those facts. A scripted identity failure never becomes a correct answer because the agent insists.
- Product decisions and revisions are isolated. Correcting the loan's date cannot silently change the card's amount. A semantic-changing revision is declared in the case and included in its admissible outcomes; it is not a style-only paraphrase.
- A read-back correction is performed once at the eligible point and remains corrected. Confirm only the current matching tuple, or the permitted matching group. Never agree to a false read-back to rescue a struggling agent.
- Tangents/questions are bounded and preserve pending answers. Ordinary callers may be terse, hesitant, impatient or mildly distracted without inserting noise into every turn. Stress profiles intentionally combine two or three events and are labelled as designed stress, not estimated human frequencies.
- Customer hang-up follows explicit bounded patience/termination rules. Do not hang up solely because a model selected `hang_up=true` without supported state.

Use deterministic checks for known digits, value equivalence, cursor movement and declared revisions. Use a separate bounded semantic check only when language meaning cannot be resolved deterministically; require exact transcript evidence. One bounded realization repair may occur **before** sending an invalid utterance, with all attempts saved and charged to the deadline. Unresolved invalidity ends with simulator-invalid evidence; never silently send a cooperative substitute.

## 5. Required conversational coverage

All examples below are fictional fixture patterns. Generate their actual values from each case; they are not templates containing hidden-brief constants.

| ID | Behaviour and sample pattern | What must be observed / protected |
|---|---|---|
| B01 | Fragmented digit sequence: “zero three…” then “five eight.” | Ordered assembly preserves leading zeros. First fragment is incomplete; no identity call using an invented completion. |
| B02 | Fragment plus question back: first digits, “Why do you need that?”, remaining digits. | Explanation and return to pending slot; no forgotten/restarted fragment or early debt disclosure. |
| B03 | Date/year split: day/month followed by year in words. | Full identity date required; do not substitute call year for a birth year or accept a half-date. |
| B04 | Self-repair within a turn: “forty—sorry, fourteen.” | Latest explicitly corrected value supersedes the mistaken value; ambiguous repair prompts clarification. |
| B05 | Correction after read-back, before consent. | Old tuple invalidated; new read-back and new explicit agreement before write. |
| B06 | Correction after agreement but before an uncommitted write. | Old consent invalidated. Only test a real customer-turn opportunity; do not inject a turn between silent nodes the live platform cannot interrupt. |
| B07 | Spoken money including cents, digit groups and ordinary hesitation. | Exact cents and value preserved. No float/rounding guess changes the customer's intent. |
| B08 | Relative/worded date near weekend, holiday, month/year boundary. | Resolve from case `now`; clarify vague periods; legal alternatives follow the source calendar. |
| B09 | Tangent with unrelated money/date: “My appointment is Monday; payment is Friday.” | Extract the payment date, not the first date mentioned. Keep unrelated amounts out of promise slots. |
| B10 | Question instead of answer: “Which account?” / “Are you a person?” | Answer safely and truthfully, then resume. A question is not consent or a flat refusal. |
| B11 | Mixed answer/question: amount plus uncertainty about date. | Preserve the known part, clarify the uncertain part; do not fabricate a complete tuple. |
| B12 | Minimal replies, backchannels and scoped negation: “right”, “not that one”, “yes, but tomorrow.” | Acknowledgement is not blanket agreement; product/date correction takes precedence over the leading yes. |
| B13 | Two/three products, pronouns and changed order: “that loan, not the card.” | Clarify ambiguous references and revise only the intended product. Group consent only when permitted. |
| B14 | Paid/dispute/hardship/refusal embedded in everyday speech; human request mid-negotiation. | Correct no-promise/transfer behaviour. Tangents do not erase intent or consume policy persuasion attempts incorrectly. |
| B15 | Third party offers to pay, asks what is owed, provides a worded callback. | No security answers/debt knowledge provided by simulator; privacy, callback and closure tested. |
| B16 | Identity-attempt boundary, write failure or lost reply during a stressed conversation. | No helpful actor override of failed security, premature success agreement or repeated ambiguous write. |

The release suite must demonstrate every applicable B01–B16 behaviour and the five named benchmark categories. Cover identity and negotiation, one to three products, changed field names, and clean/raw briefs. At least three compound plans must cross behaviour boundaries: fragments + question; correction + spoken money/date; multi-product + tangent + scoped confirmation. Record unsupported/inapplicable combinations explicitly.

Decouple family selection from speech-profile selection. Include clean controls, single-event profiles and compounds. Use matched clean/stressed variants for the same facts and willingness to expose speech-specific failures. These variants consume case slots. For a genuine goal revision, compute the distinct admissible outcome explicitly; do not assert metamorphic equivalence.

## 6. Generated agent architecture must be ready

Update designer/fixer guidance and reusable runtime support where necessary. The builder must derive policy values and allowed formats from supplied inputs; these are generic conversation requirements, not a hardcoded bank agent.

1. **Capture before normalization.** Preserve raw utterance, target slot, relevant turn, candidate value and completeness. Keep fragments pending until sufficiently complete under the declared field format or clarified by the caller. Where the source gives no length/format, ask; do not guess four digits universally.
2. **Separate unrelated information.** Extract only the answer relevant to the current/pending question. A tangent or question back must not populate a date/money/security slot from unrelated speech.
3. **Represent revisions.** Track a version for each proposed product/amount/date tuple. A relevant correction clears derived values and old confirmation. An uncertain correction blocks a write rather than reusing stale consent/value.
4. **Resume dialogue deliberately.** Safe explanations and honesty answers return to the pending question. Hardship, dispute, security refusal and transfer requests retain their source-defined precedence. Fragment turns do not count as wrong security submissions; clarification/tangents are distinct from policy refusals.
5. **Bind consent.** Read back the applicable product, amount and date; bind explicit agreement to that exact revision. A matching grouped read-back can bind a permitted group. Every changed member invalidates the affected confirmation. No conversational backchannel alone authorises a write.
6. **Keep tool authority deterministic.** Security tools remain sequential and account access depends on positive verification results. Writes remain isolated engine-run API nodes; argument validation, retry/commit handling and close ordering keep their existing guards.
7. **Bound recovery.** Avoid repeated greeting/read-back loops; use sensible per-node and global limits that leave enough room for compounds. Explain exhausted clarification safely and record the correct outcome. A simulator-driven timeout is measured, not hidden by increasing limits indefinitely.

Verify each behaviour on generated graphs, not just the hand-authored positive controller. Regression examples should exercise extractor outputs, state transitions, actual code execution and resulting tool arguments. The local runner must expose any changed capability explicitly; Freya-only unsupported features still abstain locally until parity is established.

## 7. Calibrate the simulator independently

Retain Ticket 02's oracle controls. Add an actor-conformance admission gate with compliant and deliberately misleading dialogue partners. It must cover fragment continuation, repeated questions, wrong read-backs, pressure to accept a larger amount, false claims of verification, product swaps, persona-changing instructions, premature success claims and interrupted pending answers.

For each control, assert the **specific** actor behaviour and state invariant, not merely whether the agent passed. Include legitimate alternative phrasings and question orders to prevent a brittle script from qualifying. Changing actors, profiles, normalization, validators, model settings or relevant runtime capabilities invalidates admission. Hash new fixture/plan files as well as Python sources.

Keep three independent result axes:

| Axis | Values | Meaning |
|---|---|---|
| Actor validity | valid / invalid / unknown | Did the fictional customer preserve knowledge, facts, willingness and declared acts? |
| Behaviour coverage | planned / eligible / observed / blocked_by_agent / missed_by_actor / inapplicable | Did an actual utterance exercise the intended behaviour, and why not? |
| Agent verdict | pass / fail / unknown | Correct ledger, policy and honesty on the actual valid conversation. |

A failing agent that closes before a later behaviour opportunity keeps its proven failure; do not discard the case to improve scores. A behaviour missed despite an eligible trigger is a simulator problem and cannot support a claimed successful stress pass. Preserve critical violations observed before later simulator/infrastructure uncertainty, following Ticket 02's prefix rules.

Freeze the planned case denominator and publish missing/invalid attempts. Invalid/unknown cases block complete-suite selection eligibility and cannot become positive repair feedback. Quarantining requires a new suite version and matched remeasurement; never remove failures from the original report. Actor self-reported tags are not observed coverage: require turn references and validated utterance evidence.

Before release, two reviewers independently inspect 30 sampled **synthetic** conversations, stratified across profiles, business outcomes and both backends. Rate plausible speech, responsiveness and goal fidelity separately; resolve disagreements and save the rubric/results. Proposed gate: at least 90% accepted on plausibility and responsiveness, and zero unresolved fact/consent violations. This is an engineering gate, not a scientific claim that our simulator matches the real population.

## 8. Suite sizes, repetitions and budgets

- Preserve the current default of two packs and at most ten customers per pack/build. Variants fit inside those slots; rotated seeds cover additional combinations. Report the smaller campaign's coverage honestly.
- Add an explicitly selected **release stress campaign** of two fictional briefs × 30 customers × three repetitions. This is 60 cases and 180 full conversations, our own benchmark-shaped campaign, never the hidden benchmark. It has a separately declared test budget and frozen manifest; it is not silently added to every 30-minute builder run.
- Every repetition starts fresh bank state, customer state and live session. Preserve semantic goals/plans while varying saved realization seeds. Three copies of one recorded conversation are replay evidence, not three adaptive trials. A seed alone cannot reproduce nondeterministic provider output; retain actual outputs and effective settings.
- A case passes the reliability gate only when all three valid repetitions pass. Also report per-repetition outcomes and failure categories. Do not use best-of-three, average pass rate or promised money to compensate for safety/policy failure.
- Preserve one active simulation per workspace, existing locks, bounded model calls and export reserve. Preflight estimated call/model/simulation cost and time. A budget shortfall records incomplete coverage and a non-success exit; it must not erase an eligible cached export.
- Reserve inexpensive actor controls for development. Run the larger conformance/human-review campaign outside final builder timing; reuse only fingerprints that still match. Any testing performed inside a builder run remains charged to that run.

## 9. Full live end-to-end testing

### Required backend distinction

| Backend | Implement/test | Evidence label and limit |
|---|---|---|
| Actual compiled graph + Docker + local bank + adaptive Actor | Extend existing runner; both fictional packs and changed policy/API. | `local_proxy`; cannot establish Freya equivalence. |
| Freya public-case simulation with speech profiles | Reuse kit sessions, personas, published version checks and ledger retrieval. Keep original facts/expected checks. Validate realised persona behaviour from the returned transcript. | Original practice baseline remains `official_public`; custom/composite diagnostics get a distinct suite identity and explicit diagnostic label. |
| Stateful Actor driving complete Freya chat | Extend one-turn smoke into a loop through greeting, security, negotiation, tools and closure. Use fresh lawful practice fixtures, actual published workflow and complete call/ledger retrieval. | `freya_chat_diagnostic`; not assumed equivalent to the simulation runtime. |
| Freya with arbitrary generated accounts/policies | Use only a documented, permitted fixture mechanism or an explicitly approved remotely reachable synthetic backend. Run the same Actor/plan contract and independent oracle. | `freya_synthetic_live`; unavailable until permission, reachability and parity evidence exist. |

The preferred immediate live slice uses the supplied bank and its practice fixtures. Persona simulations validate the real simulation path; the external Actor chat loop validates our stateful simulator against the live workflow. These complementary tests must not be described as the same backend.

Use only documented kit/platform APIs and test the contract with one small call before scaling. Do not invent an account-creation endpoint or override immutable practice-bank facts. A profile that changes the economic goal must use a matching supported fixture/oracle; it cannot borrow another case's expected ledger unchanged. Map public data into private actor knowledge without copying grading checks into actor prompts.

**External dependency:** the public kit currently offers no verified arbitrary synthetic-account live path. Ticket 02's historical proposal to rewrite tool URLs is not permission. Do not presume a testing clone is exempt from the rules. If organizer approval or an official fixture facility is unavailable, complete local and lawful public-fixture live work, but leave the arbitrary-pack live acceptance gate blocked. Ticket 04 cannot be marked fully done by relabelling the local runner as live.

### Live runner requirements

Record published workflow/version/hash and agent model before starting. Preserve the compiler-selected initial node, API URLs and production definition. Use the documented chat start/continuation/end lifecycle; always clean up a known live session in `finally`. Obtain complete ordered agent/customer speech, node events, extractions where available, tool requests/results and ledger state. Missing version, tool or ledger evidence yields unknown.

Check live/runtime parity with bounded positive and negative vectors: fragmented identity, stale extraction after correction, date normalization, response mapping, consent invalidation, tool-failure counters, retry semantics and final close. Inspect transcript/tool ordering; a green final ledger is insufficient. Record unsupported chat semantics or skipped initial code as parity gaps, rather than changing the starting node to get a favourable run. Repeat both good and failing controls three times.

### Every layer the acceptance run must cover

1. Interpret clean and raw fictional source documents; independently validate policy/API mappings.
2. Generate frozen customer facts, plans and admissible outcomes without candidate access.
3. Admit actor conformance and existing oracle calibration at matching fingerprints.
4. Run the existing analyst/designer/compiler/fix loop to create actual workflows; no hand edits.
5. Publish and verify the exact candidate/version that will be tested.
6. Exercise complete adaptive conversations, extraction, routing, code and bank actions.
7. Retrieve independent ledger effects and policy/honesty evidence; validate actor fidelity and realised coverage.
8. Apply development feedback and critical veto without merging official/generated scores or exposing holdout facts.
9. Freeze the final candidate; evaluate sealed holdout cases three times with no feedback to the builder.
10. Export and compare definition/hash with measured candidate; retain traces, cleanup evidence, budgets and released safe aggregates.

Provide one documented command/workflow for the completed acceptance campaign. Extend the existing CLI where possible with explicit backend/profile/campaign selection; document new syntax as proposed until implemented. An export alone does not mean the campaign completed.

## 10. Artifacts and observability

Extend existing manifests and reports, avoiding a second artifact system. Store customer plans/state, detailed conformance audits, raw model attempts, admissible revisions and recordings under `generalisation_agent/private/`. Release only permitted aggregate coverage and quality summaries. Keep holdout details out of designer/fixer prompts and Studio HTTP responses.

Each measurement binds case/suite ID, split, repetition, plan/version/seed, source and API hashes, effective actor/validator/judge settings, backend/capabilities, calibration IDs, workflow hash, published version, call IDs, timestamps and deadline consumption. No result can be inherited by a changed wording/graph/profile hash.

Show baseline/stressed coverage, actor-validity counts, all-three pass counts, per-family gaps, backend and incomplete reasons in existing reports. Extend `progress.py`'s aggregate allowlist carefully; model prompt/response payloads and private paths remain private. If Studio gains access to additional artifacts, first fix/test existing containment and HTML-rendering concerns identified in the [Ticket 02 audit](../ticket-02-audit-2026-10-11.md). No dashboard redesign is needed.

## 11. Acceptance tests

All gates below are required unless a supported source contract makes the specific behaviour inapplicable. Missing external live access is a recorded blocker, not an acceptance waiver.

| ID | Test | Passing evidence |
|---|---|---|
| HUM-01 | Fragmented number with leading zero and intervening question. | Correct ordered assembly; no premature tool call; actual fragment/question turns cited. |
| HUM-02 | Wrong-answer sequence under repeated/rephrased questions. | Cursor advances once per genuine answer, never resets; intended attempt boundary and closure hold. |
| HUM-03 | Identity date split into day/month/year in words. | Full date recovered without replacing year; no extra answers volunteered. |
| HUM-04 | In-turn correction plus read-back correction. | Final intended value used; old revision/consent invalidated; exactly one permitted write after matching new agreement. |
| HUM-05 | Tangent carrying unrelated date and amount. | Relevant slots survive; unrelated values never reach bank arguments. |
| HUM-06 | Question back before authentication and digital-assistant question. | Safe truthful answer, pending task resumed, no account disclosure. |
| HUM-07 | Cents, ambiguous date and mixed answer/question. | Exact amount retained; uncertainty clarified; call `now`/source calendar used. |
| HUM-08 | Multi-product reference and single-member revision. | Only named member changes; group/individual consent follows supplied policy. |
| HUM-09 | Paid, dispute, hardship, refusal and human-transfer cases. | Correct non-promise outcomes; no actor-induced payment/cooperation; source-defined precedence. |
| HUM-10 | Third party with disclosure pressure and callback words. | Actor never sees/provides private identity; agent preserves privacy and correct callback closure. |
| HUM-11 | Broken partners try to change customer facts, role or willingness. | Zero unresolved fact/consent changes; conformance catches the intended violation. |
| HUM-12 | Good partners use varied wording/order. | Actor responds adaptively, completes bounded events and does not require a memorized transcript. |
| HUM-13 | Same facts in clean, single-event and compound profiles. | Frozen paired cases; expected invariance or declared semantic revision; observed coverage independently checked. |
| HUM-14 | Three repetitions with fresh actor/bank/session state. | All-three metric correct; one failed run fails case, one missing/invalid run blocks complete success. |
| HUM-15 | Actor error/timeout after proven agent violation; agent closes before a planned trigger. | Preserve critical prefix failure and original denominator; distinguish missed actor event from blocked agent opportunity. |
| HUM-16 | Model/profile/fixture/runtime changes after admission. | Fingerprint invalidation, no cached score/feedback authority for changed configuration. |
| HUM-17 | Actual model-backed, generated clean/raw workflows on local packs. | Complete three-run holdout measurements with real adaptive actors/Docker; no fixture-role evidence presented as live models. |
| HUM-18 | Full live Freya conversation with our Actor on supported bank fixtures. | Greeting to closure, cleanup, complete transcript/tool/ledger and published-version evidence; each applicable behaviour covered. |
| HUM-19 | Freya persona simulation on clean/single/compound diagnostic profiles. | Actual observed behaviour coverage, exact version, all-three results and independent ledger checks. No prompt-only coverage claim. |
| HUM-20 | Arbitrary generated-pack live backend and runtime parity. | Verified lawful fixture/backend, reachability, matching controls and full conversations on changed policy/API; no local substitution. |
| HUM-21 | End-to-end build → feedback → freeze → holdout → export. | Immutable exact export identity, sealed holdout firewall, separate official/generated metrics and critical veto. |
| HUM-22 | Budget exhaustion, deployment outage and active workspace. | Serial simulation/cleanup, bounded waits, honest incomplete non-success result and preserved eligible export. |
| HUM-23 | Human quality review. | 30 synthetic calls, two independent reviewers, ≥90% plausibility/responsiveness acceptance and zero unresolved fact/consent violations. |
| HUM-24 | Release campaign/report and Studio privacy. | 60 frozen cases × three full calls; B01–B16 applicable coverage; released aggregates contain no sealed facts, prompts or private paths. |

Required controls must have zero false admissions and unresolved uncertainties before they authorise selection. For generated workflows, report real pass rates and failures; do not force all difficult cases green by weakening customers or expectations. “High quality” refers to measured simulator fidelity and useful stress coverage, not a guaranteed hidden score.

## 12. Implementation order and file map

| Milestone | Deliverable | Likely existing files |
|---|---|---|
| M1 — One complete conversation | Stateful fragment + question + correction actor, validated realization, wrong-read-back controls, observed events on actual compiled graph. | `models.py`, `actors.py`, `runner.py`, new focused actor/behaviour tests. |
| M2 — General coverage and agent readiness | Orthogonal plans, clean/stressed pairs, bounded compounds, product revisions and consent regressions; actor admission integrated with oracle admission. | `generation.py`, `packs.py`, `calibration.py`, `evaluation.py`, `oracle.py`, `judge.py`; builder `prompts.py`, `runtime.py`, focused `validation.py` changes if justified. |
| M3 — Full lawful live slice | External Actor chat loop plus persona diagnostics on supported fixtures; version/tool/ledger/parity checks, cleanup and serial lock. Resolve arbitrary-pack backend dependency early. | `integration.py`, `__main__.py`, builder `freya_adapter.py`, `scoring.py`; reuse kit client/tools without changing their production contract. |
| M4 — Release evidence | Actual generated-agent clean/raw local and live campaigns, sealed holdout/all-three results, quality review, exact export, aggregate report and operational docs. | `config.py`, `progress.py`, README; minimal Studio projections/tests. |

Do not mark M3 complete for a one-turn smoke, or M4 complete for pack generation. Run deterministic/unit controls first, then real Docker/model calls, then one live conformance call, then the frozen campaign. A legitimate dependency blocker must remain visible through the final report.

## 13. Definition of done

The implementation ships a small adaptive customer controller with believable wording, independently admitted behaviour/fact/consent fidelity, composed coverage and truthful scoring. The builder automatically generates speech-resilient workflows from unfamiliar source material. One reproducible acceptance workflow exercises the entire pipeline, including actual complete Freya calls, changed-source local/live coverage, three repetitions, sealed holdout, measured export identity and safe traces.

Attach the manifest, coverage matrix, actor/oracle calibration, model-backed local reports, live transcripts and ledgers, parity report, human-review results, timing/budget report and export hash. List every failed/unknown test and external dependency. If arbitrary synthetic cases cannot legally reach the live backend, state that limitation and keep HUM-20 and full Ticket 04 acceptance open.
