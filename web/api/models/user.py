"""
[web/api/models/user.py] 사용자 DB 모델
──────────────────────────────────────────────────────
역할: User 테이블 정의 (권한: admin / premium / basic)
수정 이력:
  2026-03-19  최초 작성
──────────────────────────────────────────────────────
"""

from datetime import datetime
from typing import List
from sqlalchemy import String, Boolean, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from api.database import Base
import enum


class UserRole(str, enum.Enum):
    admin   = "admin"
    premium = "premium"
    basic   = "basic"


class User(Base):
    __tablename__ = "users"

    id         : Mapped[int]      = mapped_column(primary_key=True)
    username   : Mapped[str]      = mapped_column(String(50), unique=True, index=True)
    email      : Mapped[str]      = mapped_column(String(100), unique=True, index=True)
    hashed_pw  : Mapped[str]      = mapped_column(String(200))
    role       : Mapped[UserRole] = mapped_column(default=UserRole.basic)
    is_active  : Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    watchlist  : Mapped[List["WatchlistItem"]] = relationship("WatchlistItem", back_populates="user")
