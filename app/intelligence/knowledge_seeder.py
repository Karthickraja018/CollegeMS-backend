"""
Knowledge Seeder — Seeds the Agent Intelligence Layer with CollegeMS domain knowledge.

Seeds:
  1. Semantic Entities     — Student, Faculty, Department, Subject, etc.
  2. Semantic Attributes   — Column-level metadata with business meaning
  3. Semantic Relationships— Join paths between entities
  4. Academic Terminology  — CIA, CGPA, OD, NBA, NAAC, Arrear, etc.
  5. Query Examples        — 20 canonical queries as starting query memory
  6. Runs EmbeddingService.update_all_embeddings() after seeding

Call KnowledgeSeeder.seed_if_empty(db) on app startup.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Domain Knowledge — Entities
# ─────────────────────────────────────────────────────────────────────────────

ENTITIES: list[dict[str, Any]] = [
    {
        "entity_name": "Student",
        "description": (
            "Represents a student enrolled in the college. Contains academic details, "
            "personal information, risk scores, and enrollment status."
        ),
        "primary_table": "students",
        "join_key": "id",
        "aliases": ["learner", "pupil", "student_record", "enrollee", "candidate"],
        "attributes": [
            "id", "name", "roll_number", "register_number", "email",
            "current_semester", "batch", "section", "department_id",
            "program_id", "status", "risk_score", "risk_flags",
            "gender", "community", "lateral_entry", "is_hosteller"
        ],
        "business_rules": [
            "Attendance below 75% marks the student at risk of detention",
            "Risk score > 60 means high risk; > 80 means critical",
            "Student status 'detained' means barred from end-semester exam",
            "Arrear students have grade F or U in at least one subject"
        ],
        "display_name": "Student",
    },
    {
        "entity_name": "Faculty",
        "description": (
            "Represents a faculty member (teaching staff) of the college. "
            "Faculty members belong to departments and teach subjects."
        ),
        "primary_table": "users",
        "join_key": "id",
        "aliases": ["teacher", "staff", "lecturer", "professor", "instructor"],
        "attributes": [
            "id", "full_name", "employee_id", "email", "department_id",
            "designation", "qualification", "experience_years", "role"
        ],
        "business_rules": [
            "Faculty role in users table is 'faculty'",
            "HOD role is 'hod' — they are also faculty with administrative duties",
            "Faculty are assigned subjects via faculty_subject_assignments table"
        ],
        "display_name": "Faculty",
    },
    {
        "entity_name": "Department",
        "description": (
            "Academic department of the college (e.g., Computer Science & Engineering). "
            "All students, faculty, and subjects belong to a department."
        ),
        "primary_table": "departments",
        "join_key": "id",
        "aliases": ["dept", "branch", "division", "school"],
        "attributes": ["id", "name", "code", "hod_id", "college_id", "is_active"],
        "business_rules": [
            "Department code (e.g., CSE, ECE, MECH) is the short identifier",
            "Each department has one HOD (Head of Department)",
            "Department comparison queries group by departments.id or departments.name"
        ],
        "display_name": "Department",
    },
    {
        "entity_name": "Program",
        "description": (
            "Academic program offered by a department (e.g., B.E Computer Science, M.E VLSI). "
            "Programs have a fixed duration and number of semesters."
        ),
        "primary_table": "programs",
        "join_key": "id",
        "aliases": ["course", "degree", "programme", "curriculum"],
        "attributes": [
            "id", "department_id", "name", "code", "type",
            "duration_years", "total_semesters", "intake_capacity", "is_nba_accredited"
        ],
        "business_rules": [
            "UG programs: 4 years, 8 semesters",
            "PG programs: 2 years, 4 semesters",
            "NBA accreditation applies at program level, not institution level"
        ],
        "display_name": "Program",
    },
    {
        "entity_name": "Subject",
        "description": (
            "A subject or course taught in a specific semester of a program. "
            "Subjects have exam types (CIA1/2/3, semester-end, practical)."
        ),
        "primary_table": "subjects",
        "join_key": "id",
        "aliases": ["course", "paper", "module", "paper_code", "unit"],
        "attributes": [
            "id", "department_id", "program_id", "code", "name",
            "type", "semester_number", "credits", "is_elective", "is_lab"
        ],
        "business_rules": [
            "Subject types: theory, practical, theory_cum_practical, project, seminar, mooc",
            "Lab subjects have practical_hours > 0",
            "Elective subjects have is_elective = TRUE",
            "Subject code is the official university subject code"
        ],
        "display_name": "Subject",
    },
    {
        "entity_name": "Semester",
        "description": (
            "A running academic semester tied to a program and academic year. "
            "Semesters have a status: upcoming, ongoing, completed, results_published."
        ),
        "primary_table": "semesters",
        "join_key": "id",
        "aliases": ["term", "sem", "session", "academic_term"],
        "attributes": [
            "id", "academic_year_id", "program_id", "semester_number",
            "start_date", "end_date", "status", "working_days"
        ],
        "business_rules": [
            "Odd semesters (1,3,5,7) run July–November",
            "Even semesters (2,4,6,8) run January–May",
            "Current semester has status = 'ongoing'",
            "Students reference semester via current_semester column"
        ],
        "display_name": "Semester",
    },
    {
        "entity_name": "AcademicYear",
        "description": (
            "Academic year cycle (e.g., 2024-25). "
            "Groups all semesters for that academic year across all programs."
        ),
        "primary_table": "academic_years",
        "join_key": "id",
        "aliases": ["year", "session", "academic_session", "batch_year"],
        "attributes": ["id", "college_id", "label", "start_date", "end_date", "is_current"],
        "business_rules": [
            "Label format is 'YYYY-YY' (e.g., 2024-25)",
            "Only one academic year can have is_current = TRUE per college",
            "Annual reports span the full academic year"
        ],
        "display_name": "Academic Year",
    },
    {
        "entity_name": "Attendance",
        "description": (
            "Attendance record for a student for a specific subject on a specific date. "
            "Status: present, absent, od (on-duty), medical_leave, duty_leave."
        ),
        "primary_table": "attendance_records",
        "join_key": "id",
        "aliases": ["presence", "attendance_record", "class_attendance"],
        "attributes": [
            "id", "student_id", "subject_id", "semester_id",
            "date", "period", "status", "marked_by"
        ],
        "business_rules": [
            "Minimum attendance required: 75%",
            "OD (on-duty) counts as present for attendance eligibility",
            "Medical leave counts as absent for percentage calculation",
            "Attendance percentage = present_count / total_classes * 100",
            "attendance_summary materialized view has pre-computed percentages"
        ],
        "display_name": "Attendance",
    },
    {
        "entity_name": "Assessment",
        "description": (
            "Marks/assessment record for a student in a subject for a specific exam type. "
            "Exam types: cia1, cia2, cia3, model, semester_end, practical, viva, assignment, quiz."
        ),
        "primary_table": "marks_records",
        "join_key": "id",
        "aliases": [
            "marks", "exam", "test", "assessment_record", "grade",
            "marks_record", "score", "result"
        ],
        "attributes": [
            "id", "student_id", "subject_id", "semester_id",
            "exam_type", "marks_obtained", "max_marks", "percentage",
            "grade_points", "grade", "is_absent", "is_withheld"
        ],
        "business_rules": [
            "CIA = Continuous Internal Assessment (cia1, cia2, cia3)",
            "Pass percentage: 40% for internal exams, 50% for semester-end",
            "Grade F or U means the student has failed/arrear",
            "marks_summary materialized view has aggregated CIA average and arrear flags",
            "CGPA is computed from grade_points across all subjects"
        ],
        "display_name": "Assessment",
    },
    {
        "entity_name": "Section",
        "description": (
            "A section is a division of students within a semester of a program. "
            "Referenced as 'section' column in students and enrollment tables."
        ),
        "primary_table": "students",
        "join_key": "section",
        "aliases": ["division", "class_section", "group"],
        "attributes": ["section", "semester", "department_id", "program_id"],
        "business_rules": [
            "Sections are labelled A, B, C etc.",
            "Faculty subject assignments can be section-specific"
        ],
        "display_name": "Section",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Domain Knowledge — Relationships (join paths)
# ─────────────────────────────────────────────────────────────────────────────

RELATIONSHIPS: list[dict[str, Any]] = [
    {"from_entity": "Student", "relationship": "belongs_to", "to_entity": "Department",
     "join_sql": "JOIN departments d ON d.id = s.department_id",
     "description": "Student belongs to a department", "confidence": 1.0},
    {"from_entity": "Student", "relationship": "belongs_to", "to_entity": "Program",
     "join_sql": "JOIN programs p ON p.id = s.program_id",
     "description": "Student is enrolled in a program", "confidence": 1.0},
    {"from_entity": "Student", "relationship": "has_many", "to_entity": "Attendance",
     "join_sql": "JOIN attendance_records ar ON ar.student_id = s.id",
     "description": "Student has many attendance records", "confidence": 1.0},
    {"from_entity": "Student", "relationship": "has_many", "to_entity": "Assessment",
     "join_sql": "JOIN marks_records m ON m.student_id = s.id",
     "description": "Student has many marks/assessment records", "confidence": 1.0},
    {"from_entity": "Attendance", "relationship": "belongs_to", "to_entity": "Student",
     "join_sql": "JOIN students s ON s.id = ar.student_id",
     "description": "Attendance record belongs to a student", "confidence": 1.0},
    {"from_entity": "Attendance", "relationship": "belongs_to", "to_entity": "Subject",
     "join_sql": "JOIN subjects sub ON sub.id = ar.subject_id",
     "description": "Attendance record is for a subject", "confidence": 1.0},
    {"from_entity": "Assessment", "relationship": "belongs_to", "to_entity": "Student",
     "join_sql": "JOIN students s ON s.id = m.student_id",
     "description": "Marks record belongs to a student", "confidence": 1.0},
    {"from_entity": "Assessment", "relationship": "belongs_to", "to_entity": "Subject",
     "join_sql": "JOIN subjects sub ON sub.id = m.subject_id",
     "description": "Marks record is for a subject", "confidence": 1.0},
    {"from_entity": "Subject", "relationship": "belongs_to", "to_entity": "Department",
     "join_sql": "JOIN departments d ON d.id = sub.department_id",
     "description": "Subject belongs to a department", "confidence": 1.0},
    {"from_entity": "Subject", "relationship": "belongs_to", "to_entity": "Program",
     "join_sql": "JOIN programs p ON p.id = sub.program_id",
     "description": "Subject belongs to a program", "confidence": 1.0},
    {"from_entity": "Faculty", "relationship": "belongs_to", "to_entity": "Department",
     "join_sql": "JOIN departments d ON d.id = u.department_id",
     "description": "Faculty member belongs to a department", "confidence": 1.0},
    {"from_entity": "Faculty", "relationship": "teaches", "to_entity": "Subject",
     "join_sql": "JOIN faculty_subject_assignments fsa ON fsa.user_id = u.id JOIN subjects sub ON sub.id = fsa.subject_id",
     "description": "Faculty teaches subjects via assignment table", "confidence": 1.0},
    {"from_entity": "Semester", "relationship": "belongs_to", "to_entity": "AcademicYear",
     "join_sql": "JOIN academic_years ay ON ay.id = sem.academic_year_id",
     "description": "Semester belongs to an academic year", "confidence": 1.0},
    {"from_entity": "Semester", "relationship": "belongs_to", "to_entity": "Program",
     "join_sql": "JOIN programs p ON p.id = sem.program_id",
     "description": "Semester belongs to a program", "confidence": 1.0},
    {"from_entity": "Student", "relationship": "has_summary", "to_entity": "Attendance",
     "join_sql": "JOIN attendance_summary att_sum ON att_sum.student_id = s.id",
     "description": "Use attendance_summary materialized view for aggregate attendance", "confidence": 0.95},
    {"from_entity": "Student", "relationship": "has_summary", "to_entity": "Assessment",
     "join_sql": "JOIN marks_summary ms ON ms.student_id = s.id",
     "description": "Use marks_summary materialized view for aggregate marks", "confidence": 0.95},
]


# ─────────────────────────────────────────────────────────────────────────────
# Domain Knowledge — Academic Terminology
# ─────────────────────────────────────────────────────────────────────────────

TERMINOLOGY: list[dict[str, Any]] = [
    {"term": "CIA", "full_form": "Continuous Internal Assessment",
     "definition": "Internal examinations conducted throughout the semester. Includes CIA1, CIA2, CIA3. Each has different maximum marks.",
     "category": "exam_type", "db_mapping": "cia1, cia2, cia3", "db_table": "marks_records",
     "aliases": ["internal exam", "internal assessment", "cia exam", "internal test"],
     "usage_examples": ["CIA1 marks", "CIA average", "show CIA scores"]},
    {"term": "CIA1", "full_form": "Continuous Internal Assessment 1",
     "definition": "First internal assessment exam of the semester.",
     "category": "exam_type", "db_mapping": "cia1", "db_table": "marks_records",
     "aliases": ["internal 1", "first internal", "IA1"], "usage_examples": ["CIA1 marks", "first internal exam marks"]},
    {"term": "CIA2", "full_form": "Continuous Internal Assessment 2",
     "definition": "Second internal assessment exam of the semester.",
     "category": "exam_type", "db_mapping": "cia2", "db_table": "marks_records",
     "aliases": ["internal 2", "second internal", "IA2"], "usage_examples": ["CIA2 scores", "second test results"]},
    {"term": "CIA3", "full_form": "Continuous Internal Assessment 3",
     "definition": "Third internal assessment exam of the semester. Often the last internal before the end-semester exam.",
     "category": "exam_type", "db_mapping": "cia3", "db_table": "marks_records",
     "aliases": ["internal 3", "third internal", "IA3"], "usage_examples": ["CIA3 performance", "model exam scores"]},
    {"term": "CGPA", "full_form": "Cumulative Grade Point Average",
     "definition": "Overall academic performance metric across all semesters. Computed from grade points on a 10-point scale.",
     "category": "metric", "db_mapping": "AVG(grade_points)", "db_table": "marks_records",
     "aliases": ["gpa", "grade point average", "cumulative gpa", "overall gpa"],
     "usage_examples": ["student CGPA", "CGPA above 8", "top CGPA students"]},
    {"term": "OD", "full_form": "On Duty",
     "definition": "Authorized absence where a student is on official college duty (e.g., sports, technical events). Counted as present for attendance eligibility.",
     "category": "status", "db_mapping": "od", "db_table": "attendance_records",
     "aliases": ["on duty", "official duty", "duty leave", "permitted absence"],
     "usage_examples": ["OD count", "students on duty", "OD attendance"]},
    {"term": "NAAC", "full_form": "National Assessment and Accreditation Council",
     "definition": "Institution-level accreditation body in India. Grants grades A++, A+, A, B++, B+, B, C. Institutions submit Self-Study Reports for assessment.",
     "category": "accreditation", "db_mapping": "naac_grade", "db_table": "colleges",
     "aliases": ["national accreditation", "naac grade", "naac score", "naac rating"],
     "usage_examples": ["NAAC criteria", "NAAC report", "NAAC compliance data"]},
    {"term": "NBA", "full_form": "National Board of Accreditation",
     "definition": "Program-level accreditation for engineering/technical programs. NBA accreditation is per-program, not institution-wide.",
     "category": "accreditation", "db_mapping": "is_nba_accredited", "db_table": "programs",
     "aliases": ["nba accreditation", "program accreditation"],
     "usage_examples": ["NBA accredited programs", "NBA report", "NBA SAR"]},
    {"term": "NIRF", "full_form": "National Institutional Ranking Framework",
     "definition": "India's national ranking framework for educational institutions published annually by MHRD. Covers multiple parameters including Teaching & Learning, Research, etc.",
     "category": "accreditation", "db_mapping": None, "db_table": None,
     "aliases": ["national ranking", "institutional ranking", "india ranking"],
     "usage_examples": ["NIRF ranking data", "NIRF parameters", "NIRF report"]},
    {"term": "Arrear", "full_form": None,
     "definition": "A subject in which a student has scored below the passing mark (grade F or U) and needs to re-appear. Also called backlog.",
     "category": "status", "db_mapping": "grade IN ('F', 'U')", "db_table": "marks_records",
     "aliases": ["backlog", "failed subject", "pending subject", "fail"],
     "usage_examples": ["students with arrears", "arrear count", "clear arrear", "backlog students"]},
    {"term": "Detained", "full_form": None,
     "definition": "A student barred from writing the end-semester examination due to attendance below the minimum threshold (75%).",
     "category": "status", "db_mapping": "detained", "db_table": "students",
     "aliases": ["detention", "barred", "not eligible", "attendance shortage"],
     "usage_examples": ["detained students", "students with detention", "eligible students"]},
    {"term": "Lateral Entry", "full_form": None,
     "definition": "Students who join engineering directly into the 3rd semester (2nd year) based on a diploma qualification, skipping 1st and 2nd semesters.",
     "category": "status", "db_mapping": "lateral_entry = TRUE", "db_table": "students",
     "aliases": ["LE", "lateral", "diploma lateral", "direct admission"],
     "usage_examples": ["lateral entry students", "LE batch performance"]},
    {"term": "Pass Mark", "full_form": None,
     "definition": "Minimum marks required to pass a subject. 40% for internal assessments (CIA), 50% for semester-end exams.",
     "category": "policy", "db_mapping": "pass_marks", "db_table": "exam_schedules",
     "aliases": ["passing marks", "minimum marks", "pass percentage", "cutoff"],
     "usage_examples": ["below pass mark", "failed students", "at risk"]},
    {"term": "At Risk", "full_form": None,
     "definition": "Students identified as at risk of academic failure based on computed risk score > 60. Risk factors: low attendance, low marks, multiple arrears.",
     "category": "metric", "db_mapping": "risk_score > 60", "db_table": "students",
     "aliases": ["high risk", "risk students", "struggling students", "likely to fail"],
     "usage_examples": ["at-risk students", "find at-risk", "high risk students", "identify risk"]},
    {"term": "Risk Score", "full_form": None,
     "definition": "A computed score (0-100) representing a student's academic risk. Above 60 = HIGH, above 80 = CRITICAL. Based on attendance (40%), marks (40%), arrears (20%).",
     "category": "metric", "db_mapping": "risk_score", "db_table": "students",
     "aliases": ["risk", "academic risk", "failure probability", "risk index"],
     "usage_examples": ["risk score above 80", "critical students", "rank by risk"]},
    {"term": "HOD", "full_form": "Head of Department",
     "definition": "The senior faculty member who leads and administers a department. Has access to all department-level data in the platform.",
     "category": "role", "db_mapping": "role = 'hod'", "db_table": "users",
     "aliases": ["head of department", "department head", "hod faculty"],
     "usage_examples": ["HOD report", "HOD dashboard", "notify HOD"]},
    {"term": "Semester End Exam", "full_form": None,
     "definition": "The university-conducted end-semester examination at the end of each semester. Maximum marks: 100, Pass: 50.",
     "category": "exam_type", "db_mapping": "semester_end", "db_table": "marks_records",
     "aliases": ["end sem", "university exam", "final exam", "semester exam", "ESE"],
     "usage_examples": ["semester end marks", "university exam results", "end sem performance"]},
    {"term": "Section", "full_form": None,
     "definition": "A division of students within a semester class. Usually labelled A, B, C. Used to split large classes for attendance and teaching.",
     "category": "academic", "db_mapping": "section", "db_table": "students",
     "aliases": ["class section", "division", "group", "batch section"],
     "usage_examples": ["section A attendance", "compare sections", "section-wise performance"]},
    {"term": "Batch", "full_form": None,
     "definition": "The year range of a student's enrollment (e.g., '2021-25'). Students admitted the same year belong to the same batch.",
     "category": "academic", "db_mapping": "batch", "db_table": "students",
     "aliases": ["year of admission", "admission batch", "student batch"],
     "usage_examples": ["2021 batch performance", "current batch", "batch-wise comparison"]},
    {"term": "Attendance Percentage", "full_form": None,
     "definition": "The ratio of classes attended to total classes conducted, expressed as a percentage. Minimum required: 75%.",
     "category": "metric", "db_mapping": "attendance_pct", "db_table": "attendance_summary",
     "aliases": ["attendance %", "attendance rate", "presence percentage", "attendance ratio"],
     "usage_examples": ["attendance percentage below 75", "average attendance", "attendance trend"]},
]


# ─────────────────────────────────────────────────────────────────────────────
# Domain Knowledge — Canonical Query Examples (Query Memory Seed)
# ─────────────────────────────────────────────────────────────────────────────

QUERY_EXAMPLES: list[dict[str, Any]] = [
    {
        "question": "Show attendance trends by department",
        "generated_sql": """
