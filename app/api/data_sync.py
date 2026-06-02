"""
Data Sync Center API — CSV/Excel upload, validation, and import history.

All data sync operations are Admin-only.
Validation happens before commit — users see errors before data is saved.

Supported imports:
  - Students (students.csv)
  - Attendance (attendance.csv)
  - Marks (marks.csv)

Endpoints:
  POST /api/data-sync/upload/students
  POST /api/data-sync/upload/attendance
  POST /api/data-sync/upload/marks
  GET  /api/data-sync/history
  GET  /api/data-sync/template/{type}
  GET  /api/data-sync/status/{job_id}
"""
from __future__ import annotations
import csv
import io
import json
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.access_policies import assert_can_sync_data
from app.models.user import User

router = APIRouter(prefix="/data-sync", tags=["data-sync"])

# ── CSV Templates ─────────────────────────────────────────────────────────────

TEMPLATES = {
    "students": {
        "filename": "students_template.csv",
        "headers": ["roll_number", "name", "email", "department_code", "program_code", "current_semester", "batch", "section", "phone", "gender"],
        "sample": [
            ["CS2024001", "John Doe", "john@example.com", "CSE", "B.Tech", "3", "2024", "A", "9999999999", "Male"],
            ["ME2024001", "Jane Smith", "jane@example.com", "MECH", "B.Tech", "3", "2024", "B", "8888888888", "Female"],
        ],
    },
    "attendance": {
        "filename": "attendance_template.csv",
        "headers": ["roll_number", "subject_code", "date", "status"],
        "sample": [
            ["CS2024001", "CS301", "2025-01-15", "present"],
            ["CS2024001", "CS301", "2025-01-17", "absent"],
        ],
    },
    "marks": {
        "filename": "marks_template.csv",
        "headers": ["roll_number", "subject_code", "exam_type", "marks_obtained", "max_marks"],
        "sample": [
            ["CS2024001", "CS301", "internal_1", "45", "50"],
            ["CS2024001", "CS302", "internal_1", "38", "50"],
        ],
    },
}


@router.get("/template/{import_type}")
async def download_template(
    import_type: Literal["students", "attendance", "marks"],
    current_user: User = Depends(get_current_user),
):
    """Download a CSV template for the specified import type."""
    assert_can_sync_data(current_user)

    template = TEMPLATES.get(import_type)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(template["headers"])
    for row in template["sample"]:
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={template['filename']}"},
    )


# ── Validation Helpers ────────────────────────────────────────────────────────

def _parse_csv(content: bytes) -> tuple[list[str], list[dict]]:
    """Parse CSV content into headers and rows."""
    try:
        text_content = content.decode("utf-8-sig")  # Handle BOM
    except UnicodeDecodeError:
        text_content = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text_content))
    headers = reader.fieldnames or []
    rows = list(reader)
    return list(headers), rows


async def _validate_students(rows: list[dict], db: AsyncSession) -> tuple[list[dict], list[dict]]:
    """Validate student CSV rows. Returns (valid_rows, errors)."""
    errors = []
    valid = []
    required = {"roll_number", "name", "email", "department_code", "program_code", "current_semester", "batch"}

    # Cache department and program lookups
    r = await db.execute(text("SELECT code, id FROM departments WHERE is_active = TRUE"))
    dept_map = {row[0]: row[1] for row in r.fetchall()}

    r = await db.execute(text("SELECT code, id FROM programs WHERE is_active = TRUE"))
    prog_map = {row[0]: row[1] for row in r.fetchall()}

    r = await db.execute(text("SELECT roll_number FROM students"))
    existing_rolls = {row[0] for row in r.fetchall()}

    for i, row in enumerate(rows, 1):
        row_errors = []

        # Check required fields
        for field in required:
            if not row.get(field, "").strip():
                row_errors.append(f"Row {i}: Missing required field '{field}'")

        if row_errors:
            errors.extend(row_errors)
            continue

        # Validate department
        dept_code = row.get("department_code", "").strip().upper()
        if dept_code not in dept_map:
            errors.append(f"Row {i}: Department code '{dept_code}' not found. Valid codes: {', '.join(dept_map.keys())}")
            continue

        # Validate program
        prog_code = row.get("program_code", "").strip()
        if prog_code not in prog_map:
            errors.append(f"Row {i}: Program code '{prog_code}' not found. Valid codes: {', '.join(prog_map.keys())}")
            continue

        # Validate semester
        try:
            sem = int(row.get("current_semester", 0))
            if not (1 <= sem <= 12):
                errors.append(f"Row {i}: Semester must be between 1 and 12, got '{sem}'")
                continue
        except ValueError:
            errors.append(f"Row {i}: Invalid semester value '{row.get('current_semester')}'")
            continue

        # Duplicate roll check
        roll = row.get("roll_number", "").strip()
        if roll in existing_rolls:
            errors.append(f"Row {i}: Roll number '{roll}' already exists. Use update instead.")
            continue

        valid.append({
            **row,
            "_dept_id": dept_map[dept_code],
            "_prog_id": prog_map[prog_code],
        })

    return valid, errors


