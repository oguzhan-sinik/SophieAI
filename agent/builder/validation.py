"""Conservative static Freya gate. This is not a proof of conversational policy."""
import ast
from copy import deepcopy
import re

from .schemas import Mutation, WorkflowSpec

TOP = {"initial_node", "system_prompt", "nodes", "global_nodes", "test_variables", "context_variables", "nodePositions"}
NODE = {"name", "node_type", "task_message", "role_message", "on_enter", "on_enter_first_entry_only", "transitions", "routing_prompt", "loop_condition", "loop_prompt", "extraction_schema", "tools", "pre_actions", "response_mapping", "passthrough", "passthrough_default_transition", "max_node_turns", "max_turn_transition", "terminal", "disable_inactivity_monitor", "suppress_tool_results", "truncation_strategy", "truncation_window_size", "reasoning_override", "condition", "description", "excluded_nodes", "is_tool_call"}
OPERATORS = {"equals", "not_equals", "greater_than", "less_than", "contains", "is_set", "is_not_set", "always", "matches_intent"}
MODULES = {"json", "re", "datetime"}
BLOCKED_NAMES = {"open", "exec", "eval", "compile", "getattr", "setattr", "delattr", "globals", "locals", "input", "breakpoint", "__import__", "help", "memoryview"}


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


def _entails(condition, variables, values):
    if "logic" in condition:
        checks = [_entails(c, variables, values) for c in condition.get("conditions", [])]
        return bool(checks) and (all(checks) if condition["logic"] == "or" else any(checks))
    return condition.get("operator") == "equals" and condition.get("variable") in variables and str(condition.get("operand")) in values


