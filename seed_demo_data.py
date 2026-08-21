import datetime
from app.database import SessionLocal, engine, Base
from app.models import Branch, Company, CompanyReport, BRANCH_SEED_DATA
from app.services.data_sync import calculate_deadline, normalize_company_name

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

DEMO_COMPANIES = [
    # (CompanyCode, BranchName, CompanyName, BusinessRegNo, StartDate, EndDate, Status, ReportsList)
    ("C2026_01", "Shanghai", "A전자", "123-81-00001", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Shanghai 가전 현지 매장 진출 보고서", "regDate": "2026-08-10", "isFinal": False, "isSent": True, "amount": 10000.0, "content": "1차 시장 조사 보고서."},
        {"title": "Shanghai 전자 파이널 리포트", "regDate": "2026-08-25", "isFinal": True, "isSent": True, "amount": 25000.0, "content": "Final Report - 2026-08-31 작성된 Shanghai 가전 현지 매장 진출 보고서."}
    ]),
    ("C2026_02", "Shanghai", "B바이오", "123-81-00002", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Shanghai 바이오 제약 전시회 보고서", "regDate": "2026-08-15", "isFinal": True, "isSent": False, "amount": 18000.0, "content": "Final Report - 2026-08-31 바이오 제약 Shanghai 파트너링 결과."}
    ]),
    ("C2026_03", "Shenyang", "C식품", "123-81-00003", "2025-09-15", "2026-09-14", "진행중", [
        {"title": "Shenyang 식품 바이어 상담 보고서", "regDate": "2026-09-01", "isFinal": True, "isSent": False, "amount": 12000.0, "content": "Final Report (작성일: 2026-09-01) Shenyang 및 동북3성 식품 수출 조사."}
    ]),
    ("C2026_04", "Guangzhou", "D무역", "123-81-00004", "2025-09-01", "2026-08-31", "진행중", []),
    ("C2026_05", "Chongqing", "E모빌리티", "123-81-00005", "2025-10-01", "2026-09-30", "진행중", [
        {"title": "Chongqing 자동차 부품 파이널 리포트", "regDate": "2026-09-20", "isFinal": True, "isSent": True, "amount": 35000.0, "content": "Final Report - 2026-09-30 자동차 부품 수출 지원."}
    ]),
    ("C2026_06", "Tokyo", "F소프트", "123-81-00006", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Tokyo IT 유통망 파이널 보고서", "regDate": "2026-08-20", "isFinal": True, "isSent": True, "amount": 20000.0, "content": "Final Report - 2026-08-31 Tokyo 현지 소프트웨어 유통망 분석."}
    ]),
    ("C2026_07", "Tokyo", "G콘텐츠", "123-81-00007", "2025-08-15", "2026-08-15", "진행중", []), # Overdue
    ("C2026_08", "Taipei", "H반도체", "123-81-00008", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Taipei 반도체 테스트 리포트", "regDate": "2026-08-18", "isFinal": True, "isSent": False, "amount": 15000.0, "content": "Final Report 2026-08-31 Taipei 반도체 관련 리포트."}
    ]),
    ("C2026_09", "Kuala Lumpur", "I케미칼", "123-81-00009", "2025-09-15", "2026-09-15", "진행중", [
        {"title": "KL 석유화학 시장 파이널 리포트", "regDate": "2026-09-10", "isFinal": True, "isSent": True, "amount": 28000.0, "content": "Final Report - 2026-09-15 KL 석유화학 시장 파이널 리포트."}
    ]),
    ("C2026_10", "Ho Chi Minh", "J패션", "123-81-00010", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Ho Chi Minh 패션 시장 리포트", "regDate": "2026-08-20", "isFinal": True, "isSent": False, "amount": 9000.0, "content": "Final Report (2026-08-20) Ho Chi Minh 패션 시장 리포트."}
    ]),
    ("C2026_11", "Hanoi", "K건설", "123-81-00011", "2025-10-15", "2026-10-15", "진행중", []),
    ("C2026_12", "Bangkok", "L뷰티", "123-81-00012", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Bangkok K-뷰티 수출 보고서", "regDate": "2026-08-22", "isFinal": True, "isSent": True, "amount": 16000.0, "content": "Final Report - 2026-08-31 Bangkok K-뷰티 수출 보고서."}
    ]),
    ("C2026_13", "Jakarta", "M에너지", "123-81-00013", "2025-10-01", "2026-09-30", "진행중", [
        {"title": "Jakarta 재생에너지 파이널 리포트", "regDate": "2026-09-15", "isFinal": True, "isSent": False, "amount": 42000.0, "content": "Final Report - 2026-09-30 Jakarta 에너지 시장 파이널 리포트."}
    ]),
    ("C2026_14", "Manila", "N물류", "123-81-00014", "2025-09-01", "2026-08-31", "진행중", []),
    ("C2026_15", "Sydney", "O헬스케어", "123-81-00015", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Sydney 의료기기 인증 파이널 리포트", "regDate": "2026-08-25", "isFinal": True, "isSent": True, "amount": 22000.0, "content": "Final Report - 2026-08-31 Sydney 의료기기 인증 파이널 리포트."}
    ]),
    ("C2026_16", "Mumbai", "P엔지니어링", "123-81-00016", "2025-09-15", "2026-09-15", "진행중", [
        {"title": "Mumbai 현지 법인 타당성 보고서", "regDate": "2026-09-05", "isFinal": True, "isSent": False, "amount": 19000.0, "content": "Final Report 2026-09-15 Mumbai 현지 법인 타당성 보고서."}
    ]),
    ("C2026_17", "Bengaluru", "Q테크", "123-81-00017", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Bengaluru 개발센터 설립 리포트", "regDate": "2026-08-28", "isFinal": True, "isSent": True, "amount": 31000.0, "content": "Final Report - 2026-08-31 Bengaluru 개발센터 설립 리포트."}
    ]),
    ("C2026_18", "Nairobi", "R농업", "123-81-00018", "2025-10-01", "2026-09-30", "진행중", []),
    ("C2026_19", "Istanbul", "S기계", "123-81-00019", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Istanbul 기계 수출 파이널 리포트", "regDate": "2026-08-20", "isFinal": True, "isSent": False, "amount": 14000.0, "content": "Final Report - 2026-08-31 Istanbul 기계 수출 파이널 리포트."}
    ]),
    ("C2026_20", "Dubai", "T스마트시티", "123-81-00020", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Dubai 스마트시티 프로젝트 리포트", "regDate": "2026-08-24", "isFinal": True, "isSent": True, "amount": 55000.0, "content": "Final Report - 2026-08-31 Dubai 스마트시티 프로젝트 리포트."}
    ]),
    ("C2026_21", "Moscow", "U소재", "123-81-00021", "2025-08-01", "2026-07-31", "중단", []),
    ("C2026_22", "Tashkent", "V섬유", "123-81-00022", "2025-09-15", "2026-09-15", "진행중", [
        {"title": "Tashkent 섬유 파이널 리포트", "regDate": "2026-09-10", "isFinal": True, "isSent": True, "amount": 17000.0, "content": "Final Report - 2026-09-15 Tashkent 섬유 파이널 리포트."}
    ]),
    ("C2026_23", "L.A", "W미디어", "123-81-00023", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "L.A 헐리우드 미디어 시장 리포트", "regDate": "2026-08-21", "isFinal": True, "isSent": True, "amount": 38000.0, "content": "Final Report - 2026-08-31 L.A 헐리우드 미디어 시장 리포트."}
    ]),
    ("C2026_24", "New York", "X금융", "123-81-00024", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "New York 핀테크 파이널 리포트", "regDate": "2026-08-29", "isFinal": True, "isSent": False, "amount": 45000.0, "content": "Final Report 2026-08-31 New York 핀테크 파이널 리포트."}
    ]),
    ("C2026_25", "Dallas", "Y항공", "123-81-00025", "2025-10-01", "2026-09-30", "진행중", []),
    ("C2026_26", "Vancouver", "Z클린테크", "123-81-00026", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Vancouver 클린테크 리포트", "regDate": "2026-08-18", "isFinal": True, "isSent": True, "amount": 26000.0, "content": "Final Report - 2026-08-31 Vancouver 클린테크 리포트."}
    ]),
    ("C2026_27", "Mexico City", "AA오토", "123-81-00027", "2025-09-15", "2026-09-15", "진행중", [
        {"title": "Mexico City 자동차 부품 파이널 리포트", "regDate": "2026-09-08", "isFinal": True, "isSent": False, "amount": 21000.0, "content": "Final Report - 2026-09-15 Mexico City 자동차 부품 파이널 리포트."}
    ]),
    ("C2026_28", "Santiago", "BB자원", "123-81-00028", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Santiago 자원 파이널 리포트", "regDate": "2026-08-26", "isFinal": True, "isSent": True, "amount": 33000.0, "content": "Final Report - 2026-08-31 Santiago 자원 파이널 리포트."}
    ]),
    ("C2026_29", "Frankfurt", "CC소재", "123-81-00029", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Frankfurt 소재 파이널 리포트", "regDate": "2026-08-27", "isFinal": True, "isSent": True, "amount": 29000.0, "content": "Final Report - 2026-08-31 Frankfurt 소재 파이널 리포트."}
    ]),
    ("C2026_30", "Warsaw", "DD방산", "123-81-00030", "2025-09-01", "2026-08-31", "진행중", [
        {"title": "Warsaw 방산 수출 파이널 리포트", "regDate": "2026-08-25", "isFinal": True, "isSent": False, "amount": 48000.0, "content": "Final Report - 2026-08-31 Warsaw 방산 수출 파이널 리포트."}
    ])
]


