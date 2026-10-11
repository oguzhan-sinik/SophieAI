"""Isolated bank execution. Collection policy is deliberately left to the grader."""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import re
from jsonschema import Draft4Validator, FormatChecker, SchemaError, ValidationError

from .generation import openapi_for


def read_path(value, path, missing=None):
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return missing
        value = value[key]
    return value


def write_path(value, path, item):
    keys = path.split(".")
    for key in keys[:-1]:
        value = value.setdefault(key, {})
    value[keys[-1]] = item


def check_schema(value, schema):
    try:
        Draft4Validator(schema, format_checker=FormatChecker()).validate(value)
    except ValidationError as exc:
        raise ValueError(exc.message) from exc
    kind = schema.get("type")
    matches = {"object": isinstance(value, dict), "string": isinstance(value, str),
               "number": type(value) in (int, float, Decimal), "integer": type(value) is int,
               "boolean": type(value) is bool, "array": isinstance(value, list)}
    if kind and not matches.get(kind, False):
        raise ValueError(f"Expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Value is outside the declared enum")
    if kind == "number" and not Decimal(str(value)).is_finite():
        raise ValueError("Non-finite amount")
    if kind == "object":
        if set(schema.get("required", [])) - set(value):
            raise ValueError("Missing required request fields")
        if schema.get("additionalProperties") is False and set(value) - set(schema.get("properties", {})):
            raise ValueError("Unknown request fields")
        for key, prop in schema.get("properties", {}).items():
            if key in value: check_schema(value[key], prop)
    if kind == "array":
        for item in value: check_schema(item, schema.get("items", {}))
    if schema.get("format") == "date":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Expected YYYY-MM-DD")
        date.fromisoformat(value)


