# Runtime contract

The kit's `docs/workflow-format.md` and `docs/tools-and-code.md` are authoritative. The compiler
supports only `conversation`, `api_request`, `code` and `end_call`, and rejects unsupported fields
even where the server would silently strip them.

- **Source and compiled workflow.** Models write and edit a compact source. `compile_workflow`
  turns it into what Freya runs: bank tools expanded from the current tool API file, the `code`
  shorthand wrapped as a `code_exec` action, engine-run stages made silent passthroughs whose last
  `always` transition is the fallback, and the runtime support compiled in. Nothing in that step
  adds or changes policy.
- **Bank tools.** URL, method, body types and enums, required fields and zero retries are owned by
  the controller and checked against the contract. An engine-run call needs a binding for every
  required field; a conversation tool leaves unbound fields to the dialogue model.
- **Identity.** Read from the routes, not declared: every route to `get_account` or
  `create_promise` must pass a `verify_identity` call and afterwards a transition that tests a
  variable not filled from the caller's speech (a mapped response, the flattened response, or a
  status that code derives from it). A second identity call resets that proof.
- **Closing.** `close_call` is alone in an engine-run stage, no bank tool is reachable after it,
  and no end stage is reachable without it.
- **Code.** Generated Python imports only `json`, `re` and `datetime`, has a fallback on error and
  uses call variables, never the clock. Business-day arithmetic and spoken-date resolution are
  controller helpers (`ctl_*`) whose calendar parameters the generated code takes from its brief.
- **Platform.** A dry run checks the platform schema. Deploy reads the stored workflow back and
  checks every submitted field survived; added defaults are allowed. Each simulated run must report
  the published `agentVersionNumber`; a missing or stale version invalidates the measurement.
- **Evidence.** Each practice repetition calls the kit runner's `run_once`, which opens fresh
  synthetic bank sessions; its ledger and conversation verdicts are authoritative and never
  re-judged. Static checks cannot prove speech, policy or a bank record.

Observed platform discrepancies: the live schema rejects `loop_prompt` although the format
document lists it; `response_mapping` stores scalar fields only; a `date` extraction is resolved
against the real clock, not the call's `now`.
