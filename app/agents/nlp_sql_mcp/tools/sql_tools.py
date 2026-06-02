"""
SQL generation and validation tools for CollegeMS NLP-SQL MCP.
"""
import json
import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import sqlglot
from sqlglot import exp

from app.llm.provider_factory import get_llm_provider
from app.agents.nlp_sql_mcp.config import AppConfig

class WriteSqlResult(BaseModel):
    sql: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    data_value_risk: bool = False
    risk_details: Optional[List[str]] = None
    explanation: Optional[str] = None
    blocked: bool = False
    user_prompt: Optional[str] = None

class ValidateSqlResult(BaseModel):
    valid: bool
    blocked_reason: Optional[str] = None
    statement_type: Optional[str] = None
    readonly_enforced: bool = True


def validate_confirmed_values(confirmed_values: Dict[str, Any], schema_dict: dict) -> None:
    if not confirmed_values:
        return
        
    known_columns = set()
    for table in schema_dict.get("tables", []):
        for col in table.get("columns", []):
            known_columns.add(col.get("name"))
            
    unknown = [k for k in confirmed_values if k not in known_columns]
    if unknown:
        raise ValueError(f"confirmed_values contains unknown columns: {unknown}")


def get_unconfirmed_lookup_columns(question: str, schema_dict: dict, confirmed_values: Dict[str, Any]) -> List[str]:
    question_lower = question.lower()
    blocking_columns = []
    
    for table in schema_dict.get("tables", []):
        for col in table.get("columns", []):
            if col.get("lookup", False):
                col_name = col.get("name", "")
                col_name_lower = col_name.lower()
                if col_name_lower in question_lower:
                    if col_name not in confirmed_values:
                        blocking_columns.append(col_name)
                        
    return list(set(blocking_columns))


async def tool_generate_sql(
    question: str,
    schema_context: str,
    dialect: str = "postgresql",
    confirmed_values: Optional[Dict[str, Any]] = None
) -> str:
    """
    """
    if confirmed_values is None:
        confirmed_values = {}
        
    try:
        schema_dict = json.loads(schema_context)
    except json.JSONDecodeError:
        raise ValueError("schema_context is not valid JSON")

    # Validate confirmed_values
    validate_confirmed_values(confirmed_values, schema_dict)

    # Check lookup columns before calling LLM (B1 enforcement)
    blocking_columns = get_unconfirmed_lookup_columns(question, schema_dict, confirmed_values)
    if blocking_columns:
        return WriteSqlResult(
            blocked=True,
            user_prompt=f"Please verify exact values before generating SQL. Use the sample_values tool for columns: {', '.join(blocking_columns)}",
            sql=None
        ).model_dump_json(indent=2)

    # Call LLM
    llm = get_llm_provider()
    
    system_prompt = f"""You are a SQL generator. You have ONLY this schema: {schema_context}.
                    Dialect: {dialect}.
                    Confirmed Values: {json.dumps(confirmed_values)}

                    Generate a SELECT query that answers: {question}.
                    Rules:
                    1. Use only tables and columns that exist in the schema above.
                    2. Parameterize any user-supplied values using named placeholders (e.g. :name). We will use SQLAlchemy `text()`, so use :name format for parameters.
                    3. Values from `confirmed_values` must be used exclusively as bind parameters (e.g., :key), and never interpolated literally into the SQL.
                    4. If a WHERE filter requires a string literal that is not an enum value, and it is not explicitly provided in `confirmed_values`, add this comment above that line: -- WARNING: assumed value '<value>' — verify it exists in your data
                    and set data_value_risk to true. Do not flag values from `confirmed_values` as risks.
                    5. Respond ONLY with a JSON object. No markdown, no explanation outside the JSON.
                    6. ALWAYS limit the generated SQL SELECT query to exactly 10 rows (LIMIT 10) unless the user explicitly asks for more.
                    JSON keys: sql, params, data_value_risk, risk_details, explanation"""

    messages = [{"role": "user", "content": f"Question: {question}"}]
    
    response = await llm.generate(
        messages=messages,
        system_prompt=system_prompt,
        temperature=0.0,
    )
    
    content = response.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    
    try:
        parsed = json.loads(content)
        if "risk_details" in parsed:
            if not isinstance(parsed["risk_details"], list):
                if isinstance(parsed["risk_details"], str):
                    parsed["risk_details"] = [parsed["risk_details"]]
                elif parsed["risk_details"] is None:
                    parsed["risk_details"] = []
                else:
                    parsed["risk_details"] = [str(parsed["risk_details"])]
        return WriteSqlResult(**parsed).model_dump_json(indent=2)
    except json.JSONDecodeError as e:
        # Fallback to parse it cleanly if the LLM put thinking process outside
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if "risk_details" in parsed:
                    if not isinstance(parsed["risk_details"], list):
                        if isinstance(parsed["risk_details"], str):
                            parsed["risk_details"] = [parsed["risk_details"]]
                        elif parsed["risk_details"] is None:
                            parsed["risk_details"] = []
                        else:
                            parsed["risk_details"] = [str(parsed["risk_details"])]
                return WriteSqlResult(**parsed).model_dump_json(indent=2)
            except Exception:
                pass
        raise ValueError(f"Failed to parse LLM response as JSON: {e}\nResponse was:\n{content}")


