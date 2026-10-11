"""Bounded execution of compiled workflow JSON against an isolated local bank."""
from copy import deepcopy
import json
import re
from typing import Any

from pydantic import Field

from .actors import Actor
from .bank import Bank, check_schema, read_path
from .models import Record
from .sandbox import DockerCode, Unsupported

CAPABILITIES = {
    "version": "local-proxy-1", "nodes": ["conversation", "api_request", "code", "end_call"],
    "features": ["ordered deterministic/intent routes", "global routes", "pre-actions", "API mappings",
                 "Docker Python/hook execution", "fixed/LLM entry", "turn limits", "tool-call transitions"],
    "unsupported": ["audio", "lifecycle tools", "custom extraction_prompt", "history summarisation", "context_variables", "silent conversation waits", "previous-node routing", "suppressed tool results", "automatic tool retries"],
    "limitations": ["BUILDER_MODEL replaces Freya model", "extraction certainty is not Freya token confidence",
                    "structured mappings use JSON strings", "not certified platform equivalence"],
}


class Extracted(Record):
    values: dict[str, Any]
    uncertain: list[str]


class IntentMatches(Record):
    matches: dict[str, bool]


class ToolCall(Record):
    name: str
    arguments: dict[str, Any]


class Dialogue(Record):
    message: str = Field(max_length=4000)
    tool_calls: list[ToolCall] = Field(max_length=4)
    transition: str | None


def substitute(value, variables):
    if isinstance(value, dict): return {k: substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list): return [substitute(v, variables) for v in value]
    if not isinstance(value, str): return value
    exact = re.fullmatch(r"\{\{([^{}]+)\}\}", value)
    if exact:
        key = exact[1].strip()
        if key not in variables: raise Unsupported("Unset template variable: " + key)
        return variables[key]
    def replace(match):
        key = match[1].strip()
        if key not in variables: raise Unsupported("Unset template variable: " + key)
        return str(variables[key])
    return re.sub(r"\{\{([^{}]+)\}\}", replace, value)


def parameters(schema, supplied, variables):
    if "default" in schema:
        value = substitute(schema["default"], variables)
        if isinstance(value, str) and schema.get("type") in {"array", "object"}:
            value = json.loads(value)
        return value
    if schema.get("type") == "object":
        supplied = supplied or {}
        if not isinstance(supplied, dict): raise Unsupported("Tool arguments are not an object")
        fields = schema.get("properties", {})
        if set(supplied) - set(fields): raise Unsupported("Tool arguments have unknown fields")
        return {key: parameters(prop, supplied.get(key), variables) for key, prop in fields.items()
                if key in supplied or "default" in prop or key in schema.get("required", []) or prop.get("type") == "object"}
    if supplied is None: raise Unsupported("Tool requires an unresolved model argument")
    return supplied


def scalar(value):
    if isinstance(value, bool): return "true" if value else "false"
    if isinstance(value, (list, dict)): return json.dumps(value)
    return value


def flatten(value, prefix, variables):
    if isinstance(value, dict):
        for key, item in value.items(): flatten(item, prefix + "." + key, variables)
    elif isinstance(value, list):
        for key, item in enumerate(value): flatten(item, prefix + "." + str(key), variables)
    else: variables[prefix] = scalar(value)


def merged_routes(routes):
    result, by_target = [], {}
    for route in routes:
        if route.get("is_tool_call"):
            continue
        target = route.get("target_node")
        if target in by_target:
            previous = by_target[target]
            previous["condition"] = {"logic": "or", "conditions": [previous["condition"], route["condition"]]}
        else:
            current = deepcopy(route)
            by_target[target] = current
            result.append(current)
    return result


def has_intent(condition):
    return condition.get("operator") == "matches_intent" or any(has_intent(c) for c in condition.get("conditions", []))


def condition_matches(condition, variables, semantic):
    if condition.get("conditions"):
        values = [condition_matches(c, variables, semantic) for c in condition["conditions"]]
        return all(values) if condition.get("logic") == "and" else any(values)
    op, variable = condition.get("operator"), condition.get("variable")
    value, operand = variables.get(variable), condition.get("operand")
    if op == "always": return True
    if op == "matches_intent": return semantic.get(condition.get("description", ""), False)
    if op == "is_set": return value is not None and value != ""
    if op == "is_not_set": return value is None or value == ""
    if op == "equals": return value is not None and str(value) == str(operand)
    if op == "not_equals": return value is not None and str(value) != str(operand)
    if op == "contains": return str(operand).lower() in str(value or "").lower()
    if op in {"greater_than", "less_than"}:
        try: return float(value) > float(operand) if op == "greater_than" else float(value) < float(operand)
        except (ValueError, TypeError): return False
    raise Unsupported("Unsupported route operator: " + str(op))


