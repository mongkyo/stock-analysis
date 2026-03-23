"""
[web/api/routers/watchlist.py] 관심종목 CRUD 라우터
──────────────────────────────────────────────────────
엔드포인트:
  GET  /watchlist              → 관심종목 목록 (HTMX 부분 렌더링)
  POST /watchlist              → 종목 추가
  DELETE /watchlist/{code}     → 종목 삭제
수정 이력:
  2026-03-19  최초 작성
──────────────────────────────────────────────────────
"""

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from api.database import get_db
from api.auth import get_current_user
from api.models.user import User
from api.models.stock import WatchlistItem

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
def watchlist_page(request: Request, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """관심종목 목록 페이지"""
    items = (db.query(WatchlistItem)
             .filter(WatchlistItem.user_id == user.id)
             .order_by(WatchlistItem.added_at.desc())
             .all())
    return templates.TemplateResponse(request, "watchlist/index.html", {
        "user":  user,
        "items": items,
    })


@router.post("", response_class=HTMLResponse)
def add_watchlist(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """관심종목 추가 (HTMX)"""
    # 중복 체크
    exists = (db.query(WatchlistItem)
              .filter(WatchlistItem.user_id == user.id,
                      WatchlistItem.code == code)
              .first())
    if not exists:
        item = WatchlistItem(user_id=user.id, code=code.strip(), name=name.strip())
        db.add(item)
        db.commit()
        db.refresh(item)

    items = (db.query(WatchlistItem)
             .filter(WatchlistItem.user_id == user.id)
             .order_by(WatchlistItem.added_at.desc())
             .all())
    return templates.TemplateResponse(request, "watchlist/partials/list.html", {
        "items": items,
    })


@router.delete("/{code}", response_class=HTMLResponse)
def remove_watchlist(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """관심종목 삭제 (HTMX)"""
    (db.query(WatchlistItem)
     .filter(WatchlistItem.user_id == user.id,
             WatchlistItem.code == code)
     .delete())
    db.commit()

    items = (db.query(WatchlistItem)
             .filter(WatchlistItem.user_id == user.id)
             .order_by(WatchlistItem.added_at.desc())
             .all())
    return templates.TemplateResponse(request, "watchlist/partials/list.html", {
        "items": items,
    })
