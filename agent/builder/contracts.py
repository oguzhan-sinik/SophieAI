"""Compile source-grounded requirements and the supplied OpenAPI contract."""
from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from . import runtime
from .artifacts import digest
from .schemas import RequirementsBundle
from .sources import load_api, read_document

# Sent with every tool call to a mock the team runs itself, so the mock can keep two calls apart. The platform
# drops a field whose placeholder has no value, so the header is absent rather than wrong where it is unknown.
CALL_HEADER = ("X-Call-Id", "{{call.call_id}}")


def source_documents(paths):
    documents = []
    for path in paths:
        path = Path(path).resolve()
        # A Markdown brief is read as it is, so that the text is the file's and line numbers are the file's.
        text, why = (path.read_text(), None) if path.suffix.lower() in (".md", ".txt") else read_document(path)
        if text is None or not text.strip():
            raise ValueError(f"Empty brief: {path}" if why in (None, "empty") else f"Cannot read {path}: {why}")
        documents.append({"path": str(path), "text": text, "numbered_text": "\n".join(f"{n}: {line}" for n, line in enumerate(text.splitlines(), 1))})
    if not documents:
        raise ValueError("At least one brief is required")
    return documents


def validate_requirements(bundle, documents):
    bundle = RequirementsBundle.model_validate(bundle)
    sources = {d["path"]: d["text"].splitlines() for d in documents}
    ids = {r.rule_id for r in bundle.requirements}
    if not ids or len(ids) != len(bundle.requirements):
        raise ValueError("Requirements must have unique IDs and cannot be empty")
    for rule in bundle.requirements:
        source = rule.source
        lines = sources.get(source.path)
        if lines is None or not 1 <= source.start_line <= source.end_line <= len(lines):
            raise ValueError(f"Invalid source range for {rule.rule_id}")
        actual = "\n".join(lines[source.start_line - 1:source.end_line])
        # Expand an explicitly abbreviated quotation only when every quoted
        # fragment occurs, in order, inside the declared source line range.
        if source.span not in actual and re.search(r"\.\.\.|…", source.span):
            fragments = [part.strip() for part in re.split(r"\.\.\.|…", source.span) if part.strip()]
            offset = 0
            for fragment in fragments:
                found = actual.find(fragment, offset)
                if found < 0:
                    break
                offset = found + len(fragment)
            else:
                if fragments:
                    source.span = actual
        if not source.span.strip() or source.span not in actual:
            raise ValueError(f"Source quotation is not verbatim for {rule.rule_id}")
        references = rule.dependencies + rule.precedence.supersedes + rule.precedence.superseded_by
        if any(r not in ids or r == rule.rule_id for r in references):
            raise ValueError(f"Unknown/self reference for {rule.rule_id}")
        if not rule.must and not rule.must_not:
            raise ValueError(f"Requirement has no obligation: {rule.rule_id}")
    index = {r.rule_id: r for r in bundle.requirements}
    for rule in bundle.requirements:
        for replaced in rule.precedence.supersedes:
            other = index[replaced]
            if rule.rule_id not in other.precedence.superseded_by:
                other.precedence.superseded_by.append(rule.rule_id)
    visiting, visited = set(), set()
    def visit(key):
        if key in visiting:
            raise ValueError("Cyclic policy precedence")
        if key in visited:
            return
        visiting.add(key)
        for replaced in index[key].precedence.supersedes:
            visit(replaced)
        visiting.remove(key)
        visited.add(key)
    for key in ids:
        visit(key)
    # Probes are derived acceptance tests, not new policy: they may only reference extracted rules,
    # and their expected record stays structural. A probe that invents a rule is a rejected bundle.
    if len(bundle.probes) != len({p.title for p in bundle.probes}):
        raise ValueError("Probes must have unique titles")
    for probe in bundle.probes:
        if any(r not in ids for r in probe.rule_ids):
            raise ValueError(f"Probe cites unknown rules: {probe.title}")
        if not all(act.strip() for act in probe.acts):
            raise ValueError(f"Probe has an empty customer act: {probe.title}")
        if not probe.expected.outcome.strip():
            raise ValueError(f"Probe has no expected outcome: {probe.title}")
    # An unresolved or ambiguous rule is passed on to the designer as it stands; raw bank material
    # is allowed to be unclear, and refusing to build would leave no phone agent at all.
    # Detect silently omitted numbered rules independently of the analyst.
    for path, lines in sources.items():
        covered = {n for r in bundle.requirements if r.source.path == path for n in range(r.source.start_line, r.source.end_line + 1)}
        if not covered and len(sources) > 2:
            # A case folder also holds documents that state no rule (example conversations, a list of customers):
            # a numbered line there is not a numbered requirement.
            continue
        missing = [i for i, line in enumerate(lines, 1) if re.match(r"^\d+\.\s", line) and i not in covered]
        if missing:
            raise ValueError(f"Uncovered numbered requirements in {path}: {missing}")
    return bundle.model_dump()


