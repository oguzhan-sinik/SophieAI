"""Seeded policy/API variation and bounded customer goals; no candidate input."""
from datetime import date, datetime, timedelta
from decimal import Decimal
import random

from .models import (Band, Customer, Fault, Goal, IdentityField, Mapping, OPERATIONS,
                     OUTCOMES, Policy, Product, REASONS)
from .reference import deadline, floor

FAMILIES = ("Full payment", "Third party", "Identity boundary", "Amount correction",
            "Calendar boundary", "Hardship", "Already paid or dispute",
            "Mixed products", "Write failure", "Closure and transfer")
STYLES = ("pieces", "corrects", "talkative", "asks_back", "in_words")


def sample_policy(seed, index=0):
    rng = random.Random(f"policy:{seed}:{index}")
    changed = bool(index % 2)
    names = ("registration_code", "postal_district") if changed else ("date_of_birth", "phone_last4")
    fraction = rng.choice((Decimal(".15"), Decimal(".20"))) if changed else None
    return Policy(
        bank_name=("Cedar" if changed else "Aster") + f" Synthetic Bank {seed}",
        identity=[IdentityField(name=n, normalisation="iso_date" if n == "date_of_birth" else "spaces") for n in names],
        wrong_answer_limit=rng.choice((2, 3, 4)), attempt_scope="per_field" if changed else "shared",
        weekdays=[0, 1, 2, 3] if changed else [0, 1, 2, 3, 4],
        holidays=[date(2028, 12, 25), date(2029, 1, 1)], count_today=changed,
        bands=[Band(name="early", first=1, last=7 if not changed else 9, deadline_days=12 if not changed else 9, attempts=1),
               Band(name="late", first=8 if not changed else 10, last=90, deadline_days=7 if not changed else 4, attempts=2)],
        floor_mode="balance_fraction" if changed else "account_field", floor_fraction=fraction,
        grouped_confirmation=not changed, multi_product_notes=True, hardship_spontaneous_promise=True,
        callback_start="09:00", callback_end="17:00", retry_limit=1,
        failed_write_commit="never" if not changed else "unknown",
        outcomes={k: ("arranged" if k == "promise" else "finished_" + k) if changed else k for k in OUTCOMES},
        reasons={k: "case_" + k if changed else k for k in REASONS},
        queues={k: "team_" + k if changed else k for k in ("support", "human", "restructuring")},
        transfer_wins=True, notification="You will receive a text message confirming this promise.",
    )


def sample_mapping(index=0):
    changed = bool(index % 2)
    semantic = {
        "verify_identity": ["customer_id", "field", "answer"], "get_account": ["customer_id"],
        "create_promise": ["customer_id", "product_id", "amount", "date"],
        "add_note": ["customer_id", "product_id", "reason", "text"],
        "schedule_callback": ["customer_id", "date", "time"],
        "transfer_to_agent": ["customer_id", "queue"], "close_call": ["customer_id", "outcome", "reason"],
    }
    rename = {"product_id": "account_ref", "amount": "sum_due", "date": "due_on",
              "field": "challenge", "answer": "response", "outcome": "disposition", "reason": "code"}
    return Mapping(
        requests={op: {k: (("payload." if op == "create_promise" else "") + rename.get(k, k)) if changed and k != "customer_id" else k for k in fields}
                  for op, fields in semantic.items()},
        response_fields={k: ("verified" if k == "field_verified" else "authenticated" if k == "all_verified" else k)
                         for k in ("ok", "error", "field_verified", "all_verified", "attempts_left", "locked",
                                   "promise_id", "uncertain_commit", "status_code")},
        response_root="result" if changed else "data", products_key="accounts" if changed else "products",
        product_fields=dict(zip(("id", "kind", "balance", "minimum", "days_late"),
                                ("account_ref", "category", "owed", "required_amount", "age_days") if changed else
                                ("product_id", "type", "past_due", "minimum_payment", "days_late"))),
    )


