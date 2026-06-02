from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db
from app.api.deps import get_current_college_admin
import csv
import io
from pydantic import BaseModel
from typing import List, Optional
import json

router = APIRouter()

class ImportResult(BaseModel):
    success_count: int
    error_count: int
    errors: List[str]
    job_id: Optional[str] = None

@router.post("/students", response_model=ImportResult)
async def import_students(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_college_admin)
):
    """
    Import students via CSV.
    Expected columns: name, email, roll_number, department_id, program_id, batch, gender, dob, phone, register_number
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    content = await file.read()
    decoded = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    
    success = 0
    errors = []

    for i, row in enumerate(reader, start=1):
        try:
            # Basic validation
            email = row.get('email', '').strip()
            roll_number = row.get('roll_number', '').strip()
            name = row.get('name', '').strip()
            department_id = row.get('department_id', '').strip()
            program_id = row.get('program_id', '').strip()
            batch = row.get('batch', '').strip()
            
            if not email or not roll_number or not name or not department_id or not program_id or not batch:
                errors.append(f"Row {i}: Missing required fields (email, roll_number, name, department_id, program_id, batch)")
                continue
            
            insert_query = text("""
                WITH new_user AS (
                    INSERT INTO users (college_id, department_id, email, full_name, password_hash, role)
                    VALUES (:college_id, :department_id::INT, :email, :name, '$2b$12$PIRu/gup6EEOtpZS5x4Ax.aFXso0/vdDnCRjrgG/VNk90aRJMMohe', 'student')
                    ON CONFLICT (email) DO NOTHING
                    RETURNING id
                )
                INSERT INTO students (user_id, college_id, department_id, program_id, roll_number, register_number, name, email, phone, gender, dob, batch, status)
                SELECT id, :college_id, :department_id::INT, :program_id::INT, :roll_number, :register_number, :name, :email, :phone, 
                       NULLIF(:gender, '')::gender_enum, NULLIF(:dob, '')::DATE, :batch, 'active'
                FROM new_user
                ON CONFLICT (college_id, roll_number) DO NOTHING
                RETURNING id;
            """)
            
            result = await db.execute(insert_query, {
                "college_id": admin["college_id"],
                "department_id": department_id,
                "program_id": program_id,
                "email": email,
                "name": name,
                "roll_number": roll_number,
                "register_number": row.get('register_number', ''),
                "phone": row.get('phone', ''),
                "gender": row.get('gender', ''),
                "dob": row.get('dob', ''),
                "batch": batch
            })
            
            if result.fetchone():
                success += 1
            else:
                errors.append(f"Row {i}: Duplicate email or roll_number")
                
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    await db.commit()
    
    return ImportResult(
        success_count=success,
        error_count=len(errors),
        errors=errors[:10]  # Return top 10 errors max
    )

@router.post("/faculty", response_model=ImportResult)
async def import_faculty(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_college_admin)
):
    """
    Import faculty via CSV.
    Expected columns: email, full_name, employee_id, designation, qualification, experience_years, department_id
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    content = await file.read()
    decoded = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    
    success = 0
    errors = []

    for i, row in enumerate(reader, start=1):
        try:
            email = row.get('email', '').strip()
            full_name = row.get('full_name', '').strip()
            employee_id = row.get('employee_id', '').strip()
            dept_id = row.get('department_id', '').strip()
            
            if not email or not full_name or not dept_id:
                errors.append(f"Row {i}: Missing required fields (email, full_name, department_id)")
                continue

            insert_query = text("""
                INSERT INTO users (
                    college_id, email, full_name, password_hash, role, department_id,
                    employee_id, designation, qualification, experience_years, phone
                )
                VALUES (
                    :college_id, :email, :full_name, '$2b$12$PIRu/gup6EEOtpZS5x4Ax.aFXso0/vdDnCRjrgG/VNk90aRJMMohe', 'faculty', :dept_id::INT,
                    :employee_id, :designation, :qualification, NULLIF(:exp, '')::INT, NULLIF(:phone, '')
                )
                ON CONFLICT (email) DO NOTHING
                RETURNING id;
            """)
            
            result = await db.execute(insert_query, {
                "college_id": admin["college_id"],
                "email": email,
                "full_name": full_name,
                "dept_id": dept_id,
                "employee_id": employee_id,
                "designation": row.get('designation', ''),
                "qualification": row.get('qualification', ''),
                "exp": row.get('experience_years', ''),
                "phone": row.get('phone', '')
            })
            
            if result.fetchone():
                success += 1
            else:
                errors.append(f"Row {i}: Duplicate email")
                
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    await db.commit()
    
    return ImportResult(
        success_count=success,
        error_count=len(errors),
        errors=errors[:10]
    )
