import httpx
import asyncio

async def test_generate():
    async with httpx.AsyncClient() as client:
        print("Logging in...")
        resp = await client.post(
            "http://localhost:8000/api/auth/login",
            data={"username": "principal@collegems.edu", "password": "password123"}
        )
        token = resp.json().get("access_token")
        
        print("Generating report...")
        resp = await client.post(
            "http://localhost:8000/api/reports/generate",
            json={
                "report_type": "department",
                "format": "pdf",
                "parameters": {"department": "Computer Science and Engineering"}
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0
        )
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.json()}")

if __name__ == "__main__":
    asyncio.run(test_generate())
