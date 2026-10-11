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
    product_fields: dict[str, str] = Field(description="Keys must be exactly the INTERNAL semantic names: id, kind, balance, minimum, days_late. Each value is the corresponding actual API product property. Never use API property names as keys.")
    response_fields: dict[str, str] = Field(description="Keys must be exactly the INTERNAL semantic names: ok, error, field_verified, all_verified, attempts_left, locked, promise_id, uncertain_commit, status_code. Each value is the corresponding actual API response property. Never reverse the mapping or use API property names as keys.")
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
        expected_response = {"ok", "error", "field_verified", "all_verified", "attempts_left", "locked",
                             "promise_id", "uncertain_commit", "status_code"}
        if set(self.response_fields) != expected_response or len(set(self.response_fields.values())) != len(expected_response):
            raise ValueError("Incomplete/duplicate response semantic bindings")
        if set(self.product_fields) != {"id", "kind", "balance", "minimum", "days_late"}:
            raise ValueError("Incomplete product mapping")
        if len(set(self.product_fields.values())) != 5:
            raise ValueError("Product fields must be unique")
        for name in [self.products_key, *self.product_fields.values(), *self.response_fields.values()]:
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


class Fault(Record):
    operation: Literal["create_promise", "get_account", "verify_identity"]
    occurrence: int = Field(ge=1)
    mode: Literal["pre_commit", "lost_reply"]


class Customer(Record):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    name: str
    family: str
    now: datetime
    identity: dict[str, str]
    products: list[Product] = Field(min_length=1, max_length=3)
    goals: list[Goal]
    third_party: bool
    wrong_answers: dict[str, list[str]]
    style: Literal["pieces", "corrects", "talkative", "asks_back", "in_words"]
    situation: str
    correction: str
    transfer: Literal["", "support", "human", "restructuring"]
    faults: list[Fault]

    @model_validator(mode="after")
    def references(self):
        ids = [p.id for p in self.products]
        if len(set(ids)) != len(ids) or {g.product_id for g in self.goals} != set(ids) or len(self.goals) != len(ids):
            raise ValueError("Exactly one goal per unique product is required")
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
