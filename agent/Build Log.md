# Ticket 1 Build Log

All implementation, test outputs, dependencies and runtime artifacts stay in `agent/`. The rest of the kit is read-only input.

## Batch 1 — Scope and initial audit

- Read the README, ticket sections 0–9, existing builder, Freya client, public runner/scorer and example skill; inventory the whole repository.
- Confirmed no applicable AGENTS.md; loaded the ponytail implementation skill.
- Confirmed the existing goal matches this task. Ticket is a complete ADK builder/search/evaluation pipeline, not a single phone-agent prompt change.
- Identified stock runner writes at kit root and unconstrained shell access in the existing builder. New controller must contain writes under `agent/` and expose no shell to generated agents.
- Continuing full brief/document/API review before implementation. No live benchmark success claimed.

## Batch 2 — Full source audit and scaffolding

- Read both briefs in full, all three runtime/API documents, the full ticket, actual OpenAPI, all Python sources, base workflow and all 13 practice cases.
- Recorded file SHA-256s, client signatures, actual bank operation schemas and runner behavior in `docs/kit-audit.md` and `docs/kit-files.json`.
- Verified Freya workspace connection using existing credentials; no credentials printed. Installed ADK 2.11.0 and runtime dependencies are available; recorded exact dependency versions and closure lock.
- Added agent-only path enforcement and removed model shell/file-write capabilities. Environment precedence is process > agent/.env > kit/.env.

## Batch 3 — Compiler, archive, scoring and controller

- Implemented provenance/precedence validation, OpenAPI reference resolution and contract-owned tool expansion. Unsupported contracts fail explicitly.
- Added strict Freya placement, route, identity gate, closing, mapping, retries and code checks. Static validation explicitly does not prove conversational policy.
- Added immutable workflow/proposal snapshots, SQLite lineage, durable trace/events, checkpoints, safe export paths and optional LangSmith spans.
- Added strict all-repetition scoring, unknown handling, matched-suite group advantages, hard-failure veto and explicit feedback allowlists.
- Added isolated tool-free ADK analyst/designer/compiler/mutator/diagnosis sessions and bounded build/search/export controller.
- Added real Freya adapter using inspected kit client/runner functions, version verification, serialization, fresh practice sessions and contained state.
- Launched a live build on Brief A with the PUB-01/PUB-03 smoke suite; awaiting actual results. Launched unmodified stock workflow startup smoke separately under the shared lock.

## Batch 4 — Verification and feedback experiment

- 29 local tests pass, covering compiler failures, hidden-style changed contracts, source overrides/conflicts, strict rewards, zero variance, unsafe/cross-suite ranking, archive tampering, crash restoration, secrets and telemetry outage.
- Controller integration test executes both feedback modes from the same pinned root with independent fake deployments and lineages. Sentinel is absent from scalar mutation payloads and visible only in the diagnostic fixture field.
- Real process lock test confirms serialized critical sections. All fake outputs are isolated under test folders and removed after tests.
- Added sequential paired-experiment CLI with shared frozen baseline support and honest unknown reporting. No mocked result is claimed as a real benchmark pass.

## Batch 5 — Live integration findings and corrections

- Stock example deployed/published and returned speech through real Freya chat. Its exact exported snapshot and smoke evidence are in `artifacts/stock-smoke/`; this is startup evidence only.
- Original GLM builder request hit its 300-second bound. A capped low-reasoning request succeeded; the provider catalog confirmed both GLM and Flash availability. Flash connectivity returned in about seven seconds.
- Retried the builder with Flash using environment configuration, preserving Freya's mandated phone model. The analyst returned a document but omitted empty `must` lists for prohibition-only rules.
- Fixed the generic schema to default empty obligation lists while requiring at least one obligation; raw model responses are now saved before structured validation. Retrying the actual build.
- Strengthened gate response provenance, positive boolean checks, snapshot tamper checks, and hook capability restrictions after rereading the ticket and implementation.
- Added source-derived code probes in a time-limited capability-restricted subprocess, optional held-out speaking-style repetitions, and a recovery CLI.
- 35 local tests pass. Missing observations now reduce coverage even when another repetition already proves failure. No incomplete suite receives a numerical strict reward.
- User asked to continue. Continuing with local traces; no LangSmith credential is currently configured, so remote receipt remains unverified.

