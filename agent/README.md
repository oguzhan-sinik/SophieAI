# Brief-driven Freya builder

Reads a bank brief and its tool API file, designs a Freya phone agent, fixes it, measures it on
practice customers where they exist, improves it and exports it. One command, no manual step.
All code and every runtime write live in this directory; the surrounding kit is read-only.

## Run

From the kit root, with Python 3.10+:

```sh
python3 -m venv agent/.venv
agent/.venv/bin/pip install -r agent/requirements.lock
agent/.venv/bin/python agent/agent_builder.py briefs/brief-a.md
agent/.venv/bin/python agent/agent_builder.py briefs/brief-a.md briefs/brief-b.md
agent/.venv/bin/python agent/agent_builder.py path/to/brief.md path/to/tool-api.json
```

A brief that is not one of the kit's own needs its tool API file, given after the brief or with
`--openapi`; without it the builder stops at once instead of building for the kit's bank.

Keys go in the kit-root `env.sh` (template `env.example`, git-ignored): `FREYA_API_KEY`,
`FREYA_BANK_TEAM_KEY` and the builder model settings. The default builder model is Qwen 3.8 on
Modal (`MODAL_BASE_URL`, `MODAL_KEY`, `MODAL_SECRET`); any LiteLLM model name works through
`BUILDER_MODEL`. The builder names any missing key and exits with code 2 before doing any work.
Settings resolve as process environment > `agent/.env` > root `.env` > root `env.sh` > defaults.

Options: `--only PUB-01,PUB-03` and `--style pieces` select practice customers and how they
talk; `--resume-run agent/artifacts/<run_id>` reuses that run's rules and first design.

The last stdout line is JSON: workflow and agent ids, the exported candidate, status, pass rate
(or null), simulations used and what became of each fix. Exit codes: 0 exported, 2 bad input or
configuration, 3 no workflow Freya accepts, 4 export failure.

## How a build works

1. **Rules.** One model call extracts the brief's rules with their source lines, as a checklist
   for the designer. If that fails twice the build goes on with the brief alone.
2. **Design.** One call writes the workflow *source*: compact, with bank tools as
   `{"bank_operation": ...}` and code stages as plain Python. The controller compiles it:
   it expands the tools from the tool API file, wraps the code, and injects the runtime support
   (spoken-date resolution against the call's `now`, business-day helpers, a loop guard).
   Models only ever see and edit the source.
3. **Compiler fixes.** Static checks and a Freya dry run produce errors that each name the stage
   to change. Up to two fix calls answer them. If no candidate is clean, the least-flawed one
   Freya accepts is exported as best effort.
4. **Measure.** Where practice customers exist (the kit's Brief A and B), the agent is deployed
   and simulated once; the kit's own runner and scorer give the verdicts.
5. **Improve.** A chain of rounds. One fix call reads the failed calls step by step and returns
   a patch: several small fixes, each a few field-level edits. All fixes that apply cleanly go
   into one child, which is simulated once. Each fix is then kept, or blamed if a customer that
   passed before now fails *and* its call visited a stage that fix edited. A blamed fix is
   dropped by branching from the parent with the kept ones. Edits that change wording only (what
   the agent is told or says; a description or a routing prompt is not wording) are committed
   without a simulation; anything else is never exported unmeasured.
6. **Export.** The best measured candidate (with its wording-only child, if any) is published
   and exported to `agent/out/<brief>.workflow.json`.

A brief without practice customers stops after step 3: no speculative edits are made to an agent
that cannot be tested. `docs/tickets/ticket-02.md` specifies generated practice customers to
close that gap.

## What the static checks cover

Stage shapes and field placement, bank tools exactly as the tool API declares them (URL, method,
fields, enums, zero retries), sandbox-safe code, every stage reachable and able to end, `close_call`
alone in its stage and before every hang-up, and identity: no route may reach `get_account` or
`create_promise` without a `verify_identity` call followed by a transition that tests something
the caller cannot simply say. An identity error prints the offending route. Hints (a value no
route tests, an offer that is never applied) are passed to fix calls and never block.

They do not prove how the agent speaks or what the bank records; only a simulation shows that.

## Artifacts

`agent/artifacts/<run_id>/`: inputs and their hashes, extracted rules, `build_trace.log` (start
and end, every model call with its purpose, what was created on Freya, every simulation and its
result), `lineage.jsonl`, and per candidate its source (`proposal.json`), compiled workflow,
the patch that made it and its static result; per simulation the raw runner output, bank ledgers
and call records. `python3 -m observability.serve --artifacts-dir agent/artifacts` (from the kit
root) shows all of it at http://127.0.0.1:8765.

`agent/.runtime/` holds the Freya slot state and the workspace lock: one workflow per brief,
updated in place, and never more than one simulation at a time.

Restore an archived candidate without any model call:

```sh
PYTHONPATH=agent agent/.venv/bin/python -m builder.restore --run agent/artifacts/<run_id>
```

## Tests

```sh
agent/.venv/bin/python -m pytest agent/tests observability/tests -q
```

Controller tests use fake Freya evidence; they show how the loop behaves, not that an agent is
correct.
