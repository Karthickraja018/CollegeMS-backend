import asyncio
from app.llm.provider_factory import get_llm_provider

async def test():
    print("Testing LLM...")
    llm = get_llm_provider()
    resp = await llm.generate([{'role':'user', 'content':'hi'}])
    print("Response:", resp)

if __name__ == '__main__':
    asyncio.run(test())
