# Code review and research for Ticket 2

Reviewed 11 October 2026 at commit `48ac224d78bf00fb9ab06df0f9a8c69ef49fc355`. This review changes documentation only. The untracked `tools/smoke_test.py` was intentionally excluded and left alone.

## What the repository does

The builder reads brief documents and an OpenAPI, extracts source-backed requirements, designs and compiles a Freya workflow, validates it, publishes it, caches the actual export, and runs a bounded fix loop when a recognised public suite is available. Immutable candidates, source snapshots, model payloads, version checks and durable traces support inspection and recovery. The local observability server reads those artifacts through a three-panel browser UI.

Unknown briefs currently have no measured customer loop: `public_suite` only admits recognised public inputs/API, and the Freya adapter rejects generated evidence. The scorer's `generated` label is a representation seam, not a working synthetic runner. The code deliberately exports compiler-fixed designs when it cannot evaluate them.

Review coverage included the Python builder modules, prompts/runtime/contracts, Freya adapter and root client, public runner/scorer and test fixtures, example builder/workflow, configuration/dependency files, observability server/store/diff/frontend and tests, repository/readme/runtime/API documents, public brief/API fixtures, and Tickets 1–3. Ignored historical run folders were context only, not fresh proof of present behaviour. No credentials or real customer records were inspected.

## Must fix before depending on the affected guarantees

### P1 — Static identity “proof” admits a failure route

[validation.py:106](/Users/oguzhansinik/Downloads/build-the-builder/agent/builder/validation.py:106) treats a comparison on a non-spoken variable as proof without checking that the value means successful verification or is derived from the appropriate tool result.

A focused probe changed the test fixture's route into account access to `all_verified equals "false"` (and separately `"False"`). Both variants returned `valid=True` with no errors. This demonstrates a static-check gap; it does not establish that a currently exported workflow actually uses that bad route.

Require success semantics/dataflow rather than any non-user comparison, and include this faulty route as a negative generated test. Until strengthened, do not describe static validation as proving identity safety.

### P1 — A failed workspace lock still enters the protected work

[freya_adapter.py:155](/Users/oguzhansinik/Downloads/build-the-builder/agent/builder/freya_adapter.py:155) logs unsuccessful lock acquisition and then yields the adapter anyway. A focused probe substituted a lock context returning `False`; the workspace body still executed.

Once the waiting build's budget is exhausted, it can still enter code that shares workflow slots and state with the lock holder. Individual deadline checks do not make that a mutually exclusive critical section. Stop protected work on lock failure, and use one lock identity across old/new entry points even when artifacts move to the sibling directory.

### P1 — Artifact readers can follow symlinks outside their configured root

[store.py:110](/Users/oguzhansinik/Downloads/build-the-builder/observability/store.py:110) checks that a run path is a directory but does not resolve/confine it to the configured artifacts root. [Candidate reads](/Users/oguzhansinik/Downloads/build-the-builder/observability/store.py:379) and [model-call reads](/Users/oguzhansinik/Downloads/build-the-builder/observability/store.py:618) access files without the artifact endpoint's confinement check. Even that endpoint confines to the resolved run directory, which itself may be outside the configured root.

Two temporary-directory probes demonstrated this: a symlinked run exposed an external synthetic report sentinel; a symlinked candidate directory exposed an external synthetic workflow sentinel. No real private data was used. The server is local by default, which limits exposure; it does not make the storage boundary reliable for a sealed holdout.

Resolve and confine all run/candidate/model-call paths consistently, rejecting traversal and escaping symlinks. Until then, keep sealed material outside all served roots rather than relying on folder names alone. This dashboard fix is separate scope from the initial harness.

### P2 — Raw strings can become HTML in the dashboard

[index.html:396](/Users/oguzhansinik/Downloads/build-the-builder/observability/static/index.html:396) inserts any string starting with `<` as HTML. Callers pass recorded fields including run errors, status, model and span purpose. The helper cannot distinguish intentional UI markup from artifact content.

Source inspection confirms the injection path; this review did not run an exploit in a browser. Escape ordinary values and use explicit trusted UI fragments when markup is needed. This matters more when future synthetic/model-generated artifacts are displayed.

## Ticket alignment and implementation cautions

