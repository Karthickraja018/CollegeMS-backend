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

from app.agents.nlp_sql_mcp.tools import (
    tool_search_schema,
    tool_generate_sql,
    tool_validate_sql,
    tool_execute_sql,
)
from app.llm.provider_factory import get_llm_provider
from app.prompts import INSIGHT_GENERATION_PROMPT


async def run_nlp_sql_workflow(prompt: str) -> Dict[str, Any]:
    """
    Runs the complete NLP-to-SQL toolchain:
    1. Search schema for relevant tables/columns matching the user's keywords.
    2. Generate raw SQL SELECT statement targeting the matching schema structures.
    3. Validate that generated SQL is completely safe and SELECT-only.
    4. Execute the SQL against the database.
    5. Pass the database outputs back to the LLM to compose user-facing insights.
    """
    print(f"\n--- Starting NLP-SQL Workflow for prompt: '{prompt}' ---")
    
    # 1. Search Schema
    # Extract candidate keywords from prompt to search
    keywords = [w for w in prompt.split() if len(w) > 3]
    schema_hint = ""
    for kw in keywords[:2]:
        result = tool_search_schema(kw)
        if "No tables or columns" not in result:
            schema_hint = result
            break
            
    if not schema_hint:
        schema_hint = tool_search_schema(None)  # fallback to entire schema
        
    print("[Step 1] Schema Search complete.")

    # 2. Generate SQL
    raw_sql = await tool_generate_sql(prompt)
    print(f"[Step 2] Generated SQL:\n{raw_sql}")

    # 3. Validate SQL
    val_raw = tool_validate_sql(raw_sql)
    val_res = json.loads(val_raw)
    
    if val_res.get("status") != "valid":
        print(f"[Step 3] Validation FAILED: {val_res.get('error')}")
        return {
            "success": False,
            "error_step": "validation",
            "error_msg": val_res.get("error"),
            "sql": raw_sql
        }
    
    validated_sql = val_res["sql"]
    print("[Step 3] Validation PASSED.")

    # 4. Execute SQL
    exec_raw = await tool_execute_sql(validated_sql)
    exec_res = json.loads(exec_raw)
    
    if isinstance(exec_res, dict) and "error" in exec_res:
        print(f"[Step 4] Execution FAILED: {exec_res['error']}")
        return {
            "success": False,
            "error_step": "execution",
            "error_msg": exec_res["error"],
            "sql": validated_sql
        }
        
    print(f"[Step 4] Execution Success. Retrieved {len(exec_res)} rows.")

    # 5. Generate LLM Insights
    llm = get_llm_provider()
    
    insight_prompt = (
        f"User asked: \"{prompt}\"\n"
        f"Results ({len(exec_res)} rows):\n"
        f"{json.dumps(exec_res[:50], indent=2, default=str)}\n\n"
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
        "sql": validated_sql,
        "data": exec_res,
        "insights": response
    }


if __name__ == "__main__":
    import asyncio
    
    async def test():
        # Quick test run with actual columns schema (roll_number and semester, not roll_no / current_semester)
        res = await run_nlp_sql_workflow("List all students in CSE department")
        print("\n--- Final Workflow Output ---")
        print(json.dumps(res, indent=2))
        
    asyncio.run(test())
