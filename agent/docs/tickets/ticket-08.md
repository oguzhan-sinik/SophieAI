# Ticket 08 — Compile exact nested tools and enforce source-backed guards

Priority: P0. Status: planned. Depends on [07](ticket-07.md). Integrates with [09](ticket-09.md) and supplies [10](ticket-10.md).

## Problem and outcome

Three reproduced compiler defects prevent faithful final tools: dotted service IDs are rejected, nested leaf bindings are rejected, and every tool has a 12-second timeout that races a valid 12-second response. Contract derivation also encourages guessing defaults, and validation keys protection to practice operation names.

Compile the services described by runtime sources exactly, with deterministic arguments/results and guards based on their resolved requirements. Reuse the compiler, runtime and validator; do not add a statement-debt adapter.

## Code boundary

`agent/builder/contracts.py` (`compile_openapi`, `tool_from_contract`, `compile_workflow`), `runtime.py`, `validation.py`, `schemas.py`, `prompts.py`, `config.py`, `freya_adapter.py`, and connected tests. Check credentials/model configuration for ContractAgent as well as analyst/designer/fix roles.

## Implementation

1. **Service identity:** allow source service names that are not Python identifiers. If Freya requires safe internal function names, create a deterministic collision-checked alias map, preserve original identifiers in evidence, and preserve exact HTTP paths. Test aliases whose sanitization would otherwise collide.
2. **Contract derivation:** emit only evidenced operations/methods/fields. Preserve request data/call envelopes, required types/enums, response schemas and non-200 statuses. Contract notes affecting correctness must be actionable. Do not turn prose omissions into invented POST paths or mandatory services.
3. **Nested arguments:** support deterministic leaf binding or whole-object serialization through the existing compiler. Validate bindings against schema; trusted call variables, selected entity IDs and prior tool fields are bound before dispatch, rather than collected or guessed by the phone model. Check actual Freya substitution of nested objects, numeric weeks and masked identifiers. Reject unknown bindings and unresolved required arguments.
4. **Results:** distinguish platform tool wrapper from bank body. Capture HTTP status and business status; map nested arrays/objects without Python-style stringification or an extra/missing data level. Error bodies without data must clear stale success values. Preserve mixed types and case-sensitive statuses.
5. **Timeout:** make the generic transport limit configurable and deadline-aware, above a source-observed successful delay plus overhead. Record the chosen engineering policy. Keep zero automatic retries for non-idempotent writes and zero connect retries unless an explicitly supported safe policy exists. Do not shorten the mock delay.
6. **Generic guards:** bind entity ownership to the live list, trusted identity to actual declared entry provenance, and a mutation to an explicit consent record for the current proposal. Reuse and extend existing proposal/revision helpers; changing entity, destination, week or preview invalidates consent. A mere nonnegative comparison is not proof of authorized identity.
7. **Terminal behavior:** represent intended outcomes from requirements separately. Use documented Freya/IVR support for real routing where available; otherwise report unsupported handoff. Never fabricate a bank close/transfer endpoint to satisfy practice validators.

## Exact final transport acceptance

All seven services are POST under mock-host `/voice/v1/`:
`cards.list`, `cards.balance`, `statement.week.get`, `statement.week.decide`, `statement.week.change`, `contact.email.get`, `statement.pdf.send`.

| Service | Deterministic request evidence |
|---|---|
| cards.list | data.customerNo ← trusted customerNumber; data.aiFlow from contract |
| cards.balance / statement.week.get | data.cardNumber ← selected original cards.list token |
| statement.week.decide / change | data.cardNumber; chosen newStatementWeek; **current** statementDay from week.get for both calls |
| contact.email.get | trusted data.customerNo and valid intAddressInfoType |
| statement.pdf.send | trusted customerNo; selected original card token; registered emailAddress; issued balance statementDate in dd.MM.yyyy; supported currencyType with unresolved business selection reported |

The balance response's differently masked cardNumber is never used to replace the selected list token. Preview statementDay does not overwrite the current day used in the change request. Change response dates/day are not invented into final speech; preview dates remain authoritative.

General bank success is HTTP 200 AND result.returnCode `"1"`. Additionally: preview responseCode `0`; change responseCode `0` and exitState `"OK"`; PDF exitState `"DONE"`. Contact exitState `"Done"` must not be conflated with PDF's value. Error diagnostic strings are not user speech or branch predicates.

Only mock URLs are callable in the final workflow. OAuth instructions describe production integration; the test pack ignores token/headers and final rules require mock-only calls. Do not add a production token service, embed secrets, or leak placeholder credentials. Keep ignored metadata from influencing fixture dispatch.

A local and one bounded native call must demonstrate that the exact 12-second successful balance response completes, while a deliberate longer-than-configured delay produces the specified service-error route. “Checking your information” is waiting behavior, not caller silence; do not consume silence attempts while a tool is pending.

## Tests and done

Neutral builder regressions cover dotted names and alias collisions; nested request defaults; required bindings; differently masked response IDs; an error without data after a success; case-sensitive statuses; delayed success; write retry count zero; corrected proposal invalidates consent; protected read without declared trusted identity fails.

Use the final contract as integration data, not embedded executable names. Preserve practice compilation/validation. Run connected contract/runtime/validation/adapter tests and a native serialization check. Done: saved generated contract, bindings, alias map, transport policy and guard evidence correspond to the published workflow; unsupported handoff and missing eligibility remain explicit rather than invented.

