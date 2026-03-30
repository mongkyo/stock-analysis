"""
[tests/test_cache.py] _find_cache_dates() 단위 테스트
─────────────────────────────────────────────────────
SQLite 인메모리 DB로 DB 의존 로직 검증:
- 정상 날짜 탐색 (start < end)
- 데이터 없을 때 (None, None) 반환
- start ≥ end 인 경우 (None, None) 반환
- min_stocks 기준 미달 날짜 건너뜀
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import Base
from api.models.stock import StockPrice
from api.services.analysis_service import _find_cache_dates


# ── 테스트 전용 DB ────────────────────────────────────────
@pytest.fixture(scope="module")
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # 테스트 데이터 삽입
    # 날짜 "20260101": 종목 3개 (min_stocks=2 이상)
    # 날짜 "20260115": 종목 3개
    # 날짜 "20260120": 종목 1개 (min_stocks=2 미만)
    for date, count in [("20260101", 3), ("20260115", 3), ("20260120", 1)]:
        for i in range(count):
            session.add(StockPrice(
                code=f"00000{i}",
                name=f"종목{i}",
                date=date,
                close_price=1000 + i * 100,
            ))
    session.commit()

    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


# ── 정상 케이스 ───────────────────────────────────────────
class TestFindCacheDatesNormal:
    def test_exact_dates_found(self, db_session):
        """start/end 날짜가 DB에 있으면 그대로 반환"""
        s, e = _find_cache_dates(db_session, "20260101", "20260115", min_stocks=2)
        assert s == "20260101"
        assert e == "20260115"

    def test_returns_latest_date_before_start(self, db_session):
        """요청 날짜보다 이전 거래일로 자동 조정"""
        # "20260105"는 DB에 없음 → "20260101"로 조정
        s, e = _find_cache_dates(db_session, "20260105", "20260115", min_stocks=2)
        assert s == "20260101"
        assert e == "20260115"

    def test_returns_latest_date_before_end(self, db_session):
        """end 날짜가 DB에 없으면 이전 거래일로 조정"""
        # "20260116"은 DB에 없음 → "20260115"로 조정
        s, e = _find_cache_dates(db_session, "20260101", "20260116", min_stocks=2)
        assert s == "20260101"
        assert e == "20260115"


# ── 예외 케이스 ───────────────────────────────────────────
class TestFindCacheDatesEdge:
    def test_no_data_returns_none(self, db_session):
        """DB에 데이터가 없는 기간 → (None, None)"""
        s, e = _find_cache_dates(db_session, "20250101", "20250115", min_stocks=2)
        assert s is None
        assert e is None

    def test_min_stocks_filter(self, db_session):
        """min_stocks 기준 미달 날짜는 건너뜀"""
        # "20260120"은 종목 1개뿐 → min_stocks=2 이상인 "20260115"로 조정
        s, e = _find_cache_dates(db_session, "20260101", "20260120", min_stocks=2)
        assert e == "20260115"

    def test_start_equals_end_returns_none(self, db_session):
        """start == end 이면 s < e 조건 불만족 → (None, None)"""
        s, e = _find_cache_dates(db_session, "20260101", "20260101", min_stocks=2)
        assert s is None
        assert e is None

    def test_start_after_end_returns_none(self, db_session):
        """start > end 이면 (None, None)"""
        s, e = _find_cache_dates(db_session, "20260115", "20260101", min_stocks=2)
        assert s is None
        assert e is None

    def test_empty_db_returns_none(self):
        """빈 DB → (None, None)"""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        session = sessionmaker(bind=engine)()
        s, e = _find_cache_dates(session, "20260101", "20260115", min_stocks=2)
        assert s is None and e is None
        session.close()
