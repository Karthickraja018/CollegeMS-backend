"""
Seed script — generates realistic demo data for CollegeMS.
Run: python -m app.utils.seed

Generates:
- 4 departments (CSE, ECE, MECH, CIVIL)
- 1 admin + 4 HODs + 8 faculty users
- 200 students (50 per department)
- Subjects for each department/semester
- 2 years of attendance records
- Marks for 3 exam types across 3 semesters
"""
import asyncio
import random
from datetime import date, timedelta
from faker import Faker

from sqlalchemy.ext.asyncio import AsyncSession

fake = Faker("en_IN")
random.seed(42)
Faker.seed(42)

DEPARTMENTS = [
    {"name": "Computer Science & Engineering", "code": "CSE"},
    {"name": "Electronics & Communication Engineering", "code": "ECE"},
    {"name": "Mechanical Engineering", "code": "MECH"},
    {"name": "Civil Engineering", "code": "CIVIL"},
]

SUBJECTS_TEMPLATE = {
    1: ["Mathematics I", "Physics", "Chemistry", "Engineering Graphics", "Communication Skills"],
    2: ["Mathematics II", "Data Structures", "Digital Electronics", "Environmental Science", "Programming Lab"],
    3: ["Algorithms", "Database Systems", "Operating Systems", "Discrete Mathematics", "Web Technologies"],
    4: ["Software Engineering", "Computer Networks", "Machine Learning Basics", "Statistics", "Mini Project"],
    5: ["Artificial Intelligence", "Cloud Computing", "Cybersecurity", "Mobile Computing", "Project Work I"],
    6: ["Deep Learning", "Big Data Analytics", "Distributed Systems", "Elective I", "Project Work II"],
}

BATCHES = ["2021-2025", "2022-2026", "2023-2027"]
SECTIONS = ["A", "B"]
EXAM_TYPES = ["internal1", "internal2", "internal3"]


async def seed_database():
    from app.database import AsyncSessionLocal, engine, Base
    import app.models  # noqa — ensures all models are registered

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await _seed_all(db)
        print("✅ Seed complete!")


