"""Explicit semantic facts; source ambiguity cannot be filled with policy defaults."""
from datetime import date, datetime
from decimal import Decimal
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OPERATIONS = ("verify_identity", "get_account", "create_promise", "add_note",
              "schedule_callback", "transfer_to_agent", "close_call")
OUTCOMES = ("promise", "paid", "transferred", "no_promise", "not_verified", "not_reached")
REASONS = ("refused", "hardship", "dispute", "service_error", "failed", "declined",
           "callback", "no_callback", "wrong_number", "deceased", "unclear",
           "support", "human", "restructuring", "paid")
CORE_RULES = (
    "privacy_before_identity", "sequential_verification", "full_then_floor", "decimal_half_up",
    "no_discounts", "date_clamp_to_deadline", "clarify_vague_date_once", "confirmation_before_write",
    "reconfirm_corrections", "one_promise_per_product", "no_false_success", "notify_after_success",
    "hardship_before_persuasion", "paid_no_promise", "third_party_callback",
    "notes_for_unpromised_multi", "no_notes_on_transfer", "end_close_last",
    "mixed_closure_first_unpaid", "ambiguous_write_service_error",
)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityField(Record):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    normalisation: Literal["exact", "spaces", "casefold", "iso_date"]


class Band(Record):
    name: str
    first: int = Field(ge=1)
    last: int = Field(ge=1)
    deadline_days: int = Field(ge=1, le=30)
    attempts: int = Field(ge=0, le=3)

    @model_validator(mode="after")
    def ordered(self):
        if self.last < self.first:
            raise ValueError("Reversed delinquency band")
        return self


class Policy(Record):
    bank_name: str
    identity: list[IdentityField] = Field(min_length=1, max_length=3)
    wrong_answer_limit: int = Field(ge=1, le=5)
    attempt_scope: Literal["shared", "per_field"]
    weekdays: list[int] = Field(min_length=1, max_length=7)
    holidays: list[date]
    count_today: bool
    bands: list[Band] = Field(min_length=1, max_length=4)
    floor_mode: Literal["account_field", "balance_fraction"]
    floor_fraction: Decimal | None = Field(gt=0, le=1)
    grouped_confirmation: bool
    multi_product_notes: bool
    hardship_spontaneous_promise: bool
    callback_start: str = Field(pattern=r"^\d{2}:\d{2}$")
    callback_end: str = Field(pattern=r"^\d{2}:\d{2}$")
    retry_limit: int = Field(ge=0, le=1)
    failed_write_commit: Literal["never", "unknown"]
    outcomes: dict[str, str] = Field(description="Map INTERNAL semantic keys to actual API enum values. Keys must be exactly: " + ", ".join(OUTCOMES) + ". Values must be unique. Do not use API enum values as keys.")
    reasons: dict[str, str] = Field(description="Map INTERNAL semantic keys to actual API enum values. Keys must be exactly: " + ", ".join(REASONS) + ". Values must be unique. Do not omit inactive reasons or use API enum values as keys.")
    queues: dict[str, str] = Field(description="Map INTERNAL semantic keys support, human, restructuring to their actual API queue enum values. Exactly these three keys with unique values; never reverse the mapping.")
    transfer_wins: bool
    notification: str

    @model_validator(mode="after")
    def coherent(self):
        if len(set(self.weekdays)) != len(self.weekdays) or any(d not in range(7) for d in self.weekdays):
            raise ValueError("Working weekdays must be unique values 0..6")
        if len({i.name for i in self.identity}) != len(self.identity):
            raise ValueError("Duplicate identity fields")
        end = 0
        for band in self.bands:
            if band.first != end + 1:
                raise ValueError("Bands must cover contiguous days beginning at one")
            end = band.last
        for mapping, keys in ((self.outcomes, OUTCOMES), (self.reasons, REASONS),
                              (self.queues, ("support", "human", "restructuring"))):
            if set(mapping) != set(keys) or len(set(mapping.values())) != len(keys):
                raise ValueError("Semantic enums must have complete, unique bindings")
        for value in (self.callback_start, self.callback_end):
            datetime.strptime(value, "%H:%M")
        if self.callback_start >= self.callback_end:
            raise ValueError("Callback window must start before it ends")
        if not self.notification.strip():
            raise ValueError("Notification cannot be empty")
        if (self.floor_mode == "balance_fraction") != (self.floor_fraction is not None):
            raise ValueError("A fraction is specified only for balance_fraction floors")
        return self


