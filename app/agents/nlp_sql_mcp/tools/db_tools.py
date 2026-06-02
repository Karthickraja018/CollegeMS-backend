"""
Schema description and database query tools for Model Context Protocol.
"""
import json
from typing import Optional
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.utils.sql_validator import validate_sql as app_validate_sql, SQLValidationError

# Accurate database schema mapping matching SQLAlchemy models
SCHEMA_METADATA = {
    "departments": {
        "description": "College departments listing.",
        "columns": {
            "id": "INTEGER (Primary Key) - Unique identifier.",
            "name": "VARCHAR (Unique) - Full name of the department.",
            "code": "VARCHAR (Unique) - Short abbreviation code (e.g. CSE, ECE).",
        }
    },
    "users": {
        "description": "System accounts for admins, principals, HODs, and faculty.",
        "columns": {
            "id": "INTEGER (Primary Key) - Unique identifier.",
            "email": "VARCHAR (Unique) - User login email address.",
            "full_name": "VARCHAR - Full name of the user.",
            "role": "VARCHAR - User role ('admin', 'principal', 'hod', 'faculty').",
            "department_id": "INTEGER (Foreign Key -> departments.id) - Associated department.",
            "is_active": "BOOLEAN - Account active status.",
        }
    },
    "students": {
        "description": "Students registered in the system.",
        "columns": {
            "id": "INTEGER (Primary Key) - Unique identifier.",
            "roll_number": "VARCHAR (Unique) - Student's roll number (e.g. CS2001).",
            "name": "VARCHAR - Full name of the student.",
            "email": "VARCHAR (Unique) - Student's email address.",
            "department_id": "INTEGER (Foreign Key -> departments.id) - Associated department.",
            "semester": "INTEGER - Current semester (1 to 8).",
            "batch": "VARCHAR - Student cohort batch year (e.g., 2023-2027).",
            "section": "VARCHAR (Nullable) - Class section letter (e.g., A, B).",
            "risk_score": "FLOAT (Nullable) - Calculated academic failure risk level.",
        }
    },
    "subjects": {
        "description": "Academic courses offered.",
        "columns": {
            "id": "INTEGER (Primary Key) - Unique identifier.",
            "code": "VARCHAR (Unique) - Subject code (e.g. CS8501).",
            "name": "VARCHAR - Full name of the subject.",
            "department_id": "INTEGER (Foreign Key -> departments.id) - Offering department.",
            "semester": "INTEGER - Academic semester in which subject is taught.",
            "credits": "INTEGER - Subject credit weight.",
        }
    },
    "attendance": {
        "description": "Student daily attendance logs.",
        "columns": {
            "id": "INTEGER (Primary Key) - Unique identifier.",
            "student_id": "INTEGER (Foreign Key -> students.id) - Reference to student.",
            "subject_id": "INTEGER (Foreign Key -> subjects.id) - Reference to subject.",
            "date": "DATE - Date of class.",
            "status": "VARCHAR - Attendance status ('present' or 'absent').",
        }
    },
    "marks": {
        "description": "Academic exam marks achievements.",
        "columns": {
            "id": "INTEGER (Primary Key) - Unique identifier.",
            "student_id": "INTEGER (Foreign Key -> students.id) - Reference to student.",
            "subject_id": "INTEGER (Foreign Key -> subjects.id) - Reference to subject.",
            "semester": "INTEGER - Academic semester.",
            "exam_type": "VARCHAR - Exam categories ('internal1', 'internal2', 'internal3', 'semester_end', 'practical', 'assignment').",
            "marks_obtained": "FLOAT - Scored marks.",
            "max_marks": "FLOAT - Maximum possible marks.",
        }
    }
}


def tool_search_schema(keyword: Optional[str] = None) -> str:
    """
    Search database schema details (table structures, column definitions, data types).
    Use this to find which tables or columns to query for specific fields.
    """
    if not keyword:
        return json.dumps(SCHEMA_METADATA, indent=2)
    
    keyword_lower = keyword.lower()
    filtered = {}
    for table_name, meta in SCHEMA_METADATA.items():
        if keyword_lower in table_name.lower() or keyword_lower in meta["description"].lower():
            filtered[table_name] = meta
            continue
        
        matching_cols = {}
        for col_name, col_desc in meta["columns"].items():
            if keyword_lower in col_name.lower() or keyword_lower in col_desc.lower():
                matching_cols[col_name] = col_desc
        
        if matching_cols:
            filtered[table_name] = {
                "description": meta["description"],
                "columns": matching_cols
            }
            
    return json.dumps(filtered, indent=2) if filtered else f"No tables or columns match the keyword: '{keyword}'"


async def tool_execute_sql(sql: str) -> str:
    """
    Execute a validated SQL SELECT statement and return results in JSON.
    """
    # Verify SQL safety
    try:
        app_validate_sql(sql)
    except SQLValidationError as e:
        return json.dumps({"error": f"Safety check failed: {str(e)}"})

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text(sql))
            rows = result.fetchall()
            columns = list(result.keys())
            data = [dict(zip(columns, row)) for row in rows]
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": f"Database execution error: {str(e)}"})
