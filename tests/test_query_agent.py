import asyncio
import os
from dotenv import load_dotenv

async def verify_query():
    load_dotenv()
    from app.database import AsyncSessionLocal
    from app.agents.supervisor import build_supervisor_graph
    
    async with AsyncSessionLocal() as db:
        print("Initializing supervisor...")
        graph = build_supervisor_graph(db)
        
        query = "Show students with attendance below 75%"
        print(f"Executing query: {query}")
        
        # Initial state
        state = {
            "user_query": query,
            "messages": [{"role": "user", "content": query}],
        }
        
        # Run graph
        result = await graph.ainvoke(state)
        
        print("\n--- RESULTS ---")
        print("Intent:", result.get("intent"))
        print("Agent Pipeline:", result.get("agent_pipeline"))
        print("SQL Query:", result.get("generated_sql"))
        print("Summary:", result.get("result_summary"))
        
        rows = result.get("sql_result", [])
        print(f"Row count: {len(rows)}")
        if rows:
            print("First row:", rows[0])

if __name__ == "__main__":
    asyncio.run(verify_query())
