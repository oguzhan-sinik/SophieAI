# TICKET-03 — Freya Builder Observability Studio: Live Traces, Workflow Lineage & Candidate Forensics

**Status:** Implementation-ready engineering ticket  
**Priority:** P0 for operational visibility and debugging; implement after Ticket 01 instrumentation and **before Ticket 02** if desired  
**Project:** Freya “Build the Builder” hackathon, kit v3 (10 October 2026)  
**Scope:** Browser-based **HTML observability platform** over durable JSON/JSONL artifacts  
**Integrates with:** `ticket-01.md` (required: ADAS → evolutionary workflow search → GRPO-inspired benchmarking) and `ticket-02.md` (optional/later: generalization, adversarial scenarios, suite partitions, anti-overfitting)  
**Existing runtime:** Python 3.10+, Google ADK, Freya-hosted phone workflows, LangSmith  
**Suggested UI stack:** React + TypeScript + Vite, `@xyflow/react` for interactive graph, ELK.js for layout, FastAPI + Server-Sent Events (SSE) for the read-only artifact server. These are **implementation recommendations**, not Freya requirements.  
**Primary deliverable:** `python -m builder.observability.serve` launches a local web dashboard showing a synchronized live trace navigator, detailed execution inspector, and **complete** candidate evolution tree for every builder run. No hosted account and no database server required.

> **Source alignment:** The contracts in this ticket are based on the existing `ticket-01.md`, `ticket-02.md`, the six supplied Freya kit docs (`README`, `api.md`, `workflow-format.md`, `tools-and-code.md`, Brief A, Brief B), and the user's three-column UI sketch. Ticket 01 already specifies immutable workflow snapshots, `artifacts/<run_id>/lineage.jsonl`, `manifest.json`, `candidates/`, `evaluations/`, `build_trace.log`, and LangSmith instrumentation. Ticket 02 adds split-restricted synthetic scenario suites, oracle evidence classes, and sealed validation/holdout storage. **This ticket reads and enriches those sources; it must not invent success scores, fabricate spans or expose sealed data.**

---

## 0. Why this ticket exists

Our builder iteratively creates a Freya phone agent, benchmarks it, uses optional referee feedback, and mutates the agent to improve bank-state, policy, and honesty outcomes. We need to **see what the builder actually did**, not just the champion score:

- What did the ADAS agents receive as prompts? What exactly did they return?
- Which ADK agent or deterministic service ran each step? Which tools were invoked with what redacted arguments and returned what data?
- When and why did a parent workflow spawn a new child?
- How did a child's Freya workflow differ from the parent? Was a route, prompt, code node, API tool, or guard changed?
- Which brief rules motivated the change and which tests exercised it?
- What was the actual evidence for benchmark scores, failures, unknowns, elapsed time, and GRPO-style relative advantage?
- Which workflow/version was published and evaluated, and was the eventual champion truly restored and exported?
- Are we making progress, looping without improvement, waiting on the single Freya simulation slot, or heading toward the 30-minute time limit?
- When Ticket 02 generates new cases, what kind of tests did it generate, how novel were they, and what evaluation **evidence class** supports the results?

**One-line product promise:** Open one URL and watch the entire builder run unfold; click any execution trace or tree node and reconstruct the exact, evidence-backed story of what happened.

### 0.1 The user's layout is the starting point (do not redesign away)

```
┌────────────────────────┬───────────────────────────────────────────────┬──────────────────────────────────────────┐
│ LEFT — TRACES          │ CENTER — DETAILS / INSPECTOR                  │ RIGHT — FULL EVOLUTION TREE              │
│ ~16–22%               │ ~48–56%                                       │ ~26–34%                                  │
│                        │                                               │                                          │
│ Run picker             │ Breadcrumb: Run / Candidate / Span            │ Zoom, pan, fit, search                   │
│ Live indicator         │ Context header + status                        │ Root workflow                            │
│ Trace search/filter    │                                               │   ├── candidate A                        │
│                        │ Timeline / event details / raw JSON            │   │     ├── candidate C                    │
│ ADAS / brief compile   │ Prompt → response → tools → outcome            │   │     └── candidate D                    │
│ Root creation          │ Candidate creation explanation                 │   └── candidate B                        │
│ Mutation #1            │ Parent-child diff                              │         ├── candidate E                  │
│ Benchmark / referees   │ Scores, rule refs, linked cases               │         └── candidate F                  │
│ Relative rank          │ Workflow JSON, LangSmith links                │                                          │
│ Champion / export      │                                               │ All nodes retained, not just champion    │
│                        │                                               │ Node badges and selection highlight      │
└────────────────────────┴───────────────────────────────────────────────┴──────────────────────────────────────────┘
```

**Hard UX rule:** The tree always occupies the right panel as the main visual summary. The middle panel is the shared inspector for the selection from **either** the left trace navigator **or** the right tree. Clicking a tree node must show **what created that node**, not only a number and its current status.

---

## 1. Clear scope and non-goals

### In scope

1. Full local, self-hosted, read-only HTML observability UI.
2. Auto-refresh while a builder run is live, without manual page reload.
3. Display and persistently navigate **all historical and active runs**, with a first-class run-history picker, and show all candidate nodes (valid, invalid, proposed, archived, champion) and complete lineage relationships **within the selected run**.
4. Show nested spans/events and their prompt/response/tool/validation/evaluation details, subject to capture and privacy restrictions.
5. Explain a selected candidate's generation, mutation, parent diff, validations, tests, scores, and selection decision.
6. Access JSON artifacts and JSONL event logs directly; SQLite indexes are optional accelerators, not the only source of truth.
7. Deep links to a run, candidate, span, benchmark, and relevant LangSmith trace.
8. Ticket 02's synthetic-case metadata, evidence classes, split protection, and generalization reporting.
9. Replaying completed runs **as recorded timelines** (read-only playback, not rerunning model/tool calls).
10. A polished developer UI with loading, reconnect, stale, missing, and partial-artifact states.

### Explicit non-goals

- Replacing LangSmith or building a second tracing SaaS.
- Running live Freya phone calls from the dashboard (especially not a second concurrent simulation).
- Editing, deleting, executing, promoting, or publishing workflows from dashboard buttons in v1.
- Making sealed holdout/validation test payloads available to the optimizer or default dashboard view.
- Inventing prompt text, reasoning traces, transcript content, or scores that were not captured.
- Changing the Freya phone-agent model or creating extra Freya workflows for visualization.
- Implementing a new graph-search algorithm or benchmark scorer. Tickets 01/02 own those decisions.
- Retaining private credentials in browser-visible files, URLs, or telemetry.

---

## 2. Architecture and ownership boundaries

### 2.1 Components

```text
                             TICKET-01 / TICKET-02 SERVICES

    Google ADK agents            Evolution coordinator             Benchmark services
    Brief compiler              Candidates & mutations           Official and synthetic runs
    LangSmith instrumentation   Relative selection               Oracle and referee judgments
             \                           |                              /
              └────────────── append-only OBSERVABILITY EVENTS ─────────┘
                                        |
                                        v
                           Local durable artifact store
              artifacts/<run_id>/manifest.json + lineage.jsonl
              candidates/<id>/*.json + evaluations/<id>/*.json
              observability/events.jsonl + spans/*.json (new)
                                        |
                ┌───────────────────────┴─────────────────────────┐
                |                                                 |
       Read-only artifact indexer                         LangSmith links/export
       validates + projects events                        optional deep linking
                |
       FastAPI HTTP + SSE stream
                |
       HTML / TypeScript single-page application
              /              |               \
         Trace list      Evidence inspector       Lineage graph
```

### 2.2 Data ownership

| Producer | Owns | This dashboard does |
|---|---|---|
| Ticket 01 archive | `Candidate`, workflow snapshots, lineage events, champion pointers | Read and project as a complete graph; never edit source |
| Ticket 01 scorer | Strict per-case verdicts, group rewards/advantages | Show explicit score provenance/evidence, never recompute official scores |
| Ticket 01 Freya adapter | Workflow ID, agent ID, published version, simulation/call IDs | Display exact IDs and links when available; flag mismatches |
| Ticket 01 observability | ADK/Python spans and LangSmith IDs | Mirror sanitized content to local span artifacts; deep-link to LangSmith |
| Ticket 02 suite manager | Optimization/validation/holdout partitions, cases, suite hashes | Show only authorized metadata/aggregates; no unrestricted case-browser |
| Ticket 02 execution router | Actual evaluation evidence class (official, grounded Freya, transcript-only, local mock, static) | Visibly label the source on every displayed result |
| Ticket 03 bridge | Normalized dashboard event/spans schema | Write append-only presentation-specific artifacts without modifying outcomes |
| Ticket 03 server/UI | Indexed projections, search and browser state | Read-only; all view models derived from immutable stored evidence |

The **dashboard may display a trace** that the **optimizer may not consume**. This is still safe only if the trace is authorized for the human viewer and never routed back through optimizer tools, prompts, shared ADK sessions, or auto-generated mutation feedback. More importantly, sealed validation and holdout payloads should **not be served at all by default**, even to a browser on localhost.

### 2.3 Integration principles

- Builder performance wins: recording an event must not block workflow generation or cause the 30-minute job to fail if the UI is closed.
- Artifact-first: a run recorded without the dashboard present must be viewable afterward.
- Append-only source history: no existing candidate snapshot should change because a later candidate wins.
- Observability is not grading: missing trace data is shown as `not captured`, never interpreted as a failed or successful bank action.
- Correlation by identifiers rather than timestamp guesses.
- Versions first: displaying a Freya simulation against a candidate requires matching its recorded published workflow version.
- Retain the original tool/agent model boundaries: Google ADK builds; Freya executes generated phone workflows.

---

## 3. The three-pane interface (detailed requirements)

### 3.1 Global application shell

**Header (persistent):** product name `Freya Builder Studio`, run selector, brief name/hash prefix, stage/status, benchmark mode, elapsed/remaining budget, total candidate count, current champion, connections (local artifacts, LangSmith, Freya), live/pause state, last event timestamp. No credential information.

**Panels:** resize with drag handles; panel widths persisted in browser-local preferences only, not written to artifact logs. At 1440px default widths `20% / 50% / 30%`, with minimum practical sizes. For narrower screens use collapsible left/right drawers but retain all functionality; do not cut off tree inspection.

**Look:** dense technical workstation style, responsive, accessible contrast. Light/dark mode optional; legible code fonts and structured JSON. All long text wraps or scrolls independently, never destroys layout. Use obvious empty-state affordances.

