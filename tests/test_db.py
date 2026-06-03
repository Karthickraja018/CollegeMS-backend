import asyncio
from app.database import AsyncSessionLocal
from sqlalchemy import text

async def test():
    print("Testing DB...")
    async with AsyncSessionLocal() as db:
        print("Connected. Executing query...")
        result = await db.execute(text("SELECT 1"))
        print("Result:", result.scalar())

if __name__ == '__main__':
    asyncio.run(test())
