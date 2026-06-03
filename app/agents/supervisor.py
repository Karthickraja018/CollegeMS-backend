"""
Supervisor Agent V2 — Master orchestration with intent routing and multi-agent pipelines.

Responsibilities:
1. Memory: Resolve entity references from conversation history ("it" = CSE)
2. Semantic enrichment: Apply college terminology → DB concept mapping
3. Intent classification: Structured JSON intent with agent pipeline decision
4. Multi-agent orchestration: Run agents in sequence, collect all outputs
5. Response composition: Merge all agent outputs into a unified response

Architecture:
  classify_intent → route → [agent pipeline] → compose_response
"""
from __future__ import annotations

import json
import re
import time
from functools import partial

from langgraph.graph import StateGraph, START, END
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.callbacks.manager import adispatch_custom_event

from app.agents.state import AgentState
from app.agents.semantic_layer import semantic_layer
from app.llm.provider_factory import get_llm_provider
from app.prompts import SUPERVISOR_PROMPT_V2


def _strip_thinking(text: str) -> str:
    """Remove <thinking> / <thought> blocks from model output."""
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _extract_intent_json(response: str) -> dict:
    """
    Robustly extract the intent JSON from supervisor LLM response.
    Falls back to a safe default if parsing fails.
    """
    clean = _strip_thinking(response)

    # Remove markdown fences
    clean = re.sub(r"```(?:json)?\s*", "", clean)
    clean = re.sub(r"```", "", clean)

    # Find first JSON object
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Return safe default
    return {
        "query_type": "descriptive",
        "entities": {"departments": [], "metrics": [], "time": None, "students": [], "subjects": []},
        "needs_visualization": False,
        "needs_report": False,
        "needs_analytics": False,
        "needs_performance": False,
        "agent_pipeline": ["query"],
        "complexity": "simple",
        "enriched_query": "",
        "primary_agent": "query",
    }


def _extract_memory_context(conversation_history: list) -> dict:
    """
    Scan recent conversation messages to build memory context.
    Extracts last referenced departments, metrics, student groups, subjects.
    """
    memory: dict = {}

    # conversation_history items can be (role, content) tuples or {"role": ..., "content": ...} dicts
    for msg in conversation_history[-10:]:
        if isinstance(msg, (list, tuple)):
            role, content = msg[0], msg[1]
        elif isinstance(msg, dict):
            role = msg.get("role", "")
            content = msg.get("content", "")
        else:
            continue

        if role != "user":
            continue

        content_str = str(content)

        # Extract departments from past user messages
        departments = semantic_layer.extract_departments(content_str)
        if departments:
            memory["last_department"] = departments[0]
            memory["last_departments"] = departments

        # Extract metrics from past user messages
        metrics = semantic_layer.extract_metrics(content_str)
        if metrics:
            memory["last_metric"] = metrics[0]

    return memory


