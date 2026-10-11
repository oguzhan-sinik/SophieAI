"""Seeded policy/API variation and bounded customer goals; no candidate input."""
from datetime import date, datetime, timedelta
from decimal import Decimal
import random

from .models import (Band, Behaviour, BehaviourPlan, Customer, Fault, Goal, IdentityField, Mapping, OPERATIONS,
                     OUTCOMES, Policy, Product, REASONS)
from .reference import business_day, callback_time, deadline, floor

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
        response["properties"] = {mapping.response_fields[k]: v for k, v in response["properties"].items() if k in mapping.response_fields}
        if operation == "get_account":
            response["properties"][mapping.products_key] = {"type": "array", "items": {
                "type": "object", "properties": {field: {"type": "number" if key in {"balance", "minimum"} else
                                                               "integer" if key == "days_late" else "string"}
                                                          for key, value in mapping.product_fields.items()
                                                          for field in (value.values() if isinstance(value, dict) else [value])}}}
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


def plan_for(customer, seed, profile='ordinary'):
    events = []
    if profile != 'baseline':
        if customer.third_party:
            events = [Behaviour(id='B15', kind='question', trigger='any')]
        else:
            field = next((k for k, v in customer.identity.items() if v.isdigit()), next(iter(customer.identity)))
            choices = [Behaviour(id='B01', kind='fragment', trigger='identity', target=field),
                       Behaviour(id='B10', kind='question', trigger='identity', question_topic='digital' if seed % 3 == 0 else 'purpose'),
                       Behaviour(id='B09', kind='tangent', trigger='identity'),
                       Behaviour(id='B07', kind='words', trigger='offer'),
                       Behaviour(id='B04', kind='self_repair', trigger='offer')]
            events = [choices[seed % len(choices)]]
            if profile == 'stress':
                slot = seed % 7
                dob = next((k for k,v in customer.identity.items() if len(v) == 10 and v[4] == '-'), None)
                if slot == 0 and dob:
                    events = [Behaviour(id='B03', kind='date_split', trigger='identity', target=dob), choices[3]]
                elif slot == 1:
                    events = [Behaviour(id='B08', kind='relative', trigger='offer'), choices[4]]
                elif slot == 2:
                    events = [Behaviour(id='B11', kind='mixed', trigger='offer'), choices[3]]
                elif slot == 3:
                    events = [Behaviour(id='B12', kind='backchannel', trigger='readback'), choices[2]]
                elif len(customer.products) > 1:
                    events = [Behaviour(id='B13', kind='reference', trigger='offer'), choices[2], choices[3]]
                else:
                    events = [choices[0], Behaviour(id='B02', kind='question', trigger='identity', target=field), choices[3]]
        if not customer.third_party and customer.identity_terminal:
            field = next(iter(customer.wrong_answers))
            events = [Behaviour(id='B10', kind='question', trigger='identity', target=field)] if profile == 'ordinary' else [Behaviour(id='B16', kind='tangent', trigger='identity', target=field)]
        elif not customer.third_party and (customer.transfer or all(g.action not in {'full','floor'} for g in customer.goals)):
            events = [Behaviour(id='B10',kind='question',trigger='identity')] if profile == 'ordinary' else [Behaviour(id='B09',kind='tangent',trigger='identity'), Behaviour(id='B14',kind='situation',trigger='any')]
        elif customer.faults and profile == 'stress':
            events = [Behaviour(id='B16',kind='tangent',trigger='identity'), choices[3]]
        if customer.correction:
            goal = next(g for g in customer.goals if g.action in {'full', 'floor'})
            product = next(p for p in customer.products if p.id == goal.product_id)
            revised = min(goal.maximum_amount or product.balance, product.minimum)
            events.append(Behaviour(id='B05', kind='correction', trigger='readback', target=goal.product_id, amount=revised))
    for event in events:
        if event.kind == 'tangent':
            event.amount = Decimal('17.40')
            event.day = customer.now.date() + timedelta(days=2 + seed % 3)
    return BehaviourPlan(seed=seed, profile=profile, events=events)


