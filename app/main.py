import os
import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, File, UploadFile, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import engine, Base, get_db, SessionLocal
from app.models import Branch, Company, CompanyReport, EmailLog, MonthlyAggregate, BRANCH_SEED_DATA
from app.services.data_sync import process_file_upload, upsert_single_project, calculate_deadline
from app.services.scheduler_mail import check_and_send_deadline_reminders
from app.services.eom_aggregator import run_monthly_aggregation
from app.services.quality_engine import inspect_report_quality

# Initialize DB tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="해외지소 관리 및 파이널 리포트 모니터링 시스템",
    description="21개국 28개 지소별 진행 개사 수 및 리포트 실시간 업로드/발송 현황 대시보드 API",
    version="1.0.0"
)

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# Seed Initial Branch Data
def seed_branches_if_needed():
    db = SessionLocal()
    try:
        count = db.query(Branch).count()
        if count == 0:
            for item in BRANCH_SEED_DATA:
                b = Branch(
                    branch_name=item["branch_name"],
                    country=item["country"],
                    region=item["region"]
                )
                db.add(b)
            db.commit()
            print("[DB Seed] 28 branches initialized.")
    finally:
        db.close()


seed_branches_if_needed()


# Pydantic Schemas
class ManualProjectSchema(BaseModel):
    branch_name: str
    company_name: str
    agreement_end_date: str  # YYYY-MM-DD
    status: Optional[str] = "진행중"
    report_uploaded: Optional[bool] = False
    report_sent: Optional[bool] = False
    report_title: Optional[str] = None
    report_content: Optional[str] = None
    registered_date: Optional[str] = None
    contract_amount_usd: Optional[float] = 0.0


class InspectQualitySchema(BaseModel):
    report_content: str
    compare_against_text: Optional[str] = None
    project_id: Optional[int] = None
    agreement_end_date: Optional[str] = None
    today_override: Optional[str] = None


class TriggerMailSchema(BaseModel):
    recipient_email: Optional[str] = "admin@gms-global.org"
    today_override: Optional[str] = None
    simulate_fail: Optional[bool] = False


# HTML Page Route
@app.get("/", response_class=HTMLResponse)
def read_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


# RESET ALL DATA API
@app.delete("/api/reset")
def reset_all_data(db: Session = Depends(get_db)):
    """Clear all registered company and report data while retaining 28 branches."""
    db.query(CompanyReport).delete()
    db.query(Company).delete()
    db.query(MonthlyAggregate).delete()
    db.query(EmailLog).delete()
    db.commit()
    return {"success": True, "message": "전체 등록 데이터가 성공적으로 초기화(Reset)되었습니다."}