**Status vocabulary:** `queued`, `running`, `succeeded`, `failed`, `unknown`, `skipped`, `timed_out`, `partial`. Candidate-specific states additionally `proposed`, `valid`, `invalid`, `evaluated`, `champion`, `archived`. Display truthful status legends; do not treat `unknown` as passed.

### 3.1.1 Historical run library and run switching (**P0**, not optional)

The left panel starts with a **Run History** selector above its trace tree; the persistent top header mirrors the active selection. A run is one independently recorded invocation of the Ticket-01 builder, not a candidate, Freya simulation, synthetic scenario, or LangSmith span.

**Required run-list experience:**

- On startup discover all `artifacts/<run_id>/` folders for which a valid manifest or recoverable event archive exists. Show current and past runs from disk, including completed, failed, interrupted, stale, partially captured, and live runs; surviving a backend/browser restart must not depend on an in-memory registry.
- Default to the **most recently active run** on first visit, unless the URL explicitly names a run. Never silently switch away from a run the developer deliberately selected merely because a newer run starts.
- Picker supports search, timestamp sorting (latest/oldest), optional filters for brief/hash, status, benchmark mode, and champion result/evidence class. Paginate or virtualize a large archive. Group by date or brief if helpful, but preserve a single unambiguous run ID.
- Every row displays short run ID, human-friendly time with timezone, brief label + source hash, active/completed/failed/stale status, benchmark mode (`scoring_only` or `scoring_with_diagnostics`), candidate count, champion ID and **recorded** score when present, duration, and source/trace-capture completeness. If not captured, display `unknown`, never `0`.
- Selecting a historical run **atomically changes the scope of all three panels**: left traces, center inspector and right lineage graph, plus header metadata, benchmark charts, playback cursor and SSE subscription. An old candidate/span ID from another run must never appear under the new run's scope, even if both runs reuse the same local candidate names such as `cand_0001`.
- Store selection in a shareable deep link `/runs/<run_id>?candidate=<candidate_id>&span=<span_id>`. Handle missing, deleted, malformed or unauthorized run IDs with a non-destructive error and a path back to history; do not fall back silently to a different run.
- Preserve separate UI view state **per run** for the current browser session (expanded traces, selected candidate, tree zoom/pan, filters and playback position). Switching back to an already opened run should restore that run's selection if its artifacts still exist; initial or unknown runs use a deterministic default (champion if present, otherwise root).
- Historical completed runs default to **read-only static inspection with optional recorded-event replay**; selecting them must not start Freya simulations, regenerate agent prompts or re-run the builder. An actually live run auto-updates only when that run is selected and live mode enabled.
- Allow a dedicated **Compare runs** action (P1) for side-by-side aggregate summaries, explicitly matched by brief/OpenAPI/suite hash and evidence class. Cross-run comparison must not merge the two candidate trees or imply score comparability when suites differ. The *run history picker itself is P0*.

**Run-isolation invariant:** All API requests, UI caches, event-stream subscriptions and links are keyed by `(run_id, entity_id)`, not just `candidate_id` or `span_id`. On run change, cancel in-flight reads, close the old `EventSource`, clear transient state, fetch the selected run's manifest + trace/tree snapshots, then subscribe to that run's stream if live. Reject late old-run responses; guard with a selection epoch or `AbortController`.

**Persistence and recovery:** Each run's `manifest.json` and immutable archive are authoritative. The observability service may maintain a rebuildable run index, but never rewrite the source archive. Determine final state from recorded terminal events/manifest; when unavailable show `interrupted/stale/unknown`, not fabricated completion. Run history remains navigable with zero API credentials or LangSmith availability.

**Developer workflow:** Start a builder run A; inspect A; start a second independent builder run B; switch to A to inspect its prompts, candidate tree and champion; switch back to B and watch updates; restart the dashboard and repeat. A and B must stay entirely isolated.

### 3.2 Left panel — **Traces** (execution navigator)

This is not a plain scrolling logfile. It is a searchable **nested trace explorer**, matching the user's sketch's narrow left column.

**Hierarchy example:**

```
Freya Build · Run 2026-10-10-A [RUNNING]
  00:00  Brief & OpenAPI Compile
     ├─ BriefAnalystAgent prompt/response
     ├─ Resolve Brief A/B overrides
     └─ OpenAPI Contract Compiler
  00:24  ADAS Baseline
     ├─ ADASDesignerAgent
     ├─ WorkflowCompilerAgent
     ├─ Local Freya schema validation
     └─ Root candidate created [cand_0001]
  01:05  Depth 1 / Sibling group g1
     ├─ Parent selection
     ├─ MutationDesignerAgent [cand_0002]
     ├─ Static validation [cand_0002]
     ├─ MutationDesignerAgent [cand_0003]
     └─ Relative ranking / champion updated
  04:31  Benchmark [cand_0002]
     ├─ Freya publish version 4
     ├─ Simulation / poll / cases
     ├─ Core score
     └─ Diagnostics (when enabled)
  09:45  Ticket-02 anti-overfit tests
     ├─ Generated scenario families
     ├─ Frozen suite selection
     └─ Evidence-class results
  16:50  Finalize / export
```

**Each row must show:** display name, role/type icon, start time or elapsed offset, duration, running/progress indicator, status, candidate association, error/warning marker, and compact token/cost indicator if available. Expand/collapse hierarchically with keyboard support. Search by agent name, tool, candidate, rule ID, Freya simulation ID, status, model, and error string; filter by stage, span type, success/failure, feedback mode, and candidate.

**Trace click behavior:** selects the span and opens its information in the center inspector. When the span belongs to a candidate, the corresponding graph node is outlined on the right but the graph's center is not forcibly moved unless out of view. Selecting a leaf should not hide its parent chain.

**Trace data tabs:** `Timeline`, `Model calls`, `Tools`, `Benchmarks`, `Errors`, `All`. The default remains hierarchical timeline. A row can display an expandable nested waterfall for long operations. New events are appended in order, not used to rebuild/reset the whole list.

**Live behavior:** auto-follow newest events when the user is near the bottom. If the user scrolled up or selected an old span, do **not** steal focus; display `N new events` and allow manual jump to latest. Preserve open groups, query filters, and selected span across refreshes.

### 3.3 Center panel — **Trace / Candidate Inspector**

**Mode A, when a trace/span is selected:**

- Breadcrumb: `Run > Stage > Span > Subspan`; IDs and timestamps.
- Summary row: status, duration, agent/service, model/provider (if applicable), candidate ID, generation, stage, input/output artifact hashes, tokens and cost estimate when available.
- Tabs:
  1. **Overview:** one-sentence purpose, structured execution status, parent/child spans, error and retry explanation, linked artifacts.
  2. **Prompt / Input:** exact **captured, sanitized** system/developer/user messages or tool request inputs, with roles and code blocks. Show template version and variables if they were saved.
  3. **Response / Output:** exact **captured, sanitized** model output/structured JSON, parse results, errors, validation issues. If not captured, say so.
  4. **Tool calls:** time-ordered tool name, handler, redacted arguments, returned payload/status, retries/timeouts; label ADK tools vs Freya phone workflow tools.
  5. **Timeline:** child span waterfall; model calls → parsing → validation → persistence → execution.
  6. **Raw JSON:** immutable stored normalized event + artifact reference, pretty/prism rendering, safe copy/download of sanitized content.
- Display step-by-step events without assuming every ADK SDK internal callback is available. Explicit instrumentation is required.

**Mode B, when a candidate tree node is selected:**

- Header: `cand_0007`, generation/depth, parent, mutation family, status, creation time, duration to create, workflow SHA, Freya workflow/agent version, sibling group ID, current champion comparison.
- A conspicuous **“How this candidate was created”** section with **the full creation chain**:
  `parent selected → optimization request → ADK mutation prompt → model return → semantic patch → compiler → validator → archived child → deployed/published? → benchmarked? → ranked?`.
- Show the **actual reason the parent was selected** (beam policy, diversity quota, rank, or fallback), the **mutation hypothesis**, target node(s), targeted rule IDs, selected feedback visibility mode, expected effect, and observed effect after benchmarking.
- Expandable **Parent → Child Difference**:
  - `system_prompt`, `task_message`, `routing_prompt`, `loop_prompt`, `extraction_schema` deltas.
  - Added/removed/renamed workflow nodes; changed transitions and route priorities.
  - Code node/hook diff in syntax-highlighted unified diff, redacted if needed.
  - Tool attachment, parameter, default, enum, response mapping, or guard changes.
  - Graph summary: e.g., `+2 nodes / -1 transition / 3 prompt changes` (computed, not invented).
  - Source artifacts and SHA hashes for both versions; tree history must remain immutable.
- **Evaluation tab**: all linked evaluations, official vs proxy/evidence class, suite and split, repetitions, strict pass/unknown/fail counts, subverdicts (bank-state/policy/honesty), runtime, cost, relative group reward/advantage (if recorded), diagnostic record when authorized.
- **Failure and repair tab**: targeted rules with source excerpts/references, evidence-backed errors, referee judgments, suggested changes **only if `scoring_with_diagnostics` and optimizer-visible**, and what was actually changed.
- **Workflow tab**: embedded read-only Freya workflow graph or structured `workflow.json`, plus raw export; do not mistake the builder evolution tree for the phone-agent's internal conversation graph.
- **Provenance tab**: run/branch/group IDs, prompt/model hashes, input brief/OpenAPI hashes, all artifact refs, saved LangSmith trace URL, Freya published `agentVersionNumber`, deployment/restore/export events and timestamps.
- A **“Compare to parent”** button (read-only), plus optional `Compare to champion/root/another candidate` selection in v1.1.

**Critical differentiation:** The right-panel **candidate lineage tree** represents **versions of whole Freya workflows**. The candidate inspector's optional workflow tab may contain a **separate graph of Freya dialogue/API/code nodes**, but should not swap or pollute the main lineage graph.

**Mode C, when a benchmark or synthetic case is selected:**

- Runner type, suite hash, split, evidence class, case ID only if authorized, repetition index, underlying published workflow version and reset/fixture status.
- Summaries of expected and observed bank-state outcomes **only when genuinely known**. Unknown and transcript-only scores must be labeled as such.
- For `scoring_only`, the human may inspect authorized optimization raw traces for debugging, but no hidden diagnostic fields may be fabricated or fed into the mutator. Provide an indicator of **optimizer-visible feedback** separate from **developer-visible evidence**.
- For Ticket 02 validation and holdout, display **only** released aggregate reports. Never offer a raw case/transcript/artifact URL unless the suite access policy explicitly allows release.

### 3.4 Right panel — **Complete evolutionary lineage tree**

The diagram must be interactive and legible. Implement with `@xyflow/react` (or an equivalent), automatic layered tree layout (ELK.js or Dagre), zoom/pan, fit-to-view, minimap, and selected node emphasis. Use SVG/canvas virtualization if needed for large trees, but **the data model must still contain all nodes**.

