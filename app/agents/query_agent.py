"""
Query Agent V2 — Reasoning-first SQL pipeline.

Pipeline:
  Question → Intent Understanding → Query Planning → SQL Generation
  → SQL Validation → Execution → Retry (up to 3x) → Insight Generation → Response

The agent behaves like an experienced data analyst: it plans before it queries,
validates before it executes, and explains results in plain language.
"""
from __future__ import annotations

import re
import json
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.utils.sql_validator import validate_sql, SQLValidationError
from langchain_core.callbacks.manager import adispatch_custom_event
from app.prompts import (
    QUERY_SYSTEM_PROMPT_V2,
    INSIGHT_GENERATION_PROMPT,
)
import time

from app.agents.nlp_sql_mcp.tools.db_tools import (
    tool_search_schema,
    tool_sample_values,
    tool_execute_sql
)

MAX_RETRIES = 3


def _strip_thinking(text: str) -> str:
    """Remove <thinking> / <thought> blocks from model output."""
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _extract_sql(llm_response: str) -> str:
    """
    Extract SQL from LLM response. Handles:
    - ```sql ... ``` blocks
    - ``` ... ``` blocks (no language tag)
    - Raw SELECT statements
    """
    clean = _strip_thinking(llm_response)

    # Try ```sql ... ``` first
    match = re.search(r"```sql\s*(.*?)\s*```", clean, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Try ``` ... ``` with SELECT inside
    match = re.search(r"```\s*(SELECT.*?)\s*```", clean, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Find any SELECT statement (multi-line)
    match = re.search(r"(SELECT\s+.+?)(?:;|\Z)", clean, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    raise ValueError("Could not extract a valid SQL SELECT statement from the response.")





def _extract_insight_json(text: str) -> Optional[dict]:
    """Extract JSON insight object from LLM response."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


async def _generate_sql(
    llm,
    query: str,
    intent: dict,
    schema_context: str,
    sample_values_result: str,
    previous_error: Optional[str] = None,
) -> str:
    """
    Generate SQL based on the intent, schema, and samples.
    """
    enriched_query = intent.get("enriched_query", query)
    role = "college user"

    correction_note = ""
    if previous_error:
        correction_note = (
            f"\n\nPREVIOUS SQL FAILED with this error:\n{previous_error}\n"
            "Fix the SQL to resolve this error."
        )

    entities = intent.get("entities", {})
    query_type = intent.get("query_type", "descriptive")

    trend_instruction = ""
    if query_type == "trend":
        trend_instruction = "\nCRITICAL: This is a trend query. You MUST aggregate the data over time (e.g. GROUP BY month/year) rather than returning raw individual rows. Return the aggregated metric (e.g. AVG(attendance)) alongside the time dimension."

    sql_request = (
        f"You are a PostgreSQL expert.\n"
        f"User Role: {role}\n"
        f"Relevant Schema:\n{schema_context}\n"
        f"Known Values:\n{sample_values_result}\n\n"
        f"Question: \"{enriched_query}\"\n"
        f"Query type: {query_type}\n"
        f"Departments: {entities.get('departments', [])}\n"
        f"Metrics needed: {entities.get('metrics', [])}\n"
        f"Time filter: {entities.get('time', 'none')}\n"
        f"{trend_instruction}\n"
        f"{correction_note}\n"
        "Generate a single read-only PostgreSQL SELECT query.\n"
        "Return SQL only."
    )

    messages = [{"role": "user", "content": sql_request}]
    response = await llm.generate(
        messages=messages,
        system_prompt=QUERY_SYSTEM_PROMPT_V2,
        temperature=0.05,
        model_name="llama-3.3-70b-versatile"
    )
    return _extract_sql(response)


async def _generate_insights(
    llm,
    query: str,
    data: list[dict],
    intent: dict,
) -> dict:
    """
    Step 3 (post-execution): Generate insights from the results.
    Returns {"summary": str, "insights": [...], "recommendations": [...]}
    """
    if not data:
        return {
            "summary": "No records were found matching your query.",
            "insights": [],
            "recommendations": ["Try broadening your search criteria or check if data has been uploaded for this period."],
        }

    data_preview = data[:60]
    query_type = intent.get("query_type", "descriptive")
    entities = intent.get("entities", {})

    insight_request = (
        f"Summarize results.\n"
        f"Provide:\n"
        f"* Key findings\n"
        f"* Trends\n"
        f"* Notable observations\n\n"
        f"Maximum 150 words.\n\n"
        f"User asked: \"{query}\"\n"
        f"Results ({len(data)} total rows, showing {len(data_preview)}):\n"
        f"{json.dumps(data_preview, indent=2, default=str)}"
    )

    messages = [{"role": "user", "content": insight_request}]
    try:
        insight_text = await llm.generate(
            messages=messages,
            system_prompt="You are a data analyst.",
            temperature=0.3,
            model_name="gemma2-9b-it"
        )
        insight_text = _strip_thinking(insight_text)
        result = _extract_insight_json(insight_text)
        if result:
            return result
    except Exception:
        pass

    # Fallback
    return {
        "summary": f"Found {len(data)} records matching your query.",
        "insights": [f"Query returned {len(data)} records."],
        "recommendations": [],
    }


async def _execute_sql(db: AsyncSession, sql: str) -> tuple[list[dict], Optional[str]]:
    """
    Execute SQL and return (results, error_message).
    Returns (data, None) on success or ([], error_string) on failure.
    """
    try:
        result = await db.execute(text(sql))
        rows = result.fetchall()
        columns = list(result.keys())
        return [dict(zip(columns, row)) for row in rows], None
    except Exception as e:
        await db.rollback()
        return [], str(e)


async def query_agent_node(state: AgentState, db: AsyncSession) -> dict:
    """
    LangGraph node: Query Agent V2 optimized.
    MCP tools integration, no planning layer.
    """
    start_time = time.time()
    timing_metrics = state.get("timing_metrics", {})
    
    llm = get_llm_provider()
    query = state.get("user_query", "")
    intent = state.get("intent", {})

    effective_query = intent.get("enriched_query", query) or query
    entities = intent.get("entities", {})

    await adispatch_custom_event("status_update", {"status": "Discovering Schema"})

    # ── Step 1: Schema Lookup ────────────────────────────────────────────────
    t0 = time.time()
    schema_context = tool_search_schema(effective_query)
    timing_metrics["schema_lookup_time"] = round(time.time() - t0, 2)

    # ── Step 2: Sample Values ────────────────────────────────────────────────
    sample_values_res = {}
    if entities.get("departments"):
        dept_samples = await tool_sample_values("departments", "code", limit=10)
        sample_values_res["departments"] = json.loads(dept_samples).get("values", [])
    sample_values_result = json.dumps(sample_values_res)

    # ── Step 3-5: SQL Generation, Validation, Execution (with retries) ───────
    sql_result: list[dict] = []
    last_error: Optional[str] = None
    final_sql: Optional[str] = None
    
    gen_time_total = 0.0
    val_time_total = 0.0
    exec_time_total = 0.0

    for attempt in range(MAX_RETRIES):
        # Generate SQL
        await adispatch_custom_event("status_update", {"status": "Generating SQL"})
        t0 = time.time()
        try:
            raw_sql = await _generate_sql(
                llm,
                effective_query,
                intent,
                schema_context,
                sample_values_result,
                previous_error=last_error if attempt > 0 else None,
            )
        except ValueError as e:
            last_error = str(e)
            gen_time_total += time.time() - t0
            if attempt == MAX_RETRIES - 1:
                timing_metrics["sql_generation_time"] = round(gen_time_total, 2)
                return _error_response(state, "query", str(e), timing_metrics)
            continue
        except Exception as e:
            last_error = f"LLM generation failed: {str(e)}"
            gen_time_total += time.time() - t0
            if attempt == MAX_RETRIES - 1:
                timing_metrics["sql_generation_time"] = round(gen_time_total, 2)
                return _error_response(state, "query", last_error, timing_metrics)
            continue
        gen_time_total += time.time() - t0

        # Validate SQL
        t0 = time.time()
        try:
            safe_sql = validate_sql(raw_sql)
            val_time_total += time.time() - t0
        except SQLValidationError as e:
            last_error = f"SQL safety validation failed: {str(e)}"
            val_time_total += time.time() - t0
            if attempt == MAX_RETRIES - 1:
                timing_metrics["validation_time"] = round(val_time_total, 2)
                return _error_response(state, "query", last_error, timing_metrics)
            continue

        # Execute against DB using MCP tool
        await adispatch_custom_event("status_update", {"status": "Executing Query"})
        t0 = time.time()
        exec_json = await tool_execute_sql(safe_sql, {})
        exec_res = json.loads(exec_json)
        exec_time_total += time.time() - t0
        
        if exec_res.get("error"):
            last_error = f"Database execution error: {exec_res.get('message')}"
            if attempt == MAX_RETRIES - 1:
                timing_metrics["execution_time"] = round(exec_time_total, 2)
                return _error_response(state, "query", last_error, timing_metrics)
            continue

        # Success!
        columns = exec_res.get("columns", [])
        rows = exec_res.get("rows", [])
        sql_result = [dict(zip(columns, row)) for row in rows]
        final_sql = safe_sql
        last_error = None
        break
        
    timing_metrics["sql_generation_time"] = round(gen_time_total, 2)
    timing_metrics["validation_time"] = round(val_time_total, 2)
    timing_metrics["execution_time"] = round(exec_time_total, 2)

    # ── Step 6: Generate Insights ────────────────────────────────────────────
    await adispatch_custom_event("status_update", {"status": "Generating Insights"})
    t0 = time.time()
    insight_data = await _generate_insights(llm, effective_query, sql_result, intent)
    timing_metrics["insight_time"] = round(time.time() - t0, 2)

    summary = insight_data.get("summary", "")
    insights = insight_data.get("insights", [])
    recommendations = insight_data.get("recommendations", [])

    if summary:
        final_response = summary
    elif sql_result:
        final_response = f"Found {len(sql_result)} records matching your query."
    else:
        final_response = "No records were found matching your query."
        
    timing_metrics["total_time"] = round(time.time() - start_time, 2)

    return {
        "agent_used": "query",
        "query_plan": [],
        "sql_result": sql_result,
        "sql_query": final_sql,
        "insights": insights,
        "recommendations": recommendations,
        "final_response": final_response,
        "error": None,
        "timing_metrics": timing_metrics,
    }


def _error_response(state: AgentState, agent: str, error: str, timing_metrics: dict) -> dict:
    return {
        "agent_used": agent,
        "query_plan": [],
        "sql_result": [],
        "insights": [],
        "recommendations": [],
        "error": error,
        "final_response": f"Encountered an error: {error}",
        "timing_metrics": timing_metrics,
    }