# KPI & Summary API
@app.get("/api/dashboard/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    companies = db.query(Company).all()
    branches = db.query(Branch).all()

    today_dt = datetime.date.today()
    current_year = str(today_dt.year)

    total_projects = len(companies)

    # 2026 / Current Year agreement ending companies
    this_year_companies = [
        c for c in companies if c.agreement_end_date and c.agreement_end_date.startswith(current_year)
    ]
    this_year_count = len(this_year_companies)

    # Upload & Sent rate calculations
    this_year_uploaded = 0
    this_year_sent = 0

    for c in this_year_companies:
        reps = c.reports
        if any(r.is_final for r in reps):
            this_year_uploaded += 1
        if reps and all(r.is_sent for r in reps):
            this_year_sent += 1

    this_year_upload_rate = round((this_year_uploaded / this_year_count * 100), 1) if this_year_count > 0 else 0.0
    this_year_sent_rate = round((this_year_sent / this_year_count * 100), 1) if this_year_count > 0 else 0.0

    # Overdue or Risk companies
    overdue_risk_count = 0
    for c in companies:
        reps = c.reports
        all_sent = reps and all(r.is_sent for r in reps)
        if not all_sent and c.deadline_date:
            try:
                dl_dt = datetime.datetime.strptime(c.deadline_date, "%Y-%m-%d").date()
                if today_dt >= dl_dt or (0 <= (dl_dt - today_dt).days <= 3):
                    overdue_risk_count += 1
            except Exception:
                pass

    # Branch summaries
    branch_summaries = []
    for b in branches:
        b_comps = [c for c in companies if c.branch_name == b.branch_name]
        b_total = len(b_comps)
        b_uploaded = sum(1 for c in b_comps if any(r.is_final for r in c.reports))
        b_sent = sum(1 for c in b_comps if c.reports and all(r.is_sent for r in c.reports))
        b_risk = 0
        for c in b_comps:
            all_sent = c.reports and all(r.is_sent for r in c.reports)
            if not all_sent and c.deadline_date:
                try:
                    dl_dt = datetime.datetime.strptime(c.deadline_date, "%Y-%m-%d").date()
                    if today_dt >= dl_dt or (0 <= (dl_dt - today_dt).days <= 3):
                        b_risk += 1
                except Exception:
                    pass

        branch_summaries.append({
            "branch_id": b.id,
            "branch_name": b.branch_name,
            "country": b.country,
            "region": b.region,
            "total_companies": b_total,
            "uploaded_count": b_uploaded,
            "sent_count": b_sent,
            "risk_count": b_risk,
            "upload_rate": round((b_uploaded / b_total * 100), 1) if b_total > 0 else 0.0,
            "sent_rate": round((b_sent / b_total * 100), 1) if b_total > 0 else 0.0
        })

    return {
        "kpi": {
            "total_projects": total_projects,
            "this_year_count": this_year_count,
            "this_year_upload_rate": this_year_upload_rate,
            "this_year_sent_rate": this_year_sent_rate,
            "overdue_risk_count": overdue_risk_count,
            "current_year": current_year,
            "total_branches": len(branches),
            "total_countries": 21
        },
        "branch_summaries": branch_summaries
    }


# Branch List API
@app.get("/api/branches")
def get_branches(db: Session = Depends(get_db)):
    branches = db.query(Branch).all()
    return [{"id": b.id, "branch_name": b.branch_name, "country": b.country, "region": b.region} for b in branches]


# Projects/Companies List & Search API
@app.get("/api/projects")
def get_projects(
    branch_name: Optional[str] = None,
    country: Optional[str] = None,
    status: Optional[str] = None,
    risk_only: Optional[bool] = False,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Company)

    if branch_name:
        query = query.filter(Company.branch_name == branch_name)
    if country:
        query = query.join(Branch).filter(Branch.country == country)
    if status:
        query = query.filter(Company.status == status)
    if search:
        s_term = f"%{search.strip()}%"
        query = query.filter(
            (Company.company_name.like(s_term)) |
            (Company.branch_name.like(s_term))
        )

    companies = query.order_by(Company.agreement_end_date.asc()).all()

    today_dt = datetime.date.today()
    result = []
    for c in companies:
        reps = c.reports
        reports_count = len(reps)
        total_contract_usd = sum(r.contract_amount_usd or 0.0 for r in reps)
        report_uploaded = any(r.is_final for r in reps) or reports_count > 0
        report_sent = all(r.is_sent for r in reps) if reports_count > 0 else False
        
        last_reg_date = max([r.registered_date for r in reps if r.registered_date], default=None)

        # Risk status calculation
        is_risk = False
        is_overdue = False
        days_left = None
        if c.deadline_date:
            try:
                dl_dt = datetime.datetime.strptime(c.deadline_date, "%Y-%m-%d").date()
                days_left = (dl_dt - today_dt).days
                if not report_sent:
                    if days_left < 0:
                        is_overdue = True
                        is_risk = True
                    elif days_left <= 3:
                        is_risk = True
            except Exception:
                pass

        if risk_only and not is_risk:
            continue

        result.append({
            "id": c.id,
            "company_code": c.company_code,
            "branch_id": c.branch_id,
            "branch_name": c.branch_name,
            "company_name": c.company_name,
            "business_reg_no": c.business_reg_no or '',
            "registered_date": last_reg_date or '',
            "agreement_end_date": c.agreement_end_date,
            "deadline_date": c.deadline_date,
            "status": c.status,
            "reports_count": reports_count,
            "contract_amount_usd": total_contract_usd,
            "report_uploaded": report_uploaded,
            "report_sent": report_sent,
            "is_risk": is_risk,
            "is_overdue": is_overdue,
            "days_left": days_left
        })

    return result


# Company Detailed Child Reports List API (Drill-down)
@app.get("/api/companies/{company_id}/reports")
def get_company_reports(company_id: int, db: Session = Depends(get_db)):
    comp = db.query(Company).filter(Company.id == company_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="해당 기업을 찾을 수 없습니다.")

    reps = comp.reports
    return {
        "company_id": comp.id,
        "company_code": comp.company_code,
        "company_name": comp.company_name,
        "branch_name": comp.branch_name,
        "agreement_end_date": comp.agreement_end_date,
        "deadline_date": comp.deadline_date,
        "reports": [
            {
                "id": r.id,
                "report_title": r.report_title or f"{comp.company_name} 리포트",
                "registered_date": r.registered_date or "",
                "is_final": r.is_final,
                "is_sent": r.is_sent,
                "contract_amount_usd": r.contract_amount_usd or 0.0,
                "report_content": r.report_content or ""
            }
            for r in reps
        ]
    }


# CSV / Excel Upload API
@app.post("/api/projects/upload")
async def upload_file(
    file: UploadFile = File(...),
    file_type: str = Form("auto"),
    db: Session = Depends(get_db)
):
    contents = await file.read()
    res = process_file_upload(contents, file.filename, db, file_type=file_type)
    return res


# Manual Entry Form API (Upsert)
@app.post("/api/projects/manual")
def create_or_update_manual(payload: ManualProjectSchema, db: Session = Depends(get_db)):
    res = upsert_single_project(payload.dict(), db)
    return {"success": True, "message": f"'{res.company_name}' 기업 정보가 성공적으로 저장되었습니다."}


# Single Company Edit API
@app.put("/api/projects/{project_id}")
def update_project(project_id: int, payload: ManualProjectSchema, db: Session = Depends(get_db)):
    comp = db.query(Company).filter(Company.id == project_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="해당 기업을 찾을 수 없습니다.")

    branch = db.query(Branch).filter(Branch.branch_name == payload.branch_name).first()
    if not branch:
        raise HTTPException(status_code=400, detail=f"존재하지 않는 지소명입니다: {payload.branch_name}")

    comp.branch_id = branch.id
    comp.branch_name = payload.branch_name
    comp.company_name = payload.company_name
    comp.agreement_end_date = payload.agreement_end_date
    comp.deadline_date = calculate_deadline(payload.agreement_end_date)
    comp.status = payload.status
    comp.updated_at = datetime.datetime.utcnow()

    db.commit()
    return {"success": True, "message": "성공적으로 수정되었습니다."}


# Delete Company API
@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    comp = db.query(Company).filter(Company.id == project_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="해당 기업을 찾을 수 없습니다.")

    db.delete(comp)
    db.commit()
    return {"success": True, "message": "삭제되었습니다."}


# Delete Single Report API
@app.delete("/api/reports/{report_id}")
def delete_report(report_id: int, db: Session = Depends(get_db)):
    rep = db.query(CompanyReport).filter(CompanyReport.id == report_id).first()
    if not rep:
        raise HTTPException(status_code=404, detail="해당 리포트를 찾을 수 없습니다.")

    db.delete(rep)
    db.commit()
    return {"success": True, "message": "해당 리포트가 삭제되었습니다."}


# Trigger Email Reminder Scheduler API
@app.post("/api/scheduler/trigger-mail")
def trigger_email_scheduler(payload: TriggerMailSchema, db: Session = Depends(get_db)):
    res = check_and_send_deadline_reminders(
        db,
        recipient_email=payload.recipient_email,
        today_override=payload.today_override,
        simulate_fail=payload.simulate_fail
    )
    return res


# Email Logs API
@app.get("/api/scheduler/logs")
def get_email_logs(db: Session = Depends(get_db)):
    logs = db.query(EmailLog).order_by(EmailLog.sent_at.desc()).limit(50).all()
    return [
        {
            "id": l.id,
            "company_name": l.company_name,
            "branch_name": l.branch_name,
            "deadline_date": l.deadline_date,
            "status": l.status,
            "recipient": l.recipient,
            "subject": l.subject,
            "body": l.body,
            "error_message": l.error_message,
            "sent_at": l.sent_at.strftime("%Y-%m-%d %H:%M:%S") if l.sent_at else ""
        }
        for l in logs
    ]


# Month-end Aggregation Trigger API
@app.post("/api/aggregate/run")
def trigger_monthly_aggregation(target_ym: Optional[str] = Query(None), db: Session = Depends(get_db)):
    res = run_monthly_aggregation(db, target_year_month=target_ym)
    return res


# Month-end Aggregation History API
@app.get("/api/aggregate/history")
def get_monthly_aggregation_history(db: Session = Depends(get_db)):
    aggregates = db.query(MonthlyAggregate).order_by(
        MonthlyAggregate.year_month.desc(),
        MonthlyAggregate.branch_name.asc()
    ).all()
    
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for a in aggregates:
        ym = a.year_month
        if ym not in grouped:
            grouped[ym] = []
        grouped[ym].append({
            "branch_id": a.branch_id,
            "branch_name": a.branch_name,
            "total_companies": a.total_companies,
            "reports_uploaded": a.reports_uploaded,
            "reports_sent": a.reports_sent,
            "sent_rate": a.sent_rate
        })
    return grouped


# Quality Inspection API
@app.post("/api/quality/inspect")
def inspect_quality(payload: InspectQualitySchema, db: Session = Depends(get_db)):
    res = inspect_report_quality(
        report_content=payload.report_content,
        db=db,
        exclude_report_id=payload.project_id,
        compare_against_text=payload.compare_against_text,
        agreement_end_date=payload.agreement_end_date,
        today_override=payload.today_override
    )
    return res


# Download Template Sample
@app.get("/api/sample-template")
def download_sample_template():
    csv_path = os.path.join(STATIC_DIR, "sample_template.csv")
    if os.path.exists(csv_path):
        return FileResponse(
            csv_path,
            media_type="text/csv",
            filename="sample_upload_template.csv"
        )
    raise HTTPException(status_code=404, detail="템플릿 파일을 찾을 수 없습니다.")
