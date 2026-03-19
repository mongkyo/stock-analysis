"""
[web/api/services/analysis_service.py] Top100 분석 실행 서비스
──────────────────────────────────────────────────────
역할:
  - KIS API 호출 → Top100 분석 실행
  - 결과를 analysis_results DB 테이블에 upsert
  - admin 전용 (routers/dashboard.py 에서 require_role(admin) 보호)

주요 함수:
  run_analysis(db, start, end) → dict
      {"saved": int, "markets": list}  — 저장 건수 반환
  _upsert_results(db, rows, market) → int
      AnalysisResult 레코드 upsert

의존성:
  - scripts/top100.py (get_combined_top100)
  - api/config.py (KIS 키)
  - api/models/stock.py (AnalysisResult)

수정 이력:
  2026-03-19  최초 작성
──────────────────────────────────────────────────────
"""

import sys
import os
from typing import Optional

from sqlalchemy.orm import Session

from api.config import settings
from api.models.stock import AnalysisResult

# scripts/ 경로를 sys.path에 추가 (top100.py import용)
_scripts_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts")
)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


def _get_kis_client():
    """KIS API 클라이언트 생성. 키 미설정 시 ValueError 발생."""
    if not settings.kis_configured():
        raise ValueError(
            "KIS API 키가 설정되지 않았습니다. "
            ".env 파일에 KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO를 입력하세요."
        )
    from kis_api import KISClient
    return KISClient(
        app_key=settings.KIS_APP_KEY,
        app_secret=settings.KIS_APP_SECRET,
    )


def _upsert_results(db: Session, rows: list[dict], market: str,
                    start: str, end: str) -> int:
    """분석 결과를 DB에 upsert (같은 기간+시장+종목코드+순위 → 덮어쓰기)

    Args:
        db:     DB 세션
        rows:   [{"rank": int, "code": str, "name": str, ...}, ...]
        market: "통합" | "코스피" | "코스닥"
        start:  YYYYMMDD
        end:    YYYYMMDD

    Returns:
        저장된 레코드 수
    """
    # 해당 기간+시장 기존 데이터 삭제 후 재삽입 (upsert 대신 delete-insert)
    (db.query(AnalysisResult)
     .filter(AnalysisResult.start_date == start,
             AnalysisResult.end_date == end,
             AnalysisResult.market == market)
     .delete())

    records = [
        AnalysisResult(
            start_date=start,
            end_date=end,
            market=market,
            rank=row["rank"],
            code=row["code"],
            name=row["name"],
            start_price=row["start_price"],
            end_price=row["end_price"],
            growth_rate=row["growth_rate"],
            roe=row.get("roe"),
            op_margin=row.get("op_margin"),
        )
        for row in rows
    ]
    db.add_all(records)
    return len(records)


def _df_to_rows(df, market: str) -> list[dict]:
    """DataFrame → DB 저장용 dict 리스트 변환

    top100.py 컬럼: 종목코드 | 종목명 | 시장 | 시작가 | 종료가 | 수익률(%) | ROE | 영업이익률
    itertuples()는 컬럼명의 특수문자(%)를 _로 치환하므로 getattr로 접근
    """
    rows = []
    for i, r in enumerate(df.itertuples(), start=1):
        # 수익률(%) → itertuples에서 '수익률__'로 변환될 수 있어 df 직접 접근
        row_dict = df.iloc[i - 1].to_dict()
        rows.append({
            "rank":        i,
            "code":        row_dict["종목코드"],
            "name":        row_dict["종목명"],
            "start_price": int(row_dict["시작가"]),
            "end_price":   int(row_dict["종료가"]),
            "growth_rate": float(row_dict["수익률(%)"]),
            "roe":         float(row_dict["ROE"]) if row_dict.get("ROE") is not None else None,
            "op_margin":   float(row_dict["영업이익률"]) if row_dict.get("영업이익률") is not None else None,
        })
    return rows


def run_analysis(db: Session, start: str, end: str) -> dict:
    """Top100 분석 실행 → DB 저장

    Args:
        db:    DB 세션
        start: 시작일 YYYYMMDD (또는 YYYY-MM-DD, 자동 변환)
        end:   종료일 YYYYMMDD (또는 YYYY-MM-DD, 자동 변환)

    Returns:
        {"saved": 총 저장 건수, "markets": ["통합", "코스피", "코스닥"]}

    Raises:
        ValueError: KIS 키 미설정
        RuntimeError: 분석 실패
    """
    # 날짜 형식 정규화 (YYYY-MM-DD → YYYYMMDD)
    start = start.replace("-", "")
    end   = end.replace("-", "")

    client = _get_kis_client()

    from top100 import get_combined_top100, find_reentry_stocks, load_prev_combined
    from report import create_excel_report

    try:
        combined_df, kospi_df, kosdaq_df = get_combined_top100(client, start, end)
    except Exception as e:
        raise RuntimeError(f"KIS API 분석 실패: {e}") from e

    if combined_df.empty and kospi_df.empty and kosdaq_df.empty:
        raise RuntimeError("분석 결과가 비어 있습니다. 날짜 범위를 확인하세요.")

    # ── 재진입 포착 ───────────────────────────────────────────
    prev_df = load_prev_combined()
    reentry_df = find_reentry_stocks(prev_df, combined_df) if not prev_df.empty else None

    # ── 엑셀 리포트 생성 → data/ 저장 ────────────────────────
    try:
        excel_path = create_excel_report(
            combined_df, kospi_df, kosdaq_df, reentry_df, start, end
        )
    except Exception as e:
        excel_path = None  # 엑셀 실패해도 DB 저장은 계속 진행
        print(f"[경고] 엑셀 생성 실패: {e}")

    # ── DB 저장 ───────────────────────────────────────────────
    total_saved = 0
    for df, market in [
        (combined_df, "통합"),
        (kospi_df,   "코스피"),
        (kosdaq_df,  "코스닥"),
    ]:
        if df.empty:
            continue
        rows = _df_to_rows(df, market)
        total_saved += _upsert_results(db, rows, market, start, end)

    db.commit()
    return {
        "saved":      total_saved,
        "markets":    ["통합", "코스피", "코스닥"],
        "excel_path": excel_path,  # 웹 리포트 목록에서 바로 확인 가능
    }
