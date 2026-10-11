# TICKET-05 — Tiered model assignment for token and resource efficiency

**Status:** Implemented this milestone.
**Priority:** P1 — we pay our own model-call costs and the 30-minute budget is fixed; the builder makes hundreds of calls per run.
**Depends on:** [Ticket 02](ticket-02.md) (single `ADKRoles.ask` chokepoint, calibration fingerprints). Composes with [Ticket 04](ticket-04.md): its stateful actor multiplies per-conversation calls, which is exactly where cheap tiers pay.

## 1. Outcome

Every model call is routed to the cheapest tier that does the task well. Hard design work keeps the strong model; independent checks and grading use a medium model; high-volume, narrow per-turn roles (customer speech, listener classification, generated-workflow proxy nodes) use a cheap model. Selection, admission and export identity stay bound to the *full* set of models used, not just the primary one.

Authoritative constraint: builder models are unrestricted but we pay per call, phone-agent model is fixed and untouchable, and the top-ten rebuild is compared against traces — so the trace must record which model served every call (https://www.freyavoice.ai/hackathon).

## 2. Design

One chokepoint already exists: `agent/builder/adk.py` `ADKRoles.ask(role, ...)`. Tiering is therefore one resolution step: **role → tier → model**.

| Tier | Default model | Roles |
|---|---|---|
| `hard` | `BUILDER_MODEL` (e.g. `openrouter/openai/gpt-6.1-sol`) | `BriefAnalystAgent`, `ADASDesignerAgent`, `FixAgent`, `synthetic_source_analyst` |
| `medium` | `openrouter/openai/gpt-6-luna-pro` | `synthetic_brief_writer`, `synthetic_brief_checker`, `synthetic_transcript_judge`, `synthetic_transcript_reviewer`, `synthetic_transcript_validator`, `synthetic_live_judge`, `synthetic_live_reviewer`, `synthetic_customer_validator` |
| `easy` | `openrouter/deepseek/deepseek-v4.1-flash` | `synthetic_customer_listener`, `synthetic_customer`, `proxy_router`, `proxy_dialogue`, `proxy_extractor` |

Rationale: the analyst/designer/fixer and live-policy interpretation decide *what is built* and feed calibration — errors there are unbounded, keep the strong model. Grading, conformance validation and brief writing are bounded, well-schematized checks — a medium model suffices and its failures are caught by existing validation and two-blind-reading disagreement. Actor speech, question classification and the generated workflow's own proxy nodes are short, per-turn and high-volume — the cheapest tier dominates total tokens.

Explicit non-goals: no prompt rewriting per model, no response-format downgrades (each tier keeps the same strict schema path its provider prefix already routes), no change to the phone-agent model, no new dependencies, no cost-estimation service.

## 3. Configuration and override rules

- `MODEL_TIER_HARD` / `MODEL_TIER_MEDIUM` / `MODEL_TIER_EASY` override a whole tier; unset tiers take the defaults above (`hard` falls back to `BUILDER_MODEL`).
- `ROLE_MODELS="role=model,role=model"` pins individual roles and wins over tier settings.
- Reads happen once in `Config.from_env`, matching the existing read-once flag convention. Unknown tier envs are ordinary strings; a malformed `ROLE_MODELS` pair is ignored rather than guessed at.
- `missing_credentials` fails closed before any run when any resolved tier's provider key is unset. With the defaults, `OPENROUTER_API_KEY` becomes required even when `BUILDER_MODEL` points elsewhere.

## 4. Fingerprint and trace integrity

- Calibration (`calibration.fingerprint`), suite identity (`evaluation.suite_for`), admission (`admitted`) and the frozen build manifest now bind to the resolved tier map, not `builder_model` alone. Changing any tier's model invalidates prior calibration — same rule as changing the single model before this ticket.
- `adk._request` resolves the model per role and records it in the `ADKModelCall` span and `model_usage` event; per-tier token totals are therefore already publishable by the existing dashboard allowlist (numeric token fields per `model`). No new artifact system.
- Provider prefix routing (`modal/`, `doubleword/`, `qwencloud/`, `openrouter/`, LiteLLM passthrough) is unchanged and applies to whichever model a role resolves to.

## 5. Acceptance tests

| ID | Test | Passing evidence |
|---|---|---|
| TIER-01 | Default tier map | Hard roles resolve to `BUILDER_MODEL`; medium/easy resolve to the documented defaults. |
| TIER-02 | Env overrides | `MODEL_TIER_*` replaces a tier; `ROLE_MODELS` pins one role over its tier; unset envs fall back cleanly. |
| TIER-03 | Credential check | Missing OpenRouter key with default tiers fails closed; mixed providers require the union of keys. |
| TIER-04 | Per-role routing in `adk` | `_request` sends each role to its resolved model; the span/usage events carry the resolved model name. |
| TIER-05 | Fingerprint invalidation | Changing one tier's model changes calibration/suite fingerprints and breaks `admitted`. |
| TIER-06 | Existing suite green | All current tests pass unchanged; fixture-role fakes are unaffected because they never touch `ADKRoles`. |

## 6. Definition of done

All roles route through the tier map with the defaults above; overrides and the credential check work; fingerprints bind to the full model map; the trace records the serving model per call; tests TIER-01…06 pass alongside the existing suite; README and env examples document the tiers.
