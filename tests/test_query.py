import asyncio
import time
from app.database import AsyncSessionLocal
from app.agents.supervisor import build_supervisor_graph
from app.agents.state import AgentState

async def run():
    print("Starting query trace...")
    async with AsyncSessionLocal() as db:
        graph = build_supervisor_graph(db)
        state = {
            "messages": [("user", "Compare attendance between CSE and ECE")],
            "user_query": "Compare attendance between CSE and ECE",
            "memory_context": {},
            "intent": {},
            "query_plan": [],
            "agent_used": "",
            "agent_pipeline": [],
            "sql_result": [],
            "analytics_result": None,
            "chart_spec": None,
            "report_url": None,
            "risk_analysis": None,
            "final_response": "",
            "insights": [],
            "recommendations": [],
            "error": None,
            "iterations": 0,
            "user_role": "admin",
            "user_department_id": None,
            "is_institution_wide": True,
            "student_filter": "all",
            "dept_filter_sql": "",
            "student_filter_sql": "",
        }
        
        last_time = time.time()
        start_time = last_time
        async for output in graph.astream(state):
            for node_name, new_state in output.items():
                current_time = time.time()
                elapsed = current_time - last_time
                print(f"-> Node [{node_name}] finished in {elapsed:.2f}s")
                last_time = current_time
        
        total_time = time.time() - start_time
        print(f"Total time: {total_time:.2f}s")

if __name__ == "__main__":
    asyncio.run(run())
