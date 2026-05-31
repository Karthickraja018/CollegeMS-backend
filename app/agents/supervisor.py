"""
Supervisor — LangGraph StateGraph that routes user queries to the right agent.
"""
from functools import partial
from langgraph.graph import StateGraph, START, END
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.prompts import SUPERVISOR_PROMPT


async def _classify_intent(state: AgentState) -> dict:
    """Classify the user query and decide which agent to use."""
    llm = get_llm_provider()

    # Guard against infinite loops
    iterations = state.get("iterations", 0)
    if iterations >= 3:
        return {"agent_used": "query", "iterations": iterations + 1}

    query = state.get("user_query", "")
    messages = [{"role": "user", "content": f"Classify this query: {query}"}]

    try:
        response = await llm.generate(
            messages=messages,
            system_prompt=SUPERVISOR_PROMPT,
            temperature=0.0,
        )
        agent = response.strip().lower()
        # Normalise to known agents
        if agent not in ("query", "performance", "visualization", "report"):
            agent = "query"
    except Exception:
        agent = "query"

    return {"agent_used": agent, "iterations": iterations + 1}


def _route_to_agent(state: AgentState) -> str:
    """Conditional edge: return the node name to go to."""
    agent = state.get("agent_used", "query")
    valid_agents = {"query", "performance", "visualization", "report"}
    return agent if agent in valid_agents else "query"


async def _needs_visualization(state: AgentState) -> str:
    """After query agent, decide if we should also run viz agent."""
    query = state.get("user_query", "").lower()
    sql_result = state.get("sql_result", [])

    viz_keywords = {"chart", "graph", "plot", "trend", "visualize", "show me", "compare"}
    wants_viz = any(kw in query for kw in viz_keywords)

    if wants_viz and sql_result:
        return "visualization"
    return END


def build_supervisor_graph(db: AsyncSession) -> StateGraph:
    """Build and compile the supervisor LangGraph."""

    # Import agent nodes
    from app.agents.query_agent import query_agent_node
    from app.agents.performance_agent import performance_agent_node
    from app.agents.visualization_agent import visualization_agent_node
    from app.agents.report_agent import report_agent_node

    # Bind DB session to agent nodes that need it
    query_node = partial(query_agent_node, db=db)
    performance_node = partial(performance_agent_node, db=db)
    report_node = partial(report_agent_node, db=db)

    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("classify", _classify_intent)
    graph.add_node("query", query_node)
    graph.add_node("performance", performance_node)
    graph.add_node("visualization", visualization_agent_node)
    graph.add_node("report", report_node)

    # Edges
    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        _route_to_agent,
        {
            "query": "query",
            "performance": "performance",
            "visualization": "query",  # Viz always runs after query to get data
            "report": "report",
        },
    )

    # After query, check if visualization is also needed
    graph.add_conditional_edges(
        "query",
        _needs_visualization,
        {"visualization": "visualization", END: END},
    )

    # Terminal nodes
    graph.add_edge("performance", END)
    graph.add_edge("visualization", END)
    graph.add_edge("report", END)

    return graph.compile()
