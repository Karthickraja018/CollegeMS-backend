"""
Coordination workflow showing how the tools connect together to process a query
from natural language prompt -> schema search -> SQL generation -> validation -> database execution -> LLM insights.
"""
import sys
import os
import json
from typing import Dict, Any

# Ensure project root is in python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.agents.nlp_sql_mcp.tools.db_tools import (
    tool_search_schema,
    tool_execute_sql,
    tool_sample_values,
)
from app.agents.nlp_sql_mcp.tools.sql_tools import (
    tool_generate_sql,
    tool_validate_sql,
)
from app.llm.provider_factory import get_llm_provider
from app.prompts import INSIGHT_GENERATION_PROMPT


async def run_nlp_sql_workflow(prompt: str, confirmed_values: dict = None) -> Dict[str, Any]:
    """
    Runs the complete NLP-to-SQL toolchain matching the external MCP architecture:
    1. Search schema for relevant tables/columns.
    2. Generate SQL using the schema context (handling lookup verification blocks).
    3. Validate that generated SQL is safe and SELECT-only.
    4. Execute the SQL against the database using parameter bindings.
    5. Pass database outputs back to LLM to generate insights.
    """
    print(f"\n--- Starting NLP-SQL Workflow for prompt: '{prompt}' ---")
    
    # 1. Search Schema
    schema_context_raw = tool_search_schema(prompt)
    print("[Step 1] Schema Search complete.")

    # 2. Generate SQL
    sql_generation_raw = await tool_generate_sql(
        question=prompt,
        schema_context=schema_context_raw,
        dialect="postgresql",
        confirmed_values=confirmed_values
    )
    sql_gen_res = json.loads(sql_generation_raw)
    
    if sql_gen_res.get("blocked"):
        print(f"[Step 2] SQL Generation BLOCKED: {sql_gen_res.get('user_prompt')}")
        return {
            "success": False,
            "blocked": True,
            "user_prompt": sql_gen_res.get("user_prompt"),
            "step": "generation"
        }
        
    raw_sql = sql_gen_res.get("sql")
    params = sql_gen_res.get("params", {})
    print(f"[Step 2] Generated SQL:\n{raw_sql}\nParameters: {params}")

    # 3. Validate SQL
    val_raw = tool_validate_sql(raw_sql)
    val_res = json.loads(val_raw)
    
    if not val_res.get("valid"):
        print(f"[Step 3] Validation FAILED: {val_res.get('blocked_reason')}")
        return {
            "success": False,
            "error_step": "validation",
            "error_msg": val_res.get("blocked_reason"),
            "sql": raw_sql
        }
    
    print("[Step 3] Validation PASSED.")

    # 4. Execute SQL
    exec_raw = await tool_execute_sql(raw_sql, params)
    exec_res = json.loads(exec_raw)
    
    if exec_res.get("error"):
        print(f"[Step 4] Execution FAILED: {exec_res.get('message')}")
        return {
            "success": False,
            "error_step": "execution",
            "error_msg": exec_res.get("message"),
            "sql": raw_sql
        }
        
    rows = exec_res.get("rows", [])
    cols = exec_res.get("columns", [])
    row_count = exec_res.get("row_count", 0)
    print(f"[Step 4] Execution Success. Retrieved {row_count} rows.")

    # Convert rows lists back to dicts for downstream insight step
    dict_rows = [dict(zip(cols, row)) for row in rows]

    # 5. Generate LLM Insights
    llm = get_llm_provider()
    
    insight_prompt = (
        f"User asked: \"{prompt}\"\n"
        f"Results ({len(dict_rows)} rows):\n"
        f"{json.dumps(dict_rows[:50], indent=2, default=str)}\n\n"
        "Generate a concise, human-friendly summary of these results along with any key insights."
    )
    
    messages = [{"role": "user", "content": insight_prompt}]
    
    try:
        response = await llm.generate(
            messages=messages,
            system_prompt=INSIGHT_GENERATION_PROMPT,
            temperature=0.25,
        )
        print("[Step 5] Insights Generated successfully.")
    except Exception as e:
        response = f"Could not generate insights: {str(e)}"
        print(f"[Step 5] Insights Generation Failed: {str(e)}")

    return {
        "success": True,
        "sql": raw_sql,
        "params": params,
        "data": dict_rows,
        "insights": response
    }


if __name__ == "__main__":
    import asyncio
    
    async def test():
        # First query: lists all students. Should not trigger lookup block
        res = await run_nlp_sql_workflow("List all students")
        print("\n--- First Test Output ---")
        print(json.dumps(res, indent=2))
        
        # Second query: lists a specific department code (lookup column).
        # This will trigger B1 check blocking, prompting for sample values
        res_blocked = await run_nlp_sql_workflow("List all students in CSE department")
        print("\n--- Blocked Test Output ---")
        print(json.dumps(res_blocked, indent=2))
        
        if res_blocked.get("blocked"):
            # Fetch sample values
            sample_val_json = await tool_sample_values("departments", "code", "CSE")
            print(f"\n--- Fetched Sample Values: {sample_val_json} ---")
            
            # Re-run with confirmed value
            res_confirmed = await run_nlp_sql_workflow(
                prompt="List all students in CSE department",
                confirmed_values={"code": "CSE"}
            )
            print("\n--- Confirmed Test Output ---")
            print(json.dumps(res_confirmed, indent=2))
        
    asyncio.run(test())
