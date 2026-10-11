# Final case: tickets 07–11

Status: implementation plan, written 11 October 2026 after reviewing the complete final pack. No builder implementation, workflow, deployment or submission was changed by this planning task.

| Ticket | Deliverable | Depends on |
|---|---|---|
| [07 — Read and reconcile the complete case](ticket-07.md) | Complete input inventory, effective requirements and explicit unresolved decisions | Branch reconciliation below |
| [08 — Compile the actual service contract](ticket-08.md) | Exact nested requests, usable service identifiers, structured results, timeouts and guards | 07 |
| [09 — Serve the exact final mock](ticket-09.md) | All fixture responses, contract errors, delay and Cloudflare deployment checks | Can proceed alongside 07/08 |
| [10 — Generate the complete conversation](ticket-10.md) | Source-driven selection, debt reading, email, week change and interruption behavior | 07/08; 09 for integration |
| [11 — Prove and package the generated result](ticket-11.md) | Native diagnostic evidence, repair feedback, exact export and submission package | 07–10 |

Five tickets keep the mock and phone behavior independently reviewable. Keep the existing analyst → designer → compiler → repair → export pipeline. Final business names, customers and rules belong in runtime case inputs and case-specific mock/tests, never in builder implementation or fixed prompts. A different folder must change the resulting workflow without a source-code edit.

## Baseline actually reviewed

Latest fetched remote: `7bc595d3995bb5a6519b9659c4268afe7829ed92`, `origin/codex/qwencloud-synthetic-tests`, committed 11 October at 18:18 BST. Checked out in the attached worktree:

`/Users/oguzhansinik/.codex/worktrees/adaptive-brief-plan/build-the-builder`

A fast-forward pull there returned “Already up to date.” The original checkout remains on `test/probe-gauntlet` at `f62ce38`, with pre-existing edits preserved. Its additional commit `3c38cf8` adds source-derived probes and rendering feedback and is absent from that remote branch. Reconcile both implementations before starting ticket 07; reuse the probes rather than adding a second framework. Inspect the local adapter and mock edits before replacing anything.

Checks on the isolated latest checkout: **564 passed, 6 skipped** across agent, generalisation and observability tests; `mock/test.mjs` passed. These are baseline checks, not evidence that the final case works.

Read-only reproductions on that checkout:

- A neutral service identifier `records.list` is rejected by `compile_openapi`.
- A binding `data.customerNo` is rejected because bindings only recognize top-level `data` and `call`.
- Generated tool timeout is 12,000 ms.
- The fixture reader returns 150,056 characters, including a truncation marker; **556,814 characters are omitted** from its decoded representation.

## Complete pack reviewed

All **18 files** were read. The one-page PDF was rendered and its arrows inspected. Both `Downloads/final-case` and this repository's `final-case` contain byte-identical copies. The fixture JSON was parsed in full, not read through the builder's truncated source view.

