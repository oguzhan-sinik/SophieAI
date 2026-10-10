"""Internal contracts, independent of Freya's permissive save schema."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(Record):
    path: str
    heading: str
    span: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class Precedence(Record):
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: list[str] = Field(default_factory=list)


class Requirement(Record):
    rule_id: str
    source: Source
    kind: Literal["identity", "privacy", "tool", "money", "date", "dialogue", "outcome", "escalation", "other"]
    priority: Literal["hard", "normal"]
    condition: str
    must: list[str] = Field(default_factory=list)
    must_not: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    precedence: Precedence = Field(default_factory=Precedence)
    interpretation_status: Literal["resolved", "ambiguous", "conflicting"]
    test_templates: list[str]


class RequirementsBundle(Record):
    requirements: list[Requirement]
    input_variables: list[str]
    unresolved: list[str]


class Coverage(Record):
    nodes: list[str]
    tests: list[str]


class ToolGate(Record):
    """A source-backed gate checked on every entry path to a protected tool."""
    operation: str
    rule_ids: list[str]
    variable: str
    allowed_values: list[str]
    producer_operation: str
    response_path: str


class WorkflowSpec(Record):
    workflow: dict[str, Any]
    coverage: dict[str, Coverage]
    tool_gates: list[ToolGate]
    architecture: str


class CalendarExpectation(Record):
    variable: str = Field(description='The expected output variable holding the calculated day.')
    anchor: str = Field(description='ISO date (or date-time) the count starts after, normally the call now of this probe.')
    weekdays: list[int] = Field(description='Business weekdays from the source, Monday=0.')
    excluded_dates: list[str] = Field(description='Every non-business ISO date the source lists.')
    count: int = Field(ge=1, le=366, description='Which business day after the anchor.')


class CodeProbe(Record):
    probe_id: str
    rule_ids: list[str]
    node_id: str
    variables: dict[str, Any]
    expected: dict[str, Any] = Field(description='Only actual output variable names and expected values. No explanations or metadata.')
    rationale: str = ''
    calendar: list[CalendarExpectation] = Field(default_factory=list, description='One entry per expected variable that is the Nth business day after a date. The controller calculates the day and writes it into expected.')


class CodeProbes(Record):
    probes: list[CodeProbe]


class Edit(Record):
    op: Literal["set_node", "remove_node", "set_system_prompt", "set_initial_node", "set_global_nodes"]
    target: str
    value: Any = None


class RepairPatch(Record):
    """Only what a repair changes. Rewriting a whole workflow to fix two stages has corrupted the rest."""
    operations: list[Edit] = Field(min_length=1, description='set_node carries the complete corrected stage under its own name.')
    tool_gates: list[ToolGate] = Field(default_factory=list, description='The complete new gate list, only when a gate declaration itself must change.')
    summary: str


class Mutation(Record):
    parent_id: str
    mutation_type: Literal["add_guard", "change_route", "repair_tool_args", "adjust_prompt", "change_code_node", "add_role", "simplify_graph", "other"]
    target_nodes: list[str]
    target_rule_ids: list[str]
    hypothesis: str
    operations: list[Edit]
    expected_effect: str
    risk: Literal["low", "normal", "high"]
    coverage: dict[str, Coverage]


class MutationGroup(Record):
    proposals: list[Mutation]


class Diagnostic(Record):
    case_id: str
    rule_ids: list[str] = Field(max_length=6)
    # Bounded: asked for "every turn", a model has enumerated references until its output ran out.
    evidence_refs: list[str] = Field(max_length=4)
    failure_type: str
    likely_workflow_nodes: list[str] = Field(max_length=4)
    repair_hypothesis: str
    confidence: float = Field(ge=0, le=1)
    counterfactual_test: str
    status: Literal["hypothesis"] = "hypothesis"


class Diagnostics(Record):
    diagnoses: list[Diagnostic]