class Bank:
    def __init__(self, policy, mapping, customer, api=None):
        self.policy, self.mapping, self.customer = policy, mapping, customer
        self.api = api or openapi_for(policy, mapping, "local-bank")
        self.operations = operations_for(self.api)
        validate_mapping(policy, mapping, self.operations)
        self.verified, self.wrong, self.counts = set(), {}, {}
        self.closed = False
        self.ledger = {"promises": [], "notes": [], "callbacks": [], "transfers": [],
                       "outcome": None, "reason": None, "calls": []}

    def invoke(self, operation, body):
        if operation not in self.mapping.requests:
            raise ValueError("Unknown bank operation")
        event = {"tool": operation, "request": deepcopy(body), "verified_before": sorted(self.verified), "committed": False}
        self.counts[operation] = self.counts.get(operation, 0) + 1
        try:
            if self.closed: raise ValueError("call closed")
            schema = self.operations[operation].get("documented_body") or self.operations[operation]["body"]
            check_schema(body, schema)
            args = {key: read_path(body, path) for key, path in self.mapping.requests[operation].items()}
            event["args"] = args
            if args["customer_id"] != self.customer.id: raise ValueError("unknown customer")
            fault = next((f for f in self.customer.faults if f.operation == operation and f.occurrence == self.counts[operation]), None)
            if fault and fault.mode == "pre_commit":
                result = {"ok": False, "error": "service unavailable", "status_code": 500, "uncertain_commit": False}
            else:
                result = self._execute(operation, args, event)
                if fault and fault.mode == "lost_reply" and event["committed"]:
                    result = {"ok": False, "error": "reply lost", "status_code": 504, "uncertain_commit": True}
        except (ValueError, KeyError, TypeError) as exc:
            result = {"ok": False, "error": str(exc), "status_code": 400}
        event["result"] = deepcopy(result)
        self.ledger["calls"].append(event)
        schema = self.operations[operation]["responses"]["200"]["content"]["application/json"]["schema"]
        if self.mapping.response_root: schema = schema_at(schema, self.mapping.response_root)
        payload = {self.mapping.response_fields.get(k, k): v for k, v in result.items()
                   if self.mapping.response_fields.get(k, k) in schema.get("properties", {})}
        return {self.mapping.response_root: payload} if self.mapping.response_root else payload

    def _execute(self, operation, args, event):
        policy, customer = self.policy, self.customer
        if operation == "verify_identity":
            field = args["field"]
            rule = next(f for f in policy.identity if f.name == field)
            scope = field if policy.attempt_scope == "per_field" else "all"
            used = self.wrong.get(scope, 0)
            if used >= policy.wrong_answer_limit:
                return {"ok": False, "error": "identity locked", "locked": True, "all_verified": False}
            def normalise(value):
                if rule.normalisation == "spaces": return "".join(value.split())
                if rule.normalisation == "casefold": return value.strip().casefold()
                if rule.normalisation == "iso_date": return date.fromisoformat(value).isoformat()
                return value
            if rule.normalisation == "iso_date" and self.mapping.response_fields.get("hint"):
                expected = date.fromisoformat(customer.identity[field])
                if args["answer"] == f"{expected.year:04d}-{expected.day:02d}-{expected.month:02d}" and expected.day != expected.month:
                    return {"ok": True, "field_verified": False, "all_verified": False,
                            "attempts_left": policy.wrong_answer_limit - used, "hint": "day_month_swapped"}
            correct = not customer.third_party and normalise(args["answer"]) == normalise(customer.identity[field])
            if correct: self.verified.add(field)
            else: self.wrong[scope] = used + 1
            return {"ok": True, "field_verified": correct, "all_verified": len(self.verified) == len(policy.identity),
                    "attempts_left": policy.wrong_answer_limit - self.wrong.get(scope, 0),
                    "locked": self.wrong.get(scope, 0) >= policy.wrong_answer_limit}
        if operation in {"get_account", "create_promise", "add_note"} and len(self.verified) != len(policy.identity):
            raise ValueError("identity not verified")
        if operation == "get_account":
            products = [{(field[product.kind] if isinstance(field, dict) else field):
                         float(getattr(product, meaning)) if meaning in {"balance", "minimum"} else getattr(product, meaning)
                         for meaning, field in self.mapping.product_fields.items()
                         if meaning != "card_last4" or (product.kind == "credit_card" and product.card_last4 is not None)} for product in customer.products]
            return {"ok": True, self.mapping.products_key: products}
        if operation in {"create_promise", "add_note"}:
            if args["product_id"] not in {p.id for p in customer.products}:
                raise ValueError("unknown product")
        if operation == "create_promise":
            if any(p["product_id"] == args["product_id"] for p in self.ledger["promises"]):
                raise ValueError("promise already recorded")
            promise = {"product_id": args["product_id"], "amount": str(Decimal(str(args["amount"]))), "date": args["date"]}
            self.ledger["promises"].append(promise)
            result = {"ok": True, "promise_id": f"promise_{len(self.ledger['promises'])}"}
        elif operation == "add_note":
            self.ledger["notes"].append({k: args[k] for k in ("product_id", "reason", "text")})
            result = {"ok": True}
        elif operation == "schedule_callback":
            datetime.strptime(args["time"], "%H:%M")
            self.ledger["callbacks"].append({"date": args["date"], "time": args["time"]})
            result = {"ok": True}
        elif operation == "transfer_to_agent":
            self.ledger["transfers"].append({"queue": args["queue"]})
            result = {"ok": True}
        elif operation == "close_call":
            semantic = next(k for k, value in policy.outcomes.items() if value == args["outcome"])
            if semantic not in {"promise", "paid"} and not args.get("reason"):
                raise ValueError("closure reason required")
            self.ledger["outcome"], self.ledger["reason"] = args["outcome"], args.get("reason")
            self.closed = True
            result = {"ok": True}
        else:
            raise ValueError("Unsupported operation")
        event["committed"] = True
        return result


def operations_for(api):
    import tempfile
    from pathlib import Path
    import json
    from agent.builder.contracts import compile_openapi
    with tempfile.TemporaryDirectory(prefix="synthetic-contract-") as folder:
        path = Path(folder) / "openapi.json"
        path.write_text(json.dumps(api))
        return compile_openapi(path)["operations"]


