"""PydanticAI agent definitions for BOM360.

Agents are pure functions of (system_prompt, input) → structured output.
They have no side effects and no graph access — all data is injected.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic_ai import Agent

from .models import (
    CapacityReport,
    LineStatusReport,
    SupplierRiskReport,
    VerificationResult,
    WorkInstruction,
)
from .prompts import (
    CAPACITY_PROMPT,
    LINE_STATUS_PROMPT,
    MERMAID_VSM_PROMPT,
    ROUTER_PROMPT,
    SUPPLIER_RISK_PROMPT,
    VERIFIER_PROMPT,
    WORK_INSTRUCTION_PROMPT,
)


def _model_name() -> str:
    return os.getenv("LLM_MODEL", "anthropic:claude-sonnet-4-20250514")


# ---------------------------------------------------------------------------
# Router: classifies user goal → intent token
# ---------------------------------------------------------------------------

router_agent = Agent(
    model=_model_name(),
    output_type=Literal[
        "work_instructions", "capacity_wip", "vsm", "supplier_risk", "line_status"
    ],
    system_prompt=ROUTER_PROMPT,
)

# ---------------------------------------------------------------------------
# Domain analysts (each produces a typed output from injected facts)
# ---------------------------------------------------------------------------

capacity_agent = Agent(
    model=_model_name(),
    output_type=CapacityReport,
    system_prompt=CAPACITY_PROMPT,
)

instruction_agent = Agent(
    model=_model_name(),
    output_type=list[WorkInstruction],
    system_prompt=WORK_INSTRUCTION_PROMPT,
)

supplier_risk_agent = Agent(
    model=_model_name(),
    output_type=SupplierRiskReport,
    system_prompt=SUPPLIER_RISK_PROMPT,
)

line_status_agent = Agent(
    model=_model_name(),
    output_type=LineStatusReport,
    system_prompt=LINE_STATUS_PROMPT,
)

mermaid_agent = Agent(
    model=_model_name(),
    output_type=str,
    system_prompt=MERMAID_VSM_PROMPT,
)

# ---------------------------------------------------------------------------
# Verifier: checks output against source facts
# ---------------------------------------------------------------------------

verifier_agent = Agent(
    model=_model_name(),
    output_type=VerificationResult,
    system_prompt=VERIFIER_PROMPT,
)
