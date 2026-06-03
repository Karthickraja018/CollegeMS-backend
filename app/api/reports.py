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
from app.models.report import Report, ReportType, ReportFormat, ReportStatus
from app.config import get_settings

router = APIRouter(prefix="/reports", tags=["reports"])
settings = get_settings()


class GenerateReportRequest(BaseModel):
    report_type: str
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

    # Determine department filter (if any)
    dept_name = None
    if current_user.role == UserRole.hod and current_user.department_id:
        # HOD can only see their own department
        from app.models.department import Department
        from sqlalchemy import select
        dept = await db.scalar(select(Department).where(Department.id == current_user.department_id))
        if dept:
            dept_name = dept.name
    else:
        dept_name = body.parameters.get("department")

    state: AgentState = {
        "messages": [],
        "user_query": body.report_type,  # Pass report_type down directly
        "intent": {"entities": {"departments": [dept_name] if dept_name else []}},
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
        college_id=current_user.college_id,
        title=f"{body.report_type.replace('_', ' ').title()} Report",
        report_type=body.report_type,
        format=body.format,
        file_path=result.get("report_url"),
        parameters=json.dumps(body.parameters),
        generated_by=current_user.id,
        status=ReportStatus.completed,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    return {
        "id": report.id,
        "title": report.title,
        "report_type": body.report_type,
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
            "report_type": r.report_type,
            "format": r.format,
            "created_at": r.created_at.isoformat(),
            "download_url": f"/api/reports/download/{os.path.basename(r.file_path)}" if r.file_path else None,
        }
        for r in reports
    ]


@router.get("/download/{filename}")
async def download_report(
    filename: str,
    download: bool = False,
):
    """Download or view a generated report file."""
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
    if download:
        return FileResponse(filepath, media_type=media_type, filename=filename)
    return FileResponse(filepath, media_type=media_type, content_disposition_type="inline")
