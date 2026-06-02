"""
MCP Server exposing NLP to SQL tools for CollegeMS database.
"""
import os
import sys
import json
from typing import Optional

# Ensure project root is in python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from fastmcp import FastMCP
from app.agents.nlp_sql_mcp.tools.db_tools import (
    tool_search_schema,
    tool_execute_sql,
    tool_sample_values,
)
from app.agents.nlp_sql_mcp.tools.sql_tools import (
    tool_generate_sql,
    tool_validate_sql,
)

# Initialize MCP Server
mcp = FastMCP("NLP-SQL MCP Server")


@mcp.tool()
def search_schema(question: Optional[str] = None) -> str:
    """
    Search database schema details (table structures, column definitions, data types).
    Use this to find which tables or columns to query for specific fields.
    """
    return tool_search_schema(question)


@mcp.tool(
    description="""Generates SQL for a question.
    IMPORTANT: If the result contains blocked=true,
    stop immediately. Do not call validate_sql or execute.
    Show the user_prompt field to the user verbatim and wait for their reply."""
)
async def write_sql(
    question: str,
    schema_context: str,
    dialect: str = "postgresql",
    confirmed_values: str = "{}"
) -> str:
    """
    Generate a SELECT query using ONLY columns and tables present in schema_context.
    """
    try:
        confirmed_dict = json.loads(confirmed_values)
    except json.JSONDecodeError:
        confirmed_dict = {}
        
    return await tool_generate_sql(question, schema_context, dialect, confirmed_dict)


@mcp.tool()
def validate_sql(sql: str) -> str:
    """
    Perform a security and structure check on the SQL statement.
    Ensures it is SELECT-only and contains no forbidden SQL keywords.
    """
    return tool_validate_sql(sql)


@mcp.tool()
async def sample_values(table: str, column: str, search_term: str = "", limit: int = 20) -> str:
    """
    Fetch up to `limit` distinct values for a given table and column.
    Only allows columns marked as lookup: true in the schema.
    """
    search = search_term if search_term else None
    return await tool_sample_values(table, column, search, limit)


@mcp.tool()
async def execute(sql: str, params: str = "{}") -> str:
    """
    Execute SQL query using parameterized binding.
    Returns JSON string of the results.
    """
    try:
        params_dict = json.loads(params)
    except json.JSONDecodeError:
        params_dict = {}
        
    return await tool_execute_sql(sql, params_dict)


if __name__ == "__main__":
    mcp.run()
