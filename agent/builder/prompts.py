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
"""

CONTRACT = """Write the OpenAPI 3.0 document of the bank services a phone agent calls during a call, from the
supplied bank documents. They describe those services in prose, tables or examples, in any language.
One operation for each service the documents describe as callable during a call, and no other.
operationId is the service's name exactly as documented. The HTTP method and path are the documented
ones; where the documents give none, POST and the path /<operationId>. requestBody: an object
schema with every documented field, its type, its allowed values as enum, format date for calendar
dates, and required for the fields documented as mandatory. responses.200: an object schema with
every documented response field and its type; a documented list of objects is an array with its
item fields. Put each field's documented meaning in its description, in the documents' own words.
servers: one entry with the supplied server URL. No security schemes and no path, query or header
parameters: a documented value passed in the path or the query is written as a body field of the
same name. Invent nothing: no operation, field, value or default the documents do not state.
compiler_errors lists what was wrong with your previous answer; correct exactly that.
List in notes what the documents leave unclear about a service.
"""

# How to write a workflow or any part of one. Shared by the designer and by every fix.
RULES = """All money, dates, enums, names, attempts and outcomes must come from the source documents or
from live bank responses. Call now is the date anchor; never the host or system clock. Documents that
list single customers, accounts or example conversations show the data and the way people speak:
nothing about one customer (a name, a number, an amount, a date) is written into the workflow.

LANGUAGE. The agent speaks the language the source documents are written in and their example
conversations use. Every spoken line is in that language: fixed tts text, terminal messages and
whatever a task_message tells the agent to say; system_prompt names the language and keeps the agent
in it. Stage names, variable names, enum values, tool fields and outcome codes keep the exact
spelling the sources and the contract give them and are never translated. Every example in these
rules is English and only an illustration: never copy its wording, write what it stands for in the
language of the call. Extraction descriptions say, for each value, what the caller says for it in
that language. The controller helpers read English and Turkish.

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
or a code stage has set; a payment or callback day is bound to its date-typed extraction
variable, an amount to a variable a code stage set as a number, a security number to the variable
ctl_collect completed and a security date to the variable a code stage set with ctl_identity_date,
never to free text. Post hooks may add a truthful
what_to_do_next to result['data'] and read or write vars; they never change what a tool returned.

Code stage: {"name":"...","node_type":"code","code":"<Python source>","transitions":[...]}.
Write the Python as plain text in code. The controller adds the execution wrapper, makes api_request
and code stages run silently and route at once, and uses their last transition, which must be
always, as the fallback. Code reads vars.get('name') and writes vars['name']; it is wrapped in
try/except and sets a fallback status on error. Import only json, re and datetime. No adjacent
double braces in code (put a space between nested braces). No network, files, private attributes,
eval/exec/getattr, dynamic imports or clock calls. Hooks may read config['body'] only.
A code stage decides one thing and sets one status that its own routes test. What would decide
several things is several code stages of well under 120 lines each, because one mistake in a
large stage closes the call for every case it handles. Every silent stage between the caller's
words and the agent's next line costs the caller seconds: keep that chain to two or three stages.
A value the caller's words fill can be unset. Test it before int() or float() and decide what a
missing value means there; the controller rejects an untested conversion. An amount or a day the
caller names by reference (the full amount, the minimum, the same day, that one) has no number or
date of its own: code takes it from what the stage offered.

Conversation stage: it does one thing. It asks one question or makes one offer, extracts the reply
and routes. It extracts at most five values: what its own routes test and what the next code stage
needs from this reply. Every extracted value is a model call on every turn and the caller waits for
all of them. task_message says what this stage is for, not how routing works, and does not carry the
policy for several steps: what decides between outcomes lives in code stages and transitions. Give
max_node_turns and a max_turn_transition that closes the call correctly. A conversation stage has no
tools and no pre_actions. End stages use an
__function__:end_call terminal and have no transitions.

ROUTING. Routing lives in transitions, extraction in extraction_schema with an explicit
min_confidence on every variable. Top-level grouped conditions use OR (nest AND inside). Compare
with the strings true/True, never boolean operands. List the values of every variable a stage routes
on in enum_values and give each value that should move the call its own transition. An agreement to
what the stage just proposed is such a value: route it, never wait for the customer to repeat a
number or a date the stage itself stated. Describe every value in enum_values by what the caller
says for it, and where a reply could fit two values say which one it is. A reply that fits a
specific value and a general one is the specific one: what the caller said about the amount or the
day is decided before a general intent.

