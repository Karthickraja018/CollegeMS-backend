import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
import os
from dotenv import load_dotenv

load_dotenv()
async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as conn:
        from sqlalchemy import text
        res = await conn.execute(text("SELECT id, name, code FROM departments LIMIT 10"))
        print("--- DEPARTMENTS ---")
        for row in res.fetchall():
            print(row)

        res = await conn.execute(text("SELECT COUNT(*) FROM marks_records"))
        print("Total marks_records:", res.scalar())

        res = await conn.execute(text("SELECT COUNT(*) FROM marks"))
        print("Total marks:", res.scalar())

asyncio.run(main())
