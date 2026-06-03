import sys
import os
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

conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)
cur = conn.cursor()

# 1. Departments without students
cur.execute("""
SELECT d.id, d.name, COUNT(s.id) as student_count 
FROM departments d 
LEFT JOIN students s ON s.department_id = d.id 
GROUP BY d.id, d.name 
ORDER BY student_count ASC
""")
print("Departments by student count:")
for row in cur.fetchall():
    print(f"  {row[1]}: {row[2]} students")

# 2. Departments without faculty
cur.execute("""
SELECT d.id, d.name, COUNT(u.id) as faculty_count 
FROM departments d 
LEFT JOIN users u ON u.department_id = d.id AND u.role = 'faculty'
GROUP BY d.id, d.name 
ORDER BY faculty_count ASC
""")
print("\nDepartments by faculty count:")
for row in cur.fetchall():
    print(f"  {row[1]}: {row[2]} faculty")

# 3. Subjects without marks/attendance
cur.execute("""
SELECT d.name, sub.name, COUNT(DISTINCT mr.student_id) as students_with_marks
FROM subjects sub
JOIN departments d ON d.id = sub.department_id
LEFT JOIN marks_records mr ON mr.subject_id = sub.id
GROUP BY d.name, sub.name
ORDER BY students_with_marks ASC
LIMIT 10
""")
print("\nSubjects by marks count (bottom 10):")
for row in cur.fetchall():
    print(f"  {row[0]} - {row[1]}: {row[2]} students with marks")

cur.close()
conn.close()
