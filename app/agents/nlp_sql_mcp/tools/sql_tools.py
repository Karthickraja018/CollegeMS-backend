"""
SQL generation and validation tools for Model Context Protocol.
"""
import json
import re
from app.utils.sql_validator import validate_sql as app_validate_sql, SQLValidationError
from app.llm.provider_factory import get_llm_provider
from app.prompts import QUERY_SYSTEM_PROMPT_V2
from app.agents.nlp_sql_mcp.tools.db_tools import SCHEMA_METADATA


async def tool_generate_sql(prompt: str) -> str:
    """
    Generate a PostgreSQL SELECT query based on a natural language prompt and schema layout.
    """
    llm = get_llm_provider()
    
    messages = [
        {
            "role": "user",
            "content": (
                f"Generate a valid PostgreSQL query for the following request:\n"
                f"Request: \"{prompt}\"\n\n"
                f"Schema Metadata:\n{json.dumps(SCHEMA_METADATA, indent=2)}\n\n"
                f"Rules for SQL Generation:\n"
                f"1. Prefer filtering by department code (`d.code = 'CSE'`) rather than department name (`d.name = '...'`) when department abbreviations (like CSE, ECE, EEE, MECH) are used or implied.\n"
                f"2. If filtering by name or descriptive columns where spelling or casing might vary, use `ILIKE` with `%` wildcards (e.g. `d.name ILIKE '%Computer Science%'`) instead of strict equal matches (`=`).\n\n"
                f"Write SELECT query only. Wrap your SQL in ```sql ... ``` block."
            )
        }
    ]
    
    response = await llm.generate(
        messages=messages,
        system_prompt=QUERY_SYSTEM_PROMPT_V2,
        temperature=0.0,
    )
    
    # Extract SQL block
    match = re.search(r"```sql\s*(.*?)\s*```", response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    match_raw = re.search(r"(SELECT\s+.+?)(?:;|\Z)", response, re.DOTALL | re.IGNORECASE)
    if match_raw:
        return match_raw.group(1).strip()
        
    return response.strip()


def tool_validate_sql(sql: str) -> str:
    """
    Perform a security and structure check on the SQL statement.
    Ensures it is SELECT-only and contains no forbidden SQL keywords.
    """
    try:
        cleaned_sql = app_validate_sql(sql)
        return json.dumps({"status": "valid", "sql": cleaned_sql})
    except SQLValidationError as e:
        return json.dumps({"status": "invalid", "error": str(e)})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
