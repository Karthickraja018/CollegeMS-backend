import asyncio
from datetime import date, timedelta
import random
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.models.user import User  # Just to ensure models load

async def main():
    start_date = date(2025, 12, 1)
    end_date = date(2026, 6, 4)

    # We need to get all active students, their current semesters, and the subjects for that semester.
    async with AsyncSessionLocal() as db:
        print("Fetching students and their subjects...")
        # Get students
        r = await db.execute(text("""
            SELECT s.id as student_id, s.program_id, s.current_semester, se.id as semester_id
            FROM students s
            JOIN semesters se ON se.program_id = s.program_id AND se.semester_number = s.current_semester
            WHERE s.status = 'active'
        """))
        students = r.fetchall()
        
        # Group by program_id and semester_number to fetch subjects
        programs_sems = set((s.program_id, s.current_semester) for s in students)
        
        subjects_map = {}
        for pid, sem in programs_sems:
            r = await db.execute(text("""
                SELECT id FROM subjects WHERE program_id = :pid AND semester_number = :sem
            """), {"pid": pid, "sem": sem})
            subjects_map[(pid, sem)] = [row[0] for row in r.fetchall()]
        
        print(f"Found {len(students)} active students.")
        
        # Generate dates (exclude weekends)
        current_date = start_date
        dates_to_insert = []
        while current_date <= end_date:
            if current_date.weekday() < 5:  # 0-4 are Mon-Fri
                dates_to_insert.append(current_date)
            current_date += timedelta(days=1)
            
        print(f"Generating attendance for {len(dates_to_insert)} days...")
        
        records = []
        count = 0
        for d in dates_to_insert:
            for s in students:
                subs = subjects_map.get((s.program_id, s.current_semester), [])
                for idx, sub_id in enumerate(subs):
                    # Each subject represents a period, roughly
                    status = "present" if random.random() < 0.85 else "absent"
                    records.append({
                        "student_id": s.student_id,
                        "subject_id": sub_id,
                        "semester_id": s.semester_id,
                        "date": d,
                        "period": idx + 1,
                        "status": status
                    })
                    
                    if len(records) >= 5000:
                        await db.execute(
                            text("""
                                INSERT INTO attendance_records (student_id, subject_id, semester_id, date, period, status)
                                VALUES (:student_id, :subject_id, :semester_id, :date, :period, :status)
                                ON CONFLICT DO NOTHING
                            """),
                            records
                        )
                        count += len(records)
                        records = []
                        print(f"Inserted {count} records...")

        if records:
            await db.execute(
                text("""
                    INSERT INTO attendance_records (student_id, subject_id, semester_id, date, period, status)
                    VALUES (:student_id, :subject_id, :semester_id, :date, :period, :status)
                    ON CONFLICT DO NOTHING
                """),
                records
            )
            count += len(records)
            print(f"Inserted {count} records total.")
            
        print("Refreshing materialized view attendance_summary...")
        await db.execute(text("REFRESH MATERIALIZED VIEW attendance_summary"))
        await db.commit()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