SELECT d.name AS department,
       TO_CHAR(ar.date, 'YYYY-MM') AS month,
       ROUND(COUNT(CASE WHEN ar.status IN ('present','od','duty_leave') THEN 1 END) * 100.0
             / NULLIF(COUNT(*), 0)::numeric, 2) AS attendance_pct,
       COUNT(DISTINCT ar.student_id) AS student_count
FROM attendance_records ar
JOIN students s ON s.id = ar.student_id
JOIN departments d ON d.id = s.department_id
WHERE ar.date >= NOW() - INTERVAL '6 months'
GROUP BY d.name, TO_CHAR(ar.date, 'YYYY-MM')
ORDER BY d.name, month""",
        "result_summary": "Monthly attendance percentage grouped by department for the last 6 months",
        "entities_used": ["Student", "Attendance", "Department"],
        "metrics_used": ["attendance_pct"],
        "tables_used": ["attendance_records", "students", "departments"],
        "agent_used": "query", "query_type": "trend", "feedback_score": 1.0,
    },
    {
        "question": "Find at-risk students with low attendance",
        "generated_sql": """
SELECT s.name, s.roll_number, d.name AS department,
       s.current_semester, s.risk_score,
       ROUND(COUNT(CASE WHEN ar.status IN ('present','od') THEN 1 END) * 100.0
             / NULLIF(COUNT(ar.id), 0)::numeric, 2) AS attendance_pct
