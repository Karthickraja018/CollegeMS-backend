import os
from dotenv import load_dotenv
from groq import AsyncGroq
import asyncio

async def main():
    load_dotenv(override=True)
    api_key = os.environ.get("GROQ_API_KEY")
    print(f"Key loaded: {api_key[:10]}...")
    
    client = AsyncGroq(api_key=api_key)
    try:
        completion = await client.chat.completions.create(
            messages=[{"role": "user", "content": "Hello"}],
            model="llama-3.3-70b-versatile"
        )
        print("Success:", completion.choices[0].message.content)
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
