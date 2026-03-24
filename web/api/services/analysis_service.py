"""
[web/api/services/analysis_service.py] Top100 분석 실행 서비스
──────────────────────────────────────────────────────
역할:
  - KIS API 호출 → Top100 분석 실행
  - 종가를 stock_prices 테이블에 저장 (재사용 가능)
  - 분석 결과를 analysis_results 테이블에 upsert
  - admin 전용 (routers/dashboard.py 에서 require_role(admin) 보호)
  - 캐시 로직: start/end 날짜 모두 StockPrice에 충분한 데이터가 있으면
    KIS 가격 API 호출 없이 DB에서 직접 수익률 계산

주요 함수:
  run_analysis(db, start, end) → dict
      {"saved": int, "markets": list}  — 저장 건수 반환
  _find_cache_dates(db, start, end) → (actual_start, actual_end) | (None, None)
      StockPrice에서 유효한 실제 매매일 탐색
  _run_from_cache(db, actual_start, actual_end) → (combined_df, kospi_df, kosdaq_df)
      DB에서 수익률 계산 → 재무 API 호출 → Top100 반환
  _upsert_stock_prices(db, rows, start, end) → None
      시작일·종료일 종가를 StockPrice 테이블에 저장 (중복 무시)
  _upsert_results(db, rows, market, start, end) → int
      AnalysisResult 레코드 upsert

의존성:
  - scripts/top100.py (get_combined_top100, filter_by_financials, calculate_composite_score)
  - api/config.py (KIS 키)
  - api/models/stock.py (AnalysisResult, StockPrice)

수정 이력:
  2026-03-19  최초 작성
  2026-03-23  StockPrice 저장 추가, AnalysisResult 가격 컬럼 제거
  2026-03-24  캐시 로직 추가 — StockPrice 데이터 충분 시 KIS 가격 API 0번 호출
──────────────────────────────────────────────────────
"""

import sys
import os
from typing import Optional

from sqlalchemy.orm import Session

from api.config import settings
from api.models.stock import AnalysisResult, StockPrice

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


def _find_cache_dates(db: Session, start: str, end: str,
                      min_stocks: int = 2000) -> tuple[str | None, str | None]:
    """start/end 날짜 근방에서 StockPrice 데이터가 충분한 실제 매매일 탐색

    Args:
        db:         DB 세션
        start:      요청 시작일 (YYYYMMDD)
        end:        요청 종료일 (YYYYMMDD)
        min_stocks: 유효 날짜 판정 최소 종목 수 (기본 2000)

    Returns:
        (actual_start, actual_end) — 유효 날짜 쌍.
        충분한 데이터 없으면 (None, None).
    """
    from sqlalchemy import func

    # start 이후 첫 번째 충분한 데이터 날짜 (공휴일 자동 스킵)
    row_s = (
        db.query(StockPrice.date)
        .group_by(StockPrice.date)
        .having(func.count(StockPrice.code) >= min_stocks)
        .filter(StockPrice.date >= start)
        .order_by(StockPrice.date)
        .first()
    )

    # end 이전 마지막 충분한 데이터 날짜 (공휴일 자동 스킵)
    row_e = (
        db.query(StockPrice.date)
        .group_by(StockPrice.date)
        .having(func.count(StockPrice.code) >= min_stocks)
        .filter(StockPrice.date <= end)
        .order_by(StockPrice.date.desc())
        .first()
    )

    s = row_s[0] if row_s else None
    e = row_e[0] if row_e else None

    if s and e and s < e:
        return s, e
    return None, None


