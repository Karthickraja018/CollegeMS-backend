import asyncio
import os
from dotenv import load_dotenv

async def seed():
    load_dotenv()
    from app.database import get_db, AsyncSessionLocal
    from app.intelligence.knowledge_seeder import KnowledgeSeeder
    async with AsyncSessionLocal() as db:
        print("Seeding knowledge store...")
        counts = await KnowledgeSeeder.seed_all(db)
        print("Counts:", counts)

if __name__ == "__main__":
    asyncio.run(seed())