**Display:**

- Roots at top, children below; each parent→child edge is a workflow mutation (not an execution span).
- Preserve all candidates, including failed schema validation, archived, incomplete, and never-evaluated nodes. Do not show only current beam.
- Each node: short candidate ID, generation, status, strict score (if known), comparison evidence class, mutation-type glyph, optional group-relative advantage, tiny branch label.
- Champion badge (one prominent cue), currently deployed indicator, best-official vs best-proxy marker. These may refer to different nodes; never silently collapse them.
- Colors/shapes must distinguish good, bad, unknown, invalid, live; include accessible text labels and legend (color not sole signal).
- Hover tooltip: parent, created time, mutation kind, targeted rules, score type, safe summary, untested/unknown count.
- Click: select node; center shows creation record/diff/evaluations; left trace jumps/highlights to the candidate's creation span (without losing current filters; allow clear filter).
- Double-click (or separate control) to **focus subtree**; always provide `Show entire tree` / `Fit all` / breadcrumb to root. Filtering or collapsing nodes must show a **hidden node count**, never misleadingly imply missing candidates do not exist.
- Graph filters: depth, generation, mutation family, group, status, strict score range, evidence class, created time; text search by candidate ID/rule ID/agent tool.
- Layout stability: new children should be inserted without resetting pan/zoom. If automatic layout shifts existing nodes, animate gently and preserve the selected candidate anchor.
- Explicit graph data validation: unique IDs, parent existence, cycle prevention, duplicate hashes and orphan handling. Orphans become **visible warnings**, not silently hidden records.
- For 0 candidates show waiting state; for 1 candidate show a root; for hundreds or thousands of candidates maintain usability without hiding data from exports.

**Graph selection consistency:** trace→candidate and candidate→trace interactions should not create an infinite feedback loop. Maintain one shared `selection` object plus separate `hover` state, not independent drifting IDs in each component.

### 3.5 Top-level run detail and progress widgets

Show a compact run timeline aligned to competition phases:

- Stage 1: Brief/OpenAPI compile and ADAS baseline.
- Stage 2: Evolution expansion; depth and group progress.
- Stage 3: benchmark, oracle/referees, relative ranking, finalist tests.
- Ticket 02: synthetic generation and generalization coverage, when enabled.
- Final: restore → publish → export.

If present, display total elapsed, 30-minute deadline countdown, export reserve, active simulation wait vs run, candidates attempted/valid/evaluated, best strict score, official and proxy evidence-separated trend, model tokens and estimated cost. `Remaining` is inferred only from an actual run manifest budget and start; do not presume the timer began when the UI opened.

### 3.6 Keyboard, accessibility, responsive use

- Left rows and graph nodes keyboard reachable; `Enter` selects, arrows navigate hierarchical trace/graph where practical.
- `Esc` clears selection; `/` focuses trace search; `F` fits lineage; `L` toggles live-follow; `[`/`]` toggles side panels (document in Help).
- Visual focus outlines; screen-reader labels/status announcements for newly completed spans; avoid announcing every polled heartbeat.
- Copy buttons for candidate ID, artifact hash, sanitized prompt, tool JSON, LangSmith URL; never clipboard-copy secrets.
- Graph should degrade to a fully browsable hierarchical node list if canvas rendering fails or assistive technology cannot interact with it.

---

## 4. Core user journeys (these are acceptance-critical)

### Journey A — Watch the builder start from zero

1. User runs `python -m builder.observability.serve`, opens URL.
2. Dashboard lists historical and current runs from `ARTIFACTS_DIR`.
3. Builder runs `python3 builder/build.py ...` in another terminal; a run appears automatically.
4. Brief compilation and ADAS root steps are appended on the left; prompts/outputs appear when captured.
5. Root candidate appears on the right; right-click/selection displays its source and workflow snapshot in the center.
6. New child candidates, validations, Freya evaluations, and champion changes stream in without a reload.
7. Run completion shows exact exported workflow path/hash and builder trace path.

### Journey B — Diagnose a bad workflow mutation

1. Click a red/invalid candidate in the right graph.
2. Center immediately shows parent, originating mutation request, specific target rules and patch.
3. Open `Compare to parent` and see a failed `response_mapping`/route/code change.
4. Follow link to its schema validation error or benchmark case record.
5. Inspect responsible ADK prompt + response, tool call and validation; copy sanitized event JSON.
6. Return to graph; selection and viewport are preserved.

### Journey C — Understand a positive benchmark jump

1. Select a candidate with improved strict score.
2. Show matched sibling suite hash, evidence class, repetition policy, per-case results and GRPO-style group-relative advantage.
3. Show why current champion selected that candidate, distinguishing actual strict score from relative advantage and tie breakers.
4. Compare its workflow snapshot with parent and inspect which failure pattern was repaired.
5. If the winning metric came from mock-only data, prominently say **PROXY — NOT OFFICIAL PASS**.

### Journey D — Anti-overfitting experiment without leaking holdout

1. Expand Ticket 02 suite-generation spans.
2. See optimization family/strategy counts, case-count settings from `.env`, coverage gaps and evidence types.
3. See matched optimization suites for sibling comparisons.
4. Validation tab shows only released aggregate metrics and checkpoint count.
5. Holdout payload is unavailable during active search, even if someone constructs a guessed API URL.
6. After proper final freeze/release, show the allowed final report, with no mutation feedback route.

### Journey E — Inspect an old offline build

Start the server days later with no Freya credentials and `LANGSMITH_TRACING=false`. Choose a prior `artifacts/<run_id>/` directory. The dashboard reconstructs the complete tree from immutable snapshots and JSONL even if events were written before the dashboard was installed (limited detail must be identified as missing rather than hallucinated).

---

## 5. Canonical artifact contracts: normalized JSON on disk

### 5.1 Preserve Ticket-01/Ticket-02 existing directories

The dashboard **MUST read** the existing layout, not force a migration before any screen works:

```text
artifacts/<run_id>/
  manifest.json
  requirements.json
  tool_contracts.json
  lineage.jsonl
  lineage.sqlite                  # optional existing index
  champion.json
  champion.workflow.json
  build_trace.log
  candidates/<candidate_id>/
    workflow.json
    proposal.json
    mutation.json
    validation.json
  evaluations/<evaluation_id>/
    raw_runner.json
    core_score.json
    diagnostics.json              # if authorized/recorded
    evidence_index.json
  reports/
    coverage.json
    search_summary.md
  observability/                  # NEW, additive
    schema.json
    events.jsonl
    spans/<span_id>.json
    indexes/                      # generated projections; safe to rebuild
    blobs/                        # sanitized large captured inputs/outputs
    diffs/                        # derived semantic diff summaries
    session.json                  # optional writer/runtime heartbeat
  synthetic/                      # Ticket-02 split-restricted; do not recursively serve by default
    ...
```

Ticket 02 may use `artifacts/synthetic/` at project root instead of a run-local directory; support both as references, but **never automatically expose its raw files**.

**Migrate lightly:** If Ticket 01 has already shipped event/spans of the same semantic meaning in another shape, write a read adapter and optionally a normalized sidecar. Avoid rewriting original `lineage.jsonl` or mutating existing `Candidate` records.

### 5.2 Normalized event envelope (`builder.obs.event.v1`)

Append one UTF-8 JSON object per line to `observability/events.jsonl`. Event boundaries are semantic, not each token. The core writer owns monotonically increasing `seq` per run. `event_id` is globally unique or deterministic from (`run_id`, `seq`); clients deduplicate by it.

```json
{
  "schema_version": "builder.obs.event.v1",
  "event_id": "run_20261010_a:00000142",
  "seq": 142,
  "run_id": "run_20261010_a",
  "time": "2026-10-10T18:41:12.351Z",
  "monotonic_elapsed_ms": 267351,
  "type": "candidate.created",
  "stage": "evolution",
  "severity": "info",
  "status": "succeeded",
  "span_id": "sp_mutate_0007",
  "parent_span_id": "sp_group_0002",
  "candidate_id": "cand_0007",
  "parent_candidate_id": "cand_0003",
  "group_id": "g2",
  "generation": 2,
  "summary": "Added an identity verification guard",
  "payload_ref": "candidates/cand_0007/mutation.json",
  "payload_sha256": "sha256:example-not-real",
  "visible_to_optimizer": true,
  "data_scope": "optimization",
  "langsmith_run_id": null,
  "metadata": {"mutation_kind": "add_guard", "targeted_rule_ids": ["R-IDENTITY-001"]}
}
```

**The sample is an illustrative Ticket-03 schema; not a payload verified from the Freya API.** Implement it as a Python Pydantic v2 schema plus generated TypeScript type/JSON Schema; avoid mismatched hand-maintained definitions.

Required event types (stable prefix family, extensible):

| Family | Required events |
|---|---|
| `run.*` | `run.started`, `run.configured`, `run.progress`, `run.completed`, `run.failed`, `run.cancelled` (if supported) |
| `brief.*` | `brief.parse.started`, `brief.rule.extracted`, `brief.compile.completed`, `brief.conflict.detected` |
| `agent.*` | `agent.started`, `agent.prompt.saved`, `agent.response.saved`, `agent.completed`, `agent.failed` |
| `tool.*` | `tool.started`, `tool.completed`, `tool.failed`, `tool.retry` |
| `candidate.*` | `candidate.proposed`, `candidate.created`, `candidate.validation.completed`, `candidate.archived`, `candidate.promoted`, `candidate.deployed` |
| `mutation.*` | `mutation.requested`, `mutation.generated`, `mutation.compiled`, `mutation.rejected` |
| `benchmark.*` | `benchmark.queued`, `benchmark.started`, `benchmark.completed`, `benchmark.failed`, `benchmark.scored`, `benchmark.diagnosed` |
| `referee.*` | `referee.started`, `referee.completed`, `referee.unknown`, `referee.failed` |
| `search.*` | `search.parent.selected`, `search.group.created`, `search.advantages.calculated`, `search.beam.updated` |
| `suite.*` | `suite.generated`, `suite.frozen`, `suite.selected`, `suite.summary.released`, `suite.leakage.blocked` |
| `freya.*` | `freya.dry_run`, `freya.workflow.updated`, `freya.version.published`, `freya.simulation.started`, `freya.simulation.completed`, `freya.export.completed` |
| `system.*` | `system.warning`, `system.error`, `system.heartbeat`, `system.artifact.corrupt`, `system.stream.reconnected` |

Only produce events for actions that actually occur. Missing typed event families in an older run are allowed; inferred summaries must be visibly marked `derived` rather than `recorded`.

