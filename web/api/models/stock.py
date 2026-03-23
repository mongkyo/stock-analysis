"""
[web/api/models/stock.py] 주식 관련 DB 모델
──────────────────────────────────────────────────────
역할:
  StockPrice      — 종목별 날짜별 종가 (원본 데이터 — 분석 결과와 분리)
  AnalysisResult  — Top100 분석 결과 (기간별, 가격은 StockPrice 참조)
  WatchlistItem   — 사용자별 관심종목
  GoldenCrossLog  — 골든크로스 신호 이력

설계 원칙:
  - StockPrice: 한번 저장하면 재사용. 다른 기간 분석 시 API 재호출 없이 활용
  - AnalysisResult: 순위·수익률·재무지표만 저장 (가격은 StockPrice에서 조회)

수정 이력:
  2026-03-19  최초 작성
  2026-03-23  StockPrice 테이블 추가, AnalysisResult 가격 컬럼 제거
──────────────────────────────────────────────────────
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from api.database import Base


class StockPrice(Base):
    """종목별 날짜별 종가 — 원본 데이터 저장소

    (code, date) 유니크 제약으로 중복 저장 방지.
    분석 기간의 시작일·종료일 종가만 저장 (일별 전체 아님).
    """
    __tablename__ = "stock_prices"
    __table_args__ = (UniqueConstraint("code", "date", name="uq_stock_price_code_date"),)

    id          : Mapped[int]   = mapped_column(primary_key=True)
    code        : Mapped[str]   = mapped_column(String(6), index=True)
    name        : Mapped[str]   = mapped_column(String(50))
    date        : Mapped[str]   = mapped_column(String(8), index=True)  # YYYYMMDD
    close_price : Mapped[int]   = mapped_column(Integer)
    created_at  : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AnalysisResult(Base):
    """Top100 분석 결과 — 기간별 1행 (가격은 StockPrice에서 조회)"""
    __tablename__ = "analysis_results"

    id          : Mapped[int]             = mapped_column(primary_key=True)
    start_date  : Mapped[str]             = mapped_column(String(8), index=True)  # YYYYMMDD
    end_date    : Mapped[str]             = mapped_column(String(8), index=True)
    market      : Mapped[str]             = mapped_column(String(10))  # 코스피 / 코스닥 / 통합
    rank        : Mapped[int]             = mapped_column(Integer)
    code        : Mapped[str]             = mapped_column(String(6))
    name        : Mapped[str]             = mapped_column(String(50))
    growth_rate : Mapped[float]           = mapped_column(Float)
    roe         : Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    op_margin   : Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score       : Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 복합점수
    created_at  : Mapped[datetime]        = mapped_column(DateTime, default=datetime.utcnow)


class WatchlistItem(Base):
    """사용자별 관심종목"""
    __tablename__ = "watchlist_items"

    id         : Mapped[int]      = mapped_column(primary_key=True)
    user_id    : Mapped[int]      = mapped_column(ForeignKey("users.id"), index=True)
    code       : Mapped[str]      = mapped_column(String(6))
    name       : Mapped[str]      = mapped_column(String(50))
    added_at   : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="watchlist")


class GoldenCrossLog(Base):
    """골든크로스 신호 이력"""
    __tablename__ = "golden_cross_logs"

    id         : Mapped[int]           = mapped_column(primary_key=True)
    code       : Mapped[str]           = mapped_column(String(6), index=True)
    name       : Mapped[str]           = mapped_column(String(50))
    signal_at  : Mapped[str]           = mapped_column(String(6))   # HHMMSS
    close      : Mapped[float]         = mapped_column(Float)
    ma3        : Mapped[float]         = mapped_column(Float)
    ma5        : Mapped[float]         = mapped_column(Float)
    detected_at: Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
