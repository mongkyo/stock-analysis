"""
[web/tests/conftest.py] 공통 테스트 픽스처
─────────────────────────────────────────
- SQLite 인메모리 DB (PostgreSQL 불필요)
- 테스트용 사용자(admin, operator, basic) 생성
- FastAPI TestClient + get_db 오버라이드
"""
import os
import sys

# 반드시 앱 import 전에 설정 (database.py가 환경변수를 읽어 engine 생성)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")

# web/ 디렉토리를 sys.path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import Base, get_db
from api.models.user import User, UserRole
from api.auth import create_token, hash_password


# ── 테스트 전용 SQLite 인메모리 엔진 ───────────────────────
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,   # 모든 연결이 같은 인메모리 DB 공유
)
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def override_get_db():
    """FastAPI 의존성 오버라이드 — 프로덕션 DB 대신 SQLite 사용"""
    session = _Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """세션 시작 시 테이블 생성, 종료 시 삭제"""
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture
def db(create_tables):
    """각 테스트마다 독립적인 DB 세션 (rollback으로 격리)"""
    session = _Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="session")
def client(create_tables):
    """FastAPI TestClient — get_db를 SQLite로 오버라이드"""
    from main import app
    app.dependency_overrides[get_db] = override_get_db
    from fastapi.testclient import TestClient
    with TestClient(app, raise_server_exceptions=False, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _make_user(db, username, email, role, is_active=True):
    user = User(
        username=username,
        email=email,
        hashed_pw=hash_password("testpass"),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(scope="session")
def admin_user(create_tables):
    db = _Session()
    user = _make_user(db, "admin_user", "admin@test.com", UserRole.admin)
    db.close()
    return user


@pytest.fixture(scope="session")
def operator_user(create_tables):
    db = _Session()
    user = _make_user(db, "operator_user", "operator@test.com", UserRole.operator)
    db.close()
    return user


@pytest.fixture(scope="session")
def basic_user(create_tables):
    db = _Session()
    user = _make_user(db, "basic_user", "basic@test.com", UserRole.basic)
    db.close()
    return user


@pytest.fixture(scope="session")
def admin_cookies(admin_user):
    return {"access_token": create_token({"sub": admin_user.username})}


@pytest.fixture(scope="session")
def operator_cookies(operator_user):
    return {"access_token": create_token({"sub": operator_user.username})}


@pytest.fixture(scope="session")
def basic_cookies(basic_user):
    return {"access_token": create_token({"sub": basic_user.username})}