### 5.3 Span object (`builder.obs.span.v1`)

One span describes a timed operation; the event stream records updates and points to this immutable or safely-finalized span object. Store in `observability/spans/<span_id>.json` via atomic replace, with explicit `revision` so clients can reload.

```json
{
  "schema_version": "builder.obs.span.v1",
  "run_id": "run_20261010_a",
  "span_id": "sp_mutate_0007",
  "parent_span_id": "sp_group_0002",
  "kind": "llm_agent",
  "name": "MutationDesignerAgent",
  "purpose": "Create a targeted Freya workflow mutation",
  "status": "succeeded",
  "start_time": "2026-10-10T18:41:01.000Z",
  "end_time": "2026-10-10T18:41:12.000Z",
  "duration_ms": 11000,
  "candidate_id": "cand_0007",
  "group_id": "g2",
  "model": {"provider": "configured-provider", "model": "configured-model", "prompt_version": "v3"},
  "input": {"capture": "redacted", "ref": "observability/blobs/input-0007.json", "sha256": "sha256:..."},
  "output": {"capture": "redacted", "ref": "observability/blobs/output-0007.json", "sha256": "sha256:..."},
  "tool_call_ids": ["tc_31"],
  "error": null,
  "tokens": {"input": 1890, "output": 573, "total": 2463},
  "cost_estimate_usd": null,
  "langsmith": {"run_id": null, "trace_url": null},
  "metadata": {"stage": "evolution", "feedback_mode": "scoring_with_diagnostics"},
  "revision": 1
}
```

`input.capture` and `output.capture` are explicit enums: `full_sanitized`, `redacted`, `hash_only`, `not_captured`. **Do not pretend that model private reasoning / chain-of-thought is available.** Log visible prompts, model responses, tool invocations and orchestration metadata only. When a provider redacts its internal reasoning, show `not available`.

### 5.4 Creation record (`builder.obs.candidate_origin.v1`)

Every candidate should have a creation record that allows the question **“what happened to create this agent?”** to be answered without reverse-engineering all spans. Create it at generation time and enrich with evaluation and ranking refs afterward; immutable revisions/sidecars preferred.

```json
{
  "schema_version": "builder.obs.candidate_origin.v1",
  "run_id": "run_20261010_a",
  "candidate_id": "cand_0007",
  "parent_candidate_id": "cand_0003",
  "generation": 2,
  "sibling_group_id": "g2",
  "selected_parent_reason": "beam + novelty quota",
  "creation_span_ids": ["sp_parent_select_2", "sp_mutate_0007", "sp_compile_0007", "sp_validate_0007"],
  "mutation": {
    "kind": "add_guard",
    "hypothesis": "Require verified identity before account lookup",
    "target_nodes": ["lookup_account"],
    "target_rule_ids": ["R-IDENTITY-001"],
    "proposal_ref": "candidates/cand_0007/proposal.json",
    "patch_ref": "candidates/cand_0007/mutation.json"
  },
  "parent_workflow_ref": "candidates/cand_0003/workflow.json",
  "child_workflow_ref": "candidates/cand_0007/workflow.json",
  "diff_summary_ref": "observability/diffs/cand_0007.json",
  "validation_ref": "candidates/cand_0007/validation.json",
  "evaluation_ids": ["eval_0014"],
  "selection_event_ids": ["run_20261010_a:00000158"],
  "workflow_sha256": "sha256:..."
}
```

The record must be treated as a **join/projection of independent facts**: if `evaluation_ids` are not yet known, show `pending` not empty verified. Produce deterministic derived views from existing Ticket-01 artifacts when sidecar creation is not available. Keep proposal, final patch, compiler output, and actual persisted snapshot distinct.

### 5.5 Evaluation view contract

Read Ticket 01's `core_score.json` and Ticket 02's `EvaluationRecord`. Normalize to a UI-facing `EvaluationSummary` without changing the canonical scorer:

```
{
  run_id,
  candidate_id,
  evaluation_id,
  suite_id, suite_hash, split,
  evidence_type,                       // official_public|freya_bank_grounded|freya_transcript_only|local_mock|static_only
  core_verdict,                        // pass|fail|unknown|not_run
  bank_state_verdict, policy_verdict, honesty_verdict,
  repetition_count, strict_all_repeat_pass,
  passed_count, failed_count, unknown_count, total_count,
  comparable_group_id, initial_state_hash, state_isolated,
  raw_score_ref, diagnostics_ref?,
  backend_fingerprint, freya_workflow_id?, freya_agent_id?, published_version?,
  runtime_ms?, observed_cost_estimate_usd?,
  captured_at
}
```

If a field does not exist, preserve `null`/`not_available` in the dashboard projection; never fill it with made-up values. One known limitation in the source briefs: `openapi.json` and kit runner source code were not attached when Ticket 01 was drafted. This ticket **does not assert exact runner payload fields**; adapter implementer must inspect them in the actual project.

### 5.6 Artifact index manifest (`builder.obs.index.v1`)

```
{
  schema_version, run_id, last_seq, indexed_at,
  candidate_count, span_count, evaluation_count,
  source_manifest_hash, lineage_jsonl_offset,
  events_jsonl_offset, projection_version,
  warnings: []
}
```

Index is **rebuildable**. Source files are authoritative; corruption of the index should never destroy lineage or evaluation history.

### 5.7 Correlation requirements

Propagate these **standard IDs** wherever applicable:

- `run_id`, `span_id`, `parent_span_id`, `event_id`, `seq`.
- `candidate_id`, `parent_candidate_id`, `generation`, `sibling_group_id`, `mutation_id`.
- `evaluation_id`, `case_id`, `case_family_id`, `suite_id`, `suite_hash`, `split`.
- `brief_sha256`, `openapi_sha256`, `workflow_sha256`, `published_workflow_version`.
- `freya_workflow_id`, `freya_agent_id`, `freya_simulation_id`, `freya_call_id`, `langsmith_run_id`.
- `benchmark_mode`, `evidence_type`, `trace_visibility_scope`, `model`, `prompt_template_hash`.

Do not use timestamps alone to associate Freya calls with candidate nodes. One live Freya workflow may be updated/published repeatedly; always record the snapshot hash and published version actually tested.

### 5.8 Safe artifact references and snapshots

Only store project-relative **allowlisted** references in server-visible records. Never blindly serve arbitrary absolute paths, `../` traversal, symlinks escaping `ARTIFACTS_DIR`, hidden `.env`, private keys, or restricted split files. Validate resolved paths against the run root and visibility policy. Long payloads may be stored separately (e.g. JSON/JSONL/gzip) and fetched on demand; use SHA verification and stable storage format.

Write JSON with temporary file + `fsync` where practical + atomic rename; write JSONL with a single serialization lock/queue (one complete line per append). Reader must ignore a trailing partial line until complete and show a warning for persistent malformed historic lines.

---

## 6. Instrumentation bridge: ADK, Freya, benchmark and LangSmith

### 6.1 Observability writer API (do not block business logic)

Implement a small Python package with typed methods:

```python
from typing import Protocol, Mapping, Any

class ObservationSink(Protocol):
    def emit(self, event_type: str, *, run_id: str, span_id: str | None = None,
             candidate_id: str | None = None, status: str | None = None,
             summary: str = "", payload_ref: str | None = None,
             metadata: Mapping[str, Any] | None = None) -> None: ...

    def start_span(self, *, run_id: str, parent_span_id: str | None,
                   name: str, kind: str, context: Mapping[str, Any]) -> str: ...

    def finish_span(self, *, run_id: str, span_id: str, status: str,
                    output_ref: str | None = None, error: str | None = None,
                    tokens: Mapping[str, int] | None = None) -> None: ...
```

- One process-local, bounded queue; background writer flushes to durable files in order. If saturation occurs, **do not lose critical events** (`candidate.created`, `benchmark.scored`, `champion.updated`, `freya.version.published`, `run.completed`). Degrade by dropping/reducing **verbose low-priority** token chunks with a recorded `telemetry.dropped` count. At process exit, flush within a bounded time, without violating competition export budget.
- Crash/restart: read last stable sequence from durable state and continue without duplicate event IDs; if recovery cannot guarantee monotonicity, create a new writer segment and event origin ID instead of silently reusing IDs.
- Errors in observability must be logged locally and must not cancel the builder unless **artifact correctness** itself is compromised; missing required submission trace cannot silently succeed.
- Avoid modifying core business logic just to display it. Wrap high-level service boundaries and model calls; use explicit agent callback adapters only where supported by actual Google ADK version.
- Record prompt/response payloads when configured and after redaction, not solely LangSmith trace handles.

### 6.2 Required span boundaries

```
BuilderRun
 ├─ BriefCompile
 │   ├─ BriefAnalystAgent.call
 │   ├─ RuleCompiler.parse/override_resolution
 │   └─ OpenAPICompiler.compile
 ├─ ADASBaseline
 │   ├─ ADASDesignerAgent.call
 │   ├─ WorkflowCompiler.compile
 │   ├─ FreyaDryRun
 │   └─ CandidateArchive.create(root)
 ├─ BeamExpansion(depth=N, group=G)
 │   ├─ ParentSelection
 │   ├─ MutationDesignerAgent.call
 │   ├─ MutationCompiler.apply
 │   ├─ StaticValidator
 │   ├─ CandidateArchive.create(child)
 │   ├─ EvaluationRunner
 │   │   ├─ FreyaPublish
 │   │   ├─ SimulationQueueWait
 │   │   ├─ SimulationRun
 │   │   ├─ DeterministicCoreScore
 │   │   ├─ RefereeJudgments
 │   │   └─ DiagnosisAgent.call (if enabled)
 │   ├─ GroupRelativeReward
 │   └─ BeamUpdate
 ├─ Ticket02SuiteGeneration
 │   ├─ RuleDrivenGenerator
 │   ├─ AdversarialCustomerAgent.call
 │   ├─ OracleValidation
 │   ├─ SuiteFreeze
 │   └─ SyntheticExecution / EvidenceClassification
 └─ ChampionRestore → FreyaPublish → ExportWorkflow
```

Span duration must distinguish simulation **queue wait** from actual case evaluation; no misleading elapsed calculations. Emit Freya `agentVersionNumber` from actual run evidence when available, not simply current dashboard version.

### 6.3 Prompt and response capture

Capture **if available and allowed**:

- The exact caller-visible ADK agent messages sent to the model, grouped by role.
- User-supplied brief excerpts as source paths/references; avoid duplicating entire briefing documents into every model span.
- Effective system/developer prompts as actually sent, plus prompt-template hashes/versions.
- Structured model response and parsing/validation exceptions.
- Tool registrations and invoked tool names with redacted arguments/results, retry count, status and latency.
- Model provider/name, temperature/seed if provided, token usage, provider-reported cost or explicitly labeled estimate.
- Sanitized Freya transcript and tool events, **only when authorized** and linked to published workflow version.