def capability_errors(workflow):
    errors = []
    if workflow.get("tools") or workflow.get("context_variables"): errors.append("Lifecycle tools/context variables")
    nodes = {**workflow.get("nodes", {}), **workflow.get("global_nodes", {})}
    if workflow.get("initial_node") not in workflow.get("nodes", {}): errors.append("Missing initial node")
    for key, node in nodes.items():
        if node.get("node_type") not in CAPABILITIES["nodes"]: errors.append(key + ": unsupported node type")
        if node.get("on_enter", {}).get("type") not in {None, "tts", "llm", "silent"}: errors.append(key + ": unsupported entry mode (including audio)")
        if node.get("node_type") == "conversation" and node.get("on_enter", {}).get("type") == "silent" and not node.get("passthrough"): errors.append(key + ": silent wait semantics")
        if node.get("suppress_tool_results"): errors.append(key + ": suppressed tool results")
        if any(r.get("target_node") == "__previous__" for r in node.get("transitions", [])): errors.append(key + ": previous-node routing")
        if node.get("truncation_strategy") == "summarize": errors.append(key + ": summarisation")
        if any(field.get("extraction_prompt") for field in node.get("extraction_schema", [])): errors.append(key + ": custom extraction prompt")
        for tool in node.get("tools", []) + node.get("pre_actions", []):
            if tool.get("config", {}).get("maxRetries", 0): errors.append(key + ": automatic tool retries")
            if tool.get("config", {}).get("alwaysRunsAt"): errors.append(key + ": lifecycle tool")
            if tool.get("function", {}).get("handler") not in {"__function__:code_exec", "__function__:api_call"}: errors.append(key + ": unknown tool handler")
    return errors


