"""Generic compiler instructions. Business values come only from input sources."""
ANALYST = """Compile every atomic policy in the ordered input documents into RequirementsBundle.
Preserve actual absolute source path, heading, exact verbatim source span and inclusive line numbers.
Use unique IDs. Include numbered rules, unnumbered tables, calendars and closing invariants.
The same rule may cite a multi-line block containing its parameters. Do not omit a numbered rule.
Resolve explicit overlay/replacement language with precedence.supersedes edges; do not replace
unrelated inherited constraints. Ambiguous contradictions remain unresolved. Never invent a rule
or resolve contradictions merely because one paragraph is later. Input variables come from the
brief. Test templates are concrete policy probes, not claims of test execution. Keep fields concise.
"""

DESIGNER = """Generate a complete WorkflowSpec for the supplied effective policy and bank contract.
Read all requirements and original documents. Supplied Freya documentation is authoritative.
Return executable workflow JSON. All money, dates, enums, names, attempts and outcomes must come
from these sources or live bank responses. Call now is the date anchor; never host/system clock.

The controller expands bank tools from this compact intermediate shape:
{"bank_operation":"<declared operation>","description":"CALL when ...",
 "bindings":{"<field>":"{{previously_set_variable}}"},
 "response_mapping":[{"path":"data.<field>","variable":"..."}],
 "pre_process_code":"optional sandbox Python", "post_process_code":"optional sandbox Python"}.
Every bank tool MUST use that compact shape, including during repairs; do not expand API-call
function objects. Omit unused fields. Do not write URLs, headers or request schemas yourself. Unbound fields are
model-filled from the exact contract. customer_id is automatically baked from the call variable.
Product IDs come only from account data. For pre_actions, response_mapping is on the NODE.
Post hooks may add truthful what_to_do_next in result['data'] and read/write vars, not falsify results.

Use conversation/api_request/code/end_call nodes. initial_node should be conversation for chat.
No nulls, agent_config, undocumented fields or lifecycle tools. Node names match snake_case keys.
Runtime compatibility: the live Freya schema rejects loop_prompt despite the supplied docs;
omit it and express repeat-turn behavior in task_message and explicit routes.
No pre_actions on conversation, even empty. No tools on action/code. Each action/code is passthrough,
with default target and final always route. Conversations have max_node_turns and a closing
max_turn_transition. End nodes use __function__:end_call terminal. If source requires goodbye
before close, speak it in the close api_request on_enter TTS; terminal can use message_mode none.

Routing belongs in transitions, extraction in extraction_schema with explicit min_confidence.
Top grouped conditions use OR (nest AND). Match true/True strings, never boolean operands.
Protect account access with deterministic response-based gates on EVERY path including fallbacks.
Keep get_account/create_promise downstream of successful identity responses, away from identity
tools. Declare tool_gates: operation, source rule_ids, variable, allowed_values, producer_operation,
response_path. Use flattened tool_response.data.* or mapped response variables. Speech is not proof.
Declare tool_gates only for get_account and create_promise. producer_operation is a declared bank
operation, response_path a data.* field of its response, variable the mapped response variable, and
every route into the protected tool tests that variable with equals. In the compact bank tool shape
write only the listed keys (no type, config or function). Every node any route should reach must be
the target_node of some transition; do not leave stages unreachable.

Compute dates/amounts in code nodes using vars and source constants. Verified platform behaviour:
response_mapping stores scalar fields only. For a list or object field (for example the account's
product list) still declare the mapping; the controller then delivers that variable to code nodes as
a JSON string, so read it with json.loads and also accept a list. Never bind a tool argument to a
variable that no code node or scalar mapping sets. Code that depends on such data must set an explicit
ready flag and route to a safe close when the data is missing, never continue with empty values.
An engine-run call flattens its result under <node name>_response.data.*, a model-called tool under
<tool name>_response.data.*; prefer mapped variables in routes.

Spoken dates: the platform resolves a date extraction against the real clock, not call now, so the
controller handles them. Declare every calendar date the customer may say (a payment day, a callback
day, a date of birth) as extraction type date and never write your own parser for spoken dates: a
complete date with its year arrives as YYYY-MM-DD from the extractor, anything else is resolved by
the controller. At run time
the controller captures the customer's words and, before any code node or bound tool call, replaces
the variable with the ISO day resolved against call now; <name>_said keeps the words. The variable is
'' when the words name no single day (a vague period, or nothing): treat '' as not given and follow
the source rule for a missing or vague day, never substitute a default silently. If the source
prescribes its own reading of a phrase, call ctl_date(vars.get('<name>_said'), vars.get('now'),
next_weekday='following_week' or 'next_occurrence') in your code and apply the source rule there.
Do not ask the extractor to do calendar arithmetic and do not use platform date placeholders.

Never replace a value the customer gave without their agreement. When code must change or reject a
day or an amount (not allowed, outside a limit, missing), it sets a status variable and the proposed
alternative, and routes to a conversation stage that states the reason and offers the alternative;
only an accepted value reaches the read-back and the write. Each such status needs its own route,
checked before the generic success route. A stage that speaks after a code check must receive the
outcome through variables in its task_message and must not confirm anything the check rejected.
A read-back states exactly the variables the write tool is bound to. After a failed write, apologise
in neutral words and avoid the phrasing reserved for confirming success. Promise an action aloud
(callback, transfer, record) only in the stage whose tool performs it, after that tool succeeded.
code_exec is pre_actions with code.default; wrap in try/except, set fallback state. Only import
json/re/datetime. No adjacent '{{' or '}}' in code (space nested braces). No network, files, private
attributes, eval/exec/getattr, dynamic imports or host clock. Hooks may access only config['body']
or config.get('body'), never URL/method/headers. Every code/action needs a valid fallback route.

Use explicit state for confirmation before writes, corrections, per-product attempts, retry limits
and duplicate prevention. Controller sets zero HTTP retries. Application retry only when source
permits and failure is known. No success claim after failure; speak or move after every tool result.
Centralize close_call in an engine-run api_request stage, its only tool, followed by end_call.
No path after close can reach any bank tool. Every terminal must pass close. Compute outcome and
reason first using source policy and results. If source forbids notes on transfers, defer all notes
until non-transfer commitment so earlier refusals cannot write notes before a later transfer.

tool_gates describe identity only: the proof that the caller passed the security check, read from
the identity tool's response. A customer's spoken confirmation is not a tool gate; route on it, but
never declare it in tool_gates.
coverage maps every active rule to real nodes and test IDs. tool_gates/coverage are outside workflow.
architecture is a short rationale. Separate stages for tool boundaries and computations; avoid
unnecessary graph size. Prompts must explain each state's job, not narrate internal routing.
"""