Do not claim access to model internal hidden reasoning, invisible provider system prompts, raw provider telemetry unavailable through the SDK, or redacted secrets. Show capture-quality badges: `full sanitized`, `redacted`, `hash only`, `not captured`.

### 6.4 LangSmith integration

- Reuse Ticket 01's LangSmith project and tracing; embed **exact LangSmith run/trace URLs returned/constructed from authorized IDs**, not speculative links.
- Trace/export connectivity is optional. Dashboard works if LangSmith is disabled, offline, slow, or incomplete.
- Bidirectional correlation via `run_id`/`candidate_id`/`span_id` in trace metadata where possible.
- No background ingestion of sealed holdout traces from LangSmith into the shared local cache. Respect Ticket 02's split access policy.
- Expose a LangSmith button only when an actual trace URL exists. A captured local span is valid even if the corresponding LangSmith trace is missing.

### 6.5 Freya integration realities (from uploaded kit docs)

- Freya workflow shape: `initial_node`, `nodes`, optional `global_nodes`, prompts and `tools`/`pre_actions`; code nodes and conversation nodes have different allowed fields. The candidate workflow tab can render structure from snapshots, but **must not send unapproved mutating calls**.
- Freya makes distinct extraction/routing/dialogue calls per phone turn; show separate stages only when underlying Freya execution event data exposes them. Do not synthesize per-turn internal calls from the prompt alone.
- A `PUT` creates an unpublished version. Tests run the published version; UI must visibly flag a mismatch between intended workflow hash/version and actual evaluated version.
- Live Freya practice simulations are serialized by workspace; display queue/wait status, not an inaccurate parallel progress indicator.
- Use official test runner's stored call IDs and `freya.get_call(call_id)` evidence when available; do not automatically fetch call payloads without explicit authorization/security checks.
- The bank's actual OpenAPI schema and runner source must be read in the local kit before interpreting any tool arguments or score payloads.

---

## 7. Backend: artifact discovery, projections, HTTP and auto-refresh

### 7.1 Recommended server

FastAPI + Uvicorn, launched locally with an explicit artifact root. `watchfiles` can detect writes, and a conservative polling fallback works on systems where filesystem watchers are unreliable (Docker mounts/network shares). Do not let a filesystem watcher run as a separate full-index scan for every appended line.

The backend is **read-only** for builder-owned files. It may maintain its own disposable projection cache under `observability/indexes/` or an application cache directory. It must not call Freya create/update/publish APIs.

### 7.2 Discovery and indexing

- Watch **allowlisted `artifacts/<run_id>` folders** containing a valid `manifest.json` or compatible archive.
- Detect live, completed, partial and corrupted run states by recorded events/manifest and writer heartbeat. `No update for N seconds` means **stale**, not necessarily `failed`.
- Parse `lineage.jsonl` incrementally; parse `observability/events.jsonl` incrementally by byte offset; maintain `seq` and artifact revision.
- Parse `.json` only after atomic completion; retry a partially written file with bounded backoff instead of discarding its candidate.
- Build normalized materialized views: runs, span tree, candidate graph, candidate origin, evaluation index, timeline and aggregate metrics.
- If a run was recorded by pre-Ticket-03 code, reconstruct a **best-effort** graph and summary using Ticket 01 source files; distinguish `derived` and `recorded` fields.
- Recompute projections from scratch on index corruption or schema-version upgrade without modifying source artifacts.
- Use stable deterministic sort (`seq` primary; timestamp secondary only for other sources) and duplicate suppression.
- Handle symlinks and path traversal defensively. Never discover a `synthetic/holdout` directory recursively just to index more JSON.

### 7.2.1 Durable run catalog and historical selection

- Build a catalog from the artifact root at every cold start and incrementally maintain it via watcher/poll fallback. Persist indexing acceleration only in a **disposable cache**; source run folders remain the source of truth.
- Canonical run ID must match the folder's validated manifest ID; reject duplicated/conflicting IDs and untrusted names with an explicit catalog warning. Support partially written manifests as `discovering` only once there is a safe validated run identity.
- Run timestamps are stored as timezone-aware ISO 8601 strings; sort primarily by most recently recorded activity and secondarily by start timestamp/run ID. Do not equate local browser timezone with event timestamp zone.
- API paging/filtering/sorting must happen server-side, e.g. `GET /api/runs?limit=25&cursor=...&status=completed&brief_hash=...&sort=recent`; return `items`, `next_cursor`, and a stable ordering key. Provide an optional `/api/runs/summary` for aggregated counts if needed.
- Normalize archive version differences into a common `RunSummary` contract with: `run_id`, `started_at`, `ended_at?`, `last_event_at?`, `status`, `brief_label?`, `brief_hash?`, `openapi_hash?`, `benchmark_mode?`, `candidate_count?`, `champion_candidate_id?`, `strict_score?`, `score_evidence_class?`, `artifact_schema_version`, `capture_completeness`, and `warnings[]`.
- Archived run artifacts must remain available independently of the process that generated them. Do not automatically delete artifacts, and add no retention policy that silently erases historic runs.
- Cache keys for detail, graph layout, spans, evaluations, and SSE cursors use the composite run namespace. Request cancellation and cursor/stream cleanup are required on run switch; ensure late network results cannot overwrite the newly selected run.

### 7.3 API contracts (suggested local routes, to implement)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Server, watcher, last index, schema compatibility |
| `/api/runs` | GET | **Durable historical run catalog**: paginated, sortable/searchable runs with status, brief, mode and summary filters |
| `/api/runs/{run_id}` | GET | Sanitized run manifest, budget, champion pointers, progress |
| `/api/runs/{run_id}/tree` | GET | Full list of candidate nodes and parent edges; graph metadata |
| `/api/runs/{run_id}/candidates/{candidate_id}` | GET | Candidate creation record and safe linked artifact summaries |
| `/api/runs/{run_id}/candidates/{candidate_id}/diff` | GET | Typed and textual workflow diff to parent or authorized comparison |
| `/api/runs/{run_id}/spans` | GET | Paginated/filterable nested spans; no huge prompt blobs inline |
| `/api/runs/{run_id}/spans/{span_id}` | GET | Sanitized span content and safe payload refs |
| `/api/runs/{run_id}/events` | GET | Cursor/seq paginated event replay |
| `/api/runs/{run_id}/evaluations` | GET | Authorized evaluation summaries with evidence classes |
| `/api/runs/{run_id}/evaluations/{id}` | GET | Authorized per-case evidence/metadata, split-filtered |
| `/api/runs/{run_id}/metrics` | GET | Derived run/candidate/trend metrics and provenance |
| `/api/runs/{run_id}/artifact` | GET | **Allowlisted opaque artifact ID** only, never user-supplied raw path |
| `/api/runs/{run_id}/stream` | GET (SSE) | Real-time `seq`-ordered event stream + heartbeats |
| `/api/preferences` | GET/POST optional | Local browser layout preferences only; no builder mutation |

JSON responses are versioned or advertise a schema version; HTTP errors use typed codes (`RUN_NOT_FOUND`, `ARTIFACT_RESTRICTED`, `ARTIFACT_MISSING`, `SCHEMA_UNSUPPORTED`, `INDEX_STALE`, etc.). Support request cancellation and pagination. For deep links, a single-page application route like `/runs/<id>?candidate=<id>&span=<id>` is sufficient.

### 7.4 SSE stream lifecycle

**Choose SSE over WebSocket for v1:** the server only pushes data to read-only browsers; SSE supports reconnection, event IDs, and straightforward reverse-proxy configuration.

Server rules:

1. Send a `snapshot`/handshake message with `run_id`, current indexed `last_seq`, projection version and timestamp. Client fetches the tree/spans snapshot by HTTP.
2. Then stream new `event` messages with their durable sequence IDs and a small payload.
3. Honor `Last-Event-ID` (or `?after=<seq>`) on reconnection; replay retained events in order.
4. Heartbeat/comment every ~15 seconds to keep the connection alive; no UI event must be generated for an empty heartbeat.
5. If a client is too far behind or a projection has been rebuilt, send `resync_required` and let the UI refetch snapshot. Do not silently skip events.
6. Buffer/backpressure per client; prevent a slow browser from blocking the writer or other viewers. Coalesce low-priority progress indicators while **preserving critical durable event replay**.
7. Polling fallback every 2–5 seconds on disconnected SSE; exponential backoff and clear `Disconnected / retrying` UI indicator.
8. The UI can toggle **Pause live rendering** while still buffering/catching up; it must not pause the underlying builder.

**Target**, subject to local testing: under typical development load a persisted event should become visible within **2 seconds**; no guarantee is implied under a saturated workstation or unavailable filesystem watcher.

### 7.5 Safe caching and bounded payload size

- Initial tree and trace list endpoints return lightweight summaries; long model texts load only on detail selection.
- Prefer queryable span index over shipping entire `events.jsonl` to the browser.
- Impose configurable `OBS_MAX_ARTIFACT_READ_BYTES` and truncated-display notice for huge prompts; enable paginated/chunked retrieval of authorized large evidence. Do not silently drop the end of a model output.
- Use ETag / `last_seq` / stable artifact hashes for cache validators; mutation of a source after its hash has been recorded raises provenance warning.
- Render arbitrary JSON as **text**, not trusted HTML. No `dangerouslySetInnerHTML` for model outputs.

---

## 8. Frontend implementation plan

### 8.1 Component tree (suggested)

```text
AppShell
├─ RunToolbar
│  ├─ RunSelector
│  ├─ ExecutionStatus + BudgetClock
│  ├─ BenchmarkMode + EvidenceLegend
│  └─ LiveConnectionIndicator
├─ ResizablePanels
│  ├─ TraceSidebar
│  │  ├─ TraceFilters + Search
│  │  ├─ HierarchicalSpanList (virtualized)
│  │  └─ LiveTailButton
│  ├─ MainInspector
│  │  ├─ SelectionBreadcrumb
│  │  ├─ RunOverview | TraceInspector | CandidateInspector | EvaluationInspector
│  │  ├─ PromptViewer / ResponseViewer / ToolCallViewer
│  │  ├─ TimelineWaterfall
│  │  ├─ CandidateOriginStory
│  │  ├─ WorkflowDiffViewer
│  │  ├─ BenchmarksAndEvidence
│  │  └─ RawJsonViewer
│  └─ LineageSidebar
│     ├─ GraphControls + Legend
│     ├─ CandidateLineageGraph
│     ├─ GraphMinimap
│     └─ AccessibleNodeListFallback
├─ GlobalToast/WarningPanel
└─ MissingData / Error / Reconnection States
```