def compile_openapi(path, server=None):
    """The tool contract from an OpenAPI 3 file, JSON or YAML. With `server`, the address of a mock the team
    runs itself, every operation is called there: the contract's own server and its security do not apply."""
    spec = load_api(path)
    if not isinstance(spec, dict) or not str(spec.get("openapi", "")).startswith("3."):
        raise ValueError("Expected OpenAPI 3 document")
    if server is not None:
        mock = urlparse(str(server))
        if mock.scheme != "https" or not mock.hostname or mock.username or mock.password or mock.query or mock.fragment:
            raise ValueError(f"The mock address must be a plain https URL, not {server!r}")
        server = str(server).rstrip("/")

    def resolve(value, stack=()):
        if isinstance(value, list):
            return [resolve(v, stack) for v in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            ref = value["$ref"]
            if not ref.startswith("#/") or ref in stack:
                raise ValueError(f"Unsupported external/cyclic reference: {ref}")
            target = spec
            for token in ref[2:].split("/"):
                target = target[token.replace("~1", "/").replace("~0", "~")]
            return resolve({**target, **{k: v for k, v in value.items() if k != "$ref"}}, stack + (ref,))
        return {k: resolve(v, stack) for k, v in value.items()}

    resolved = resolve(spec)
    operations = {}
    for path_name, path_item in resolved.get("paths", {}).items():
        for method, op in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            name = op.get("operationId") or path_name.rstrip("/").rsplit("/", 1)[-1]
            if not re.fullmatch(r"[A-Za-z_]\w*", name) or name in operations:
                raise ValueError("Missing/duplicate usable operation ID")
            servers = op.get("servers", path_item.get("servers", resolved.get("servers", [])))
            if server is not None:
                # A bare mock host keeps the path the contract's own server has (/v1), so a contract and its mock agree on it.
                declared = urlparse(str(servers[0].get("url", ""))).path.rstrip("/") if servers and isinstance(servers[0], dict) else ""
                url = server + (declared if not urlparse(server).path and "{" not in declared else "") + path_name
            else:
                if not servers:
                    raise ValueError("Operation has no declared server")
                url = servers[0]["url"].rstrip("/") + path_name
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or "{" in url:
                raise ValueError("Only explicit HTTPS contract URLs are supported")
            parameters = path_item.get("parameters", []) + op.get("parameters", [])
            if parameters:
                raise ValueError(f"{name}: non-body parameters require a supported translator; refusing to guess")
            security = op.get("security", resolved.get("security", []))
            if server is not None:
                security = []
            if any(requirement for requirement in security):
                raise ValueError(f"{name}: credential binding is not configured for this contract")
            content = op.get("requestBody", {}).get("content", {})
            if content and "application/json" not in content:
                raise ValueError(f"{name}: only JSON request bodies are supported")
            body = content.get("application/json", {}).get("schema", {"type": "object", "properties": {}})
            if body.get("type") != "object":
                raise ValueError(f"{name}: request body must be an object")
            operations[name] = {"name": name, "method": method.upper(), "url": url, "description": op.get("description", op.get("summary", "")), "body": body, "responses": op.get("responses", {}), "security": security}
            if server is not None:
                operations[name]["call_header"] = True
    if not operations:
        raise ValueError("OpenAPI declares no supported operations")
    # The same contract served from another address is another contract: practice customers belong to the bank's own host.
    return {"sha256": digest(spec) if server is None else digest({"spec": spec, "server": server}), "operations": operations}


def tool_from_contract(contract, description, bindings=None):
    body = deepcopy(contract["body"])
    bindings = bindings or {}
    if set(bindings) - set(body.get("properties", {})):
        raise ValueError(f"Unknown argument bindings {sorted(set(bindings) - set(body.get('properties', {})))} for {contract['name']}; its fields are {sorted(body.get('properties', {}))}")
    for key, prop in body.get("properties", {}).items():
        # customer_id is the stable kit call token, not a sample customer's ID.
        if key == "customer_id":
            prop["default"] = "{{customer_id}}"
        elif key in bindings:
            prop["default"] = bindings[key]
        prop.setdefault("description", f"Value of {key} from the caller or preceding tool result, never invented.")
    return {"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 0}, "function": {
        "name": contract["name"], "handler": "__function__:api_call", "description": description,
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "default": contract["url"]}, "method": {"type": "string", "default": contract["method"]},
            "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"},
                                                         **({CALL_HEADER[0]: {"type": "string", "default": CALL_HEADER[1]}} if contract.get("call_header") else {})}},
            "connect_retries": {"type": "number", "default": 0}, "body": body}}}}