FROM students s
JOIN departments d ON d.id = s.department_id
LEFT JOIN attendance_records ar ON ar.student_id = s.id
WHERE s.status = 'active'
GROUP BY s.id, s.name, s.roll_number, d.name, s.current_semester, s.risk_score
HAVING ROUND(COUNT(CASE WHEN ar.status IN ('present','od') THEN 1 END) * 100.0
             / NULLIF(COUNT(ar.id), 0)::numeric, 2) < 75
ORDER BY attendance_pct ASC""",
        "result_summary": "Active students with attendance below 75%, ordered by lowest attendance",
        "entities_used": ["Student", "Attendance", "Department"],
        "metrics_used": ["attendance_pct", "risk_score"],
        "tables_used": ["students", "attendance_records", "departments"],
        "agent_used": "query", "query_type": "predictive", "feedback_score": 1.0,
    },
    {
        "question": "Compare department-wise average marks performance",
        "generated_sql": """
SELECT d.name AS department,
       ROUND(AVG(m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0))::numeric, 2) AS avg_marks_pct,
       COUNT(DISTINCT m.student_id) AS student_count,
       COUNT(CASE WHEN m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0) < 40 THEN 1 END) AS below_pass
FROM marks_records m
JOIN students s ON s.id = m.student_id
JOIN departments d ON d.id = s.department_id
GROUP BY d.name
ORDER BY avg_marks_pct DESC""",
        "result_summary": "Average marks percentage and failure count by department",
        "entities_used": ["Assessment", "Student", "Department"],
        "metrics_used": ["avg_marks_pct"],
        "tables_used": ["marks_records", "students", "departments"],
        "agent_used": "query", "query_type": "comparative", "feedback_score": 1.0,
    },
    {
        "question": "List students with attendance below 75 percent",
        "generated_sql": """
