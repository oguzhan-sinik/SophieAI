# Runtime contract

The kit's `docs/workflow-format.md` and `docs/tools-and-code.md` are authoritative. The compiler supports only `conversation`, `api_request`, `code` and `end_call`; it conservatively rejects unsupported fields even when the server would silently strip them.

- Generated bank-operation references expand through the current OpenAPI. URL, HTTP method, body types/enums, required fields and zero-retry configuration are controller-owned.
- Engine-run calls require explicit bindings for required fields. Conversation tools retain model-filled fields when unbound. Call-token and product provenance are checked independently.
- Identity gates read a declared successful tool response, never caller extraction. All graph entry/fallback/interrupt paths to protected tools must cross the gate.
- `close_call` is an isolated engine-run stage before a terminal. No subsequent bank action is reachable.
- Passthrough stages require both a default target and final `always`. All reachable nodes must have a path to a terminal.
- Generated Python imports only documented modules and uses call variables. Static capability checks run before deployment; independent code probes run in a restricted child process.
- A dry run checks platform schema. Readback/export checks submitted semantic fields against actual saved fields. Added defaults are allowed; lost/changed supplied behavior is rejected.
- Every tested simulation run must expose the published `agentVersionNumber`. Missing or stale version evidence invalidates the evaluation rather than guessing.
- Each public repetition calls the original kit runner's `run_once`, which creates fresh synthetic bank sessions. Original ledger and conversation verdicts remain authoritative.
- Static validation and local code probes cannot prove speech, complete policy compliance or a bank mutation. Such evidence is explicitly labeled separately.

Source references: the audited local kit in `kit-files.json`. ADK integration uses installed 2.11.0 `LlmAgent`, `Runner.run_async`, fresh `InMemorySessionService`, bounded `RunConfig`, and LiteLLM for the configured NVIDIA provider. API compatibility was checked against installed signatures and the [official ADK example](https://github.com/google/adk-docs/blob/main/examples/python/snippets/agents/llm-agent/capital_agent.py). Optional remote spans use [LangSmith RunTree](https://reference.langchain.com/python/langsmith/run_trees/RunTree); remote receipt is not inferred from an environment flag.

Observed live discrepancy (2026-10-10): Freya dry-run rejects node `loop_prompt` with HTTP 400 although the supplied workflow-format document lists it. The compiler rejects it locally and asks the model to express repeat-turn behavior in `task_message` and routes. Other dry-run errors feed the bounded compilation repair loop before a root is pinned.