def seed_demo_data():
    db = SessionLocal()
    try:
        # Seed branches
        for item in BRANCH_SEED_DATA:
            b = Branch(branch_name=item["branch_name"], country=item["country"], region=item["region"])
            db.add(b)
        db.commit()

        branches = db.query(Branch).all()
        b_map = {b.branch_name: b.id for b in branches}

        # Clear existing companies
        db.query(CompanyReport).delete()
        db.query(Company).delete()
        db.commit()

        for item in DEMO_COMPANIES:
            code, b_name, c_name, reg_no, start_d, end_d, status, reports = item
            if b_name in b_map:
                dl_date = calculate_deadline(end_d)
                comp = Company(
                    company_code=code,
                    branch_id=b_map[b_name],
                    branch_name=b_name,
                    company_name=c_name,
                    normalized_company_name=normalize_company_name(c_name),
                    business_reg_no=reg_no,
                    agreement_start_date=start_d,
                    agreement_end_date=end_d,
                    deadline_date=dl_date,
                    status=status
                )
                db.add(comp)
                db.flush() # get comp.id

                for r in reports:
                    rep = CompanyReport(
                        company_id=comp.id,
                        report_title=r.get("title") or f"{c_name} 리포트",
                        registered_date=r.get("regDate"),
                        is_final=r.get("isFinal", False),
                        is_sent=r.get("isSent", False),
                        contract_amount_usd=r.get("amount", 0.0),
                        report_content=r.get("content")
                    )
                    db.add(rep)

        db.commit()
        print("Demo 1:N companies & reports seeded successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
