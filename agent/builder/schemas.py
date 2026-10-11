"""Internal contracts, independent of Freya's permissive save schema."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class RequirementsBundle(Record):
    requirements: list[Requirement]
    input_variables: list[str]
    unresolved: list[str]


class WorkflowSpec(Record):
    """The editable source of a phone agent: compact, before the controller compiles it."""
    workflow: dict[str, Any]
    architecture: str = Field(description="A short rationale: the stages, what decides each route, and where each bank tool is called.")


class Edit(Record):
    op: Literal["set_field", "set_stage", "remove_stage", "set_workflow_field"]
    stage: str = Field(default="", description="The stage the edit is for. Empty for set_workflow_field.")
    field: str = Field(default="", description="set_field: the stage field to replace. set_workflow_field: system_prompt or initial_node.")
    value: Any = Field(default=None, description="The complete new value of that field, or the complete stage for set_stage.")


class Fix(Record):
    """One cause, the customers it is for, and the smallest edits that remove it."""
    cases: list[str] = Field(default_factory=list)
    problem: str = Field(description="One line: what goes wrong, and in which stage.")
    edits: list[Edit] = Field(min_length=1, max_length=20)


class Patch(Record):
    fixes: list[Fix]

    @model_validator(mode="before")
    @classmethod
    def usable_fixes(cls, value):
        """Keep the fixes that are well formed and drop the others one by one. Where the provider does
        not enforce the schema while the model writes, a patch arrives with one slip in it now and
        then (an edit given as text, a fix with too many edits); refusing the whole patch for that
        threw away every good fix in it and left the design with all its errors."""
        if not isinstance(value, dict) or not isinstance(value.get("fixes"), list):
            return value
        kept = []
        for fix in value["fixes"][:30]:
            try:
                kept.append(Fix.model_validate(fix).model_dump())
            except ValueError:
                continue
        return {**value, "fixes": kept}