class Runner:
    def __init__(self, workflow, policy, mapping, customer, roles, deadline, api=None, code=None, actor=None):
        self.workflow = deepcopy(workflow)
        self.roles, self.deadline = roles, deadline
        self.bank = Bank(policy, mapping, customer, api)
        self.code = code or DockerCode(deadline)
        self.actor = actor or Actor(roles, customer)
        names = customer.name.split(" ", 1)
        self.variables = {"customer_id": customer.id, "first_name": names[0], "last_name": names[-1], "now": customer.now.isoformat()}
        self.turns = [{"role": "user", "text": "Hello?", "node": workflow.get("initial_node"), "step": 0}]
        self.visits, self.step, self.previous = {}, 0, None

    def speak(self, text, node):
        if text: self.turns.append({"role": "assistant", "text": text, "node": node, "step": self.step})

    def model(self, role, instruction, payload, schema):
        self.deadline.require()
        return schema.model_validate(self.roles.ask(role, "local workflow proxy", instruction, payload, schema, max_tokens=5000))

    def history(self, node):
        history = self.turns
        if node.get("truncation_strategy") == "keep_recent": history = history[-node.get("truncation_window_size", 10):]
        return history

    def execute_tool(self, tool, supplied, node, stage):
        function = tool["function"]
        config = parameters(function.get("parameters", {}), supplied, self.variables)
        if function["handler"] == "__function__:code_exec":
            output = self.code.run(config["code"], self.variables)
            self.variables = output["vars"]
            result = {"status": "success", "data": None, "message": "Code executed successfully", "status_code": 200}
        else:
            if tool.get("pre_process_code"):
                output = self.code.run(tool["pre_process_code"], self.variables, config=config)
                self.variables, config = output["vars"], output["config"]
            name = function["name"]
            api = self.bank.api
            contract = self.bank.operations.get(name, {})
            expected_url = contract.get("url")
            if name not in self.bank.mapping.requests or config.get("url") != expected_url or config.get("method") != contract.get("method"):
                raise Unsupported("Workflow endpoint differs from the supplied bank contract")
            body = self.bank.invoke(name, config.get("body", {}))
            self.bank.ledger["calls"][-1]["step"] = self.step
            inner = body.get(self.bank.mapping.response_root, body) if self.bank.mapping.response_root else body
            status = inner.get(self.bank.mapping.response_fields["status_code"], 200)
            result = {"status": "success" if status < 400 else "error", "data": body, "status_code": status,
                      "message": "Local API response", "header": {"Content-Type": "application/json"}}
            if tool.get("post_process_code"):
                output = self.code.run(tool["post_process_code"], self.variables, result=result)
                self.variables, result = output["vars"], output["result"]
        name = stage if function["handler"] == "__function__:code_exec" else function["name"]
        flatten(result, name + "_response", self.variables)
        self.variables[name + "_status_code"] = result["status_code"]
        if result["status_code"] < 400:
            self.variables[name + "_success_count"] = int(self.variables.get(name + "_success_count", 0)) + 1
        for mapping in tool.get("response_mapping", []) + node.get("response_mapping", []):
            value = read_path(result, mapping["path"])
            if value is not None: self.variables[mapping["variable"]] = scalar(value)
        self.turns.append({"role": "tool", "name": function["name"], "result": result, "node": stage, "step": self.step})

    def route(self, node, stage):
        routes = merged_routes(node.get("transitions", []))
        deterministic = next((r["target_node"] for r in routes
                              if not has_intent(r["condition"]) and condition_matches(r["condition"], self.variables, {})), None)
        if deterministic and not node.get("loop_condition"):
            return deterministic
        descriptions = set()
        def collect(condition):
            if condition.get("operator") == "matches_intent": descriptions.add(condition.get("description", ""))
            for child in condition.get("conditions", []): collect(child)
        for route in routes: collect(route["condition"])
        if node.get("loop_condition"): descriptions.add(node["loop_condition"])
        if descriptions:
            matches = self.model("proxy_router", "Judge only these intent descriptions against the latest user speech and recent conversation. "
                                 "Do not choose a route yourself. Return one boolean per exact description; do not infer from hidden customer facts.",
                                 {"descriptions": sorted(descriptions), "routing_prompt": node.get("routing_prompt"),
                                  "conversation": self.history(node), "variables": self.variables}, IntentMatches).matches
            if set(matches) != descriptions: raise Unsupported("Routing model omitted an intent verdict")
            if node.get("loop_condition") and matches[node["loop_condition"]]: return stage
            if deterministic: return deterministic
            for route in routes:
                if condition_matches(route["condition"], self.variables, matches): return route["target_node"]
        return None

    def run(self):
        errors = capability_errors(self.workflow)
        stage, entering, extract = self.workflow.get("initial_node"), True, True
        ended = None
        try:
            if errors: raise Unsupported("; ".join(errors))
            nodes = {**self.workflow["nodes"], **self.workflow.get("global_nodes", {})}
            for self.step in range(1, 161):
                self.deadline.require()
                node = nodes[stage]
                if entering:
                    self.visits[stage] = self.visits.get(stage, 0) + 1
                    for tool in node.get("pre_actions", []): self.execute_tool(tool, {}, node, stage)
                if node["node_type"] == "end_call":
                    terminal = node.get("terminal", {}).get("function", {}).get("parameters", {})
                    args = parameters(terminal, {}, self.variables)
                    mode = args.get("message_mode", "none")
                    if mode not in {"none", "custom", "llm"}: raise Unsupported("Unknown terminal message mode")
                    if args.get("interruptible"): raise Unsupported("Interruptible terminal")
                    if mode == "custom": self.speak(args.get("spoken_message", ""), stage)
                    elif mode == "llm":
                        output = self.model("proxy_dialogue", args.get("llm_prompt", "Say goodbye."),
                                            {"conversation": self.history(node)}, Dialogue)
                        if output.tool_calls or output.transition: raise Unsupported("Terminal model attempted actions")
                        self.speak(output.message, stage)
                    ended = "end_call"
                    break
                if node["node_type"] in {"code", "api_request"}:
                    target = self.route(node, stage) or node.get("passthrough_default_transition")
                    if not target: raise Unsupported("Silent node has no matched continuation")
                    self.previous, stage, entering = stage, target, True
                    continue
                if extract and node.get("extraction_schema"):
                    schema = node["extraction_schema"]
                    output = self.model("proxy_extractor", "Extract only the declared speech variables. Preserve corrections. "
                                        "Return uncertain names separately and do not invent values. Dates are anchored to the call's now. "
                                        "Certainty is a local proxy, not Freya token probability.",
                                        {"schema": schema, "conversation": self.history(node), "now": self.variables["now"]}, Extracted)
                    fields = {f["name"]: f for f in schema}
                    if set(output.values) - set(fields): raise Unsupported("Extractor returned undeclared variables")
                    for key, value in output.values.items():
                        if key in output.uncertain or value is None: continue
                        field = fields[key]
                        if field.get("enum_values") and value not in field["enum_values"]: continue
                        if field.get("validation_pattern") and not re.fullmatch(field["validation_pattern"], str(value)): continue
                        self.variables[key] = value
                        self.turns.append({"role": "extracted", "name": key, "value": value, "node": stage, "step": self.step})
                target = self.route(node, stage) if extract or node.get("passthrough") or node.get("pre_actions") else None
                if target and target != stage:
                    self.previous, stage, entering = stage, target, True
                    continue
                for global_key, global_node in self.workflow.get("global_nodes", {}).items():
                    if target or stage in global_node.get("excluded_nodes", []): continue
                    if self.route({"transitions": [{"target_node": global_key, "condition": global_node.get("condition", {"operator": "always"})}]}, stage):
                        self.previous, stage, entering = stage, global_key, True
                        break
                else:
                    on_enter = node.get("on_enter", {"type": "llm"})
                    fixed = entering and on_enter.get("type") == "tts" and (not node.get("on_enter_first_entry_only") or self.visits[stage] == 1)
                    if fixed:
                        self.speak(substitute(on_enter.get("text", ""), self.variables), stage)
                        output = None
                    else:
                        if on_enter.get("type") == "silent" and node.get("passthrough"):
                            raise Unsupported("Silent passthrough conversation has no matched continuation")
                        task = node.get("loop_prompt") if self.visits.get(stage, 0) > 1 and node.get("loop_prompt") else node.get("task_message", "")
                        output = self.model("proxy_dialogue", "Act as the phone assistant in this current workflow stage. "
                                            "Follow the supplied system, role and task instructions. You know only call variables and conversation. "
                                            "Use only listed tools; arguments follow their function schemas, with baked defaults owned by the controller. "
                                            "A message is spoken before any tool_calls in the same result. Request a transition only if listed as a tool-call transition.",
                                            {"system": substitute(self.workflow.get("system_prompt", ""), self.variables),
                                             "role": substitute(node.get("role_message", ""), self.variables),
                                             "task": substitute(task, self.variables), "entry_prompt": substitute(on_enter.get("prompt", ""), self.variables) if entering else "", "conversation": self.history(node),
                                             "variables": self.variables, "tools": node.get("tools", []),
                                             "tool_transitions": [r for r in node.get("transitions", []) if r.get("is_tool_call")]}, Dialogue)
                        self.speak(output.message, stage)
                    entering, extract = False, False
                    if output and output.tool_calls:
                        tools = {tool["function"]["name"]: tool for tool in node.get("tools", [])}
                        for call in output.tool_calls:
                            if call.name not in tools: raise Unsupported("Dialogue requested a tool unavailable in the current stage")
                            self.execute_tool(tools[call.name], call.arguments, {}, stage)
                        target = self.route(node, stage)
                        if target and target != stage: self.previous, stage, entering = stage, target, True
                        continue
                    if output and output.transition:
                        allowed = {r["target_node"] for r in node.get("transitions", []) if r.get("is_tool_call")}
                        if output.transition not in allowed: raise Unsupported("Undeclared tool-call transition")
                        self.previous, stage, entering = stage, output.transition, True
                        continue
                    if not self.turns or self.turns[-1]["role"] != "assistant": raise Unsupported("Conversation produced no speech")
                    reply = self.actor.reply([t for t in self.turns if t["role"] in {"user", "assistant"}])
                    self.turns.append({"role": "user", "text": reply.message, "node": stage, "step": self.step})
                    if reply.hang_up:
                        ended = "customer_hangup"
                        break
                    if sum(t["role"] == "user" for t in self.turns) >= 30: raise Unsupported("User-turn cap reached")
                    extract = True
                    self.visits[stage] = self.visits.get(stage, 0) + 1
                    if self.visits[stage] >= node.get("max_node_turns", 1000):
                        target = node.get("max_turn_transition")
                        if not target: raise Unsupported("Node turn limit has no continuation")
                        self.previous, stage, entering = stage, target, True
                    continue
                continue
            if not ended: raise Unsupported("Workflow step cap reached")
        except (Unsupported, TimeoutError, KeyError, ValueError, TypeError) as exc:
            errors.append(str(exc))
        return {"case_id": self.bank.customer.id, "ended": ended, "turns": self.turns,
                "ledger": self.bank.ledger, "unknown": errors, "capabilities": CAPABILITIES}