def openapi_for(policy, mapping, pack_id):
    descriptions = {
        "verify_identity": "Check only the named identity field. All required questions must pass before account access. "
                           "Invalid ISO dates do not consume an attempt; a wrong valid answer does. "
                           "Response fields are declared in the response schema.",
        "get_account": "Return the ordered products only after identity verification.",
        "create_promise": "Record once per product, after identity verification. The bank validates shape and product id, "
                          "NOT amount floors, calendar policy or caller confirmation. " +
                          ("Every failed write commits nothing; a retry is allowed by policy." if policy.failed_write_commit == "never" else
                           "A failed reply may hide a committed write. There is no idempotency or write-status endpoint; never retry an ambiguous failure."),
        "add_note": "Record a product note. Notes are not a bank policy decision.",
        "schedule_callback": "Record a date and HH:MM time; the agent is responsible for policy eligibility.",
        "transfer_to_agent": "Record a transfer to the requested queue.",
        "close_call": "Record the closure once. No operation is accepted after closure.",
    }
    paths = {}
    for operation in OPERATIONS:
        body = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
        for meaning, path in mapping.requests[operation].items():
            prop = {"type": "number" if meaning == "amount" else "string", "description": "Semantic meaning: " + meaning}
            if meaning == "date": prop["format"] = "date"
            if meaning == "field": prop["enum"] = [f.name for f in policy.identity]
            if meaning == "queue": prop["enum"] = list(policy.queues.values())
            if meaning == "outcome": prop["enum"] = list(policy.outcomes.values())
            if meaning == "reason": prop["enum"] = list(policy.reasons.values())
            parts = path.split(".")
            current = body
            if len(parts) == 2:
                parent = parts[0]
                if parent not in current["properties"]:
                    current["properties"][parent] = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
                    current["required"].append(parent)
                current = current["properties"][parent]
            current["properties"][parts[-1]] = prop
            if meaning not in {"reason", "text"}: current["required"].append(parts[-1])
        response = {"type": "object", "properties": {
            "ok": {"type": "boolean"}, "error": {"type": "string"},
            "field_verified": {"type": "boolean"}, "all_verified": {"type": "boolean"},
            "attempts_left": {"type": "integer"}, "locked": {"type": "boolean"},
            "promise_id": {"type": "string"}, "uncertain_commit": {"type": "boolean"},
            "status_code": {"type": "integer"},
        }}
        response["properties"] = {mapping.response_fields[k]: v for k, v in response["properties"].items()}
        if operation == "get_account":
            response["properties"][mapping.products_key] = {"type": "array", "items": {
                "type": "object", "properties": {field: {"type": "number" if key in {"balance", "minimum"} else
                                                               "integer" if key == "days_late" else "string"}
                                                          for key, field in mapping.product_fields.items()}}}
        if mapping.response_root:
            response = {"type": "object", "properties": {mapping.response_root: response}, "required": [mapping.response_root]}
        paths["/" + operation] = {"post": {"operationId": operation, "description": descriptions[operation],
            "requestBody": {"required": True, "content": {"application/json": {"schema": body}}},
            "responses": {"200": {"description": "Read ok, not HTTP success alone.", "content": {"application/json": {"schema": response}}},
                          "400": {"description": "Rejected request or operation; nothing committed."},
                          "500": {"description": "See the operation's declared commit semantics."},
                          "504": {"description": "Reply lost; commitment may be uncertain."}}}}
    return {"openapi": "3.0.3", "info": {"title": policy.bank_name, "version": "synthetic-1"},
            "servers": [{"url": f"https://{pack_id}.synthetic.invalid/v1"}], "paths": paths}


def customers_for(policy, seed, count=10):
    if not 1 <= count <= 10:
        raise ValueError("The approved starting cap is ten users per pack/build")
    rng = random.Random(f"users:{seed}")
    users = []
    for index in range(count):
        now = datetime(2028, 12, 20 + index % 9, 11, 0)
        products = []
        total = 3 if index in {7, 9} else 1
        for j in range(total):
            balance = Decimal(rng.randrange(45000, 150000)) / 100
            products.append(Product(id=f"product_{j+1}", kind=("credit_card", "personal_loan", "car_loan")[j],
                                    balance=balance, minimum=(balance * Decimal(".20")).quantize(Decimal(".01")),
                                    days_late=policy.bands[j % len(policy.bands)].first))
        goals = []
        for j, product in enumerate(products):
            action = "floor" if index in {3, 4} else "hardship" if index == 5 else "paid" if index == 6 else "refuse" if index == 7 and j else "full"
            requested = date(2028, 12, 25) if index == 4 else deadline(policy, product, now) if index in {7, 9} else now.date()
            amount = floor(policy, product) if action == "floor" else product.balance
            if index == 3: amount -= Decimal(".01")
            goals.append(Goal(product_id=product.id, action=action, proposed_amount=amount if action in {"full", "floor"} else None,
                              proposed_date=requested if action in {"full", "floor"} else None, accepts_legal_alternative=True))
        identity = {f.name: "1988-03-14" if f.normalisation == "iso_date" else
                    f"{rng.randrange(1000,9999)}" for f in policy.identity}
        wrong = {policy.identity[0].name: ["1991-07-12" if policy.identity[0].normalisation == "iso_date" else "999999"] * policy.wrong_answer_limit} if index == 2 else {}
        if index == 7:
            wrong = {policy.identity[-1].name: ["wrong-code"]}
        faults = [Fault(operation="create_promise", occurrence=1,
                        mode="pre_commit" if policy.failed_write_commit == "never" else "lost_reply")] if index == 8 else []
        users.append(Customer(id=f"SYN_{seed}_{index+1:02d}", name=f"{rng.choice(('Alex','Jordan','Morgan','Sam'))} {rng.choice(('Vale','Rowan','Ash','Reed'))}",
            family=FAMILIES[index], now=now, identity=identity, products=products, goals=goals, third_party=index == 1,
            wrong_answers=wrong, style=STYLES[index % 5],
            situation="You are the customer's partner; they can be called on the next working day at 11:00. Ask what this is about and offer to pay." if index == 1 else
                      "You lost your job and cannot pay. Decline a support transfer." if index == 5 else
                      "You paid the overdue payment in the app this morning." if index == 6 else
                      "Negotiate according to your product goals; give security answers only when asked.",
            correction="After the first read-back, correct the amount to your product's minimum; ask for another read-back before confirming." if index == 3 else "",
            transfer="human" if index == 9 else "", faults=faults))
    return users
