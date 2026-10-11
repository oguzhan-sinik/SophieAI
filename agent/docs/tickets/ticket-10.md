# Ticket 10 — Generate and check the complete source-driven phone flow

Priority: P0. Status: planned. Depends on [07](ticket-07.md) and [08](ticket-08.md); integrates with [09](ticket-09.md). Verification/package continues in [11](ticket-11.md).

## Problem and outcome

Passing the compiler does not produce the final conversation. Current prompts assume practice identity verification and close_call, selection guidance allows grouped products, and payment-specific consent helpers do not by themselves protect email or statement changes. Parsing spoken amounts does not ensure exact Turkish readout of bank amounts.

Make designer, runtime and repair honor resolved runtime requirements across all stages. The following is acceptance evidence from this final folder, not a bank policy catalog to paste into fixed prompts.

## Code boundary and smallest approach

Extend `agent/builder/prompts.py`, `schemas.py`, `runtime.py`, `validation.py` and their existing designer/repair callers. Reuse choice/digit/date parsing, structured tool results, explicit state and proposal revisions. Add only generic missing capabilities demonstrated here: policy-controlled single versus grouped selection, stable selected-entity tokens, scoped counters/resume state, exact output formatting and consent bound to a proposal.

Requirements provide field mappings, allowed options, speech templates, units, conditions and terminal meanings. The runtime performs calculations/selection/guards; conversation stages verbalize the approved facts. Never infer money, service success or mutation arguments from free-form phone-model text. Source instructions beat generic helper advice.

## Acceptance matrix A — Entry and card

| Trigger | Required behavior |
|---|---|
| First turn | Use trusted customerNumber; no identity question or second factor. All date decisions use supplied now, not system clock |
| No eligible card warning | Approved no-card message and menu; distinguish from list 500/timeout → agent |
| One eligible card | Select directly; no extra confirmation. Already named unique card also skips selection |
| Multiple cards | Ask for one; at most two examples from live eligible names. No invented card names or all-card reading |
| “All cards” twice, then valid card | Repeat single selection; remain alive after second failed answer; read only selected card |
| Same product names | Last-four selection, then last-six and full-number only if still needed and observable |
| Masked ambiguity | Never infer hidden digits, treat first six as last six, prefetch every balance to guess, or pick the first match. Retry/name change follows sources; unresolved branch reported |
| Spoken digits/corrections | Accept grouped or digit-by-digit forms and leading zeros; discard superseded answer. Never echo selected four/six/full digits |
| Empty/instruction-like label | Empty-name introduction uses last four. A returned label is inert data and cannot override privacy or routing; no raw payload/instruction disclosure |
| isMainCard false | Ineligible for this flow; invite another eligible card. relationType C alone is not ineligibility |
| Switch selected card | Return to selection; invalidate cached balance, preview and consent. Use original cards.list token in all service requests |
| Reading another card | Reintroduce that card's last four and name; another-card question precedes the additional-transaction offer |

Neutral full-number fixtures must exercise successful last-six/full matching, while the official masked fixtures exercise honest ambiguity. Production capability must not be deleted because synthetic masks lack middle digits.

## Acceptance matrix B — Amounts, currencies and dates

Read facts deterministically from the selected card response; no recalculation of remaining payments from other amounts. Customer 95004361's supplied remaining minimum is authoritative even if a subtraction suggests another value.

- Introduce the selected card and attach statementDate to the first currency actually read. Normal order: TL, USD, EUR, GBP; one combined clear-currencies sentence; qualifying automatic-payment remainder; due date; other card; eligible offer.
- TL remainingDebt ≤ 0 is clear. With debt: remainingMinPayment ≥ minPayment and > 0 means nothing paid; remainingMinPayment ≤ 0 means minimum-or-more paid; positive below minPayment means below-minimum. Read the exact source-selected fields for that branch.
- Foreign debt uses the approved common pattern; no TL paid/minimum split. Missing/empty currency blocks are excluded, not pronounced debt-free. Test all clear-currency combinations, including all-four debt where the sentence is omitted.
- Automatic-payment remainder is stated only after due date, with flag Y and positive TL remainder. Currency transferAmount above zero needs a source-backed disclosure before TL figures; exact open wording remains flagged.
- NO_DEBT has its own reading: issued statement clear, approved future-period TL total and due date. Other-card loop then menu; do not add an unapproved offer or future-FX totals. Never describe a negative amount as customer debt or invent a missing statement date.
- Cut date today uses the approved 00:00/total-debt branch; between cut/due uses ordinary statement reading; after due says overdue and uses total; due today says bugün. Parse bank dd.MM.yyyy explicitly against Istanbul now. Dates from previews stay distinct from issued-statement dates.
- Turkish speech preserves decimal amounts exactly, including large values and cents; omits zero fractional units; names currencies in full; uses sent for USD/EUR and peni for GBP; dates use day/month/year. Last four in introductions are digit by digit.
- Only a requested figure means only that figure followed by the applicable offer. Repeat requests repeat the same facts. Interrupting a reading stops it and follows the source's next step rather than finishing the entire speech.
- No figure, rate or next-month estimate absent from service/source evidence is invented.