def tool_validate_sql(sql: str) -> str:
    """
    Validate SQL strictly using sqlglot, allowing only SELECT/WITH statements.
    """
    try:
        statements = sqlglot.parse(sql)
    except sqlglot.errors.ParseError as e:
        return ValidateSqlResult(
            valid=False,
            blocked_reason=f"Failed to parse SQL: {e}"
        ).model_dump_json(indent=2)
        
    statements = [stmt for stmt in statements if stmt is not None]
    
    if not statements:
        return ValidateSqlResult(
            valid=False,
            blocked_reason="No valid SQL statement found."
        ).model_dump_json(indent=2)
        
    if len(statements) > 1:
        return ValidateSqlResult(
            valid=False,
            blocked_reason="Stacked queries (multiple statements) are not permitted.",
            statement_type="MULTIPLE"
        ).model_dump_json(indent=2)
        
    stmt = statements[0]
    
    if isinstance(stmt, exp.Select):
        if stmt.args.get("with_"):
            statement_type = "WITH"
        else:
            statement_type = "SELECT"
    elif isinstance(stmt, exp.With):
        statement_type = "WITH"
    elif isinstance(stmt, exp.Delete):
        statement_type = "DELETE"
    elif isinstance(stmt, exp.Update):
        statement_type = "UPDATE"
    elif isinstance(stmt, exp.Insert):
        statement_type = "INSERT"
    elif isinstance(stmt, exp.Drop):
        statement_type = "DROP"
    elif isinstance(stmt, exp.Alter):
        statement_type = "ALTER"
    elif isinstance(stmt, exp.Command):
        statement_type = "COMMAND"
    elif isinstance(stmt, exp.Create):
        statement_type = "CREATE"
    else:
        statement_type = stmt.key.upper()
        
    for node in stmt.walk():
        if isinstance(node, exp.Insert):
            return ValidateSqlResult(
                valid=False,
                blocked_reason="INSERT statement is not permitted.",
                statement_type="INSERT"
            ).model_dump_json(indent=2)
        if isinstance(node, (exp.Delete, exp.Update, exp.Drop, exp.Alter, exp.Create)):
            return ValidateSqlResult(
                valid=False,
                blocked_reason=f"{node.key.upper()} operations are not permitted.",
                statement_type=node.key.upper()
            ).model_dump_json(indent=2)
            
    if statement_type not in ["SELECT", "WITH"]:
        return ValidateSqlResult(
            valid=False,
            blocked_reason=f"{statement_type} statement is not permitted.",
            statement_type=statement_type
        ).model_dump_json(indent=2)
        
    return ValidateSqlResult(
        valid=True,
        statement_type=statement_type
    ).model_dump_json(indent=2)