SELECT s.name, s.roll_number, d.name AS department,
       s.current_semester,
       ROUND(COUNT(CASE WHEN ar.status IN ('present','od','duty_leave') THEN 1 END) * 100.0
             / NULLIF(COUNT(ar.id), 0)::numeric, 2) AS attendance_pct,
       COUNT(ar.id) AS total_classes
FROM students s
JOIN departments d ON d.id = s.department_id
LEFT JOIN attendance_records ar ON ar.student_id = s.id
WHERE s.status = 'active'
GROUP BY s.id, s.name, s.roll_number, d.name, s.current_semester
HAVING ROUND(COUNT(CASE WHEN ar.status IN ('present','od','duty_leave') THEN 1 END) * 100.0
             / NULLIF(COUNT(ar.id), 0)::numeric, 2) < 75
ORDER BY attendance_pct ASC""",
        "result_summary": "Students below the 75% attendance threshold",
        "entities_used": ["Student", "Attendance", "Department"],
        "metrics_used": ["attendance_pct"],
        "tables_used": ["students", "attendance_records", "departments"],
        "agent_used": "query", "query_type": "descriptive", "feedback_score": 1.0,
    },
    {
        "question": "Show faculty performance and subjects taught",
        "generated_sql": """
SELECT u.full_name AS faculty_name, u.employee_id,
       d.name AS department,
       COUNT(DISTINCT fsa.subject_id) AS subjects_taught,
       STRING_AGG(DISTINCT sub.name, ', ') AS subject_names