class Mapping(Record):
    requests: dict[str, dict[str, str]] = Field(description="For each bank operation, map INTERNAL semantic argument names to actual API request paths; never reverse this direction.")
    response_root: str = Field(description="Actual API response wrapper property, or empty string for an unwrapped response.")
    product_fields: dict[str, str | dict[str, str]] = Field(description="Required semantic keys: id, kind, balance, minimum, days_late; optional card_last4. Values are API properties. minimum may instead map credit_card, personal_loan, car_loan to their different API properties.")
    response_fields: dict[str, str] = Field(description="Required semantic keys: ok, error, field_verified, all_verified, attempts_left, promise_id. Optional locked, uncertain_commit, status_code, hint: include only if declared by the API. Values are actual API response properties.")
    products_key: str = Field(description="Actual API property containing the product array inside response_root.")

    @model_validator(mode="after")
    def complete(self):
        expected = {
            "verify_identity": {"customer_id", "field", "answer"}, "get_account": {"customer_id"},
            "create_promise": {"customer_id", "product_id", "amount", "date"},
            "add_note": {"customer_id", "product_id", "reason", "text"},
            "schedule_callback": {"customer_id", "date", "time"},
            "transfer_to_agent": {"customer_id", "queue"},
            "close_call": {"customer_id", "outcome", "reason"},
        }
        if set(self.requests) != set(OPERATIONS):
            raise ValueError("Exactly seven bank operation mappings are required")
        for operation, fields in self.requests.items():
            if set(fields) != expected[operation] or len(set(fields.values())) != len(fields):
                raise ValueError(f"Incomplete/duplicate semantic binding for {operation}")
            if any(not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?", p) for p in fields.values()):
                raise ValueError("Unsupported request field path")
        expected_response = {"ok", "error", "field_verified", "all_verified", "attempts_left", "promise_id"}
        if not expected_response.issubset(self.response_fields) or set(self.response_fields) - expected_response - {"locked", "uncertain_commit", "status_code", "hint"} or len(set(self.response_fields.values())) != len(self.response_fields):
            raise ValueError("Incomplete/duplicate response semantic bindings")
        if set(self.product_fields) - {"id", "kind", "balance", "minimum", "days_late", "card_last4"} or not {"id", "kind", "balance", "minimum", "days_late"}.issubset(self.product_fields):
            raise ValueError("Incomplete product mapping")
        for meaning, value in self.product_fields.items():
            if isinstance(value, dict) and (meaning != "minimum" or set(value) != {"credit_card", "personal_loan", "car_loan"}):
                raise ValueError("Only minimum supports a complete per-product-kind binding")
        names = [v for value in self.product_fields.values() for v in (value.values() if isinstance(value, dict) else [value])]
        for kind in ("credit_card", "personal_loan", "car_loan"):
            fields = [v[kind] if isinstance(v, dict) else v for v in self.product_fields.values()]
            if len(set(fields)) != len(fields): raise ValueError("Product fields must be unique")
        for name in [self.products_key, *names, *self.response_fields.values()]:
            if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                raise ValueError("Unsupported response field name")
        if self.response_root and not re.fullmatch(r"[a-z][a-z0-9_]*", self.response_root):
            raise ValueError("Unsupported response wrapper")
        return self


class Product(Record):
    id: str
    kind: Literal["credit_card", "personal_loan", "car_loan"]
    balance: Decimal = Field(gt=0)
    minimum: Decimal = Field(gt=0)
    days_late: int = Field(ge=1)
    card_last4: str | None = Field(default=None, pattern=r"^\d{4}$")

    @model_validator(mode="after")
    def amounts(self):
        if self.minimum > self.balance or any(x != x.quantize(Decimal(".01")) for x in (self.balance, self.minimum)):
            raise ValueError("Amounts must be cents, with minimum no greater than balance")
        return self


class Goal(Record):
    product_id: str
    action: Literal["full", "floor", "refuse", "paid", "dispute", "hardship"]
    proposed_amount: Decimal | None
    proposed_date: date | None
    accepts_legal_alternative: bool
    maximum_amount: Decimal | None = Field(default=None, gt=0)


class Fault(Record):
    operation: Literal["create_promise", "get_account", "verify_identity"]
    occurrence: int = Field(ge=1)
    mode: Literal["pre_commit", "lost_reply"]


class Behaviour(Record):
    id: str = Field(pattern=r"^B(0[1-9]|1[0-6])$")
    kind: Literal["fragment", "question", "tangent", "words", "self_repair", "correction", "date_split", "relative", "mixed", "backchannel", "reference", "situation"]
    trigger: Literal["identity", "offer", "readback", "any"]
    target: str = ""
    question_topic: Literal["purpose", "digital", "product"] = "purpose"
    amount: Decimal | None = None
    day: date | None = None


class BehaviourPlan(Record):
    version: str = "human-1"
    seed: int = 0
    profile: Literal["baseline", "ordinary", "stress"] = "ordinary"
    events: list[Behaviour] = Field(default_factory=list, max_length=6)
    patience: int = Field(default=40, ge=8, le=60)

    @model_validator(mode="after")
    def unique(self):
        if len({e.id for e in self.events}) != len(self.events):
            raise ValueError("Behaviour ids must be unique within a plan")
        for event in self.events:
            if event.kind == "correction" and (not event.target or event.amount is None and event.day is None):
                raise ValueError("A correction needs a product and a revised amount/date")
        return self


class Customer(Record):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    name: str
    family: str
    now: datetime
    identity: dict[str, str]
    products: list[Product] = Field(min_length=1, max_length=3)
    goals: list[Goal]
    third_party: bool
    identity_terminal: bool = False
    wrong_answers: dict[str, list[str]]
    style: Literal["pieces", "corrects", "talkative", "asks_back", "in_words"]
    situation: str
    correction: str
    transfer: Literal["", "support", "human", "restructuring"]
    faults: list[Fault]
    plan: BehaviourPlan | None = None

    @model_validator(mode="after")
    def references(self):
        ids = [p.id for p in self.products]
        if len(set(ids)) != len(ids) or {g.product_id for g in self.goals} != set(ids) or len(self.goals) != len(ids):
            raise ValueError("Exactly one goal per unique product is required")
        for goal in self.goals:
            product = next(p for p in self.products if p.id == goal.product_id)
            for value in (goal.proposed_amount, goal.maximum_amount):
                if value is not None and (not value.is_finite() or value <= 0 or value != value.quantize(Decimal('.01'))):
                    raise ValueError("Willingness amounts must be positive finite cents")
            if goal.maximum_amount is not None and goal.maximum_amount > product.balance:
                raise ValueError("Willingness cannot exceed the product balance")
            if goal.action in {'full', 'floor'} and (goal.proposed_amount is None or goal.proposed_date is None):
                raise ValueError("A payment goal needs amount and date")
        if self.plan:
            for event in self.plan.events:
                if event.target and event.target not in ids and event.target not in self.identity:
                    raise ValueError("Behaviour targets an unknown slot/product")
                if event.kind == 'correction' and event.target not in ids:
                    raise ValueError("Correction must target a product")
                if event.kind in {'fragment', 'date_split'} and event.target not in self.identity:
                    raise ValueError("A fragmented answer must target an identity slot")
                if self.third_party and (event.trigger == "identity" or event.kind == "correction"):
                    raise ValueError("Third parties cannot perform private identity/product events")
                if event.amount is not None and (not event.amount.is_finite() or event.amount <= 0 or event.amount != event.amount.quantize(Decimal('.01'))):
                    raise ValueError("Correction amounts must be positive finite cents")
        return self


class RenderedBrief(Record):
    markdown: str = Field(min_length=100)


class PolicyReading(Record):
    policy: Policy | None
    unresolved: list[str]
    supported_core_rules: list[str]


class RenderedReading(PolicyReading):
    mapping: Mapping | None


class Citation(Record):
    field: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str


class SourceReading(PolicyReading):
    citations: list[Citation]
    mapping: Mapping | None


class UserReply(Record):
    message: str = Field(min_length=1, max_length=2000)
    hang_up: bool
