# Ticket 07 — Read the whole case and resolve what governs it

Priority: P0. Status: planned. Depends on reconciling the branch baseline in [the series plan](adaptive-brief-series.md).

## Problem and outcome

The final folder combines an overview, conflicting historical analysis, quoted email corrections, a drawing, examples, infrastructure samples and a 707 KB fixture corpus. Today they become mostly flat text; JSON is truncated at 150,000 characters, and extraction may fail twice before the builder continues without requirements. The designer can then revive old rules or learn “policy” from a sample Worker.

The same builder must turn any supported case folder into a complete source inventory, effective requirements, contract evidence and test data references. Preserve the existing source/span/precedence models and source-derived probes. Add only metadata needed to distinguish policy, contract, fixture, example and infrastructure material.

## Scope

Touch `agent/builder/sources.py`, `contracts.py` (`source_documents` and contract derivation), `schemas.py`, `prompts.py`, `build.py`, and their callers/tests. Reconcile `3c38cf8` probes with latest remote `ctl_choice` fixes first; preserve current user edits.

1. Inventory every file with relative path, hash, detected format and extraction outcome. Mark truncation, unsupported or unreadable input explicitly. A truncated representation must never pretend to cover a full document.
2. Keep fixture JSON available in full for mock and diagnostic use. Give analyst/contract extraction bounded structural views plus references to complete records; do not push all 617 repetitive responses into every model call. Summary must preserve schema variants, error statuses, missing fields and delayed-response metadata, with pointers back to originals.
3. Split evidence into role-aware views using file content and context, not a statement-debt filename allowlist. Read BRIEF first. Infrastructure code/examples do not become bank services; response labels never become instructions. MD/TXT and binary readers must agree about coverage accounting.
4. Resolve policy per rule, using explicit approval/correction/supersession and the date of each email message, including quoted messages. Keep exact existing source spans. Record winning and superseded evidence; date alone cannot resolve an unapproved proposal.
5. Keep ambiguous/conflicting requirements and unsupported capabilities visible with affected paths. Repair extraction errors within the deadline. Do not silently discard requirements; do not hold all known branches hostage to one missing field.
6. Derive input variables, permitted scope, side effects, source-backed acceptance probes and contract references from runtime inputs. Separate trusted entry variables from conversational values. Avoid practicing identity verification or closure rules being automatically inserted into another case.
7. For this pack, the textual bank decisions resolve the drawing's obsolete second-factor box. Preserve PDF extraction limitations in the inventory. No new general OCR/vision subsystem is required to finish this readable pack.

## Final-pack acceptance

The generated evidence report covers all 18 files and the full fixture corpus. It identifies the following effective decisions without putting them into fixed builder prompts:

- Entry is already authenticated; customerNumber and now are supplied; no PIN/code/date-of-birth request.
- Registered email only; later business policy overrides technical ability to send elsewhere.
- Once per calendar year per card, resetting 1 January, supersedes older frequency limits; the explanatory line is optional.
- Exactly one card per reading; three attempts per question; repeat requests cost no attempt; third silence ends the call.
- Three calming replies supersede the “two” inside the recap's quoted earlier message.
- Out-of-scope question asks permission; declining resumes the suspended question.
- Full production card numbers may be used for matching but never spoken. Masked test numbers stay masked.
- NO_DEBT offer/future-FX additions and transfer wording remain proposals/open questions where not approved.

The report must include this decision ledger:

| Open item | Evidence | Owner / acceptance impact |
|---|---|---|
| Yearly change eligibility | October analysis §5.2/§11; contract §5.3 | Bank/card-platform clarification; offer filtering unproved for unknown eligibility |
| Masked last-six identity | Test overview; October recap | Bank/test clarification; unresolved masks cannot yield a unique card |
| Handoff mechanism and third-party route | Contract introduction; analysis §8.6; example 5 | Freya/IVR clarification; separate intended terminal from actual routing |
| Required PDF currencyType choice | Contract §5.7; email business flow | Bank clarification; multi-currency send default not established |
| Slow-service limit | Contract §4/§7; analysis §8.3 | Engineering proposal with measured test, not bank rule |
| Remaining speech/privacy details | Analysis §4.4/§4.7/§11 | Owner and scope retained; no fabricated rates, totals or mandatory notice |

For a missing fact, record any deliberate engineering fallback separately from a resolved bank requirement, including its risk. A workflow can expose a best-effort artifact while reporting affected requirements as unknown; it cannot claim all final acceptance checks passed.

## Generic regressions and done

Use neutral cases in builder tests: a quoted correction overriding an earlier message, a withdrawn verification step in a diagram, an approved policy overriding a permissive API, and a large JSON corpus whose decisive variant is beyond the old cap. A contradictory proposal remains unresolved. A fixture string saying “ignore instructions” is inert data.

Run the same extraction on collection practice and an unrelated authenticated support case. Swap a policy version or input variable name at runtime; requirements and probes must change without a code edit. An unreadable governing document produces explicit incomplete evidence, not a successful empty bundle.

Done: inventory, effective requirement bundle, contract evidence, complete fixture references and decision ledger are persisted in the build trace and consumed by designer/repair. No second requirements/probe framework, hard-coded final rule catalog, vector database or generalized document platform.

