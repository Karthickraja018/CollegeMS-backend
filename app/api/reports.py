"""
Reports API — generate and download reports.
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User, UserRole
from app.models.report import Report, ReportType, ReportFormat
from app.config import get_settings

router = APIRouter(prefix="/reports", tags=["reports"])
settings = get_settings()


class GenerateReportRequest(BaseModel):
    report_type: ReportType
    format: ReportFormat = ReportFormat.pdf
    parameters: dict = {}


@router.post("/generate")
async def generate_report(
    body: GenerateReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a report via the Report Agent."""
    if current_user.role not in [UserRole.admin, UserRole.principal, UserRole.hod]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to generate reports")

    from app.agents.report_agent import report_agent_node
    from app.agents.state import AgentState

    query = f"Generate a {body.report_type.value} report"
    if body.parameters.get("department"):
        query += f" for {body.parameters['department']} department"
    if body.parameters.get("semester"):
        query += f" semester {body.parameters['semester']}"

    state: AgentState = {
        "messages": [("user", query)],
        "user_query": query,
        "agent_used": "report",
        "sql_result": [],
        "chart_spec": None,
        "report_url": None,
        "risk_analysis": None,
        "final_response": "",
        "error": None,
        "iterations": 0,
    }

    result = await report_agent_node(state, db)

    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    # Save report record to DB
    import json
    report = Report(
        title=f"{body.report_type.value.replace('_', ' ').title()} Report",
        report_type=body.report_type,
        format=body.format,
        file_path=result.get("report_url"),
        parameters=json.dumps(body.parameters),
        generated_by_id=current_user.id,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    return {
        "id": report.id,
        "title": report.title,
        "report_type": report.report_type.value,
        "download_url": result.get("report_url"),
        "content_preview": result.get("final_response", "")[:500],
    }


@router.get("")
async def list_reports(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all generated reports."""
    from sqlalchemy import select, desc
    result = await db.execute(
        select(Report).order_by(desc(Report.created_at)).limit(50)
    )
    reports = result.scalars().all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "report_type": r.report_type.value,
            "format": r.format.value,
            "created_at": r.created_at.isoformat(),
            "download_url": f"/api/reports/download/{os.path.basename(r.file_path)}" if r.file_path else None,
        }
        for r in reports
    ]


@router.get("/download/{filename}")
async def download_report(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Download a generated report file."""
    # Security: only allow alphanumeric filenames with safe extensions
    import re
    if not re.match(r"^[\w\-]+\.(pdf|docx)$", filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    filepath = os.path.join(settings.reports_dir, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Report file not found")

    media_type = "application/pdf" if filename.endswith(".pdf") else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(filepath, media_type=media_type, filename=filename)
