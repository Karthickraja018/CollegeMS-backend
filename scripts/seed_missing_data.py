# -*- coding: utf-8 -*-
import sys
import os
import random
from datetime import date, timedelta
import psycopg2
from dotenv import load_dotenv

load_dotenv()
raw_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/collegems")
sync_url = raw_url.replace("postgresql+asyncpg://", "").replace("postgresql://", "")

user_pass, rest = sync_url.split("@", 1)
host_port, dbname = rest.rsplit("/", 1)
user, password = user_pass.split(":", 1)
if ":" in host_port:
    host, port = host_port.rsplit(":", 1)
else:
    host, port = host_port, "5432"

print(f"Connecting to DB: {host}:{port}/{dbname} as {user}")
conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)
cur = conn.cursor()

cur.execute("SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT MAX(id) FROM users) + 1)")
cur.execute("SELECT setval(pg_get_serial_sequence('students', 'id'), (SELECT MAX(id) FROM students) + 1)")
cur.execute("SELECT setval(pg_get_serial_sequence('marks_records', 'id'), (SELECT MAX(id) FROM marks_records) + 1)")
cur.execute("SELECT setval(pg_get_serial_sequence('attendance_records', 'id'), COALESCE((SELECT MAX(id) FROM attendance_records), 1) + 1)")
conn.commit()

def clamp(v, lo, hi):
    return max(lo, min(hi, round(v, 1)))

# Fetch college ID
cur.execute("SELECT id FROM colleges LIMIT 1")
college_id = cur.fetchone()[0]

# Fetch Departments
cur.execute("SELECT id, name, code FROM departments WHERE is_active = TRUE")
departments = cur.fetchall()

# For each department, ensure they have at least 5 faculty and 40 students
for dept_id, dept_name, dept_code in departments:
    print(f"\nProcessing Department: {dept_name}")
    
    # Check faculty
    cur.execute("SELECT COUNT(*) FROM users WHERE department_id = %s AND role = 'faculty'", (dept_id,))
    fac_count = cur.fetchone()[0]
    
    faculty_ids = []
    if fac_count < 8:
        print(f"  Adding {8 - fac_count} faculty members...")
        for i in range(8 - fac_count):
            uid = random.randint(1000, 9999)
            name = f"Prof. Faculty_{dept_code}_{uid}"
            email = f"faculty{uid}_{dept_code.lower()}@college.edu"
            cur.execute("""
                INSERT INTO users (college_id, department_id, email, full_name, employee_id, role, designation, password_hash, is_active)
                VALUES (%s, %s, %s, %s, %s, 'faculty', 'Assistant Professor', 'hash', TRUE)
                RETURNING id
            """, (college_id, dept_id, email, name, f"EMP{uid}"))
            faculty_ids.append(cur.fetchone()[0])
            
    cur.execute("SELECT id FROM users WHERE department_id = %s AND role IN ('faculty', 'hod')", (dept_id,))
    faculty_ids = [r[0] for r in cur.fetchall()]

    # Fetch programs
    cur.execute("SELECT id FROM programs WHERE department_id = %s", (dept_id,))
    prog_rows = cur.fetchall()
    if not prog_rows:
        continue
    program_id = prog_rows[0][0]

    # Check students
    cur.execute("SELECT COUNT(*) FROM students WHERE department_id = %s", (dept_id,))
    stu_count = cur.fetchone()[0]
    
    student_ids = []
    if stu_count < 40:
        print(f"  Adding {40 - stu_count} students...")
        for i in range(40 - stu_count):
            uid = random.randint(10000, 99999)
            name = f"Student_{dept_code}_{uid}"
            email = f"student{uid}_{dept_code.lower()}@college.edu"
            risk = random.randint(10, 85)
            cur.execute("""
                INSERT INTO students (college_id, department_id, program_id, name, email, roll_number, current_semester, status, risk_score, batch)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s, '2023-2027')
                RETURNING id
            """, (college_id, dept_id, program_id, name, email, f"ROLL{uid}", 6, risk))
            student_ids.append(cur.fetchone()[0])
            
    cur.execute("SELECT id, current_semester FROM students WHERE department_id = %s AND status = 'active'", (dept_id,))
    students = cur.fetchall()

    # Assign subjects to faculty
    cur.execute("SELECT id, semester_number FROM subjects WHERE department_id = %s", (dept_id,))
    subjects = cur.fetchall()
    
    for sub_id, sem_num in subjects:
        # Check if subject is assigned
        cur.execute("SELECT COUNT(*) FROM faculty_subject_assignments WHERE subject_id = %s", (sub_id,))
        if cur.fetchone()[0] == 0 and faculty_ids:
            fac_id = random.choice(faculty_ids)
            cur.execute("""
                INSERT INTO faculty_subject_assignments (faculty_id, subject_id)
                VALUES (%s, %s) ON CONFLICT DO NOTHING
            """, (fac_id, sub_id))

        # Check marks for this subject
        # We'll assign marks for students in the matching semester (or all active students for simplicity)
        cur.execute("SELECT COUNT(*) FROM marks_records WHERE subject_id = %s", (sub_id,))
        if cur.fetchone()[0] < len(students):
            print(f"  Generating marks & attendance for subject {sub_id} (Sem {sem_num})...")
            # Get semantic matching students (assuming students in sem 6 have marks for sem 1-6)
            # Actually, let's just insert marks for all students for this subject to bulk up data
            for stu_id, stu_sem in students:
                # MARKS
                mrk = clamp(random.gauss(65, 15), 0, 100)
                is_absent = random.random() < 0.05
                if is_absent: mrk = 0
                
                # We need a semester_id. Just pick any semester associated with this program
                cur.execute("SELECT id FROM semesters WHERE program_id = %s AND semester_number = %s LIMIT 1", (program_id, sem_num))
                sem_row = cur.fetchone()
                if not sem_row:
                    continue
                sem_id = sem_row[0]
                
                cur.execute("""
                    INSERT INTO marks_records (student_id, subject_id, semester_id, exam_type, max_marks, marks_obtained, is_absent)
                    VALUES (%s, %s, %s, 'cia1', 100, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (stu_id, sub_id, sem_id, mrk, is_absent))
                
                # ATTENDANCE
                # Generate a few attendance records
                for day in range(30): # 30 days of attendance
                    d = date.today() - timedelta(days=day)
                    status = 'present' if random.random() > 0.15 else 'absent'
                    cur.execute("""
                        INSERT INTO attendance_records (student_id, subject_id, semester_id, date, period, status)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (stu_id, sub_id, sem_id, d, 1, status))
                    
            # After inserting attendance records, update attendance_summary
            pass

conn.commit()
print("\n[OK] Missing data seeded successfully!")
cur.close()
conn.close()
