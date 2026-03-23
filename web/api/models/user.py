"""
[web/api/models/user.py] 사용자 DB 모델
──────────────────────────────────────────────────────
역할: User 테이블 정의 (권한: admin / premium / basic)
컬럼:
  auth_provider — "local" | "google" | "kakao" (OAuth 확장 대비)
  hashed_pw     — 소셜 로그인 시 NULL 허용
  is_active     — False = 승인 대기 상태
수정 이력:
  2026-03-19  최초 작성
  2026-03-23  auth_provider 추가, hashed_pw nullable, name 컬럼 추가
──────────────────────────────────────────────────────
"""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, Boolean, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from api.database import Base
import enum


class UserRole(str, enum.Enum):
    admin   = "admin"
    premium = "premium"
    basic   = "basic"


class AuthProvider(str, enum.Enum):
    local  = "local"   # 일반 회원가입
    google = "google"  # 구글 로그인 (추후 구현)
    kakao  = "kakao"   # 카카오 로그인 (추후 구현)


class User(Base):
    __tablename__ = "users"

    id            : Mapped[int]          = mapped_column(primary_key=True)
    username      : Mapped[str]          = mapped_column(String(50), unique=True, index=True)
    email         : Mapped[str]          = mapped_column(String(100), unique=True, index=True)
    name          : Mapped[Optional[str]]= mapped_column(String(50), nullable=True)   # 실명/닉네임
    hashed_pw     : Mapped[Optional[str]]= mapped_column(String(200), nullable=True)  # 소셜 로그인 시 NULL
    auth_provider : Mapped[AuthProvider] = mapped_column(default=AuthProvider.local)
    role          : Mapped[UserRole]     = mapped_column(default=UserRole.basic)
    is_active     : Mapped[bool]         = mapped_column(Boolean, default=False)      # 기본값: 승인 대기
    created_at    : Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow)

    watchlist  : Mapped[List["WatchlistItem"]] = relationship("WatchlistItem", back_populates="user")