### 8.2 State model

Prefer a central run-scoped store (e.g. Zustand or React context with targeted selectors). Keep UI state distinct from persisted event data:

```ts
type InspectorSelection =
  | {kind: 'none'}
  | {kind: 'run'; runId: string}
  | {kind: 'span'; runId: string; spanId: string}
  | {kind: 'candidate'; runId: string; candidateId: string}
  | {kind: 'evaluation'; runId: string; evaluationId: string};

type LiveState = {
  connected: boolean;
  paused: boolean;
  lastSeq: number;
  latestKnownSeq: number;
  lastEventAt: string | null;
  needsResync: boolean;
};
```

Selection updates URL query state for copyable deep links, but never puts raw prompts, account data, bearer tokens, or test payload in the URL.

### 8.3 Graph layout

- Compute layout asynchronously (worker if needed) using ELK's layered `DOWN` mode; deterministic node ordering by creation sequence.
- Node dimensions measured/estimated consistently; edges point parent→child.
- On incremental addition, preserve existing coordinate positions where possible and place new descendants near their parent; a full layout can be invoked by `Relayout`.
- Render semantic zoom: zoomed out = compact ID/status/score glyph; zoomed in = title + details. Do not unload nodes from data.
- Minimap, fit selection, fit all, show root→selected path, compare nodes, graph-level error warnings.
- A run with multiple roots should show a **forest** and warning if roots are unexpected, rather than discarding any.
- Cycles are invalid for a lineage tree: flag them and refuse that edge in the layout while preserving source error evidence.

### 8.4 Workflow diff implementation

Compute both:

1. **Semantic Freya diff:** compare `initial_node`, `nodes`, `global_nodes`, prompts, transitions, extraction schemas, code hooks, tool lists/config and supported top-level keys. Report precise paths and before/after values.
2. **Raw JSON/text diff:** path-aware JSON diff and syntax-highlighted side-by-side view for recorded workflow snapshots.

Normalize only irrelevant serialization differences (JSON key ordering), not meaningful order (e.g. transitions priority or tool order). If a semantic patch says it changed one thing but snapshots reveal additional changes, flag `PATCH/SNAPSHOT DRIFT`. If either parent/child snapshot is missing, show a missing-artifact state rather than generating a fictional diff.

### 8.5 Rendering JSON and prompts

- JSON tree with expand/collapse/search/copy plus readable formatted raw mode.
- Prompt viewer preserves message roles and delimiters, displays long multi-part content, and marks redactions.
- Tool timeline pairs start/result by `tool_call_id`, exposes retried calls, idempotency concerns and error text.
- For Freya transcripts, interleave caller utterances, phone-agent replies, bank tool operations, and judge evidence if recorded and authorized.
- Add top-level toggles between chronological sequence and span nesting.
- Display exact original workflow JSON from the candidate snapshot. Never silently render server-normalized graph as if it were the exported file.

---

## 9. Benchmark, reward, experiment and generalization visualizations

### 9.1 Score provenance is mandatory

Every displayed benchmark score needs:

- `candidate_id` and immutable workflow hash.
- Suite ID/hash, execution timestamp and selected cases/repetitions.
- Evidence type: `official_public`, `freya_bank_grounded`, `freya_transcript_only`, `local_mock`, or `static_only`.
- Core verdicts including `unknown` and `not_run` counts.
- When recorded: bank-state, policy, honesty subverdicts (same strict all-or-nothing semantics as Ticket 01).
- Freya published agent/workflow version and any state-isolation verification result.
- `scoring_only` / `scoring_with_diagnostics` setting.
- Whether diagnosis was **computed**, **available to human**, and **exposed to mutator**; three distinct concepts.

A line/column chart of progress is useful but must never combine official and proxy sources as one undifferentiated pass rate. Provide segmented lines or separate selectors for evidence classes. Unknowns must not inflate performance.

### 9.2 GRPO-inspired group comparison

In a selected `sibling_group_id` view, show:

| Candidate | Strict reward | Relative advantage | Evidence | Suite hash | State comparable | Decision |
|---|---:|---:|---|---|---|---|
| cand_0007 | recorded value | recorded value | actual class | actual hash | yes/no/unknown | kept/archived |

The numeric rows above are **placeholders** until real data exists. The UI must not recompute group-relative advantages from non-matched tests. Highlight zero-variance groups, missing evaluations, and unsupported comparisons. Absolute safety gates always outrank a high relative advantage.

### 9.3 Replay and event timelines

- A **read-only playback scrubber** displays tree and trace state **as of event sequence/time** to answer “When was this candidate selected?” and “What happened before this score changed?”
- Playback uses recorded event sequence; no LLM/phone re-execution.
- Timeline must support pause, step back/forward by event, play speed (e.g. 1×/4×/10×), jump to candidate creation/evaluation/champion updates.
- A completed run opens at latest state by default; a live run opens live unless the user navigates backward.
- If early events were never captured, show the earliest available event and incomplete-history warning.

### 9.4 Ticket-02-specific data

- Synthetic case generation counts by strategy (`rules`, `adversarial`, `property`, `metamorphic`, `interaction`, `spec_mutation`).
- New brief/OpenAPI family hashes and compiler compatibility results; synthetic spec packs stay separate from real hidden briefs.
- Rule coverage, interaction coverage, novelty/duplicate rejection rates, oracle valid/partial/unknown counts.
- Optimization case details for authorized developers only.
- Validation **released aggregates only** at allowed checkpoints, not case payloads.
- Holdout **released final aggregates only** after champion freeze and reporting; no leaked case strings, expected assertions, private seeds, or direct file refs.
- Test-generation counts must reflect `.env` and actual emitted cases, not desired counts alone.

### 9.5 Research comparison page (P1)

Simple run-to-run comparisons for Ticket 01 benchmark feedback ablation and Ticket 02 anti-overfitting experiments:

- Paired runs by same brief/OpenAPI hash, seed, original baseline, and frozen suite set.
- Final strict score by evidence class, improvement time, number of candidates, simulation minutes, model cost and unknown rates.
- Different benchmark modes side by side, with warnings if evaluation budget or test suites differ.
- Do not expose validation or holdout case payloads to this page.

---

## 10. Configuration — append to the existing `.env.example`

Never change the semantics of `BENCHMARK_MODE` or Ticket-02's synthetic case configuration. Add these independent fields:

```dotenv
# ============== TICKET-03 — OBSERVABILITY STUDIO ==============
OBS_ENABLED=true
OBS_ARTIFACTS_DIR=artifacts             # defaults to existing ARTIFACTS_DIR
OBS_SERVER_HOST=127.0.0.1             # localhost by default
OBS_SERVER_PORT=8765
OBS_OPEN_BROWSER=false
OBS_FRONTEND_DEV=false                  # uses bundled built frontend otherwise

# Live updates and caching
OBS_LIVE_ENABLED=true
OBS_SSE_HEARTBEAT_SECONDS=15
OBS_POLL_FALLBACK_SECONDS=3
OBS_FS_WATCH_ENABLED=true
OBS_INDEX_REBUILD_ON_START=true
OBS_EVENT_FLUSH_MS=250
OBS_MAX_EVENT_QUEUE=5000
OBS_MAX_ARTIFACT_READ_BYTES=10485760
OBS_TRACE_PAGE_SIZE=100
OBS_GRAPH_LAYOUT=layered

# Prompt/response capture; default sanitized, controlled
OBS_CAPTURE_MODEL_INPUTS=true
OBS_CAPTURE_MODEL_OUTPUTS=true
OBS_CAPTURE_TOOL_PAYLOADS=true
OBS_REDACT_SENSITIVE_DATA=true         # never disable outside isolated synthetic testing
OBS_CAPTURE_MODE=redacted              # redacted | hash_only | full_sanitized | off
OBS_SHOW_DEVELOPER_TRACE_DETAILS=true  # only authorized optimization traces
OBS_ALLOW_RAW_ARTIFACT_DOWNLOAD=false   # opt-in, sanitized/authorized only

# Ticket-02 suite boundaries: not an override of the split firewall
OBS_SEALED_CASE_VISIBILITY=disabled     # disabled | released_aggregate_only
# No environment switch may bypass Ticket-02 sealed-case access policy.

# Optional observability connectivity
OBS_LANGSMITH_LINKS=true               # links only; no remote access required
OBS_LANGSMITH_REMOTE_FETCH=false        # default off; not needed for local studio
OBS_SERVER_AUTH_TOKEN=                 # strongly required before non-loopback bind

# Debug/fixtures
OBS_FAKE_RUN_DEMO=false
OBS_LOG_LEVEL=INFO
```

**Security validation:** Refuse to serve on `0.0.0.0`/non-loopback without explicit authenticated mode + origin protection. Do not use `OBS_CAPTURE_MODE=full_sanitized` as a synonym for raw secrets; redaction always remains mandatory. For this hackathon all identities/bank data are synthetic, but credentials and future real data still require redaction and controlled access.

**`OBS_ENABLED=false` must not break builder operation or the original Ticket-01 submission trace.** It disables optional Ticket-03 capture/streaming, not required archive records or Freya export.

---

## 11. Files/repository additions

Add to the same codebase, not a separate incompatible project:

