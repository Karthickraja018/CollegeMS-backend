import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

async def fix_db():
    db_url = "postgresql+asyncpg://postgres:Karthick0809@db.qhlmuyrphmqipidxbrhr.supabase.co:5432/postgres"
    engine = create_async_engine(db_url)

    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS reports CASCADE;"))
        await conn.execute(text("""
        CREATE TABLE reports (
            id SERIAL PRIMARY KEY,
            college_id INTEGER NOT NULL REFERENCES colleges(id),
            generated_by INTEGER NOT NULL REFERENCES users(id),
            title VARCHAR(255) NOT NULL,
            report_type VARCHAR(50) NOT NULL,
            format VARCHAR(50) DEFAULT 'pdf' NOT NULL,
            file_path VARCHAR(500),
            file_size_kb INTEGER,
            parameters JSON NOT NULL DEFAULT '{}',
            status VARCHAR(50) DEFAULT 'queued' NOT NULL,
            error_message TEXT,
            celery_task_id VARCHAR(255),
            validation_passed BOOLEAN,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            completed_at TIMESTAMP WITH TIME ZONE
        );
        """))
        print("Dropped and recreated reports table with correct string types.")

if __name__ == "__main__":
    asyncio.run(fix_db())