## Batch 6 — Provenance and ADK runtime review

- Actual unfamiliar-fixture analyst correctly rejected a contradictory brief/API retry limit. Preserved that API as `tests/fixtures/conflicting-openapi.json`; corrected the success fixture and reran.
- Actual Brief A analyst produced 51 source-backed requirements after a citation correction. Added safe expansion of ellipsized quotes only when every quoted fragment exists in order inside the cited lines.
- Actual designer startup exposed ADK interpreting Freya double-brace examples as session-state variables. Switched instructions to an InstructionProvider callable after inspecting installed ADK behavior; added a regression test.
- Added `--resume-run` for matching-source compilation recovery and now persist validated requirements before design. Resumed both live runs using validated analyst artifacts; no workflow/policy hand edits.
- Added implementation source snapshots and exact dependency lock copies per new run so later general bug fixes do not erase run reproducibility.
- Diagnostic references now resolve against actual supplied evidence. Added rejection of forged verification responses and unknown tool bindings.
- Added separate recovery CLI and documented supported runtime boundaries, budget behavior and evidence limitations. Continuing actual workflow generation and acceptance checks.

## Batch 7 — Recovery verification and live-run follow-up

- Rechecked ticket acceptance tests and P0 completion gates against the implementation. Live policy, evolution, paired comparison and LangSmith evidence remain outstanding.
- Added recovery of a previously verified actual export of the exact champion if final remote restoration fails. Reports explicitly distinguish cached export from successful remote restoration.
- Verified all 40 local tests pass, including the final-export outage regression. Updated recovery documentation to match behavior.
- Confirmed both resumed live designer processes are still running; their results remain pending. No generated baseline or benchmark pass is claimed.
- Verified Git changes remain confined to `agent/`.
- Actual unfamiliar-input designer returned a 13-node proposal; static validation rejected unproven/forged identity gates and inadequate tool descriptions. Automatic repair is running; no unsafe proposal was deployed.
- Repair calls now receive the authoritative runtime documents just as the initial designer does. Added `docs/acceptance-status.md` to track local versus live evidence for all acceptance checks.
- Brief A's streaming designer timed out after 480 seconds with no candidate or deployment. Attempted a non-streaming retry reusing validated requirements.
- Automatic approval review rejected that retry because outbound brief/contract/workflow payloads to NVIDIA/Freya were considered insufficiently authorized. Asked for explicit approval identifying the payloads and services; no workaround attempted. Local review continues.
- User explicitly approved live validation and asked to finish quickly. Resumed Brief A with the non-streaming path, a bounded 600-second model call, two sibling proposals and four simulation slots. The 1,800-second per-build ceiling remains enforced.
- Re-ran the 40-test suite after supplying repair runtime documentation; all pass. Whitespace check passes.
- Fixed fresh-checkout test setup to create its contained artifact directory. Clarified that model-generated bank tools must use compact contract references, avoiding redundant request-schema output and reducing generation latency.

## Batch 8 — Live validator correction and fast resume

