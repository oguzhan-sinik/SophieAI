# Ticket 09 — Serve every official mock response faithfully

Priority: P0. Status: planned. Independent of builder changes; uses the contract/evidence reviewed in [07](ticket-07.md). Required before final native calls.

## Problem and outcome

The current Worker implements the collection practice, dispatches by the last URL segment and expects a root customer_id. The final instead requires seven exact dotted paths, nested data fields, fixed bank responses and one deliberately slow success. The supplied ping Worker only demonstrates deployment; it is not a bank mock.

Implement a small case-specific statement-service replay Worker with a table imported from the official fixture JSON. Keep practice behavior available. Case-specific mock fixtures are permitted by the event; do not copy their business rules into builder prompts.

## Code boundary

`mock/src/worker.js`, a separate replay table/handler if needed, `mock/wrangler.toml`, deployment metadata, `mock/test.mjs` or a focused conformance runner, and `mock/README.md`. Inspect existing local mock changes before editing. Reuse Worker routing and call-record capture where helpful; do not reuse collection Bank state or add a database.

## Dispatch and response contract

Match exact method and path: POST `/voice/v1/<service-name>`. Parse the data/call envelope. Ignore token, headers, call and aiFlow for official fixture lookup, as instructed by the test overview; absence of real gateway credentials is not a fixture error.

| Service | Lookup |
|---|---|
| cards.list / contact.email.get / statement.pdf.send | data.customerNo |
| cards.balance / statement.week.get | data.cardNumber, exactly the original masked list token |
| statement.week.decide / statement.week.change | data.cardNumber, then data.newStatementWeek |

Normalize only explicitly equivalent representations: customerNo string/number and newStatementWeek string/number. Preserve masks and leading zeros in card tokens. Current-week requests have no entry; never substitute a different week. Card service keys are unique across this supplied corpus; assert conflicts rather than silently selecting an owner if future fixture data changes.

Return exactly the fixture's HTTP status and response body. Preserve casing, numeric/string types, missing currency blocks, diagnostic fields and GUIDs. Delay `94907600`'s balance reply by delaySeconds **12**, outside the JSON body. Do not “fix” arithmetic, sanitize fixture labels, manufacture a yearly eligibility flag, simulate changed balances or alter later replies after writes.

Malformed/missing required data and unknown fixture keys use the service's documented error envelope. Unknown customer/card/week: documented service-specific 404 where available, otherwise 400 INVALID_ARGUMENTS_ERROR. Method/path mismatches and invalid JSON produce deterministic errors. Do not accept arbitrary path prefixes or accidentally expose practice/admin routes as final bank operations.

The panel example's template-variable fallback is optional convenience, not final behavior. Prefer an explicit diagnostic mode if implemented; real unknown identifiers must never receive a sample customer's data.

## Conformance acceptance

Generate requests directly from every leaf in the complete fixture file. Assert **617/617** response bodies and HTTP statuses, broken down as:

- cards.list 34; cards.balance 65; week.get 65; week.decide 195; week.change 195; contact.email.get 34; PDF.send 29.
- 609 successful leaves, six HTTP 500, no-card 404 and no-PDF 404.
- Test the three off-list card service records under customer 97073972 too. Replay fidelity does not authorize the phone agent to bypass its failing card list.

Use a local fake clock for exhaustive conformance and one real elapsed-time check for the delayed response. Exhaustive fixture checks belong locally, not in hundreds of live Freya calls. Assert delay metadata never leaks into the response body.

Additional negative requests cover every required field, unsupported week, current week, unknown customer, unknown card, missing PDF entry, malformed body, bad method and wrong prefix. Type-equivalent inputs produce the same fixture reply. Existing practice mock tests still pass.

A diagnostic ledger may record request order, normalized arguments, side effects, response statuses and times using the existing test correlation header where available. It must not modify official responses or impose extra customer fields. Records distinguish an intentional resend from transport retry. Keep diagnostics separate from the seven bank endpoints.

## Deployment deliverable and done

Deployment is an implementation task, not an action authorized by these document instructions during planning. Once deployment is separately authorized, use existing Cloudflare setup, deploy the actual replay Worker, and capture URL, deployment version, source/fixture hash and bounded public smoke checks.

Public smoke checks must include the exact seven paths, a successful read, the no-card warning, one side-effect fixture and the delayed response. No Freya platform probing/load tests. Document how to keep the Worker live until results and how to verify health without changing fixture behavior.

Done: exact local conformance, contract errors, preserved delay, deployed reachable mock and provenance. A health endpoint alone is not evidence that the bank contract works.

