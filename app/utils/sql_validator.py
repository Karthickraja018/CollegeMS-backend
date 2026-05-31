"""
SQL Validator — ensures the Query Agent can only execute SELECT statements.
Uses sqlglot for AST-level validation (not string matching).
"""
import sqlglot
from sqlglot import exp


class SQLValidationError(Exception):
    """Raised when generated SQL fails safety checks."""
    pass


ALLOWED_STATEMENT_TYPES = {exp.Select}

FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
    "TRUNCATE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
    "CALL", "MERGE", "REPLACE",
}


def validate_sql(sql: str) -> str:
    """
    Parse and validate SQL. Returns the cleaned SQL string if valid.
    Raises SQLValidationError if it contains non-SELECT operations.
    """
    sql = sql.strip().rstrip(";")

    # Check forbidden keywords (fast path)
    sql_upper = sql.upper()
    for kw in FORBIDDEN_KEYWORDS:
        if kw in sql_upper.split():
            raise SQLValidationError(
                f"Forbidden SQL keyword detected: {kw}. Only SELECT queries are allowed."
            )

    # AST-level check
    try:
        statements = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.errors.ParseError as e:
        raise SQLValidationError(f"SQL parse error: {e}")

    if not statements:
        raise SQLValidationError("Empty SQL statement.")

    for stmt in statements:
        if type(stmt) not in ALLOWED_STATEMENT_TYPES:
            raise SQLValidationError(
                f"Only SELECT statements are allowed. Got: {type(stmt).__name__}"
            )

    # Disallow subquery mutations (e.g., SELECT inside UPDATE — edge case)
    for stmt in statements:
        for node in stmt.walk():
            if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create)):
                raise SQLValidationError(
                    "Nested mutation detected in SQL. Only read-only queries are allowed."
                )

    return sql
