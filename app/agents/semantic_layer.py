"""
Semantic Data Layer — College Knowledge Base.
Maps institutional terminology, abbreviations, and natural language phrases
to their database equivalents without requiring an extra LLM call.

This sits between the user's raw query and the SQL-generating agents,
enriching entities so the AI speaks "college" fluently.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional


# ── Department Aliases ──────────────────────────────────────────────────────────
# Maps any common alias → canonical department name as stored in DB
DEPARTMENT_ALIASES: dict[str, str] = {
    # Computer Science
    "cse": "Computer Science & Engineering",
    "cs": "Computer Science & Engineering",
    "computer science": "Computer Science & Engineering",
    "comp sci": "Computer Science & Engineering",
    "computers": "Computer Science & Engineering",
    "it": "Information Technology",
    "information technology": "Information Technology",
    # Electronics
    "ece": "Electronics & Communication Engineering",
    "ec": "Electronics & Communication Engineering",
    "electronics": "Electronics & Communication Engineering",
    "electronics and communication": "Electronics & Communication Engineering",
    "eee": "Electrical and Electronics Engineering",
    "electrical": "Electrical and Electronics Engineering",
    "electrical engineering": "Electrical and Electronics Engineering",
    # Mechanical
    "mech": "Mechanical Engineering",
    "me": "Mechanical Engineering",
    "mechanical": "Mechanical Engineering",
    "mechanical engineering": "Mechanical Engineering",
    # Civil
    "civil": "Civil Engineering",
    "ce": "Civil Engineering",
    "civil engineering": "Civil Engineering",
    # Chemical / Others
    "chem": "Chemical Engineering",
    "chemical": "Chemical Engineering",
    "aids": "Artificial Intelligence and Data Science",
    "ai": "Artificial Intelligence and Data Science",
    "aiml": "Artificial Intelligence and Machine Learning",
    "ds": "Data Science",
    "data science": "Data Science",
    "mba": "Master of Business Administration",
    "mca": "Master of Computer Applications",
}

# ── Metric Aliases ──────────────────────────────────────────────────────────────
METRIC_ALIASES: dict[str, str] = {
    # Attendance
    "attendance": "attendance_pct",
    "attendance %": "attendance_pct",
    "attendance percentage": "attendance_pct",
    "present %": "attendance_pct",
    "presence": "attendance_pct",
    # Marks / Performance
    "marks": "avg_marks_pct",
    "score": "avg_marks_pct",
    "performance": "avg_marks_pct",
    "marks %": "avg_marks_pct",
    "marks percentage": "avg_marks_pct",
    "average marks": "avg_marks_pct",
    # Pass rate
    "pass %": "pass_rate",
    "pass rate": "pass_rate",
    "pass percentage": "pass_rate",
    "passing rate": "pass_rate",
    # Arrears / Backlogs
    "arrear": "subjects_below_pass",
    "arrears": "subjects_below_pass",
    "backlog": "subjects_below_pass",
    "backlogs": "subjects_below_pass",
    "failed subjects": "subjects_below_pass",
    "failures": "subjects_below_pass",
    "pending subjects": "subjects_below_pass",
    # Risk
    "risk": "risk_score",
    "risk score": "risk_score",
    "at risk": "risk_score > 60",
    "likely to fail": "risk_score > 60",
    "critical students": "risk_score >= 81",
    "high risk": "risk_score >= 61",
}

# ── Time Reference Patterns ─────────────────────────────────────────────────────
# Map natural language time expressions to SQL-level hints
TIME_PATTERNS: list[tuple[str, str]] = [
    (r"\bcurrent\s+semester\b", "current_semester"),
    (r"\bthis\s+semester\b", "current_semester"),
    (r"\blast\s+semester\b", "previous_semester"),
    (r"\bprevious\s+semester\b", "previous_semester"),
    (r"\bthis\s+year\b", "current_year"),
    (r"\bcurrent\s+year\b", "current_year"),
    (r"\blast\s+year\b", "previous_year"),
    (r"\bprevious\s+(academic\s+)?year\b", "previous_year"),
    (r"\bthis\s+month\b", "current_month"),
    (r"\blast\s+month\b", "previous_month"),
    (r"\blast\s+(\d+)\s+months?\b", "last_n_months"),
    (r"\blast\s+(\d+)\s+days?\b", "last_n_days"),
]

# ── Query Type Indicators ───────────────────────────────────────────────────────
QUERY_TYPE_SIGNALS: dict[str, list[str]] = {
    "comparative": ["compare", "vs", "versus", "better than", "worse than", "difference between",
                    "which is higher", "which is lower", "between", "against"],
    "trend": ["trend", "over time", "month by month", "semester by semester", "growth",
              "increase", "decrease", "progression", "change over", "evolution"],
    "ranking": ["top", "best", "worst", "highest", "lowest", "bottom", "rank", "ranking",
                "leaderboard", "most", "least", "number one"],
    "predictive": ["likely to fail", "at risk", "predict", "forecast", "will fail",
                   "future", "projection", "expected", "declining", "showing decline"],
    "analytical": ["why", "reason", "cause", "what factors", "analysis", "breakdown",
                   "explain", "understand", "insight", "what is driving"],
    "visualization": ["chart", "graph", "plot", "visualize", "show me a", "bar chart",
                      "pie chart", "line graph", "trend chart", "draw"],
    "report": ["generate report", "create report", "report for", "download report",
               "formal report", "semester report", "hod report", "naac", "annual report"],
}


# ── Exam Type Aliases ───────────────────────────────────────────────────────────
EXAM_TYPE_ALIASES: dict[str, str] = {
    "internal": "internal1",
    "internal 1": "internal1",
    "internal 2": "internal2",
    "internal 3": "internal3",
    "cia": "internal1",
    "cia 1": "internal1",
    "cia 2": "internal2",
    "cia 3": "internal3",
    "end sem": "semester_end",
    "semester end": "semester_end",
    "final exam": "semester_end",
    "practical": "practical",
    "lab": "practical",
    "assignment": "assignment",
}

# ── Role Aliases ────────────────────────────────────────────────────────────────
ROLE_ALIASES: dict[str, str] = {
    "hod": "hod",
    "head of department": "hod",
    "head": "hod",
    "principal": "principal",
    "dean": "principal",
    "faculty": "faculty",
    "teacher": "faculty",
    "staff": "faculty",
    "admin": "admin",
    "administrator": "admin",
}


class CollegeSemanticLayer:
    """
    Resolves college institutional terminology into database-level concepts.
    Operates on user queries before they reach any SQL-generating agent.
    """

    def resolve_department(self, text: str) -> Optional[str]:
        """
        Resolve a department abbreviation or alias to its canonical DB name.
        Returns None if not recognized.
        """
        normalized = text.strip().lower().rstrip(".")
        return DEPARTMENT_ALIASES.get(normalized)

    def resolve_metric(self, text: str) -> Optional[str]:
        """Resolve a metric alias to its DB column or formula."""
        normalized = text.strip().lower()
        return METRIC_ALIASES.get(normalized)

    def extract_departments(self, query: str) -> list[str]:
        """
        Scan a query for department aliases and return canonical names.
        Handles multi-word aliases (e.g., "computer science").
        """
        found: list[str] = []
        q_lower = query.lower()

        # Sort aliases by length descending to match longer phrases first
        sorted_aliases = sorted(DEPARTMENT_ALIASES.keys(), key=len, reverse=True)
        matched_spans: list[tuple[int, int]] = []

        for alias in sorted_aliases:
            pattern = r'\b' + re.escape(alias) + r'\b'
            for match in re.finditer(pattern, q_lower):
                start, end = match.start(), match.end()
                # Skip if this span overlaps a previously matched one
                if any(s <= start < e or s < end <= e for s, e in matched_spans):
                    continue
                canonical = DEPARTMENT_ALIASES[alias]
                if canonical not in found:
                    found.append(canonical)
                matched_spans.append((start, end))

        return found

    def extract_metrics(self, query: str) -> list[str]:
        """Scan for metric aliases in the query."""
        found: list[str] = []
        q_lower = query.lower()

        sorted_aliases = sorted(METRIC_ALIASES.keys(), key=len, reverse=True)
        for alias in sorted_aliases:
            if re.search(r'\b' + re.escape(alias) + r'\b', q_lower):
                canonical = METRIC_ALIASES[alias]
                if canonical not in found:
                    found.append(canonical)

        return found

    def extract_time_reference(self, query: str) -> Optional[str]:
        """Detect and classify time references in the query."""
        q_lower = query.lower()
        for pattern, label in TIME_PATTERNS:
            match = re.search(pattern, q_lower)
            if match:
                if label == "last_n_months":
                    n = match.group(1)
                    return f"last_{n}_months"
                if label == "last_n_days":
                    n = match.group(1)
                    return f"last_{n}_days"
                return label
        return None

    def detect_query_type(self, query: str) -> str:
        """
        Heuristically detect query type from signal words.
        Returns one of: descriptive, comparative, trend, ranking,
                        analytical, predictive, visualization, report
        """
        q_lower = query.lower()
        scores: dict[str, int] = {}

        for qtype, signals in QUERY_TYPE_SIGNALS.items():
            score = sum(1 for s in signals if s in q_lower)
            if score > 0:
                scores[qtype] = score

        if not scores:
            return "descriptive"

        return max(scores, key=lambda k: scores[k])

    def resolve_entity_references(self, query: str, memory_context: dict) -> str:
        """
        Resolve pronoun/reference entity issues using memory context.
        e.g., "Compare it with ECE" + memory {"last_department": "CSE"}
              → "Compare CSE with ECE"
        """
        if not memory_context:
            return query

        q = query

        # Resolve "it" / "that" / "same" referring to last department
        last_dept = memory_context.get("last_department")
        if last_dept:
            q = re.sub(
                r'\b(it|that department|that|same department|the same)\b',
                last_dept,
                q,
                flags=re.IGNORECASE,
            )

        # Resolve "those students" / "those students" → last student group description
        last_students = memory_context.get("last_student_group")
        if last_students:
            q = re.sub(
                r'\b(those students|them|they|those)\b',
                last_students,
                q,
                flags=re.IGNORECASE,
            )

        # Resolve "that subject" → last subject
        last_subject = memory_context.get("last_subject")
        if last_subject:
            q = re.sub(
                r'\b(that subject|it)\b',
                last_subject,
                q,
                flags=re.IGNORECASE,
            )

        return q

    def enrich_query(self, query: str, memory_context: dict) -> dict:
        """
        Full enrichment pipeline:
        1. Resolve entity references from memory
        2. Extract departments, metrics, time
        3. Detect query type
        4. Return enrichment dict

        Returns:
        {
            "original_query": str,
            "enriched_query": str,       # after entity resolution
            "departments": list[str],    # canonical dept names found
            "metrics": list[str],        # metric column names found
            "time_reference": str|None,  # e.g., "current_semester"
            "query_type": str,           # e.g., "comparative"
        }
        """
        # Step 1: resolve pronouns/references
        enriched = self.resolve_entity_references(query, memory_context)

        # Step 2: extract entities
        departments = self.extract_departments(enriched)
        metrics = self.extract_metrics(enriched)
        time_ref = self.extract_time_reference(enriched)
        query_type = self.detect_query_type(enriched)

        return {
            "original_query": query,
            "enriched_query": enriched,
            "departments": departments,
            "metrics": metrics,
            "time_reference": time_ref,
            "query_type": query_type,
        }

    def update_memory_from_result(
        self,
        memory_context: dict,
        enrichment: dict,
        sql_result: list[dict],
    ) -> dict:
        """
        Update memory context based on what was just resolved/queried.
        Called after each agent response to persist entity state.
        """
        updated = dict(memory_context)

        # Track last department(s) queried
        if enrichment.get("departments"):
            depts = enrichment["departments"]
            updated["last_department"] = depts[0]
            updated["last_departments"] = depts

        # Track last metric
        if enrichment.get("metrics"):
            updated["last_metric"] = enrichment["metrics"][0]

        # Track last time reference
        if enrichment.get("time_reference"):
            updated["last_time_reference"] = enrichment["time_reference"]

        # Track last query type
        updated["last_query_type"] = enrichment.get("query_type", "descriptive")

        return updated

    def get_current_semester(self) -> int:
        """
        Estimate current semester based on calendar month.
        ODD semesters: July–November | EVEN semesters: January–May
        """
        month = datetime.now().month
        # Odd semester months: July(7) - November(11)
        if 7 <= month <= 11:
            return 1  # or 3, 5, 7 depending on year — return generic "odd" flag
        return 2  # Even semester

    def get_time_sql_filter(self, time_ref: str) -> Optional[str]:
        """
        Convert a time reference label to a SQL WHERE clause fragment.
        Returns None if no filter needed.
        """
        now = datetime.now()
        if time_ref == "current_month":
            return f"EXTRACT(MONTH FROM date) = {now.month} AND EXTRACT(YEAR FROM date) = {now.year}"
        elif time_ref == "current_year":
            return f"EXTRACT(YEAR FROM date) = {now.year}"
        elif time_ref == "previous_year":
            return f"EXTRACT(YEAR FROM date) = {now.year - 1}"
        elif time_ref == "previous_month":
            prev_month = now.month - 1 if now.month > 1 else 12
            prev_year = now.year if now.month > 1 else now.year - 1
            return f"EXTRACT(MONTH FROM date) = {prev_month} AND EXTRACT(YEAR FROM date) = {prev_year}"
        # semester references require domain logic — return a hint, not raw SQL
        return None


# Singleton instance — import this across agents
semantic_layer = CollegeSemanticLayer()