FROM users u
JOIN departments d ON d.id = u.department_id
JOIN faculty_subject_assignments fsa ON fsa.user_id = u.id
JOIN subjects sub ON sub.id = fsa.subject_id
WHERE u.role = 'faculty' AND u.is_active = TRUE
GROUP BY u.id, u.full_name, u.employee_id, d.name
ORDER BY d.name, subjects_taught DESC""",
        "result_summary": "Faculty members with count and list of subjects they teach",
        "entities_used": ["Faculty", "Department", "Subject"],
        "metrics_used": [],
        "tables_used": ["users", "departments", "faculty_subject_assignments", "subjects"],
        "agent_used": "query", "query_type": "descriptive", "feedback_score": 1.0,
    },
    {
        "question": "Compare semester-wise performance for a student",
        "generated_sql": """
SELECT s.name, s.roll_number,
       sem.semester_number,
       ay.label AS academic_year,
       ROUND(AVG(m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0))::numeric, 2) AS avg_marks_pct,
       COUNT(CASE WHEN m.grade IN ('F', 'U') THEN 1 END) AS arrears
FROM students s
JOIN marks_records m ON m.student_id = s.id
JOIN semesters sem ON sem.id = m.semester_id
JOIN academic_years ay ON ay.id = sem.academic_year_id
WHERE s.roll_number = :roll_number
GROUP BY s.name, s.roll_number, sem.semester_number, ay.label
ORDER BY ay.label, sem.semester_number""",
        "result_summary": "Semester-by-semester marks performance for a specific student",
        "entities_used": ["Student", "Assessment", "Semester", "AcademicYear"],
        "metrics_used": ["avg_marks_pct"],
        "tables_used": ["students", "marks_records", "semesters", "academic_years"],
        "agent_used": "query", "query_type": "trend", "feedback_score": 1.0,
    },
    {
        "question": "Generate department performance summary for HOD report",
        "generated_sql": """
