"""
Shared LangGraph state for all agents in the supervisor graph.
"""
from typing import Annotated, TypedDict
from langgraph.graph import add_messages


class AgentState(TypedDict):
    # Chat history (appends via reducer)
    messages: Annotated[list, add_messages]

    # User's original query
    user_query: str

    # Which agent was selected by the supervisor
    agent_used: str  # "query" | "performance" | "visualization" | "report" | "unknown"

    # Structured results from agents
    sql_result: list[dict]          # Raw tabular data from Query Agent
    chart_spec: dict | None         # Recharts-compatible JSON from Visualization Agent
    report_url: str | None          # Download URL from Report Agent
    risk_analysis: dict | None      # At-risk data from Performance Agent

    # Final formatted response for the user
    final_response: str

    # Error state
    error: str | None

    # Loop guard
    iterations: int
