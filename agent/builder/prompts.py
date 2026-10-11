"""Instructions for the three model roles. Business values come only from the input sources."""
ANALYST = """Compile every atomic policy in the ordered input documents into RequirementsBundle.
Preserve actual absolute source path, heading, exact verbatim source span and inclusive line numbers.
Use unique IDs. Include numbered rules, unnumbered tables, calendars and closing invariants.
The same rule may cite a multi-line block containing its parameters. Do not omit a numbered rule.
Resolve explicit overlay/replacement language with precedence.supersedes edges; do not replace
unrelated inherited constraints. Where the documents contradict each other without saying which
one holds, mark the rules conflicting and list the question in unresolved; never invent a rule or
settle a contradiction merely because one paragraph is later. Input variables come from the brief.
Keep fields concise.

Then derive probes: acceptance tests that pin the rules the customer's own speech can trigger.
Each probe is one short call: acts are the customer's utterances in order, in plain words; expected
is the closing bank record the rules demand for that exact call (outcome, reason, and any recorded
promise or transfer with its values). Cover every rule that changes what the agent records or says
on a triggerable condition: identity failures, callbacks, refusals, hardship, disputes, plan
requests, corrections, vague and out-of-range dates, below-floor amounts, deadline pressure, tool
failure, third parties. One probe per distinct rule behaviour; reuse earlier rules only where the
call really traverses them. Acts and expectations come only from the rules; never from any practice
customer you may have seen. The expected values must be the ones the rules compute (floors,
deadlines, outcomes), not the ones a real customer once gave.
"""