def customers_for(policy, seed, count=10, *, campaign=False):
    if campaign:
        if count != 30:
            raise ValueError('Release campaign has exactly thirty customers per pack')
        base = customers_for(policy, seed, 10)
        users = []
        for profile in ('baseline', 'ordinary', 'stress'):
            for index, original in enumerate(base):
                customer = original.model_copy(deep=True)
                customer.id += '_' + profile
                customer.plan = plan_for(customer, seed + index, profile)
                users.append(Customer.model_validate(customer.model_dump()))
        return users
    if not 1 <= count <= 10:
        raise ValueError("The approved starting cap is ten users per pack/build")
    rng = random.Random(f"users:{seed}")
    users = []
    anchor = min(policy.holidays) - timedelta(days=5) if policy.holidays else date(2028, 12, 20)
    for index in range(10):
        now = datetime.combine(anchor + timedelta(days=index % 9), datetime.min.time()).replace(hour=11)
        products = []
        total = 3 if index in {7, 9} else 1
        for j in range(total):
            balance = Decimal(rng.randrange(45000, 150000)) / 100
            products.append(Product(id=f"product_{j+1}", kind=("credit_card", "personal_loan", "car_loan")[j],
                                    balance=balance, minimum=(balance * Decimal(".20")).quantize(Decimal(".01")),
                                    days_late=policy.bands[j % len(policy.bands)].last if index == 3 else policy.bands[j % len(policy.bands)].first,
                                    card_last4=f"{rng.randrange(10000):04d}" if j == 0 else None))
        goals = []
        for j, product in enumerate(products):
            action = "floor" if index in {3, 4} else "hardship" if index == 5 else ("paid" if seed % 2 == 0 else "dispute") if index == 6 else "refuse" if index == 7 and j else "full"
            requested = next((now.date() + timedelta(days=d) for d in range(15) if not business_day(policy, now.date() + timedelta(days=d))), deadline(policy, product, now) + timedelta(days=1)) if index == 4 else deadline(policy, product, now) if index in {7, 9} else now.date()
            amount = floor(policy, product) if action == "floor" else product.balance
            if index == 3: amount -= Decimal(".01")
            goals.append(Goal(product_id=product.id, action=action, proposed_amount=amount if action in {"full", "floor"} else None,
                              proposed_date=requested if action in {"full", "floor"} else None, accepts_legal_alternative=True,
                              maximum_amount=floor(policy, product) if action == 'floor' else product.balance))
        identity = {f.name: "1988-03-14" if f.normalisation == "iso_date" else
                    f"{rng.randrange(0,10000):04d}" for f in policy.identity}
        wrong = {policy.identity[0].name: ["1991-07-12" if policy.identity[0].normalisation == "iso_date" else "999999"] * policy.wrong_answer_limit} if index == 2 else {}
        if index == 7:
            wrong = {policy.identity[-1].name: ["wrong-code"]}
        faults = [Fault(operation="create_promise", occurrence=1,
                        mode="pre_commit" if policy.failed_write_commit == "never" else "lost_reply")] if index == 8 else []
        users.append(Customer(id=f"SYN_{seed}_{index+1:02d}", name=f"{rng.choice(('Alex','Jordan','Morgan','Sam'))} {rng.choice(('Vale','Rowan','Ash','Reed'))}",
            family=FAMILIES[index], now=now, identity=identity, products=products, goals=goals, third_party=index == 1,
            wrong_answers=wrong, identity_terminal=index==2, style=STYLES[index % 5],
            situation=f"You are the customer's partner; they can be called on the next working day at {callback_time(policy)}. Ask what this is about and offer to pay." if index == 1 else
                      "You lost your job and cannot pay. Decline a support transfer." if index == 5 else
                      ("You paid the overdue payment in the app this morning." if seed % 2 == 0 else "You dispute this overdue payment; do not offer to pay.") if index == 6 else
                      "Negotiate according to your product goals; give security answers only when asked.",
            correction="After the first read-back, correct the first product's amount to its minimum; ask for another read-back before confirming." if index in {3, 7} else "",
            transfer="human" if index == 9 else "", faults=faults))
    for index, customer in enumerate(users):
        customer.plan = plan_for(customer, seed + index)
    priority = (0, 2, 8, 7, 3, 5, 4, 1, 6, 9)
    return users if count == 10 else [users[i] for i in priority[:count]]
