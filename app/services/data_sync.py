import re
import datetime
import pandas as pd
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.models import Branch, Company, CompanyReport

ALIAS_TO_ENGLISH_BRANCH = {
    # English names (case-insensitive keys)
    "shanghai": "Shanghai", "shenyang": "Shenyang", "guangzhou": "Guangzhou", "chongqing": "Chongqing",
    "tokyo": "Tokyo", "taipei": "Taipei", "kuala lumpur": "Kuala Lumpur", "kl": "Kuala Lumpur",
    "ho chi minh": "Ho Chi Minh", "hanoi": "Hanoi", "bangkok": "Bangkok", "jakarta": "Jakarta",
    "manila": "Manila", "sydney": "Sydney", "mumbai": "Mumbai", "bengaluru": "Bengaluru",
    "nairobi": "Nairobi", "istanbul": "Istanbul", "dubai": "Dubai", "moscow": "Moscow",
    "tashkent": "Tashkent", "l.a": "L.A", "la": "L.A", "l.a.": "L.A", "los angeles": "L.A",
    "new york": "New York", "dallas": "Dallas", "vancouver": "Vancouver",
    "mexico city": "Mexico City", "santiago": "Santiago", "frankfurt": "Frankfurt", "warsaw": "Warsaw",
    # Korean names
    "상하이": "Shanghai", "선양": "Shenyang", "광저우": "Guangzhou", "충칭": "Chongqing",
    "도쿄": "Tokyo", "타이페이": "Taipei", "쿠알라룸푸르": "Kuala Lumpur",
    "호치민": "Ho Chi Minh", "하노이": "Hanoi", "방콕": "Bangkok", "자카르타": "Jakarta",
    "마닐라": "Manila", "시드니": "Sydney", "뭄바이": "Mumbai", "벵갈루루": "Bengaluru",
    "나이로비": "Nairobi", "이스탄불": "Istanbul", "두바이": "Dubai", "모스크바": "Moscow",
    "타슈켄트": "Tashkent", "뉴욕": "New York", "댈러스": "Dallas",
    "밴쿠버": "Vancouver", "멕시코시티": "Mexico City", "산티아고": "Santiago",
    "프랑크푸르트": "Frankfurt", "바르샤바": "Warsaw"
}


def parse_date_string(date_val: Any) -> str:
    """Parse various date formats and return YYYY-MM-DD string."""
    if pd.isna(date_val) or date_val is None:
        raise ValueError("날짜 값이 누락되었습니다.")
    
    if isinstance(date_val, (datetime.datetime, datetime.date)):
        return date_val.strftime("%Y-%m-%d")
    
    s = str(date_val).strip()
    if not s:
        raise ValueError("날짜 값이 비어있습니다.")
    
    s = s.split(" ")[0]
    s = s.replace(".", "-").replace("/", "-")
    
    parts = [p.zfill(2) for p in s.split("-") if p]
    if len(parts) == 3:
        year, month, day = parts[0], parts[1], parts[2]
        if len(year) == 4 and 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
            return f"{year}-{month}-{day}"
    
    raise ValueError(f"유효하지 않은 날짜 형식입니다: '{date_val}' (YYYY-MM-DD 형식 필요)")


def extract_end_date_from_period(period_val: Any) -> str:
    """Extract end date from agreement period string like '2025.09.01 ~ 2026.08.31'."""
    if pd.isna(period_val) or not period_val:
        return datetime.date.today().strftime("%Y-%m-%d")
    
    s = str(period_val).strip()
    dates = re.findall(r'\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}', s)
    if dates:
        last_date_str = dates[-1]
        try:
            return parse_date_string(last_date_str)
        except Exception:
            pass
    
    try:
        return parse_date_string(s)
    except Exception:
        return datetime.date.today().strftime("%Y-%m-%d")


def calculate_deadline(agreement_end_date_str: str) -> str:
    """Calculate 파이널 리포트 deadline: agreement_end_date + 14 days."""
    try:
        dt = datetime.datetime.strptime(agreement_end_date_str, "%Y-%m-%d").date()
        dl = dt + datetime.timedelta(days=14)
        return dl.strftime("%Y-%m-%d")
    except Exception:
        return agreement_end_date_str


def parse_bool_val(val: Any) -> bool:
    """Parse boolean flag from various inputs."""
    if pd.isna(val) or val is None:
        return False
    if isinstance(val, bool):
        return val
    s = str(val).strip().upper()
    return s in ["Y", "YES", "TRUE", "1", "예", "완료", "O", "성공"]


