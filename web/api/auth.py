"""
[web/api/auth.py] 인증 유틸리티
──────────────────────────────────────────────────────
역할:
  - 비밀번호 해시/검증 (bcrypt)
  - JWT 토큰 발급/검증
  - 현재 로그인 사용자 의존성 주입
  - 권한 체크 (admin / premium / basic)

주요 함수:
  hash_password(pw)         → 해시 문자열
  verify_password(pw, hash) → bool
  create_token(data)        → JWT 문자열
  get_current_user(request) → User (쿠키에서 토큰 읽기)
  require_role(*roles)      → 의존성 팩토리

수정 이력:
  2026-03-19  최초 작성 — JWT + 쿠키 방식 (세션 없이)
──────────────────────────────────────────────────────
"""

from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Request, HTTPException, status, Depends
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from api.database import get_db
from api.models.user import User, UserRole

from api.config import settings
SECRET_KEY  = settings.SECRET_KEY
ALGORITHM   = "HS256"
TOKEN_EXPIRE_HOURS = 24


# ── 비밀번호 ───────────────────────────────────────────────

def hash_password(password: str) -> str:
    """bcrypt로 비밀번호 해시 (72바이트 제한 있음)"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── JWT ───────────────────────────────────────────────────

def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── 현재 사용자 의존성 ─────────────────────────────────────

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """쿠키에서 토큰 읽어 현재 사용자 반환. 미로그인 시 로그인 페이지로 리다이렉트."""
    from fastapi.responses import RedirectResponse
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"})

    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"})

    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"})
    return user


def require_role(*roles: UserRole):
    """특정 권한 이상만 허용하는 의존성 팩토리

    사용 예:
        @router.get("/admin")
        def admin_page(user = Depends(require_role(UserRole.admin))):
    """
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="접근 권한이 없습니다.")
        return user
    return checker
