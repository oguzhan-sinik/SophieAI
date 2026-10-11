"""Static checks on a compiled workflow, and the one way a workflow source is edited.

Errors block deployment and each names the stage to change. Warnings are hints: observations that
may or may not matter, passed to a fix as context and never acted on by the controller itself.
None of this proves how the agent speaks."""
import ast
from collections import deque
from copy import deepcopy
import re

from . import runtime
from .schemas import Fix

TOP = {"initial_node", "system_prompt", "nodes", "global_nodes", "test_variables", "context_variables", "nodePositions"}
NODE = {"name", "node_type", "task_message", "role_message", "on_enter", "on_enter_first_entry_only", "transitions", "routing_prompt", "loop_condition", "loop_prompt", "extraction_schema", "tools", "pre_actions", "response_mapping", "passthrough", "passthrough_default_transition", "max_node_turns", "max_turn_transition", "terminal", "disable_inactivity_monitor", "suppress_tool_results", "truncation_strategy", "truncation_window_size", "reasoning_override", "condition", "description", "excluded_nodes", "is_tool_call"}
OPERATORS = {"equals", "not_equals", "greater_than", "less_than", "contains", "is_set", "is_not_set", "always", "matches_intent"}
MODULES = {"json", "re", "datetime"}
BLOCKED_NAMES = {"open", "exec", "eval", "compile", "getattr", "setattr", "delattr", "globals", "locals", "input", "breakpoint", "__import__", "help", "memoryview"}
SILENT = ("code", "api_request")
# Stable operation names from the event contract; every field and value comes from the supplied API.
IDENTITY, PROTECTED = "verify_identity", ("get_account", "create_promise")
# Values and variable names that stand for a failed or unfinished check. A route that fires on one of
# them is the way out for a caller who was NOT verified, so it proves nothing.
NOT_VERIFIED = {"", "false", "no", "0", "none", "null", "failed", "fail", "unverified", "not_verified", "denied", "rejected",
                "error", "invalid", "wrong", "locked", "blocked", "mismatch", "unknown", "pending", "retry"}
NEGATIVE_NAME = re.compile(r"fail|wrong|denied|locked|error|reject|invalid|mismatch|unverified|not_verified")
# What the dialogue model is told and what is spoken as written. Descriptions and routing prompts are
# not wording: the routing model and the extractor decide by them, so changing one changes routes and values.
WORDING = {"task_message", "role_message", "system_prompt", "text", "spoken_message", "llm_prompt"}


# The review of a design before any customer is called. Each of these is a failure that is certain or
# has been seen live, that the stage's own `except` hides, and that a simulation would otherwise be the
# first to show: on a brief without practice customers nothing would show it at all.
MAX_EXTRACTED = 5     # designs that scored well extract at most 4 values in one stage; one that extracted 9 took 20-40 s a turn
MAX_CODE_LINES = 120  # their longest code stage has 86 lines; the 243-line one hid two mistakes behind one except
HELPERS = {f.name: f for f in ast.parse(runtime.DATE_HELPERS).body if isinstance(f, ast.FunctionDef) and f.name.startswith("ctl_")}


def _spoken_read(node):
    """The extraction variable a vars.get('x') or vars['x'] reads, through str()/round() wrappers."""
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("str", "round", "int", "float") and node.args:
        node = node.args[0]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and isinstance(node.func.value, ast.Name) \
            and node.func.value.id == "vars" and len(node.args) == 1 and isinstance(node.args[0], ast.Constant):
        return node.args[0].value
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "vars" and isinstance(node.slice, ast.Constant):
        return node.slice.value
    return None


SHAPING = {"strip", "lstrip", "rstrip", "lower", "upper", "casefold", "replace", "title"}


def _words_read(node, words, held):
    """The free-words variable an expression is: vars.get('x') under str(), .strip(), .lower() and `or ''`, or a
    local name that was assigned exactly that."""
    while True:
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            node = node.values[0]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str" and node.args:
            node = node.args[0]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in SHAPING:
            node = node.func.value
        else:
            break
    if isinstance(node, ast.Name):
        return held.get(node.id)
    variable = _spoken_read(node)
    return variable if variable in words else None


