"""Parameterized Cypher templates for all BOM360 data-fetching patterns.

Each function returns (cypher, params) tuples that go through Neo4jClient.run().
This is intentionally explicit: every query the agents can issue is visible,
testable, and version-controlled — no LLM-generated Cypher that might hallucinate
non-existent properties.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------


def most_urgent_lines(limit: int = 5) -> tuple[str, dict]:
    """Production lines ordered by soonest due date."""
    return (
        """
        MATCH (pl:ProductionLine)-[:CURRENT_JOB]->(j:Job)-[:FOR_PRODUCT]->(p:Product)
        RETURN pl.line_id   AS line_id,
               pl.name      AS line_name,
               pl.status    AS line_status,
               j.job_id     AS job_id,
               j.status     AS job_status,
               j.due_date   AS due_date,
               j.due_dt     AS due_dt,
               j.qty_planned   AS qty_planned,
               j.qty_completed AS qty_completed,
               p.name AS product_name,
               p.sku  AS product_sku
        ORDER BY j.due_dt ASC
        LIMIT $limit
        """,
        {"limit": limit},
    )


# ---------------------------------------------------------------------------
# Operation backbone (ordered chain for a line + job)
# ---------------------------------------------------------------------------


def operation_backbone(line_id: str, job_id: str) -> tuple[str, dict]:
    """Ordered operation chain via HAS_FIRST_OPERATION → NEXT_OPERATION traversal."""
    return (
        """
        MATCH (pl:ProductionLine {line_id: $line_id})-[:HAS_FIRST_OPERATION]->(first:Operation)
        WHERE first.job_id = $job_id OR EXISTS {
            MATCH (first)-[:FOR_JOB]->(j:Job {job_id: $job_id})
        }
        MATCH path = (first)-[:NEXT_OPERATION*0..20]->(op)
        WITH op, length(
            shortestPath((first)-[:NEXT_OPERATION*0..20]->(op))
        ) AS chain_pos
        OPTIONAL MATCH (m:Machine)-[:EXECUTES]->(op)
        OPTIONAL MATCH (op)-[:REQUIRES_MACHINE_TYPE]->(mt:MachineType)
        RETURN op.op_id          AS op_id,
               op.name           AS op_name,
               op.sequence_no    AS sequence_no,
               op.status         AS status,
               op.std_duration_min  AS std_duration_min,
               op.setup_duration_min AS setup_duration_min,
               op.planned_start  AS planned_start,
               op.planned_end    AS planned_end,
               op.current_wip    AS current_wip,
               op.current_due_dt AS current_due_dt,
               m.machine_id      AS machine_id,
               m.name            AS machine_name,
               m.status          AS machine_status,
               mt.name           AS machine_type,
               mt.type_code      AS machine_type_code
        ORDER BY op.sequence_no ASC
        """,
        {"line_id": line_id, "job_id": job_id},
    )


# ---------------------------------------------------------------------------
# Parts & suppliers for a line/job
# ---------------------------------------------------------------------------


def parts_and_suppliers(line_id: str, job_id: str) -> tuple[str, dict]:
    """Parts consumed by operations on a line/job, with supplier info."""
    return (
        """
        MATCH (pl:ProductionLine {line_id: $line_id})-[:HAS_OPERATION]->(op:Operation)
        WHERE op.job_id = $job_id OR EXISTS {
            MATCH (op)-[:FOR_JOB]->(j:Job {job_id: $job_id})
        }
        MATCH (op)-[:CONSUMES]->(pt:Part)
        OPTIONAL MATCH (sup:Supplier)-[:SUPPLIES]->(pt)
        RETURN op.op_id          AS op_id,
               op.name           AS op_name,
               op.sequence_no    AS sequence_no,
               pt.part_id        AS part_id,
               pt.name           AS part_name,
               pt.category       AS part_category,
               pt.uom            AS part_uom,
               sup.supplier_id   AS supplier_id,
               sup.name          AS supplier_name,
               sup.country       AS supplier_country,
               sup.default_lead_time_days AS lead_time_days,
               sup.reliability_score      AS reliability_score
        ORDER BY op.sequence_no ASC, sup.reliability_score DESC
        """,
        {"line_id": line_id, "job_id": job_id},
    )


# ---------------------------------------------------------------------------
# Workers assigned to machines on a line/job
# ---------------------------------------------------------------------------


def workers_for_line(line_id: str, job_id: str) -> tuple[str, dict]:
    """Workers assigned to machines that execute operations on this line/job."""
    return (
        """
        MATCH (pl:ProductionLine {line_id: $line_id})-[:HAS_OPERATION]->(op:Operation)
        WHERE op.job_id = $job_id OR EXISTS {
            MATCH (op)-[:FOR_JOB]->(j:Job {job_id: $job_id})
        }
        MATCH (m:Machine)-[:EXECUTES]->(op)
        OPTIONAL MATCH (w:Worker)-[:ASSIGNED_TO]->(m)
        OPTIONAL MATCH (w)-[:HAS_SKILL]->(sk:Skill)
        WITH op, m, w, collect(DISTINCT sk.name) AS skills
        RETURN op.op_id       AS op_id,
               op.name        AS op_name,
               op.sequence_no AS sequence_no,
               m.machine_id   AS machine_id,
               m.name         AS machine_name,
               w.worker_id    AS worker_id,
               w.full_name    AS worker_name,
               w.role         AS worker_role,
               w.status       AS worker_status,
               skills
        ORDER BY op.sequence_no ASC
        """,
        {"line_id": line_id, "job_id": job_id},
    )


def supervisors_for_line(line_id: str) -> tuple[str, dict]:
    """Supervisors assigned to a production line."""
    return (
        """
        MATCH (w:Worker)-[:SUPERVISES]->(pl:ProductionLine {line_id: $line_id})
        OPTIONAL MATCH (w)-[:HAS_SKILL]->(sk:Skill)
        RETURN w.worker_id  AS worker_id,
               w.full_name  AS worker_name,
               w.role       AS worker_role,
               collect(DISTINCT sk.name) AS skills
        """,
        {"line_id": line_id},
    )


# ---------------------------------------------------------------------------
# Skill coverage analysis
# ---------------------------------------------------------------------------


def skill_coverage(line_id: str) -> tuple[str, dict]:
    """Required machine types per operation vs worker skills on the line."""
    return (
        """
        MATCH (pl:ProductionLine {line_id: $line_id})-[:HAS_OPERATION]->(op:Operation)
        MATCH (op)-[:REQUIRES_MACHINE_TYPE]->(mt:MachineType)
        OPTIONAL MATCH (m:Machine)-[:EXECUTES]->(op)
        OPTIONAL MATCH (w:Worker)-[:ASSIGNED_TO]->(m)
        OPTIONAL MATCH (w)-[:HAS_SKILL]->(sk:Skill)
        RETURN op.op_id          AS op_id,
               op.name           AS op_name,
               op.sequence_no    AS sequence_no,
               mt.type_code      AS required_type,
               mt.name           AS required_type_name,
               m.machine_id      AS machine_id,
               w.worker_id       AS worker_id,
               w.full_name       AS worker_name,
               collect(DISTINCT sk.name) AS worker_skills
        ORDER BY sequence_no ASC
        """,
        {"line_id": line_id},
    )


# ---------------------------------------------------------------------------
# All lines quick status (for line_status intent)
# ---------------------------------------------------------------------------


def all_lines_status() -> tuple[str, dict]:
    """Quick status for every production line."""
    return (
        """
        MATCH (pl:ProductionLine)
        OPTIONAL MATCH (pl)-[:CURRENT_JOB]->(j:Job)-[:FOR_PRODUCT]->(p:Product)
        OPTIONAL MATCH (pl)-[:HAS_OPERATION]->(running_op:Operation)
            WHERE running_op.status = 'RUNNING'
        RETURN pl.line_id         AS line_id,
               pl.name            AS line_name,
               pl.status          AS line_status,
               j.job_id           AS job_id,
               j.status           AS job_status,
               j.due_date         AS due_date,
               j.due_dt           AS due_dt,
               j.qty_planned      AS qty_planned,
               j.qty_completed    AS qty_completed,
               p.name             AS product_name,
               collect(DISTINCT running_op.name) AS running_operations
        ORDER BY due_dt ASC
        """,
        {},
    )
