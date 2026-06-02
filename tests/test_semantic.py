import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
import os
from dotenv import load_dotenv

load_dotenv()
async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as conn:
        from sqlalchemy import text
        res = await conn.execute(text("SELECT entity_name, primary_table FROM semantic_entities WHERE entity_name = 'Attendance'"))
        print(res.fetchall())
asyncio.run(main())
