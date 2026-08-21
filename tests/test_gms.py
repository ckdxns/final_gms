import os
import datetime
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Branch, Company, CompanyReport, EmailLog, MonthlyAggregate, BRANCH_SEED_DATA
from app.main import app
from app.services.data_sync import process_file_upload, upsert_single_project, calculate_deadline, normalize_company_name
from app.services.scheduler_mail import check_and_send_deadline_reminders
from app.services.eom_aggregator import run_monthly_aggregation
from app.services.quality_engine import inspect_report_quality

SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


class GMSTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        db = TestingSessionLocal()
        for item in BRANCH_SEED_DATA:
            b = Branch(
                branch_name=item["branch_name"],
                country=item["country"],
                region=item["region"]
            )
            db.add(b)
        db.commit()
        db.close()
        cls.client = TestClient(app)

    def setUp(self):
        self.db = TestingSessionLocal()

    def tearDown(self):
        self.db.query(CompanyReport).delete()
        self.db.query(Company).delete()
        self.db.query(EmailLog).delete()
        self.db.query(MonthlyAggregate).delete()
        self.db.commit()
        self.db.close()

    def test_01_db_seeding_branches(self):
        """1. DB 초기화: 28개 지소, 21개국 정보가 매핑되었는지 검증"""
        branches = self.db.query(Branch).all()
        self.assertEqual(len(branches), 28, "지소 개수는 정확히 28개여야 합니다.")
        
        countries = set(b.country for b in branches)
        self.assertEqual(len(countries), 21, "국가 개수는 정확히 21개국이어야 합니다.")
        
        branch_names = [b.branch_name for b in branches]
        self.assertIn("Shanghai", branch_names)
        self.assertIn("Tokyo", branch_names)
        self.assertIn("Frankfurt", branch_names)

    def test_02_dual_excel_upload_and_1ton_mapping(self):
        """2. 2원화 엑셀 업로드 및 1:N 관계형 매핑 (기업 수 뻥튀기 방지) 검증"""
        # Upload Agreement Excel (Type 1)
        csv_agreement = (
            "GBC,기업명,사업자번호,협약기간\n"
            "Tokyo,A상사,123-45-67890,2025.09.01 ~ 2026.08.31\n"
        ).encode("utf-8")

        res1 = process_file_upload(csv_agreement, "agreement.csv", self.db, file_type="agreement")
        self.assertTrue(res1["success"])

        comp_a = self.db.query(Company).filter(Company.company_name == "A상사").first()
        self.assertIsNotNone(comp_a)
        self.assertEqual(comp_a.agreement_end_date, "2026-08-31")
        self.assertEqual(comp_a.deadline_date, "2026-09-14")

        # Upload Report Log Excel with 2 reports for 'A상사' (Type 2)
        csv_activity = (
            "GBC,기업명,등록일,계약성약실적금액,활동내역\n"
            "Tokyo,A상사,2026-08-10,10000,1차 상담 진행\n"
            "Tokyo,A상사,2026-08-25,25000,Final Report - 도쿄 시장 파이널 리포트\n"
        ).encode("utf-8")

        res2 = process_file_upload(csv_activity, "activity.csv", self.db, file_type="activity")
        self.assertTrue(res2["success"])

        # Company count must NOT inflate (remains 1)
        total_companies = self.db.query(Company).count()
        self.assertEqual(total_companies, 1, "기업 수가 뻥튀기되지 않고 1개로 유지되어야 합니다.")

        # Reports count for A상사 must be 2
        reports = comp_a.reports
        self.assertEqual(len(reports), 2, "A상사의 하위 리포트는 2개여야 합니다.")
        self.assertTrue(any(r.is_final for r in reports))

    def test_03_reset_all_data_api(self):
        """3. Reset API 테스트: DELETE /api/reset 실행 시 기업/리포트는 삭제되고 28개 지소는 유지됨"""
        comp = Company(branch_id=1, branch_name="Tokyo", company_name="테스트기업", agreement_end_date="2026-08-31", deadline_date="2026-09-14")
        self.db.add(comp)
        self.db.commit()

        rep = CompanyReport(company_id=comp.id, report_title="테스트리포트")
        self.db.add(rep)
        self.db.commit()

        # Call Reset API via TestClient
        res = self.client.delete("/api/reset")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

        # Verify DB states
        self.assertEqual(self.db.query(Company).count(), 0)
        self.assertEqual(self.db.query(CompanyReport).count(), 0)
        self.assertEqual(self.db.query(Branch).count(), 28, "28개 지소는 안전하게 유지되어야 합니다.")

    def test_04_dynamic_deadline_reminder_scheduler(self):
        """4. 데드라인 알림 스케줄러: 협약 마감일 + 14일 로직 및 자동 메일 전송 검증"""
        comp = Company(
            branch_id=1,
            branch_name="Tokyo",
            company_name="A상사",
            agreement_end_date="2026-08-31",
            deadline_date="2026-09-14"
        )
        self.db.add(comp)
        self.db.commit()

        res = check_and_send_deadline_reminders(
            self.db,
            recipient_email="test@gms-global.org",
            today_override="2026-09-14",
            simulate_fail=False
        )

        self.assertTrue(res["success"])
        self.assertTrue(res["email_sent"])
        self.assertEqual(res["unsent_count"], 1)

    def test_05_quality_inspection_engine(self):
        """5. 품질 검증 엔진: 텍스트 유사도 중복 및 조건부 부실 감지 검증"""
        comp = Company(branch_id=1, branch_name="Shanghai", company_name="기존기업", agreement_end_date="2026-08-31", deadline_date="2026-09-14")
        self.db.add(comp)
        self.db.commit()

        rep = CompanyReport(
            company_id=comp.id,
            report_title="Shanghai 시장 보고서",
            report_content="Final Report - 2026-08-31 Shanghai 현지 비즈니스 및 시장 현황 리포트입니다."
        )
        self.db.add(rep)
        self.db.commit()

        # Valid Report on/after agreement end date
        good_text = "Final Report - 2026-09-01 작성된 신규 사업 진출 프로젝트 결과 보고서입니다."
        res_good = inspect_report_quality(good_text, db=self.db, agreement_end_date="2026-08-31", today_override="2026-08-31")
        self.assertTrue(res_good["passed"])
        self.assertEqual(res_good["overall_score"], 100)

        # Missing Date on/after agreement end date -> Warning
        no_date_text = "Final Report - 날짜가 없는 파이널 리포트 본문 내용입니다."
        res_no_date = inspect_report_quality(no_date_text, db=self.db, agreement_end_date="2026-08-31", today_override="2026-08-31")
        self.assertFalse(res_no_date["passed"])

        # Missing Date BEFORE agreement end date -> Warning Suppressed
        res_before_expire = inspect_report_quality(no_date_text, db=self.db, agreement_end_date="2027-04-30", today_override="2026-08-31")
        self.assertTrue(res_before_expire["passed"], "마감일 이전에는 날짜 미표기 부실 경고가 유예되어야 합니다.")

    def test_06_company_normalization_and_multi_agreement_extension(self):
        """6. 기업명 정규화 및 다중 협약(연장/갱신) 최신 마감일 자동 통합 검증"""
        self.assertEqual(normalize_company_name("(주) 누베파마"), "누베파마")
        self.assertEqual(normalize_company_name("주식회사 누베-파마"), "누베파마")
        self.assertEqual(normalize_company_name("㈜ 누베_파마"), "누베파마")

        # Agreement CSV with 2 rows for same company (extension)
        csv_multi = (
            "GBC,기업명,사업자번호,협약기간\n"
            "Shanghai,주식회사 누베파마,111-22-33333,2025.04.13 ~ 2026.04.12\n"
            "Shanghai,누베파마,111-22-33333,2026.05.01 ~ 2027.04.30\n"
        ).encode("utf-8")

        res = process_file_upload(csv_multi, "agreement.csv", self.db, file_type="agreement")
        self.assertTrue(res["success"])

        # Verify only 1 company created
        self.assertEqual(self.db.query(Company).count(), 1, "동일 기업 연장 건은 1개의 기업으로 통합되어야 합니다.")

        comp = self.db.query(Company).first()
        self.assertEqual(comp.normalized_company_name, "누베파마")
        self.assertEqual(comp.agreement_end_date, "2027-04-30", "가장 나중의 마감일(2027-04-30)이 적용되어야 합니다.")
        self.assertEqual(comp.deadline_date, "2027-05-14", "데드라인은 최종 마감일 + 14일(2027-05-14)이어야 합니다.")

    def test_07_korean_english_branch_alias_mapping(self):
        """7. 지소명 한/영 통합 매핑 테이블 검증 ('상하이'='Shanghai', '도쿄'='Tokyo')"""
        csv_alias = (
            "GBC,기업명,사업자번호,협약기간\n"
            "상하이,상하이기업,100-01-00001,2025.01.01 ~ 2026.12.31\n"
            "Shanghai,상하이기업2,100-01-00002,2025.01.01 ~ 2026.12.31\n"
            "도쿄,도쿄기업,200-02-00001,2025.01.01 ~ 2026.12.31\n"
            "Tokyo,도쿄기업2,200-02-00002,2025.01.01 ~ 2026.12.31\n"
        ).encode("utf-8")

        res = process_file_upload(csv_alias, "agreement.csv", self.db, file_type="agreement")
        self.assertTrue(res["success"])

        # Check all mapped to Shanghai or Tokyo branches
        shanghai_branch = self.db.query(Branch).filter(Branch.branch_name == "Shanghai").first()
        tokyo_branch = self.db.query(Branch).filter(Branch.branch_name == "Tokyo").first()

        shanghai_comps = self.db.query(Company).filter(Company.branch_id == shanghai_branch.id).all()
        tokyo_comps = self.db.query(Company).filter(Company.branch_id == tokyo_branch.id).all()

        self.assertEqual(len(shanghai_comps), 2, "'상하이'와 'Shanghai'로 입력된 데이터는 동일한 Shanghai 지소로 통합 매핑되어야 합니다.")
        self.assertEqual(len(tokyo_comps), 2, "'도쿄'와 'Tokyo'로 입력된 데이터는 동일한 Tokyo 지소로 통합 매핑되어야 합니다.")


if __name__ == "__main__":
    unittest.main()