async def _seed_all(db: AsyncSession):
    from sqlalchemy import text
    from app.services.auth_service import hash_password
    from app.models.user import User, UserRole
    from app.models.department import Department
    from app.models.student import Student
    from app.models.subject import Subject
    from app.models.attendance import Attendance, AttendanceStatus
    from app.models.marks import Marks, ExamType

    print("🌱 Seeding departments...")
    dept_objects = []
    for d in DEPARTMENTS:
        dept = Department(name=d["name"], code=d["code"])
        db.add(dept)
        dept_objects.append(dept)
    await db.flush()

    print("🌱 Seeding users...")
    # Admin
    admin = User(
        email="admin@college.edu",
        full_name="System Administrator",
        password_hash=hash_password("Admin@123"),
        role=UserRole.admin,
    )
    db.add(admin)

    # Principal
    principal = User(
        email="principal@college.edu",
        full_name="Dr. Rajesh Kumar",
        password_hash=hash_password("Principal@123"),
        role=UserRole.principal,
    )
    db.add(principal)

    # HODs
    hod_users = []
    for dept in dept_objects:
        hod = User(
            email=f"hod.{dept.code.lower()}@college.edu",
            full_name=f"Dr. {fake.last_name()} {fake.first_name()}",
            password_hash=hash_password("Hod@123"),
            role=UserRole.hod,
            department_id=dept.id,
        )
        db.add(hod)
        hod_users.append(hod)

    await db.flush()

    # Link HOD to department
    for dept, hod in zip(dept_objects, hod_users):
        dept.hod_id = hod.id

    # Faculty (2 per department)
    for dept in dept_objects:
        for _ in range(2):
            faculty = User(
                email=fake.unique.email(),
                full_name=f"Prof. {fake.name()}",
                password_hash=hash_password("Faculty@123"),
                role=UserRole.faculty,
                department_id=dept.id,
            )
            db.add(faculty)

    print("🌱 Seeding subjects...")
    subject_map: dict[str, list[Subject]] = {}  # dept_code -> subjects
    for dept in dept_objects:
        dept_subjects = []
        for sem, subj_names in SUBJECTS_TEMPLATE.items():
            for idx, sname in enumerate(subj_names):
                code = f"{dept.code}{sem}{idx+1:02d}"
                subj = Subject(
                    code=code,
                    name=f"{sname} ({dept.code})",
                    semester=sem,
                    department_id=dept.id,
                    credits=4 if idx < 3 else 2,
                )
                db.add(subj)
                dept_subjects.append(subj)
        subject_map[dept.code] = dept_subjects

    await db.flush()

    print("🌱 Seeding 200 students...")
    students: list[Student] = []
    for dept in dept_objects:
        for i in range(50):
            semester = random.choice([3, 4, 5, 6])
            student = Student(
                roll_number=f"{dept.code}{random.randint(100, 999)}{i:02d}",
                name=fake.name(),
                email=fake.unique.email(),
                department_id=dept.id,
                semester=semester,
                batch=random.choice(BATCHES),
                section=random.choice(SECTIONS),
            )
            db.add(student)
            students.append(student)

    await db.flush()

    print("🌱 Seeding attendance records (this may take a moment)...")
    start_date = date.today() - timedelta(days=365)
    end_date = date.today() - timedelta(days=1)

    attendance_records = []
    for student in students:
        dept_code = next(d.code for d in dept_objects if d.id == student.department_id)
        dept_subjects = [s for s in subject_map[dept_code] if s.semester == student.semester]

        # Generate attendance for each subject over ~120 class days
        class_dates = _get_class_dates(start_date, end_date, count=random.randint(80, 120))

        for subj in dept_subjects[:3]:  # Limit to 3 subjects per student for performance
            # Students have varying attendance rates (50-95%)
            att_rate = random.gauss(0.78, 0.12)
            att_rate = max(0.4, min(0.99, att_rate))

            for d in class_dates[:40]:  # 40 classes per subject
                if random.random() < att_rate:
                    status = AttendanceStatus.present
                elif random.random() < 0.3:
                    status = AttendanceStatus.late
                else:
                    status = AttendanceStatus.absent

                attendance_records.append(Attendance(
                    student_id=student.id,
                    subject_id=subj.id,
                    date=d,
                    status=status,
                ))

    # Batch insert
    for i in range(0, len(attendance_records), 500):
        db.add_all(attendance_records[i:i + 500])
        await db.flush()

    print(f"   Added {len(attendance_records)} attendance records")

    print("🌱 Seeding marks...")
    marks_records = []
    for student in students:
        dept_code = next(d.code for d in dept_objects if d.id == student.department_id)
        dept_subjects = [s for s in subject_map[dept_code] if s.semester == student.semester]

        # Base performance (some students are naturally weaker)
        base_performance = random.gauss(0.65, 0.18)
        base_performance = max(0.2, min(0.98, base_performance))

        for subj in dept_subjects[:4]:
            for exam_type in EXAM_TYPES:
                max_marks = 30.0 if exam_type.startswith("internal") else 70.0
                performance = base_performance + random.gauss(0, 0.08)
                performance = max(0.1, min(1.0, performance))

                marks_records.append(Marks(
                    student_id=student.id,
                    subject_id=subj.id,
                    semester=student.semester,
                    exam_type=ExamType(exam_type),
                    marks_obtained=round(performance * max_marks, 1),
                    max_marks=max_marks,
                ))

    for i in range(0, len(marks_records), 500):
        db.add_all(marks_records[i:i + 500])
        await db.flush()

    print(f"   Added {len(marks_records)} marks records")

    await db.commit()

    print("\n📋 Default Credentials:")
    print("   Admin:     admin@college.edu / Admin@123")
    print("   Principal: principal@college.edu / Principal@123")
    print("   HOD (CSE): hod.cse@college.edu / Hod@123")
    print("   Faculty:   [see seeded emails] / Faculty@123")


def _get_class_dates(start: date, end: date, count: int) -> list[date]:
    """Get random class dates (Mon-Fri only) between start and end."""
    all_weekdays = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # Mon-Fri
            all_weekdays.append(current)
        current += timedelta(days=1)
    return sorted(random.sample(all_weekdays, min(count, len(all_weekdays))))


if __name__ == "__main__":
    asyncio.run(seed_database())
