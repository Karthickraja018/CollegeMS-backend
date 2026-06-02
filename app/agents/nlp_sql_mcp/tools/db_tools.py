"""
Database schema searching, execution, and sampling tools for NLP-SQL MCP.
"""
import time
import json
import re
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.agents.nlp_sql_mcp.config import AppConfig
from app.utils.sql_validator import validate_sql as app_validate_sql, SQLValidationError

# Pydantic models matching the connector models for responses
class ColumnResult(BaseModel):
    name: str
    type: str
    pk: bool
    fk: Optional[str] = None
    nullable: bool
    enum_values: Optional[List[str]] = None
    lookup: bool = False
    lookup_limit: int = 20

class TableResult(BaseModel):
    name: str
    description: Optional[str] = None
    columns: List[ColumnResult]

class SearchSchemaResult(BaseModel):
    tables: List[TableResult]
    relationships: List[str]

class ExecuteResult(BaseModel):
    columns: Optional[List[str]] = None
    rows: Optional[List[List[Any]]] = None
    row_count: Optional[int] = None
    execution_ms: Optional[int] = None
    error: Optional[str] = None
    message: Optional[str] = None

class SampleValuesResult(BaseModel):
    values: List[str]


def tool_search_schema(question: Optional[str] = None) -> str:
    """
    Search the database schema details using keyword match against table names or descriptions.
    """
    schema = AppConfig.get_schema()
    
    if not question:
        # Return complete schema format
        tables = []
        relationships = set()
        for t_name, t_def in schema.tables.items():
            cols = []
            for c_name, c_def in t_def.columns.items():
                cols.append(ColumnResult(
                    name=c_name,
                    type=c_def.type,
                    pk=c_def.pk,
                    fk=c_def.fk,
                    nullable=c_def.nullable,
                    enum_values=c_def.enum_values,
                    lookup=c_def.lookup,
                    lookup_limit=c_def.lookup_limit
                ))
                if c_def.fk:
                    relationships.add(f"{t_name}.{c_name} -> {c_def.fk}")
            tables.append(TableResult(
                name=t_name,
                description=t_def.description,
                columns=cols
            ))
        res = SearchSchemaResult(tables=tables, relationships=list(relationships))
        return res.model_dump_json(indent=2)

    # Tokenize question into words
    words = set(re.findall(r'\b\w+\b', question.lower()))
    
    matched_tables = []
    relationships = set()
    
    for table_name, table_def in schema.tables.items():
        table_name_lower = table_name.lower()
        desc_lower = (table_def.description or "").lower()
        
        table_match = False
        if table_name_lower in words:
            table_match = True
        
        for w in words:
            if len(w) > 3 and w in table_name_lower:
                table_match = True
            if len(w) > 3 and w in desc_lower:
                table_match = True
        
        matched_columns = []
        for col_name, col_def in table_def.columns.items():
            col_name_lower = col_name.lower()
            col_match = table_match
            
            if not col_match:
                if col_name_lower in words:
                    col_match = True
                for w in words:
                    if len(w) > 3 and w in col_name_lower:
                        col_match = True
            
            if col_match or table_match:
                matched_columns.append(ColumnResult(
                    name=col_name,
                    type=col_def.type,
                    pk=col_def.pk,
                    fk=col_def.fk,
                    nullable=col_def.nullable,
                    enum_values=col_def.enum_values,
                    lookup=col_def.lookup,
                    lookup_limit=col_def.lookup_limit
                ))
                if col_def.fk:
                    relationships.add(f"{table_name}.{col_name} -> {col_def.fk}")
        
        if matched_columns:
            matched_tables.append(TableResult(
                name=table_name,
                description=table_def.description,
                columns=matched_columns
            ))
            
    res = SearchSchemaResult(
        tables=matched_tables,
        relationships=list(relationships)
    )
    return res.model_dump_json(indent=2)


async def tool_execute_sql(sql: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    Execute a validated SQL SELECT statement and return results in JSON.
    """
    if params is None:
        params = {}
        
    # Safety validation
    try:
        app_validate_sql(sql)
    except SQLValidationError as e:
        return ExecuteResult(
            error="SQLValidationError",
            message=f"Safety check failed: {str(e)}"
        ).model_dump_json(indent=2)

    start_time = time.time()
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text(sql), params)
            rows = result.fetchall()
            columns = list(result.keys())
            rows_list = [list(row) for row in rows]
            execution_ms = int((time.time() - start_time) * 1000)
            
            return ExecuteResult(
                columns=columns,
                rows=rows_list,
                row_count=len(rows_list),
                execution_ms=execution_ms
            ).model_dump_json(indent=2)
            
    except Exception as e:
        return ExecuteResult(
            error=e.__class__.__name__,
            message=str(e)
        ).model_dump_json(indent=2)


async def tool_sample_values(table: str, column: str, search_term: Optional[str] = None, limit: int = 20) -> str:
    """
    Fetch distinct values for a given table and column.
    Only allows columns marked as lookup: true in the schema.
    """
    schema = AppConfig.get_schema()
    
    if table not in schema.tables:
        return json.dumps({"error": f"Table '{table}' does not exist in schema."})
        
    table_def = schema.tables[table]
    if column not in table_def.columns:
        return json.dumps({"error": f"Column '{column}' does not exist in table '{table}'."})
        
    col_def = table_def.columns[column]
    if not col_def.lookup:
        return json.dumps({"error": f"Column '{column}' in table '{table}' is not marked for lookup."})

    limit_int = int(limit)
    if limit_int > col_def.lookup_limit:
        limit_int = col_def.lookup_limit
        
    params = {}
    base_sql = f"SELECT DISTINCT {column} FROM {table}"
    
    if search_term:
        # Simple parameterization
        base_sql += f" WHERE {column} ILIKE :term"
        params["term"] = f"%{search_term}%"
        
    base_sql += f" LIMIT {limit_int}"
    
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text(base_sql), params)
            values = [str(row[0]) for row in result.fetchall() if row[0] is not None]
            return SampleValuesResult(values=values).model_dump_json(indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
