"""
Principal Agent — routes to the full Supervisor multi-agent system.

Instead of a thin LLM wrapper, this delegates to the existing Supervisor
which correctly routes to: Performance Agent, Analytics Agent, Query Agent,
or Report Agent depending on the user's intent.
"""
from sqlalchemy.ext.asyncio import AsyncSession


async def run_principal_agent(query: str, college_id: int, db: AsyncSession) -> str:
    """
    Route the principal's query through the full Supervisor Agent graph.
    This gives access to the complete multi-agent system:
    - Performance Agent for risk analysis
    - Analytics Agent for KPIs and comparisons
    - Query Agent for Text-to-SQL
    - Report Agent for accreditation reports
    """
    try:
        from app.agents.supervisor import build_supervisor_graph
        from app.agents.state import AgentState

        initial_state: AgentState = {
            "messages": [("user", query)],
            "user_query": query,
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
            "user_role": "principal",
            "user_department_id": None,
            "is_institution_wide": True,
            "student_filter": "all",
            "dept_filter_sql": "",
            "student_filter_sql": "",
        }

        graph = build_supervisor_graph(db)
        result = await graph.ainvoke(initial_state)
        return result.get("final_response") or "Analysis complete."

    except Exception as e:
        # Fallback: lightweight LLM response
        from app.llm.provider_factory import get_llm_provider
        llm = get_llm_provider()
        system_prompt = (
            "You are the AI Executive Briefing Copilot for a College Principal. "
            "Answer concisely and professionally. If data is needed, recommend visiting the AI Copilot."
        )
        try:
            return await llm.generate(
                messages=[{"role": "user", "content": query}],
                system_prompt=system_prompt,
                temperature=0.1,
                model_name="llama-3.1-8b-instant"
            )
        except Exception:
            return "Unable to process query at this time. Please use the AI Copilot (/chat) for full analysis."
