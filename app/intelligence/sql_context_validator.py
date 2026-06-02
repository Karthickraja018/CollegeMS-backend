"""
SQL Context Validator — Validates generated SQL against the assembled context.

Checks:
  1. All referenced tables exist in the retrieved context entities
  2. No obviously hallucinated table names
  3. Query uses only SELECT (handled upstream by sql_validator.py)
  4. Department/role scope respected (if context carries scope hints)

This is a lightweight, regex-based validator — not a full SQL parser.
Full SQL parsing is handled by sqlglot in sql_validator.py.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Known valid tables in CollegeMS database
KNOWN_TABLES: frozenset[str] = frozenset({
    "students", "users", "departments", "programs", "program_semesters",
    "semesters", "subjects", "syllabus_units", "timetable_slots",
    "faculty_subject_assignments", "semester_enrollments", "student_documents",
    "attendance_records", "attendance_summary",
    "marks_records", "marks_summary",
    "exam_schedules", "at_risk_snapshots",
    "reports", "chat_sessions", "notifications", "audit_logs",
    "naac_criteria_data", "colleges", "academic_years",
    # Intelligence layer tables (should NOT appear in generated SQL)
    # "semantic_entities", "query_examples", etc.
})


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tables_found: list[str] = field(default_factory=list)
    unknown_tables: list[str] = field(default_factory=list)


class SQLContextValidator:
    """
    Validates SQL against the assembled context to catch:
    - Unknown/hallucinated table names
    - Queries touching intelligence layer tables
    - Scope violations (cross-department queries for HOD)
    """

    # Intelligence layer tables that should never appear in user queries
    RESTRICTED_TABLES: frozenset[str] = frozenset({
        "semantic_entities", "semantic_attributes", "semantic_relationships",
        "academic_terminology", "query_examples", "query_feedback",
        "context_registry", "entity_embeddings", "terminology_embeddings",
        "query_embeddings",
    })

    def validate(self, sql: str, context: dict[str, Any]) -> ValidationResult:
        """
        Validate the SQL against the context.

        Returns ValidationResult with:
          - valid=True  : SQL looks safe and context-aligned
          - valid=False : SQL has critical issues (restricted tables, scope violation)
          - warnings    : Non-critical issues (unknown table not in context)
        """
        result = ValidationResult(valid=True)

        # Extract table names from SQL
        tables_in_sql = self._extract_tables(sql)
        result.tables_found = list(tables_in_sql)

        # ── Check 1: Restricted intelligence layer tables ─────────────────
        restricted_used = tables_in_sql & self.RESTRICTED_TABLES
        if restricted_used:
            result.valid = False
            result.errors.append(
                f"SQL references restricted intelligence layer tables: {restricted_used}. "
                "These tables are internal and must not be queried by user agents."
            )

        # ── Check 2: Unknown tables (not in known schema) ─────────────────
        unknown = tables_in_sql - KNOWN_TABLES - self.RESTRICTED_TABLES
        if unknown:
            result.unknown_tables = list(unknown)
            result.warnings.append(
                f"SQL references unrecognized table(s): {unknown}. "
                "These may be hallucinated. Verify against the known schema."
            )
            # Unknown tables are warnings, not errors (could be valid aliases/CTEs)

        # ── Check 3: Context alignment (do retrieved entities match tables?) ─
        context_tables: set[str] = {
            e.get("primary_table", "") for e in context.get("entities", [])
        }
        if context_tables and not tables_in_sql.intersection(context_tables | KNOWN_TABLES):
            result.warnings.append(
                "SQL tables do not overlap with retrieved context entities. "
                "The query may not match the user's intent."
            )

        # ── Check 4: Scope — no cross-department data for scoped roles ─────
        dept_filter = context.get("meta", {}).get("dept_filter_sql", "")
        if dept_filter and dept_filter.lower() not in sql.lower():
            result.warnings.append(
                "Department scope filter may be missing from SQL. "
                "Ensure department_id filter is applied for role-scoped queries."
            )

        return result

    def _extract_tables(self, sql: str) -> set[str]:
        """Extract table names from SQL using regex (handles FROM, JOIN clauses)."""
        # Remove SQL comments
        sql_clean = re.sub(r"--[^\n]*", "", sql)
        sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)

        # Match FROM and JOIN table names (handles aliases)
        # Pattern: FROM/JOIN <table_name> [alias] [ON/WHERE/,]
        pattern = r"\b(?:FROM|JOIN)\s+(\w+)"
        matches = re.findall(pattern, sql_clean, re.IGNORECASE)

        # Also match CTE names (WITH cte_name AS)
        cte_pattern = r"\bWITH\s+(\w+)\s+AS\s*\("
        cte_names = set(re.findall(cte_pattern, sql_clean, re.IGNORECASE))

        # Filter out CTE names (they're not real tables)
        real_tables = {m.lower() for m in matches} - {c.lower() for c in cte_names}

        # Filter out SQL keywords that might be picked up
        sql_keywords = {
            "select", "where", "and", "or", "not", "null", "true", "false",
            "inner", "left", "right", "outer", "cross", "lateral",
        }
        return real_tables - sql_keywords
