"""
[web/api/routers/admin.py] 관리자 전용 라우터
──────────────────────────────────────────────────────
엔드포인트:
  GET  /admin/users              → 회원 목록 (대기중 + 전체)
  POST /admin/users/{id}/approve → 회원 승인 + 권한 설정
  POST /admin/users/{id}/role    → 권한 변경
  POST /admin/users/{id}/deactivate → 비활성화

접근 권한: admin 전용 (require_role(UserRole.admin))
수정 이력:
  2026-03-23  최초 작성
──────────────────────────────────────────────────────
"""

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from api.database import get_db
from api.auth import require_role
from api.models.user import User, UserRole

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")


@router.get("/users", response_class=HTMLResponse)
def users_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    """회원 목록 — 승인 대기 + 전체"""
    pending = (db.query(User)
               .filter(User.is_active == False, User.role != UserRole.admin)
               .order_by(User.created_at.asc())
               .all())
    users = (db.query(User)
             .order_by(User.created_at.desc())
             .all())
    return templates.TemplateResponse(request, "admin/users.html", {
        "user":    user,
        "pending": pending,
        "users":   users,
    })


@router.post("/users/{user_id}/approve", response_class=HTMLResponse)
def approve_user(
    user_id: int,
    request: Request,
    role: str = Form("basic"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """회원 승인 + 권한 설정 (HTMX)"""
    target = db.query(User).filter(User.id == user_id).first()
    if target:
        target.is_active = True
        target.role = UserRole(role) if role in UserRole._value2member_map_ else UserRole.basic
        db.commit()
        db.refresh(target)

    # 승인된 행을 활성 상태로 교체
    return templates.TemplateResponse(request, "admin/partials/user_row.html", {
        "u": target,
        "context": "all",
    })


@router.post("/users/{user_id}/role", response_class=HTMLResponse)
def change_role(
    user_id: int,
    request: Request,
    role: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """권한 변경 (HTMX)"""
    target = db.query(User).filter(User.id == user_id).first()
    if target and target.role != UserRole.admin:
        target.role = UserRole(role) if role in UserRole._value2member_map_ else target.role
        db.commit()
        db.refresh(target)

    return templates.TemplateResponse(request, "admin/partials/user_row.html", {
        "u": target,
        "context": "all",
    })


@router.post("/users/{user_id}/deactivate", response_class=HTMLResponse)
def deactivate_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """비활성화 (HTMX)"""
    target = db.query(User).filter(User.id == user_id).first()
    if target and target.role != UserRole.admin:
        target.is_active = False
        db.commit()
        db.refresh(target)

    return templates.TemplateResponse(request, "admin/partials/user_row.html", {
        "u": target,
        "context": "all",
    })
