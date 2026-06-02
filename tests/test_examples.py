import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
import os
from dotenv import load_dotenv

load_dotenv()
async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as conn:
        from sqlalchemy import text
        res = await conn.execute(text("SELECT question, generated_sql FROM query_examples WHERE question ILIKE '%attendance%'"))
        for row in res.fetchall():
            print(row[0])
            print(row[1])
            print("---")
asyncio.run(main())