def _phrases(node):
    """The fixed phrases an expression is: a text, or a list of texts."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value] if node.value.strip() else []
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value.strip()]
    return []


def review_code(compiled, spoken=(), words=()):
    """What is certain to go wrong in a code stage or hook, read from the code itself.

    `compiled` is the code as deployed: the model's own part is reviewed, and the controller helpers
    count as available only if they were compiled into this very snippet."""
    try:
        own, whole = ast.parse(runtime.strip(compiled)), ast.parse(compiled)
    except (SyntaxError, TypeError, ValueError):
        return []   # code_errors names what is wrong with code that does not parse
    found = []
    present = {f.name for f in ast.walk(whole) if isinstance(f, ast.FunctionDef)}
    parents = {id(child): parent for parent in ast.walk(own) for child in ast.iter_child_nodes(parent)}
    held = {}
    for node in ast.walk(own):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and _words_read(node.value, words, {}):
            held[node.targets[0].id] = _words_read(node.value, words, {})
    for node in ast.walk(own):
        if isinstance(node, ast.Compare) and words:
            sides = [node.left] + list(node.comparators)
            for op, left, right in zip(node.ops, sides, sides[1:]):
                for said, fixed in ((left, right), (right, left)):
                    variable, phrases = _words_read(said, words, held), _phrases(fixed)
                    whole = isinstance(op, (ast.Eq, ast.NotEq)) or (isinstance(op, (ast.In, ast.NotIn)) and (said is left) == isinstance(fixed, (ast.List, ast.Tuple, ast.Set)))
                    if variable and phrases and whole:
                        found.append(f"{variable} holds the caller's own words and is compared with fixed text ({', '.join(repr(p) for p in phrases[:3])}). Callers say it their "
                                     f"own way ('the credit card', 'all three', 'both of them') and the comparison then fails. If {variable} is one of a list, give it "
                                     f"enum_values and route on them; if it names one of several things, pass the words to ctl_choice(said, names) and use its result")
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id in HELPERS \
                and any(isinstance(target, (ast.Tuple, ast.List)) for target in node.targets):
            names = max(len(target.elts) for target in node.targets if isinstance(target, (ast.Tuple, ast.List)))
            found.append(f"{node.value.func.id} returns one value; it cannot be unpacked into {names} names. Assign it to one name")
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        if name.startswith("ctl_"):
            if name not in HELPERS or name not in present:
                found.append(f"{name} is not defined" + (" here" if name in HELPERS else "; the controller provides " + ", ".join(sorted(n for n in HELPERS if "_tr" not in n))))
                continue
            arguments = HELPERS[name].args
            takes = [a.arg for a in arguments.args]
            given = takes[:len(node.args)] + [k.arg for k in node.keywords if k.arg]
            required = takes[:len(takes) - len(arguments.defaults)]
            if len(node.args) > len(takes) or set(given) - set(takes) or len(given) != len(set(given)) or set(required) - set(given):
                found.append(f"{name} called with {len(node.args) + len(node.keywords)} arguments; it takes ({', '.join(takes)})")
        elif name in ("int", "float") and node.args and _spoken_read(node.args[0]) in spoken:
            # Guarded when an enclosing test names the same variable: `if vars.get('x'): int(vars.get('x'))`.
            variable, current, guarded = _spoken_read(node.args[0]), node, False
            while id(current) in parents and not guarded:
                current = parents[id(current)]
                guarded = isinstance(current, (ast.If, ast.IfExp, ast.While)) and any(isinstance(n, ast.Constant) and n.value == variable for n in ast.walk(current.test))
            if not guarded:
                found.append(f"{name}() is applied to {variable}, which the caller's words fill and which is unset whenever they give no such value (an amount named as "
                             f"'the full amount' has no number). The conversion then fails and this stage's except closes the call. Test {variable} first and decide what "
                             f"a missing value means here: the value this stage offered, or a question back")
    return sorted(set(found))


def code_errors(source, hook=False):
    errors = []
    if not isinstance(source, str) or not source.strip():
        return ["Empty code"]
    if "{{" in source or "}}" in source:
        errors.append("Code contains template delimiters")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"Invalid Python: {exc.msg}"]
    if not any(isinstance(n, ast.Try) for n in ast.walk(tree)):
        errors.append("Code requires exception handling and fallback state")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(n not in MODULES for n in names) or getattr(node, "level", 0):
                errors.append("Code imports an unsupported module")
        if isinstance(node, ast.Name) and (node.id in BLOCKED_NAMES or node.id.startswith("__")):
            errors.append("Code uses a forbidden capability")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in BLOCKED_NAMES | {"now", "today", "utcnow", "os", "sys", "io", "codecs", "socket", "subprocess", "importlib", "builtins"}):
            errors.append("Code uses private attributes or wall clock instead of call now")
        if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.With, ast.AsyncWith)):
            errors.append("Unsupported executable construct")
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "config":
            if not isinstance(node.slice, ast.Constant) or node.slice.value != "body":
                errors.append("Hooks may only access config.body; endpoints are contract-owned")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "config":
            if node.func.attr != "get" or not node.args or not isinstance(node.args[0], ast.Constant) or node.args[0].value != "body":
                errors.append("Hooks cannot rewrite endpoint configuration")
    parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "config":
            parent = parents.get(id(node))
            if not isinstance(parent, (ast.Subscript, ast.Attribute)):
                errors.append("Hooks cannot alias or replace request config")
    return sorted(set(errors))


def _walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _condition(condition, nested=False):
    if not isinstance(condition, dict):
        return ["Condition must be an object"]
    if "logic" in condition:
        if condition["logic"] not in ({"and", "or"} if nested else {"or"}) or not condition.get("conditions"):
            return ["Grouped conditions require top-level OR and nonempty conditions"]
        return [e for c in condition["conditions"] for e in _condition(c, True)]
    op = condition.get("operator")
    if op not in OPERATORS:
        return ["Unknown routing operator"]
    if op not in {"always", "matches_intent"} and not condition.get("variable"):
        return ["Variable condition has no variable"]
    if op == "matches_intent" and not condition.get("description"):
        return ["Intent condition has no description"]
    if op in {"equals", "not_equals", "contains", "greater_than", "less_than"} and "operand" not in condition:
        return ["Condition is missing operand"]
    if isinstance(condition.get("operand"), bool):
        return ["Boolean routing operands must be explicit strings"]
    return []


def _leaves(condition):
    """Every single test inside a route condition, however it is grouped."""
    if isinstance(condition, dict):
        if condition.get("conditions"):
            for child in condition["conditions"]:
                yield from _leaves(child)
        elif condition.get("operator"):
            yield condition


def _is_proof(condition, spoken, owned=None):
    """A route that can only fire on something the caller cannot simply say: a tool result or a value code derived.

    Every alternative of an OR has to be such a test, since one spoken alternative is a way round
    the others; within an AND one is enough. With `owned`, the test must be on a variable only the
    identity tool's own result fills: that is proof wherever in the call the route stands."""
    if not isinstance(condition, dict):
        return False
    if condition.get("conditions"):
        checks = [_is_proof(child, spoken, owned) for child in condition["conditions"]]
        return all(checks) if condition.get("logic") == "or" else any(checks)
    # Proof is `equals` against a value that means verified, on a variable the caller cannot fill by
    # speaking. Which word a design uses for "verified" is its own choice (true, yes, verified,
    # all_verified, ...); what is ruled out is what can never mean it: a failed value, a variable that
    # names the failure, that a variable merely is set, and the transport's status code or counters.
    variable = str(condition.get("variable") or "")
    if owned is not None and not owned(variable):
        return False
    return (bool(variable) and variable not in spoken and
            not variable.endswith(("_turns", "_status_code", "_success_count", "_failure_count")) and
            not NEGATIVE_NAME.search(variable.lower()) and
            condition.get("operator") == "equals" and str(condition.get("operand")).strip().lower() not in NOT_VERIFIED)


