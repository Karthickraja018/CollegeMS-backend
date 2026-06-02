import asyncio
import os
from dotenv import load_dotenv

async def test_embed():
    load_dotenv()
    from app.database import AsyncSessionLocal
    from app.intelligence.embedding_service import get_embedding_service
    
    svc = get_embedding_service()
    async with AsyncSessionLocal() as db:
        try:
            print("Embedding student...")
            await svc.update_entity_embedding(1, "Student test text", db)
            await db.commit()
            print("Success")
        except Exception as e:
            print(f"Exception: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_embed())
