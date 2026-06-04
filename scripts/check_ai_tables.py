import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url)

async def check():
    async with AsyncSession(engine) as session:
        # Check chat_sessions
        res = await session.execute(text("SELECT COUNT(*) FROM chat_sessions"))
        print("chat_sessions:", res.scalar())
        # Check at_risk_snapshots
        try:
            res = await session.execute(text("SELECT COUNT(*) FROM at_risk_snapshots"))
            print("at_risk_snapshots:", res.scalar())
        except Exception as e:
            print("at_risk_snapshots error:", e)
            await session.rollback()
        # Check reports
        try:
            res = await session.execute(text("SELECT COUNT(*) FROM reports"))
            print("reports:", res.scalar())
        except Exception as e:
            print("reports error:", e)
            await session.rollback()

if __name__ == "__main__":
    asyncio.run(check())
