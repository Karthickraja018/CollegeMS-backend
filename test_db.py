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
                WHERE table_name = 'colleges';
            """))
            cols = [row[0] for row in r.fetchall()]
            print('Columns in colleges:', cols)
            if 'settings' not in cols:
                print('NO SETTINGS COLUMN!')
                
                # Check if we can alter table
                try:
                    await session.execute(text("ALTER TABLE colleges ADD COLUMN settings JSONB DEFAULT '{}'::jsonb NOT NULL;"))
                    await session.commit()
                    print('Added settings column to colleges table!')
                except Exception as e:
                    print('Failed to add settings column:', e)
            else:
                print('Settings column exists!')
    except Exception as e:
        traceback.print_exc()

import sys
from dotenv import load_dotenv
load_dotenv()
asyncio.run(test_db())
