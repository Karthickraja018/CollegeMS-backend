"""
Shared LangGraph state for all agents in the supervisor graph.
V2: Adds intent, query planning, analytics, memory, and structured response.
V2.1: Adds role-scoped context for row-level access control.
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
    intent: dict

    # ── Query plan (created by Query Agent before SQL generation) ──────────
    query_plan: list[str]

    # ── Which agents were invoked this turn ────────────────────────────────
    agent_used: str
    agent_pipeline: list[str]

    # ── Structured results from agents ─────────────────────────────────────
    sql_result: list[dict]
    analytics_result: Optional[dict]
    chart_spec: Optional[dict]
    report_url: Optional[str]
    risk_analysis: Optional[dict]

    # ── Composed response fields ────────────────────────────────────────────
    final_response: str
    insights: list[str]
    recommendations: list[str]

    # ── Error state ─────────────────────────────────────────────────────────
    error: Optional[str]

    # ── Loop guard ──────────────────────────────────────────────────────────
    iterations: int

    # ── Role-Scoped Context (V2.1) ───────────────────────────────────────────
    # These fields are injected by the chat endpoint from the authenticated user.
    # All agents MUST append these SQL clauses to their queries.
    #
    # user_role: "admin" | "college_admin" | "principal" | "hod" | "faculty"
    # user_department_id: department ID for HOD/faculty, None for admin/principal
    # is_institution_wide: True if user can see all departments
    # student_filter: "all" | "department" | "assigned"
    # dept_filter_sql: SQL fragment like "AND s.department_id = 3"
    # student_filter_sql: SQL fragment for faculty-scoped student filtering
    user_role: Optional[str]
    user_department_id: Optional[int]
    is_institution_wide: Optional[bool]
    student_filter: Optional[str]
    dept_filter_sql: Optional[str]
    student_filter_sql: Optional[str]