def _variable_use(node):
    """Variables a stage's code writes, and every other name its code mentions (reads)."""
    written, read = set(), set()
    for tool in node.get("pre_actions", []):
        function = tool.get("function", {})
        sources = [tool.get("pre_process_code"), tool.get("post_process_code")]
        if isinstance(function, dict) and function.get("handler") == "__function__:code_exec":
            sources.append(function.get("parameters", {}).get("properties", {}).get("code", {}).get("default"))
        for source in sources:
            try:
                tree = ast.parse(runtime.strip(source))
            except (SyntaxError, TypeError, ValueError):
                continue
            targets = {id(item.slice) for item in ast.walk(tree) if isinstance(item, ast.Subscript) and isinstance(item.ctx, ast.Store) and isinstance(item.slice, ast.Constant)}
            for item in ast.walk(tree):
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    (written if id(item) in targets else read).add(item.value)
    return written, read


def validate(workflow, contracts):
    errors, warnings = [], []
    result = lambda: {"valid": not errors, "errors": sorted(set(errors)), "warnings": sorted(set(warnings)), "evidence_type": "static"}
    if not isinstance(workflow, dict):
        errors.append("workflow must be an object")
        return result()
    if any(x is None for x in _walk(workflow)):
        errors.append("Workflow cannot contain null")
    if set(workflow) - TOP:
        errors.append("Unknown/unsupported top-level keys: " + str(sorted(set(workflow) - TOP)))
    normal, global_nodes = workflow.get("nodes", {}), workflow.get("global_nodes", {})
    if not isinstance(normal, dict) or not isinstance(global_nodes, dict):
        errors.append("Nodes must be maps")
        return result()
    nodes = {**normal, **global_nodes}
    for key, node in nodes.items():
        if not isinstance(node, dict):
            errors.append(f"{key}: node must be an object")
            continue
        for field in ("tools", "pre_actions", "transitions", "response_mapping", "extraction_schema"):
            if field in node and (not isinstance(node[field], list) or any(not isinstance(item, dict) for item in node[field])):
                errors.append(f"{key}: {field} must be an array of objects, never tool-name strings")
    if errors:
        return result()
    initial = workflow.get("initial_node")
    if initial not in normal:
        errors.append("initial_node does not resolve")
    if set(normal) & set(global_nodes):
        errors.append("Global and regular node names collide")
    edges = {key: [] for key in nodes}
    calls = {key: [] for key in nodes}
    spoken = {item.get("name") for node in nodes.values() for item in node.get("extraction_schema", [])}
    # Variables that hold the caller's own words: text with no list of values, and not a day or an amount the controller converts.
    listed = {item.get("name") for node in nodes.values() for item in node.get("extraction_schema", [])
              if item.get("enum_values") or item.get("type") not in (None, "string") or runtime.SAID in str(item.get("description")) or runtime.SAID_AMOUNT in str(item.get("description"))}
    words = spoken - listed
    for key, node in nodes.items():
        def bad(message):
            errors.append(f"{key}: {message}")
        kind = node.get("node_type")
        if kind == "conversation" and len(node.get("extraction_schema", [])) > MAX_EXTRACTED:
            # A hint, not an error. Made an error once, it forced an untested rewrite of a 7-of-10 design
            # that lost customers the design had passed; the rules ask for this shape in the first design.
            warnings.append(f"{key}: this stage extracts {len(node['extraction_schema'])} values from one reply ({', '.join(str(i.get('name')) for i in node['extraction_schema'])}). Every one is a "
                f"model call on every turn, so the caller waits, and overlapping values are misread. Extract at most {MAX_EXTRACTED}: what this stage's own routes test and "
                f"what the next code stage needs from this reply. Give a second question its own stage, and let code derive what follows from the values already extracted")
        if "loop_prompt" in node:
            bad("Live Freya schema rejects loop_prompt; express repeat-turn behavior in task_message")
        if kind not in {"conversation", "api_request", "code", "end_call"}:
            bad("Unsupported node type")
        if set(node) - NODE:
            bad("Unknown node fields: " + str(sorted(set(node) - NODE)))
        if node.get("name") != key or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            bad("Node name must match snake_case key")
        if "tools" in node and kind != "conversation":
            bad("tools belongs only on conversation")
        if "pre_actions" in node and kind not in SILENT:
            bad("pre_actions belongs only on action/code")
        if kind == "conversation" and "response_mapping" in node:
            bad("Conversation response_mapping belongs on its tool")
        transitions = node.get("transitions", [])
        for transition in transitions:
            target = transition.get("target_node")
            if target not in nodes:
                bad("Transition target does not resolve: " + str(target))
            else:
                edges[key].append((target, transition.get("condition", {})))
            errors.extend(f"{key}: {e}" for e in _condition(transition.get("condition")))
        if kind == "conversation":
            # A value the extractor may return but no route tests leaves the call in the stage with
            # nothing to do; the dialogue model then improvises until the customer hangs up.
            equal, unequal = {}, {}
            for transition in transitions:
                for leaf in _leaves(transition.get("condition")):
                    if leaf["operator"] in ("equals", "not_equals") and leaf.get("variable"):
                        (equal if leaf["operator"] == "equals" else unequal).setdefault(leaf["variable"], set()).add(str(leaf.get("operand")))
            fallthrough = next((t.get("target_node") for t in transitions if isinstance(t.get("condition"), dict) and t["condition"].get("operator") == "always"), key)
            # Only a stage that keeps the call when nothing matches can trap it.
            for extraction in node.get("extraction_schema", []) if fallthrough == key else []:
                name, values = extraction.get("name"), extraction.get("enum_values")
                if not isinstance(values, list) or name not in equal:
                    continue
                unrouted = [str(v) for v in values if str(v) not in equal[name] and not unequal.get(name, set()) - {str(v)}]
                if unrouted:
                    warnings.append(f"{key}: {name} can be extracted as {unrouted} but no transition of this stage tests those values, so the call stays here. "
                                    "If one of them should move the call on, give it a transition")
        for field in ("max_turn_transition", "passthrough_default_transition"):
            if field in node:
                if node[field] not in nodes:
                    bad(f"{field} target does not resolve")
                else:
                    edges[key].append((node[field], {"operator": "always"}))
        if "max_node_turns" in node and "max_turn_transition" not in node:
            bad("Turn cap has no fallback target")
        if node.get("passthrough"):
            if not node.get("passthrough_default_transition") or not transitions or transitions[-1].get("condition", {}).get("operator") != "always":
                bad("Passthrough requires default and last always transition")
        if kind in SILENT and not node.get("pre_actions"):
            bad("Action node has no pre_actions")
        for extraction in node.get("extraction_schema", []):
            if not 0 <= extraction.get("min_confidence", -1) <= 1:
                bad("Extraction requires explicit min_confidence")
            prompt = extraction.get("extraction_prompt")
            if prompt and any("{{" + p + "}}" not in prompt for p in ("extractor.speech", "extractor.conversation.last-10", "extractor.type_preamble", "extractor.variables_list")):
                bad("Extraction template is missing required placeholders")
        for mapping in node.get("response_mapping", []):
            if not mapping.get("path", "").startswith("data."):
                bad("Mapping path must start data.")
        if kind == "end_call":
            terminal = node.get("terminal", {}).get("function", {})
            if terminal.get("handler") != "__function__:end_call" or transitions:
                bad("End node requires end_call terminal and no transitions")
            props = terminal.get("parameters", {}).get("properties", {})
            mode = props.get("message_mode", {}).get("default")
            if mode not in {"custom", "none", "llm"}:
                bad("Invalid terminal message mode")
            if mode == "custom" and not props.get("spoken_message", {}).get("default"):
                bad("Custom terminal requires spoken_message")
        for placement in ("tools", "pre_actions"):
            for tool in node.get(placement, []):
                function = tool.get("function", {})
                if not isinstance(function, dict):
                    bad(f"{placement}: tool function must be an object")
                    continue
                handler, name = function.get("handler"), function.get("name")
                props = function.get("parameters", {}).get("properties", {})
                if placement == "pre_actions" and "response_mapping" in tool:
                    bad("pre_actions mapping belongs at node level")
                for mapping in tool.get("response_mapping", []) if placement == "tools" else []:
                    if not mapping.get("path", "").startswith("data."):
                        bad("Mapping path must start data.")
                if handler == "__function__:code_exec":
                    if kind != "code":
                        bad("Code execution is supported only in code nodes")
                    errors.extend(f"{key}: {e}" for e in code_errors(props.get("code", {}).get("default", "")))
                    errors.extend(f"{key}: {e}" for e in review_code(props.get("code", {}).get("default", ""), spoken, words))
                    lines = len(runtime.strip(props.get("code", {}).get("default", "")).splitlines())
                    if lines > MAX_CODE_LINES:
                        warnings.append(f"{key}: this code stage has {lines} lines and decides several things behind one except, so one mistake closes the call for every case it handles. "
                            f"Split it at its decisions into code stages of at most {MAX_CODE_LINES} lines, each setting one status that its own routes test")
                elif handler == "__function__:api_call":
                    calls[key].append(name)
                    if placement == "tools":
                        # Seen live: a model-called tool sent a spoken date as it was said, resent a stale
                        # answer, was called twice, or not at all. An engine-run call does none of that.
                        bad(f"{name} is offered to the dialogue model in a conversation stage. Bank tools run in their own api_request stage: let this stage "
                            f"extract the values and route to an api_request stage that calls {name} with every argument bound to a variable, and route on its result from there")
                    contract = contracts["operations"].get(name)
                    if not contract:
                        bad("Unsupported bank tool: " + str(name))
                        continue
                    if props.get("url", {}).get("default") != contract["url"] or props.get("method", {}).get("default") != contract["method"]:
                        bad("URL/method must be baked from supplied OpenAPI")
                    if tool.get("config", {}).get("maxRetries") != 0 or props.get("connect_retries", {}).get("default") != 0:
                        bad("Bank tools require explicit zero transport/tool retries")
                    body = props.get("body", {})
                    expected = contract["body"]
                    properties = body.get("properties", {})
                    if "default" in body or set(properties) != set(expected.get("properties", {})):
                        bad("Body fields must match contract leaf schemas")
                    if set(body.get("required", [])) != set(expected.get("required", [])):
                        bad("Required body fields differ from contract")
                    missing = [field for field in expected.get("required", []) if "default" not in properties.get(field, {})]
                    if placement == "pre_actions" and missing:
                        bad(f"{name} is run by the engine here, so every required argument needs a binding; missing {missing}")
                    for field, schema in expected.get("properties", {}).items():
                        actual = properties.get(field, {})
                        for attribute in ("type", "enum", "format", "items", "properties", "nullable", "minimum", "maximum"):
                            if schema.get(attribute) != actual.get(attribute):
                                bad(f"{field}: altered contract {attribute}")
                        if "const" in actual:
                            bad("Use default, never const, for baked values")
                        if field == "customer_id" and actual.get("default") != "{{customer_id}}":
                            bad("customer_id must be baked from call variable")
                        if field == "product_id" and "default" in actual and not re.fullmatch(r"\{\{[A-Za-z_][\w.]*\}\}", str(actual["default"])):
                            bad("product_id must come from live account data, never a literal")
                        default = actual.get("default")
                        if default is not None and not (isinstance(default, str) and "{{" in default):
                            from jsonschema import Draft202012Validator
                            if list(Draft202012Validator(schema).iter_errors(default)):
                                bad(f"{field}: bound value {default!r} is not allowed by the contract" + (f", which accepts {schema['enum']}" if schema.get("enum") else ""))
                    if "call" not in function.get("description", "").lower():
                        bad(f"The description of {name} must state its trigger, starting 'CALL when ...'")
                else:
                    bad("Unsupported handler outside terminal")
                for hook in ("pre_process_code", "post_process_code"):
                    if tool.get(hook):
                        errors.extend(f"{key}/{hook}: {e}" for e in code_errors(tool[hook], True))
                        errors.extend(f"{key}/{hook}: {e}" for e in review_code(tool[hook], spoken, words))
    # Interrupts are routes too; a global handler must not slip past a check.
    for key in normal:
        for target, node in global_nodes.items():
            if key not in node.get("excluded_nodes", []):
                edges[key].append((target, node.get("condition", {})))
    reachable = set()
    queue = [initial] if initial in nodes else []
    while queue:
        key = queue.pop()
        if key in reachable:
            continue
        reachable.add(key)
        queue += [target for target, _ in edges[key]]
    ends = {key for key, n in nodes.items() if n.get("node_type") == "end_call"}
    terminating = set(ends)
    while True:
        more = {key for key in nodes if any(target in terminating for target, _ in edges[key])}
        if more <= terminating:
            break
        terminating |= more
    if reachable - terminating:
        errors.append("Reachable nodes cannot reach end_call: " + str(sorted(reachable - terminating)))
    if set(nodes) - reachable:
        errors.append("Unreachable nodes: " + str(sorted(set(nodes) - reachable)) + "; give each a transition from the stage that should lead to it, or remove it")
    # Identity before account data, read from the routes themselves. Every route to a protected tool
    # must call the identity tool and afterwards branch on something the caller cannot simply say.
    # What only the identity tool fills: the variables its stages map from the response, unless code elsewhere writes them too.
    identity_stages = [key for key, names in calls.items() if IDENTITY in names]
    elsewhere = set().union(*(_variable_use(node)[0] for key, node in nodes.items() if key not in identity_stages)) if nodes else set()
    # Only what every identity stage maps: the result of one question alone is not the result of the check.
    per_stage = [{m.get("variable") for m in nodes[key].get("response_mapping", [])} for key in identity_stages]
    mapped = (set.intersection(*per_stage) if per_stage else set()) - elsewhere - spoken
    owned = lambda variable: variable in mapped or any(variable.startswith(stage + "_response.data.") for stage in identity_stages)
    for operation in [op for op in PROTECTED if IDENTITY in contracts["operations"] and any(op in names for names in calls.values())]:
        pending, seen = deque([(initial, None, False, [])] if initial in nodes else []), set()
        while pending:
            key, checked_at, tested, path = pending.popleft()
            if (key, checked_at is not None, tested) in seen:
                continue
            seen.add((key, checked_at is not None, tested))
            path = path + [key]
            if operation in calls[key] and not tested:
                # A long route is shown by both ends: where it leaves the start of the call says how it got round identity.
                route = " > ".join(path if len(path) <= 12 else path[:5] + ["..."] + path[-6:])
                errors.append(f"{key}: {operation} can be reached without a tested identity check, by the route {route}. " + (
                    f"No stage on that route calls {IDENTITY}. A stage a caller can reach before identity (a help, resume or turn-cap stage) leads "
                    f"into the stages that follow it: make that transition test, with equals, the result the identity stages map from the tool's response "
                    f"that means every check passed (not a status code wrote), in an AND with whatever else it tests, "
                    f"or send it back through the identity stages. Changing {key} or the stage just before it does not close this route." if checked_at is None else
                    f"After {IDENTITY} in {checked_at} no transition on that route proves its result. Make the way out of {checked_at} (or of the code stage "
                    f"that reads its response) test, with equals, the value that means verified: a mapped response variable (all_verified equals true) or a status "
                    f"a code stage derives from the response (equals verified). is_set, an HTTP status code, a success or failure counter, a turn count, a value "
                    f"that means failed, or anything the caller said does not prove it."))
                break
            if IDENTITY in calls[key]:
                checked_at, tested = key, False
            for target, condition in edges[key]:
                pending.append((target, checked_at, tested or (checked_at is not None and _is_proof(condition, spoken)) or _is_proof(condition, spoken, owned), path))
    # close_call must be isolated from other bank actions and cannot lead back to one.
    for key, names in calls.items():
        if "close_call" not in names:
            continue
        if names != ["close_call"]:
            errors.append(f"{key}: close_call must be the only tool at its stage")
        pending, seen = [target for target, _ in edges[key]], set()
        while pending:
            target = pending.pop()
            if target in seen:
                continue
            seen.add(target)
            if calls[target]:
                errors.append(f"{key}: bank tool reachable after close_call")
            pending += [n for n, _ in edges[target]]
    if "close_call" in contracts["operations"]:
        pending = [(initial, False)] if initial in nodes else []
        seen = set()
        while pending:
            key, closed = pending.pop()
            if (key, closed) in seen:
                continue
            seen.add((key, closed))
            # Only an engine-run close guarantees the call; a tool the dialogue model may skip does not.
            closed = closed or ("close_call" in calls[key] and nodes[key].get("node_type") == "api_request")
            if key in ends and not closed:
                errors.append(f"{key}: this end stage can be reached without close_call; route to it only from an api_request stage that runs close_call")
            pending += [(target, closed) for target, _ in edges[key]]
    # A stage that offers a value some check computed, and whose route runs straight back into that
    # check, only makes progress if the check reads the offer.
    statuses = {leaf["variable"] for node in nodes.values() for transition in node.get("transitions", []) for leaf in _leaves(transition.get("condition")) if leaf.get("variable")}
    for key, node in normal.items():
        shown = set(re.findall(r"\{\{\s*([A-Za-z_]\w*)\s*\}\}", str(node.get("task_message", "")))) - statuses
        if node.get("node_type") != "conversation" or not shown:
            continue
        for transition in node.get("transitions", []):
            first = transition.get("target_node")
            if first == key or nodes.get(first, {}).get("node_type") not in SILENT:
                continue
            chain, pending, returns = set(), [first], False
            while pending:
                current = pending.pop()
                if current in chain:
                    continue
                chain.add(current)
                for target, _ in edges[current]:
                    if target == key:
                        returns = True
                    elif nodes[target].get("node_type") in SILENT:
                        pending.append(target)
            if not returns:
                continue
            written, read = set(), set()
            for member in chain:
                w, r = _variable_use(nodes[member])
                written |= w
                read |= r
            offered = shown & written
            if offered and not offered & read:
                warnings.append(f"{key}: offers {sorted(offered)}, computed by {sorted(chain)}, and its route to {first} runs straight back into that check, which never reads "
                                f"{sorted(offered)}. If that route is taken when the customer accepts the offer, nothing is applied and the call loops; "
                                "acceptance then needs its own route through a code stage that copies the offered value into the variable the check reads")
    return result()


