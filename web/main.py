"""
[web/main.py] FastAPI 앱 진입점
──────────────────────────────────────────────────────
역할:
  - FastAPI 인스턴스 생성 및 라우터 등록
  - DB 테이블 초기화 (Base.metadata.create_all)
  - 정적 파일 / 템플릿 설정
  - 예외 핸들러 (303 리다이렉트 처리)

실행:
  cd web && uvicorn main:app --reload --port 8000

수정 이력:
  2026-03-19  최초 작성
──────────────────────────────────────────────────────
"""

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

from api.database import engine, Base
# 모델 import — create_all이 테이블 생성할 수 있도록
from api.models import user, stock  # noqa: F401
from api.routers import auth, dashboard, watchlist, admin

# ── DB 테이블 생성 ─────────────────────────────────────
Base.metadata.create_all(bind=engine)

# ── FastAPI 앱 ─────────────────────────────────────────
app = FastAPI(title="주식 분석 플랫폼", version="0.1.0")

# 정적 파일 (Tailwind 빌드 결과 등)
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ── 라우터 등록 ────────────────────────────────────────
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(watchlist.router)
app.include_router(admin.router)


# ── 303 리다이렉트 예외 처리 ───────────────────────────
# get_current_user가 미로그인 시 HTTPException(303)을 raise함
# FastAPI 기본 처리는 JSON 반환 → 브라우저 리다이렉트로 변환
from fastapi.exceptions import HTTPException as FastAPIHTTPException

_templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    if exc.status_code == 303:
        location = exc.headers.get("Location", "/auth/login")
        return RedirectResponse(url=location, status_code=303)

    if exc.status_code == 403:
        # 권한 부족 → 403 전용 페이지 렌더링
        from api.auth import get_current_user
        from api.database import SessionLocal
        user_role = "알 수 없음"
        try:
            db = SessionLocal()
            user = get_current_user(request, db)
            user_role = user.role if user else "비로그인"
            db.close()
        except Exception:
            pass
        return _templates.TemplateResponse(
            request, "errors/403.html",
            {"required_role": "Premium 이상", "user_role": user_role},
            status_code=403,
        )

    from fastapi.responses import JSONResponse
    import json
    return JSONResponse(
        status_code=exc.status_code,
        content=json.loads(json.dumps({"detail": exc.detail}, ensure_ascii=False))
    )
