# TICKET-02 — Generated practice customers for briefs that have none

**Status:** Specification, ready to implement on go-ahead
**Depends on:** the fix loop in `agent/builder/build.py` (one patch format, one child per round)
**Replaces:** the earlier Ticket 2 (scenario splits, sealed holdouts, leakage firewall, five-arm study). That design is dropped; section 12 says why.
**Deliverable:** on a brief the builder has never seen, the same measure-and-improve loop that runs on Briefs A and B, driven by customers the builder generates from that brief and a mock bank it controls.

---

## 1. Why

The builder improves an agent only where it can simulate it: one fix call reads the failed calls,
one child is simulated, each fix is kept or blamed. On Briefs A and B that works because the kit
ships 13 practice customers and a practice bank.

The scored briefs have neither. The hackathon FAQ says so directly:

- "Do the hidden briefs come with practice cases? No. Each comes with its tool API file only."
- "Can my builder open practice customers of its own? No. The practice bank serves the 13 cases
  PUB-01 to PUB-13 only."

So on the two briefs that decide the ranking the build stops after compiler fixes, and the agent is
exported untested. Every live build so far shows what that costs: first designs score 6–7 of 10,
and the failures are routing and state bugs that a single simulated call exposes at once.

The FAQ rules out customers at *the practice bank*. It does not rule out a bank the builder runs
itself. This ticket specifies that.

## 2. What is established, and what each fact allows

| Fact | Source | Consequence |
|---|---|---|
| A practice case file holds the whole fixture: call variables, identity answers, products, the customer's script, the expected bank records and the judge's checks | `public-test-set.json` | A generated case in the same shape needs no new format |
| The kit scorer takes the bank host from `FREYA_BANK_HOST` and talks to three practice routes: open a session, read a ledger, and the tool routes the agent calls | `tools/score.py`, `tools/run_cases.py` | A mock that serves those routes works with the kit's unmodified runner |
| Personas and simulations are an open API; the kit creates its own for every run | `docs/api.md`, `freya.py` | Generated customers can be simulated by Freya's own customer model and judge |
| An `api_call` tool's URL is a plain field of the workflow | `docs/tools-and-code.md` | A test copy of the agent can call a different host than the exported agent |
| "The phone agent may call only the tool API from the kit. A call to any other service fails the case." | Hackathon rules | Binds the *exported* agent. The test copy is never exported (section 7) |
| "Do not probe or load-test the platform." One simulation at a time per workspace | Rules, README | Same simulation budget as today: at most four per build, serialised |
| 30 minutes per build, including any test it runs | README | Generation must fit beside the design call (section 8) |
| Nothing from a hidden brief may be written into the builder | Rules | Cases, fixtures and bank behaviour are run artifacts, generated at build time, never code |
| The organisers rerun the top builders themselves | Submit page | The mock must be optional: without it the build behaves exactly as today |

Not established, and to be settled in milestone 1: whether Freya's simulation workers can reach an
arbitrary public HTTPS host, and how closely a mock can reproduce the practice bank's verdicts.

## 3. Design in one picture

```
brief + tool API ──► case generator ──► cases (kit case shape) ─┐
        │                                                        ├─► register on mock bank
        └──────────► designer ──► workflow source                │
                                    │                            │
                 compile with mock URLs ──► test copy on Freya ──┤
                 compile with real URLs ──► exported agent       │
                                                                 ▼
                              kit runner (run_once) with FREYA_BANK_HOST = mock
                                                                 │
                         verdicts + call records ──► the existing fix loop
```

Four parts are new: the mock bank, the case generator, the test compile, and suite selection.
Scoring, the fix call, keep/blame, wording commits and export are unchanged.

## 4. The mock bank

A small stateless-per-session HTTP service. It contains no bank policy and nothing from any brief.

**Routes**

| Route | Behaviour |
|---|---|
| `POST /v1/practice/suites` | The builder registers a suite: the compiled tool contract, the `bank_model` (below) and the generated cases. Keyed by the team key header, as the kit's bank is |
| `POST /v1/practice/sessions` `{"case": id}` | Opens a fresh customer for that case and returns `{"variables": {...}}` with a new `customer_id`; identical to the kit route, so `run_once` is unchanged |
| `GET /v1/practice/ledger/{customer_id}` | Returns `outcome`, `reason`, `promises`, `notes`, `callbacks`, `transfers` and `calls` (every tool call with its body and result), the shape `score_ledger` reads |
| one route per operation in the supplied OpenAPI | Validates the body against the contract (required fields, types, enums), records the call, answers from the session's fixture |

