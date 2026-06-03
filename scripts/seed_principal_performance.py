# -*- coding: utf-8 -*-
"""
Seed script: Insert 6 months of realistic performance data for all faculty and HODs.

Run from backend directory:
    python scripts/seed_principal_performance.py

This script uses psycopg2 directly to avoid async complexity in a seed script.
"""
import sys
import os
import random
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Parse DB URL: postgresql+asyncpg://user:pass@host:port/dbname
raw_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/collegems")
sync_url = raw_url.replace("postgresql+asyncpg://", "").replace("postgresql://", "")

# Parse: user:pass@host:port/dbname
user_pass, rest = sync_url.split("@", 1)
host_port, dbname = rest.rsplit("/", 1)
user, password = user_pass.split(":", 1)
if ":" in host_port:
    host, port = host_port.rsplit(":", 1)
else:
    host, port = host_port, "5432"

print(f"Connecting to DB: {host}:{port}/{dbname} as {user}")

conn = psycopg2.connect(
    host=host, port=port, dbname=dbname, user=user, password=password
)
cur = conn.cursor()

# ─── Create tables if not exist ───────────────────────────────────────────────
cur.execute("""
CREATE TABLE IF NOT EXISTS staff_performance_metrics (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    month DATE NOT NULL,
    attendance_submission_pct NUMERIC(5,2),
    marks_submission_pct NUMERIC(5,2),
    student_pass_rate NUMERIC(5,2),
    avg_student_attendance NUMERIC(5,2),
    feedback_score NUMERIC(3,1),
    classes_conducted INTEGER DEFAULT 0,
    ai_usage_count INTEGER DEFAULT 0,
    report_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, month)
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS hod_performance_metrics (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    month DATE NOT NULL,
    dept_health_score NUMERIC(5,2),
    faculty_compliance_rate NUMERIC(5,2),
    student_risk_count INTEGER DEFAULT 0,
    pass_rate NUMERIC(5,2),
    attendance_rate NUMERIC(5,2),
    review_meetings_held INTEGER DEFAULT 0,
    faculty_feedback_avg NUMERIC(3,1),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, month)
);
""")
conn.commit()
print("[OK] Tables created / verified")

# ─── Fetch Faculty and HODs ────────────────────────────────────────────────────
cur.execute("""
    SELECT u.id, u.full_name, u.role, u.department_id, d.name AS dept_name
    FROM users u
    JOIN departments d ON d.id = u.department_id
    WHERE u.role IN ('faculty', 'hod') AND u.is_active = TRUE AND u.department_id IS NOT NULL
    ORDER BY u.role, u.department_id, u.id
""")
staff = cur.fetchall()
print(f"Found {len(staff)} faculty/HOD members")

if not staff:
    print("[ERROR] No faculty/HOD found. Make sure the DB has users with role='faculty' or 'hod'")
    sys.exit(1)

# ─── Generate 6 months of data ────────────────────────────────────────────────
today = date.today()
months = []
for i in range(6, 0, -1):
    m = (today - relativedelta(months=i)).replace(day=1)
    months.append(m)

print(f"Generating data for months: {[str(m) for m in months]}")

# Faculty profile types — realistic variation
def faculty_profile(user_id: int):
    """Return a performance profile based on user_id for deterministic variation."""
    random.seed(user_id * 37)
    profile_type = random.choices(
        ["excellent", "good", "average", "struggling"],
        weights=[25, 40, 25, 10]
    )[0]
    return profile_type

def clamp(v, lo, hi):
    return max(lo, min(hi, round(v, 1)))

# ─── Seed Staff Performance ───────────────────────────────────────────────────
staff_inserted = 0
hod_inserted = 0