IDENTITY. Protect account access with deterministic, response-based routes on EVERY path, including
fallbacks and turn caps. get_account and create_promise may only be reached after verify_identity
has run and a transition after it has proved its result with equals against the value that means
verified: a mapped response variable (all_verified equals true), the flattened
<stage>_response.data.* value, or a status that a code stage derives from that response (equals
verified). is_set, an HTTP status code, a success or failure counter, a turn count and a test for a
failed result are not proof. What the caller says is never proof of identity: no alternative of
such a route may test an extracted value. A stage that can be entered both before and after identity
(one that answers a question or a request for a person and then returns the caller to where the call
was) leads back into the stages after identity only on a transition that tests the identity tool's
own mapped result (all_verified equals true), in an AND with the remembered position; a remembered
position alone is not proof, and neither is a status code wrote somewhere else.

TOOL RESULTS. response_mapping stores scalar fields only. For a list or object field (for example
the account's product list) still declare the mapping; the controller delivers that variable to code
stages as a JSON string, so read it with json.loads and also accept a list. Never bind a tool
argument to a variable that no code stage or scalar mapping sets. Code that depends on such data
sets an explicit ready flag and routes to a safe close when the data is missing: a status a code
stage sets is tested by that stage's own transitions, and a stage is never entered to speak a line
built from values that may be empty. An engine-run call
flattens its result under <stage name>_response.data.*, a model-called tool under
<tool name>_response.data.*; prefer mapped variables in routes.
A mapping path starts at data. and then follows the answer's own structure: where the service's
answer is itself an object with parts ({"data": {...}, "result": {...}}), its fields are mapped as
data.data.<field> and data.result.<field>. A request whose fields sit inside objects is shown in the
contract as one level of fields: bind each by its name, the controller sends it in its documented
place. A value every call starts with (a customer number, the call's now) is a variable from the
first stage on: bind it as {{its name}}, spelled as the sources spell it.
A call that fails leaves no result. When the service answers with an HTTP error status (404, 500)
or not in time, no response field is mapped and no post hook runs. What the engine sets then is
<stage name>_status_code (the HTTP status, for example 404; not set after a timeout),
<stage name>_response.message (the error answer as text; code can look for a documented error code
in it) and <stage name>_failure_count. So the routes out of a tool stage test success first, on a
mapped value that only a good answer carries; then, where the sources tell kinds of failure apart
(a documented "not found" answer says something about the customer, a 500 or no answer is a broken
service), one route for each documented status, <stage name>_status_code equals 404; and last the
always route, which is every other failure. Nothing that must happen after a failure is written in
a post hook. Before a call is tried again, a code stage clears the variables its earlier try mapped
and counts the tries itself.

HUMAN SPEECH. Callers talk like people, and the customers this agent is tested with do all of
the things below. Spread what follows over stages, one question per conversation stage and one
decision per code stage; never build one stage that handles every kind of reply.
1. A number in two parts ("463", then "51"). The stage that asks for a number extracts only what
this reply says of it, as a string of the caller's own words: digits or words, never completed and
never joined with an earlier part by the extraction model. A code stage passes those words to
ctl_collect(vars, name, said, count), count being the length the source states. It joins the parts
in order, keeps zeros, and returns the number only when it is whole. While <name>_complete is no the
agent asks for the rest only and no tool is called. <name>_heard no means this reply held no digits
(a question, a hold): answer or wait, then ask again; it is not a wrong answer and costs no attempt.
Where the source states no length, ask for the whole number in one piece. A date in two parts (day
and month, then the year) is kept the same way: join the words of the parts in order and call
ctl_identity_date on them; it returns '' until day, month and year are all there. Never pad missing
digits or guess a year. Ask only for the missing part.
2. Corrections ("the 21st, sorry, the 20th"). The last value said is the value. The helpers read
what follows a correction word first, so give them the caller's whole reply. A correction to a value
that was read back or agreed makes the old agreement void: new read-back, new explicit yes. "Yes,
but ..." is a correction, not a yes. Clarify ambiguous product references; never copy a loan
correction onto the card. Preserve a known amount while asking for an uncertain date.
3. Other things. A caller tells a story with a number or a day in it (what was paid last week, a
wedding on the 30th). It is not an answer: extract nothing from it, reply in one short line, ask the
pending question again. Only what the caller proposes in answer to this stage's question is a value.
4. A question back ("why do you need that?", "which account?", "are you a robot?"). Every stage
that asks something has a reply value for a question; it gets one safe line of answer and then the
same question again. A question, a hold ("one moment") and a bare acknowledgement ("ok", "I see")
are none of answer, refusal or consent, and they use up no attempt of any kind.
5. Amounts and dates in words ("four hundred and fifty-five", "the twenty-second of October").
Never let the extraction model do arithmetic on spoken words or turn words into a calendar date.
Declare a day as extraction type date and an amount as extraction type amount: the controller
captures the caller's words and converts them before any code runs (DATES AND AMOUNTS below).
6. One of several ("all three", "the card", "not the car loan"). When the call is about several
things of one kind (products, accounts), callers name them their own way, and one reply can answer
for several at once: "I can pay all three on Friday", "the card tomorrow, but not the loans". Code
never compares the caller's words with fixed text (==, a list of phrases, a substring test): "the
credit card" is not "credit card", and the controller rejects such a comparison. The stage extracts
the caller's whole reply as their own words, and a code stage calls ctl_choice(said, names). names
has one entry for each thing, in the order of the account data; an entry is a list of what the
thing is called (its type, the label the agent says, its card ending). It returns a dict: chosen,
declined and unclear are lists of positions in names, and kind is one, several, all, declined,
unclear or none. Every chosen thing takes the day and the amount of that reply and is then checked
against its own rules; a reply about all of them is about every thing still open. A thing declined
in a reply to a question about all of them has used up nothing of its own: it is then handled the
way the source handles each thing by itself, and what the caller already agreed for another thing
in that reply is kept, not asked again. Ask "which one?" only when kind is unclear, naming the
choices, and read that answer with ctl_choice too. When kind is none, the reply is about what the
stage asked (the one thing it named, or all of them). The agent never says that it can only take
one thing at a time.
A reply cut off mid-sentence gives what it completes: keep that, ask only for what is missing.
A value that holds the caller's own words (not one of a list) gets min_confidence 0.4 at most: a
long string of copied words scores low, a discarded capture looks to the stage like silence, and the
code checks the words anyway. The task_message of a stage that asks again names the thing asked for
in full each time ("the date of birth"), never only "the missing part".
The runtime provides ctl_digits(said, count=0) (digits in order however they were said: one by one,
in groups, as numerals; zeros kept; '' when another word is among them),
ctl_collect(vars, name, said, count) (above),
ctl_amount(said) (an amount in words or digits as text like 1250.50, '' when there is no single amount),
ctl_choice(said, names) (which of several known things the words name; item 6 above),
ctl_identity_date(said) (complete identity date only, never substitutes a year),
ctl_slot(vars,name,value,raw,complete,turn,correction=False) (an incomplete value becomes '' and
<name>_complete becomes no: route on <name>_complete equals yes, never on is_set),
ctl_proposal(vars,product,amount,day) (returns tuple revision and invalidates changed consent),
ctl_invalidate(vars,product), ctl_consent(vars,product,revision,explicit), and
ctl_write_ready(vars,product,amount,day). Use these in code stages. Money passed to these helpers is
already unambiguous numeric cents; spoken ambiguity must be clarified first. Before read-back save
the proposal revision; explicit agreement is scoped to that exact revision. Every correction,
including "yes, but...", invalidates old consent. Require ctl_write_ready plus source policy checks
before each write. These helpers do not enforce the bank's policy. For grouped consent check every
named member's current revision and source permission; no blanket yes for other products.

DATES AND AMOUNTS. The controller provides these functions inside every code stage; use them and
never write your own calendar loop, spoken-date parser or number-word parser. weekdays is the list of business weekdays with
Monday=0 and excluded the list of non-business ISO dates, both always taken from the source:
  ctl_is_business_day(day, weekdays, excluded) -> True/False
  ctl_add_business_days(day, count, weekdays, excluded) -> the count-th business day after day
  ctl_business_day_on_or_after(day, weekdays, excluded) -> day itself if a business day, else the next
  ctl_last_business_day_of_week(day, weekdays, excluded) -> last business day of day's Mon-Sun week
  ctl_date(said, call_now, next_weekday='following_week' or 'next_occurrence') -> the day a phrase names
All return YYYY-MM-DD text, or '' when the day cannot be worked out.
Declare payment and callback days as extraction type date. Security dates are strings: preserve
fragments, require an explicit year, and call ctl_identity_date on the assembled complete words.
It returns '' until the words hold a day, a month and a year: that code stage sets a status and
routes on it with equals, because a variable set to '' can still count as set.
For a payment or callback day, a complete date with its year arrives as YYYY-MM-DD; anything else is
captured as the customer's words and, before any code stage or bound tool call, replaced by the day
resolved against call now, with <name>_said keeping the words. The variable is filled only when the
customer names one single day; a vague period leaves it unset or ''. So a stage that asks for a day
extracts the date there, routes a vague answer through its own listed value, and tests that value
before any is_set route on the date. Treat '' as not given and follow the source rule for a missing
or vague day; never substitute a default silently. Where the source prescribes its own reading of a
phrase, call ctl_date on <name>_said in code. Do not use platform date placeholders.
An amount the caller gives is declared as extraction type amount (the controller's own type). It is
captured as the caller's words and, before any code stage or bound tool call, replaced by the number
as text with two decimals (1250.50), with <name>_said keeping the words; or by '' when the words
hold no single amount: a reference without a number (the full amount, the minimum), two amounts, or
a split that can be read two ways. Code tests it before float(). A reference is settled from what
the stage offered; '' without a reference is one question back for the amount in one piece. Amount
words given over two turns are joined in order and passed to ctl_amount.

OFFERS AND WRITES. Never replace a value the customer gave without their agreement. When code must
change or reject a day or an amount, it sets a status variable and the proposed alternative and
routes to a conversation stage that states the reason and offers the alternative. Each status has
its own route, tested before the generic success route. When the customer accepts an offered
alternative, the accepting route first passes a code stage that copies the offered value into the
variable the check reads; routing an acceptance straight back into the check changes nothing and
loops. Only an accepted value reaches the read-back and the write. An acceptance that repeats the
offered values ("I accept 540 on the 27th") is an acceptance when the values equal the offer:
compare them in code, do not treat it as a new proposal. The same holds at the read-back, also when
several things are read back together: a yes that repeats a day or an amount the read-back stated
changes nothing and is the confirmation. A reply is a change only when code finds a value in it
that differs from what the stage stated. A read-back states exactly the
variables the write tool is bound to. A stage that speaks after a check receives the outcome through
variables in its task_message and never confirms what the check rejected. Say that something is
recorded, booked or transferred only in the stage after the tool that did it succeeded; in every
other stage say nothing of the kind. A word the source allows only after an event is reserved for
it: before that event the agent does not say that word at all, not even about something else,
because a checker looks for the word itself. Where the source also asks for an earlier sentence
that would use it (a notice that the call is recorded, when "recorded" is reserved for a
successful write), keep the meaning and change the words: "we are recording this call". After a failed write, apologise in neutral words. Retry a write
only where the source permits it and the failure is known. A caller may ask or assume that
something was recorded ("you have noted it, haven't you?"): the answer comes from the tool's result
variable only. system_prompt says, in the language of the call, that the agent never states that
something was recorded, booked, sent or transferred unless the instructions of the current stage
say the tool confirmed it. The agent's model likes to thank a caller who agrees with "I have
recorded that". Where an agreement is written only later (after a read-back, after the other
things), the task_message of the stage that follows gives the agent its acknowledgement in true
words without the reserved word ("Thank you.") and says that nothing is written yet.
system_prompt also says that the agent never says goodbye, never offers more help ("anything
else?") and never sums the call up by itself: a call ends only in its closing stages, and a stage
that waits for an answer asks its question again instead. A caller who is told goodbye too early
answers goodbye, and the stage then waits for an answer that never comes.
A stage that needs no answer does not wait for one: after a line that asks nothing (a confirmation,
a goodbye) its last transition is always and leads on, so any reply moves the call. Every value in
enum_values either has a transition or is meant to keep the caller in the stage.

Keep explicit state for confirmation before writes, corrections, per-product attempts, retry limits
and duplicate prevention. Speak or move on after every tool result.

CLOSING. Where the contract has an operation that closes the call (close_call), it runs in its own
api_request stage, as its only tool, followed by an end stage; every end stage is then reached only
through a close stage and nothing after close can reach a bank tool. Work out the outcome and reason
from the source policy and the results before closing. If the source requires a goodbye before
close, speak it in the close stage's on_enter tts; the terminal can then use message_mode none.
Where the contract has no such operation, a call ends in an end stage that speaks the last sentence
the sources give for that ending, word for word, as its custom terminal message. If the source forbids notes on transfers, defer all notes until the call can
no longer end in a transfer.

Use separate stages for tool boundaries and computations. Prefer several small stages to one large
one: a stage that asks or decides one thing can be checked and repaired on its own.
"""

DESIGN = """Design a phone agent for the supplied bank policy and tool contract, as a WorkflowSpec.
Read the original documents in full; requirements, when supplied, is a checklist extracted from them
and the documents win where the two differ. The supplied Freya documentation is authoritative for
the platform. Write architecture first, then the complete workflow source.

Always return the complete workflow: an empty or withheld workflow is no agent at all, and the bank
is then answered by nobody. Bank material is written by several people over months and is never
complete. None of the following is a reason to hold the workflow back; build what the sources do
say and name the open point in architecture:
- An ending the sources describe as a hand-over (to a menu, to a person, to another step) with no
  service for it: whoever runs the line routes the call after it ends. The agent says the sentence
  the sources give for that ending and the call ends in an end stage.
- A check the sources want but no service answers (whether a right is used up, a limit reached):
  the agent offers what the sources let it offer and the service's own answer decides; where a
  service refuses or fails, the sources' sentence for that follows.
- Sources that disagree: the later document wins over the earlier one, a decision in a mail or a
  meeting over the document it corrects.
- A data file shown only in part: it is test data. Its first records show the shape of every
  record, and no design needs the rest.
- A rule below that names an operation this contract does not have: it does not apply.

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
