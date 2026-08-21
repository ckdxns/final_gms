import re
import difflib
import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models import CompanyReport, Company

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


def calculate_text_similarity(text1: str, text2: str) -> float:
    """Calculate similarity percentage between two texts (0.0 to 100.0)."""
    if not text1 or not text2:
        return 0.0
    
    t1 = text1.strip().lower()
    t2 = text2.strip().lower()
    
    if t1 == t2:
        return 100.0

    if SKLEARN_AVAILABLE:
        try:
            vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4))
            tfidf = vectorizer.fit_transform([t1, t2])
            sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
            return round(float(sim) * 100, 1)
        except Exception:
            pass

    seq = difflib.SequenceMatcher(None, t1, t2)
    return round(seq.ratio() * 100, 1)


def check_date_presence(text: str) -> bool:
    """Check if date expression is present in the text."""
    if not text:
        return False
    
    patterns = [
        r"\b(19|20)\d{2}[-./\s]\d{1,2}[-./\s]\d{1,2}\b",
        r"\b(19|20)\d{2}년\s*\d{1,2}월(\s*\d{1,2}일)?\b",
        r"\b\d{1,2}월\s*\d{1,2}일\b",
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+(19|20)\d{2}\b",
        r"\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(19|20)\d{2}\b",
        r"\b(19|20)\d{2}[-./]\d{1,2}\b"
    ]
    
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
            
    return False


def check_final_report_keyword(text: str) -> bool:
    """Check if 'Final Report' or '파이널 리포트' / '파이널리포트' is present in text."""
    if not text:
        return False
    
    t_lower = text.lower()
    keywords = ["final report", "파이널 리포트", "파이널리포트", "final_report", "final-report"]
    return any(kw in t_lower for kw in keywords)


def inspect_report_quality(
    report_content: str,
    db: Session = None,
    exclude_report_id: Optional[int] = None,
    compare_against_text: Optional[str] = None,
    agreement_end_date: Optional[str] = None,
    today_override: Optional[str] = None
) -> Dict[str, Any]:
    """
    Quality inspection engine for report content:
    1. Duplicate Check: text similarity against DB existing reports or compare_against_text
    2. Inadequacy Check: Date presence & 'Final Report' keyword presence
       (Triggered ONLY when agreement end date has arrived or passed: today >= agreement_end_date)
    """
    today_dt = datetime.datetime.strptime(today_override, "%Y-%m-%d").date() if today_override else datetime.date.today()
    is_agreement_ended = True
    if agreement_end_date:
        try:
            end_dt = datetime.datetime.strptime(agreement_end_date, "%Y-%m-%d").date()
            if today_dt < end_dt:
                is_agreement_ended = False
        except Exception:
            is_agreement_ended = True

    if not report_content or not report_content.strip():
        empty_warnings = ["리포트 내용이 비어 있습니다."]
        if is_agreement_ended:
            empty_warnings.extend([
                f"[부실 경고] 리포트 내 날짜(Date, 예: {today_dt.strftime('%Y-%m-%d')}) 표기가 누락되었습니다.",
                "[부실 경고] 'Final Report' (또는 '파이널 리포트') 필수 문구가 누락되었습니다."
            ])
        else:
            empty_warnings.append("(협약 마감일 이전 - 마감일 도래 시 부실 검증 경고가 활성화됩니다)")

        return {
            "passed": False,
            "overall_score": 0,
            "duplicate_check": {
                "max_similarity": 0.0,
                "warning": False,
                "matched_company": None,
                "message": "리포트 내용이 비어 있습니다."
            },
            "inadequacy_check": {
                "has_date": False,
                "has_final_report_keyword": False,
                "warnings": empty_warnings
            }
        }

    clean_content = report_content.strip()

    # 1. Duplicate check
    max_similarity = 0.0
    matched_company = None
    matched_title = None

    if compare_against_text:
        max_similarity = calculate_text_similarity(clean_content, compare_against_text)
        if max_similarity > 0:
            matched_company = "직접 비교 대상 텍스트"
    elif db:
        query = db.query(CompanyReport).filter(
            CompanyReport.report_content.isnot(None),
            CompanyReport.report_content != ""
        )
        if exclude_report_id:
            query = query.filter(CompanyReport.id != exclude_report_id)
        
        existing_reports = query.all()
        for rep in existing_reports:
            sim = calculate_text_similarity(clean_content, rep.report_content)
            if sim > max_similarity:
                max_similarity = sim
                comp = rep.company_rel
                matched_company = f"{comp.company_name} ({comp.branch_name})" if comp else "기존 리포트"
                matched_title = rep.report_title or "제목 없음"

    duplicate_warning = max_similarity >= 60.0
    dup_msg = "중복 없음 (기존 리포트와 고유한 내용입니다)."
    if duplicate_warning:
        dup_msg = f"중복/복사 의심 경고! 유사도 {max_similarity}% (비교 대상: {matched_company})"

    # 2. Conditional Inadequacy check
    has_date = check_date_presence(clean_content)
    has_final_keyword = check_final_report_keyword(clean_content)

    inadequacy_warnings = []
    score = 100
    if duplicate_warning:
        score -= min(40, int(max_similarity * 0.5))

    if is_agreement_ended:
        if not has_date:
            inadequacy_warnings.append(f"[부실 경고] 리포트 내 날짜(Date, 예: {today_dt.strftime('%Y-%m-%d')}) 표기가 누락되었습니다.")
            score -= 30
        if not has_final_keyword:
            inadequacy_warnings.append("[부실 경고] 'Final Report' (또는 '파이널 리포트') 필수 문구가 누락되었습니다.")
            score -= 30
    else:
        inadequacy_warnings.append("(협약 마감일 이전 - 마감일 도래 시 부실 검증 경고가 활성화됩니다)")

    score = max(0, score)
    passed = (not duplicate_warning) and (not is_agreement_ended or (has_date and has_final_keyword))

    return {
        "passed": passed,
        "overall_score": score,
        "duplicate_check": {
            "max_similarity": max_similarity,
            "warning": duplicate_warning,
            "matched_company": matched_company,
            "matched_title": matched_title,
            "message": dup_msg
        },
        "inadequacy_check": {
            "has_date": has_date,
            "has_final_report_keyword": has_final_keyword,
            "warnings": inadequacy_warnings if inadequacy_warnings else ["부실 요인 없음 (날짜 및 Final Report 필수 문구 정상 포함)"]
        }
    }
