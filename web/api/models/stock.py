"""
[web/api/models/stock.py] 주식 관련 DB 모델
──────────────────────────────────────────────────────
역할:
  AnalysisResult  — Top100 분석 결과 (기간별)
  WatchlistItem   — 사용자별 관심종목
  GoldenCrossLog  — 골든크로스 신호 이력
수정 이력:
  2026-03-19  최초 작성
──────────────────────────────────────────────────────
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from api.database import Base


class AnalysisResult(Base):
    """Top100 분석 결과 — 기간별 1행"""
    __tablename__ = "analysis_results"

    id          : Mapped[int]           = mapped_column(primary_key=True)
    start_date  : Mapped[str]           = mapped_column(String(8), index=True)  # YYYYMMDD
    end_date    : Mapped[str]           = mapped_column(String(8), index=True)
    market      : Mapped[str]           = mapped_column(String(10))  # 코스피 / 코스닥 / 통합
    rank        : Mapped[int]           = mapped_column(Integer)
    code        : Mapped[str]           = mapped_column(String(6))
    name        : Mapped[str]           = mapped_column(String(50))
    start_price : Mapped[int]           = mapped_column(Integer)
    end_price   : Mapped[int]           = mapped_column(Integer)
    growth_rate : Mapped[float]         = mapped_column(Float)
    roe         : Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    op_margin   : Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at  : Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


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
