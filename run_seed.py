import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

async def run_seed():
    # Fix the url format for asyncpg if it has postgresql+asyncpg://
    url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    
    try:
        print("Dropping public schema...")
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        
        print("Executing college_schema.sql...")
        with open("../college_schema.sql", "r", encoding="utf-8") as f:
            schema_sql = f.read()
        await conn.execute(schema_sql)
        print("Schema created.")
        
        print("Executing seed_data.sql...")
        with open("../seed_data.sql", "r", encoding="utf-8") as f:
            seed_sql = f.read()
        await conn.execute(seed_sql)
        print("Seed data executed successfully.")
    except Exception as e:
        print(f"Error executing sql: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_seed())
