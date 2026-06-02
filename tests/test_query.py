import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
import os
from dotenv import load_dotenv

load_dotenv()
async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as conn:
        from sqlalchemy import text
        res = await conn.execute(text("SELECT COUNT(*) FROM attendance"))
        print("Total attendance records:", res.scalar())
        
        res = await conn.execute(text("""
            SELECT s.name,
                   ROUND(SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) * 100.0
                         / NULLIF(COUNT(a.id), 0)::numeric, 2) AS attendance_pct
            FROM students s
            LEFT JOIN attendance a ON a.student_id = s.id
            GROUP BY s.id, s.name
        """))
        rows = res.fetchall()
        print("Total students with attendance:", len([r for r in rows if r[1] is not None]))
        print("Sample pct:", [float(r[1]) for r in rows if r[1] is not None][:10])
asyncio.run(main())
