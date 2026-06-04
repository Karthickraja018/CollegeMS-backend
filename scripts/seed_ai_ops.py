import asyncio
import random
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url)

async def seed_ai_ops():
    async with AsyncSession(engine) as session:
        # Get college and users
        r = await session.execute(text("SELECT id FROM colleges LIMIT 1"))
        college = r.fetchone()
        if not college:
            print("No college found.")
            return
        college_id = college.id
        
        r = await session.execute(text("SELECT id FROM users WHERE college_id = :cid"), {"cid": college_id})
        users = [row.id for row in r.fetchall()]
        if not users:
            print("No users found.")
            return

        r = await session.execute(text("SELECT id FROM students WHERE college_id = :cid LIMIT 50"), {"cid": college_id})
        students = [row.id for row in r.fetchall()]
        
        print(f"Found {len(users)} users, seeding AI usage...")

        # 1. Seed chat_sessions
        agents = ["query", "analytics", "performance", "report", "routing"]
        
        # Insert 150 chat sessions over the last 30 days
        for _ in range(150):
            user_id = random.choice(users)
            session_key = f"mock-session-{random.randint(100000, 999999)}"
            days_ago = random.randint(0, 30)
            hours_ago = random.randint(0, 23)
            created_at = datetime.now() - timedelta(days=days_ago, hours=hours_ago)
            agent = random.choice(agents)
            
            num_messages = random.randint(2, 10)
            messages = []
            for i in range(num_messages):
                role = "user" if i % 2 == 0 else "assistant"
                messages.append({"id": str(i), "role": role, "content": "Mock message content"})
                
            import json
            await session.execute(text("""
                INSERT INTO chat_sessions (user_id, session_key, title, messages, last_agent, created_at, updated_at)
                VALUES (:uid, :sk, :title, CAST(:msgs AS jsonb), :agent, :cat, :uat)
            """), {
                "uid": user_id,
                "sk": session_key,
                "title": f"Analysis session {days_ago} days ago",
                "msgs": json.dumps(messages),
                "agent": agent,
                "cat": created_at,
                "uat": created_at
            })
            
        # 2. Seed reports
        for _ in range(30):
            days_ago = random.randint(0, 30)
            created_at = datetime.now() - timedelta(days=days_ago)
            status = random.choices(["completed", "failed", "in_progress"], weights=[0.8, 0.1, 0.1])[0]
            
            await session.execute(text("""
                INSERT INTO reports (college_id, generated_by, title, report_type, status, parameters, created_at)
                VALUES (:cid, :uid, :title, :type, :status, '{}', :cat)
            """), {
                "cid": college_id,
                "uid": random.choice(users),
                "title": f"Automated AI Report {days_ago} days ago",
                "type": random.choice(["department_performance", "attendance_summary"]),
                "status": status,
                "cat": created_at
            })

        # 3. Seed at_risk_snapshots
        r = await session.execute(text("SELECT id FROM semesters LIMIT 1"))
        semester = r.fetchone()
        if students and semester:
            semester_id = semester.id
            for days_ago in [0, 7, 14, 21, 28]:
                snap_date = (datetime.now() - timedelta(days=days_ago)).date()
                for st in random.sample(students, min(20, len(students))):
                    risk_score = random.randint(30, 95)
                    await session.execute(text("""
                        INSERT INTO at_risk_snapshots (student_id, semester_id, snapshot_date, risk_score, created_at)
                        VALUES (:sid, :semid, :sdate, :score, :cat)
                    """), {
                        "sid": st,
                        "semid": semester_id,
                        "sdate": snap_date,
                        "score": risk_score,
                        "cat": snap_date
                    })

        await session.commit()
        print("Mock data seeded for AI Operations successfully!")

if __name__ == "__main__":
    asyncio.run(seed_ai_ops())