def validate(spec, contracts, requirements):
    errors = []
    try:
        parsed = WorkflowSpec.model_validate(spec)
    except Exception as exc:
        return {"valid": False, "errors": ["Invalid WorkflowSpec: " + str(exc)], "evidence_type": "static"}
    workflow = parsed.workflow
    if any(x is None for x in _walk(workflow)):
        errors.append("Workflow cannot contain null")
    if set(workflow) - TOP:
        errors.append("Unknown/unsupported top-level keys: " + str(sorted(set(workflow) - TOP)))
    normal, global_nodes = workflow.get("nodes", {}), workflow.get("global_nodes", {})
    if not isinstance(normal, dict) or not isinstance(global_nodes, dict):
        return {"valid": False, "errors": ["Nodes must be maps"], "evidence_type": "static"}
    nodes = {**normal, **global_nodes}
    for key, node in nodes.items():
        if not isinstance(node, dict):
            errors.append(f'{key}: node must be an object')
            continue
        for field in ('tools', 'pre_actions', 'transitions', 'response_mapping', 'extraction_schema'):
            if field in node and (not isinstance(node[field], list) or any(not isinstance(item, dict) for item in node[field])):
                errors.append(f'{key}: {field} must be an array of objects, never tool-name strings')
    if errors:
        return {'valid': False, 'errors': errors, 'evidence_type': 'static'}
    initial = workflow.get("initial_node")
    if initial not in normal:
        errors.append("initial_node does not resolve")
    if set(normal) & set(global_nodes):
        errors.append("Global and regular node names collide")
    edges = {key: [] for key in nodes}
    calls = {key: [] for key in nodes}
    mapped = {}
    for key, node in nodes.items():
        if not isinstance(node, dict):
            errors.append(f"{key}: node must be an object")
            continue
        def bad(message):
            errors.append(f"{key}: {message}")
        kind = node.get("node_type")
        if 'loop_prompt' in node:
            bad('Live Freya schema rejects loop_prompt; express repeat-turn behavior in task_message')
        if kind not in {"conversation", "api_request", "code", "end_call"}:
            bad("Unsupported node type")
        if set(node) - NODE:
            bad("Unknown node fields: " + str(sorted(set(node) - NODE)))
        if node.get("name") != key or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            bad("Node name must match snake_case key")
        if "tools" in node and kind != "conversation":
            bad("tools belongs only on conversation")
        if "pre_actions" in node and kind not in {"api_request", "code"}:
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
        if kind in {"code", "api_request"} and not node.get("pre_actions"):
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
                handler, name = function.get("handler"), function.get("name")
                props = function.get("parameters", {}).get("properties", {})
                if placement == "pre_actions" and "response_mapping" in tool:
                    bad("pre_actions mapping belongs at node level")
                mappings = tool.get("response_mapping", []) if placement == "tools" else node.get("response_mapping", [])
                for mapping in mappings:
                    if not mapping.get("path", "").startswith("data."):
                        bad("Mapping path must start data.")
                    mapped[mapping.get("variable")] = (name, mapping.get("path"))
                if handler == "__function__:code_exec":
                    if kind != "code":
                        bad("Code execution is supported only in code nodes")
                    errors.extend(f"{key}: {e}" for e in code_errors(props.get("code", {}).get("default", "")))
                elif handler == "__function__:api_call":
                    calls[key].append(name)
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
                    if placement == "pre_actions" and any("default" not in properties.get(field, {}) for field in expected.get("required", [])):
                        bad("Engine-run calls require baked defaults for every required argument")
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
                                bad(f"{field}: baked value violates contract")
                    if "call" not in function.get("description", "").lower():
                        bad("Tool description must state CALL trigger")
                else:
                    bad("Unsupported handler outside terminal")
                for hook in ("pre_process_code", "post_process_code"):
                    if tool.get(hook):
                        errors.extend(f"{key}/{hook}: {e}" for e in code_errors(tool[hook], True))
    # Include interrupts in path analysis; a global handler must not bypass a gate.
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
        errors.append("Unreachable nodes: " + str(sorted(set(nodes) - reachable)))
    rule_ids = {r["rule_id"] for r in requirements["requirements"]}
    active_ids = {r["rule_id"] for r in requirements["requirements"] if not r["precedence"]["superseded_by"]}
    if not active_ids <= set(parsed.coverage):
        errors.append("Missing active requirement coverage")
    for rule_id, coverage in parsed.coverage.items():
        if rule_id not in rule_ids or not coverage.nodes or not coverage.tests or not set(coverage.nodes) <= set(nodes):
            errors.append("Invalid coverage mapping: " + rule_id)
    # Stable operation names come from the event contract; all fields and values are source supplied.
    used = {name for names in calls.values() for name in names}
    for operation in used & {"get_account", "create_promise"}:
        if not any(g.operation == operation for g in parsed.tool_gates):
            errors.append(f"{operation}: missing source-backed deterministic tool gate")
    for gate in parsed.tool_gates:
        if gate.operation not in contracts["operations"] or not gate.rule_ids or not set(gate.rule_ids) <= rule_ids:
            errors.append("Unproven tool gate source")
            continue
        expected_var = gate.producer_operation + "_response." + gate.response_path
        producer_contract = contracts["operations"].get(gate.producer_operation, {})
        response_schema = producer_contract.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema", {})
        for field in gate.response_path.removeprefix("data.").split("."):
            response_schema = response_schema.get("properties", {}).get(field, {})
        if not response_schema or not gate.response_path.startswith("data."):
            errors.append("Gate response path does not exist in the supplied contract")
        if response_schema.get("type") == "boolean" and set(gate.allowed_values) != {"true", "True"}:
            errors.append("Boolean safety gate must require both true spellings")
        if gate.variable != expected_var and mapped.get(gate.variable) != (gate.producer_operation, gate.response_path):
            errors.append("Gate does not read its declared tool response")
        gate_variables = {gate.variable, expected_var}
        if expected_var in mapped and mapped[expected_var] != (gate.producer_operation, gate.response_path):
            errors.append("Canonical tool response cannot be mapped from another field")
        if gate_variables & set(workflow.get("test_variables", {})):
            errors.append("Tool gate cannot be initialized by test variables")
        if any(e.get("name") in gate_variables for n in nodes.values() for e in n.get("extraction_schema", [])):
            errors.append("Tool gate cannot be set by speech extraction")
        for node in nodes.values():
            for tool in node.get("tools", []) + node.get("pre_actions", []):
                function = tool.get("function", {})
                snippets = [tool.get("pre_process_code", ""), tool.get("post_process_code", "")]
                if function.get("handler") == "__function__:code_exec":
                    snippets.append(function.get("parameters", {}).get("properties", {}).get("code", {}).get("default", ""))
                for snippet in snippets:
                    try:
                        tree = ast.parse(snippet)
                    except (SyntaxError, TypeError):
                        continue
                    for item in ast.walk(tree):
                        if isinstance(item, ast.Subscript) and isinstance(item.ctx, ast.Store) and isinstance(item.slice, ast.Constant):
                            if item.slice.value in {gate.variable, expected_var}:
                                errors.append("Generated code cannot forge a tool gate variable")
                            if function.get("name") == gate.producer_operation and item.slice.value == gate.response_path.rsplit(".", 1)[-1]:
                                errors.append("Producer hook cannot overwrite its gate response field")
        stack = [(initial, False, False)] if initial in nodes else []
        seen = set()
        while stack:
            key, guarded, producer_seen = stack.pop()
            if (key, guarded, producer_seen) in seen:
                continue
            seen.add((key, guarded, producer_seen))
            if gate.operation in calls[key] and not guarded:
                errors.append(f"{key}: {gate.operation} reachable without verified gate")
            producer_seen = producer_seen or gate.producer_operation in calls[key]
            for target, condition in edges[key]:
                stack.append((target, guarded or (producer_seen and _entails(condition, gate_variables, gate.allowed_values)), producer_seen))
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
            # Only engine-run close guarantees a call; discretionary dialogue does not.
            closed = closed or ("close_call" in calls[key] and nodes[key].get("node_type") == "api_request")
            if key in ends and not closed:
                errors.append(f"{key}: terminal can bypass deterministic close_call")
            pending += [(target, closed) for target, _ in edges[key]]
    return {"valid": not errors, "errors": sorted(set(errors)), "evidence_type": "static", "reachable_nodes": len(reachable), "covered_rules": len(parsed.coverage), "policy_proven": False}


def apply_mutation(parent, mutation, parent_id):
    mutation = Mutation.model_validate(mutation)
    if mutation.parent_id != parent_id or not mutation.operations or not mutation.hypothesis:
        raise ValueError("Mutation needs correct parent, edits and rationale")
    child = deepcopy(parent)
    for edit in mutation.operations:
        if edit.op == "set_node":
            child["workflow"]["nodes"][edit.target] = deepcopy(edit.value)
        elif edit.op == "remove_node":
            del child["workflow"]["nodes"][edit.target]
        elif edit.op == "set_system_prompt":
            child["workflow"]["system_prompt"] = edit.value
        elif edit.op == "set_initial_node":
            child["workflow"]["initial_node"] = edit.value
        elif edit.op == "set_global_nodes":
            child["workflow"]["global_nodes"] = deepcopy(edit.value)
    child["coverage"] = {k: v.model_dump() for k, v in mutation.coverage.items()}
    if child["workflow"] == parent["workflow"]:
        raise ValueError("Mutation did not change workflow")
    return child