def _wording_free(value, names=False):
    """The value without its wording. `names`: the keys of this object are stage or field names, never wording keys."""
    if isinstance(value, dict):
        return {k: _wording_free(v, k in ("nodes", "global_nodes", "bindings")) for k, v in value.items() if names or k not in WORDING}
    if isinstance(value, list):
        return [_wording_free(v) for v in value]
    return value


def is_wording(before, after):
    """True when two sources differ only in what the dialogue model is told or says: no route, extraction, value, code or stage changed."""
    return before != after and _wording_free(before.get("workflow")) == _wording_free(after.get("workflow"))


def edited_stages(fix):
    """The stages a fix touches; None when it can affect every call (a workflow-level edit or a removed stage)."""
    edits = fix["edits"]
    return None if any(e["op"] in ("set_workflow_field", "remove_stage") for e in edits) else {e["stage"] for e in edits}


def apply_fix(source, fix):
    """Apply one fix to a workflow source. Everything the fix does not name is kept as it is."""
    fix = Fix.model_validate(fix)
    result = deepcopy(source)
    workflow = result.get("workflow")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), dict):
        raise ValueError("the workflow has no nodes object to edit")
    nodes = workflow["nodes"]
    for edit in fix.edits:
        label = f"{edit.op} {edit.stage}{'.' + edit.field if edit.field else ''}"
        if edit.op == "set_workflow_field":
            if edit.field not in ("system_prompt", "initial_node") or not isinstance(edit.value, str):
                raise ValueError(f"{label}: only system_prompt and initial_node can be set, to a text value")
            workflow[edit.field] = edit.value
        elif edit.op == "remove_stage":
            if edit.stage not in nodes:
                raise ValueError(f"{label}: no such stage")
            del nodes[edit.stage]
        elif edit.op == "set_stage":
            if not edit.stage or not isinstance(edit.value, dict):
                raise ValueError(f"{label}: value must be the complete stage object")
            nodes[edit.stage] = {**deepcopy(edit.value), "name": edit.stage}
        else:
            if not isinstance(nodes.get(edit.stage), dict):
                raise ValueError(f"{label}: no such stage; add a new stage with set_stage")
            if not edit.field or edit.field == "name":
                raise ValueError(f"{label}: name the field to replace")
            if edit.value is None:
                nodes[edit.stage].pop(edit.field, None)
            else:
                nodes[edit.stage][edit.field] = deepcopy(edit.value)
            if edit.field == "code":
                nodes[edit.stage].pop("pre_actions", None)
    if result == source:
        raise ValueError("it changes nothing")
    return result
