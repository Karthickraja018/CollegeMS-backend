"""
MCP Server exposing NLP to SQL tools for CollegeMS database.
Imports functions from separated tools package modules.
"""
import os
import sys
from typing import Optional

# Ensure project root is in python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from fastmcp import FastMCP
from app.agents.nlp_sql_mcp.tools import (
    tool_search_schema,
    tool_generate_sql,
    tool_validate_sql,
    tool_execute_sql,
)

# Expose server endpoint
mcp = FastMCP("NLP-SQL MCP Server")


@mcp.tool()
def search_schema(keyword: Optional[str] = None) -> str:
    """
    Search database schema details (table structures, column definitions, data types).
    Use this to find which tables or columns to query for specific fields.
    """
    return tool_search_schema(keyword)


@mcp.tool()
async def generate_sql(prompt: str) -> str:
    """
    Generate a PostgreSQL SELECT query based on a natural language prompt and schema layout.
    """
    return await tool_generate_sql(prompt)


@mcp.tool()
def validate_sql(sql: str) -> str:
    """
    Perform a security and structure check on the SQL statement.
    Ensures it is SELECT-only and contains no forbidden SQL keywords.
    """
    return tool_validate_sql(sql)


@mcp.tool()
async def execute_sql(sql: str) -> str:
    """
    Execute a validated SQL SELECT statement and return results in JSON.
    """
    return await tool_execute_sql(sql)


if __name__ == "__main__":
    mcp.run()