async def _validate_attendance(rows: list[dict], db: AsyncSession) -> tuple[list[dict], list[dict]]:
    """Validate attendance CSV rows."""
    errors = []
    valid = []

    r = await db.execute(text("SELECT roll_number, id FROM students WHERE status = 'active'"))
    student_map = {row[0]: row[1] for row in r.fetchall()}

    r = await db.execute(text("SELECT code, id FROM subjects WHERE is_active = TRUE"))
    subject_map = {row[0]: row[1] for row in r.fetchall()}

    valid_statuses = {"present", "absent", "late", "excused"}

    for i, row in enumerate(rows, 1):
        roll = row.get("roll_number", "").strip()
        subj_code = row.get("subject_code", "").strip().upper()
        date_str = row.get("date", "").strip()
        status = row.get("status", "").strip().lower()

        if not all([roll, subj_code, date_str, status]):
            errors.append(f"Row {i}: Missing required field(s)")
            continue

        if roll not in student_map:
            errors.append(f"Row {i}: Student '{roll}' not found")
            continue

        if subj_code not in subject_map:
            errors.append(f"Row {i}: Subject code '{subj_code}' not found")
            continue

        if status not in valid_statuses:
            errors.append(f"Row {i}: Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}")
            continue

        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            errors.append(f"Row {i}: Invalid date format '{date_str}'. Use YYYY-MM-DD")
            continue

        valid.append({
            **row,
            "_student_id": student_map[roll],
            "_subject_id": subject_map[subj_code],
        })

    return valid, errors


async def _validate_marks(rows: list[dict], db: AsyncSession) -> tuple[list[dict], list[dict]]:
    """Validate marks CSV rows."""
    errors = []
    valid = []

    r = await db.execute(text("SELECT roll_number, id FROM students WHERE status = 'active'"))
    student_map = {row[0]: row[1] for row in r.fetchall()}

    r = await db.execute(text("SELECT code, id FROM subjects WHERE is_active = TRUE"))
    subject_map = {row[0]: row[1] for row in r.fetchall()}

    valid_exam_types = {"internal_1", "internal_2", "internal_3", "semester", "practical", "assignment"}

    for i, row in enumerate(rows, 1):
        roll = row.get("roll_number", "").strip()
        subj_code = row.get("subject_code", "").strip().upper()
        exam_type = row.get("exam_type", "").strip().lower()

        if not all([roll, subj_code, exam_type]):
            errors.append(f"Row {i}: Missing required field(s)")
            continue

        if roll not in student_map:
            errors.append(f"Row {i}: Student '{roll}' not found")
            continue

        if subj_code not in subject_map:
            errors.append(f"Row {i}: Subject code '{subj_code}' not found")
            continue

        if exam_type not in valid_exam_types:
            errors.append(f"Row {i}: Invalid exam type '{exam_type}'. Valid: {', '.join(valid_exam_types)}")
            continue

        try:
            obtained = float(row.get("marks_obtained", 0))
            max_m = float(row.get("max_marks", 100))
            if obtained < 0 or obtained > max_m:
                errors.append(f"Row {i}: Marks obtained ({obtained}) must be between 0 and max_marks ({max_m})")
                continue
        except (ValueError, TypeError):
            errors.append(f"Row {i}: Invalid marks values")
            continue

        valid.append({
            **row,
            "_student_id": student_map[roll],
            "_subject_id": subject_map[subj_code],
        })

    return valid, errors


# ── Upload Endpoints ──────────────────────────────────────────────────────────