SELECT d.name AS department,
       COUNT(DISTINCT s.id) AS total_students,
       ROUND(AVG(CASE WHEN ar.status IN ('present','od') THEN 100.0 ELSE 0 END)::numeric, 2) AS avg_attendance_pct,
       ROUND(AVG(m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0))::numeric, 2) AS avg_marks_pct,
       COUNT(CASE WHEN s.risk_score >= 61 THEN 1 END) AS high_risk_students,
       COUNT(CASE WHEN s.risk_score >= 81 THEN 1 END) AS critical_students
FROM departments d
LEFT JOIN students s ON s.department_id = d.id AND s.status = 'active'
LEFT JOIN attendance_records ar ON ar.student_id = s.id
LEFT JOIN marks_records m ON m.student_id = s.id
GROUP BY d.name, d.code
ORDER BY d.name""",
        "result_summary": "Department-wide summary of attendance, marks, and risk for HOD report",
        "entities_used": ["Department", "Student", "Attendance", "Assessment"],
        "metrics_used": ["avg_attendance_pct", "avg_marks_pct", "risk_score"],
        "tables_used": ["departments", "students", "attendance_records", "marks_records"],
        "agent_used": "report", "query_type": "report", "feedback_score": 1.0,
    },
    {
        "question": "Show students with declining performance across semesters",
        "generated_sql": """
WITH sem_avg AS (
    SELECT m.student_id,
           sem.semester_number,
           ROUND(AVG(m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0))::numeric, 2) AS avg_pct
    FROM marks_records m
    JOIN semesters sem ON sem.id = m.semester_id
    GROUP BY m.student_id, sem.semester_number
)
SELECT s.name, s.roll_number, d.name AS department,
       MAX(CASE WHEN sa.semester_number = 1 THEN sa.avg_pct END) AS sem1_avg,
       MAX(CASE WHEN sa.semester_number = 2 THEN sa.avg_pct END) AS sem2_avg,
       MAX(CASE WHEN sa.semester_number = 3 THEN sa.avg_pct END) AS sem3_avg
