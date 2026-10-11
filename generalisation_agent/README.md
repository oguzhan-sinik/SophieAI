# Generalisation agent

Ticket 2's implementation includes synthetic debt-collection briefs/APIs, adaptive customers, an isolated mock bank, an independent policy oracle, a Docker workflow proxy, calibration controls, offline rehearsals and an optional live builder evaluation provider. QwenCloud connectivity and structured streaming have been verified. Final model-backed verification remains pending: the first QwenCloud writer exhausted its completion budget on reasoning without producing an answer. No successful rendered two-pack rehearsal is claimed.

- [Canonical Ticket 2](docs/tickets/ticket-02.md)
- [Review and research](docs/review-and-research.md)

## Run

Local model roles reuse `BUILDER_MODEL` and its existing credentials. Configuration loads `generalisation_agent/.env`, then the existing builder configuration, with process environment taking precedence. Flags are read once per invocation and accept only `true` or `false`.

QwenCloud is selected in `env.sh`: `BUILDER_MODEL=qwencloud/qwen3.8-max-0902`.
Add `DASHSCOPE_API_KEY` there. Its default endpoint is
`https://maas.qwencloudapi.com/compatible-mode/v1`, overridable with `QWENCLOUD_BASE_URL`.
All model roles stream with thinking enabled and QwenCloud's default reasoning budget.
Calls allow at least 65,536 completion tokens (reasoning plus answer); the eight-minute
call timeout and 30-minute build deadline remain in force.
The [QwenCloud API](https://docs.qwencloud.com/api-reference/chat/openai-chat) supports
the existing structured-output path; final answers still undergo local schema and semantic
checks. Modal and Doubleword credentials/configurations remain available.

For Doubleword testing, fill `DOUBLEWORD_API_KEY` in the kit-root `env.sh`, then prefix a command
with `BUILDER_MODEL=doubleword/zai-org/GLM-5.3-Flash`. Its default endpoint is
`https://api.doubleword.ai/v1`; existing provider configuration is preserved. The exact model
and compatible request format are documented by [Doubleword](https://doubleword.ai/models/glm-5-3-flash).
All builder, actor, proxy and judge roles use the selected model. Changing it invalidates prior
calibration; a successful live request and credit eligibility remain unverified until the key is supplied.

```sh
# Default: no synthetic work. This delegates to the existing builder.
python3 -m generalisation_agent build briefs/brief-a.md tools/openapi.json

# Create two different packs, ten users each: development and sealed holdout.
GENERALISATION_ENABLED=true python3 -m generalisation_agent generate --seed 42 --packs 2 --users 10

# Build both packs with the existing builder; synthetic calls stay local.
GENERALISATION_ENABLED=true python3 -m generalisation_agent rehearse --manifest generalisation_agent/artifacts/<run>/manifest.json

# Diagnostic evaluation of an existing compiled/exported workflow on one pack.
GENERALISATION_ENABLED=true python3 -m generalisation_agent evaluate generalisation_agent/artifacts/<run>/packs/<pack>/manifest.json <workflow.json> --reps 3

# Build actual supplied inputs; independently interpret their policy and calibrate generated feedback.
GENERALISATION_ENABLED=true python3 -m generalisation_agent build <brief.md> <openapi.json> --users 10
```

For an end-to-end test, run `generate`, then `rehearse` with the returned top-level manifest.
This covers rendered synthetic inputs, calibration, workflow construction, local mock-bank
execution and final holdout evaluation when an export is available. Start the observation
dashboard in another terminal before running them:

```sh
python3 -m observability.serve --artifacts-dir agent/artifacts --host 127.0.0.1 --port 8765
```

Open [the observation dashboard](http://127.0.0.1:8765/). Generation, preparation and each
builder run appear as separate synthetic progress entries. Private prompts, responses and
holdout details stay outside its served directory. Set `LANGSMITH_TRACING=false` for these
local test commands to keep their trace data local.

`GENERALISATION_ENABLED=false` disables the extension. `GENERALISATION_BRIEFS_ENABLED=false` disables synthetic brief generation/rehearsals while retaining synthetic customers for actual supplied inputs. `GENERALISATION_USERS_ENABLED=false` disables customer generation, evaluation and feedback. Brief generation with users disabled explicitly produces incomplete packs. Disabled features preserve saved artifacts without reusing their scores.

Offline rehearsals export **local compiled JSON**, labelled `platform_export=false`, under `local_out/`. They never create Freya workflows or simulations and need no Freya credentials. Production builds retain the supplied API URLs and use the real Freya adapter/export path under `out/`. Hosted Freya mock testing remains unavailable until rules permission and remote reachability are verified.

The development pack may provide grounded failure feedback after calibration. Holdout customers enter only evaluation of the final frozen export; they do not enter design/fix prompts. Source, configuration and pack hashes are checked. The two builds each use the existing maximum 30-minute deadline, including preparation, calibration, tests and export reserve. Live suites admit at most ten users before freezing; conservative estimates may admit fewer. Budget-skipped calls are unknown, never passes.

## Evidence and selection

The mock resolves operation URLs/methods/references through the existing contract compiler and checks explicit request/response/product bindings. Bank writes remain separate from policy judgement: an accepted but illegal promise fails independent grading. Unsupported contracts or source conflicts disable synthetic selection authority rather than supplying invented policy defaults.

Calibration runs eleven authored positive/negative controls, including a compiled controller with the configured extractor and scripted control utterances. Two blind transcript readings must agree; quotes must be real. Read-back/agreement proofs must match the actual product, amount and date and precede its write. Zero false passes, false failures and abstentions are required. Model, source, policy, API, mapping and Docker fingerprints bind admission to that version. These finite controls do not establish Freya equivalence or model perfection.

When official public tests apply, official scores rank candidates; calibrated synthetic critical failures can veto them. Generated scores remain separate. Without official tests, only admitted, complete generated measurements rank candidates. Calibrated development failures can reach the fixer; unknowns cannot be treated as actionable failures. Wording changes are measured at their own workflow hash. If every tested candidate is vetoed, the build fails and retains its tested artifacts for inspection. Otherwise an interrupted test/export preserves the eligible cached export when available.

A case passes only if every requested repetition passes. Incomplete evidence has no strict pass rate. One repetition is the existing development default (`EVAL_REPETITIONS`); use three for a three-run result. Standalone `evaluate` is diagnostic and carries no selection authority.

## Runtime and artifacts

Prepare the pinned image and keep Docker running:

```sh
docker pull python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
```

Code containers have no network or host mounts, a read-only root, an unprivileged user, dropped capabilities, and CPU/memory/process limits. Generated stdout cannot corrupt the protocol, and timed-out containers are removed. These controls use documented [Docker run options](https://docs.docker.com/reference/cli/docker/container/run/).

The proxy supports basic conversation/API/code/end nodes, extraction, ordered routes, pre-actions, mappings and Python hooks. Unsupported audio, custom extraction prompts, lifecycle tools, history summaries, silent conversation waits, previous-node routing, suppressed tool results and automatic tool retries abstain. `CAPABILITIES` in `runner.py` publishes the limits. Local extraction uncertainty differs from Freya token confidence; the user approved calibrated proxy feedback with this limitation recorded.

Brief/API inputs and released aggregate reports go under `artifacts/`. Customer facts, expectations, calibration transcripts, prompts and detailed builder evidence stay under `private/`, outside the dashboard's served root. Production exports go under `out/`; offline compiled exports go under `local_out/`. Runtime state uses `.runtime/`; the real adapter shares the original `agent/.runtime/workspace.lock` across entry points and fails closed without the lock. Generated outputs/secrets are ignored locally.

The regular dashboard at `http://127.0.0.1:8765/` discovers synthetic progress under
`agent/artifacts/synthetic_<run>/`. These entries publish only model-call starts, ends,
exception types, retries and numeric token counts. They never copy prompts, responses,
customer cases, private paths or holdout findings. The private trace remains authoritative.

## Verification

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest generalisation_agent/tests agent/tests observability/tests -q -p no:cacheprovider
GENERALISATION_TEST_DOCKER=true PYTHONDONTWRITEBYTECODE=1 python3 -m pytest generalisation_agent/tests/test_docker.py -q -p no:cacheprovider
```

**177 tests passed**, with three real Docker tests skipped in the ordinary suite. **All three real Docker tests passed separately**, including the actual compiled controller against renamed API fields, Python date arithmetic/output isolation and CPU termination. Model roles in these tests are fixtures, not live model evidence.

A live QwenCloud request through ADK/LiteLLM returned valid JSON using `qwen3.8-max-0902`,
thinking enabled and SSE streaming; its numeric usage appeared in the dashboard.
The subsequent two-pack generation attempt spent all 12,000 completion tokens on reasoning
in its first writer call and returned no answer. Its retry was interrupted and the run marked
failed. ADK maps `max_output_tokens` to the shared `max_completion_tokens` limit. The user
approved a minimum 65,536-token total limit for QwenCloud retries; synthetic users have not yet been exercised
through a QwenCloud-generated workflow.

A live Doubleword request through ADK/LiteLLM returned valid structured output using `zai-org/GLM-5.3-Flash`. Brief writing/checking uses medium reasoning; other Doubleword roles use low reasoning. Live generation exposed truncated outputs, ambiguous mapping/enum schema descriptions and conditional-rule interpretation failures. Mapping descriptions and bounded rewrite feedback were corrected; generation still fails closed when independent semantic checks disagree. No complete two-pack rehearsal or Freya deployment has been verified. The pinned Docker image was restored for the current local testing session.

The source checker counts an accurately documented conditional obligation as preserved even
when this policy makes it inactive. Omitting its meaning or merely naming it still fails;
every sampled policy value and API mapping must still match the independent reconstruction.

Review baseline remains commit `48ac224d78bf00fb9ab06df0f9a8c69ef49fc355`. `tools/smoke_test.py` is untouched. Builder integration covers configuration/output confinement, optional evaluation/deadline/export hooks and the adapter's shared lock/runtime state. Doubleword testing adds provider routing, and dashboard progress adds an optional trace observer.
