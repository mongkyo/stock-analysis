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
  2026-03-24  _recalc_scores() 추가 — 조회 시 현재 가중치로 종합점수 실시간 재계산
──────────────────────────────────────────────────────
"""

import os
import glob
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
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


def _recalc_scores(rows: list[_ResultRow]) -> list[_ResultRow]:
    """DB 조회 결과에 현재 가중치로 종합점수 실시간 재계산 후 재정렬

    AnalysisResult에는 일평균거래량이 없으므로 3개 지표만 사용.
    SCORE_WEIGHTS에서 가용 지표의 비율로 정규화.
    """
    if not rows:
        return rows

    import pandas as pd
    # top100.py SCORE_WEIGHTS import (analysis_service가 sys.path 설정)
    try:
        from top100 import SCORE_WEIGHTS
        weights = {k: v for k, v in SCORE_WEIGHTS.items()
                   if k in ("수익률(%)", "ROE", "영업이익률")}
        total_w = sum(weights.values())
        weights = {k: v / total_w for k, v in weights.items()}  # 합계 1.0 정규화
    except Exception:
        # import 실패 시 고정값 fallback
        weights = {"수익률(%)": 0.7368, "ROE": 0.1579, "영업이익률": 0.1053}

    col_map = {"수익률(%)": "growth_rate", "ROE": "roe", "영업이익률": "op_margin"}

    df = pd.DataFrame([
        {col: getattr(r, attr) for col, attr in col_map.items()}
        for r in rows
    ])

    score = pd.Series(0.0, index=df.index)
    for col, weight in weights.items():
        series = df[col].copy().astype(float)
        series = series.fillna(series.median())
        pct = series.rank(pct=True, method="average") * 100
        score += pct * weight

    for i, row in enumerate(rows):
        row.score = round(float(score[i]), 2)

    rows.sort(key=lambda r: r.score, reverse=True)
    for i, row in enumerate(rows):
        row.rank = i + 1

    return rows


def _query_results_with_prices(db, start: str, end: str, market: str,
                                limit: int = 100) -> list[_ResultRow]:
    """AnalysisResult + StockPrice 조인 → 현재 가중치로 점수 재계산 후 반환"""
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
    result_rows = [_ResultRow(ar, sp, ep) for ar, sp, ep in rows]
    return _recalc_scores(result_rows)  # 현재 가중치로 실시간 재계산

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


@router.post("/analysis/run")
def analysis_run(
    start: str = Query(...),
    end:   str = Query(...),
    user: User = Depends(require_role(UserRole.admin)),
):
    """분석 백그라운드 시작 (admin 전용) → job_id 반환"""
    from api.services.analysis_service import start_analysis_job
    job_id = start_analysis_job(start, end)
    return JSONResponse({"job_id": job_id})


@router.get("/analysis/progress/{job_id}")
def analysis_progress(
    job_id: str,
    user: User = Depends(get_current_user),
):
    """분석 진행 상태 폴링"""
    from api.services.analysis_service import get_job_status
    status = get_job_status(job_id)
    if status is None:
        return JSONResponse({"status": "not_found", "message": "작업을 찾을 수 없습니다", "percent": 0})
    return JSONResponse({
        "status":  status["status"],
        "message": status["message"],
        "percent": status["percent"],
        "error":   status.get("error"),
    })


@router.get("/analysis/progress/{job_id}/result", response_class=HTMLResponse)
def analysis_progress_result(
    request: Request,
    job_id: str,
    start:  str = Query(...),
    end:    str = Query(...),
    market: str = Query("통합"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """분석 완료 후 결과 테이블 반환"""
    start_n = start.replace("-", "")
    end_n   = end.replace("-", "")
    results = _query_results_with_prices(db, start_n, end_n, market)

    from api.services.analysis_service import get_job_status
    job         = get_job_status(job_id) or {}
    result_meta = job.get("result") or {}
    excel_name  = None
    if result_meta.get("excel_path"):
        excel_name = os.path.basename(result_meta["excel_path"])

    run_msg = f"분석 완료 — {result_meta.get('saved', 0)}건 저장"
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


def _quick_query_from_prices(db, start: str, end: str,
                              market: str) -> list[_ResultRow] | None:
    """StockPrice + AnalysisResult 이력만으로 실시간 Top100 계산 (API 0번 호출)

    AnalysisResult가 없는 기간 조회 시 폴백으로 사용.
    - 가격:       StockPrice (start/end 날짜 근방 실제 매매일 자동 탐색)
    - ROE/OPM:    해당 종목의 가장 최근 AnalysisResult 값 재사용
    - 시장 구분:  이전 AnalysisResult 이력에서 코드 → 시장 추론

    Returns:
        _ResultRow 리스트 (없으면 None)
    """
    import pandas as pd
    from sqlalchemy import func
    from api.services.analysis_service import _find_cache_dates

    actual_start, actual_end = _find_cache_dates(db, start, end)
    if not actual_start or not actual_end:
        return None

    # ── 종가 조회 ─────────────────────────────────────────────
    start_map: dict[str, tuple[str, int]] = {
        sp.code: (sp.name, sp.close_price)
        for sp in db.query(StockPrice)
                    .filter(StockPrice.date == actual_start).all()
    }
    end_map: dict[str, int] = {
        sp.code: sp.close_price
        for sp in db.query(StockPrice)
                    .filter(StockPrice.date == actual_end).all()
    }

    common = set(start_map) & set(end_map)
    if not common:
        return None

    # ── 수익률 계산 ───────────────────────────────────────────
    rows = []
    for code in common:
        name, sp = start_map[code]
        ep = end_map[code]
        if sp and ep and sp > 0:
            rows.append({
                "code": code, "name": name,
                "start_price": sp, "end_price": ep,
                "growth_rate": round((ep - sp) / sp * 100, 2),
            })

    if not rows:
        return None

    # ── 이전 분석 이력에서 종목별 ROE/OPM + 시장 구분 ─────────
    # 종목 코드 → (ROE, op_margin) : 가장 최신 AnalysisResult 값 재사용
    fin_sq = (
        db.query(
            AnalysisResult.code,
            AnalysisResult.roe,
            AnalysisResult.op_margin,
            func.row_number().over(
                partition_by=AnalysisResult.code,
                order_by=AnalysisResult.end_date.desc()
            ).label("rn")
        ).subquery()
    )
    fin_rows = db.query(fin_sq).filter(fin_sq.c.rn == 1).all()
    fin_map  = {r.code: (r.roe, r.op_margin) for r in fin_rows}

    # 종목 코드 → 시장 (코스피/코스닥): 어느 market 분석에 가장 많이 등장했는지
    mkt_rows = (
        db.query(AnalysisResult.code, AnalysisResult.market)
        .filter(AnalysisResult.market.in_(["코스피", "코스닥"]))
        .all()
    )
    mkt_counter: dict[str, dict[str, int]] = {}
    for r in mkt_rows:
        mkt_counter.setdefault(r.code, {}).setdefault(r.market, 0)
        mkt_counter[r.code][r.market] += 1
    mkt_map = {
        code: max(mkts, key=mkts.get)
        for code, mkts in mkt_counter.items()
    }

    for row in rows:
        roe, opm = fin_map.get(row["code"], (None, None))
        row["roe"]       = roe
        row["op_margin"] = opm
        row["stock_market"] = mkt_map.get(row["code"])  # 없으면 None

    # 시장 필터 (코스피/코스닥 탭)
    if market in ("코스피", "코스닥"):
        rows = [r for r in rows if r["stock_market"] == market]

    if not rows:
        return None

    # ── 복합점수 계산 → Top100 ────────────────────────────────
    FETCH_N = 500
    TOP_N   = 100
    rows.sort(key=lambda r: r["growth_rate"], reverse=True)
    rows = rows[:FETCH_N]

    result_rows = [
        _ResultRow(
            _FakeAR(i + 1, r["code"], r["name"],
                    r["growth_rate"], r["roe"], r["op_margin"],
                    actual_start, actual_end),
            r["start_price"], r["end_price"],
        )
        for i, r in enumerate(rows)
    ]
    result_rows = _recalc_scores(result_rows)
    return result_rows[:TOP_N]


class _FakeAR:
    """_ResultRow 생성에 필요한 AnalysisResult 인터페이스 모사"""
    __slots__ = ("rank", "code", "name", "growth_rate", "roe",
                 "op_margin", "score", "start_date", "end_date")

    def __init__(self, rank, code, name, growth_rate, roe, op_margin,
                 start_date, end_date):
        self.rank        = rank
        self.code        = code
        self.name        = name
        self.growth_rate = growth_rate
        self.roe         = roe
        self.op_margin   = op_margin
        self.score       = None
        self.start_date  = start_date
        self.end_date    = end_date


@router.get("/analysis/result", response_class=HTMLResponse)
def analysis_result(
    request: Request,
    start: str = Query(...),
    end:   str = Query(...),
    market: str = Query("통합"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """HTMX 요청 — Top100 테이블 부분 렌더링
    AnalysisResult 없으면 StockPrice + 이전 재무 이력으로 실시간 계산 (API 0번 호출)
    """
    start_n = start.replace("-", "")
    end_n   = end.replace("-", "")

    results   = _query_results_with_prices(db, start_n, end_n, market)
    is_live   = False  # 저장된 분석 결과 사용 여부

    if not results:
        results = _quick_query_from_prices(db, start_n, end_n, market) or []
        is_live = bool(results)

    return templates.TemplateResponse(request, "analysis/partials/table.html", {
        "results": results,
        "market":  market,
        "start":   start,
        "end":     end,
        "is_live": is_live,  # 템플릿에서 "실시간 조회" 배지 표시용
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