**Behaviour comes from data.** The OpenAPI gives shapes but not meaning, so the generator also
emits a `bank_model`: a small JSON object that names, for this tool API, which request field carries
the security question and which the answer, which response fields report "this answer was right",
"all questions passed" and "attempts left", how many wrong answers end the check, which operations
require a verified session, which is the single closing operation, and which operations write the
records the ledger lists. The mock interprets that model generically:

- An identity answer is compared with the fixture after normalising case, spaces and date format.
- An operation marked as needing verification is refused with an error until the session is verified.
- A write is recorded once per product; a second write for the same product is refused.
- A case may declare faults ("the first call of operation X fails"); the mock returns the contract's
  error shape for them. This is how the tool-failure family is exercised.
- Nothing is accepted after the closing operation.
- A response field whose meaning the model does not cover is returned as a neutral value of its
  schema type, and the suite is marked `bank_model_incomplete` in the trace.

**Hosting.** It must be reachable from Freya over public HTTPS. Recommended: a Modal web endpoint,
since the team already runs its builder model there; session state in a Modal `Dict` with a one-hour
expiry. Fallback: a tunnel from the build machine. The builder reads the address from
`GEN_BANK_HOST`; **if it is unset or the health check fails, generated testing is skipped and the
build proceeds exactly as it does today.** That is also what happens in an organiser's rerun without
our endpoint, and the trace says so.

## 5. The case generator

One model call, started as soon as the build begins and run beside the rule extraction and design
calls. It sees the brief and the tool contract. **It never sees the workflow**, so a case cannot be
shaped by what the agent happens to do.

**Output**

- `bank_model` (section 4).
- `cases`: `GEN_CASE_COUNT` of them (default 10), each in the kit's case shape:
  `id`, `family`, `variables` (the call variables the brief lists, including `now`), `identity`,
  `products`, `script`, `expected` (the closing outcome and reason and every record the bank must
  hold), `checks` (what the judge reads in the transcript), optional `faults`, and `rule_refs`
  (the brief lines the expectation rests on).

**Coverage the prompt asks for,** all taken from the brief in front of it:

- one case per row of the brief's outcome table, as far as the count allows;
- a clean promise; the identity check failing; someone else answering;
- a date on each side of the brief's deadline, and one on a non-business day;
- an amount on each side of the brief's lower limit;
- a write that fails once;
- with several products allowed, one case with the maximum number;
- call dates on at least three different days, one of them next to a non-business day.

**Checked in Python before a case is used**

- Every value conforms to the contract: enums, required fields, product ids of the form the
  account operation returns.
- Any expected date the case derives from business-day arithmetic is declared with its calendar
  parameters and recomputed with the controller helpers (`ctl_add_business_days` and friends); the
  recomputed value replaces the model's.
- `expected` closes exactly once, and names no record for a customer who was never verified.
- A case that fails a check is dropped, with the reason in the trace. Fewer than three surviving
  cases means no generated suite.

## 6. Trusting a generated expectation

A generated expectation is the generator's reading of the brief, not ground truth. Three measures
keep a wrong one from doing damage.

1. **Independence.** Designer and generator read the brief separately. Where the agent and the case
   disagree, one of two independent readings is wrong, which is worth a look either way.
2. **Dispute.** The fix call receives a failed generated case with its `rule_refs`. The patch schema
   gains one optional field per fix, `disputes`, listing cases whose expectation the brief does not
   support, with the line that says otherwise. A disputed case is removed from the suite for the rest
   of the build and reported; it is neither a pass nor a fail. If more than a third of the suite is
   disputed the generated suite is abandoned.
3. **Calibration before the final (section 10, milestone 2).** On Briefs A and B the official
   expectations exist. Give the generator each public case's fixture and script without its expected
   records, and compare what it derives with the official values. This yields a measured agreement
   rate. Generated testing is enabled for the final only if that rate is at least 85% on both briefs;
   otherwise the generator prompt is revised, never patched with case-specific knowledge.

Generated verdicts are never called official. Their evidence type is `generated`, shown as such in
the trace, the report and the dashboard, and a build that used both reports the two pass counts
separately.

## 7. Two compiles of one source

The workflow source is compiled twice from the same text:

- **test copy**: the contract's operation URLs rewritten to `GEN_BANK_HOST`, deployed to a second
  Freya slot `builder-<brief>-test` and used for every generated simulation;
- **export**: the unmodified contract, deployed to `builder-<brief>` and exported.

`compile_workflow` already takes the contract as an argument and the static checks already require
each tool URL to equal the contract's, so both compiles are validated against their own contract.
Before export the builder asserts that the exported file contains no occurrence of the mock host.
The two slots cost one extra workflow per brief out of the workspace's 200.

## 8. Fit into the build