FROM sem_avg sa
JOIN students s ON s.id = sa.student_id
JOIN departments d ON d.id = s.department_id
GROUP BY s.id, s.name, s.roll_number, d.name
HAVING MAX(CASE WHEN sa.semester_number = 3 THEN sa.avg_pct END) <
       MAX(CASE WHEN sa.semester_number = 1 THEN sa.avg_pct END) - 10
ORDER BY d.name""",
        "result_summary": "Students whose semester marks have declined by more than 10% from sem 1 to sem 3",
        "entities_used": ["Student", "Assessment", "Semester", "Department"],
        "metrics_used": ["avg_marks_pct"],
        "tables_used": ["marks_records", "students", "departments", "semesters"],
        "agent_used": "performance", "query_type": "predictive", "feedback_score": 1.0,
    },
    {
        "question": "Show subject pass rates ranked lowest to highest",
        "generated_sql": """
SELECT sub.name AS subject, sub.code AS subject_code,
       d.name AS department, sub.semester_number,
       COUNT(m.id) AS total_students,
       COUNT(CASE WHEN m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0) >= 40 THEN 1 END) AS passed,
       ROUND(COUNT(CASE WHEN m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0) >= 40 THEN 1 END)
             * 100.0 / NULLIF(COUNT(m.id), 0)::numeric, 2) AS pass_rate
FROM subjects sub
JOIN departments d ON d.id = sub.department_id
LEFT JOIN marks_records m ON m.subject_id = sub.id
GROUP BY sub.id, sub.name, sub.code, d.name, sub.semester_number
HAVING COUNT(m.id) > 0
ORDER BY pass_rate ASC
LIMIT 20""",
        "result_summary": "Bottom 20 subjects by pass rate, showing highest-failure subjects",
        "entities_used": ["Subject", "Assessment", "Department"],
        "metrics_used": ["pass_rate"],
        "tables_used": ["subjects", "marks_records", "departments"],
        "agent_used": "query", "query_type": "ranking", "feedback_score": 1.0,
    },
    {
        "question": "Count critical students by department",
        "generated_sql": """
SELECT d.name AS department,
       COUNT(CASE WHEN s.risk_score >= 81 THEN 1 END) AS critical,
       COUNT(CASE WHEN s.risk_score BETWEEN 61 AND 80 THEN 1 END) AS high,
       COUNT(CASE WHEN s.risk_score BETWEEN 31 AND 60 THEN 1 END) AS medium,
       COUNT(CASE WHEN s.risk_score < 31 THEN 1 END) AS low,
       COUNT(*) AS total