```text
project-root/
├─ builder/
│  ├─ observability.py                   # existing Ticket-01 tracing integration; adapt it
│  └─ observability/
│     ├─ __init__.py
│     ├─ config.py                        # new env schema
│     ├─ schemas.py                       # event/span/origin models
│     ├─ sink.py                          # bounded nonblocking writer
│     ├─ capture.py                       # explicit ADK/tool/benchmark trace adapters
│     ├─ redact.py                        # secret scrubbing and safe payload capture
│     ├─ archive_reader.py                # Ticket-01/Ticket-02 read adapters
│     ├─ indexer.py                       # incremental JSONL tail + projection
│     ├─ lineage.py                       # graph validation / candidate joins
│     ├─ diff.py                          # Freya workflow semantic diff
│     ├─ access.py                        # allowlisted paths, split policy
│     ├─ server.py                        # FastAPI app factory
│     ├─ stream.py                        # SSE event replay/fan-out
│     ├─ metrics.py                       # provenance-safe derived metrics
│     ├─ legacy_import.py                 # adapt pre-Ticket-03 artifacts
│     └─ serve.py                         # python -m builder.observability.serve
├─ dashboard/
│  ├─ index.html
│  ├─ package.json
│  ├─ vite.config.ts
│  ├─ tsconfig.json
│  └─ src/
│     ├─ main.tsx
│     ├─ app/App.tsx
│     ├─ app/store.ts
│     ├─ api/client.ts
│     ├─ api/stream.ts
│     ├─ types/obs.ts                     # generated or validated against Python JSON schemas
│     ├─ components/RunToolbar.tsx
│     ├─ components/TraceSidebar.tsx
│     ├─ components/MainInspector.tsx
│     ├─ components/LineageGraph.tsx
│     ├─ components/CandidateOrigin.tsx
│     ├─ components/WorkflowDiff.tsx
│     ├─ components/PromptResponseViewer.tsx
│     ├─ components/ToolCalls.tsx
│     ├─ components/BenchmarkPanel.tsx
│     ├─ components/TimelineWaterfall.tsx
│     ├─ components/LiveStatus.tsx
│     ├─ components/ErrorBoundary.tsx
│     └─ styles/
│        ├─ globals.css
│        └─ panels.css
├─ tests/
│  └─ observability/
│     ├─ fixtures/                     # entirely synthetic traces and workflows
│     ├─ test_event_schema.py
│     ├─ test_writer_atomicity.py
│     ├─ test_legacy_lineage_import.py
│     ├─ test_candidate_origin_join.py
│     ├─ test_graph_integrity.py
│     ├─ test_semantic_diff.py
│     ├─ test_sse_replay.py
│     ├─ test_artifact_security.py
│     ├─ test_split_redaction.py
│     ├─ test_published_version_mismatch.py
│     ├─ test_partial_jsonl_recovery.py
│     ├─ test_no_builder_dependency_on_ui.py
│     └─ test_e2e_offline_demo.py
├─ dashboard/e2e/                    # Playwright/browser acceptance tests
│  ├─ live-update.spec.ts
│  ├─ tree-selection.spec.ts
│  ├─ trace-inspector.spec.ts
│  ├─ resume-stream.spec.ts
│  ├─ sealed-access.spec.ts
│  └─ keyboard-navigation.spec.ts
├─ scripts/
│  ├─ generate_observability_demo.py
│  └─ validate_observability_artifacts.py
├─ artifacts/<run_id>/observability/  # runtime output, ignored by Git when sensitive
└─ docs/
   ├─ observability-artifact-contract.md
   ├─ observability-security.md
   └─ observability-troubleshooting.md
```

**Potential Python module name collision:** Ticket 01 has `builder/observability.py`; Python cannot consistently expose both `builder.observability` as a module file and `builder/observability/` as a package. As part of implementation, **migrate** existing `builder/observability.py` into `builder/observability/legacy.py` (and re-export compatibility imports from package `__init__.py`), then update imports/tests. Never ship both paths unresolved. Confirm repo's actual state first.

**Frontend dependencies:** Prefer a pinned standard React stack and `@xyflow/react`, ELK.js/Dagre, TanStack Query for data fetching, and a code/text diff renderer with safe escaping. Keep the bundle moderate. The UI should serve as static assets from FastAPI in production and via Vite proxy during local frontend development.

---

## 12. Implementation milestones and vertical-slice order

### M0 — Audit and contracts (P0)

- [ ] Read actual `ticket-01.md`, `ticket-02.md`, and source implementations if already present.
- [ ] Inspect real `artifacts/<run_id>` files; document which keys are captured vs missing.
- [ ] Define/generate canonical `Event`, `Span`, `CandidateOrigin` JSON schemas and TypeScript mappings.
- [ ] Document split/evidence visibility rules and approved artifact refs.
- [ ] Create synthetic fixture run with at least root + 2 children, 5 spans, one evaluation, one mutation, and champion event.
- [ ] Decide migration of existing `builder/observability.py` without import conflicts.

**Gate:** A JSON-only fixture can be validated and rendered without LangSmith, Freya or LLM credentials.

### M1 — Read-only artifact server + historical run browser + complete tree (P0)

- [ ] Implement **durable discovery of all prior runs** on startup, a run catalog/selector, and lineage snapshot parser and graph integrity checks.
- [ ] Implement paginated `/runs` history, `/tree`, `/candidate`, `/diff` endpoints with composite `(run_id, entity_id)` scoping.
- [ ] Build core HTML shell and right-hand tree, including root/child edges, invalid/archived nodes, selection and fit-to-view.
- [ ] Build center **candidate creation inspector** using existing proposal/mutation/validation/evaluation files.
- [ ] Support missing artifact and duplicate/orphan warnings.

**Gate:** Run A and Run B are selectable from history after a server restart; selecting either swaps all three panels without cross-run data, and clicking any candidate explains its creation.

### M2 — Traces and full model/tool details (P0)

- [ ] Implement explicit ADK and deterministic-service span capture (prompt/response/tool calls) with redaction.
- [ ] Add durable event writer and validated JSONL ingestion.
- [ ] Build left hierarchical trace tree with search, filtering and a center span inspector.
- [ ] Show exact captured prompt, output, tool calls, errors, durations and LangSmith link when available.
- [ ] Synchronize trace selection and corresponding candidate graph highlighting.

**Gate:** One end-to-end ADAS → mutation → score sequence can be reconstructed in the UI with no invented details.

### M3 — Live refresh and replay (P0)

- [ ] Add filesystem watcher/poll fallback and incremental indexing.
- [ ] Add SSE event stream with `seq` cursor, reconnection, dedup and snapshot resync.
- [ ] Preserve selection/scroll/zoom while events arrive; show no-focus-stealing behavior, and **cancel/re-subscribe SSE when switching between live and historical runs**.
- [ ] Track active run progress and builder budget countdown.
- [ ] Add replay scrubber or basic event stepping for completed runs.

**Gate:** A new candidate and model span appear while the browser stays open; killing/restarting the server does not lose or duplicate source facts.

### M4 — Benchmarks, lineage forensics and Ticket 02 (P0)

- [ ] Show per-candidate benchmark results with official/proxy evidence classes and unknowns.
- [ ] Show GRPO sibling comparison only on matched suite/state evidence.
- [ ] Add semantic Freya workflow diff and exact workflow snapshot viewer.
- [ ] Surface source-linked rule targets, mutation cause, parent-selection rationale and champion decision.
- [ ] Show Ticket 02 case-generation stats and released aggregates; enforce split read restrictions server-side.
- [ ] Confirm benchmark mode (`scoring_only` vs `scoring_with_diagnostics`) display does not change scores or leak explanations into optimizer contexts.

**Gate:** Team can diagnose why a candidate improved or regressed without confusing mock/real evaluations or leaking sealed cases.

### M5 — Polish, scale, resilience and developer onboarding (P1)

- [ ] Virtualize long trace lists; async graph layout and stable incremental positioning.
- [ ] Handle corrupted/incomplete JSON, low bandwidth, disconnections and LangSmith offline.
- [ ] Add keyboard access, accessibility fallback and responsive panels.
- [ ] Build optional **cross-run comparison report** (run history picker/switching is already P0), read-only event playback refinements, screenshot-ready layout.
- [ ] Benchmark typical and large synthetic event archives; fix performance bottlenecks.
- [ ] Document CLI, `.env` and how to point dashboard at an existing archive.

**Gate:** A developer unfamiliar with the codebase can launch dashboard and inspect a recorded run within two commands.

### Team parallelization suggestion

- **UI engineer:** three-pane layout, trace explorer, lineage graph, inspector/diffs.
- **Backend/observability engineer:** schemas, writer, indexing, SSE, secure APIs.
- **Builder/benchmark engineer:** explicit span hooks around existing ADK/Freya/Ticket-02 services; ensure event IDs and split boundaries are correct.

Merge through the JSON schema and API fixtures first, not by manually inventing fields on both sides.

---

## 13. Acceptance tests (automatable where possible)

Implement at least the following **51** checks, split between Python unit/integration and Playwright browser tests:

**Artifacts and durability**

1. A Ticket-01 run with no Ticket-03 sidecars is discovered and shows a best-effort lineage tree.
2. Every candidate in `lineage.jsonl`, including invalid/archived ones, appears in the tree.
3. `candidate_id` and parent edges remain stable across backend restarts.
4. Missing parent node produces visible integrity warning; no child is silently dropped.
5. Cycle in corrupted lineage produces a safe graph error, not infinite renderer recursion.
6. Duplicate workflow hashes retain distinct attempted candidate events and hashes.
7. Atomic file replace never displays half-written JSON as completed evidence.
8. Trailing incomplete JSONL line is retried; earlier complete lines remain available.
9. Index corruption triggers source-only rebuild without modifying lineage or workflow snapshots.
10. Source snapshot SHA mismatch produces provenance warning.

**Trace capture**

11. Recorded ADK prompt and response are visible in the center, with role labels and capture mode.
12. Missing prompt is rendered as `not captured`, not an empty invented prompt.
13. Tool calls are paired to results and retries with correct IDs; missing result remains pending/unknown.
14. Span parent-child nesting and displayed durations match recorded timestamps.
15. Long prompt/JSON response is scrollable/searchable without breaking the layout.
16. LangSmith URL appears only when an actual authorized ID/URL exists.
17. Observability failure does not cancel builder iteration or Freya export.
18. Instrumented final build generates the kit-required plain-text `build_trace.log` independently of UI availability.

**Evolution graph and inspector**

19. Root + child + grandchild are connected by parent edges, not execution span edges.
20. Clicking a child shows originating parent, mutation hypothesis, rule IDs, patch and originating ADK span.
21. Parent→child diff detects prompt, transition, code-node and tool configuration changes correctly.
22. Raw workflow snapshot matches stored SHA and is not altered by graph layout.
23. Clicking a trace highlights corresponding candidate without unexpectedly scrolling it out of view.
24. Clicking a graph node selects corresponding candidate traces while preserving current query/filter state.
25. New events do not reset graph zoom, selected node, panel sizes or old trace inspection.
26. `Show all` restores collapsed/filtered candidates with hidden-count indicator.
27. Champion, best official, best proxy and active deployed pointers can differ and are shown separately.

**Benchmark truthfulness**

28. `unknown`/`not_run` never render as passed; mock/transcript-only results never show as official success.
29. Displayed strict score and relative advantage match recorded canonical scorer values.
30. Group comparisons warn on differing suite hashes or non-isolated initial bank states.
31. A workflow version mismatch between publish and evaluated `agentVersionNumber` is flagged.
32. `scoring_only` does not cause diagnostic text to be generated/exposed to the mutator, regardless of developer UI inspection.
33. Ticket-02 configured desired counts are distinguishable from actual generated/executed counts.
34. Validation raw cases cannot be retrieved via the dashboard API before release.
35. Holdout case payloads and direct paths are inaccessible even by guessed URLs.

