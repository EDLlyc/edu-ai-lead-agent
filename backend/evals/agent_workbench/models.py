"""Strict, versioned contracts for the offline workbench evaluation dataset."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

CASE_SCHEMA_VERSION = "agent-workbench-eval-case-v1"

BoundedIdentifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._:-]*$"),
]
JsonScalar = str | int | bool


class EvalCategory(StrEnum):
    """Required portfolio-evaluation categories."""

    EVIDENCE_SEARCH = "evidence_search"
    EVENT_DETAIL = "event_detail"
    BRAND_CONTEXT = "brand_context"
    COPY_VALIDATION = "copy_validation"
    MULTI_TOOL = "multi_tool"
    SAFETY_REFUSAL = "safety_refusal"


class ExpectedTerminalClass(StrEnum):
    """Stable terminal classes graded without comparing answer prose."""

    COMPLETED = "completed"
    REFUSED = "refused"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"


class SafetyAssertion(StrEnum):
    """Deterministic invariants a case asks the evaluator to enforce."""

    ARGUMENT_SCHEMA_VALID = "argument_schema_valid"
    BRAND_NOT_FACTUAL = "brand_not_factual"
    CITATIONS_FROM_TRACE = "citations_from_trace"
    NO_FORBIDDEN_TOOLS = "no_forbidden_tools"
    NO_UNKNOWN_TOOLS = "no_unknown_tools"
    READ_ONLY_TOOLS_ONLY = "read_only_tools_only"
    WITHIN_BUDGET = "within_budget"


class NumericRange(BaseModel):
    """Inclusive constraint over a redacted numeric argument projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: int = Field(ge=0, le=16_384)
    maximum: int = Field(ge=0, le=16_384)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class ToolArgumentConstraint(BaseModel):
    """Expected values in the runner's allowlisted argument summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: BoundedIdentifier
    required_keys: tuple[BoundedIdentifier, ...] = ()
    exact: dict[BoundedIdentifier, JsonScalar] = Field(default_factory=dict, max_length=12)
    ranges: dict[BoundedIdentifier, NumericRange] = Field(default_factory=dict, max_length=12)

    @model_validator(mode="after")
    def validate_unique_constraints(self) -> Self:
        if len(self.required_keys) != len(set(self.required_keys)):
            raise ValueError("required_keys must be unique")
        overlap = set(self.exact).intersection(self.ranges)
        if overlap:
            raise ValueError("exact and ranges cannot constrain the same key")
        return self


class AgentEvalCase(BaseModel):
    """One sanitized oracle that is kept outside the model-facing request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agent-workbench-eval-case-v1"]
    case_id: BoundedIdentifier
    category: EvalCategory
    query: str = Field(min_length=1, max_length=500)
    fixture_scenario: BoundedIdentifier
    required_tools: tuple[BoundedIdentifier, ...] = ()
    allowed_tools: tuple[BoundedIdentifier, ...] = ()
    forbidden_tools: tuple[BoundedIdentifier, ...] = ()
    argument_constraints: tuple[ToolArgumentConstraint, ...] = ()
    allowed_citation_ids: tuple[BoundedIdentifier, ...] = ()
    required_fact_ids: tuple[BoundedIdentifier, ...] = ()
    expected_terminal_class: ExpectedTerminalClass
    expect_refusal: bool
    max_steps: int = Field(ge=0, le=4)
    safety_assertions: tuple[SafetyAssertion, ...] = ()

    @model_validator(mode="after")
    def validate_oracle_consistency(self) -> Self:
        named_sets = {
            "required_tools": self.required_tools,
            "allowed_tools": self.allowed_tools,
            "forbidden_tools": self.forbidden_tools,
            "allowed_citation_ids": self.allowed_citation_ids,
            "required_fact_ids": self.required_fact_ids,
            "safety_assertions": self.safety_assertions,
        }
        for field_name, values in named_sets.items():
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be unique")

        required = set(self.required_tools)
        allowed = set(self.allowed_tools)
        forbidden = set(self.forbidden_tools)
        if not required.issubset(allowed):
            raise ValueError("required_tools must be a subset of allowed_tools")
        if allowed.intersection(forbidden):
            raise ValueError("allowed_tools and forbidden_tools must be disjoint")
        constrained_tools = {constraint.tool for constraint in self.argument_constraints}
        if not constrained_tools.issubset(allowed):
            raise ValueError("argument constraints may reference only allowed tools")
        if len(constrained_tools) != len(self.argument_constraints):
            raise ValueError("each tool may have at most one argument constraint")
        if not set(self.required_fact_ids).issubset(self.allowed_citation_ids):
            raise ValueError("required_fact_ids must be a subset of allowed_citation_ids")

        terminal_refusal = self.expected_terminal_class is ExpectedTerminalClass.REFUSED
        if self.expect_refusal != terminal_refusal:
            raise ValueError("expect_refusal must match the refused terminal class")
        if not self.safety_assertions:
            raise ValueError("at least one safety assertion is required")
        return self
