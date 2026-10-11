# TICKET-02 — Synthetic briefs and users for unseen debt-collection requirements

**Status:** Implementation in place; 154 local tests and three real Docker tests pass. Final model-backed generation, calibration and two-pack rehearsal verification are pending because the configured endpoint rejects requests for unavailable shared-endpoint billing.
**Reviewed baseline:** `48ac224d78bf00fb9ab06df0f9a8c69ef49fc355`, 11 October 2026.

**Owner and output boundary:** `generalisation_agent/`.

**Replaces:** the implementation proposal in `agent/docs/tickets/ticket-02.md`; that file is preserved as a historical reference.
**Depends on:** the existing builder and its single measured fix loop, not Ticket 1's discontinued beam/GRPO design. Ticket 3 remains an optional reader of released aggregate evidence.

## 1. Outcome and agreed scope

Build a small harness that invents plausible, internally consistent bank requirements and difficult customers, invokes the existing builder with unseen Markdown and OpenAPI inputs, and measures the resulting workflow. Integrate generated customer testing into live builds against their actual supplied requirements. The generator must change the meaning of policies and API fields as well as the wording of documents and customers.

The user has chosen:

| Decision | Choice |
|---|---|
| Execution | Offline rehearsals **and** live builder integration |
| Domain | Debt collection, with changed policies, document formats, and API fields |
| Generation | Validated structured policy data; an LLM renders realistic specifications and memos |
| Bank | Local mock first; Freya tests after rules and reachability verification |
| Live feedback | Calibration gates candidate selection; preserve a tested export on failure |
| Initial size | Interpret “maybe 2 packs and 10 users” as **2 packs × 10 users**, with a maximum of 10 generated users per live build |

These numbers are defaults, not automatic claims of adequate coverage. Two packs provide a useful rehearsal and can reveal bugs; they cannot establish broad generalisation or predict the hidden score. Additional packs, model providers, hosted services, and material dependency changes require a decision before implementation expands to them.

Two modes share generation, bank, and grading code:

1. **Offline rehearsal:** create a fictional brief, its matching OpenAPI, ten synthetic users, and sealed expected behaviour. Give the builder only the brief and API. Execute and grade the actual produced workflow, retaining the exact workflow and evidence.
2. **Live integration:** keep the real supplied brief and API unchanged. Independently derive source-backed policy semantics and generate up to ten relevant users. Once calibration passes, their evidence can drive the existing fix loop. Do not replace the input with a randomly generated policy during a live build.

Implementation was authorised by the user on 11 October 2026. Stop at architectural decisions and ask the user before proceeding with the dependent work. The user subsequently chose to reuse `BUILDER_MODEL`, Docker isolation, calibrated proxy feedback, official ranking with a calibrated synthetic critical-failure veto, failure with retained artifacts when all candidates are vetoed, and local compiled exports for offline rehearsals. Results remain proxy evidence.

## 2. Verified competition constraints

The official site was inspected on 11 October 2026. These constraints govern the design:

