# Ticket 2 implementation audit — 11 October 2026

What this repo does: it converts debt-collection briefs and OpenAPI contracts into Freya workflows, measures and repairs them where evidence exists, and exports the selected workflow. `generalisation_agent/` adds synthetic requirements, adaptive customers, a local workflow interpreter, mock bank, independent ledger checks, transcript grading, and optional feedback into that builder.

**Verdict: the architecture is useful, but Ticket 2 is incomplete and its synthetic evidence is not yet reliable enough to control selection.** There are reproducible false negatives and false positives in grading, runtime differences inside the advertised supported subset, and contract assumptions that prevent live admission against the supplied practice API. Passing the current unit tests does not resolve those problems.

Reviewed working tree at `77c8b34c83666ce60a136554ff0f67bd9c358722`, including the existing uncommitted `agent/builder/adk.py` and untracked `tools/smoke_test.py`. No implementation files were changed by this audit.

## Scope and verification

The current specification is [generalisation_agent/docs/tickets/ticket-02.md](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/docs/tickets/ticket-02.md). The older [agent proposal](/Users/oguzhansinik/Downloads/build-the-builder/agent/docs/tickets/ticket-02.md) is explicitly superseded; its hosted mock, 85% admission threshold, and mutable suite proposal are not the acceptance criteria.

I inspected the maintained source across `generalisation_agent`, the existing builder, official client/runner/scorer, examples, observability backend/frontend, tests, briefs, practice cases, API/workflow documentation, and dependency configuration. Historical run directories, installed dependencies, and secret files were outside the source-review scope. The review traced generation through compilation, execution, grading, candidate selection, export, holdout evaluation, and dashboard publication.

Fresh checks:

| Check | Result | What it establishes |
|---|---|---|
| Existing generalisation, builder, and observability tests | 177 passed; 3 Docker tests skipped in the ordinary run | Existing controller and fixture assertions hold |
| Explicit Docker test run | 3 passed | Pinned image, CPU termination, and compiled controller/mapping execution work here |
| Targeted independent probes | Reproduced the failures described below | Gaps exist beyond the current tests |
| Paid/model-backed two-pack rehearsal | Not run in this audit | No new claim of successful generation, calibration, or generalisation |
| Official Freya simulation/platform parity | Not run in this audit | Local results remain proxy evidence |

