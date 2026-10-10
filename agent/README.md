# Ticket 1: brief-driven Freya builder

All implementation and runtime writes live in this directory. The surrounding kit is read-only. Google ADK generates requirements, workflows and typed patches; deterministic Python controls validation, deployments, scores, time limits and exports. Agents have no shell, file, network, deployment or trace-query tools. The code-test referee has one pure calendar calculator, parameterized entirely from source policy.

## Run

From the kit root, with Python 3.10+ and the existing kit credentials:

```sh
python3 -m venv agent/.venv
agent/.venv/bin/pip install -r agent/requirements.lock
python3 agent/agent_builder.py briefs/brief-a.md
python3 agent/agent_builder.py briefs/brief-a.md briefs/brief-b.md
python3 agent/agent_builder.py path/to/policy.md --openapi path/to/openapi.json
```

Use the virtual environment's Python if dependencies are not already installed. Put keys in the kit-root `env.sh` (template provided, git-ignored): `FREYA_API_KEY`, `FREYA_BANK_TEAM_KEY` and the builder LLM settings. The default builder LLM is Qwen 3.8 (`Qwen/Qwen3.8-2.4T-A95B`) served on Modal (`modal/<served model name>`): set `MODAL_BASE_URL` (the OpenAI-compatible `.../v1` URL), `MODAL_KEY` (`wk-...`) and `MODAL_SECRET` (`ws-...`), sent as Modal proxy-auth headers. Other LiteLLM providers still work (`anthropic/...` needs `ANTHROPIC_API_KEY`, `gemini/...` needs `GOOGLE_API_KEY`). The builder loads it automatically and exits with code 2, naming any missing key, before doing any work. Settings resolve as CLI mode > process environment > `agent/.env` > root `.env` > root `env.sh` > defaults.

Optional public test selectors:

```sh
python3 agent/agent_builder.py briefs/brief-a.md --only PUB-01,PUB-03
python3 agent/agent_builder.py briefs/brief-a.md --style pieces
BENCHMARK_MODE=scoring_only python3 agent/agent_builder.py briefs/brief-a.md
PYTHONPATH=agent python3 -m builder.experiments.compare_modes --brief briefs/brief-a.md --only PUB-01,PUB-03
```

`--only`, styles and repetition counts create distinct suites. Partial or different suites are never ranked as equal. Unfamiliar input has unknown official fitness; no practice expected values are applied to it. The paired experiment first builds a pinned root and freezes its baseline measurement, then runs isolated arms sequentially. Every build gets its own wall-clock budget. A shared baseline is explicitly identified; its cost belongs to the baseline run.

The last stdout line is JSON with workflow/agent/candidate IDs, mode, evidence type, strict rate (or null), status and actual export path. Exit codes: 0 real export, 2 bad input/config, 3 no valid candidate, 4 deployment/export failure. `exported_with_errors` means the champion was recovered after a later failure, not that all search objectives passed.

## Artifacts and recovery

Each `agent/artifacts/<run_id>/` contains input hashes/snapshots, requirements, tool contracts, SQLite + JSONL lineage, immutable candidate snapshots/patches, validations, frozen scores, authorized diagnostics, model requests, local build trace, pinned root, report and real root/champion exports. Submission copy: `agent/out/<last-brief-stem>.workflow.json`. State/locks remain in `agent/.runtime/`; each feedback mode reuses one workflow slot. A timed-out simulation leaves a lease so the next run waits for it to settle.

`--pinned-root agent/artifacts/<run_id>/pinned_root.json` starts from an exact source-matched snapshot without regenerating it. Historical candidates never change. Export restores and publishes the selected candidate and checks all submitted semantic fields against the server export; added server defaults are tolerated. If final restoration fails, a previously verified real export of that exact champion can be recovered with status `exported_cached` and `remote_restored=false`. This preserves the submission without claiming the remote deployment was restored. Without such an export, the build fails.

The benchmark wrapper calls the original kit `persona_for` and `run_once`, keeping their bank-state and conversation verdicts. It avoids the stock main's writes outside `agent`. Real runs must report the expected `agentVersionNumber`. Missing versions or incomplete runs cannot produce a complete scored suite. No LLM diagnosis changes core scores. A proxy or static check is never labeled official success.

## Validation

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest agent/tests -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=agent python3 -m builder.audit_smoke
```

The audit smoke intentionally loads the stock example unchanged and tests startup only. The supplied example has legacy fields and incomplete policy; it is not used as a compliant generated root. Unit/controller tests explicitly use fake Freya evidence and cannot demonstrate live bank correctness.

Static checks reject misplaced fields, unsupported operations and URLs, missing mapping prefixes, altered tool schemas, retry hazards, dangling/deadlocked routes, unguarded account access and closing bypasses. Snippet validation rejects undocumented imports, filesystem/network capabilities, dynamic execution and host-clock use. It does not prove all spoken policies; actual practice runs remain necessary.

LangSmith is optional at runtime: local durable logs survive missing credentials/outages. Remote traces contain metadata and artifact references rather than customer transcripts. Local evidence is restricted to the synthetic kit, with credentials and structured identity fields redacted. No real customer data is supported. LangSmith receipt is unverified unless a configured account receives a trace.

No model weight training, frontend or builder self-rewriting is included. Search uses GRPO-style relative normalization only on complete matched sibling suites. With the default four-simulation budget, some children will still have unknown fitness; they cannot displace a measured champion without comparable evidence.

Restore after an interrupted run without another model call:

```sh
PYTHONPATH=agent python3 -m builder.restore --run agent/artifacts/<run_id>
```

Recovery revalidates the selected immutable snapshot, rejects known hard failures, updates/publishes its original slot and exports into a new recovery directory. The original lineage stays intact.

Code probes are generated from source rules once and reused for children. They run in a separate process with restricted builtins/imports and CPU/wall limits; they test deterministic snippet outputs only. Held-out validation uses a speaking style withheld from optimization and runs only if repetition, simulation and wall budgets allow it.