**Live operation and security**

36. SSE event arrival updates traces/tree without page reload.
37. SSE disconnect and reconnect replays each missing event exactly once by `seq`.
38. Resync after expired/mismatched cursor restores the same graph as a clean reload.
39. User viewing an old span sees `N new events` without losing focus/scroll position.
40. Secret/API-key patterns are redacted in HTML, JSON API and artifact downloads; HTML injection in a model output is escaped.
41. Path traversal and unauthorized artifact IDs return 403/404, never local file contents.
42. Dashboard launches offline with a deterministic fixture and supports deep-linking to a known candidate.

**Historical runs and run isolation (P0)**

43. The picker discovers two or more archived runs and one live run; supports search, filters, and newest/oldest sorting with stable pagination.
44. A completed run remains selectable with all its trace/tree/artifact data after browser refresh and backend restart, with no LangSmith or Freya credentials.
45. Switching between runs A and B changes **left traces, center inspector, right tree, header and benchmark summaries together**; IDs reused between runs cannot cross-contaminate content.
46. Late API responses and old SSE events from run A arriving after selection of B are dropped; only B can update the visible tree/trace, without event duplication.
47. Opening a deep link to an existing old run selects exactly that run and, when valid, the specified candidate/span; a missing run ID displays an explicit error rather than silently selecting the newest run.
48. Switching A → B → A restores per-run filters, tree viewport, expanded spans and selected node when available; B retains separate state.
49. A newly started run appears in history automatically without forcing the user away from an older run they are investigating.
50. An interrupted or partially written historical run appears with honest status and available evidence; it does not disappear or falsely render as completed or scored zero.
51. Selecting, replaying, or comparing historical runs produces **no** builder, Freya create/publish, simulation or mutation side effects; comparison warns when brief/OpenAPI/suite/evidence differs.

### 13.1 Manual visual quality checklist

- [ ] Three columns substantially match supplied sketch: **Traces left, large detail area center, full tree right**.
- [ ] Tree fits all nodes or gives obvious pan/zoom controls; no cutoff of the last branch.
- [ ] Inspector is readable at common laptop widths, with tabbed long prompts and structured JSON.
- [ ] Status and candidate IDs are not hidden behind hover-only interfaces.
- [ ] Fresh data indicators, reconnecting, no-data and unknown-evidence states are visually distinct.
- [ ] Source refs/hashes/case splits are visible where safe and clearly explained.
- [ ] Important errors can be located in under 15 seconds using trace filters or graph highlighting.

---

## 14. Operational robustness and security

### 14.1 Sensitive content

- Redact `Authorization`, Freya/Google/LangSmith keys, bearer tokens, cookies, `.env` fields, secret refs, account access credentials and payment/contact details where relevant.
- Avoid accidentally storing a non-sanitized raw LLM prompt or tool result in SSE event metadata. Run redaction **before local persistence**, not only in browser display.
- All case data are synthetic for the hackathon, but **holdout secrecy is still essential to evaluation integrity**. Never expose sealed payloads to the optimizer through logs, UI APIs, ADK tools or shared LangSmith traces.
- Do not use browser analytics or third-party hosted telemetry on the dashboard by default.
- Escape malicious text in model outputs, bank responses and arbitrary Markdown; all JSON viewers use text-safe rendering.

### 14.2 Safe deployment

- Local development binds to `127.0.0.1`, with conservative CORS and no wildcard origins.
- Support an optional token for permitted remote team demo; proxy via TLS/VPN rather than exposing unsecured artifact paths.
- Serve only the built frontend and allowlisted API routes; no `directory listing` of the project root.
- If authentication is added, read-only by default; group APIs by access level. Client-side hidden tabs do not enforce confidentiality.

### 14.3 Performance targets (engineering objectives, not documented Freya guarantees)

Under a synthetic fixture containing **250 candidates, 5,000 spans and 30,000 events** on a normal development laptop:

- First usable shell + run list within roughly 2 seconds from a warm index.
- Tree interaction and panning remain responsive; target 30+ FPS under common conditions.
- Search/filter operates interactively without freezing the main thread.
- New event visible within approximately 2 seconds when filesystem and server are healthy.
- No O(N²) rebuild of all history on each new append.
- Browser does not prefetch all huge tool/prompt payloads at startup.

Record environment, memory and page timings; do not claim these objectives were achieved without measuring them.

### 14.4 Writer backpressure and crash safety

Observability must not consume the full simulation/optimization time budget. Keep small per-event metadata on the hot path; expensive formatting/redaction and persistence should be efficient or asynchronous with bounded overhead. On abrupt termination, a future viewer should still recover completed events and existing Ticket-01 artifact tree. Events for operations that never finished must appear as `interrupted`/`unknown`, not `succeeded`.

---

## 15. Commands and local demo

### 15.1 Install (example; pin resolved versions after auditing repository)

```bash
# In the project's Python environment
pip install fastapi uvicorn watchfiles pydantic

# Frontend
cd dashboard
npm install
npm run build
cd ..
```

If your project already uses `uv` or `pyproject.toml`, declare and lock Python dependencies there rather than relying on ad-hoc unpinned installation.

### 15.2 Start dashboard, no network services required

```bash
export ARTIFACTS_DIR=artifacts
python -m builder.observability.serve --host 127.0.0.1 --port 8765
# Visit http://127.0.0.1:8765
```

`--artifacts-dir` may override the `.env` path. If the directory is empty, show an informative screen and a link/command for generating a synthetic demo run.

### 15.3 Start normal Freya builder separately

```bash
# In another terminal. Actual kit/client paths are checked by Tickets 01/02.
python3 builder/build.py briefs/brief-a.md --openapi tools/openapi.json
```

The dashboard must automatically discover and show the new `run_id` and update while this process runs; it must not require restarting either process. Viewing a run cannot inadvertently start another Freya simulation.

### 15.4 Demo fixtures and verification

```bash
python scripts/generate_observability_demo.py --out artifacts/demo_run
python scripts/validate_observability_artifacts.py --dir artifacts/demo_run
python -m pytest tests/observability -q
cd dashboard && npm run test && npx playwright test
```

Demo data should include: ADAS root; one failed validation child; one successful benchmark child; a later champion; score-only and diagnostic example traces; a mock-only synthetic case correctly labeled proxy; an unreleased holdout whose payload API requests are denied; a simulated long-running span; an explicit unpublished-version mismatch; at least one deliberate tool error and model prompt/response pair.

---

## 16. Definition of done

Ticket 03 is complete only when all conditions hold:

1. **The exact user-requested three-pane UI works**: trace list left, detail inspector middle, always-present lineage tree right.
2. A developer can select *any candidate* and identify who created it, from which parent, with which prompt/mutation/patch, what changed in workflow JSON, which validation/evaluation ran and what its score actually means.
3. A developer can select *any captured trace span* and inspect sanitized actual inputs, outputs, tools, timing, errors, retry history and LangSmith link when recorded.
4. Existing Ticket-01 JSON artifacts load without requiring a live Freya/Google/LangSmith connection; Ticket-02 metadata is optional and its absence must not block the dashboard.
5. The live dashboard updates automatically with deterministic event ordering, replay/reconnect support and without losing selection or graph viewport; **historical runs remain selectable and isolated across restarts**.
6. Correct strict pass/fail, unknown, official-vs-proxy, group comparison, and Ticket-02 split restrictions are enforced **in the backend**, not only UI labels.
7. The dashboard is read-only and cannot compromise the builder's 30-minute budget or required submission exports.
8. End-to-end fixture and integration tests, browser tests and security tests pass; deployment instructions and event schema docs are checked in.

**Build-order recommendation:** Ticket 01 baseline artifact capture → Ticket 03 dashboard (including run history) → Ticket 02 optional anti-overfitting views. P0 starts with the existing archive and a fully clickable tree/candidate-origin inspector, then adds deep traces, live streaming and benchmark evidence. A beautiful trace UI without trustworthy candidate provenance is not an acceptable substitute; likewise, a powerful graph with no prompt/return/tool details does not satisfy the request.

---

## 17. Engineering decisions to preserve explicitly

1. **One tree node = one entire generated Freya phone-agent workflow within a uniquely identified run**; don't mix that with Freya's internal conversation nodes or Ticket-02's scenario family tree.
2. **Read-only observability**; no new workflow deployment, no hidden extra simulations.
3. **JSON/JSONL first**; optional SQLite/indices/LangSmith enrich but are not runtime dependencies.
4. **Two separate truth axes**: `evaluation outcome/evidence class` and `capture completeness`. Missing telemetry is never a pass/fail decision.
5. **Feedback visibility is not the same as developer visibility**; the screenshot can show developer information without changing the optimizer's scoring-only rules, but sealed case details must remain inaccessible until explicitly released.
6. **Every event must be source-linked** to a candidate/span/evaluation and artifact hash when available.
7. **Full tree** really means all candidates; filters/collapsed subtrees must say how much is hidden.
8. **Prompt/response completeness is capture-dependent**, not a guarantee of revealing inaccessible model internal reasoning.
9. **The server starts without live credentials**; historical runs remain useful indefinitely.
10. **No fake claims:** mark derived, approximate, proxy, incomplete, stale, unpublished, unknown and unauthorized explicitly.

---

## 18. Final implementer checklist (first coding session)

- [ ] Read `ticket-01.md` Section 9 and Ticket-02 Sections 3, 8, 13.
- [ ] Read actual archived `manifest.json`, `lineage.jsonl`, candidate snapshots and `core_score.json` files to confirm available fields.
- [ ] Introduce one shared normalized schema and one synthetic end-to-end fixture before frontend coding.
- [ ] Implement `/api/runs`, `/tree`, `/candidates/{id}`, `/spans` against **at least two distinct historical run fixtures**.
- [ ] Render the three panels with a clickable root+two-child graph and a trace explorer, and a **working historical run selector** that swaps all panels.
- [ ] Show candidate origin, parent diff and captured model prompt/response in the center.
- [ ] Implement the event sink and write `events.jsonl` while a mocked optimizer produces a new child.
- [ ] Add SSE and confirm that this new child appears in the tree without refresh.
- [ ] Add strict redaction, payload allowlisting and sealed-case API denial tests.
- [ ] Only after all of the above, integrate the real Freya runner and fine-tune UI styling.

**Hand-off instruction to coding agent:** Do not respond with a UI concept or static wireframe. Implement the real JSON artifact data contracts and a working, responsive HTML dashboard over those artifacts. Use the source documents and the existing repository conventions. Make reasonable implementation choices without changing the three-pane UX or breaking Tickets 01/02. Record ambiguities as explicit warnings; never fabricate trace, reward, or evaluation evidence.