def _run_from_cache(db: Session,
                    actual_start: str,
                    actual_end: str) -> tuple | None:
    """StockPrice DB에서 수익률 계산 → 재무 API 조회 → Top100 반환

    KIS 가격 API(get_period_price)를 호출하지 않고 DB에 저장된 종가로 수익률 계산.
    재무 데이터(ROE, 영업이익률)는 여전히 KIS 재무 API로 조회.

    Args:
        db:           DB 세션
        actual_start: StockPrice에 존재하는 실제 시작일 (YYYYMMDD)
        actual_end:   StockPrice에 존재하는 실제 종료일 (YYYYMMDD)

    Returns:
        (combined_df, kospi_df, kosdaq_df) — top100.py와 동일한 포맷.
        실패 시 None.
    """
    import pandas as pd

    # 시작일·종료일 종가 일괄 조회
    start_map: dict[str, tuple[str, int]] = {
        sp.code: (sp.name, sp.close_price)
        for sp in db.query(StockPrice).filter(StockPrice.date == actual_start).all()
    }
    end_map: dict[str, int] = {
        sp.code: sp.close_price
        for sp in db.query(StockPrice).filter(StockPrice.date == actual_end).all()
    }

    common_codes = set(start_map.keys()) & set(end_map.keys())
    if not common_codes:
        return None

    rows = []
    for code in common_codes:
        name, sp = start_map[code]
        ep = end_map[code]
        if sp and ep and sp > 0:
            growth = round((ep - sp) / sp * 100, 2)
            rows.append({
                "종목코드": code,
                "종목명":   name,
                "시작가":   sp,
                "종료가":   ep,
                "수익률(%)": growth,
                # 일평균거래량: StockPrice에 미저장 → 컬럼 제외 (복합점수에서 자동 스킵)
            })

    if not rows:
        return None

    # 종목 마스터 다운로드로 시장 구분 (인증 불필요 — 정적 zip 파일)
    client = _get_kis_client()
    kospi_set  = {s["종목코드"] for s in client.download_stock_list("J")}
    kosdaq_set = {s["종목코드"] for s in client.download_stock_list("Q")}

    for row in rows:
        if row["종목코드"] in kospi_set:
            row["시장"] = "코스피"
        elif row["종목코드"] in kosdaq_set:
            row["시장"] = "코스닥"
        else:
            row["시장"] = None

    # 시장 정보 없는 종목 제외
    rows = [r for r in rows if r["시장"] is not None]
    if not rows:
        return None

    from top100 import (filter_by_financials, calculate_composite_score,
                        FETCH_N, TOP_N)

    df_all = pd.DataFrame(rows)
    df_all["종목코드"] = df_all["종목코드"].astype(str).str.zfill(6)
    df_all.sort_values("수익률(%)", ascending=False, inplace=True)
    df_all.reset_index(drop=True, inplace=True)

    # 시장별 FETCH_N 추출 (재무 필터 손실분 감안)
    combined  = df_all.head(FETCH_N).reset_index(drop=True)
    kospi_df  = df_all[df_all["시장"] == "코스피"].head(FETCH_N).reset_index(drop=True)
    kosdaq_df = df_all[df_all["시장"] == "코스닥"].head(FETCH_N).reset_index(drop=True)

    # 재무 데이터 일괄 조회 (중복 방지: 세 df 합집합)
    all_codes = (set(combined["종목코드"]) | set(kospi_df["종목코드"])
                 | set(kosdaq_df["종목코드"]))
    unique_stocks = [{"종목코드": c, "종목명": ""} for c in all_codes]
    client.add_financial_data(unique_stocks)

    fin_map = {
        s["종목코드"]: {"ROE": s["ROE"], "영업이익률": s["영업이익률"]}
        for s in unique_stocks
    }

    def _merge_fin(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()
        df["ROE"] = df["종목코드"].map(
            lambda c: fin_map.get(c, {}).get("ROE"))
        df["영업이익률"] = df["종목코드"].map(
            lambda c: fin_map.get(c, {}).get("영업이익률"))
        return df

    combined  = calculate_composite_score(
        filter_by_financials(_merge_fin(combined))).head(TOP_N).reset_index(drop=True)
    kospi_df  = calculate_composite_score(
        filter_by_financials(_merge_fin(kospi_df))).head(TOP_N).reset_index(drop=True)
    kosdaq_df = calculate_composite_score(
        filter_by_financials(_merge_fin(kosdaq_df))).head(TOP_N).reset_index(drop=True)

    print(f"[캐시] 통합 {len(combined)}개 / 코스피 {len(kospi_df)}개 / 코스닥 {len(kosdaq_df)}개")
    return combined, kospi_df, kosdaq_df


def _upsert_stock_prices(db: Session, rows: list[dict],
                         start: str, end: str) -> None:
    """시작일·종료일 종가를 StockPrice 테이블에 저장 (이미 있으면 skip)

    Args:
        db:    DB 세션
        rows:  [{"code", "name", "start_price", "end_price"}, ...]
        start: YYYYMMDD (시작일)
        end:   YYYYMMDD (종료일)
    """
    # 이미 저장된 (code, date) 쌍 조회
    codes = [r["code"] for r in rows]
    existing = {
        (sp.code, sp.date)
        for sp in db.query(StockPrice.code, StockPrice.date)
                    .filter(StockPrice.code.in_(codes),
                            StockPrice.date.in_([start, end]))
                    .all()
    }

    new_prices = []
    for row in rows:
        if (row["code"], start) not in existing:
            new_prices.append(StockPrice(
                code=row["code"], name=row["name"],
                date=start, close_price=row["start_price"],
            ))
        if (row["code"], end) not in existing:
            new_prices.append(StockPrice(
                code=row["code"], name=row["name"],
                date=end, close_price=row["end_price"],
            ))

    if new_prices:
        db.add_all(new_prices)


def _upsert_results(db: Session, rows: list[dict], market: str,
                    start: str, end: str) -> int:
    """분석 결과를 DB에 upsert (같은 기간+시장 → 삭제 후 재삽입)

    Args:
        db:     DB 세션
        rows:   [{"rank": int, "code": str, "name": str, ...}, ...]
        market: "통합" | "코스피" | "코스닥"
        start:  YYYYMMDD
        end:    YYYYMMDD

    Returns:
        저장된 레코드 수
    """
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
            growth_rate=row["growth_rate"],
            roe=row.get("roe"),
            op_margin=row.get("op_margin"),
            score=row.get("score"),
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
            "score":       float(row_dict["종합점수"]) if row_dict.get("종합점수") is not None else None,
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

    from top100 import find_reentry_stocks, load_prev_combined
    from report import create_excel_report

    # ── 캐시 체크: StockPrice에 충분한 데이터가 있으면 KIS 가격 API 스킵 ──
    actual_start, actual_end = _find_cache_dates(db, start, end)
    combined_df = kospi_df = kosdaq_df = None
    used_cache = False

    if actual_start and actual_end:
        print(f"[캐시 모드] StockPrice DB 활용 "
              f"(요청: {start}~{end} → 실제: {actual_start}~{actual_end})")
        try:
            result = _run_from_cache(db, actual_start, actual_end)
            if result is not None:
                combined_df, kospi_df, kosdaq_df = result
                used_cache = True
        except Exception as e:
            print(f"[캐시 실패] {e} — KIS API 모드로 전환")

    if not used_cache:
        # 캐시 없거나 실패 → KIS API 직접 호출
        print(f"[API 모드] KIS API 호출 ({start}~{end})")
        client = _get_kis_client()
        from top100 import get_combined_top100
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
        # 종가 원본 저장 (중복 skip) — 분석 결과보다 먼저 저장
        # 캐시 모드: StockPrice에 이미 전 종목 데이터 있음 → 스킵
        if market == "통합" and not used_cache:
            _upsert_stock_prices(db, rows, start, end)
        total_saved += _upsert_results(db, rows, market, start, end)

    db.commit()
    return {
        "saved":      total_saved,
        "markets":    ["통합", "코스피", "코스닥"],
        "excel_path": excel_path,  # 웹 리포트 목록에서 바로 확인 가능
    }