# How to write a workflow or any part of one. Shared by the designer and by every fix.
RULES = """All money, dates, enums, names, attempts and outcomes must come from the source documents or
from live bank responses. Call now is the date anchor; never the host or system clock.

WORKFLOW SOURCE. You write a compact source; the controller compiles it for the platform.
Stages are conversation, api_request, code and end_call nodes under workflow.nodes, each with a name
equal to its snake_case key. initial_node is a conversation stage. No nulls, agent_config,
undocumented fields or lifecycle tools. The live schema rejects loop_prompt: express
repeat-turn behaviour in task_message and explicit routes. Every stage a call should reach must be
the target_node of some transition.

Every bank tool runs in its own api_request stage, as the single entry of pre_actions, never as a
tool of a conversation stage. A conversation stage asks, extracts the reply into variables and
routes; the api_request stage it routes to makes the call, and the routes out of that stage read the
mapped result. This is how every call is certain to happen once, with the values the controller has
normalised. A bank tool is always written in this shape, with only these keys:
{"bank_operation":"<declared operation>","description":"CALL when ...",
 "bindings":{"<field>":"{{previously_set_variable}}"},
 "response_mapping":[{"path":"data.<field>","variable":"..."}],
 "pre_process_code":"optional Python","post_process_code":"optional Python"}
Omit unused keys. Never write URLs, headers, request schemas, type or config: the controller takes
them from the contract and sets zero retries. customer_id is bound automatically. Product ids come
only from account data. Every other required field needs a binding to a variable that an extraction
or a code stage has set; an answer the customer gives as a date is bound to its date-typed
extraction variable, never to free text. Post hooks may add a truthful
what_to_do_next to result['data'] and read or write vars; they never change what a tool returned.

Code stage: {"name":"...","node_type":"code","code":"<Python source>","transitions":[...]}.
Write the Python as plain text in code. The controller adds the execution wrapper, makes api_request
and code stages run silently and route at once, and uses their last transition, which must be
always, as the fallback. Code reads vars.get('name') and writes vars['name']; it is wrapped in
try/except and sets a fallback status on error. Import only json, re and datetime. No adjacent
double braces in code (put a space between nested braces). No network, files, private attributes,
eval/exec/getattr, dynamic imports or clock calls. Hooks may read config['body'] only.

Conversation stage: it does one thing. It asks one question or makes one offer, extracts the reply
and routes. task_message says what this stage is for, not how routing works, and does not carry the
policy for several steps: what decides between outcomes lives in code stages and transitions. Give
max_node_turns and a max_turn_transition that closes the call correctly. A conversation stage has no
tools and no pre_actions. End stages use an
__function__:end_call terminal and have no transitions.

ROUTING. Routing lives in transitions, extraction in extraction_schema with an explicit
min_confidence on every variable. Top-level grouped conditions use OR (nest AND inside). Compare
with the strings true/True, never boolean operands. List the values of every variable a stage routes
on in enum_values and give each value that should move the call its own transition. An agreement to
what the stage just proposed is such a value: route it, never wait for the customer to repeat a
number or a date the stage itself stated.

IDENTITY. Protect account access with deterministic, response-based routes on EVERY path, including
fallbacks and turn caps. get_account and create_promise may only be reached after verify_identity
has run and a transition after it has tested its result: a mapped response variable, the flattened
<stage>_response.data.* value, or a status that a code stage derives from that response. What the
caller says is never proof of identity: no alternative of such a route may test an extracted value.

TOOL RESULTS. response_mapping stores scalar fields only. For a list or object field (for example
the account's product list) still declare the mapping; the controller delivers that variable to code
stages as a JSON string, so read it with json.loads and also accept a list. Never bind a tool
argument to a variable that no code stage or scalar mapping sets. Code that depends on such data
sets an explicit ready flag and routes to a safe close when the data is missing: a status a code
stage sets is tested by that stage's own transitions, and a stage is never entered to speak a line
built from values that may be empty. An engine-run call
flattens its result under <stage name>_response.data.*, a model-called tool under
<tool name>_response.data.*; prefer mapped variables in routes.

HUMAN SPEECH. Callers split answers across turns, ask questions, correct themselves and mention
unrelated numbers/dates. Keep one pending slot, its ordered fragments, raw words, completeness,
source turn and revision. Never pad missing digits or guess a birth year. Security dates need an
explicit year; capture partial security dates as strings, clarify, and assemble before verification.
Ask only for the missing part. Answer questions safely, then resume; a question, tangent or brief
acknowledgement is not consent or a refusal. Latest explicit self-correction wins. Clarify ambiguous
product references; never copy a loan correction onto the card. Preserve known amount while asking
for an uncertain date. Do not extract the first date/money from an unrelated story.
The runtime also provides ctl_digits(said) (ordered digit words, preserves zeros),
ctl_identity_date(said) (complete identity date only, never substitutes a year),
ctl_slot(vars,name,value,raw,complete,turn,correction=False) (clears incomplete routable values),
ctl_proposal(vars,product,amount,day) (returns tuple revision and invalidates changed consent),
ctl_invalidate(vars,product), ctl_consent(vars,product,revision,explicit), and
ctl_write_ready(vars,product,amount,day). Use these in code stages. Money passed to these helpers is
already unambiguous numeric cents; spoken ambiguity must be clarified first. Before read-back save
the proposal revision; explicit agreement is scoped to that exact revision. Every correction,
including "yes, but...", invalidates old consent. Require ctl_write_ready plus source policy checks
before each write. These helpers do not enforce the bank's policy. For grouped consent check every
named member's current revision and source permission; no blanket yes for other products.

DATES. The controller provides these functions inside every code stage; use them and never write
your own calendar loop or spoken-date parser. weekdays is the list of business weekdays with
Monday=0 and excluded the list of non-business ISO dates, both always taken from the source:
  ctl_is_business_day(day, weekdays, excluded) -> True/False
  ctl_add_business_days(day, count, weekdays, excluded) -> the count-th business day after day
  ctl_business_day_on_or_after(day, weekdays, excluded) -> day itself if a business day, else the next
  ctl_last_business_day_of_week(day, weekdays, excluded) -> last business day of day's Mon-Sun week
  ctl_date(said, call_now, next_weekday='following_week' or 'next_occurrence') -> the day a phrase names
All return YYYY-MM-DD text, or '' when the day cannot be worked out.
Declare payment and callback days as extraction type date. Security dates are strings: preserve
fragments, require an explicit year, and call ctl_identity_date on the assembled complete words. A complete date with its year arrives as YYYY-MM-DD; anything else is
captured as the customer's words and, before any code stage or bound tool call, replaced by the day
resolved against call now, with <name>_said keeping the words. The variable is filled only when the
customer names one single day; a vague period leaves it unset or ''. So a stage that asks for a day
extracts the date there, routes a vague answer through its own listed value, and tests that value
before any is_set route on the date. Treat '' as not given and follow the source rule for a missing
or vague day; never substitute a default silently. Where the source prescribes its own reading of a
phrase, call ctl_date on <name>_said in code. Do not use platform date placeholders.

OFFERS AND WRITES. Never replace a value the customer gave without their agreement. When code must
change or reject a day or an amount, it sets a status variable and the proposed alternative and
routes to a conversation stage that states the reason and offers the alternative. Each status has
its own route, tested before the generic success route. When the customer accepts an offered
alternative, the accepting route first passes a code stage that copies the offered value into the
variable the check reads; routing an acceptance straight back into the check changes nothing and
loops. Only an accepted value reaches the read-back and the write. A read-back states exactly the
variables the write tool is bound to. A stage that speaks after a check receives the outcome through
variables in its task_message and never confirms what the check rejected. Say that something is
recorded, booked or transferred only in the stage after the tool that did it succeeded; in every
other stage say nothing of the kind. After a failed write, apologise in neutral words. Retry a write
only where the source permits it and the failure is known.

Keep explicit state for confirmation before writes, corrections, per-product attempts, retry limits
and duplicate prevention. Speak or move on after every tool result.

CLOSING. close_call runs in its own api_request stage, as its only tool, followed by an end stage.
Every end stage is reached only through a close stage and nothing after close can reach a bank tool.
Work out the outcome and reason from the source policy and the results before closing. If the source
requires a goodbye before close, speak it in the close stage's on_enter tts; the terminal can then
use message_mode none. If the source forbids notes on transfers, defer all notes until the call can
no longer end in a transfer.

Use separate stages for tool boundaries and computations, and no more stages than the policy needs.
"""