async def _classify_intent(state: AgentState) -> dict:
    """
    Classify user intent using Rule-Based Routing + LLM Fallback.
    """
    await adispatch_custom_event("status_update", {"status": "Understanding Question"})
    start_time = time.time()
    llm = get_llm_provider()
    iterations = state.get("iterations", 0)

    # Initialize timing metrics if not exists
    timing_metrics = state.get("timing_metrics", {})

    # Guard against infinite loops
    if iterations >= 4:
        timing_metrics["supervisor_time"] = time.time() - start_time
        return {
            "intent": {"agent_pipeline": ["query"], "primary_agent": "query", "enriched_query": state.get("user_query", "")},
            "agent_used": "query",
            "agent_pipeline": ["query"],
            "iterations": iterations + 1,
            "timing_metrics": timing_metrics,
        }

    query = state.get("user_query", "")
    query_lower = query.lower()
    messages_history = state.get("messages", [])
    memory_context = state.get("memory_context", {})

    # ── Build memory from conversation history ──────────────────────────────
    if messages_history:
        memory_context = _extract_memory_context(messages_history)

    # ── Semantic enrichment (fast, no LLM needed) ───────────────────────────
    enrichment = semantic_layer.enrich_query(query, memory_context)
    enriched_query = enrichment["enriched_query"] or query

    # ── Rule-Based Routing ─────────────────────────────────────────────────
    route = None
    pipeline = ["query"]

    if any(word in query_lower for word in ["compare", "difference", "higher", "lower", "better", "worse"]):
        route = "analytics"
        pipeline = ["query", "analytics"]
    elif any(word in query_lower for word in ["risk", "dropout", "arrears", "fail", "critical"]):
        route = "performance"
        pipeline = ["performance"]
    elif any(word in query_lower for word in ["report", "summary", "pdf", "naac"]):
        route = "report"
        pipeline = ["report"]
    
    intent = {
        "query_type": enrichment["query_type"],
        "entities": {
            "departments": enrichment["departments"],
            "metrics": enrichment["metrics"],
            "time": enrichment["time_reference"],
            "students": [],
            "subjects": [],
        },
        "needs_visualization": False,
        "needs_report": route == "report",
        "needs_analytics": route == "analytics",
        "needs_performance": route == "performance",
        "agent_pipeline": pipeline,
        "complexity": "multi_step" if len(pipeline) > 1 else "simple",
        "enriched_query": enriched_query,
        "primary_agent": route if route else "query",
    }

    # ── LLM Fallback Classification if NO rule matches ─────────────────────
    if not route:
        context_note = ""
        if memory_context.get("last_department"):
            context_note = f"\n[Memory context: user previously asked about {memory_context['last_department']}]"

        classification_request = (
            f"Classify this query and return a JSON intent:{context_note}\n\n"
            f"Original query: \"{query}\"\n"
            f"Enriched query: \"{enriched_query}\"\n"
        )
        messages = [{"role": "user", "content": classification_request}]

        try:
            response = await llm.generate(
                messages=messages,
                system_prompt=SUPERVISOR_PROMPT_V2,
                temperature=0.0,
                model_name="llama-3.1-8b-instant"
            )
            llm_intent = _extract_intent_json(response)
            
            # Merge fallback results into intent
            valid_agents = {"query", "analytics", "performance", "report"}
            llm_pipeline = [a for a in llm_intent.get("agent_pipeline", ["query"]) if a in valid_agents]
            if not llm_pipeline:
                llm_pipeline = ["query"]
                
            intent["agent_pipeline"] = llm_pipeline
            intent["primary_agent"] = llm_pipeline[0]
            intent["query_type"] = llm_intent.get("query_type", intent["query_type"])
            pipeline = llm_pipeline
            
        except Exception:
            # If fallback LLM fails, default to query
            intent["agent_pipeline"] = ["query"]
            intent["primary_agent"] = "query"
            pipeline = ["query"]

    timing_metrics["supervisor_time"] = round(time.time() - start_time, 2)

    return {
        "intent": intent,
        "memory_context": memory_context,
        "agent_used": intent["primary_agent"],
        "agent_pipeline": pipeline,
        "iterations": iterations + 1,
        "insights": [],
        "recommendations": [],
        "query_plan": [],
        "timing_metrics": timing_metrics,
    }


def _route_from_classify(state: AgentState) -> str:
    """
    Route to first agent in the pipeline after intent classification.
    """
    pipeline = state.get("agent_pipeline", ["query"])
    return pipeline[0] if pipeline else "query"


def _route_after_query(state: AgentState) -> str:
    """
    After query agent: decide if analytics should follow.
    """
    pipeline = state.get("agent_pipeline", ["query"])
    intent = state.get("intent", {})
    sql_result = state.get("sql_result", [])

    # If no data retrieved, skip downstream agents
    if not sql_result:
        return END

    # Check what's next after "query" in pipeline
    try:
        query_idx = pipeline.index("query")
        next_agent = pipeline[query_idx + 1] if query_idx + 1 < len(pipeline) else None
    except ValueError:
        next_agent = None

    if next_agent in ("analytics",):
        return next_agent

    return END


def _route_after_analytics(state: AgentState) -> str:
    """After analytics: END."""
    return END


def build_supervisor_graph(db: AsyncSession) -> StateGraph:
    """
    Build and compile the V2 supervisor LangGraph.
    Supports sequential multi-agent pipelines.
    """
    # Import agent nodes
    from app.agents.query_agent import query_agent_node
    from app.agents.analytics_agent import analytics_agent_node
    from app.agents.performance_agent import performance_agent_node
    from app.agents.report_agent import report_agent_node

    # Bind DB session to agents that need it
    query_node = partial(query_agent_node, db=db)
    performance_node = partial(performance_agent_node, db=db)
    report_node = partial(report_agent_node, db=db)

    graph = StateGraph(AgentState)

    # ── Nodes ───────────────────────────────────────────────────────────────
    graph.add_node("classify", _classify_intent)
    graph.add_node("query", query_node)
    graph.add_node("analytics", analytics_agent_node)
    graph.add_node("performance", performance_node)
    graph.add_node("report", report_node)

    # ── Edges ───────────────────────────────────────────────────────────────
    graph.add_edge(START, "classify")

    # classify → first agent in pipeline
    graph.add_conditional_edges(
        "classify",
        _route_from_classify,
        {
            "query": "query",
            "analytics": "analytics",
            "performance": "performance",
            "report": "report",
        },
    )

    # query → analytics | END
    graph.add_conditional_edges(
        "query",
        _route_after_query,
        {
            "analytics": "analytics",
            END: END,
        },
    )

    # analytics → END
    graph.add_conditional_edges(
        "analytics",
        _route_after_analytics,
        {
            END: END,
        },
    )

    # Terminal nodes
    graph.add_edge("performance", END)
    graph.add_edge("report", END)

    return graph.compile()
