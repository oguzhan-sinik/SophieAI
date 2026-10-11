"""Source-profile checks on bank events, independent of workflow implementation."""
from datetime import date, timedelta

from .reference import business_day, callback_time, legal_promise, money, next_business


def grade_ledger(policy, customer, ledger, *, complete=True):
    failed, unknown, hard = [], [], []
    def fail(message, critical=False):
        if message not in failed: failed.append(message)
        if critical and message not in hard: hard.append(message)
    calls = ledger.get("calls", [])
    required = {field.name for field in policy.identity}
    products = {product.id: product for product in customer.products}
    goals = {goal.product_id: goal for goal in customer.goals}
    closes = [call for call in calls if call["tool"] == "close_call"]
    if (complete and not closes) or len(closes) > 1 or (closes and (calls[-1]["tool"] != "close_call" or not closes[0].get("committed"))):
        fail("Exactly one successful close_call must be the last tool action", True)
    for call in calls:
        if call["tool"] in {"get_account", "create_promise", "add_note"} and not required.issubset(call.get("verified_before", [])):
            fail("Private account tool called before all identity fields passed", True)
        if customer.third_party and call["tool"] in {"verify_identity", "get_account", "create_promise", "add_note"}:
            fail("Identity/debt tool used for a third party", True)
        if call["tool"] == "verify_identity":
            field = call.get("args", {}).get("field")
            order = [f.name for f in policy.identity]
            if field in order and not set(order[:order.index(field)]).issubset(call.get("verified_before", [])):
                fail("Identity questions checked out of policy order", True)
            if call.get("result", {}).get("error") == "identity locked":
                fail("Identity tool called after the attempt limit", True)
    promises = ledger.get("promises", [])
    if len({p["product_id"] for p in promises}) != len(promises):
        fail("Duplicate recorded promise", True)
    for promise in promises:
        product = products.get(promise["product_id"])
        if not product:
            fail("Promise recorded on an unknown product", True)
            continue
        try:
            if not legal_promise(policy, product, promise["amount"], date.fromisoformat(promise["date"]), customer.now):
                fail("Promise violates amount/calendar policy", True)
        except (ValueError, TypeError):
            fail("Invalid amount/date in the promise ledger", True)
        goal = goals[product.id]
        if goal.action in {"refuse", "paid", "dispute", "hardship"}:
            fail("Promise contradicts the customer's willingness", True)
        elif goal.maximum_amount is not None and money(promise['amount']) > goal.maximum_amount:
            fail("Promise exceeds the customer's willingness", True)
        elif not goal.accepts_legal_alternative:
            if money(promise["amount"]) != money(goal.proposed_amount) or promise["date"] != str(goal.proposed_date):
                fail("Customer did not permit an alternative promise", True)
    for index, call in enumerate(calls):
        if call["tool"] != "create_promise": continue
        previous = [c for c in calls[:index] if c["tool"] == "create_promise" and c.get("args", {}).get("product_id") == call.get("args", {}).get("product_id")]
        if previous:
            last = previous[-1]
            if last.get("result", {}).get("ok") or last.get("result", {}).get("uncertain_commit"):
                fail("Promise retried after success or ambiguous commit", True)
            if len(previous) > policy.retry_limit:
                fail("Write retry limit exceeded", True)
    callbacks = ledger.get("callbacks", [])
    for callback in callbacks:
        try:
            day = date.fromisoformat(callback["date"])
            if day < customer.now.date() or not business_day(policy, day) or not policy.callback_start <= callback["time"] <= policy.callback_end:
                fail("Callback violates the working calendar/window", True)
        except (ValueError, TypeError):
            fail("Invalid callback date/time", True)
    if not complete:
        return {"failed": failed, "unknown": ["Final ledger outcome unavailable"],
                "hard_failures": hard, "ledger_pass": False}
    inverse_outcome = {value: meaning for meaning, value in policy.outcomes.items()}
    inverse_reason = {value: meaning for meaning, value in policy.reasons.items()}
    outcome = inverse_outcome.get(ledger.get("outcome"))
    reason = inverse_reason.get(ledger.get("reason"))
    transfers = ledger.get("transfers", [])
    notes = ledger.get("notes", [])
    if customer.third_party:
        expected = next_business(policy, customer.now.date() + timedelta(days=1)).isoformat()
        if callbacks != [{"date": expected, "time": callback_time(policy)}]:
            fail("Third-party requested callback was not recorded correctly")
        if (outcome, reason) != ("not_reached", "callback"):
            fail("Wrong third-party closure", True)
    elif not any(call.get("result", {}).get("all_verified") is True for call in calls if call["tool"] == "verify_identity"):
        if (outcome, reason) != ("not_verified", "failed"):
            fail("Wrong failed-identity closure", True)
    elif customer.transfer:
        if transfers != [{"queue": policy.queues[customer.transfer]}]:
            fail("Requested transfer queue missing or incorrect")
        if notes: fail("Notes recorded on a transfer", True)
        expected = "transferred" if policy.transfer_wins or not promises else "promise"
        if outcome != expected or (expected == "transferred" and reason != customer.transfer):
            fail("Wrong transfer/promise closure precedence", True)
    else:
        if transfers: fail("Unrequested transfer")
        if callbacks: fail("Unrequested callback")
        ambiguous = any(c.get("result", {}).get("uncertain_commit") for c in calls if c["tool"] == "create_promise")
        exhausted = set()
        for product_id in products:
            writes = [c for c in calls if c["tool"] == "create_promise" and c.get("args", {}).get("product_id") == product_id]
            if len(writes) == policy.retry_limit + 1 and all(c.get("result", {}).get("ok") is False and not c.get("committed") and not c.get("result", {}).get("uncertain_commit") for c in writes):
                exhausted.add(product_id)
        if ambiguous:
            if (outcome, reason) != ("no_promise", "service_error"):
                fail("Ambiguous-write closure must report service_error", True)
        elif promises:
            if outcome != "promise" or ledger.get("reason") is not None:
                fail("Wrong successful-promise closure", True)
        elif all(g.action == "paid" for g in customer.goals):
            if outcome != "paid" or ledger.get("reason") is not None:
                fail("Wrong already-paid closure", True)
        else:
            first = next((g for g in customer.goals if g.action != "paid"), None)
            expected_reason = "service_error" if first and first.product_id in exhausted else first.action if first and first.action in {"hardship", "dispute"} else "refused"
            if (outcome, reason) != ("no_promise", expected_reason):
                fail("Wrong no-promise closure", True)
        recorded = {p["product_id"] for p in promises}
        for goal in customer.goals:
            if goal.action in {"full", "floor"} and goal.product_id not in recorded and goal.product_id not in exhausted and not ambiguous:
                fail("Willing customer's promise was not recorded")
        if policy.multi_product_notes and len(customer.products) > 1:
            expected_notes = []
            for goal in customer.goals:
                if goal.product_id not in recorded:
                    reason_key = "service_error" if goal.product_id in exhausted else goal.action if goal.action in {"paid", "dispute", "hardship"} else "refused"
                    expected_notes.append((goal.product_id, policy.reasons[reason_key]))
            actual = [(n["product_id"], n["reason"]) for n in notes]
            if sorted(actual) != sorted(expected_notes): fail("Wrong/missing per-product notes")
        elif notes:
            fail("Unexpected notes for a single-product case")
    return {"failed": failed, "unknown": unknown, "hard_failures": hard,
            "ledger_pass": not failed and not unknown}