DESIGN = """Design a phone agent for the supplied bank policy and tool contract, as a WorkflowSpec.
Read the original documents in full; requirements, when supplied, is a checklist extracted from them
and the documents win where the two differ. When requirements carries probes, they are acceptance
tests: each names customer acts and the closing bank record the finished agent must produce for
them. Design so that every probe would pass: its expected outcome, reason, promise and transfer
values must be reachable through explicit routes, extraction values and code checks in your
workflow — a rule that a probe exercises must be decided by logic, not left to the dialogue
model's judgement. The supplied Freya documentation is authoritative for
the platform. Write architecture first, then the complete workflow source.

""" + RULES

FIX = """You are fixing a phone agent workflow that already exists. Return a Patch: a list of fixes,
each a small set of edits to the supplied workflow source. Everything you do not name stays exactly
as it is, so never repeat an unchanged stage or field.

An edit is one of:
  set_field (stage, field, value): replace one field of one existing stage, such as its task_message,
    transitions, extraction_schema, code or pre_actions. value is the complete new value of that field only.
  set_stage (stage, value): add a new stage, or replace a whole one when field edits cannot express it.
  remove_stage (stage).
  set_workflow_field (field = system_prompt or initial_node, value).
Prefer the smallest edit: one field over a stage, one stage over several. A route change is an edit
to that stage's transitions; a wrong calculation is an edit to that stage's code.

problems lists what must be fixed.
- Compiler problems each name the stage at fault and say what is wrong. Fix every one of them.
- For failed practice calls, calls holds each failed call step by step: every spoken turn with the
  stage it ran in, each stage change with the route that fired, extracted values, tool calls and
  results. Read the call before the judge's summary. Find the first step where it went wrong (a
  route that did not fire, a value never extracted, a code result, a tool that was not called) and
  fix that stage.
probes, when present, are acceptance tests derived from the source policy: customer acts and the
bank record the call must end with. When a failed call broke one, fix toward that expected record.
Write one fix per distinct cause. In cases list the customers it is for; in problem say what goes
wrong and in which stage. Do not change what is not shown to be broken.

hints are static observations that may or may not matter. Act on one only when a failed call or the
source policy supports it.
history lists earlier fixes. Kept fixes are already in the workflow. Blamed fixes broke a customer
that passed before and were taken out; rejected fixes could not be applied, for the stated reason.
Do not submit either again: remove the cause in a different way.
If wording_only is true, only edits that change wording alone (task_message, role_message,
system_prompt, a fixed spoken line) will be applied; a description, a route or an extraction is not
wording.
Never write a practice customer's name, amounts, dates or expected results into the workflow:
repair the general behaviour the source policy asks for. If nothing can be fixed, return no fixes.

The rules below describe a whole workflow. Every value you write must follow them.

""" + RULES
