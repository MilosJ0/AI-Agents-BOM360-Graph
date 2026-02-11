"""LangGraph workflow: data-fetching nodes + agent nodes + verifier.

Key fixes over v0.1:
- No MCP: direct Neo4j queries via parameterized templates.
- All 5 intents fully routed (no silent fallthrough).
- Conditional edges after every fork (no conflicting unconditional edges).
- Verifier node validates outputs against source facts.
- Immutable state updates via model_copy().
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from langgraph.graph import END, StateGraph

from .agents import (
    capacity_agent,
    instruction_agent,
    line_status_agent,
    mermaid_agent,
    router_agent,
    supplier_risk_agent,
    verifier_agent,
)
from .cypher_templates import (
    all_lines_status,
    most_urgent_lines,
    operation_backbone,
    parts_and_suppliers,
    skill_coverage,
    supervisors_for_line,
    workers_for_line,
)
from .models import AppState
from .neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Helper: serialize facts for agent prompts
# ═══════════════════════════════════════════════════════════════════════════


def _facts_payload(state: AppState, keys: list[str]) -> str:
    """Build a structured text payload from selected fact keys."""
    sections = []
    sections.append(f"Scope: line_id={state.line_id}, job_id={state.job_id}")
    for k in keys:
        qr = state.facts.get(k)
        if qr and qr.rows:
            sections.append(f"\n### {k} ({qr.row_count} rows)\n{json.dumps(qr.rows, indent=2, default=str)}")
        elif qr:
            sections.append(f"\n### {k}\nNo data returned.")
    return "\n".join(sections)


# ═══════════════════════════════════════════════════════════════════════════
# Node functions (each returns a NEW AppState via model_copy)
# ═══════════════════════════════════════════════════════════════════════════


def node_route(state: AppState) -> AppState:
    """Classify user goal into an intent."""
    user_goal = state.user_goal
    if not user_goal and state.messages:
        # Extract from last message (Studio sends HumanMessage objects or dicts)
        last = state.messages[-1]
        user_goal = last.content if hasattr(last, "content") else str(last)
    logger.info("Routing: %s", user_goal)
    result = router_agent.run_sync(user_goal)
    logger.info("Intent: %s", result.output)
    return state.model_copy(update={"intent": result.output, "user_goal": user_goal})


def node_pick_scope(state: AppState, db: Neo4jClient) -> AppState:
    """Resolve line_id and job_id if not already set."""
    if state.line_id and state.job_id:
        return state

    cypher, params = most_urgent_lines(limit=5)
    qr = db.run(cypher, params)
    updates: dict = {"facts": {**state.facts, "scope_candidates": qr}}

    if qr.rows:
        updates["line_id"] = qr.rows[0].get("line_id")
        updates["job_id"] = qr.rows[0].get("job_id")
        logger.info("Auto-scoped to line=%s job=%s", updates["line_id"], updates["job_id"])

    return state.model_copy(update=updates)


# --- Data fetching nodes (intent-agnostic building blocks) ----------------


def node_fetch_backbone(state: AppState, db: Neo4jClient) -> AppState:
    """Fetch ordered operation chain for the scoped line/job."""
    cypher, params = operation_backbone(state.line_id, state.job_id)
    qr = db.run(cypher, params)
    return state.model_copy(update={"facts": {**state.facts, "backbone": qr}})


def node_fetch_parts(state: AppState, db: Neo4jClient) -> AppState:
    """Fetch parts and suppliers for the scoped line/job."""
    cypher, params = parts_and_suppliers(state.line_id, state.job_id)
    qr = db.run(cypher, params)
    return state.model_copy(update={"facts": {**state.facts, "parts_suppliers": qr}})


def node_fetch_workers(state: AppState, db: Neo4jClient) -> AppState:
    """Fetch worker assignments for the scoped line/job."""
    cypher, params = workers_for_line(state.line_id, state.job_id)
    qr = db.run(cypher, params)

    cypher2, params2 = supervisors_for_line(state.line_id)
    qr2 = db.run(cypher2, params2)

    cypher3, params3 = skill_coverage(state.line_id)
    qr3 = db.run(cypher3, params3)

    return state.model_copy(
        update={
            "facts": {
                **state.facts,
                "workers": qr,
                "supervisors": qr2,
                "skill_coverage": qr3,
            }
        }
    )


def node_fetch_all_lines(state: AppState, db: Neo4jClient) -> AppState:
    """Fetch quick status for all lines (for line_status intent)."""
    cypher, params = all_lines_status()
    qr = db.run(cypher, params)
    return state.model_copy(update={"facts": {**state.facts, "all_lines": qr}})


# --- Agent nodes (invoke PydanticAI with serialized facts) ----------------


def node_capacity(state: AppState) -> AppState:
    """Run capacity analysis agent."""
    payload = _facts_payload(state, ["backbone", "workers", "supervisors", "skill_coverage"])
    result = capacity_agent.run_sync(payload)
    return state.model_copy(update={"capacity_report": result.output})


def node_instructions(state: AppState) -> AppState:
    """Run work instruction writer agent."""
    payload = _facts_payload(state, ["backbone", "parts_suppliers", "workers"])
    result = instruction_agent.run_sync(payload)
    return state.model_copy(update={"work_instructions": result.output})


def node_supplier_risk(state: AppState) -> AppState:
    """Run supplier risk analysis agent."""
    payload = _facts_payload(state, ["backbone", "parts_suppliers"])
    result = supplier_risk_agent.run_sync(payload)
    return state.model_copy(update={"supplier_risk_report": result.output})


def node_line_status(state: AppState) -> AppState:
    """Run line status summary agent."""
    payload = _facts_payload(state, ["all_lines"])
    result = line_status_agent.run_sync(
        f"Generate a status summary.\n\n{payload}\n\nCurrent time: {datetime.now(timezone.utc).isoformat()}"
    )
    return state.model_copy(update={"line_status_report": result.output})


def node_vsm_mermaid(state: AppState) -> AppState:
    """Generate Mermaid VSM diagram from backbone data."""
    payload = _facts_payload(state, ["backbone"])
    result = mermaid_agent.run_sync(payload)
    return state.model_copy(update={"mermaid": result.output})


# --- Verifier node --------------------------------------------------------


def node_verify(state: AppState) -> AppState:
    """Verify the generated output against source facts."""
    # Determine what output to verify
    if state.capacity_report:
        output_str = state.capacity_report.model_dump_json()
        fact_keys = ["backbone", "workers", "supervisors", "skill_coverage"]
    elif state.work_instructions:
        output_str = json.dumps([wi.model_dump() for wi in state.work_instructions], default=str)
        fact_keys = ["backbone", "parts_suppliers", "workers"]
    elif state.supplier_risk_report:
        output_str = state.supplier_risk_report.model_dump_json()
        fact_keys = ["backbone", "parts_suppliers"]
    elif state.line_status_report:
        output_str = state.line_status_report.model_dump_json()
        fact_keys = ["all_lines"]
    elif state.mermaid:
        # Light verification for Mermaid — just check it's non-empty valid-ish
        from .models import VerificationResult

        valid = "graph" in state.mermaid.lower() or "flowchart" in state.mermaid.lower()
        return state.model_copy(
            update={
                "verification": VerificationResult(
                    valid=valid,
                    issues=[] if valid else ["Mermaid output missing graph/flowchart declaration"],
                )
            }
        )
    else:
        return state

    source_str = _facts_payload(state, fact_keys)
    prompt = (
        f"Verify this output against the source data.\n\n"
        f"### Output\n{output_str}\n\n"
        f"### Source Facts\n{source_str}"
    )
    result = verifier_agent.run_sync(prompt)
    logger.info("Verification: valid=%s issues=%d", result.output.valid, len(result.output.issues))
    return state.model_copy(update={"verification": result.output})


# --- Respond node (format output as chat message) -------------------------


def _format_response(state: AppState) -> str:
    """Format the structured output as human-readable text."""
    parts = []
    parts.append(f"**Intent:** {state.intent}")

    if state.capacity_report:
        r = state.capacity_report
        parts.append(f"\n## Capacity & WIP Report\n**Scope:** {r.scope}")
        if r.bottlenecks:
            parts.append("\n### Bottlenecks")
            for b in r.bottlenecks:
                parts.append(f"- [{b.severity.upper()}] {b.finding}")
        if r.staffing_gaps:
            parts.append("\n### Staffing Gaps")
            for g in r.staffing_gaps:
                parts.append(f"- [{g.severity.upper()}] {g.finding}")
        if r.due_date_risks:
            parts.append("\n### Due-Date Risks")
            for d in r.due_date_risks:
                parts.append(f"- [{d.severity.upper()}] {d.finding}")
        if r.recommended_actions:
            parts.append("\n### Recommended Actions")
            for i, a in enumerate(r.recommended_actions, 1):
                parts.append(f"{i}. {a}")

    elif state.work_instructions:
        parts.append(f"\n## Work Instructions ({len(state.work_instructions)} operations)")
        for wi in state.work_instructions:
            parts.append(f"\n### {wi.op_name} ({wi.op_id})")
            if wi.machine:
                parts.append(f"Machine: {wi.machine}")
            if wi.workers:
                parts.append(f"Workers: {', '.join(wi.workers)}")
            for step in wi.steps:
                parts.append(f"  {step.step_no}. {step.instruction}")
                if step.safety_note:
                    parts.append(f"     Safety: {step.safety_note}")

    elif state.supplier_risk_report:
        r = state.supplier_risk_report
        parts.append(f"\n## Supplier Risk Report\n**Scope:** {r.scope}")
        if r.risks:
            for item in r.risks:
                parts.append(
                    f"- [{item.risk_level.upper()}] {item.supplier} / {item.part} "
                    f"(lead time: {item.lead_time_days}d, reliability: {item.reliability:.0%})"
                )
        if r.recommended_actions:
            parts.append("\n### Recommended Actions")
            for i, a in enumerate(r.recommended_actions, 1):
                parts.append(f"{i}. {a}")

    elif state.line_status_report:
        parts.append("\n## Line Status")
        for ls in state.line_status_report.lines:
            risk_tag = " **AT RISK**" if ls.at_risk else ""
            pct = f" ({ls.pct_complete:.0%})" if ls.pct_complete is not None else ""
            parts.append(f"- **{ls.line_name}** [{ls.status}]{risk_tag}{pct}")
            if ls.current_operation:
                parts.append(f"  Current op: {ls.current_operation}")

    elif state.mermaid:
        parts.append(f"\n## Value Stream Map\n```mermaid\n{state.mermaid}\n```")

    if state.verification:
        v = state.verification
        tag = "PASSED" if v.valid else "ISSUES FOUND"
        parts.append(f"\n---\n**Verification:** {tag}")
        for issue in v.issues:
            parts.append(f"- {issue}")

    return "\n".join(parts)


def node_respond(state: AppState) -> AppState:
    """Format output as a chat message and append to messages."""
    from langchain_core.messages import AIMessage

    text = _format_response(state)
    new_messages = list(state.messages) + [AIMessage(content=text)]
    return state.model_copy(update={"messages": new_messages})


# ═══════════════════════════════════════════════════════════════════════════
# Graph construction
# ═══════════════════════════════════════════════════════════════════════════


def build_graph(db: Neo4jClient) -> StateGraph:
    """Build and compile the LangGraph workflow.

    Topology:
        route → scope → [intent branch]

        capacity_wip:       backbone → fetch_cap_workers → capacity → verify
        work_instructions:  backbone → fetch_instr_parts → fetch_instr_workers → instructions → verify
        supplier_risk:      backbone → fetch_risk_parts → supplier_risk → verify
        vsm:                backbone → vsm_mermaid → verify
        line_status:        fetch_all_lines → line_status → verify

    Note: worker/part fetching nodes are duplicated per path to avoid the
    conflicting-edge problem from v0.1 (same node → multiple unconditional targets).
    """

    g = StateGraph(AppState)

    # --- Shared entry nodes ---
    g.add_node("route", node_route)
    g.add_node("scope", lambda s: node_pick_scope(s, db))
    g.add_node("backbone", lambda s: node_fetch_backbone(s, db))

    # --- Capacity path ---
    g.add_node("fetch_cap_workers", lambda s: node_fetch_workers(s, db))
    g.add_node("capacity", node_capacity)

    # --- Work instructions path ---
    g.add_node("fetch_instr_parts", lambda s: node_fetch_parts(s, db))
    g.add_node("fetch_instr_workers", lambda s: node_fetch_workers(s, db))
    g.add_node("instructions", node_instructions)

    # --- Supplier risk path ---
    g.add_node("fetch_risk_parts", lambda s: node_fetch_parts(s, db))
    g.add_node("supplier_risk", node_supplier_risk)

    # --- VSM path ---
    g.add_node("vsm_mermaid", node_vsm_mermaid)

    # --- Line status path (skips backbone entirely) ---
    g.add_node("fetch_all_lines", lambda s: node_fetch_all_lines(s, db))
    g.add_node("line_status", node_line_status)

    # --- Verifier + responder (shared sink) ---
    g.add_node("verify", node_verify)
    g.add_node("respond", node_respond)

    # ---- Edges: entry ----
    g.set_entry_point("route")
    g.add_edge("route", "scope")

    # ---- Edges: intent branching after scope ----
    def branch_after_scope(state: AppState) -> str:
        """Route to the correct data-fetch path based on intent."""
        match state.intent:
            case "capacity_wip":
                return "backbone"
            case "work_instructions":
                return "backbone"
            case "supplier_risk":
                return "backbone"
            case "vsm":
                return "backbone"
            case "line_status":
                return "fetch_all_lines"
            case _:
                return "backbone"  # safe default

    g.add_conditional_edges(
        "scope",
        branch_after_scope,
        {
            "backbone": "backbone",
            "fetch_all_lines": "fetch_all_lines",
        },
    )

    # ---- Edges: branching after backbone (4 intents share backbone) ----
    def branch_after_backbone(state: AppState) -> str:
        match state.intent:
            case "capacity_wip":
                return "cap_workers"
            case "work_instructions":
                return "instr_parts"
            case "supplier_risk":
                return "risk_parts"
            case "vsm":
                return "vsm"
            case _:
                return "cap_workers"

    g.add_conditional_edges(
        "backbone",
        branch_after_backbone,
        {
            "cap_workers": "fetch_cap_workers",
            "instr_parts": "fetch_instr_parts",
            "risk_parts": "fetch_risk_parts",
            "vsm": "vsm_mermaid",
        },
    )

    # ---- Edges: capacity path ----
    g.add_edge("fetch_cap_workers", "capacity")
    g.add_edge("capacity", "verify")

    # ---- Edges: work instructions path ----
    g.add_edge("fetch_instr_parts", "fetch_instr_workers")
    g.add_edge("fetch_instr_workers", "instructions")
    g.add_edge("instructions", "verify")

    # ---- Edges: supplier risk path ----
    g.add_edge("fetch_risk_parts", "supplier_risk")
    g.add_edge("supplier_risk", "verify")

    # ---- Edges: VSM path ----
    g.add_edge("vsm_mermaid", "verify")

    # ---- Edges: line status path ----
    g.add_edge("fetch_all_lines", "line_status")
    g.add_edge("line_status", "verify")

    # ---- Edges: verify → respond → END ----
    g.add_edge("verify", "respond")
    g.add_edge("respond", END)

    return g.compile()