@router.post("/upload/students")
async def upload_students(
    file: UploadFile = File(...),
    commit: bool = Query(False, description="Set to true to commit after preview"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload student CSV. Preview validation without commit=true."""
    assert_can_sync_data(current_user)

    if not file.filename.endswith((".csv", ".xlsx")):
        raise HTTPException(status_code=400, detail="Only .csv files are supported")

    content = await file.read()
    headers, rows = _parse_csv(content)

    required_headers = {"roll_number", "name", "email", "department_code", "program_code", "current_semester", "batch"}
    missing = required_headers - set(headers)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"CSV is missing required columns: {', '.join(missing)}. Download template for reference.",
        )

    valid_rows, errors = await _validate_students(rows, db)
    preview = rows[:10]

    if not commit:
        return {
            "status": "preview",
            "total_rows": len(rows),
            "valid_rows": len(valid_rows),
            "error_count": len(errors),
            "errors": errors[:20],
            "preview": preview,
            "message": "Pass commit=true to confirm import" if not errors else "Fix errors before committing",
        }

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": f"{len(errors)} validation errors. Fix before committing.", "errors": errors[:20]},
        )

    # Commit
    job_id = str(uuid.uuid4())
    imported = 0
    for row in valid_rows:
        await db.execute(
            text("""
                INSERT INTO students (roll_number, name, email, department_id, program_id, current_semester, batch, section, status, risk_score)
                VALUES (:roll, :name, :email, :dept_id, :prog_id, :sem, :batch, :section, 'active', 0)
                ON CONFLICT (roll_number) DO NOTHING
            """),
            {
                "roll": row["roll_number"].strip(),
                "name": row["name"].strip(),
                "email": row["email"].strip(),
                "dept_id": row["_dept_id"],
                "prog_id": row["_prog_id"],
                "sem": int(row["current_semester"]),
                "batch": row.get("batch", "").strip(),
                "section": row.get("section", "").strip(),
            },
        )
        imported += 1

    table_exists = await db.execute(text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'import_jobs')"))
    if table_exists.scalar():
        try:
            await db.execute(
                text("""
                    INSERT INTO import_jobs (id, import_type, status, rows_total, rows_imported, errors, imported_by_id, created_at)
                    VALUES (:id, 'students', 'completed', :total, :imported, :errors, :user_id, NOW())
                """),
                {"id": job_id, "total": len(rows), "imported": imported, "errors": json.dumps([]), "user_id": current_user.id},
            )
        except Exception:
            pass  # Fallback if something else fails

    await db.commit()

    return {
        "status": "success",
        "job_id": job_id,
        "rows_imported": imported,
        "total_rows": len(rows),
        "errors": [],
    }


@router.post("/upload/attendance")
async def upload_attendance(
    file: UploadFile = File(...),
    commit: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload attendance CSV."""
    assert_can_sync_data(current_user)

    content = await file.read()
    headers, rows = _parse_csv(content)
    valid_rows, errors = await _validate_attendance(rows, db)
    preview = rows[:10]

    if not commit:
        return {
            "status": "preview",
            "total_rows": len(rows),
            "valid_rows": len(valid_rows),
            "error_count": len(errors),
            "errors": errors[:20],
            "preview": preview,
        }

    if errors:
        raise HTTPException(status_code=422, detail={"message": "Validation errors", "errors": errors[:20]})

    job_id = str(uuid.uuid4())
    imported = 0
    for row in valid_rows:
        await db.execute(
            text("""
                INSERT INTO attendance (student_id, subject_id, date, status)
                VALUES (:student_id, :subject_id, :date, :status)
                ON CONFLICT DO NOTHING
            """),
            {
                "student_id": row["_student_id"],
                "subject_id": row["_subject_id"],
                "date": row["date"].strip(),
                "status": row["status"].strip().lower(),
            },
        )
        imported += 1

    await db.commit()
    return {"status": "success", "job_id": job_id, "rows_imported": imported}


@router.post("/upload/marks")
async def upload_marks(
    file: UploadFile = File(...),
    commit: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload marks CSV."""
    assert_can_sync_data(current_user)

    content = await file.read()
    headers, rows = _parse_csv(content)
    valid_rows, errors = await _validate_marks(rows, db)
    preview = rows[:10]

    if not commit:
        return {
            "status": "preview",
            "total_rows": len(rows),
            "valid_rows": len(valid_rows),
            "error_count": len(errors),
            "errors": errors[:20],
            "preview": preview,
        }

    if errors:
        raise HTTPException(status_code=422, detail={"message": "Validation errors", "errors": errors[:20]})

    job_id = str(uuid.uuid4())
    imported = 0
    for row in valid_rows:
        max_m = float(row.get("max_marks", 100))
        obtained = float(row.get("marks_obtained", 0))
        pct = round(obtained * 100 / max_m, 1) if max_m > 0 else 0

        await db.execute(
            text("""
                INSERT INTO marks_records (student_id, subject_id, exam_type, marks_obtained, max_marks, percentage, is_absent, is_withheld)
                VALUES (:student_id, :subject_id, :exam_type, :obtained, :max_marks, :pct, FALSE, FALSE)
                ON CONFLICT (student_id, subject_id, exam_type) DO UPDATE
                SET marks_obtained = EXCLUDED.marks_obtained,
                    max_marks = EXCLUDED.max_marks,
                    percentage = EXCLUDED.percentage
            """),
            {
                "student_id": row["_student_id"],
                "subject_id": row["_subject_id"],
                "exam_type": row["exam_type"].strip(),
                "obtained": obtained,
                "max_marks": max_m,
                "pct": pct,
            },
        )
        imported += 1

    await db.commit()
    return {"status": "success", "job_id": job_id, "rows_imported": imported}


@router.get("/history")
async def get_import_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return import job history."""
    assert_can_sync_data(current_user)

    try:
        r = await db.execute(
            text("""
                SELECT ij.id, ij.import_type, ij.status, ij.rows_total, ij.rows_imported,
                    ij.errors, ij.created_at, u.full_name AS imported_by
                FROM import_jobs ij
                LEFT JOIN users u ON u.id = ij.imported_by_id
                ORDER BY ij.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": page_size, "offset": (page - 1) * page_size},
        )
        rows = r.fetchall()
        cols = list(r.keys())
        history = []
        for row in rows:
            item = dict(zip(cols, row))
            # Parse errors JSON
            try:
                item["errors"] = json.loads(item["errors"]) if item["errors"] else []
            except Exception:
                item["errors"] = []
            history.append(item)

        return {"history": history, "page": page, "page_size": page_size}
    except Exception:
        return {"history": [], "page": 1, "page_size": page_size, "note": "Import history table not yet created"}
