"""
Shared LangGraph state for all agents in the supervisor graph.
V2: Adds intent, query planning, analytics, memory, and structured response.
"""
from typing import Annotated, TypedDict, Optional
from langgraph.graph import add_messages


class AgentState(TypedDict):
    # ── Chat history (appends via reducer) ─────────────────────────────────
    messages: Annotated[list, add_messages]

    # ── User's original query ───────────────────────────────────────────────
    user_query: str

    # ── Memory context from prior turns ────────────────────────────────────
    # Resolved entity references: {"last_department": "CSE", "last_metric": "attendance"}
    memory_context: dict

    # ── Structured intent from supervisor ──────────────────────────────────
    # {
    #   "query_type": "descriptive|comparative|trend|ranking|analytical|predictive|report|visualization",
    #   "entities": {"departments": [], "metrics": [], "time": "", "students": []},
    #   "needs_visualization": bool,
    #   "needs_report": bool,
    #   "needs_analytics": bool,
    #   "agent_pipeline": ["query", "analytics", "visualization"],
    #   "complexity": "simple|multi_step",
    #   "enriched_query": str   # query after semantic resolution
    # }
    intent: dict

    # ── Query plan (created by Query Agent before SQL generation) ──────────
    # ["Step 1: Get attendance for CSE", "Step 2: Get attendance for ECE", ...]
    query_plan: list[str]

    # ── Which agents were invoked this turn ────────────────────────────────
    agent_used: str          # Primary agent label for UI badge
    agent_pipeline: list[str]  # All agents used in this turn

    # ── Structured results from agents ─────────────────────────────────────
    sql_result: list[dict]           # Raw tabular data from Query Agent
    analytics_result: Optional[dict] # KPIs, comparisons, trends from Analytics Agent
    chart_spec: Optional[dict]       # Recharts-compatible JSON from Visualization Agent
    report_url: Optional[str]        # Download URL from Report Agent
    risk_analysis: Optional[dict]    # At-risk data from Performance Agent

    # ── Composed response fields ────────────────────────────────────────────
    # Final narrative response for the user
    final_response: str
    # AI-generated bullet insights (e.g., ["CSE has 12% lower attendance than ECE"])
    insights: list[str]
    # Actionable recommendations (e.g., ["Schedule intervention for 14 at-risk students"])
    recommendations: list[str]

    # ── Error state ─────────────────────────────────────────────────────────
    error: Optional[str]

    # ── Loop guard ──────────────────────────────────────────────────────────
    iterations: int