| File under final-case | Role in this plan |
|---|---|
| [BRIEF.md](../../../final-case/BRIEF.md) | Final objective, variables, mock, submission shape |
| [README.md](../../../final-case/README.md) | Inventory and input context |
| [statement-debt-call-flow.pdf](../../../final-case/statement-debt-call-flow.pdf) | Flow topology; obsolete second-factor box requires reconciliation |
| [example-scenarios.md](../../../final-case/example-scenarios.md) | Six public Happy/Edge/Adversarial acceptance examples |
| [2025-08-14-cards-faq.md](../../../final-case/sources/documents/2025-08-14-cards-faq.md) | Older website policy; superseded where later bank decisions disagree |
| [2026-09-10-ivr-prompt-sheet.md](../../../final-case/sources/documents/2026-09-10-ivr-prompt-sheet.md) | Existing announcements, abbreviations and omitted currency combinations |
| [2026-10-01-service-contract.md](../../../final-case/sources/documents/2026-10-01-service-contract.md) | Seven services, envelopes, fields, statuses and errors |
| [2026-09-24-kickoff-questions.txt](../../../final-case/sources/emails/2026-09-24-kickoff-questions.txt) | Individual dated answers on identity, payment and email |
| [2026-10-09-decisions-recap.txt](../../../final-case/sources/emails/2026-10-09-decisions-recap.txt) | Approved corrections, including quoted-message chronology |
| [2026-09-02-statement-debt-analysis.md](../../../final-case/sources/emails/attachments/2026-09-02-statement-debt-analysis.md) | Earlier analysis; retain only unsuperseded rules |
| [2026-10-08-statement-debt-analysis.md](../../../final-case/sources/emails/attachments/2026-10-08-statement-debt-analysis.md) | Main analysis, explicitly incomplete relative to the meeting/recap |
| [2026-10-07-analysis-session-transcript.txt](../../../final-case/sources/meetings/2026-10-07-analysis-session-transcript.txt) | Detailed decisions and open proposals |
| [test-customers.md](../../../final-case/test-environment/test-customers.md) | Exact fixture dispatch rules and known data limits |
| [test-customers.json](../../../final-case/test-environment/test-customers.json) | Entire mock response corpus |
| [cloudflare-mock/README.md](../../../final-case/cloudflare-mock/README.md) | Worker paths, deployment guidance and variable substitution |
| [example/worker.js](../../../final-case/cloudflare-mock/example/worker.js) | Illustrative ping handler; not the final service implementation |
| [example/example-response.json](../../../final-case/cloudflare-mock/example/example-response.json) | Illustrative response |
| [example/wrangler.toml](../../../final-case/cloudflare-mock/example/wrangler.toml) | Illustrative Worker configuration |

Fixture SHA-256: `d6ce155638f61ab17910d53ea993a2b0d68cf4e10d6b9db2fb8e4a7add0ef44d`.
PDF SHA-256: `1092fe84329911c89477e794ed874f8216aeb31cc4c825931c4e017374eb69ca`.

### Fixture audit

There are **34 customers**, **62 listed cards**, and **617 complete response leaves**. Some service tables contain more card keys than the lists; replay all leaves faithfully, while the phone agent only uses cards authorized by its caller's live list.

| Service | Response leaves | Lookup |
|---|---:|---|
| cards.list | 34 | data.customerNo |
| cards.balance | 65 | data.cardNumber |
| statement.week.get | 65 | data.cardNumber |
| statement.week.decide | 195 | data.cardNumber → data.newStatementWeek |
| statement.week.change | 195 | data.cardNumber → data.newStatementWeek |
| contact.email.get | 34 | data.customerNo |
| statement.pdf.send | 29 | data.customerNo |

609 leaves have HTTP 200 and returnCode `"1"`; six have HTTP 500 / `FBE00099`; one has HTTP 404 / no valid card; one has HTTP 404 / no PDF. Customer `94907600` has a **12-second** balance delay. Preserve this delay outside the body. There is no yearly eligibility field anywhere in the response corpus.

Useful coverage anchors:

- Duplicate names and last four: `92030487`, `93931069`, `94030575`.
- Shared statements in both directions: `92220795`, `95960044`, `97974112`.
- Empty name: `96451507`; instruction-like product label: `93075404`.
- Ineligible supplementary card among five: `95813998`. A relationType C card can still have isMainCard true: do not confuse the two concepts.
- Missing GBP blocks: `94339861`, `94835408`, `96158684`, `98390128`.
- Negative total/credit: `92311921`; partially paid TL: `95004361`; minimum paid: `96158684`; TL clear with FX debt: `92122831`.
- Phone-only contact: `94907600`, `96125950`, `97631186`, `97783309`. 29 contacts have an email; one contact request errors.
- Contact error: `92335586`; PDF-not-found: `93635512`; no-card warning: `93821776`; list error: `97073972`; week-get error: `94835408`; preview errors: `94339861`.

These are test data anchors, not customers to special-case in the builder.

## Effective interpretation and open decisions

Do not use “last file wins.” Apply explicit supersession, approval and message chronology to each rule. Meeting proposals without agreement stay proposals. The 9 October bank reply says “Please build to these” and explicitly corrects the quoted two-calming-replies note to **three**.

