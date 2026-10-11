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
`FREYA_BANK_TEAM_KEY` and the model settings. The kit-root `env.example` shows the three
OpenRouter tiers: `MODEL_TIER_HARD`, `MODEL_TIER_MEDIUM`, and `MODEL_TIER_EASY`. Change those
lines in `env.sh` to select models for each tier; `BUILDER_MODEL` is the hard-tier fallback.
The builder names any missing key and exits with code 2 before doing any work.
Settings resolve as process environment > `agent/.env` > root `.env` > root `env.sh` > defaults.

QwenCloud is also available. Add `DASHSCOPE_API_KEY` to `env.sh` and select
`qwencloud/qwen3.8-max-0902` for a tier; this routes the
exact model ID to `https://maas.qwencloudapi.com/compatible-mode/v1` (override with
`QWENCLOUD_BASE_URL`). Requests stream with `enable_thinking=true` and the provider's
default reasoning budget for QwenCloud roles. Each QwenCloud call allows at least 65,536 total
completion tokens, including reasoning, within the existing call/build timeouts.
Only the final answer enters JSON validation;
dashboard observations publish progress and token usage. QwenCloud documents its
[compatible API](https://docs.qwencloud.com/api-reference/chat/openai-chat) and
[structured outputs](https://docs.qwencloud.com/developer-guides/text-generation/structured-output).
Existing provider settings remain available by changing `BUILDER_MODEL`.

Doubleword is an optional provider through the same ADK/LiteLLM client. Put your key in
`DOUBLEWORD_API_KEY` in `env.sh`; `DOUBLEWORD_BASE_URL` defaults to `https://api.doubleword.ai/v1`.
Select it for a test run without changing the saved provider selection:

```sh
GENERALISATION_ENABLED=true BUILDER_MODEL=doubleword/zai-org/GLM-5.3-Flash python3 -m generalisation_agent generate --seed 42 --packs 2 --users 10
```

The `doubleword/` prefix is
local routing metadata; the API receives `zai-org/GLM-5.3-Flash`. Requests use Doubleword's
[OpenAI-compatible structured outputs](https://docs.doubleword.ai/inference-api/tool-calling).
Existing Modal, OpenAI, Anthropic and Gemini settings remain available. No extra SDK is needed.
Doubleword brief writing/checking uses medium reasoning effort; other roles use low effort.

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
3. **Compiler fixes and design review.** Static checks and a Freya dry run produce errors that
   each name the stage to change. The same pass reviews the design for what would otherwise only
   show in a call: a conversion of a value the caller may not have given and a controller helper
   called wrongly are errors. A stage that extracts more than five values from one reply and a
   code stage of more than 120 lines are hints only: forcing a rewrite of a working design lost
   customers when tried. Up to three fix calls answer the errors. If no candidate is clean, the
   least-flawed one Freya accepts is exported as best effort.
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
