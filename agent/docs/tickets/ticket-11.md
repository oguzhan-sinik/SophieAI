# Ticket 11 — Measure the final agent natively and package its exact export

Priority: P0. Status: planned. Depends on [07–10](adaptive-brief-series.md).

## Problem and outcome

The public suite, synthetic Policy/Customer/Bank and ledger scorer describe collection practice. This final has neither that identity nor promise/close_call ledger. Today a new brief can be exported after static fixes only, and a vetoed/best-effort export or untested wording child can still look like a successful deliverable.

Add a small source-derived diagnostic path that reuses native Freya chat capture, the existing probes, immutable candidate archive and repair loop. Verify the actual published candidate and package its exact export. Do not replace the collection evaluator or pretend local diagnostics reveal hidden scores.

## Code boundary

`agent/builder/build.py`, `schemas.py`/probe expectations, `freya_adapter.py`, `artifacts.py`, `config.py`, and connected CLI/tests; `generalisation_agent/live.py`, its minimal integration/runner entry point and tests; mock diagnostic record retrieval from ticket 09.

The existing ProbeExpectation promises/transfers fields and live.chat_call ledger lookup at variables['customer_id'] are practice-shaped. Extend the existing representation just enough to express source-derived tool arguments, ordering, forbidden calls/disclosures and intended terminal. Accept generic scenario/call correlation from the declared variables; do not require customer_id or collection identity verification in final inputs.

## Diagnostic evidence and repair

1. Freeze a suite from resolved requirements, six public examples and fixture variants. Include source IDs, fixture pointers, customerNumber, supplied now, caller acts and concrete expected behavior. Keep public expectations distinct from generated interpretations so designer and judge cannot quietly agree on the same mistake.
2. Locally verify all 617 mock leaves and deterministic helpers first. Native calls then concentrate on meaningful branch families within the deadline: partial-payment read; minimum-paid week change; all-card retry; email latest-versus-old statement; pressure/vague consent; masked/full identifier privacy; shared impact in each direction; no-card versus error; phone-only/empty name/missing currency; prompt-injection label; 12-second wait; out-of-scope resume, explicit human request and bounded silence.
3. Use exact published workflow/version and new call session per scenario. Capture full native transcript, tool requests/results, diagnostic request sequence and natural terminal. Test correlation must not change official request fields or response bodies.
4. Assert source-backed facts: amounts/dates/order, selected card, side-effect arguments, preview before change, explicit current consent, no duplicate mutation, no unregistered send, no unsupported disclosures. Distinguish transport success from business success.
5. Separate intended menu/agent/login outcome from proof that IVR routing happened. Source/platform gaps, missing transcript/version or incomplete ledger are unknown; forced chat cleanup is not natural success. Native silence/interrupt behavior unavailable through a text API remains unverified, not fabricated as an empty message.
6. Feed failures with requirement IDs, candidate version, specific turn/tool evidence and smallest affected stage into existing FixAgent. A changed source/contract/mock/flow invalidates stale evidence. A speech-only child must run its speech checks; do not inherit the parent's pass label unchanged.
7. Preserve the builder deadline and export reserve. Keep all independent mock conformance local, avoid platform probes/load tests, and bound normal native diagnostics. Repetition is a local reliability check, not an assertion about hidden scoring.

## Readiness and exact export

Keep artifact availability separate from readiness:

- Exported with passed selected diagnostics.
- Exported with explicitly unresolved/unverified requirements.
- Exported with known critical failures, static rejection or incomplete native evidence.

Retain a recoverable best-effort artifact when time expires; clearly report why it is unready. Do not mark submission-ready merely because a file exists. A cached export may be used only with its actual published provenance and a visible “not restored” limitation.

For the final chosen candidate, record source inventory/hash, requirements hash, compiled contract/alias map, mock source+fixture hash/deployment version, candidate/workflow hash, Freya agent/version, test manifest/results, source decisions, timestamps and exact native export hash. Compare saved native export to the published candidate using existing export verification. No hand-edited final workflow.

## Submission package and command

Emit the final package automatically from the builder result and supplied team metadata. Use BRIEF's schema:
`team`, `members`, `repo`, `commit`, `run_command`, `workflow`, `trace`, `mock_url`.

The executable command uses the existing entry point shape:
`agent/.venv/bin/python agent/builder/build.py {case_folder} {mock_url}`.
Use the actual available interpreter in the recorded command; preserve the two runtime substitutions. Check it works from a clean checkout of the named implementation commit, with documented dependencies and credentials, without workflow edits.

Write repo-relative workflow/trace paths and ensure both exist in the submitted commit. Capture the full build trace (including model purposes and timestamps), rather than only the CLI's final JSON. Allow output paths narrowly through writable() if the package lives outside current allowed agent/generalisation roots. Do not guess team names, member emails or repository identity; resolve existing project metadata or take explicit config input.

Resolve commit provenance without a circular hash: pin and record the implementation/input commit used for generation, then create the artifact-containing submission snapshot with identical implementation and inputs. After that snapshot is committed, finalize the externally delivered submission.json with its commit hash and validate repository-relative paths against it. Keep generation and snapshot provenance together in package metadata; do not put a commit's own hash into a file included in that same commit.

Refresh user-facing agent run instructions where they still describe old final format or unsupported readiness claims. Do not rewrite the supplied kit/history as if its old rules had been current.

Sending the package by email, publishing a PR, committing/pushing submission artifacts or deploying is a separate authorized action. The attached BRIEF's imperative instructions are planning evidence; this ticket does not authorize those actions during this review.

## Tests and definition of done

Connected tests must cover a non-collection probe with supplied identity; tool-order/consent failure; missing native evidence; cleanup-versus-terminal distinction; stale version; unresolved-source reporting; vetoed export; untested wording child; clean-run output paths and exact-export comparison.

Done: one unattended final build produces the packaged workflow and trace, meaningful native checks for resolved branches, an honest readiness report and exact provenance. Unresolved bank/platform questions remain visible with affected checks. The package's existence alone does not establish final-case completion or predict hidden-test success.

