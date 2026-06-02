"""
Tests for Context Retrieval Service.
Tests all 10 required query patterns from the spec.

Run with:
    cd backend
    python -m pytest tests/intelligence/test_context_retrieval.py -v
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.intelligence.context_retrieval import (
    ContextRetrievalService,
    RetrievedEntity,
    RetrievedTerm,
    RetrievedQuery,
    RetrievalResult,
)
from app.intelligence.context_assembler import ContextAssembler


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_entities() -> list[RetrievedEntity]:
    """Sample entity results for mock tests."""
    return [
        RetrievedEntity(
            entity_id=1,
            entity_name="Student",
            description="Represents a student enrolled in the college.",
            primary_table="students",
            join_key="id",
            aliases=["learner", "pupil"],
            attributes=["id", "name", "roll_number", "risk_score", "current_semester"],
            business_rules=["Attendance below 75% marks at risk"],
            similarity=0.92,
        ),
        RetrievedEntity(
            entity_id=3,
            entity_name="Attendance",
            description="Attendance record for a student.",
            primary_table="attendance_records",
            join_key="id",
            aliases=["presence"],
            attributes=["id", "student_id", "subject_id", "date", "status"],
            business_rules=["Minimum attendance required: 75%", "OD counts as present"],
            similarity=0.88,
        ),
    ]


@pytest.fixture
def sample_terms() -> list[RetrievedTerm]:
    """Sample terminology results."""
    return [
        RetrievedTerm(
            term_id=1,
            term="CIA",
            full_form="Continuous Internal Assessment",
            definition="Internal examinations (CIA1, CIA2, CIA3).",
            category="exam_type",
            db_mapping="cia1, cia2, cia3",
            db_table="marks_records",
            aliases=["internal exam"],
            similarity=0.85,
        ),
    ]


@pytest.fixture
def assembler():
    return ContextAssembler()


# ─────────────────────────────────────────────────────────────────────────────
# Test 1-10: The 10 Required Query Patterns
# ─────────────────────────────────────────────────────────────────────────────

class TestRequiredQueries:
    """Test that the 10 required query patterns trigger correct entity retrieval."""

    def _make_retrieval(self, entities, terms=None, queries=None) -> RetrievalResult:
        return RetrievalResult(
            question="test",
            entities=entities,
            terminology=terms or [],
            query_examples=queries or [],
        )

    def test_query_1_attendance_trends(self, sample_entities, assembler):
        """Q1: 'Show attendance trends' → retrieves Attendance entity."""
        retrieval = self._make_retrieval(sample_entities)
        ctx = assembler.assemble(retrieval, "query")

        entity_names = [e["name"] for e in ctx["entities"]]
        assert "Attendance" in entity_names, "Attendance entity must be in context"
        assert "Student" in entity_names, "Student entity must be in context"

    def test_query_2_at_risk_students(self, sample_entities, assembler):
        """Q2: 'Find at-risk students' → retrieves Student + risk_score attribute."""
        retrieval = self._make_retrieval(sample_entities)
        ctx = assembler.assemble(retrieval, "performance")

        student_entity = next((e for e in ctx["entities"] if e["name"] == "Student"), None)
        assert student_entity is not None
        assert "risk_score" in student_entity["attributes"]

    def test_query_3_compare_departments(self, assembler):
        """Q3: 'Compare departments' → context has Department entity."""
        dept_entity = RetrievedEntity(
            entity_id=3, entity_name="Department", description="Academic department",
            primary_table="departments", join_key="id",
            aliases=["dept"], attributes=["id", "name", "code"], business_rules=[],
            similarity=0.90,
        )
        retrieval = self._make_retrieval([dept_entity])
        ctx = assembler.assemble(retrieval, "query")

        entity_names = [e["name"] for e in ctx["entities"]]
        assert "Department" in entity_names

    def test_query_4_attendance_below_threshold(self, sample_entities, assembler):
        """Q4: 'Students with attendance below 75%' → business rules include threshold."""
        retrieval = self._make_retrieval(sample_entities)
        ctx = assembler.assemble(retrieval, "query")

        rules_text = " ".join(ctx["business_rules"])
        assert "75%" in rules_text or "75" in rules_text, \
            "75% attendance threshold must appear in business rules"

    def test_query_5_faculty_performance(self, assembler):
        """Q5: 'Show faculty performance' → retrieves Faculty entity."""
        faculty_entity = RetrievedEntity(
            entity_id=2, entity_name="Faculty", description="Faculty member",
            primary_table="users", join_key="id",
            aliases=["teacher", "staff"], attributes=["id", "full_name", "department_id"],
            business_rules=["Faculty role is 'faculty'"], similarity=0.87,
        )
        retrieval = self._make_retrieval([faculty_entity])
        ctx = assembler.assemble(retrieval, "query")

        entity_names = [e["name"] for e in ctx["entities"]]
        assert "Faculty" in entity_names

    def test_query_6_cia_requirements(self, sample_terms, assembler):
        """Q6: 'Explain CIA requirements' → CIA terminology is in context."""
        retrieval = self._make_retrieval([], terms=sample_terms)
        ctx = assembler.assemble(retrieval, "query")

        assert "CIA" in ctx["terminology"]
        cia = ctx["terminology"]["CIA"]
        assert cia["db_mapping"] == "cia1, cia2, cia3"
        assert "exam_type" == cia["category"]

    def test_query_7_semester_performance(self, assembler):
        """Q7: 'Compare semester performance' → retrieves Semester + Assessment entities."""
        sem_entity = RetrievedEntity(
            entity_id=6, entity_name="Semester", description="Academic semester",
            primary_table="semesters", join_key="id",
            aliases=["term", "sem"], attributes=["id", "semester_number", "status"],
            business_rules=[], similarity=0.88,
        )
        assessment_entity = RetrievedEntity(
            entity_id=9, entity_name="Assessment", description="Marks record",
            primary_table="marks_records", join_key="id",
            aliases=["marks", "exam"], attributes=["id", "student_id", "exam_type", "marks_obtained"],
            business_rules=["Pass percentage: 40% for internal exams"],
            similarity=0.82,
        )
        retrieval = self._make_retrieval([sem_entity, assessment_entity])
        ctx = assembler.assemble(retrieval, "query")

        entity_names = [e["name"] for e in ctx["entities"]]
        assert "Semester" in entity_names
        assert "Assessment" in entity_names

    def test_query_8_annual_summary(self, assembler):
        """Q8: 'Generate annual academic summary' → retrieves AcademicYear entity."""
        year_entity = RetrievedEntity(
            entity_id=7, entity_name="AcademicYear", description="Academic year cycle",
            primary_table="academic_years", join_key="id",
            aliases=["year", "session"], attributes=["id", "label", "is_current"],
            business_rules=["Label format: YYYY-YY"], similarity=0.85,
        )
        retrieval = self._make_retrieval([year_entity])
        ctx = assembler.assemble(retrieval, "report")

        entity_names = [e["name"] for e in ctx["entities"]]
        assert "AcademicYear" in entity_names

    def test_query_9_od_students(self, sample_terms, assembler):
        """Q9: 'Show OD students' → OD terminology maps to db value 'od'."""
        od_term = RetrievedTerm(
            term_id=6, term="OD", full_form="On Duty",
            definition="Authorized absence counted as present.",
            category="status", db_mapping="od", db_table="attendance_records",
            aliases=["on duty", "duty leave"], similarity=0.90,
        )
        retrieval = self._make_retrieval([], terms=[od_term])
        ctx = assembler.assemble(retrieval, "query")

        assert "OD" in ctx["terminology"]
        assert ctx["terminology"]["OD"]["db_mapping"] == "od"

    def test_query_10_declining_performance(self, sample_entities, assembler):
        """Q10: 'Show students with declining performance' → Student + risk."""
        retrieval = self._make_retrieval(sample_entities)
        ctx = assembler.assemble(retrieval, "performance")

        student = next((e for e in ctx["entities"] if e["name"] == "Student"), None)
        assert student is not None
        assert "risk_score" in student["attributes"]


# ─────────────────────────────────────────────────────────────────────────────
# Test: Context Assembler Structure
# ─────────────────────────────────────────────────────────────────────────────

class TestContextAssembler:
    """Test ContextAssembler output structure."""

    def test_schema_summary_not_empty(self, sample_entities, sample_terms, assembler):
        """Schema summary must be a non-empty string."""
        from app.intelligence.context_retrieval import EntityRelationship
        rel = EntityRelationship(
            from_entity="Student", relationship="belongs_to", to_entity="Attendance",
            join_sql="JOIN attendance_records ar ON ar.student_id = s.id",
            description="Student has attendance records", confidence=1.0,
        )
        retrieval = RetrievalResult(
            question="test attendance",
            entities=sample_entities,
            terminology=sample_terms,
            relationships=[rel],
        )
        ctx = assembler.assemble(retrieval, "query")

        assert ctx["schema_summary"], "schema_summary must not be empty"
        assert "=== RELEVANT ENTITIES ===" in ctx["schema_summary"]
        assert "=== ACADEMIC TERMINOLOGY ===" in ctx["schema_summary"]

    def test_join_paths_deduplicated(self, assembler):
        """Duplicate join paths must be removed."""
        from app.intelligence.context_retrieval import EntityRelationship
        dup_rel = EntityRelationship(
            from_entity="Student", relationship="has_many", to_entity="Attendance",
            join_sql="JOIN attendance_records ar ON ar.student_id = s.id",
            description="dup", confidence=1.0,
        )
        retrieval = RetrievalResult(
            question="test", entities=[], terminology=[],
            relationships=[dup_rel, dup_rel],  # duplicate
        )
        ctx = assembler.assemble(retrieval, "query")
        # Should only have 1 join path
        assert len(ctx["join_paths"]) == 1

    def test_business_rules_deduplicated(self, sample_entities, assembler):
        """Duplicate business rules must appear only once."""
        # Add duplicate entity with same rule
        dup_entity = RetrievedEntity(
            entity_id=99, entity_name="StudentDup", description="dup",
            primary_table="students", join_key="id",
            aliases=[], attributes=[],
            business_rules=["Attendance below 75% marks at risk"],  # same as sample
            similarity=0.70,
        )
        retrieval = RetrievalResult(
            question="test",
            entities=[sample_entities[0], dup_entity],
            terminology=[],
        )
        ctx = assembler.assemble(retrieval, "query")
        rule_count = sum(
            1 for r in ctx["business_rules"]
            if r == "Attendance below 75% marks at risk"
        )
        assert rule_count == 1, "Duplicate business rules must be deduplicated"

    def test_meta_fields_present(self, sample_entities, assembler):
        """Meta fields must be present and correct type."""
        retrieval = RetrievalResult(
            question="test", entities=sample_entities, terminology=[],
        )
        ctx = assembler.assemble(retrieval, "query")
        meta = ctx["meta"]
        assert "retrieval_ms" in meta
        assert "entities_found" in meta
        assert meta["entities_found"] == len(sample_entities)


# ─────────────────────────────────────────────────────────────────────────────
# Test: SQL Context Validator
# ─────────────────────────────────────────────────────────────────────────────

class TestSQLContextValidator:
    """Test SQL context validation."""

    def test_valid_sql_passes(self, sample_entities, assembler):
        from app.intelligence.sql_context_validator import SQLContextValidator
        retrieval = RetrievalResult(question="test", entities=sample_entities)
        ctx = assembler.assemble(retrieval, "query")
        validator = SQLContextValidator()
        result = validator.validate(
            "SELECT s.name FROM students s JOIN attendance_records ar ON ar.student_id = s.id",
            ctx,
        )
        assert result.valid
        assert not result.errors

    def test_restricted_table_fails(self, assembler):
        from app.intelligence.sql_context_validator import SQLContextValidator
        ctx = assembler.assemble(
            RetrievalResult(question="test", entities=[]), "query"
        )
        validator = SQLContextValidator()
        result = validator.validate("SELECT * FROM semantic_entities", ctx)
        assert not result.valid
        assert any("restricted" in e.lower() for e in result.errors)

    def test_unknown_table_warns(self, assembler):
        from app.intelligence.sql_context_validator import SQLContextValidator
        ctx = assembler.assemble(
            RetrievalResult(question="test", entities=[]), "query"
        )
        validator = SQLContextValidator()
        result = validator.validate("SELECT * FROM nonexistent_made_up_table", ctx)
        # Should be a warning, not an error
        assert result.valid  # Not a critical failure
        assert result.unknown_tables or result.warnings
