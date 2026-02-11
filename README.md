# BOM360 Multi-Agent System v0.2

Multi-agent manufacturing execution system built with **LangGraph** + **PydanticAI** + **Neo4j**.

## Architecture

```
User Goal
    │
    ▼
┌─────────┐     ┌─────────┐
│  Router  │────▶│  Scope  │
└─────────┘     └────┬────┘
                     │
         ┌───────────┼───────────┬──────────────┐
         ▼           ▼           ▼              ▼
    ┌──────────┐ ┌────────┐ ┌────────┐  ┌─────────────┐
    │ Backbone │ │Backbone│ │Backbone│  │FetchAllLines│
    └────┬─────┘ └───┬────┘ └───┬────┘  └──────┬──────┘
         │           │          │               │
    ┌────▼────┐ ┌────▼───┐ ┌───▼────┐   ┌──────▼──────┐
    │ Workers │ │ Parts  │ │ Parts  │   │ LineStatus  │
    └────┬────┘ └───┬────┘ └───┬────┘   └──────┬──────┘
         │          │          │                │
    ┌────▼────┐ ┌───▼─────┐   │                │
    │Capacity │ │ Workers │   │                │
    └────┬────┘ └───┬─────┘   │                │
         │     ┌────▼──────┐  │                │
         │     │Instructions│  │                │
         │     └────┬──────┘  │                │
         │          │    ┌────▼────────┐       │
         │          │    │SupplierRisk │       │
         │          │    └────┬────────┘       │
         ▼          ▼         ▼                ▼
    ┌────────────────────────────────────────────┐
    │               Verifier                     │
    └────────────────────────────────────────────┘
```

## Key design decisions (v0.2 vs v0.1)

| Issue in v0.1 | Fix in v0.2 |
|---|---|
| MCP Text→Cypher adds latency + hallucination risk for 47-node graph | Direct Neo4j driver with parameterized Cypher templates |
| Conflicting unconditional edges from `workers` node | Separate fetch nodes per path (`fetch_cap_workers`, `fetch_instr_workers`) |
| `supplier_risk` and `line_status` intents silently fall through | All 5 intents explicitly routed with `match` statements |
| No Verifier agent (despite being in design doc) | Verifier node validates every output against source query results |
| State mutated in place | Immutable updates via `model_copy(update={...})` |
| PydanticAI agents receive raw dicts | Structured text payloads with section headers |
| No error handling | Try/except in client + graceful CLI error messages |

## Setup (Windows / VSCode)

```powershell
# 1. Clone or copy this folder
cd bom360-agents

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -e .

# 4. Configure environment
copy .env.example .env
# Edit .env with your Neo4j credentials and API key

# 5. Run
python -m src.app
# Or with a goal directly:
python -m src.app "Show me capacity risks for the most urgent job"
```

## Intents

| Intent | What it does | Data fetched |
|---|---|---|
| `line_status` | Quick summary of all production lines | All lines + jobs + products |
| `capacity_wip` | Bottleneck detection, staffing gaps, due-date risk | Backbone + workers + skills |
| `work_instructions` | Step-by-step shop floor instructions per operation | Backbone + parts + workers |
| `supplier_risk` | Material lead-time and reliability analysis | Backbone + parts + suppliers |
| `vsm` | Value stream map as Mermaid diagram | Backbone (operation chain) |

## Adding new Cypher queries

All queries live in `src/cypher_templates.py` as functions returning `(cypher, params)` tuples.
To add a new query:

1. Add a function to `cypher_templates.py`
2. Call it from a new or existing node in `workflows.py`
3. The result is automatically wrapped in `QueryResult` for audit

## Extending to Text→Cypher (future)

When the graph grows beyond ~200 node types or users need ad-hoc questions,
add a Text→Cypher fallback alongside the template registry:

```python
def run_query(self, intent: str, question: str) -> QueryResult:
    template = self.registry.get(intent)
    if template:
        return self.db.run(*template)
    else:
        cypher = self.text2cypher_llm(question)  # LLM fallback
        return self.db.run(cypher)
```
