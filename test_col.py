import asyncio
import os
from sqlalchemy import text
from app.database import AsyncSessionLocal
import traceback

async def test_db():
    try:
        async with AsyncSessionLocal() as session:
            r = await session.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'faculty_subject_assignments';
            """))
            print('Columns in faculty_subject_assignments:', [row[0] for row in r.fetchall()])
    except Exception as e:
        traceback.print_exc()

import sys
from dotenv import load_dotenv
load_dotenv()
asyncio.run(test_db())
