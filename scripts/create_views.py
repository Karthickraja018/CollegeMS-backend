import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

async def create_views():
    db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:Karthick0809@db.qhlmuyrphmqipidxbrhr.supabase.co:5432/postgres")
    engine = create_async_engine(db_url)

    drop_sql = [
        "DROP VIEW IF EXISTS vw_department_profile CASCADE;",
        "DROP VIEW IF EXISTS vw_faculty_profile CASCADE;",
        "DROP VIEW IF EXISTS vw_student_strength CASCADE;",
        "DROP VIEW IF EXISTS vw_subject_performance CASCADE;",
        "DROP VIEW IF EXISTS vw_student_attendance CASCADE;",
        "DROP VIEW IF EXISTS vw_placement_internship CASCADE;",
    ]

    views_sql = [
        """
        CREATE VIEW vw_department_profile AS
        SELECT 
            d.id as department_id,
            d.name as department_name,
            d.code as department_code,
            COUNT(DISTINCT s.id) as total_students,
            COUNT(DISTINCT u.id) as total_faculty
        FROM departments d
        LEFT JOIN students s ON s.department_id = d.id AND s.status = 'active'
        LEFT JOIN users u ON u.department_id = d.id AND u.role IN ('faculty', 'hod') AND u.is_active = TRUE
        GROUP BY d.id, d.name, d.code;
        """,
        
        """
        CREATE VIEW vw_faculty_profile AS
        SELECT
            d.name as department_name,
            u.department_id,
            u.id as faculty_id,
            u.full_name as faculty_name,
            u.designation,
            u.qualification,
            u.experience_years
        FROM users u
        JOIN departments d ON d.id = u.department_id
        WHERE u.role IN ('faculty', 'hod') AND u.is_active = TRUE;
        """,

        """
        CREATE VIEW vw_student_strength AS
        SELECT
            d.name as department_name,
            s.department_id,
            s.program_id,
            s.current_semester,
            COUNT(s.id) as total_strength,
            SUM(CASE WHEN s.gender = 'male' THEN 1 ELSE 0 END) as male_count,
            SUM(CASE WHEN s.gender = 'female' THEN 1 ELSE 0 END) as female_count
        FROM students s
        JOIN departments d ON d.id = s.department_id
        WHERE s.status = 'active'
        GROUP BY d.name, s.department_id, s.program_id, s.current_semester;
        """,
        
        """
        CREATE VIEW vw_subject_performance AS
        SELECT 
            d.name as department_name,
            sub.department_id,
            sub.id as subject_id,
            sub.name as subject_name,
            sub.code as subject_code,
            sub.type as subject_type,
            COUNT(mr.id) as students_appeared,
            SUM(CASE WHEN mr.marks_obtained >= (mr.max_marks * 0.4) THEN 1 ELSE 0 END) as students_passed,
            CASE WHEN COUNT(mr.id) > 0 
                THEN ROUND((SUM(CASE WHEN mr.marks_obtained >= (mr.max_marks * 0.4) THEN 1 ELSE 0 END)::NUMERIC / COUNT(mr.id)::NUMERIC) * 100, 2) 
                ELSE 0 END as pass_pct,
            ROUND(AVG(mr.marks_obtained / NULLIF(mr.max_marks, 0) * 100), 2) as avg_marks_pct
        FROM subjects sub
        JOIN departments d ON d.id = sub.department_id
        LEFT JOIN marks_records mr ON mr.subject_id = sub.id
        GROUP BY d.name, sub.id, sub.department_id, sub.name, sub.code, sub.type;
        """,
        
        """
        CREATE VIEW vw_student_attendance AS
        SELECT
            d.name as department_name,
            s.department_id,
            s.id as student_id,
            s.name as student_name,
            s.register_number,
            s.current_semester,
            COUNT(a.id) as total_classes,
            SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) as days_present,
            CASE WHEN COUNT(a.id) > 0 
                THEN ROUND((SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END)::NUMERIC / COUNT(a.id)::NUMERIC) * 100, 2) 
                ELSE 0 END as attendance_pct
        FROM students s
        JOIN departments d ON d.id = s.department_id
        LEFT JOIN attendance_records a ON a.student_id = s.id
        WHERE s.status = 'active'
        GROUP BY d.name, s.id, s.department_id, s.name, s.register_number, s.current_semester;
        """,
        
        """
        CREATE VIEW vw_placement_internship AS
        SELECT
            pd.id as drive_id,
            pd.college_id,
            pd.company_name,
            pd.job_role as role_offered,
            pd.ctc_lpa as package_lpa,
            COUNT(ps.id) as total_offers
        FROM placement_drives pd
        LEFT JOIN placement_applications ps ON ps.drive_id = pd.id AND ps.status = 'Selected'
        GROUP BY pd.id, pd.college_id, pd.company_name, pd.job_role, pd.ctc_lpa;
        """
    ]

    async with engine.begin() as conn:
        # Drop all views first (CASCADE handles dependencies)
        for sql in drop_sql:
            await conn.execute(text(sql))
            print(f"Dropped: {sql.strip()[:50]}")
        # Recreate
        for sql in views_sql:
            await conn.execute(text(sql))
            print("Recreated view.")

if __name__ == "__main__":
    asyncio.run(create_views())
