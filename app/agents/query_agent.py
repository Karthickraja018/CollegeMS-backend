"""
Query Agent — translates natural language to SQL, validates, executes, and explains.
"""
import re
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.utils.sql_validator import validate_sql, SQLValidationError
from app.prompts import QUERY_SYSTEM_PROMPT


def _extract_sql(llm_response: str) -> str:
    """Extract SQL from LLM response that may contain markdown code blocks."""
    # Try ```sql ... ``` first
    match = re.search(r"```sql\s*(.*?)\s*```", llm_response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Try ``` ... ``` (no language tag)
    match = re.search(r"```\s*(SELECT.*?)\s*```", llm_response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Fall back: try to find a line starting with SELECT
    for line in llm_response.splitlines():
        if line.strip().upper().startswith("SELECT"):
            return line.strip()
    raise ValueError("Could not extract SQL from LLM response.")


async def query_agent_node(state: AgentState, db: AsyncSession) -> dict:
    """LangGraph node: Query Agent."""
    llm = get_llm_provider()
    query = state["user_query"]

    # Step 1: Generate SQL
    messages = [{"role": "user", "content": query}]
    try:
        llm_response = await llm.generate(
            messages=messages,
            system_prompt=QUERY_SYSTEM_PROMPT,
            temperature=0.1,
        )
    except Exception as e:
        return {
            "agent_used": "query",
            "error": f"LLM generation failed: {str(e)}",
            "final_response": f"I encountered an error generating the query: {str(e)}",
        }

    # Step 2: Extract SQL
    try:
        raw_sql = _extract_sql(llm_response)
    except ValueError as e:
        return {
            "agent_used": "query",
            "error": str(e),
            "final_response": "I could not generate a valid SQL query for your request. Please try rephrasing.",
        }

    # Step 3: Validate SQL (SELECT only)
    try:
        safe_sql = validate_sql(raw_sql)
    except SQLValidationError as e:
        return {
            "agent_used": "query",
            "error": str(e),
            "final_response": "The generated query was rejected for safety reasons. Please try a different question.",
        }

    # Step 4: Execute against DB
    try:
        result = await db.execute(text(safe_sql))
        rows = result.fetchall()
        columns = list(result.keys())
        sql_result = [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        return {
            "agent_used": "query",
            "error": f"Database error: {str(e)}",
            "final_response": f"The query generated was valid but failed to execute: {str(e)}",
        }

    # Step 5: Handle explanations and empty results
    # Remove <thinking> blocks if the model outputs them
    clean_text = re.sub(r"<thinking>.*?</thinking>", "", llm_response, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r"<thought>.*?</thought>", "", clean_text, flags=re.DOTALL | re.IGNORECASE)
    
    explanation = re.sub(r"```sql.*?```", "", clean_text, flags=re.DOTALL).strip()
    # Remove common prefixes like '### Explanation:'
    explanation = re.sub(r"^(###\s*)?Explanation:?\s*", "", explanation, flags=re.IGNORECASE).strip()
    
    if len(sql_result) == 0:
        try:
            summary_messages = [{"role": "user", "content": f"The user asked: '{query}'. The database query returned 0 results. Tell the user nicely that no matching records were found based on their request."}]
            explanation = await llm.generate(
                messages=summary_messages,
                system_prompt="You are a helpful AI assistant. Keep your response brief, clear, and direct.",
                temperature=0.3,
            )
            explanation = re.sub(r"<thinking>.*?</thinking>", "", explanation, flags=re.DOTALL | re.IGNORECASE)
            explanation = re.sub(r"<thought>.*?</thought>", "", explanation, flags=re.DOTALL | re.IGNORECASE).strip()
        except Exception:
            explanation = "No records were found matching your query."
    elif not explanation:
        explanation = f"Found {len(sql_result)} records matching your query."

    return {
        "agent_used": "query",
        "sql_result": sql_result,
        "final_response": explanation,
        "error": None,
    }