CODE_NAME = "code_exec"


def compile_workflow(source, contracts):
    """Compact source -> deployable workflow, plus notes on what was normalised.

    Purely mechanical: bank tools are expanded from the contract, the `code` shorthand becomes a
    code_exec action, engine-run stages get their fixed plumbing, and the runtime support is
    compiled in. No policy content is added or changed, so the model only ever edits the source."""
    if not isinstance(source, dict):
        raise ValueError("workflow must be an object")
    workflow, notes = deepcopy(source), []
    for group in ("nodes", "global_nodes"):
        if workflow.get(group) is None:
            workflow[group] = {}
        if not isinstance(workflow[group], dict):
            raise ValueError(f"workflow.{group} must be an object mapping each stage name to its stage")
    for group in ("nodes", "global_nodes"):
        for key, node in workflow[group].items():
            # Anything that is not a stage object or a tool object is left for the validator, which names it.
            if not isinstance(node, dict):
                continue
            if "code" in node:
                code = node.pop("code")
                if not isinstance(code, str):
                    raise ValueError(f"{key}: code must be the Python source as text")
                if node.get("pre_actions"):
                    raise ValueError(f"{key}: give either code or pre_actions, not both")
                node["pre_actions"] = [{"type": "function", "function": {"name": CODE_NAME, "handler": "__function__:code_exec", "parameters": {
                    "type": "object", "properties": {"code": {"type": "string", "default": code}, "timeout_ms": {"type": "number", "default": 10000}}}}}]
            if node.get("node_type") in ("code", "api_request"):
                node.setdefault("passthrough", True)
                node.setdefault("on_enter", {"type": "silent"})
                last = node["transitions"][-1] if isinstance(node.get("transitions"), list) and node["transitions"] else None
                if "passthrough_default_transition" not in node and isinstance(last, dict) and isinstance(last.get("condition"), dict) and last["condition"].get("operator") == "always":
                    node["passthrough_default_transition"] = last.get("target_node")
            for placement in ("tools", "pre_actions"):
                for i, tool in enumerate(node[placement] if isinstance(node.get(placement), list) else []):
                    if not isinstance(tool, dict) or "bank_operation" not in tool:
                        continue
                    name = tool["bank_operation"]
                    if name not in contracts["operations"]:
                        raise ValueError(f"{key}: unsupported bank operation {name}; the contract declares {sorted(contracts['operations'])}")
                    # type/config are controller-owned and rebuilt from the contract; a model-supplied copy is discarded.
                    unknown = set(tool) - {"bank_operation", "description", "bindings", "response_mapping", "pre_process_code", "post_process_code", "type", "config"}
                    if unknown:
                        raise ValueError(f"{key}: unknown bank tool fields {sorted(unknown)} on {name}; allowed are bank_operation, description, bindings, response_mapping, pre_process_code, post_process_code")
                    if not isinstance(tool.get("description"), str) or not isinstance(tool.get("bindings", {}), dict):
                        raise ValueError(f"{key}: bank tool {name} needs a text description and an object of bindings")
                    compiled = tool_from_contract(contracts["operations"][name], tool["description"], tool.get("bindings"))
                    for hook in ("pre_process_code", "post_process_code"):
                        if hook in tool:
                            compiled[hook] = tool[hook]
                    if isinstance(tool.get("response_mapping"), list):
                        if placement == "tools":
                            compiled["response_mapping"] = tool["response_mapping"]
                        else:
                            # Engine-run calls map their response on the stage, not on the tool.
                            existing = node.setdefault("response_mapping", [])
                            if isinstance(existing, list):
                                existing.extend(m for m in tool["response_mapping"] if m not in existing)
                                notes.append(f"{key}: moved response_mapping from the action to the stage")
                    node[placement][i] = compiled
    return runtime.apply(workflow, contracts), notes
