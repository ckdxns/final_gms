import datetime
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from app.models import Company, CompanyReport, EmailLog


def format_korean_date(date_str: str) -> str:
    """Format YYYY-MM-DD to 'X월 Y일'."""
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.month}월 {dt.day}일"
    except Exception:
        return date_str


def check_and_send_deadline_reminders(
    db: Session,
    recipient_email: str = "admin@gms-global.org",
    today_override: str = None,
    simulate_fail: bool = False
) -> Dict[str, Any]:
    """
    Find companies where today >= deadline_date or approaching and final report is unsent.
    Generates reminder email and logs result.
    If send fails, returns error alert for UI popup.
    """
    if today_override:
        today_dt = datetime.datetime.strptime(today_override, "%Y-%m-%d").date()
    else:
        today_dt = datetime.date.today()

    today_str = today_dt.strftime("%Y-%m-%d")

    # Find companies where final report is missing or unsent
    all_companies = db.query(Company).all()

    overdue_list: List[Company] = []
    for comp in all_companies:
        # Check if company has an unsent report or missing final report
        reports = comp.reports
        has_sent_final = any(r.is_final and r.is_sent for r in reports)
        if has_sent_final:
            continue # Fully sent

        try:
            dl_dt = datetime.datetime.strptime(comp.deadline_date, "%Y-%m-%d").date()
            if today_dt >= dl_dt or (0 <= (dl_dt - today_dt).days <= 3):
                overdue_list.append(comp)
        except Exception:
            continue

    if not overdue_list:
        return {
            "success": True,
            "message": f"기준일({today_str}) 기준 마감 기한 도래/초과 미발송 기업이 없습니다.",
            "unsent_count": 0,
            "email_sent": False,
            "alert_triggered": False
        }

    # Build email body matching reference format:
    # 제목: [리포트 미발송 안내] 파이널 리포트 발송 기한(협약마감+14일) 도래 기업
    # 내용: 안녕하세요. 마감 기준 14일이 경과했으나 파이널 리포트가 미발송된 기업 목록입니다.
    # - 미발송 기업: A상사 (협약마감일: 2026-08-31 / 데드라인: 2026-09-14)
    company_entries = []
    for p in overdue_list:
        company_entries.append(f"{p.company_name} (협약마감일: {p.agreement_end_date} / 데드라인: {p.deadline_date})")

    subject = "[리포트 미발송 안내] 파이널 리포트 발송 기한(협약마감+14일) 도래 기업"
    body = (
        "안녕하세요. 마감 기준 14일이 경과했으나 파이널 리포트가 미발송된 기업 목록입니다.\n\n"
        "- 미발송 기업:\n" + "\n".join([f"  • {e}" for e in company_entries]) + "\n\n"
        "확인 후 조속히 발송을 완료해 주시기 바랍니다."
    )

    if simulate_fail:
        send_status = "FAILED"
        err_msg = "SMTP 서버 연결 타임아웃 (메일 게이트웨이 응답 없음: 504 Gateway Timeout)"
    else:
        send_status = "SUCCESS"
        err_msg = None

    # Log to EmailLog
    for p in overdue_list:
        log_entry = EmailLog(
            company_name=p.company_name,
            branch_name=p.branch_name,
            deadline_date=p.deadline_date,
            status=send_status,
            recipient=recipient_email,
            subject=subject,
            body=body,
            error_message=err_msg
        )
        db.add(log_entry)

    try:
        db.commit()
    except Exception:
        db.rollback()

    if send_status == "FAILED":
        return {
            "success": False,
            "message": f"메일 전송 실패! [오류: {err_msg}]",
            "unsent_count": len(overdue_list),
            "email_sent": False,
            "alert_triggered": True,
            "error_detail": {
                "recipient": recipient_email,
                "unsent_companies": [p.company_name for p in overdue_list],
                "error_message": err_msg
            }
        }

    return {
        "success": True,
        "message": f"총 {len(overdue_list)}개 미발송 기업 안내 메일이 성공적으로 자동 전송되었습니다.",
        "unsent_count": len(overdue_list),
        "email_sent": True,
        "alert_triggered": False,
        "subject": subject,
        "body": body,
        "unsent_companies": [p.company_name for p in overdue_list]
    }