| Area | Current evidence and implication |
|---|---|
| Ticket 1 | `agent/docs/acceptance-status.md` explicitly drops sibling/beam/relative-ranking modes. Use the implemented single fix chain. Do not reintroduce obsolete architecture merely because the original ticket contains it. |
| Ticket 2 | The original proposal focuses on generated customers for an existing brief and defers novel brief packs. The rewrite makes coherent brief/API generation a first-class offline deliverable, plus generated users for actual live inputs. |
| Ticket 3 | The implemented stdlib server and single HTML page already supply the requested layout. No React/FastAPI migration is needed for this task. Backend cycle warnings do not by themselves protect recursive frontend layout; async inspector selection also deserves a separate robustness pass. These are source-inspection concerns, not reproduced regressions here. |
| Persona contract | `tools/run_cases.py:persona_for` expects identity/variables plus id, brief, family, title, level and checks. Adapt a complete generated-case schema; the old ticket's abbreviated shape is insufficient. Do not expose answer keys to the actor. |
| Bank/scoring | `tools/score.py` captures `FREYA_BANK_HOST` at import and hardcodes ledger fields such as amount/date/product_id. Use explicit mapping and a separate generated runner; changing an environment variable after import or passing changed payloads through the existing scorer is unreliable. |
| Unknown briefs | `FreyaAdapter.evaluate` accepts official-public suites only. `Builder` chooses its suite internally. A real integration needs an explicit provider seam, not an evidence-label switch. |
| File ownership | `writable()` confines outputs to `agent/`; build/export/runtime paths also use that directory. Zero compatibility changes cannot satisfy the requested sibling output boundary. The new ticket lists the smallest planned changes and a narrow shared-lock exception. |
| Dates and money | Reusing the workflow's own date helper as its oracle risks shared mistakes. Use independently checked reference vectors and exact decimal comparisons. Relative dates are anchored to each case's `now`. |
| Baseline fixtures | The existing unfamiliar-policy fixture is useful robustness material but has four operations. It is not a representative seven-operation final-style pack. |
| Candidate evidence | The current builder explicitly flags untested wording children. Generated live selection must evaluate the exported child or retain its tested parent, rather than attaching the parent's score to new dialogue. |
| Judge disputes | A fixer cannot be allowed to delete a failing case or rewrite its expectations. Independent quarantine creates a new version, preserves the original result, and requires matched remeasurement. |
| Budget | Generation, calibration and local calls also take time. Share the existing deadline/reserve; do not add a second 30-minute allowance. Two packs with ten users each are the starting proposal, not a large benchmark. |

## Why the old mock-bank plan needs revision

The original ticket presumes an external mock-bank test copy is allowed so long as the final export points to the supplied bank. The official rules do not state that exception. The FAQ does not let teams register arbitrary practice customers. Optional public hosting also introduces reachability and organiser-rebuild dependencies.

The safe engineering response is a self-contained local mock/proxy first, with clearly labelled evidence; use Freya chat only within supplied API permissions, and enable full custom-bank platform tests after explicit rules and reachability verification. Unsupported mock responses must abstain, rather than returning invented values that conceal workflow errors. This is a design consequence of the verified rules, not a claim that Freya has prohibited every possible local rehearsal.

A permissive bank is essential: the official evaluator says policy-invalid promises may still be accepted. A mock that enforces those policies for the assistant produces false confidence. Separate bank semantics from policy/ledger/transcript judgement. [Evaluation](https://www.freyavoice.ai/hackathon#evaluation)

## Research and authoritative sources

Official sections were read through the in-app browser because the site's content was not retrievable through the web text opener. Inspection established:

- [Rules](https://www.freyavoice.ai/hackathon#rules): supplied API restriction, fixed phone model, 30-minute inclusive budget, workflow/concurrency limits, synthetic data, and general post-release changes.
- [FAQ](https://www.freyavoice.ai/hackathon#faq): practice-only customer ids, no hidden practice customers, changed final fields/enums, and chat as a no-practice check.
- [Evaluation](https://www.freyavoice.ai/hackathon#evaluation): bank-state plus policy plus honesty, permissive backend, three-run requirement, and diverse interaction styles.
- [Submission](https://www.freyavoice.ai/hackathon#submit): actual exports, trace/code correspondence, organiser rebuild, and lower-score removal risk.
- [Overview](https://www.freyavoice.ai/hackathon): two final input formats and the published 11 October release/submission schedule.

[CheckList, Ribeiro et al., ACL 2020](https://aclanthology.org/2020.acl-main.442/) motivates capability-oriented behavioural testing instead of relying solely on aggregate held-out accuracy. Our application is a small coverage matrix over debt-collection capabilities and adversarial speech/policy boundaries. It does not require a new testing-framework dependency or establish a success rate for this project.

No source promises that our generated policies will match the hidden briefs. We can test plausible variation and measure observed failures; hidden-test performance remains unknown.

## Verification and limits

The existing suites completed successfully:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest agent/tests observability/tests -q -p no:cacheprovider
112 passed in 2.34s
```

These are unit/integration tests with fake controllers and local fixtures. They establish current test-suite health, not collection-policy correctness on Freya. Focused additional probes reproduced the identity-proof, failed-lock, and two symlink-confinement gaps described above. Probe state used temporary synthetic fixtures and was removed.

No model generation, live phone workflow, hosted mock, public bank test, or organiser rebuild was run as part of this review. Existing traces were not substituted for fresh evidence. No executable code, original ticket, or untracked smoke-test file was changed. The rewritten proposal is ready for the user's implementation decision.
