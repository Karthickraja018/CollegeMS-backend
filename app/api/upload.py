"""
Upload API — CSV/Excel import with column mapping and validation.
"""
import io
import json
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user, require_admin
from app.models.user import User, UserRole

router = APIRouter(prefix="/upload", tags=["upload"])


class ColumnMapping(BaseModel):
    dataset: Literal["students", "attendance", "marks", "subjects", "departments"]
    mapping: dict[str, str]  # {csv_column: db_field}


EXPECTED_FIELDS = {
    "students": ["roll_number", "name", "email", "department_id", "semester", "batch"],
    "attendance": ["student_id", "subject_id", "date", "status"],
    "marks": ["student_id", "subject_id", "semester", "exam_type", "marks_obtained", "max_marks"],
    "subjects": ["code", "name", "semester", "department_id", "credits"],
    "departments": ["name", "code"],
}


@router.post("/preview")
async def preview_upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Parse uploaded file and return preview + column names.
    Does NOT write to DB.
    """
    if current_user.role not in [UserRole.admin, UserRole.principal]:
        raise HTTPException(status_code=403, detail="Only admin/principal can upload data")

    content = await file.read()

    try:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content), nrows=100)
        elif file.filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content), nrows=100)
        else:
            raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {str(e)}")

    # Clean column names
    df.columns = [str(c).strip() for c in df.columns]

    return {
        "filename": file.filename,
        "total_rows": len(df),
        "columns": list(df.columns),
        "preview": df.head(10).to_dict(orient="records"),
        "expected_mappings": EXPECTED_FIELDS,
    }


@router.post("/import")
async def import_data(
    file: UploadFile = File(...),
    mapping_json: str = "",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Import data with column mapping. Runs validation then bulk inserts.
    Transactional: rolls back on any error.
    """
    if current_user.role not in [UserRole.admin, UserRole.principal]:
        raise HTTPException(status_code=403, detail="Only admin/principal can import data")

    try:
        mapping_data = json.loads(mapping_json)
        mapping = ColumnMapping(**mapping_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid mapping JSON: {e}")

    content = await file.read()
    try:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"File parse error: {e}")

    # Apply column mapping
    df = df.rename(columns=mapping.mapping)
    df.columns = [str(c).strip() for c in df.columns]

    # Validate required fields present
    required = EXPECTED_FIELDS.get(mapping.dataset, [])
    missing = [f for f in required if f not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns after mapping: {missing}",
        )

    # Row-level validation
    errors = []
    valid_rows = []
    for idx, row in df.iterrows():
        row_errors = []
        for field in required:
            if pd.isna(row.get(field)):
                row_errors.append(f"'{field}' is empty")
        if row_errors:
            errors.append({"row": int(idx) + 2, "errors": row_errors})
        else:
            valid_rows.append(row.to_dict())

    if errors and len(errors) == len(df):
        raise HTTPException(
            status_code=400,
            detail={"message": "All rows failed validation", "errors": errors[:20]},
        )

    # Import valid rows
    imported = 0
    import_errors = []

    from sqlalchemy import text
    for row_data in valid_rows:
        try:
            if mapping.dataset == "students":
                await db.execute(text("""
                    INSERT INTO students (roll_number, name, email, department_id, semester, batch)
                    VALUES (:roll_number, :name, :email, :department_id, :semester, :batch)
                    ON CONFLICT (roll_number) DO UPDATE SET
                        name = EXCLUDED.name,
                        email = EXCLUDED.email,
                        semester = EXCLUDED.semester
                """), row_data)
            elif mapping.dataset == "attendance":
                await db.execute(text("""
                    INSERT INTO attendance (student_id, subject_id, date, status)
                    VALUES (:student_id, :subject_id, :date, :status)
                """), row_data)
            elif mapping.dataset == "marks":
                await db.execute(text("""
                    INSERT INTO marks (student_id, subject_id, semester, exam_type, marks_obtained, max_marks)
                    VALUES (:student_id, :subject_id, :semester, :exam_type, :marks_obtained, :max_marks)
                """), row_data)
            elif mapping.dataset == "subjects":
                await db.execute(text("""
                    INSERT INTO subjects (code, name, semester, department_id, credits)
                    VALUES (:code, :name, :semester, :department_id, :credits)
                    ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
                """), row_data)
            elif mapping.dataset == "departments":
                await db.execute(text("""
                    INSERT INTO departments (name, code)
                    VALUES (:name, :code)
                    ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
                """), row_data)
            imported += 1
        except Exception as e:
            import_errors.append(str(e)[:100])

    await db.commit()

    return {
        "status": "success",
        "dataset": mapping.dataset,
        "total_rows": len(df),
        "imported": imported,
        "skipped": len(errors),
        "validation_errors": errors[:20],
        "import_errors": import_errors[:10],
    }