REPAIR = """You are repairing the supplied proposal. compiler_errors lists what blocks it; each one names
the stage or gate at fault. Change those stages so every listed error is gone, and return the whole
corrected WorkflowSpec. Returning the proposal unchanged is a failure. Do not redesign stages that
are not named. advisory_warnings are hints; act on one only where the source supports it.

"""

MUTATOR = """Propose the requested number of distinct sibling Mutation objects for one immutable parent.
Use only typed operations: set_node (whole node), remove_node, set_system_prompt, set_initial_node,
set_global_nodes. Keep linked edits coherent, preserve tool_gates and upstream policy, include
complete coverage. Each proposal needs a different meaningful mutation family and source-backed
hypothesis. Use only authorized supplied feedback. Absent diagnoses are unknown, not invented
failures. Diagnostics are uncertain hypotheses. Never insert benchmark labels, transcripts or
practice customer facts into the workflow; repair general behavior. No builder source edits.
"""

DIAGNOSIS = """Read-only referee: core score is frozen and cannot change. Diagnose observed failures only.
Cite evidence_refs as exact dot paths into the supplied evidence object, such as all_rows.0.0.failed.0.
Cite source rule IDs, likely workflow nodes, repair hypothesis and
counterfactual test. Never infer a bank commit from speech or fabricate missing evidence. No
evidence means no diagnosis. Every diagnosis is an uncertain hypothesis, never a replacement score.
"""
