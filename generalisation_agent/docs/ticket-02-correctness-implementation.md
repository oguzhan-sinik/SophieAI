# Ticket 2 correctness milestone

Implemented the execution, grading, and contract-conformance milestone from the [audit](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/docs/ticket-02-audit-2026-10-11.md). This document records the resulting behavior; the audit remains a snapshot of the previous implementation.

## Changes

- Interrupted calls retain independently proven ledger violations and confirmed transcript violations. Missing final outcomes remain unknown. A failure accompanied by unknown evidence cannot produce a complete suite or strict pass rate.
- Exhausted, noncommitting writes permit truthful `service_error` closure and per-product notes. Retry-after-success and ambiguous commitment checks remain separate.
- Calibration requires the intended critical rule, rather than any critical failure. The dishonest-success fixture now has an otherwise valid error ledger. Twelve controls include an executed compliant graph and an executed graph that proceeds despite a wrong identity answer.
- Transcript validation rejects inapplicability for obligations triggered by verification, writes, successful recording, transfers, and cited corrections. Prefix judging explicitly distinguishes observed violations from missing later speech.
- API pre-actions use node-named results/counters; model-called tools use tool-named results/counters. Results replace stale flattened fields. Turn totals, current turns, entry counts, and per-node caps are separate. Fixed action-node speech occurs before its tools; unverified LLM action-entry ordering abstains explicitly.
- Mapping supports absent optional response fields, conditional card/loan minima, and optional card identifiers. Responses emit declared fields instead of inventing `locked` or HTTP-status properties in the bank body. Identity swap hints preserve the attempt budget.
- API request constraints use the installed JSON Schema validator. Unsupported schema features fail admission instead of being silently ignored.
- Preparation is bounded to at most five minutes and one quarter of the available active budget. Timeout restores the shared deadline before the baseline builder runs.
- Customer dates derive from source holidays; callback time fits the source window. Reduced suites prioritize identity, write failure, and mixed-product risks. Fragmented-number instructions are explicit.
- Holdout builds reserve time for diagnostics. Completed development measurements supply observed case durations for holdout admission. Both packs use the same resolved configuration. Rehearsal returns exit code **5** when exports exist but required measurements are incomplete; exit code 0 requires completed evidence.
- Calibration/suite fingerprints include nonsecret endpoint and reasoning settings. Pack format version is now 2; old packs require regeneration.
- The existing static validator rejects negative, existence-only, and transport-only identity conditions. It remains a structural check, not a formal proof of arbitrary generated Python.

## Verification

The regression suite covers interrupted calls, schema bounds, stale results, exact calibration targets, timeout fallback, incomplete rehearsal exit status, source-specific callbacks, and fingerprint changes. Independent fixtures replay all **13 supplied practice-case ledgers** against the bank and reference oracle. Additional conformance checks use the supplied OpenAPI and an independently renamed/wrapped equivalent, including conditional product fields.

**213 ordinary tests passed. Four explicit Docker tests passed**, including both compliant and incorrect compiled identity controllers. Docker readiness failed in earlier attempts; direct image inspection and the final integration run succeeded with Docker socket access.

The model-backed generation step succeeded with the currently configured `openrouter/openai/gpt-6.1-sol`, producing one clean development pack and one raw holdout pack with ten users each. The [saved top-level manifest](/Users/oguzhansinik/Downloads/build-the-builder/generalisation_agent/artifacts/20261011T055823_3aaa115d/manifest.json) binds the stored inputs and private cases. These are generated inputs, not a workflow score.

The live development calibration completed six of twelve controls before its five-minute active budget expired. It recorded zero false passes, zero false failures, and seven unknowns, including the budget timeout; date-rule readings lacked agreement. Admission stayed disabled, and the original build deadline was restored before baseline workflow construction. This demonstrates the fallback, not successful calibration.

The optional rehearsal was stopped during development workflow design after calibration failed admission, before any holdout workflow evaluation. The source-freeze guard also detected a concurrent `packs.py` change; that edit was preserved. The final schema-admission patch was applied after stopping the process. No completed two-pack workflow measurement is claimed, and no calibration from this earlier source snapshot admits the final implementation. No Freya workflow deployment, official simulation, or custom hosted bank was performed.

## Remaining boundaries

This milestone does not claim full Ticket 2 acceptance. The live source interpreter still conservatively requires the complete supported policy profile; unresolved real-source rules are not guessed. Broader partial-profile grading, additional actor realism/boundary coverage, and dashboard containment/HTML hardening remain findings in the audit. The local model and interpreter remain a proxy for Freya; exact platform entry ordering still needs recorded parity evidence.

Selection remains gated by fresh calibration and complete evidence. A generated pack, compiled export, or incomplete rehearsal alone never establishes admission or hidden-score performance.
