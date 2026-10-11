# Freya Builder Studio (Ticket-03 observability)

Read-only HTML dashboard over `artifacts/<run_id>/` builder artifacts.
Zero Python dependencies (stdlib only), zero npm — one HTML file frontend.

## Run

```bash
python3 -m observability.serve --artifacts-dir agent/artifacts
# open http://127.0.0.1:8765
```

`--artifacts-dir` defaults to `$OBS_ARTIFACTS_DIR` → `$ARTIFACTS_DIR` → `agent/artifacts`.
Non-loopback bind is refused (ticket §10).

Synthetic runs appear as `synthetic_<run>` in the same picker. Their progress traces expose
model-call timing and token usage; prompts, responses and holdout evidence stay private.

Offline demo (no Freya/LLM/credentials):

```bash
python3 -m observability.demo --out artifacts/demo_run
python3 -m observability.serve --artifacts-dir artifacts
```

## What it shows

- **Header**: historical run picker (all runs discovered from disk, survives restart),
  status, mode, champion + score, live indicator.
- **Left — traces**: chronological span list derived from `build_trace.log`
  (model calls paired by `call_id`/order and flagged `derived`, Freya deploys,
  errors, retries), text filter, `/` to focus.
- **Center — inspector**: run overview, span detail (status/duration/tokens,
  captured prompt + parsed/raw response from `model_calls/`, raw event JSON),
  candidate inspector (origin, validation, **semantic diff vs parent** with
  `+nodes/-transitions/prompt` summary, exact workflow snapshot, raw).
- **Right — lineage tree**: every candidate from `lineage.jsonl` (or derived from
  `candidates/` snapshots, labeled as such), pan/zoom/fit, champion/invalid/valid
  states, orphan + cycle integrity warnings, click to inspect.
- **Live**: SSE (`/api/runs/<id>/stream`) pushes `changed` on any file change;
  UI refetches snapshots. Heartbeats every 15 s, reconnect shown honestly.

## API

`/api/health`, `/api/runs`, `/api/runs/{id}` (summary), `.../tree`, `.../spans`,
`.../events`, `.../candidates/{id}`, `.../candidates/{id}/diff[?against=]`,
`.../model_calls/{call_id}`, `.../metrics`, `.../artifact?path=<allowlisted rel>`,
`.../stream` (SSE). Errors typed: `RUN_NOT_FOUND`, `ARTIFACT_MISSING`,
`ARTIFACT_RESTRICTED`.

## Security

- Artifact endpoint resolves and confines to the run dir; denies `..`, dotfiles,
  `synthetic/`, non-allowlisted suffixes, >10 MB reads (truncated with the
  response capped, never silent promotion).
- Server never writes builder artifacts; view models are projections only.
- Missing data renders as `not captured` / `unknown`, never as a pass.

## Layout

```
observability/
├─ store.py       # discovery, parsing, projections (mtime-keyed cache)
├─ diff.py        # semantic Freya workflow diff
├─ server.py      # stdlib HTTP + SSE
├─ serve.py       # python -m observability.serve
├─ demo.py        # synthetic offline fixture run
├─ static/index.html  # three-pane SPA (vanilla JS + SVG)
└─ tests/test_studio.py  # 12 checks; python3 -m pytest observability/tests -q
```

Deliberate deviations from ticket recommendations (kept lazy on purpose):
FastAPI/React/xyflow replaced by stdlib `http.server` + one-file vanilla JS/SVG
frontend — same three-pane UX, no install step. `OBS_*` env knobs from ticket §10
are not yet wired; defaults are the safe ones (`redacted` read paths, loopback,
10 MB cap). Writer/instrumentation bridge (§6) not included: producer events
already exist in `build_trace.log`; the studio is read-only by design.
