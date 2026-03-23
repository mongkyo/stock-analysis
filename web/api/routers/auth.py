"""
[web/api/routers/auth.py] 로그인/로그아웃 라우터
──────────────────────────────────────────────────────
엔드포인트:
  GET  /auth/login   → 로그인 페이지
  POST /auth/login   → 로그인 처리 (JWT 쿠키 발급)
  GET  /auth/logout  → 로그아웃 (쿠키 삭제)
수정 이력:
  2026-03-19  최초 작성
──────────────────────────────────────────────────────
"""

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from api.database import get_db
from api.models.user import User
from api.auth import verify_password, create_token

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html")


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    # 사용자 조회
    user = db.query(User).filter(User.username == username).first()

    if not user or not verify_password(password, user.hashed_pw):
        return templates.TemplateResponse(request, "auth/login.html", {
            "error": "아이디 또는 비밀번호가 올바르지 않습니다.",
        })

    if not user.is_active:
        return templates.TemplateResponse(request, "auth/login.html", {
            "error": "비활성화된 계정입니다. 관리자에게 문의하세요.",
        })

    # JWT 발급 → 쿠키에 저장
    token = create_token({"sub": user.username, "role": user.role})
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,   # JS에서 접근 불가 (XSS 방지)
        max_age=60 * 60 * 24,  # 24시간
        samesite="lax",
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie("access_token")
    return response
