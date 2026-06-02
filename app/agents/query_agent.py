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
import time
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.utils.sql_validator import validate_sql, SQLValidationError
from app.intelligence.agent_context_bus import get_context_bus
from app.intelligence.sql_context_validator import SQLContextValidator
from app.prompts import (
    QUERY_SYSTEM_PROMPT_V2,
    QUERY_PLANNER_PROMPT,
    INSIGHT_GENERATION_PROMPT,
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


def _extract_plan_steps(plan_text: str) -> list[str]:
    """Parse numbered plan steps from LLM planning response."""
    steps = []
    # Match lines like "Step 1:", "1.", "1)" etc.
    for line in plan_text.splitlines():
        line = line.strip()
        match = re.match(r"^(?:step\s+)?(\d+)[:.)\-]\s+(.+)$", line, re.IGNORECASE)
        if match:
            steps.append(match.group(2).strip())
    return steps if steps else [plan_text[:200]]


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


async def _generate_query_plan(
    llm, query: str, intent: dict
) -> list[str]:
    """
    Step 1: Generate a reasoning plan before writing SQL.
    Returns a list of step strings.
    """
    enriched_query = intent.get("enriched_query", query)
    entities = intent.get("entities", {})
    query_type = intent.get("query_type", "descriptive")

    plan_request = (
        f"Question: \"{enriched_query}\"\n"
        f"Query type: {query_type}\n"
        f"Departments involved: {entities.get('departments', [])}\n"
        f"Metrics needed: {entities.get('metrics', [])}\n"
        f"Time reference: {entities.get('time', 'none')}\n\n"
        "Create a numbered execution plan for answering this question."
    )

    messages = [{"role": "user", "content": plan_request}]
    try:
        plan_text = await llm.generate(
            messages=messages,
            system_prompt=QUERY_PLANNER_PROMPT,
            temperature=0.0,
        )
        plan_text = _strip_thinking(plan_text)
        return _extract_plan_steps(plan_text)
    except Exception:
        return [f"Retrieve data to answer: {enriched_query}"]


async def _generate_sql(
    llm,
    query: str,
    intent: dict,
    plan: list[str],
    previous_error: Optional[str] = None,
    intelligence_context: Optional[dict] = None,
) -> str:
    """
    Step 2: Generate SQL based on the plan and intent.
    If previous_error is provided, this is a retry with correction context.
    Injects schema_summary from intelligence context if available.
    """
    enriched_query = intent.get("enriched_query", query)
    entities = intent.get("entities", {})
    plan_str = "\n".join(f"  {i+1}. {step}" for i, step in enumerate(plan))

    correction_note = ""
    if previous_error:
        correction_note = (
            f"\n\nPREVIOUS SQL FAILED with this error:\n{previous_error}\n"
            "Fix the SQL to resolve this error. Common fixes:\n"
            "- Add ::numeric cast before ROUND()\n"
            "- Check table/column names match the schema exactly\n"
            "- Use NULLIF() for division\n"
            "- Verify JOIN conditions\n"
        )

    # ── Intelligence context injection ─────────────────────────────────────
    context_section = ""
    if intelligence_context and intelligence_context.get("schema_summary"):
        context_section = (
            f"\n\nSEMANTIC CONTEXT (use this instead of guessing schema):\n"
            f"{intelligence_context['schema_summary']}\n"
        )

    sql_request = (
        f"User question: \"{enriched_query}\"\n"
        f"Query type: {intent.get('query_type', 'descriptive')}\n"
        f"Departments: {entities.get('departments', [])}\n"
        f"Metrics needed: {entities.get('metrics', [])}\n"
        f"Time filter: {entities.get('time', 'none')}\n\n"
        f"Execution plan:\n{plan_str}\n"
        f"{context_section}"
        f"{correction_note}\n"
        "Write the SQL query to execute this plan."
    )

    messages = [{"role": "user", "content": sql_request}]
    response = await llm.generate(
        messages=messages,
        system_prompt=QUERY_SYSTEM_PROMPT_V2,
        temperature=0.05,
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
        f"User asked: \"{query}\"\n"
        f"Query type: {query_type}\n"
        f"Departments: {entities.get('departments', [])}\n"
        f"Results ({len(data)} total rows, showing {len(data_preview)}):\n"
        f"{json.dumps(data_preview, indent=2, default=str)}\n\n"
        "Generate insights and summary."
    )

    messages = [{"role": "user", "content": insight_request}]
    try:
        insight_text = await llm.generate(
            messages=messages,
            system_prompt=INSIGHT_GENERATION_PROMPT,
            temperature=0.3,
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
    LangGraph node: Query Agent V2.
    Full reasoning pipeline: plan → SQL → validate → execute → retry → insights.
    Uses Agent Intelligence Layer context from state if available.
    """
    llm = get_llm_provider()
    query = state.get("user_query", "")
    intent = state.get("intent", {})
    intelligence_context = state.get("intelligence_context") or {}

    # Use enriched query if semantic layer resolved references
    effective_query = intent.get("enriched_query", query) or query

    # Track query start time for feedback
    query_start = time.monotonic()

    # ── Step 1: Generate Query Plan ─────────────────────────────────────────
    plan = await _generate_query_plan(llm, effective_query, intent)

    # ── Step 2–4: SQL Generation → Validation → Execution (with retries) ───
    sql_result: list[dict] = []
    last_error: Optional[str] = None
    final_sql: Optional[str] = None

    for attempt in range(MAX_RETRIES):
        # Generate SQL (with error context on retries)
        try:
            raw_sql = await _generate_sql(
                llm,
                effective_query,
                intent,
                plan,
                previous_error=last_error if attempt > 0 else None,
                intelligence_context=intelligence_context,
            )
        except ValueError as e:
            last_error = str(e)
            if attempt == MAX_RETRIES - 1:
                return {
                    "agent_used": "query",
                    "query_plan": plan,
                    "sql_result": [],
                    "insights": [],
                    "recommendations": [],
                    "error": str(e),
                    "final_response": (
                        "I had difficulty formulating a precise database query for your request. "
                        "Could you rephrase it with more specific details?"
                    ),
                }
            continue
        except Exception as e:
            last_error = f"LLM generation failed: {str(e)}"
            if attempt == MAX_RETRIES - 1:
                return {
                    "agent_used": "query",
                    "query_plan": plan,
                    "sql_result": [],
                    "insights": [],
                    "recommendations": [],
                    "error": last_error,
                    "final_response": f"I encountered an error generating the query: {str(e)}",
                }
            continue

        # Validate SQL (SELECT-only safety check)
        try:
            safe_sql = validate_sql(raw_sql)
        except SQLValidationError as e:
            last_error = f"SQL safety validation failed: {str(e)}"
            if attempt == MAX_RETRIES - 1:
                return {
                    "agent_used": "query",
                    "query_plan": plan,
                    "sql_result": [],
                    "insights": [],
                    "recommendations": [],
                    "error": last_error,
                    "final_response": "The generated query was rejected for safety reasons. Please try a different question.",
                }
            continue

        # Context validation — warn on unknown tables
        if intelligence_context:
            ctx_validator = SQLContextValidator()
            val_result = ctx_validator.validate(safe_sql, intelligence_context)
            if not val_result.valid:
                last_error = f"SQL context validation failed: {'; '.join(val_result.errors)}"
                if attempt == MAX_RETRIES - 1:
                    return {
                        "agent_used": "query",
                        "query_plan": plan,
                        "sql_result": [],
                        "insights": [],
                        "recommendations": [],
                        "error": last_error,
                        "final_response": "The generated query referenced invalid tables. Please rephrase your question.",
                    }
                continue

        # Execute against DB
        rows, db_error = await _execute_sql(db, safe_sql)

        if db_error:
            last_error = f"Database execution error: {db_error}"
            if attempt == MAX_RETRIES - 1:
                return {
                    "agent_used": "query",
                    "query_plan": plan,
                    "sql_result": [],
                    "insights": [],
                    "recommendations": [],
                    "error": last_error,
                    "final_response": (
                        f"I generated a valid query but it encountered a database error. "
                        f"Details: {db_error}"
                    ),
                }
            # Loop back with error for LLM to correct
            continue

        # Success!
        sql_result = rows
        final_sql = safe_sql
        last_error = None
        break

    # ── Step 5: Generate Insights ──────────────────────────────────────────
    insight_data = await _generate_insights(llm, effective_query, sql_result, intent)

    summary = insight_data.get("summary", "")
    insights = insight_data.get("insights", [])
    recommendations = insight_data.get("recommendations", [])

    # Build the final human-readable response
    if summary:
        final_response = summary
    elif sql_result:
        final_response = f"Found {len(sql_result)} records matching your query."
    else:
        final_response = "No records were found matching your query."

    # ── Step 6: Feedback Learning Loop ────────────────────────────────────
    # Store successful queries in query memory for future retrieval
    if final_sql and sql_result and not last_error:
        try:
            exec_time_ms = int((time.monotonic() - query_start) * 1000)
            entities_used = intent.get("entities", {}).get("departments", [])
            tables_used = [
                e.get("primary_table", "") for e in
                (intelligence_context.get("entities") or [])
            ]
            bus = get_context_bus()
            await bus.store_successful_query(
                question=effective_query,
                generated_sql=final_sql,
                result_summary=summary or f"Returned {len(sql_result)} rows.",
                entities_used=entities_used,
                tables_used=[t for t in tables_used if t],
                metrics_used=intent.get("entities", {}).get("metrics", []),
                agent_used="query",
                query_type=intent.get("query_type", "descriptive"),
                exec_time_ms=exec_time_ms,
                db=db,
            )
        except Exception:
            pass  # Non-critical

    return {
        "agent_used": "query",
        "query_plan": plan,
        "sql_result": sql_result,
        "insights": insights,
        "recommendations": recommendations,
        "final_response": final_response,
        "error": None,
    }