- Unfamiliar generation completed its bounded repairs but exposed a false rejection: an OR condition combining the declared mapped gate and its canonical API response was treated as unguarded.
- Updated proof checking to recognize only those two equivalent response variables. Both retain initialization/extraction/forgery restrictions. Added a positive alias regression and a negative forged-initial-value assertion.
- Revalidated the unchanged final generated unfamiliar proposal: all 13 nodes and seven source rules pass static validation. No generated policy was hand-edited.
- Resume now loads the latest source-matched structured proposal and reruns validation/probes instead of regenerating the full workflow. Added a test verifying zero model calls for valid resumed compilation.
- Resumed the unfamiliar run at code probes/deployment under the user's explicit live-validation approval. Brief A's non-streaming generation remains in progress.
- Live probe generation exposed invalid test metadata in expected variables and probes targeting API hooks. Stopped that run's unnecessary repair call. Probe generation now receives only code nodes, has a separate rationale field, and validates target/output keys before any workflow repair.
- Added a regression rejecting explanatory metadata and non-code probe targets. All 43 tests pass. Restarted unfamiliar validation from the unchanged saved proposal with the corrected test boundary.
- Six of seven regenerated code probes passed; the remaining expected deadline incorrectly used a source-excluded holiday. Added a separate source-only referee that cannot see code or observations and must recalculate/correct expectations before freezing tests. Stopped the repair based on that invalid oracle.
- Added a referee-isolation regression; 44 tests pass. Resume can now recover an immutable baseline/compile-repair snapshot with hash verification and reuse probes for source-only review, without redoing generation.

## Batch 9 — Actual platform schema integration

- Reviewed unfamiliar code probes passed and the generated root reached real Freya dry-run. Freya rejected `loop_prompt`, contrary to its supplied documentation. Recorded this observed discrepancy and reject the field locally.
- Moved real dry-run into the bounded compilation repair loop before pinning the root. Added a regression proving three rejected proposals cannot deploy or become pinned roots.
- Brief A's non-streaming GLM call also reached its 600-second timeout without producing a workflow. Preserved the failed trace; no success claimed.
- Inspected the configured NVIDIA model catalog and selected available Nemotron Super for the next validation attempts to avoid repeating GLM timeouts. Defaults and the prescribed Freya phone model remain unchanged. GLM-specific request options now apply only to GLM models.
- Resumed unfamiliar compilation and Brief A generation on the same user-approved NVIDIA endpoint. All writes remain under `agent/`.
- Alternate model outputs exposed malformed JSON and output truncation from a large reasoning allocation. Verified NVIDIA JSON mode with a tiny real request (HTTP 200), enabled it, and used documented Nemotron non-thinking mode for bounded generation. Stopped obsolete retries and restarted with those settings.
- Provider references: https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard and https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/deploy. Local suite: 46 passing tests.

## Batch 10 — The fixing stage rebuilt

- Ten live builds: 19 repair attempts with 1 success, 12 of the failures on the declared identity
  gate; mutations of ~10 KB per stage for 5–15 changed lines; sibling ranking computed once in six
  groups; probes with three false alarms and no real bug.
- Replaced by one loop: a compact workflow source that every model call sees, one patch format of
  field-level edits used for compiler fixes and for improvement, one fix call that reads failed
  calls step by step, one child per round, and each fix kept or blamed on the customers whose calls
  visited the stages it edited. Wording-only edits are committed without a simulation.
- Identity is checked on the routes themselves and the error prints the route. Business-day
  arithmetic became controller helpers; the probe machinery, feedback modes, beam and ranking,
  held-out revalidation and the paired experiment were deleted.

## Batch 11 — First live build on the rebuilt loop, and a logic review

- The first live build scored 0 of 10. Two causes, both mine: a new helper was named like a
  variable of the injected prelude, so every business-day call failed once a spoken date had been
  resolved; and the rewritten design rules allowed bank tools in conversation stages again, so
  identity ran through a model-called tool with unnormalised dates. Prelude variables now carry
  their own prefix, bank tools must be engine-run, and an identity route with one spoken
  alternative is no longer accepted as proof.
- Review of every path afterwards. Fixed: a leftover simulation or a held lock could end a build
  with no export (the lease is gone, the lock no longer raises); a provider error in any model call
  ended the build (one more try, then handled like a bad answer); a dry run that got no answer
  counted as a rejection; descriptions and routing prompts counted as wording although the router
  and the extractor decide by them; the last wording round could be shown another candidate's
  calls; a fix that only stood on a blamed one was reported as kept; a year said in words was
  replaced by the call's year; and a brief from outside the kit was silently built against the
  kit's tool API when none was given.