def read_excel_dataframe(file_contents: bytes, filename: str) -> Dict[str, Any]:
    """Read excel/csv file into pandas DataFrame ignoring sheet '[0. 총괄]' if present."""
    if filename.lower().endswith(".csv"):
        import io
        try:
            df = pd.read_csv(io.BytesIO(file_contents), encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(io.BytesIO(file_contents), encoding="cp949")
        return {"df": df, "sheet_name": "CSV"}

    import io
    excel_file = pd.ExcelFile(io.BytesIO(file_contents))
    sheet_names = excel_file.sheet_names
    
    target_sheet = sheet_names[0]
    for s in sheet_names:
        s_clean = s.strip()
        if "총괄" not in s_clean:
            target_sheet = s
            break
            
    df = excel_file.parse(target_sheet)
    
    # Header check
    has_gbc = any("GBC" in str(c) or "지소" in str(c) for c in df.columns)
    has_company = any("기업" in str(c) for c in df.columns)
    
    if not (has_gbc or has_company) and len(df) > 0:
        df = excel_file.parse(target_sheet, header=1)
    
    return {"df": df, "sheet_name": target_sheet}


def normalize_company_name(name: str) -> str:
    """Normalize company name by stripping (주), 주식회사, ㈜, (株), spaces, special chars, lowercasing."""
    if not name:
        return ""
    cleaned = re.sub(r"\([^)]*\)|㈜|주식회사|株|\s+|[^\w가-힣]|_", "", str(name))
    return cleaned.lower()


def generate_unique_company_code(db: Session, existing_codes_set: Optional[set] = None) -> str:
    """Generate a unique company code C2026_XX."""
    if existing_codes_set is None:
        existing_codes_set = set(c[0] for c in db.query(Company.company_code).all() if c[0])
    
    seq = 1
    while True:
        code = f"C2026_{seq:02d}"
        if code not in existing_codes_set:
            existing_codes_set.add(code)
            return code
        seq += 1


def process_agreement_excel(df: pd.DataFrame, db: Session) -> Dict[str, Any]:
    """
    Type 1: Process Agreement Date Registration Excel (기업별 협약 마감일 엑셀).
    Headers: GBC, 번호, 사업자번호, 기업명(국문), 기업명(영문), 협약년도, 상태, 마케팅시작년도, 기간 / 협약기간
    Extracts: GBC, 기업명(국문), 사업자번호, 협약기간 -> agreement_end_date, deadline_date.
    Normalizes company names & computes MAX agreement_end_date across multi-agreement extensions.
    """
    col_map = {}
    for col in df.columns:
        c_clean = str(col).strip().replace(" ", "").replace("\n", "")
        if c_clean in ["GBC", "지소", "지소명"]:
            col_map[col] = "GBC"
        elif "국문" in c_clean or c_clean in ["기업명(국문)", "기업명", "기업"]:
            col_map[col] = "기업명"
        elif "영문" in c_clean or c_clean == "기업명(영문)":
            col_map[col] = "기업명영문"
        elif "사업자" in c_clean or "사업자번호" in c_clean:
            col_map[col] = "사업자번호"
        elif "협약기간" in c_clean or c_clean == "기간":
            col_map[col] = "협약기간"
        elif "년도" in c_clean:
            col_map[col] = "협약년도"
        elif "진행상태" in c_clean or c_clean == "상태":
            col_map[col] = "진행상태"

    df = df.rename(columns=col_map)
    
    required_cols = ["GBC", "기업명"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        return {
            "success": False,
            "message": f"협약 마감일 엑셀에 필수 헤더가 누락되었습니다: {', '.join(missing_cols)}. (GBC, 기업명 필수)",
            "inserted": 0, "updated": 0, "errors": []
        }

    branches = db.query(Branch).all()
    branch_lookup = {b.branch_name: b.id for b in branches}
    existing_codes = set(c[0] for c in db.query(Company.company_code).all() if c[0])
    
    inserted_count = 0
    updated_count = 0
    errors = []
    batch_map = {}  # (b_name, norm_key) -> Company

    for idx, row in df.iterrows():
        row_num = idx + 2
        
        b_raw = str(row.get("GBC", "")).strip() if not pd.isna(row.get("GBC")) else ""
        c_name = str(row.get("기업명", "")).strip() if not pd.isna(row.get("기업명")) else ""
        c_name_en = str(row.get("기업명영문", "")).strip() if "기업명영문" in df.columns and not pd.isna(row.get("기업명영문")) else None
        biz_no = str(row.get("사업자번호", "")).strip() if "사업자번호" in df.columns and not pd.isna(row.get("사업자번호")) else None
        period_val = row.get("협약기간")

        if not b_raw:
            errors.append({"row": row_num, "error": "GBC(지소명)가 비어 있습니다."})
            continue
        if not c_name:
            errors.append({"row": row_num, "error": "기업명이 비어 있습니다."})
            continue

        b_name = ALIAS_TO_ENGLISH_BRANCH.get(b_raw.lower(), ALIAS_TO_ENGLISH_BRANCH.get(b_raw, b_raw))
        if b_name not in branch_lookup:
            errors.append({"row": row_num, "error": f"존재하지 않는 GBC(지소명)입니다: '{b_raw}'"})
            continue

        end_date_str = extract_end_date_from_period(period_val)
        deadline_date_str = calculate_deadline(end_date_str)
        status = str(row.get("진행상태", "진행중")).strip() if "진행상태" in df.columns and not pd.isna(row.get("진행상태")) else "진행중"
        norm_key = normalize_company_name(c_name)

        # Multi-agreement extension consolidation check within batch
        if (b_name, norm_key) in batch_map:
            comp = batch_map[(b_name, norm_key)]
            if end_date_str > comp.agreement_end_date:
                comp.agreement_end_date = end_date_str
                comp.deadline_date = calculate_deadline(end_date_str)
            updated_count += 1
            continue

        # Upsert Company by matching branch_name and normalized_company_name
        existing = db.query(Company).filter(
            Company.branch_name == b_name,
            ((Company.normalized_company_name == norm_key) | (Company.company_name == c_name))
        ).first()

        if existing:
            if not existing.normalized_company_name:
                existing.normalized_company_name = norm_key
            if end_date_str > existing.agreement_end_date:
                existing.agreement_end_date = end_date_str
                existing.deadline_date = calculate_deadline(end_date_str)
            existing.status = status
            if biz_no:
                existing.business_reg_no = biz_no
            if c_name_en:
                existing.company_name_en = c_name_en
            existing.updated_at = datetime.datetime.utcnow()
            batch_map[(b_name, norm_key)] = existing
            updated_count += 1
        else:
            code_str = generate_unique_company_code(db, existing_codes)
            new_comp = Company(
                company_code=code_str,
                branch_id=branch_lookup[b_name],
                branch_name=b_name,
                company_name=c_name,
                normalized_company_name=norm_key,
                company_name_en=c_name_en,
                business_reg_no=biz_no,
                agreement_end_date=end_date_str,
                deadline_date=deadline_date_str,
                status=status
            )
            db.add(new_comp)
            db.flush()
            batch_map[(b_name, norm_key)] = new_comp
            inserted_count += 1

    db.commit()
    return {
        "success": True,
        "type": "협약마감일 등록 엑셀",
        "message": f"협약 기업 등록 완료: 신규 {inserted_count}건, 업데이트 {updated_count}건",
        "inserted": inserted_count,
        "updated": updated_count,
        "errors": errors
    }


def process_activity_excel(df: pd.DataFrame, db: Session) -> Dict[str, Any]:
    """
    Type 2: Process Activity & Final Report Log Excel (파이널 리포트/활동내역 엑셀).
    Headers: 번호, GBC, 기업명, 리포트명, 등록일, 계약 성약 실적금액(USD), 활동내역, 파이널여부, 발송여부
    Maps multiple reports to parent Company (1:N) without inflating company count.
    """
    col_map = {}
    for col in df.columns:
        c_clean = str(col).strip().replace(" ", "").replace("\n", "")
        if c_clean in ["GBC", "지소", "지소명"]:
            col_map[col] = "GBC"
        elif "기업명" in c_clean or c_clean == "기업":
            col_map[col] = "기업명"
        elif "리포트명" in c_clean or "제목" in c_clean:
            col_map[col] = "리포트명"
        elif "등록일" in c_clean:
            col_map[col] = "등록일"
        elif "협약" in c_clean or "마감일" in c_clean:
            col_map[col] = "협약마감일"
        elif "실적금액" in c_clean:
            col_map[col] = "계약성약실적금액"
        elif "진행상태" in c_clean or c_clean == "상태":
            col_map[col] = "진행상태"
        elif "활동내역" in c_clean or "리포트내용" in c_clean:
            col_map[col] = "활동내역"
        elif "파이널여부" in c_clean or "리포트업로드" in c_clean or c_clean == "업로드":
            col_map[col] = "파이널여부"
        elif "발송여부" in c_clean or c_clean == "발송":
            col_map[col] = "발송여부"

    df = df.rename(columns=col_map)
    
    required_cols = ["GBC", "기업명"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        return {
            "success": False,
            "message": f"활동내역 엑셀에 필수 헤더가 누락되었습니다: {', '.join(missing_cols)}. (GBC, 기업명 필수)",
            "inserted": 0, "updated": 0, "errors": []
        }

    branches = db.query(Branch).all()
    branch_lookup = {b.branch_name: b.id for b in branches}
    existing_codes = set(c[0] for c in db.query(Company.company_code).all() if c[0])
    
    reports_added = 0
    companies_created = 0
    errors = []

    for idx, row in df.iterrows():
        row_num = idx + 2
        
        b_raw = str(row.get("GBC", "")).strip() if not pd.isna(row.get("GBC")) else ""
        c_name = str(row.get("기업명", "")).strip() if not pd.isna(row.get("기업명")) else ""
        raw_reg_date = row.get("등록일")

        if not b_raw:
            errors.append({"row": row_num, "error": "GBC(지소명)가 비어 있습니다."})
            continue
        if not c_name:
            errors.append({"row": row_num, "error": "기업명이 비어 있습니다."})
            continue

        b_name = ALIAS_TO_ENGLISH_BRANCH.get(b_raw.lower(), ALIAS_TO_ENGLISH_BRANCH.get(b_raw, b_raw))
        if b_name not in branch_lookup:
            errors.append({"row": row_num, "error": f"존재하지 않는 GBC(지소명)입니다: '{b_raw}'"})
            continue

        # Parse registered date
        registered_date_str = None
        if not pd.isna(raw_reg_date) and str(raw_reg_date).strip():
            try:
                registered_date_str = parse_date_string(raw_reg_date)
            except Exception:
                registered_date_str = datetime.date.today().strftime("%Y-%m-%d")
        else:
            registered_date_str = datetime.date.today().strftime("%Y-%m-%d")

        # Parse agreement end date if present
        raw_end_date = row.get("협약마감일")
        agreement_end_date_str = None
        if not pd.isna(raw_end_date) and str(raw_end_date).strip():
            try:
                agreement_end_date_str = parse_date_string(raw_end_date)
            except Exception as e:
                errors.append({"row": row_num, "error": str(e)})
                continue

        status = str(row.get("진행상태", "진행중")).strip() if "진행상태" in df.columns and not pd.isna(row.get("진행상태")) else "진행중"
        
        raw_amount = row.get("계약성약실적금액", 0.0)
        try:
            if pd.isna(raw_amount) or raw_amount is None:
                contract_usd = 0.0
            else:
                contract_usd = float(re.sub(r"[^\d.]", "", str(raw_amount)))
        except Exception:
            contract_usd = 0.0

        activity_text = str(row.get("활동내역", "")).strip() if "활동내역" in df.columns and not pd.isna(row.get("활동내역")) else ""
        report_title = str(row.get("리포트명", "")).strip() if "리포트명" in df.columns and not pd.isna(row.get("리포트명")) else f"{c_name} 활동 보고서"

        # Check for final report keyword in activity_text or title
        has_final_keyword = False
        text_to_check = (activity_text + " " + report_title).lower()
        if "final report" in text_to_check or "파이널 리포트" in text_to_check or "파이널리포트" in text_to_check:
            has_final_keyword = True

        is_final = has_final_keyword or parse_bool_val(row.get("파이널여부", False))
        is_sent = parse_bool_val(row.get("발송여부", False)) or (status in ["완료", "발송", "발송완료"])

        # Find or create parent Company using normalized_company_name
        norm_key = normalize_company_name(c_name)
        company = db.query(Company).filter(
            Company.branch_name == b_name,
            ((Company.normalized_company_name == norm_key) | (Company.company_name == c_name))
        ).first()

        if not company:
            code_str = generate_unique_company_code(db, existing_codes)
            final_end = agreement_end_date_str or (datetime.date.today() + datetime.timedelta(days=365)).strftime("%Y-%m-%d")
            company = Company(
                company_code=code_str,
                branch_id=branch_lookup[b_name],
                branch_name=b_name,
                company_name=c_name,
                normalized_company_name=norm_key,
                agreement_end_date=final_end,
                deadline_date=calculate_deadline(final_end),
                status=status
            )
            db.add(company)
            db.flush()
            companies_created += 1
        elif agreement_end_date_str and agreement_end_date_str > company.agreement_end_date:
            company.agreement_end_date = agreement_end_date_str
            company.deadline_date = calculate_deadline(agreement_end_date_str)
            company.agreement_end_date = agreement_end_date_str
            company.deadline_date = calculate_deadline(agreement_end_date_str)

        # Insert new CompanyReport child
        rep = CompanyReport(
            company_id=company.id,
            report_title=report_title,
            registered_date=registered_date_str,
            is_final=is_final,
            is_sent=is_sent,
            contract_amount_usd=contract_usd,
            report_content=activity_text or None
        )
        db.add(rep)
        reports_added += 1

    db.commit()
    return {
        "success": True,
        "type": "활동내역/파이널리포트 엑셀",
        "message": f"리포트 매핑 완료: 총 {reports_added}개 리포트 추가 (신규 기업 생성 {companies_created}건)",
        "inserted": reports_added,
        "updated": companies_created,
        "errors": errors
    }


def process_file_upload(file_contents: bytes, filename: str, db: Session, file_type: str = "auto") -> Dict[str, Any]:
    """Master file upload handler."""
    try:
        parsed_data = read_excel_dataframe(file_contents, filename)
        df = parsed_data["df"]
    except Exception as e:
        return {
            "success": False,
            "message": f"파일 읽기 오류: {str(e)}. CSV 또는 표준 .xlsx/.xls 파일인지 확인하세요.",
            "inserted": 0, "updated": 0, "errors": []
        }

    cols_joined = " ".join([str(c) for c in df.columns]).replace(" ", "").replace("\n", "")
    is_agreement_file = ("사업자" in cols_joined or "협약기간" in cols_joined or "협약년도" in cols_joined)
    
    if file_type == "agreement" or (file_type == "auto" and is_agreement_file):
        return process_agreement_excel(df, db)
    else:
        return process_activity_excel(df, db)


def upsert_single_project(data: Dict[str, Any], db: Session) -> Company:
    """Manual single company creation/update."""
    b_raw = data.get("branch_name", "").strip()
    b_name = ALIAS_TO_ENGLISH_BRANCH.get(b_raw.lower(), ALIAS_TO_ENGLISH_BRANCH.get(b_raw, b_raw))
    
    branch = db.query(Branch).filter(Branch.branch_name == b_name).first()
    if not branch:
        raise ValueError(f"존재하지 않는 지소명입니다: '{b_raw}'")

    c_name = data.get("company_name", "").strip()
    if not c_name:
        raise ValueError("기업명은 필수입니다.")

    end_date = data.get("agreement_end_date") or datetime.date.today().strftime("%Y-%m-%d")
    deadline_date = calculate_deadline(end_date)

    norm_key = normalize_company_name(c_name)
    existing = db.query(Company).filter(
        Company.branch_name == b_name,
        ((Company.normalized_company_name == norm_key) | (Company.company_name == c_name))
    ).first()

    act_content = data.get("report_content", "")
    has_final_kw = False
    if act_content:
        act_lower = act_content.lower()
        if "final report" in act_lower or "파이널 리포트" in act_lower or "파이널리포트" in act_lower:
            has_final_kw = True

    is_final = parse_bool_val(data.get("report_uploaded", False)) or has_final_kw
    is_sent = parse_bool_val(data.get("report_sent", False))

    if existing:
        existing.agreement_end_date = end_date
        existing.deadline_date = deadline_date
        existing.status = data.get("status", existing.status)
        existing.updated_at = datetime.datetime.utcnow()
        
        # Add report if content or title provided
        if act_content or data.get("report_title"):
            rep = CompanyReport(
                company_id=existing.id,
                report_title=data.get("report_title", f"{c_name} 수동 입력 리포트"),
                registered_date=data.get("registered_date", datetime.date.today().strftime("%Y-%m-%d")),
                is_final=is_final,
                is_sent=is_sent,
                contract_amount_usd=float(data.get("contract_amount_usd", 0.0)),
                report_content=act_content or None
            )
            db.add(rep)
        db.commit()
        db.refresh(existing)
        return existing
    else:
        code_str = generate_unique_company_code(db)
        new_comp = Company(
            company_code=code_str,
            branch_id=branch.id,
            branch_name=b_name,
            company_name=c_name,
            business_reg_no=data.get("business_reg_no"),
            agreement_end_date=end_date,
            deadline_date=deadline_date,
            status=data.get("status", "진행중")
        )
        db.add(new_comp)
        db.flush()

        if act_content or data.get("report_title"):
            rep = CompanyReport(
                company_id=new_comp.id,
                report_title=data.get("report_title", f"{c_name} 파이널 리포트"),
                registered_date=data.get("registered_date", datetime.date.today().strftime("%Y-%m-%d")),
                is_final=is_final,
                is_sent=is_sent,
                contract_amount_usd=float(data.get("contract_amount_usd", 0.0)),
                report_content=act_content or None
            )
            db.add(rep)

        db.commit()
        db.refresh(new_comp)
        return new_comp
