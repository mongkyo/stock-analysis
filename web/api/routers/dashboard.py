"""
[web/api/routers/dashboard.py] 메인 대시보드 라우터
──────────────────────────────────────────────────────
엔드포인트:
  GET /          → 대시보드 (로그인 필요)
  GET /analysis  → Top100 분석 결과 페이지
  GET /analysis/run  → 분석 실행 (HTMX 요청)
  GET /reports   → 리포트 다운로드 페이지
  GET /reports/download/{filename} → 엑셀 파일 다운로드
수정 이력:
  2026-03-19  최초 작성
──────────────────────────────────────────────────────
"""

import os
import glob
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from api.database import get_db
from api.auth import get_current_user, require_role
from api.models.user import User, UserRole
from api.models.stock import AnalysisResult, GoldenCrossLog, StockPrice
from sqlalchemy.orm import aliased
from api.services.analysis_service import run_analysis

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="templates")


class _ResultRow:
    """AnalysisResult + 가격 정보를 하나의 객체로 래핑 — 템플릿 호환용"""
    __slots__ = ("rank", "code", "name", "growth_rate", "roe", "op_margin",
                 "score", "start_date", "end_date", "start_price", "end_price")

    def __init__(self, ar: AnalysisResult, start_price, end_price):
        self.rank        = ar.rank
        self.code        = ar.code
        self.name        = ar.name
        self.growth_rate = ar.growth_rate
        self.roe         = ar.roe
        self.op_margin   = ar.op_margin
        self.score       = ar.score
        self.start_date  = ar.start_date
        self.end_date    = ar.end_date
        self.start_price = start_price or 0
        self.end_price   = end_price   or 0


def _query_results_with_prices(db, start: str, end: str, market: str,
                                limit: int = 100) -> list[_ResultRow]:
    """AnalysisResult + StockPrice 조인 → _ResultRow 리스트 반환"""
    sp_start = aliased(StockPrice)
    sp_end   = aliased(StockPrice)
    rows = (
        db.query(
            AnalysisResult,
            sp_start.close_price.label("start_price"),
            sp_end.close_price.label("end_price"),
        )
        .outerjoin(sp_start, (sp_start.code == AnalysisResult.code) &
                             (sp_start.date == AnalysisResult.start_date))
        .outerjoin(sp_end,   (sp_end.code == AnalysisResult.code) &
                             (sp_end.date == AnalysisResult.end_date))
        .filter(AnalysisResult.start_date == start,
                AnalysisResult.end_date == end,
                AnalysisResult.market == market)
        .order_by(AnalysisResult.rank)
        .limit(limit)
        .all()
    )
    return [_ResultRow(ar, sp, ep) for ar, sp, ep in rows]

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """메인 대시보드 — 요약 카드 + 최근 Top5 + 골든크로스 신호"""

    # 가장 최근 분석 결과 기간 조회
    latest = (db.query(AnalysisResult)
              .filter(AnalysisResult.market == "통합")
              .order_by(AnalysisResult.end_date.desc(),
                        AnalysisResult.rank.asc())
              .first())

    top5 = []
    summary = {}

    if latest:
        start_date = latest.start_date
        end_date   = latest.end_date

        top5 = _query_results_with_prices(db, start_date, end_date, "통합", limit=5)

        summary = {
            "start_date": f"{start_date[:4]}.{start_date[4:6]}.{start_date[6:]}",
            "end_date":   f"{end_date[:4]}.{end_date[4:6]}.{end_date[6:]}",
            "top1":       top5[0] if top5 else None,
        }

    # 오늘 골든크로스 신호
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    signals = (db.query(GoldenCrossLog)
               .filter(GoldenCrossLog.detected_at >= today)
               .order_by(GoldenCrossLog.detected_at.desc())
               .limit(5).all())

    return templates.TemplateResponse(request, "dashboard/index.html", {
        "user":     user,
        "top5":     top5,
        "summary":  summary,
        "signals":  signals,
    })


@router.get("/analysis", response_class=HTMLResponse)
def analysis_page(
    request: Request,
    user: User = Depends(require_role(UserRole.admin, UserRole.premium, UserRole.basic)),
):
    return templates.TemplateResponse(request, "analysis/index.html", {
        "user": user,
    })


@router.post("/analysis/run", response_class=HTMLResponse)
def analysis_run(
    request: Request,
    start: str = Query(...),
    end:   str = Query(...),
    market: str = Query("통합"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),  # admin 전용
):
    """분석 실행 (admin 전용, HTMX 요청)
    KIS API 호출 → DB 저장 → 결과 테이블 반환
    """
    from fastapi.responses import HTMLResponse as HR

    try:
        result = run_analysis(db, start, end)
        # 저장 완료 후 해당 기간 통합 결과 조회
        results = _query_results_with_prices(
            db, start.replace("-", ""), end.replace("-", ""), market)
        import os
        excel_name = os.path.basename(result["excel_path"]) if result.get("excel_path") else None
        run_msg = f"분석 완료 — {result['saved']}건 저장"
        if excel_name:
            run_msg += f" · 엑셀 저장됨 ({excel_name})"
        return templates.TemplateResponse(request, "analysis/partials/table.html", {
            "results":    results,
            "market":     market,
            "start":      start,
            "end":        end,
            "run_msg":    run_msg,
            "excel_name": excel_name,
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "analysis/partials/error.html", {
            "error": str(e),
        })
    except RuntimeError as e:
        return templates.TemplateResponse(request, "analysis/partials/error.html", {
            "error": str(e),
        })


@router.get("/analysis/result", response_class=HTMLResponse)
def analysis_result(
    request: Request,
    start: str = Query(...),
    end:   str = Query(...),
    market: str = Query("통합"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """HTMX 요청 — Top100 테이블 부분 렌더링"""
    results = _query_results_with_prices(
        db, start.replace("-", ""), end.replace("-", ""), market)

    return templates.TemplateResponse(request, "analysis/partials/table.html", {
        "results": results,
        "market":  market,
        "start":   start,
        "end":     end,
    })


@router.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, user: User = Depends(require_role(UserRole.admin, UserRole.premium))):
    """리포트 목록 페이지"""
    files = sorted(
        glob.glob(os.path.join(DATA_DIR, "report_*.xlsx")),
        reverse=True)
    report_list = [os.path.basename(f) for f in files]

    return templates.TemplateResponse(request, "dashboard/reports.html", {
        "user":    user,
        "reports": report_list,
    })


@router.get("/reports/download/{filename}")
def download_report(filename: str, user: User = Depends(require_role(UserRole.admin, UserRole.premium))):
    """엑셀 리포트 다운로드"""
    # 경로 탈출 방지
    if ".." in filename or "/" in filename:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="잘못된 파일명")

    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