def schema_at(schema, path):
    for key in path.split("."):
        schema = schema.get("properties", {}).get(key, {})
    return schema


def supported_schema(schema):
    if schema.get("nullable") or set(schema) - set(Draft4Validator.META_SCHEMA["properties"]) - {"example", "nullable", "readOnly", "writeOnly", "deprecated", "xml", "externalDocs", "discriminator"}:
        raise ValueError("Unsupported API schema constraint")
    if schema.get("format") and schema["format"] not in FormatChecker.checkers:
        raise ValueError("Unsupported API schema format")
    try:
        Draft4Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError("Invalid API schema: " + exc.message) from exc
    if isinstance(schema.get("items"), list):
        raise ValueError("Unsupported API schema tuple items")
    children = [child for key in ("properties", "patternProperties", "definitions", "dependencies")
                for child in schema.get(key, {}).values() if isinstance(child, dict)]
    for key in ("items", "additionalProperties", "additionalItems", "not"):
        if isinstance(schema.get(key), dict): children.append(schema[key])
    for key in ("allOf", "anyOf", "oneOf"):
        children.extend(schema.get(key, []))
    for child in children: supported_schema(child)


def validate_mapping(policy, mapping, operations):
    if set(operations) != set(mapping.requests):
        raise ValueError("Unsupported operation set for local bank")
    for name, operation in operations.items():
        if operation["method"] != "POST":
            raise ValueError("Local bank supports only explicit POST operations")
        body = operation.get("documented_body") or operation["body"]   # the request as the contract documents it
        supported_schema(body)
        fields = mapping.requests[name]
        for semantic, path in fields.items():
            prop = schema_at(body, path)
            expected = "number" if semantic == "amount" else "string"
            if prop.get("type") != expected:
                raise ValueError(name + ": incompatible/missing request binding " + semantic)
            enum = prop.get("enum")
            reason_keys = ("refused", "hardship", "dispute", "paid", "service_error") if name == "add_note" else policy.reasons
            values = [f.name for f in policy.identity] if semantic == "field" else list(policy.queues.values()) if semantic == "queue" else list(policy.outcomes.values()) if semantic == "outcome" else [policy.reasons[k] for k in reason_keys] if semantic == "reason" else []
            if enum is not None and not set(values).issubset(enum):
                raise ValueError(name + ": policy enum is absent from the supplied API")
        def leaves(node, prefix=""):
            result = set()
            for key in node.get("required", []):
                path = prefix + key
                prop = node.get("properties", {}).get(key, {})
                result.update(leaves(prop, path + ".") if prop.get("type") == "object" else {path})
            return result
        if leaves(body) - set(fields.values()):
            raise ValueError(name + ": additional required arguments have no semantic binding")
        schema = operation["responses"].get("200", {}).get("content", {}).get("application/json", {}).get("schema", {})
        if mapping.response_root:
            schema = schema_at(schema, mapping.response_root)
        required = {"ok": "boolean"}
        if name == "verify_identity": required.update(field_verified="boolean", all_verified="boolean", attempts_left="integer")
        if name == "create_promise": required["promise_id"] = "string"
        for meaning, kind in required.items():
            if schema_at(schema, mapping.response_fields[meaning]).get("type") != kind:
                raise ValueError(name + ": incompatible/missing response binding " + meaning)
        if name == "get_account":
            products = schema_at(schema, mapping.products_key)
            if products.get("type") != "array": raise ValueError("Missing account array")
            for meaning, field in mapping.product_fields.items():
                kind = "number" if meaning in {"balance", "minimum"} else "integer" if meaning == "days_late" else "string"
                for property_name in (field.values() if isinstance(field, dict) else [field]):
                    if schema_at(products.get("items", {}), property_name).get("type") != kind:
                        raise ValueError("Unsupported account/product response schema")
