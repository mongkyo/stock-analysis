"""
[web/api/database.py] DB 연결 설정
──────────────────────────────────────────────────────
역할: SQLAlchemy 엔진, 세션, Base 클래스 제공
수정 이력:
  2026-03-19  최초 작성
──────────────────────────────────────────────────────
"""

from api.config import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = settings.DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 의존성 주입용 DB 세션"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
