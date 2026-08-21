import datetime
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from app.database import Base

BRANCH_SEED_DATA = [
    # 중국 (4)
    {"branch_name": "Shanghai", "country": "China", "region": "아시아"},
    {"branch_name": "Shenyang", "country": "China", "region": "아시아"},
    {"branch_name": "Guangzhou", "country": "China", "region": "아시아"},
    {"branch_name": "Chongqing", "country": "China", "region": "아시아"},
    # 일본 (1)
    {"branch_name": "Tokyo", "country": "Japan", "region": "아시아"},
    # 대만 (1)
    {"branch_name": "Taipei", "country": "Taiwan", "region": "아시아"},
    # 말레이시아 (1)
    {"branch_name": "Kuala Lumpur", "country": "Malaysia", "region": "아시아"},
    # 베트남 (2)
    {"branch_name": "Ho Chi Minh", "country": "Vietnam", "region": "아시아"},
    {"branch_name": "Hanoi", "country": "Vietnam", "region": "아시아"},
    # 태국 (1)
    {"branch_name": "Bangkok", "country": "Thailand", "region": "아시아"},
    # 인도네시아 (1)
    {"branch_name": "Jakarta", "country": "Indonesia", "region": "아시아"},
    # 필리핀 (1)
    {"branch_name": "Manila", "country": "Philippines", "region": "아시아"},
    # 호주 (1)
    {"branch_name": "Sydney", "country": "Australia", "region": "오세아니아"},
    # 인도 (2)
    {"branch_name": "Mumbai", "country": "India", "region": "아시아"},
    {"branch_name": "Bengaluru", "country": "India", "region": "아시아"},
    # 케냐 (1)
    {"branch_name": "Nairobi", "country": "Kenya", "region": "아프리카/중동"},
    # 튀르키예 (1)
    {"branch_name": "Istanbul", "country": "Turkey", "region": "유럽"},
    # UAE (1)
    {"branch_name": "Dubai", "country": "UAE", "region": "아프리카/중동"},
    # 러시아 (1)
    {"branch_name": "Moscow", "country": "Russia", "region": "유럽"},
    # 우즈베키스탄 (1)
    {"branch_name": "Tashkent", "country": "Uzbekistan", "region": "아시아"},
    # 미국 (3)
    {"branch_name": "L.A", "country": "USA", "region": "미주"},
    {"branch_name": "New York", "country": "USA", "region": "미주"},
    {"branch_name": "Dallas", "country": "USA", "region": "미주"},
    # 캐나다 (1)
    {"branch_name": "Vancouver", "country": "Canada", "region": "미주"},
    # 멕시코 (1)
    {"branch_name": "Mexico City", "country": "Mexico", "region": "미주"},
    # 칠레 (1)
    {"branch_name": "Santiago", "country": "Chile", "region": "미주"},
    # 독일 (1)
    {"branch_name": "Frankfurt", "country": "Germany", "region": "유럽"},
    # 폴란드 (1)
    {"branch_name": "Warsaw", "country": "Poland", "region": "유럽"},
]


class Branch(Base):
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, index=True)
    branch_name = Column(String(50), unique=True, nullable=False, index=True)
    country = Column(String(50), nullable=False)
    region = Column(String(50), nullable=False)

    companies = relationship("Company", back_populates="branch_rel", cascade="all, delete-orphan")


class Company(Base):
    """2026 Agreement Company Model (1 in 1:N)"""
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    company_code = Column(String(50), unique=True, nullable=True, index=True)  # e.g. C2026_01
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    branch_name = Column(String(50), nullable=False, index=True)
    company_name = Column(String(100), nullable=False, index=True)            # 기업명(국문)
    normalized_company_name = Column(String(100), nullable=True, index=True) # 정규화된 기업명 (매핑용)
    company_name_en = Column(String(100), nullable=True)                      # 기업명(영문)
    business_reg_no = Column(String(50), nullable=True)                      # 사업자번호
    agreement_year = Column(String(10), default="2026")                        # 협약년도
    agreement_start_date = Column(String(10), nullable=True)                 # YYYY-MM-DD
    agreement_end_date = Column(String(10), nullable=False)                   # YYYY-MM-DD
    deadline_date = Column(String(10), nullable=False)                        # agreement_end_date + 14 days
    status = Column(String(20), default="진행중")                             # 진행중, 완료, 중단 등
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    branch_rel = relationship("Branch", back_populates="companies")
    reports = relationship("CompanyReport", back_populates="company_rel", cascade="all, delete-orphan")


class CompanyReport(Base):
    """Child Report Model linked to Company (N in 1:N)"""
    __tablename__ = "company_reports"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    report_title = Column(String(200), nullable=True)
    registered_date = Column(String(10), nullable=True)                      # 등록일 (YYYY-MM-DD)
    is_final = Column(Boolean, default=False)                                 # 파이널 리포트 여부 (Y/N)
    is_sent = Column(Boolean, default=False)                                  # 발송 여부 (Y/N)
    contract_amount_usd = Column(Float, default=0.0)                          # 계약 성약 실적금액 (USD)
    report_content = Column(Text, nullable=True)                             # 활동내역
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    company_rel = relationship("Company", back_populates="reports")


class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(100), nullable=False)
    branch_name = Column(String(50), nullable=False)
    deadline_date = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False) # SUCCESS, FAILED
    recipient = Column(String(100), nullable=False)
    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=datetime.datetime.utcnow)


class MonthlyAggregate(Base):
    __tablename__ = "monthly_aggregates"

    id = Column(Integer, primary_key=True, index=True)
    year_month = Column(String(7), nullable=False, index=True) # YYYY-MM
    branch_id = Column(Integer, nullable=False)
    branch_name = Column(String(50), nullable=False)
    total_companies = Column(Integer, default=0)
    reports_uploaded = Column(Integer, default=0)
    reports_sent = Column(Integer, default=0)
    sent_rate = Column(Float, default=0.0)
    aggregated_at = Column(DateTime, default=datetime.datetime.utcnow)