Commands used:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest generalisation_agent/tests agent/tests observability/tests -q -p no:cacheprovider
GENERALISATION_TEST_DOCKER=true PYTHONDONTWRITEBYTECODE=1 python3 -m pytest generalisation_agent/tests/test_docker.py -q -p no:cacheprovider
```

The first explicit Docker run had one readiness failure. Direct inspection then found the pinned image, and a complete rerun passed all three tests. This is not evidence of a consistently failing sandbox.

## What is already sound

- The extension reuses the existing builder instead of copying its search loop. Master-off delegates to the old entry point; brief/user switches are independently checked.
- Policy facts, mappings, saved wording, suites, and workflow hashes are explicit. Rendering has a separate extraction/check pass. Holdout users enter evaluation after building, rather than design/fix prompts.
- The bank deliberately accepts collection-policy violations, while a separate reference module uses decimal arithmetic and source calendar rules. This matches the competition's separation of tool execution from policy compliance.
- Generated results have a distinct evidence label. Incomplete suites do not receive a strict pass rate. Wording changes are measured at their own workflow hash in calibrated generated mode.
- Docker isolation, endpoint matching, fresh case state, shared workspace locking, retained candidate exports, and the all-vetoed failure path are worthwhile safeguards. Keep them.

## Must fix before synthetic selection

### 1. [P1] A later unknown erases an already observed critical violation

**What:** [evaluation.py:32](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/evaluation.py:32) returns before ledger or transcript grading when execution is incomplete or has any unknown.

**Problem:** An authored false-identity recording produces `pass=false`, a pre-verification account-access failure, and `verified_hard_failure=true`. Adding a later unsupported-runtime unknown changes it to `pass=null`, `failed=[]`, and `verified_hard_failure=false`. The provider's critical veto reads that flag. An officially ranked candidate can therefore avoid a synthetic veto by failing critically and then hitting an unrelated unsupported feature or timeout.

**Fix:** Grade proven facts in the executed prefix even when the rest is unknown. Preserve confirmed privacy violations, invalid committed writes, and duplicate writes. Only completion-dependent checks, such as a missing final close on an interrupted call, should abstain. Keep the suite incomplete, but retain the critical veto and evidence.

**If skipped:** A runtime limitation can hide an actual safety failure. AT-06, AT-10, and critical-veto guarantees are not met.

### 2. [P1] The live mapping model cannot represent the supplied API

**What:** [models.py:98](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/models.py:98), [bank.py:163](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/bank.py:163), and [packs.py:144](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/packs.py:144).

**Problem:** `validate_mapping` requires a boolean `locked` response from `verify_identity`; the supplied API has `verified`, `wrong_answers_left`, `all_verified`, and an optional hint, but no `locked`. With correct wrapper and field bindings, the probe rejects it for that missing field. Adding only `locked` to a temporary contract exposes the next incompatibility: every `reason` argument must represent all **15** policy reasons, while the supplied `add_note` enum has only five. Separately, one `minimum` product binding cannot faithfully reproduce cards' `minimum_payment` and loans' `instalment_amount`. The current mock also omits conditional fields such as `card_last4` and identity hints.

The live interpreter additionally requires citations for every synthetic policy field and all 20 fixed core rules. A real brief that omits a synthetic commit guarantee or obligation disables the entire profile, even when many other checks are supported. This abstention is safer than guessing, but defeats the requested live use case.

**Fix:** Make mappings operation-specific, support optional/derived internal state without inventing external response fields, allow conditional product fields, and validate reason enums per operation. Separate synthetic pack completeness from live check support: unresolved semantics disable the affected checks with source reasons. Validate against the real kit API first, then a renamed equivalent.

**If skipped:** The extension can evaluate APIs it generates itself while failing to admit ordinary supplied inputs. AT-03 and AT-12 are unmet.

### 3. [P1] Pre-action response variables use the wrong name

**What:** [runner.py:200](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/runner.py:200).

**Problem:** API pre-actions write `<function_name>_response` and success counters, although the builder explicitly instructs models to use `<stage>_response` for pre-actions. The kit also documents node-based pre-action counters. A stage named `check_dob` calling `verify_identity` will not supply the keys its routes/code expect. My compiled close-stage probe produced only `close_call_response...` and `close_call_success_count`, with no `close_response...`. Failure counters are never populated.

**Fix:** Pass execution placement into `execute_tool`; use node names for pre-actions and tool names for model-called tools. Implement the documented result/counter variables for both success and failure. Add conformance cases where stage and operation names intentionally differ. See [builder prompt:75](/Users/oguzhansinik/Downloads/build-the-builder/agent/builder/prompts.py:75) and [tool documentation:325](/Users/oguzhansinik/Downloads/build-the-builder/docs/tools-and-code.md:325).

**If skipped:** Valid workflow routes can fail locally or take a different branch from Freya, contaminating repair feedback.

### 4. [P1] Supported entry speech is silently skipped on action nodes

**What:** [runner.py:261](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/runner.py:261) routes API/code nodes before processing `on_enter`.

**Problem:** A compiled API close node with `on_enter` TTS and a silent terminal passes `capability_errors`, finishes normally, reports no unknown, and records no assistant speech. The builder itself recommends putting a required pre-close goodbye in that stage's TTS. The proxy therefore accepts a feature it silently drops.

**Fix:** Establish the platform order for action-node entry speech and implement it. Until that order is supported, explicitly abstain for these nodes rather than silently omitting speech. Test an API close node with a fixed farewell and a silent terminal.

**If skipped:** The judge sees a different conversation and can penalize correct workflows or miss actual behavior. This is a confirmed proxy omission; exact live ordering still needs platform evidence.

### 5. [P1] Exhausted noncommitting write failures receive the wrong oracle outcome

**What:** [oracle.py:92](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/oracle.py:92).

**Problem:** Only ambiguous commitment activates `service_error` handling. When both permitted write attempts fail before committing, the oracle expects `refused` and also penalizes an unrecorded willing customer's promise. The probe closes truthfully with `no_promise/service_error` and receives a critical wrong-closure failure. The supplied [Brief A rule 37](/Users/oguzhansinik/Downloads/build-the-builder/briefs/brief-a.md:91) explicitly requires this service-error closure. [Brief B rule 11](/Users/oguzhansinik/Downloads/build-the-builder/briefs/brief-b.md:19) requires a `service_error` note for the failed product; the oracle currently derives its note reason from willingness instead.

**Fix:** Compute per-product terminal write state from attempted operations, results, commit state, and retry allowance. Derive closure and notes from those actual states, rather than customer intention alone. A source-supported exhausted service failure is an acceptable result, not an impossible promise obligation.

**If skipped:** Correct recovery can be vetoed, and repair feedback can push the builder toward an incorrect closure.

### 6. [P1] Calibration can pass without detecting the rule it claims to test

**What:** [calibration.py:34](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/calibration.py:34) and [calibration.py:173](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/calibration.py:173).

**Problem:** Admission asserts case pass/fail and a generic critical flag, not the intended rule. The `false_success` fixture removes the committed promise but leaves a promise closure. With a transcript judge that reports no failures, the ledger oracle still produces a critical closure failure. Thus this control can be counted as successful even when honesty detection is blind. Most negatives are edited recordings; the one executed workflow is compliant and uses a scripted customer. Negative routing behavior and adaptive actor semantics are not established by that control.

**Fix:** Store an expected rule ID for each control and assert that specific detection. Isolate dishonest speech by keeping its ledger/closure otherwise correct. Add executed bad-identity and failure-routing controls, plus focused boundary and changed-contract controls. Recompute admission after fixing these fixtures.

**If skipped:** “Zero false passes” over these controls overstates what was calibrated. AT-08 is not established.

### 7. [P1] The judge can mark triggered obligations inapplicable

**What:** [judge.py:36](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/judge.py:36).

**Problem:** Only privacy and final closure are prohibited from being `not_applicable`. In a probe with an actual promise-write event and matching confirmation evidence, both readings mark all other rules inapplicable; the validator accepts them and `Judge.grade` returns no failure or unknown. Instructions ask the model to determine applicability correctly, but the validator does not enforce known triggers. A verbatim quote also proves that text exists, not that every semantic claim attached to it is true.

**Fix:** Determine rule applicability from policy and observed events where possible. A write triggers confirmation and success-honesty checks; a committed promise triggers notification; a correction triggers reconfirmation. Reject contradictory inapplicability as unknown. Keep semantic judging for speech that needs interpretation, with isolated negative controls and evidence binding.

**If skipped:** Same-model agreement can silently waive required checks.

### 8. [P1] Optional preparation can abort before any baseline export

**What:** [integration.py:108](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/integration.py:108) through builder construction.

**Problem:** Source interpretation and calibration run before the builder, using its shared active deadline. A source-analyst `TimeoutError` is not caught by the preparation fallback. The probe confirms the exception propagates and the builder is never called. Calibration can also exhaust the active budget, after which `deadline.require()` aborts. An export reserve cannot preserve an export that was never built.

**Fix:** Give optional preparation a bounded portion of the shared deadline and retain enough time for baseline design/compilation/export. Treat preparation timeouts as admission failures. Alternatively establish and cache the baseline before expensive optional evaluation. Preserve the single overall 30-minute limit.

**If skipped:** Enabling optional synthetic testing can turn an otherwise exportable build into a total failure. AT-13/AT-14 fallback behavior is incomplete.

## Should fix for useful generalisation evidence

### 9. [P2] Customer facts and coverage are not sufficiently source-adaptive

**What:** [generation.py:124](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/generation.py:124), [actors.py:4](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/actors.py:4), and [oracle.py:72](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/oracle.py:72).

**Problem:** Every call date is in December 2028, and the holiday proposal is fixed to Christmas 2028. This exercises the generated calendar but need not exercise a supplied calendar's holidays. The third-party scenario and oracle demand exactly 11:00, even for a valid source profile whose callback window starts at 13:00; that produces an impossible passing case. Identity values are arbitrary four-digit strings except ISO dates. `pieces` asks for one detail at a time, rather than splitting the same number across turns as the public style does.

Coverage is also fixed by slot index. There is no dispute goal, no required calendar + multiple-products + correction combination, and only band starts are sampled. Smaller suites take a prefix. Even with the full initial 1,620 active seconds, live admission permits at most five users at one repetition or one at three repetitions before preparation time. That prefix omits hardship, paid, mixed products, write failure, and human transfer.

**Fix:** Derive call dates from source holidays/boundaries and callback times from the legal window. Validate that each case has at least one attainable acceptable outcome. Select a balanced subset by relevant risks, with explicit coverage gaps. Allocate the ten slots to targeted combinations and pairs; make fragmented-number behavior explicit and verify fact preservation in actor transcripts.

**If skipped:** Ten saved users, or a smaller prefix, can look comprehensive while missing the intended capabilities. AT-05, AT-09, and AT-18 remain partial.

### 10. [P2] Turn counters and caps differ from the documented engine

**What:** [runner.py:245](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/runner.py:245) and [runner.py:332](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/runner.py:332).

**Problem:** `visits` combines node entry and user turns, persists across re-entry, and drives the per-node cap. The documented engine counts user turns since entry separately from total turns. The proxy never supplies `<node>.current_turns` or `<node>.total_turns`, even though the existing compiler inserts guards on the latter. The default proxy cap is 1,000 instead of the documented 10.

**Fix:** Track entries, current user turns, and total user turns separately; expose the documented variables and apply the appropriate defaults. Verify re-entry and compiler-inserted loop guards. See [workflow-format.md:237](/Users/oguzhansinik/Downloads/build-the-builder/docs/workflow-format.md:237) and [runtime.py:310](/Users/oguzhansinik/Downloads/build-the-builder/agent/builder/runtime.py:310).

**If skipped:** Loop termination and repeated greetings can differ from the workflow being exported.

### 11. [P2] The mock accepts requests outside declared schema constraints

**What:** [bank.py:25](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/bank.py:25).

**Problem:** Validation checks a small set of keywords but silently ignores numeric bounds, string patterns/lengths, and composition constraints. Adding `minimum: 100` to the actual promise request schema still allows amount `1` and records the promise. Accepting collection-policy violations is intentional; accepting a request that violates the supplied API schema is a different behavior.

**Fix:** Use the already installed `jsonschema` dependency for an explicitly supported OpenAPI schema subset, with version-aware handling; reject or abstain on unsupported constraints during mapping admission. Do not introduce a new validator dependency. [OpenAPI 3.0.3 Schema Object](https://spec.openapis.org/oas/v3.0.3.html#schema-object) defines these supported constraint keywords.

**If skipped:** Changed API contracts can produce confident results for calls the real bank rejects.

### 12. [P2] Rehearsal can succeed with no completed holdout measurement

**What:** [integration.py:148](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/integration.py:148) and [__main__.py:65](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/__main__.py:65).

**Problem:** Post-build evaluation uses a fixed estimate of 120 seconds per user/run with a 1.2 multiplier. Ten holdout users at three repetitions require an estimated 4,320 seconds, exceeding the maximum active build budget even before building; that configuration always abstains. At one repetition, 1,440 seconds must remain after the build. The CLI nevertheless returns success whenever both exports exist, without requiring completed measurements. Scores are honestly incomplete, but command success does not mean Ticket 2's rehearsal succeeded.

**Fix:** Reserve time for final diagnostics, use observed throughput to budget a frozen suite, and distinguish export success from rehearsal completion. A completed rehearsal requires both exact exports and all requested measurements. Label a partial rehearsal explicitly and return a distinct unsuccessful completion status. Keep one-run development and three-run robustness claims separate.

**If skipped:** The required vertical slice can be reported as finished while every sealed case is unknown.

### 13. [P1, existing builder] Identity “proof” accepts an explicit failure route

**What:** [validation.py:106](/Users/oguzhansinik/Downloads/build-the-builder/agent/builder/validation.py:106).

**Problem:** Any condition on a non-spoken variable can count as verification proof. Changing the existing minimal fixture's account route to `all_verified equals false` still returns `valid=true` with no errors or warnings. Testing that a tool ran, or that a response exists, does not establish that identity passed.

**Fix:** Require proof tied to the source-mapped verification-success signal and a positive success condition. Keep runtime negative-route calibration as an independent backstop. Make this a small separately scoped builder change, as the current ticket already anticipates.

**If skipped:** An unsafe identity graph can pass static validation; finding 1 can then hide its observed runtime violation.

### 14. [P2, observability] Private artifacts can escape containment; values can become HTML

**What:** [store.py:110](/Users/oguzhansinik/Downloads/build-the-builder/observability/store.py:110), [store.py:379](/Users/oguzhansinik/Downloads/build-the-builder/observability/store.py:379), and [index.html:396](/Users/oguzhansinik/Downloads/build-the-builder/observability/static/index.html:396).

**Problem:** `run_dir` permits `..` and follows symlink directories without checking their resolved location. A temporary symlink from the served root to a separate “sealed” directory exposes its sentinel report through `run_summary`. Candidate paths similarly lack resolved containment. Separately, `kvTable` renders any string beginning with `<` as raw HTML, including artifact-derived values. The server's loopback binding limits exposure but does not establish sealed-data separation or safe artifact rendering.

**Fix:** Resolve and confine every run/candidate/artifact path using one helper; reject dot IDs and escapes through symlinks. Escape artifact values by default and make intentional UI markup explicit at trusted call sites.

**If skipped:** Keeping private files outside the nominal served directory is not sufficient to guarantee the holdout boundary. This is hardening of the existing dashboard, not a requested rewrite.

## Nice to have after correctness

### 15. [P2] Freeze effective model configuration and refresh status documents

**What:** [calibration.py:22](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/calibration.py:22), [integration.py:79](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/integration.py:79), and the ticket/README status sections.

**Problem:** Fingerprints include Python source and the model name, but provider endpoint and environment-derived reasoning settings are outside `Config` and that fingerprint. Rehearsal freezes source between packs but resolves build configuration anew. The canonical ticket also reports an older test count and billing failure, while the README describes later output/time-limit and semantic-check failures.

**Fix:** Snapshot the nonsecret effective provider configuration once, pass it through both packs, and include it in calibration/suite identity. Record the selected endpoint, reasoning/output settings, dependency/runtime version, and relevant model settings without credentials. Update acceptance status to the verified evidence, with separate statuses for unit tests, generation, calibration, rehearsal, and platform parity.

**If skipped:** Identical model labels may refer to materially different executions, and readers cannot tell which stages were actually completed.

## Acceptance assessment

| Ticket criteria | Assessment |
|---|---|
| AT-01/AT-04: two coherent model-rendered packs, independent rendering check | Code and fixture coverage exist; successful real two-pack generation/rehearsal remains unverified |
| AT-02: saved structural facts and hash replay | Substantial local implementation; exact saved output replay is preferable to assuming a seed reproduces model wording |
| AT-03/AT-12: changed semantics/API and live source users | Partial; supplied API incompatibility and fixed case assumptions are concrete blockers |
| AT-05/AT-18: realistic adaptive users | Adaptive mechanism exists; fragmented speech, source-derived cases, and real actor behavior need evidence |
| AT-06/AT-07: actual workflow execution and independent truth | Actual compiled execution and permissive bank work; runtime and partial-evidence bugs invalidate some judgments |
| AT-08/AT-09: calibrated negatives and boundaries | Gate exists; confounded controls, applicability gaps, and incomplete boundary coverage prevent reliance on it |
| AT-10: sealed holdout and failures retained | Holdout is excluded from build feedback; failure erasure and dashboard containment need correction |
| AT-11: evidence labels and incomplete scores | Mostly sound; keep those distinctions while repairing grading |
| AT-13: exact measured versions and fallback | Own-hash wording checks and retained exports are good; pre-baseline timeout fallback is missing |
| AT-14: scheduling/lock/deadline | Shared lock and Docker verified locally; preparation and holdout scheduling need work |
| AT-15/AT-16/AT-17: boundaries, replay, switches | Largely implemented locally; effective model configuration and containment need hardening; hosted mock remains conditional |

## Best path to the requested outcome

Keep the current architecture and ten-user/two-pack cap. Spend the next work on evidence correctness before adding more models, hosted services, or wider runtime support.

1. **Repair grading first:** preserve proven violations on incomplete calls, derive service-error outcomes from actual writes, isolate calibration controls, and enforce known applicability. Add regressions for the exact probes above.
2. **Make the supported interpreter trustworthy:** pre-action naming, counters, turn accounting, and explicit entry-speech support. Build a small conformance matrix from the supplied runtime documentation, with a known-good and known-bad workflow for each supported behavior. Unsupported behavior must abstain visibly.
3. **Prove one real source contract:** adapt the kit API faithfully, check Brief A and A+B against supplied expected fixtures, then repeat with field/enum renaming and a changed calendar. Use independent recorded outcomes; do not reuse builder-extracted requirements as truth.
4. **Generate attainable, targeted cases:** derive facts from the source profile, use balanced risk selection, include the required combinations, and test invariance/boundary pairs within the cap. Verify actor transcripts preserve facts and apply corrections rather than only checking that their prompts request it.
5. **Reserve build and final evaluation time:** cache a baseline, bound preparation, measure case/model-call durations, and freeze the selected suite before comparing candidates. Never reduce a suite after observing failures.
6. **Complete the actual vertical slice:** generate one clean development pack and one raw holdout pack, build the development workflow with admitted feedback, freeze effective code/configuration, build the holdout without its user feedback, then evaluate both exact exports. Archive all cases, judgments, unknowns, calibration controls, timings, and hashes. A low score can still be a completed experiment; missing measurements cannot.
7. **Enable selection only after those gates pass:** official scores continue to rank official candidates; confirmed critical synthetic violations can veto; changed workflows need their own evidence. Keep local proxy claims separate from Freya parity and hidden-score claims.

This approach follows capability-focused behavioral testing: CheckList organizes test ideas by capabilities and test types. For this project, boundary pairs and meaning-preserving speech changes are useful engineering applications, not evidence that two packs predict the final score. [Ribeiro et al., ACL 2020](https://aclanthology.org/2020.acl-main.442/)

LLM-judge research documents position, verbosity, self-enhancement, and reasoning limitations. My engineering inference is that two calls to the same model should be treated as a disagreement detector, not independent ground truth. Prefer deterministic checks for ledger/order facts and isolated calibration for semantic speech judgments; adding another provider is unnecessary before fixing the existing controls. [Zheng et al., MT-Bench/Chatbot Arena](https://arxiv.org/abs/2306.05685)

The official evaluation requires ledger correctness, policy, and honesty together, with every repetition passing. It also confirms that the bank itself does not enforce collection policy. Preserve that three-part evaluation design. [Freya evaluation](https://www.freyavoice.ai/hackathon#evaluation) The current rules restrict phone-agent tools to the supplied API, and the FAQ limits the practice bank to its supplied customers; neither establishes permission for a hosted custom bank. Keep local testing as the immediate deliverable. [Rules](https://www.freyavoice.ai/hackathon#rules), [FAQ](https://www.freyavoice.ai/hackathon#faq)

## Limits of this audit

No live provider requests, deployment, official simulations, new hosted services, or hidden-case access were performed. Existing documents report unsuccessful model-backed generation attempts; those are historical evidence, not freshly reproduced provider failures. Platform behavior inferred from the supplied runtime documentation still needs differential checks against actual recorded Freya behavior. The current findings are sufficient to withhold confidence in synthetic selection even without that extra experiment.

**Overall assessment:** retain the implementation and fix its measurement contract. Stages 1–4 are not yet demonstrated end to end, and the critical-veto gate currently has both false-negative and false-positive paths. The smallest useful next milestone is a correct, fully measured development/holdout rehearsal using the existing components.