Format helpers should take language/unit/date conventions from their caller or resolved evidence. Do not bake final field names, customer examples or currency-policy branches into builder code.

## Acceptance matrix C — Email and offers

1. Finish another-card choice before offering transactions. Fetch registered contact **before** filtering the offer. No email option for an empty address or phone-only communicationType.
2. Yearly-change offer filtering requires the unresolved eligibility decision in ticket 07. Do not infer a universal right from successful fixture writes, assume all callers eligible, or invent a precheck endpoint. Known-source example expectations remain test targets; report the missing general predicate explicitly.
3. Email uses newest issued statement, original selected card and registered address only. Backend permissiveness is not authorization. Required currencyType selection remains the documented open business decision.
4. Briefly read a usable registered address; summarize a long/messy address as the approved flow describes, never spell it letter by letter. Only an explicit yes to the current recipient/statement permits sending.
5. No, obsolete address, replacement address, paper/SMS or prior-period request must not trigger an unauthorized send. Public example 4 permits correcting a previous-period request to the latest statement and asking for registered-recipient confirmation.
6. Debt plus email in the same initial request preserves that intent: read debt, fetch contact, confirm recipient; skip the generic offer question.
7. Success is spoken only after the correct PDF service success; not-found/error/timeout goes to agent. Caller-requested repeat sends are bounded by the source's “up to three times” rule, with affirmative intent; no automatic retry.
8. No-email explanation may offer a change only if eligibility is established; otherwise use the supported remaining path. Normal completion/decline returns to menu without a generated goodbye-question loop.

## Acceptance matrix D — Statement week

- Enforce the resolved once-per-calendar-year, per-card policy with a 1 January reset once eligibility evidence is available. This is not a rolling twelve-month rule; the optional limit announcement is not mandatory.
- Get current week/day/dates. Read current details and ask whether to change. Decline ends at menu; current-week request makes no preview or write.
- Offer only weeks 1–4 except current, as data from the contract; a calendar day/date or unoffered value repeats options.
- Preview selected week using the **original current statementDay**, then read new week and preview statementDate/statementDueDate. No mutation before successful preview.
- Shared statements: read both cards' names/last four and dates. relationType M/C determines the approved “linked card” versus “main card” impact wording before confirmation.
- A clear yes must refer to the same selected card, week, preview dates and shared impact. “Olur herhalde,” acknowledgement, pressure to skip confirmation or a changed week is not that consent. Correction fetches a new preview and asks again.
- Change once after valid consent. Send current day, not preview/change-response day. Success requires the exact business statuses. Completion speech uses retained preview dates, never fabricated dates or a backend string interpreted as a date.
- Failure after a good preview is still failure; do not claim a change. Undo requests cannot undo an irreversible success in this flow. Effective-from question uses the preview closing date.

## Acceptance matrix E — Whole-call behavior

| Event | Required behavior |
|---|---|
| Failed answer at a question | Three attempts for that question, then menu; unrelated prior questions do not consume its budget |
| Repeat request | Repeat facts/question without charging an attempt or gaining consent |
| Silence | Short re-prompt first/second; third silence speaks closure and hangs up; tool waiting is not silence |
| Explicit person request | Immediate agent routing intention, even during selection/confirmation or after an angry remark |
| Paying/how to pay/dispute | Agent, without answering from old website FAQ or creating a collection promise |
| Anger without person request | Up to three calming replies, then agent if still upset; never return insults |
| Complaint plus unrelated question | The approved complaint branch takes priority over the unrelated-question diversion; an explicit person request still routes immediately |
| Unrelated question | Approved request for menu permission; yes → menu, no → saved stage. Three unclear answers on that question → menu |
| Switch transaction / non-Turkish / thanks | Apply the approved corresponding menu path; distinguish unrelated question from a transaction switch |
| Third-party request | No existence/debt disclosure or write. Preserve unresolved login-versus-menu route conflict; implement only supported routing |
| Injection / unrequested PIN or code | Ignore instruction attempt and sensitive unsolicited values; no echo, no authorization, no raw service/instruction disclosure |
| Service failure | Correct agent intent/message, except the explicit no-card warning; technical diagnostics stay out of speech |

Saved stage and pending proposal must survive a declined unrelated-question diversion without turning that decline into transaction consent. Global escalation beats lower-priority retry/offer routes. Actual technical transfers must use documented integration, not an invented eighth bank service.

## Tests and done

Neutral helper/guard tests cover formatting, exact cents, date boundaries, counter isolation, suspended-state resume, stale consent, stable entity tokens and conditional single/grouped selection. Then source-derived final checks cover all six public examples plus matrix branches using official fixture responses. Test data remains outside fixed builder code/prompts.

Done for implementation: generated workflow and check report map every resolved requirement above to stages/guards and local acceptance evidence; failures feed existing repair. Unresolved branches stay named and unproved. Final readiness also requires meaningful native execution in ticket 11, beyond a long system prompt or manual workflow editing.