FROM students s
JOIN departments d ON d.id = s.department_id
WHERE s.status = 'active'
GROUP BY d.name
ORDER BY critical DESC""",
        "result_summary": "Risk category breakdown (CRITICAL/HIGH/MEDIUM/LOW) by department",
        "entities_used": ["Student", "Department"],
        "metrics_used": ["risk_score"],
        "tables_used": ["students", "departments"],
        "agent_used": "performance", "query_type": "ranking", "feedback_score": 1.0,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeSeeder
# ─────────────────────────────────────────────────────────────────────────────

class KnowledgeSeeder:
    """
    Seeds the Agent Intelligence Layer knowledge store with CollegeMS domain knowledge.
    Safe to call multiple times — uses INSERT ... ON CONFLICT DO NOTHING.
    """

    @classmethod
    async def seed_if_empty(cls, db: AsyncSession) -> bool:
        """
        Check if knowledge store is empty; if so, seed it.
        Returns True if seeding was performed.
        """
        result = await db.execute(text("SELECT COUNT(*) FROM semantic_entities"))
        count = result.scalar()
        if count and count > 0:
            logger.info(f"Knowledge store already has {count} entities — skipping seed")
            return False

        logger.info("Knowledge store is empty — seeding now...")
        await cls.seed_all(db)
        return True

    @classmethod
    async def seed_all(cls, db: AsyncSession) -> dict:
        """Full seeding run. Returns counts of records inserted."""
        counts = {}
        counts["entities"] = await cls._seed_entities(db)
        counts["relationships"] = await cls._seed_relationships(db)
        counts["terminology"] = await cls._seed_terminology(db)
        counts["query_examples"] = await cls._seed_query_examples(db)
        await db.commit()

        # Generate all embeddings
        from app.intelligence.embedding_service import get_embedding_service
        svc = get_embedding_service()
        embed_counts = await svc.update_all_embeddings(db)
        counts["embeddings"] = embed_counts

        logger.info(f"Knowledge seeding complete: {counts}")
        return counts

    @classmethod
    async def _seed_entities(cls, db: AsyncSession) -> int:
        inserted = 0
        for entity in ENTITIES:
            try:
                import json
                result = await db.execute(
                    text("""
                        INSERT INTO semantic_entities
                            (entity_name, description, primary_table, join_key,
                             aliases, attributes, business_rules, display_name)
                        VALUES
                            (:name, :desc, :table, :key,
                             :aliases::jsonb, :attrs::jsonb, :rules::jsonb, :display)
                        ON CONFLICT (entity_name) DO UPDATE
                          SET description    = EXCLUDED.description,
                              aliases        = EXCLUDED.aliases,
                              attributes     = EXCLUDED.attributes,
                              business_rules = EXCLUDED.business_rules,
                              updated_at     = NOW()
                        RETURNING id
                    """),
                    {
                        "name": entity["entity_name"],
                        "desc": entity["description"],
                        "table": entity["primary_table"],
                        "key": entity.get("join_key"),
                        "aliases": json.dumps(entity.get("aliases", [])),
                        "attrs": json.dumps(entity.get("attributes", [])),
                        "rules": json.dumps(entity.get("business_rules", [])),
                        "display": entity.get("display_name", entity["entity_name"]),
                    }
                )
                if result.fetchone():
                    inserted += 1
            except Exception as e:
                logger.warning(f"Failed to seed entity {entity['entity_name']}: {e}")
        logger.info(f"Seeded {inserted} entities")
        return inserted

    @classmethod
    async def _seed_relationships(cls, db: AsyncSession) -> int:
        inserted = 0
        for rel in RELATIONSHIPS:
            try:
                await db.execute(
                    text("""
                        INSERT INTO semantic_relationships
                            (from_entity, relationship, to_entity, join_sql, description, confidence)
                        VALUES
                            (:from_e, :rel, :to_e, :join_sql, :desc, :conf)
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "from_e": rel["from_entity"],
                        "rel": rel["relationship"],
                        "to_e": rel["to_entity"],
                        "join_sql": rel["join_sql"],
                        "desc": rel.get("description"),
                        "conf": rel.get("confidence", 1.0),
                    }
                )
                inserted += 1
            except Exception as e:
                logger.warning(f"Failed to seed relationship: {e}")
        logger.info(f"Seeded {inserted} relationships")
        return inserted

    @classmethod
    async def _seed_terminology(cls, db: AsyncSession) -> int:
        import json
        inserted = 0
        for term in TERMINOLOGY:
            try:
                await db.execute(
                    text("""
                        INSERT INTO academic_terminology
                            (term, full_form, definition, category,
                             db_mapping, db_table, aliases, usage_examples)
                        VALUES
                            (:term, :full_form, :def, :cat,
                             :db_mapping, :db_table, :aliases::jsonb, :usage::jsonb)
                        ON CONFLICT (term) DO UPDATE
                          SET definition    = EXCLUDED.definition,
                              db_mapping    = EXCLUDED.db_mapping,
                              aliases       = EXCLUDED.aliases,
                              usage_examples = EXCLUDED.usage_examples
                    """),
                    {
                        "term": term["term"],
                        "full_form": term.get("full_form"),
                        "def": term["definition"],
                        "cat": term.get("category"),
                        "db_mapping": term.get("db_mapping"),
                        "db_table": term.get("db_table"),
                        "aliases": json.dumps(term.get("aliases", [])),
                        "usage": json.dumps(term.get("usage_examples", [])),
                    }
                )
                inserted += 1
            except Exception as e:
                logger.warning(f"Failed to seed term {term['term']}: {e}")
        logger.info(f"Seeded {inserted} terminology entries")
        return inserted

    @classmethod
    async def _seed_query_examples(cls, db: AsyncSession) -> int:
        import json
        inserted = 0
        for qe in QUERY_EXAMPLES:
            try:
                await db.execute(
                    text("""
                        INSERT INTO query_examples
                            (question, generated_sql, result_summary,
                             entities_used, metrics_used, tables_used,
                             agent_used, query_type, feedback_score, success, source)
                        VALUES
                            (:question, :sql, :summary,
                             :entities::jsonb, :metrics::jsonb, :tables::jsonb,
                             :agent, :qtype, :score, TRUE, 'system')
                        ON CONFLICT DO NOTHING
                        RETURNING id
                    """),
                    {
                        "question": qe["question"],
                        "sql": qe["generated_sql"].strip(),
                        "summary": qe.get("result_summary"),
                        "entities": json.dumps(qe.get("entities_used", [])),
                        "metrics": json.dumps(qe.get("metrics_used", [])),
                        "tables": json.dumps(qe.get("tables_used", [])),
                        "agent": qe.get("agent_used"),
                        "qtype": qe.get("query_type"),
                        "score": qe.get("feedback_score", 1.0),
                    }
                )
                inserted += 1
            except Exception as e:
                logger.warning(f"Failed to seed query example: {e}")
        logger.info(f"Seeded {inserted} query examples")
        return inserted

    @classmethod
    async def re_seed_terminology(cls, db: AsyncSession) -> int:
        """Re-seed only terminology (useful for updates)."""
        count = await cls._seed_terminology(db)
        await db.commit()
        return count
