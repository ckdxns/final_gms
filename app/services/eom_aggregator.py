import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models import Branch, Company, CompanyReport, MonthlyAggregate


def run_monthly_aggregation(db: Session, target_year_month: str = None) -> Dict[str, Any]:
    """
    Aggregate cumulative reports per branch for target_year_month (YYYY-MM).
    If target_year_month is None, defaults to current YYYY-MM.
    """
    if not target_year_month:
        target_year_month = datetime.date.today().strftime("%Y-%m")

    branches = db.query(Branch).all()
    aggregated_results = []

    for branch in branches:
        companies = db.query(Company).filter(
            Company.branch_id == branch.id
        ).all()

        total_companies = len(companies)
        uploaded_count = 0
        sent_count = 0

        for c in companies:
            reps = c.reports
            if any(r.is_final for r in reps):
                uploaded_count += 1
            if reps and all(r.is_sent for r in reps):
                sent_count += 1

        sent_rate = round((sent_count / total_companies * 100), 1) if total_companies > 0 else 0.0

        existing = db.query(MonthlyAggregate).filter(
            MonthlyAggregate.year_month == target_year_month,
            MonthlyAggregate.branch_id == branch.id
        ).first()

        if existing:
            existing.total_companies = total_companies
            existing.reports_uploaded = uploaded_count
            existing.reports_sent = sent_count
            existing.sent_rate = sent_rate
            existing.aggregated_at = datetime.datetime.utcnow()
        else:
            agg = MonthlyAggregate(
                year_month=target_year_month,
                branch_id=branch.id,
                branch_name=branch.branch_name,
                total_companies=total_companies,
                reports_uploaded=uploaded_count,
                reports_sent=sent_count,
                sent_rate=sent_rate
            )
            db.add(agg)

        aggregated_results.append({
            "branch_id": branch.id,
            "branch_name": branch.branch_name,
            "country": branch.country,
            "total_companies": total_companies,
            "reports_uploaded": uploaded_count,
            "reports_sent": sent_count,
            "sent_rate": sent_rate
        })

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return {"success": False, "message": f"말일 집계 중 오류 발생: {str(e)}"}

    total_companies_all = sum(r["total_companies"] for r in aggregated_results)
    total_uploaded_all = sum(r["reports_uploaded"] for r in aggregated_results)
    total_sent_all = sum(r["reports_sent"] for r in aggregated_results)

    return {
        "success": True,
        "year_month": target_year_month,
        "message": f"{target_year_month}월 말일 집계가 성공적으로 완료되었습니다.",
        "summary": {
            "total_branches": len(branches),
            "total_companies": total_companies_all,
            "total_uploaded": total_uploaded_all,
            "total_sent": total_sent_all,
            "overall_sent_rate": round((total_sent_all / total_companies_all * 100), 1) if total_companies_all > 0 else 0.0
        },
        "branch_details": aggregated_results
    }