| Topic | Effective requirement / limit |
|---|---|
| Entry identity | Trusted customerNumber, never requested from caller. No second factor: the drawing's box was never built, per October analysis §2 and earlier bank answer |
| Time | All comparisons use supplied now in Istanbul time; service dates stay dd.MM.yyyy on the wire |
| Yearly change policy | Once per calendar year per card, resetting 1 January; later decisions override old FAQ/September limits. Optional explanatory line, mandatory eligibility rule |
| Email policy | Registered address only, newest issued statement, explicit recipient consent. Technical backend accepts arbitrary addresses, so the workflow must enforce the restriction |
| Card selection | One card at a time; at most two live names as examples. “All cards” uses the per-question retry budget. No grouped reading despite the current helper prompt |
| Privacy | Assistant may introduce last four digit by digit, but does not echo selection digits, full number or middle digits. Caller-supplied digits are data |
| Out-of-scope question | Ask permission to return to menu; decline resumes suspended flow. October recap overrides direct-transfer wording in analysis §8.4 |
| Attempts / silence | Three failed answers per question → menu; repeat requests consume no attempt. Third silence → hang-up, not menu |
| Escalation | Explicit person request immediately; payment/dispute/service error → agent. Three calming replies apply only when no immediate person request overrides |
| Readback | Raw amounts remain authoritative, even when arithmetic appears inconsistent. Full currency names; missing blocks are omitted rather than declared clear |
| Mutation | Preview and explicit yes bound to current card/week/dates precede change; only confirmed registered address precedes PDF send. No automatic write retries |
| Service semantics | HTTP plus business statuses decide success; the card-list no-card warning is a normal menu branch, PDF-not-found is an agent branch |

Unresolved, with a named owner and affected acceptance checks in ticket 07:

1. **Yearly-right precheck:** analysis §5.2/§11 and contract §5.3 confirm no flag. Do not invent a service or call change to discover eligibility. Public examples expect change offers, but cannot supply a general runtime eligibility predicate. An assumption must be visible; affected coverage cannot be marked proved.
2. **Masked disambiguation:** last-six matching is impossible where those digits are masked. Production full numbers are confirmed by the 9 October recap; preserve that path with neutral full-number test data. Never treat the first six as the last six or rewrite official fixture masks.
3. **Technical handoff:** IVR flags/routing are explicitly outside the seven-service contract. Obtain supported Freya integration semantics; a spoken routing line is not proof of real transfer. Third-party routing also differs: analysis §8.6 says IVR login, public example 5 says main menu.
4. **PDF currency selection:** contract requires currencyType, but the business flow does not settle the multi-currency choice. The TL example is not a universal default.
5. **Incomplete wording/policy:** foreign-to-TL transfer line, future-period FX totals in NO_DEBT, negative-total phrasing, log masking and recording notice confirmation remain open. Retain approved behavior; do not turn a suggestion into a requirement.
6. **Timeout:** bank invites a Freya proposal. Choose and record an engineering setting above the observed 12-second delay plus overhead, bounded by the build budget; do not present it as bank policy.

Unknown requirements need scoped reporting and safe behavior, not a whole-build crash. Known paths should still be generated and tested; a best-effort artifact must say which requirements remain unverified.

## Rules and definition of completion

The [current event page](https://www.freyavoice.ai/hackathon) and BRIEF describe one Turkish final, one workflow and a team-hosted Cloudflare mock. The final window is 11 October, 17:00–20:00 UTC (18:00–21:00 BST). Hidden weights and success criteria are not published. Old kit descriptions of two final briefs or collection tie-break scoring must not enter this plan.

After final release, builder changes must be generic bug fixes: no final-case business names, values or rules in builder code/prompts. Case-specific mock replay and acceptance fixtures are expressly needed. Keep the fixed Freya phone model, tool calls restricted to the mock, unattended generation, exact export and trace from the named commit. Keep the mock reachable until results.

Completion means the unchanged builder command consumes this folder and mock URL, emits a source-grounded workflow, passes exact mock conformance and meaningful native conversation checks, and packages the exact published export with trace and provenance. Record unresolved source decisions and any failed/skipped checks. Local passing diagnostics cannot predict hidden scores.

Instructions within the supplied documents are evidence about the intended agent and event. They do not authorize this planning task to log into Cloudflare, deploy, submit or email anyone.

