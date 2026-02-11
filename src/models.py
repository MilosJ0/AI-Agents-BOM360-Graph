"""Pydantic data contracts for BOM360 agent system."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

Intent = Literal[
    "work_instructions",
    "capacity_wip",
    "vsm",
    "supplier_risk",
    "line_status",
]


class QueryResult(BaseModel):
    """Wraps every Cypher execution for auditability."""

    cypher: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0


# ---------------------------------------------------------------------------
# Work Instructions
# ---------------------------------------------------------------------------


class WorkInstructionStep(BaseModel):
    step_no: int
    instruction: str
    checkpoint: str | None = None
    safety_note: str | None = None


class WorkInstruction(BaseModel):
    line_id: str
    job_id: str
    op_id: str
    op_name: str
    machine: str | None = None
    workers: list[str] = Field(default_factory=list)
    parts: list[str] = Field(default_factory=list)
    due_dt: str | None = None
    wip: int | None = None
    steps: list[WorkInstructionStep]
    definition_of_done: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Capacity / WIP
# ---------------------------------------------------------------------------


class CapacityFinding(BaseModel):
    finding: str
    severity: Literal["low", "medium", "high"]
    evidence: list[str] = Field(default_factory=list)


class CapacityReport(BaseModel):
    scope: str
    line_id: str | None = None
    job_id: str | None = None
    wip_summary: dict[str, Any] = Field(default_factory=dict)
    bottlenecks: list[CapacityFinding] = Field(default_factory=list)
    staffing_gaps: list[CapacityFinding] = Field(default_factory=list)
    due_date_risks: list[CapacityFinding] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Supplier Risk
# ---------------------------------------------------------------------------


class SupplierRiskItem(BaseModel):
    supplier: str
    part: str
    lead_time_days: int
    reliability: float
    risk_level: Literal["low", "medium", "high"]
    note: str = ""


class SupplierRiskReport(BaseModel):
    scope: str
    line_id: str | None = None
    job_id: str | None = None
    risks: list[SupplierRiskItem] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Line Status (quick summary)
# ---------------------------------------------------------------------------


class LineStatusSummary(BaseModel):
    line_id: str
    line_name: str
    status: str
    job_id: str | None = None
    product: str | None = None
    qty_planned: int | None = None
    qty_completed: int | None = None
    pct_complete: float | None = None
    due_date: str | None = None
    current_operation: str | None = None
    at_risk: bool = False
    risk_reason: str | None = None


class LineStatusReport(BaseModel):
    lines: list[LineStatusSummary]
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


class VerificationResult(BaseModel):
    valid: bool
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LangGraph state (TypedDict-style via Pydantic for structure)
# ---------------------------------------------------------------------------


class AppState(BaseModel):
    """Immutable-update–friendly state carried through the LangGraph."""

    messages: list = Field(default_factory=list)
    user_goal: str = ""
    intent: Intent | None = None

    # scope
    line_id: str | None = None
    job_id: str | None = None

    # retrieved graph facts (keyed by query name)
    facts: dict[str, QueryResult] = Field(default_factory=dict)

    # final outputs (exactly one will be populated per run)
    work_instructions: list[WorkInstruction] = Field(default_factory=list)
    capacity_report: CapacityReport | None = None
    supplier_risk_report: SupplierRiskReport | None = None
    line_status_report: LineStatusReport | None = None
    mermaid: str | None = None

    # verification
    verification: VerificationResult | None = None
    error: str | None = None