- `public_suite` becomes `practice_suite`: the kit's customers when the inputs are the kit's own
  brief and tool API (as today); otherwise a generated suite when `GEN_BANK_HOST` answers and at
  least three cases survive; otherwise none.
- `FreyaAdapter.evaluate` gains the bank host of the suite and sets it for the kit scorer; nothing
  else in it changes, so ledgers, call records, version checks and the live view keep working.
- The fix loop receives rows, findings and call records in the form it already reads.
- Time: the generator runs concurrently with rules and design (about two minutes); registration
  takes seconds. The loop then has the budget it has today: a root simulation and two to three rounds.
- New settings: `GEN_BANK_HOST`, `GEN_CASE_COUNT` (default 10), `GEN_ENABLED` (default `true`;
  generated testing still requires the host).

## 9. Rules, as they apply here

- The exported agent calls only the tool API from the kit; the check in section 7 enforces it.
- No hidden-brief content enters the repository. Cases, `bank_model` and transcripts live under
  `agent/artifacts/<run>/generated/`, which is git-ignored; the submitted trace names the suite by
  size and hash and lists results by case id and family.
- The builder still runs with one command and no manual step. The mock is deployed once before the
  event, like the builder's model endpoint.
- Platform use is ordinary: personas and serial simulations through the documented API.
- The mock holds only synthetic data, generated per build and expired after an hour.

## 10. Milestones

1. **Mock fidelity (half a day).** Build the mock. Register the ten public Brief A cases on it,
   compile the best existing agent against it and run them. Gate: Freya reaches the host, and the
   per-case verdicts match a run of the same agent against the real practice bank on at least nine
   of ten cases (two runs each side, to see past run-to-run variation). If Freya cannot reach an
   external host, stop: this ticket cannot be built on the platform's simulator.
2. **Generator and calibration (half a day).** Build the generator and the Python checks. Measure
   the agreement rate of section 6 on Briefs A and B. Gate: 85% on both.
3. **Loop integration.** `practice_suite`, the second slot, the two compiles, the dispute field.
   Gate: a full build on `agent/tests/fixtures/unfamiliar-policy.md` with its own tool API runs the
   improve loop on generated customers and exports an agent with only real URLs.
4. **Rehearsal.** One build of Brief A with the kit's customers hidden from the builder (generated
   suite only), then the exported agent scored on the official ten. Gate: the generated-suite build
   scores no lower on the official customers than a build that stopped after compiler fixes, in two
   of two attempts. This is the only evidence that generated testing helps on a brief it cannot see.

## 11. Acceptance tests

| ID | Check |
|---|---|
| G-01 | With `GEN_BANK_HOST` unset, a build of an unfamiliar brief is identical to today's: no generator call, no test slot, status `exported` |
| G-02 | A registered suite serves `sessions` and `ledger` in the kit's shapes; the unmodified `run_once` scores it |
| G-03 | The mock rejects a body the contract does not allow, and refuses a protected operation before verification, using the contract's error shape |
| G-04 | A declared fault fails exactly the stated call and no other |
| G-05 | A generated case with a value outside the contract, or closing twice, is dropped with a reason |
| G-06 | A business-day expectation is recomputed in Python and replaces the model's value |
| G-07 | The generator's input contains the brief and contract and no workflow |
| G-08 | A disputed case leaves the suite and is counted as neither pass nor fail; over a third disputed abandons the suite |
| G-09 | The test copy carries only mock URLs, the export only contract URLs; an export containing the mock host fails the build |
| G-10 | Generated and official results are never added together or labelled alike in trace, report or dashboard |
| G-11 | The generator finishing late or failing does not delay or fail the build; the trace records that generated testing was skipped |

## 12. What was dropped from the earlier ticket, and why

- **Optimization / validation / holdout splits, sealed storage and a leakage firewall.** They guard
  an optimizer against memorising its test set over many generations. The fix loop runs at most
  three rounds on at most ten cases, and the case generator cannot see the workflow.
- **Metamorphic, property-based and adversarial generators as separate engines.** One generator
  call with an explicit coverage list replaces them. If calibration shows a family is missing, the
  coverage list grows.
- **Counterfactual brief and tool API packs.** Still the right way to test the builder against
  unfamiliar input, but it needs the mock bank first. With the mock in place a counterfactual pack is
  a brief, a tool API and nothing else, and can be added without new machinery.
- **The five-arm ablation study and the score-only / diagnostics switch.** The switch no longer
  exists, and milestone 4 answers the one question that matters before the final.

## 13. Decisions for the team

1. Where the mock is hosted (recommended: Modal).
2. Whether to spend the remaining time before the final on milestones 1–2 first, since milestone 1
   can end the ticket in an hour if Freya cannot reach an external host.
3. Whether generated testing is on for the final if calibration lands between 70% and 85%.