for user_id, full_name, role, dept_id, dept_name in staff:
    profile = faculty_profile(user_id)
    random.seed(user_id * 13)

    # Base values by profile
    base = {
        "excellent":  {"att_sub": 97, "marks_sub": 96, "pass": 88, "avg_att": 86, "feedback": 4.6, "classes": 28, "ai": 12, "reps": 5},
        "good":       {"att_sub": 91, "marks_sub": 90, "pass": 78, "avg_att": 80, "feedback": 4.1, "classes": 25, "ai": 7,  "reps": 3},
        "average":    {"att_sub": 82, "marks_sub": 80, "pass": 68, "avg_att": 73, "feedback": 3.6, "classes": 22, "ai": 4,  "reps": 2},
        "struggling": {"att_sub": 68, "marks_sub": 65, "pass": 54, "avg_att": 63, "feedback": 3.0, "classes": 18, "ai": 2,  "reps": 1},
    }[profile]

    for month in months:
        # Add slight monthly noise
        noise = lambda base_v, spread: clamp(base_v + random.uniform(-spread, spread), 0, 100)

        att_sub = noise(base["att_sub"], 5)
        marks_sub = noise(base["marks_sub"], 5)
        pass_rate = noise(base["pass"], 6)
        avg_att = noise(base["avg_att"], 4)
        feedback = clamp(base["feedback"] + random.uniform(-0.4, 0.4), 1.0, 5.0)
        classes = max(10, base["classes"] + random.randint(-3, 3))
        ai_usage = max(0, base["ai"] + random.randint(-2, 3))
        reports = max(0, base["reps"] + random.randint(-1, 2))

        if role == "faculty":
            cur.execute("""
                INSERT INTO staff_performance_metrics
                    (user_id, department_id, month, attendance_submission_pct, marks_submission_pct,
                     student_pass_rate, avg_student_attendance, feedback_score,
                     classes_conducted, ai_usage_count, report_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, month) DO NOTHING
            """, (user_id, dept_id, month, att_sub, marks_sub, pass_rate, avg_att,
                  feedback, classes, ai_usage, reports))
            staff_inserted += 1

        elif role == "hod":
            # HOD also gets staff metrics (they teach too)
            cur.execute("""
                INSERT INTO staff_performance_metrics
                    (user_id, department_id, month, attendance_submission_pct, marks_submission_pct,
                     student_pass_rate, avg_student_attendance, feedback_score,
                     classes_conducted, ai_usage_count, report_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, month) DO NOTHING
            """, (user_id, dept_id, month, att_sub, marks_sub, pass_rate, avg_att,
                  feedback, classes, ai_usage, reports))
            staff_inserted += 1

            # HOD-specific metrics
            dept_health = clamp(pass_rate * 0.4 + avg_att * 0.4 + feedback * 4, 40, 98)
            compliance = noise(base["att_sub"] - 5, 8)  # HOD ensures team compliance
            risk_students = random.randint(2, 20)
            meetings = random.randint(1, 4)
            fac_feedback = clamp(feedback - 0.2 + random.uniform(-0.3, 0.3), 1.0, 5.0)

            cur.execute("""
                INSERT INTO hod_performance_metrics
                    (user_id, department_id, month, dept_health_score, faculty_compliance_rate,
                     student_risk_count, pass_rate, attendance_rate,
                     review_meetings_held, faculty_feedback_avg)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, month) DO NOTHING
            """, (user_id, dept_id, month, dept_health, compliance,
                  risk_students, pass_rate, avg_att, meetings, fac_feedback))
            hod_inserted += 1

conn.commit()
print(f"[OK] Inserted {staff_inserted} staff_performance_metrics rows")
print(f"[OK] Inserted {hod_inserted} hod_performance_metrics rows")

# ─── Verify ───────────────────────────────────────────────────────────────────
cur.execute("SELECT COUNT(*) FROM staff_performance_metrics")
print(f"Total staff_performance_metrics: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM hod_performance_metrics")
print(f"Total hod_performance_metrics: {cur.fetchone()[0]}")

# Sample output
cur.execute("""
    SELECT u.full_name, u.role, spm.month, spm.student_pass_rate, spm.attendance_submission_pct
    FROM staff_performance_metrics spm
    JOIN users u ON u.id = spm.user_id
    ORDER BY spm.month DESC, u.full_name
    LIMIT 10
""")
print("\nSample staff_performance_metrics:")
for row in cur.fetchall():
    print(f"  {row[0]} ({row[1]}) | {row[2]} | pass={row[3]}% | att_sub={row[4]}%")

cur.execute("""
    SELECT u.full_name, hpm.month, hpm.dept_health_score, hpm.faculty_compliance_rate, hpm.student_risk_count
    FROM hod_performance_metrics hpm
    JOIN users u ON u.id = hpm.user_id
    ORDER BY hpm.month DESC, u.full_name
    LIMIT 6
""")
print("\nSample hod_performance_metrics:")
for row in cur.fetchall():
    print(f"  {row[0]} | {row[1]} | health={row[2]} | compliance={row[3]}% | at_risk={row[4]}")

cur.close()
conn.close()
print("\n[DONE] Seeding complete!")