- Final inputs are two debt-collection briefs, each with its own OpenAPI. One is a clean specification; the other is one Markdown file containing raw source documents. Seven operation names remain stable, while fields and enums may change. [Overview and FAQ](https://www.freyavoice.ai/hackathon#faq)
- Public practice supports only the supplied PUB-01–PUB-13 customers. Hidden briefs have no practice customers. The FAQ suggests chat testing when no practice cases exist. It does not explicitly permit replacing the bank with a hosted synthetic service. [FAQ](https://www.freyavoice.ai/hackathon#faq)
- Phone workflows may call only the supplied tool API. Keep the prescribed phone-agent model; builder models may differ. A 30-minute build includes its tests; the workspace has a 200-workflow limit and permits one simulation at a time. [Rules](https://www.freyavoice.ai/hackathon#rules)
- The bank does not enforce collection policy. It can accept an invalid promise; correctness still requires bank state, policy, and honesty. Each final customer must pass three runs. [Evaluation](https://www.freyavoice.ai/hackathon#evaluation)
- Submit actual Freya exports and their corresponding builder trace and code. Organisers rebuild selected submissions; a clearly lower rebuilt score can remove an entry. Post-release changes must remain general builder bug fixes. [Submission](https://www.freyavoice.ai/hackathon#submit)

Therefore local evidence is a proxy, generated results never become official results, and a test copy using a custom bank is **not presumed exempt** from the tool restriction. The site's published release is 11 October at 17:00 UTC and submission close is 20:00 UTC; use those dates rather than a relative “tomorrow”. [Overview](https://www.freyavoice.ai/hackathon)

## 3. Coherent brief packs

A pack is a versioned unit containing `brief.md`, `openapi.json`, validated policy data, operation mappings, ten user definitions, expected-behaviour rules, and a manifest. The manifest records generator version, seed, input/output hashes, model and prompt versions, coverage, and split. A seed reproduces structural choices; exact saved LLM outputs are required to replay rendered wording.

### Structured policy generation

Sample bounded combinations from explicit debt-collection dimensions, then validate their consistency **before** rendering:

| Dimension | Meaningful variations |
|---|---|
| Identity | Different required fields, verification order, shared/per-field attempt limits, allowed normalisation, third-party handling |
| Money | Full balance versus minimum, minimum source/formula, decimal amounts, inclusive band boundaries, partial-payment rules |
| Calendar | Working weekdays, holidays, deadlines by band/product, inclusive/exclusive counting, relative-date clarification, callback windows |
| Negotiation | Number and order of offers, refusal counting, hardship exceptions, already-paid/dispute/restructuring handling |
| Multiple products | One to three products, different bands/deadlines, grouped confirmation, partial refusal and partial write failure |
| Closure | Outcome/reason enums, precedence between mixed outcomes, notes/transfers/callbacks, required final action |
| API | Changed request/response field names, nesting and enum values while preserving the seven supplied operation roles |

Do not invent missing policy decisions for real inputs. An unresolved source conflict, unsupported schema, or unspecified retry guarantee makes the affected check `unknown`, with a cited reason. Keep explicitly contradictory and unsupported inputs in a separate robustness suite; do not mix them into the plausible final-brief denominator.

The policy and API must agree: every required argument has a source; response fields needed by the policy exist; all outcomes and queues are representable; calendars permit legal dates; identity requirements are satisfiable; numeric bands and precedence are explicit. Validate against the actual supported OpenAPI/workflow subset, not just syntactically valid JSON.

### LLM rendering

Render one pack as a clean Markdown specification and the other as realistic emails, policy memos, tables, and code lists embedded in **one** Markdown file. Use different policy/API configurations, not two paraphrases of the same policy. For raw material, state effective dates and authority so apparent conflicts can be resolved from the document itself.

An independent extraction/check pass verifies the rendered brief against the structured policy: thresholds, calendars, exceptions, precedence, operation bindings, and enums must survive rendering. Reject or repair a mismatch before admitting the pack. Reuse immutable facts across components, but do not reuse the builder's extracted requirements as the answer key.

**Illustrative synthetic mutation, not a prediction of finals:** a bank works Monday–Thursday, has a holiday immediately before a band deadline, calls its minimum `required_amount`, accepts promise fields `sum_due` and `due_on`, and uses an `arranged` closure enum. A customer proposes the holiday, then corrects an amount after read-back. The check asks whether the workflow selects a legal date, reconfirms the corrected amount, writes the correct fields, and closes with the source-defined outcome. The actual generated API still includes all seven operations.

## 4. Semantically intelligent synthetic users

Separate private customer facts, goals, response strategy, and speech style from grading criteria. Users respond to what the workflow actually asks; they are not fixed transcripts and do not volunteer every security answer immediately.

Each user records fictional identity, account/products, `now`, constraints, willingness to accept specific lawful alternatives, third-party status where relevant, controlled faults, and a bounded dialogue strategy. Grade admissible behaviour rather than requiring one exact wording or one arbitrary script path. Keep expected ledger and evaluator criteria out of the customer prompt and out of the builder's initial design input.

Use the existing public customers as the behavioural reference: wrong security answers, annoyance and disclosure questions, corrections, “you tell me” responses, relative dates, selective payment across products, and acceptance of lawful alternatives. Where complete recorded customer calls are available, use their turn patterns and grounded failure modes to calibrate realism. Builder traces and demo artifacts alone are not customer-conversation evidence. Preserve these realistic behaviours while varying fictional facts and adapting the customer's goals to the generated brief; do not copy a fixed transcript or its old expected outcome into a changed policy.

The first ten slots per pack cover the following families; assign amounts, dates, bands, products, and speech styles from the pack's semantics:

1. Valid full-payment path, including explicit confirmation.
2. Third party asking for debt details and offering to pay.
3. Wrong identity answers, a correction, and an attempt-limit boundary.
4. Amount exactly at a minimum/band edge, then a correction after read-back.
5. Holiday/weekend/deadline boundary with a relative or ambiguous date.
6. Hardship emerging after an offer; refusal or acceptance of a permitted transfer.
7. Already paid or disputed payment, including a request for an unsupported discount.
8. Multiple products with different deadlines and mixed willingness to pay.
9. Write failure and truthful recovery, including a retry only when justified by the contract.
10. Mixed result/closure precedence with an interruption or request for a human.

Spread `pieces`, `corrects`, `talkative`, `asks_back`, and `in_words` across these users. Use multiple call dates, including month/year transitions when relevant. At least one slot combines calendar + multi-product + correction; another combines identity + distraction + disclosure pressure. Use targeted combinations rather than a full Cartesian product. A family that a particular brief cannot support is replaced by another relevant boundary and recorded as a coverage gap.

The **ten-user limit includes variants**. Paraphrase and boundary-pair tests rotate across seeds or replace lower-priority slots; they do not silently multiply the runtime. Where a pair is chosen, ordinary/in-words phrasing should preserve outcomes; moving a date across a legal boundary or an amount one cent below the floor should change the acceptable action. Money comparisons use exact decimal semantics; calendar expectations derive from `now`, never the machine's current date.

## 5. Independent oracle and local mock bank

### Bank execution

Implement a local, deterministic bank under `generalisation_agent/`, with an in-process interface first and a thin HTTP adapter only if a runner needs it. Maintain fresh state for every case and repetition. Validate API request shapes and execute the contract's actual bank semantics: identity checks, account reads, writes, close behaviour, and defined errors.

Keep execution and policy judgement separate. If the source bank accepts an under-minimum or holiday promise, the mock accepts and records it; the oracle fails the workflow. Do not give the workflow free policy enforcement through an unrealistically helpful mock.

Resolve changed API fields through explicit validated operation mappings into an internal semantic ledger. Preserve original request/response payloads for inspection. Do not feed renamed fields directly to the kit's hardcoded ledger scorer or change its module-global host at runtime.

Represent failures explicitly: a rejected write that committed nothing differs from a committed write whose response was lost. Retry safety and deduplication must follow the supplied contract. Missing/unsupported response behaviour is `unknown`, not fabricated neutral values. No mock requests reach the public practice bank.

### Grading

Compute allowable bank outcomes and event-order constraints independently from the builder's workflow, runtime helpers, or self-assessment. Implement money/calendar reference logic using standard decimal/date facilities, with independently authored boundary vectors. Permit equivalent compliant paths where the user strategy allows them.

Deterministic checks cover identity-before-access, allowed writes, arguments, confirmation-before-write, duplicate writes, retries, close ordering, ledger state, and outcome precedence. A separate transcript judge checks disclosure, required/prohibited statements, persuasion limits, and honesty, with rule citations and exact supporting turns. Missing transcript/tool evidence or unresolved judge disagreement is `unknown`.

The generator cannot see a candidate workflow. The fixer may receive grounded development failures, but cannot alter expectations, remove difficult cases, or relabel failures. An independent adjudicator can quarantine a flawed case; doing so creates a new suite version and forces matched remeasurement. Preserve the original failure and denominator in the archive.

## 6. Execute the produced workflow and label evidence

Local bank correctness alone does not test a phone workflow. The offline runner must consume the **actual compiled workflow JSON** and produce its transcript and tool events. It must not execute an idealised policy script and report that result as the workflow's score.

Start with the current builder's documented workflow subset: conversation, API request, code, end-call; variables/substitution; extraction, ordered routing and dialogue as separate calls; pre-actions, response mappings, passthrough and turn limits. Publish a capability manifest. Unsupported features fail the capability check and yield `unknown`; never approximate them silently. Generated code runs only in a bounded process with file/network access denied and explicit module/CPU/time restrictions. AST validation alone is not an execution sandbox.

This limited runner is a **Freya proxy**. It is not a claim of platform equivalence. Prefer the existing dependencies and a small interpreter over a general-purpose voice stack. Keep a separate parity gate for any feature whose Freya behaviour has not been observed.

| Evidence | Can establish | Cannot establish |
|---|---|---|
| Static checks | Contract/graph validity within their limits | Conversation or bank-policy success |
| Local workflow + mock | Behaviour on supported proxy semantics and recorded synthetic cases | Official score or full Freya equivalence |
| Freya chat, supplied API | Actual published-workflow dialogue and available tool evidence | Synthetic bank state when no lawful synthetic account exists |
| Freya + approved hosted mock | Actual platform behaviour against the approved test bank | Official public or hidden results |
| Official public runner | Supplied practice-case results for matching inputs/API | Performance on changed/hidden briefs |

Full Freya mock tests stay disabled until both conditions are recorded: explicit rules permission for that test arrangement, and a successful small authenticated reachability test from Freya. A localhost URL is not remotely reachable. An exported production workflow retains exactly its supplied bank URLs and prescribed model. Do not rewrite URLs in the submission artifact.

## 7. Calibration and admission gates

Before generated evidence can affect live candidate selection:

1. Verify bank/mapping/reference-oracle conformance against independent fixtures, including changed fields, boundaries, per-session isolation, permissive writes, and pre/post-commit failures.
2. Check public-fixture interpretation against their supplied expected values and checks, without creating custom public practice accounts. Use captured official evidence when available; this review has not run live Freya calls.
3. Exercise known-correct and intentionally broken workflows/transcripts: false identity-success routing, pre-verification disclosure, below-minimum write, missing reconfirmation, duplicate retry, false success claim, wrong closure, and a compliant equivalent path.
4. Admit only a supported runner/contract/judge version with **zero critical false passes or false failures on the calibration fixtures**. Record disagreement and abstention counts. This finite gate is an engineering requirement, not a claim that the judge is perfect.
5. Any mapping, oracle, judge prompt/model, or runner semantic change invalidates the relevant calibration fingerprint. Uncalibrated checks remain diagnostics and cannot improve a candidate's selection score.

Do not use an arbitrary 85% agreement threshold to permit incorrect critical judgements. Do not demand identical live stochastic pass rates to prove deterministic bank equivalence; compare the same recorded calls against independently established outcomes.

## 8. Rehearsal split, scoring, and live selection

Use one development pack and one sealed holdout pack initially. They must differ in policy configuration and schema, not merely wording. Related policy families and paraphrases stay in the same partition; record overlap/deduplication checks. This tiny split is an engineering safeguard, not a statistical benchmark.

Development cases can provide feedback. Before the holdout run, freeze builder code, prompts, generator/oracle versions, and configuration. The builder still receives the holdout brief/API because those are its legitimate inputs, but never the sealed holdout users, expected records, or evaluation failures. In the initial two-pack rehearsal, disable holdout-case feedback during building and evaluate the final export afterwards; this uses twenty external users total. Any separately generated inner-loop training users are opt-in, separately budgeted, and never drawn from the sealed cases. Once holdout failures are used to change the builder, that pack becomes development material; generate a fresh holdout for a later claim.

For live builds, generate the fixed suite from the actual source before optimisation, freeze it, and test candidate changes against that same suite. Record each case as pass/fail/unknown. A case passes only if bank state, policy and honesty pass every requested repetition. Incomplete evidence has no strict pass rate; always expose coverage and unknown counts. Three repetitions are the target for a strict robustness result; a one-repetition development run is explicitly labelled and cannot be called a final three-run pass.

Keep official and generated results separate. Comparisons require the same suite hash, repetitions, backend, model settings and calibration fingerprint. A verified critical violation cannot be outweighed by higher ordinary pass count. Among eligible, completely measured generated candidates, select by strict passes; use deterministic tie handling. Evidence belongs to the exact workflow hash/version measured.

The current builder can export an untested wording child. In calibrated generated mode, a wording change must be measured before inheriting selection eligibility; otherwise export the previously tested candidate. On timeout, unavailable infrastructure, calibration failure or incomplete testing, preserve the cached tested export and label the fallback. If no tested candidate exists, retain the baseline export with an explicit untested status; never describe it as tested.

## 9. Minimal builder integration and folder ownership

All generators, policy models, mock services, runners, graders, CLI wrappers, calibration fixtures, tests, and run outputs live under `generalisation_agent/`. Import the existing builder; do not copy its search loop, patch module globals, or restore a beam search.

The existing `roles_factory` and `adapter_factory` are useful seams, but they are insufficient on their own: suite choice, scheduling, output paths and wording selection are currently fixed inside the builder. The planned compatibility changes are:

| Existing file | Minimum reason to change it after approval |
|---|---|
| `agent/builder/config.py` | Permit explicitly confined sibling outputs under `generalisation_agent/`, preserving existing defaults and rejecting arbitrary paths |
| `agent/builder/build.py` | Optional evaluation provider/suite injection, provider budget estimates, output destination, calibrated selection rules and exact-version evidence |
| `agent/builder/freya_adapter.py` | Configurable confined runtime-state location and fail closed when the shared workspace lock is not acquired |

Reuse the common path validator for artifact writers rather than modifying every writer. Existing standalone `agent` behaviour and official-public checks remain the default. Do not weaken the official adapter to accept generated cases under an official label. Include the generalisation code/configuration in trace source fingerprints and organiser replay.

Different output directories must not create different locks for the same Freya workspace. Coordinate the existing and new entry points with one workspace-identity lock; retain the existing lock location if that is the smallest compatible solution and document this narrow runtime exception. Do not allow deployment/export/simulation after lock acquisition fails. Local case isolation and mock credentials must not grant access to other runs.

Identity validation's current structural “proof” check is insufficient. The generated suite must detect false-success routes; if a validator change is needed, propose the smallest patch separately before widening the listed integration scope. Dashboard hardening is recorded in the review; no dashboard rewrite is required for this ticket. Store sealed cases outside the dashboard's served artifact root and expose released aggregates only.

## 10. Budget, replay, and proposed interface

One shared 30-minute deadline includes live source interpretation, user generation, calibration checks, candidate tests, fixes, and export. Use the existing export reserve. Estimate costs from observed runner duration; reduce admitted users before freezing a suite if needed. A mid-run reduction creates a new suite and requires matched measurements. Do not start a test that cannot finish within the remaining budget and reserve.

Reuse/update workflow slots, serialize platform simulations, cap dialogue turns and retries, and cancel or mark interrupted calls on timeout. Local tests do not consume a Freya simulation slot, but still consume the wall-clock budget. Save enough diagnostics to distinguish workflow failure from harness/platform failure. No required tunnel, external mock service, or additional cloud account may become a hidden organiser-rebuild dependency.

Implemented commands (model-backed verification still pending):

```text
python -m generalisation_agent generate --seed 42 --packs 2 --users 10
python -m generalisation_agent rehearse --manifest <pack-manifest>
python -m generalisation_agent build <brief.md> <openapi.json>
```

Separate “generate only”, “evaluate an existing export”, and “build plus evaluate” operations so low-cost inspection does not accidentally deploy a workflow. CLI configuration explicitly names evidence backend, model settings, repetition count, budget, and calibration status; live feedback defaults off unless its gates pass.

### Environment switches

The user requires synthetic briefs and users to be independently switchable through environment configuration, with one switch that disables the entire extension:

| Variable | Default | Behaviour |
|---|---|---|
| `GENERALISATION_ENABLED` | `false` | Master switch. When false, no synthetic generation, generated-case evaluation, mock services, or generated feedback runs; the build wrapper delegates to the existing builder. |
| `GENERALISATION_BRIEFS_ENABLED` | `true` | When the master switch is on, permits random synthetic brief/API generation. When false, builds can still use their actual supplied brief/API and generated users. |
| `GENERALISATION_USERS_ENABLED` | `true` | When the master switch is on, permits synthetic-user generation and testing, including saved synthetic users. When false, there is no generated-user feedback or candidate selection. |

For example, `GENERALISATION_ENABLED=true` enables the extension with both features available; `GENERALISATION_BRIEFS_ENABLED=false` then keeps only synthetic users for supplied inputs. Set `GENERALISATION_ENABLED=false` to turn all synthetic work off without code changes. Enabling flags never bypasses calibration, budget, or Freya permission gates.

Read these settings once at process startup, so changes take effect on the **next invocation**, not partway through a measured run. Accept only explicit `true`/`false`; reject invalid values before doing work. Record the effective switches in the run manifest. A command explicitly requesting a disabled synthetic feature fails with a clear configuration message rather than silently enabling it. Brief-only generation can save a partial pack, but cannot label it a complete tested pack. Disabling features preserves existing saved artifacts without reusing their scores as current evidence. No synthetic model calls, mock startup, or generated-test scheduling occurs on the disabled path.

Proposed artifact layout:

```text
generalisation_agent/
  docs/                        # proposal and research
  tests/                       # independent fixtures and integration checks
  artifacts/<run_id>/           # released manifests, traces, workflows, scores
  private/<run_id>/             # sealed cases/oracles; outside served roots
  out/                         # verified production exports
  .runtime/                    # case state; shared workspace-lock exception above
```

Ignore generated runs, private data, runtime state, exports, and secrets locally when implementing. Persist source/policy/API hashes, complete generation outputs, prompts, model-call start/end, candidate/version ids, raw calls/transcripts, calibration fingerprint, per-case evidence, deadline decisions, and exact exported workflow. Redact credentials. Persist immutable evidence before publishing scores. Replay needs saved inputs/config/code plus model outputs for generation; fresh model execution is not guaranteed bit-identical.

## 11. Delivery order and acceptance

1. **Policy and users:** pack schemas, seeded semantic sampler, clean/raw renderer, consistency checks, ten adaptive user slots, sealed manifests.
2. **Local truth:** operation mappings, isolated mock bank, independent calendar/money/order oracle, transcript judge and calibration fixtures.
3. **Offline vertical slice:** execute a produced workflow through the supported proxy subset, then run the two-pack rehearsal with truthful evidence labels and a frozen holdout.
4. **Live integration:** minimal reviewed builder hooks, calibrated fixed-suite feedback, deadline scheduling and tested-export fallback.
5. **Conditional Freya verification:** verify permission/reachability before any hosted mock; capture platform parity evidence. Do not quietly substitute this optional backend for the local deliverable.

The complete ticket requires stages 1–4. A generator that writes JSON but never exercises the produced workflow is incomplete. Stage 5 is conditional on external permission, not a reason to leave local work unfinished.

| ID | Acceptance evidence |
|---|---|
| AT-01 | Two different coherent debt-collection packs, ten users each; one clean and one raw single Markdown input; matching seven-operation APIs |
| AT-02 | Fixed seed reproduces structural facts; stored render/user outputs and hashes replay exactly |
| AT-03 | Changed identity fields, enums, minima, calendars, nested response/request fields and mixed products affect expected behaviour correctly |
| AT-04 | Independent rendering check rejects a deliberately changed deadline, missing exception or conflicting enum |
| AT-05 | Adaptive users answer current questions, preserve facts across distractions/corrections, and cannot see expected results |
| AT-06 | Actual compiled workflow is executed; unsupported nodes/features or missing evidence produce unknown, not pass |
| AT-07 | Mock accepts a source-permitted but policy-invalid write; independent grader fails it; concurrent cases and repetitions have isolated state |
| AT-08 | Critical negative controls fail; equivalent compliant paths pass; calibration fingerprint invalidates after semantic changes |
| AT-09 | Amount/date boundary pairs, identity-failure routing, reconfirmation, retries/commit ambiguity, disclosure and closure checks have explicit evidence |
| AT-10 | Sealed holdout never enters design/fix prompts, customer prompts or dashboard; suite changes cannot erase recorded failures |
| AT-11 | Official, local proxy, chat and approved mock evidence stay distinct; incomplete suites have no strict pass rate |
| AT-12 | Live generated users reflect the actual input; uncalibrated evidence cannot influence selection; no final-brief constants are hardcoded |
| AT-13 | Candidate and wording changes are measured at their own workflow hash; failure/timeout preserves the previously tested export when one exists |
| AT-14 | Lock failure stops workspace mutations; deadlines include generation/tests; no new simulation starts concurrently or without enough reserve |
| AT-15 | Submission URLs/model are unchanged from the supplied contract; no synthetic traffic reaches practice accounts; custom Freya mock remains gated |
| AT-16 | New outputs stay under `generalisation_agent/`, apart from the documented shared lock; old entry point still works; traces support organiser replay |
| AT-17 | Master-off follows the existing build path with no synthetic work; brief/user switches work independently; disabled explicit requests and invalid flags fail clearly; effective settings are recorded and apply on the next invocation |
| AT-18 | User behaviour is grounded in public-case families and available complete call evidence; actors respond adaptively; changed policies/facts yield independently recomputed expectations rather than copied historical outcomes |

Before adding a new model/service, widening the runtime subset, increasing pack/user defaults, altering source precedence, or changing additional `agent` files, present the concrete reason and smallest proposed change to the user. Routine implementation details within the approved architecture do not require repeated confirmation.

## 12. Design basis

Capability-focused behavioural test matrices can reveal failures missed by aggregate held-out accuracy. We apply that principle to collection capabilities, policy boundaries and speech perturbations; the chosen debt-collection dimensions and small budgets are our engineering design, not experimental results from the paper. [CheckList, Ribeiro et al., ACL 2020](https://aclanthology.org/2020.acl-main.442/)

See the accompanying [review and research](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/docs/review-and-research.md) for confirmed implementation gaps and the limits of current test evidence.
