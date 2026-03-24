"""
[top100.py] 코스피/코스닥 수익률 Top100 추출 메인 로직
──────────────────────────────────────────────────────
역할:
  - 코스피/코스닥 전 종목 수익률 계산 → Top100 추출
  - 재무 필터 적용 (ROE_THRESHOLD, OP_MARGIN_THRESHOLD)
  - 재진입 종목 포착 (이전 기간 CSV 비교)
  - 결과 CSV 저장 (data/combined_top100_YYYYMMDD_YYYYMMDD.csv)

주요 함수:
  get_top100(client, start, end, market_code, limit)
      → 단일 시장 Top100 DataFrame
  get_combined_top100(client, start, end, limit)
      → (통합, 코스피, 코스닥) 세 DataFrame 반환
  filter_by_financials(df)
      → ROE/영업이익률 기준 필터링 (Phase 1-3에서 실제 데이터 연동)
  find_reentry_stocks(prev_df, curr_df)
      → 재진입 종목 DataFrame
  save_combined_csv(df, start, end) → CSV 경로 반환

필터 기준값 (이 파일 상단 변수로 관리):
  ROE_THRESHOLD = 0        # 미만 종목 제외 (0=필터 없음)
  OP_MARGIN_THRESHOLD = 0  # 미만 종목 제외
  REENTRY_PREV_RANK = 50   # 이 순위 초과였던 종목만 재진입 대상

의존성: pandas, python-dotenv, kis_api.py
환경변수: KIS_APP_KEY, KIS_APP_SECRET (.env)

실행 예:
  python top100.py 20260101 20260131
  python top100.py 20260101 20260131 --limit 10   # 테스트

수정 이력:
  2026-03-19  최초 작성 — stock-scanner/main.py 로직 모듈화
  2026-03-19  Phase 1-2: get_combined_top100()에 재무 데이터 연동 추가
  2026-03-19  get_watchlist_performance() 추가 — 관심종목 기간 수익률 조회
              scheduler/jobs.py report_job()에서 호출 → 엑셀 관심종목 시트 연결
  2026-03-23  FETCH_N 300→500, calculate_composite_score() 추가
              수익률60%+ROE25%+영업이익률15% 백분위 가중합산 → 복합점수 Top100 정렬
              엑셀은 수익률 순 유지, 웹 분석 결과만 복합점수 순
  2026-03-24  거래량 지표 추가 — get_period_price() 일평균거래량 반환
              가중치: 수익률55%+ROE20%+영업이익률15%+일평균거래량10%
──────────────────────────────────────────────────────
"""

import os
import sys
import glob
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

# 프로젝트 루트의 .env 로드
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from kis_api import KISClient
from report import create_excel_report

# ── 필터 기준값 (상단 변수로 관리) ─────────────────────────
ROE_THRESHOLD = 0           # ROE 이 값 미만 종목 제외 (0이면 필터 없음)
OP_MARGIN_THRESHOLD = 0     # 영업이익률 이 값 미만 종목 제외
REENTRY_PREV_RANK = 50      # 재진입: 이전달 이 순위 초과였던 종목만

TOP_N = 100                 # 최종 출력 종목 수
FETCH_N = 500               # 복합 점수 산정 범위 (수익률 기준 상위 500 → 재무조회 → 점수 정렬)
MAX_WORKERS = 5             # 병렬 API 호출 스레드 수

# ── 복합 점수 가중치 ────────────────────────────────────────
SCORE_WEIGHTS = {
    "수익률(%)":    0.55,  # 모멘텀 (핵심 지표)
    "ROE":          0.20,  # 자본 효율성
    "영업이익률":   0.15,  # 사업 안정성
    "일평균거래량": 0.10,  # 시장 관심도 (유동성)
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


# ── 수익률 계산 ────────────────────────────────────────────

def fetch_growth_rates(client: KISClient,
                       stocks: list[dict],
                       start_date: str,
                       end_date: str,
                       market: str) -> list[dict]:
    """종목 리스트의 기간 수익률을 병렬 조회

    Args:
        client: KISClient 인스턴스
        stocks: [{"종목코드": ..., "종목명": ...}, ...]
        start_date: 시작일 (YYYYMMDD)
        end_date:   종료일 (YYYYMMDD)
        market:     "코스피" 또는 "코스닥"

    Returns:
        [{"종목코드", "종목명", "시장", "시작가", "종료가", "수익률(%)"}, ...]
    """
    import time

    results = []
    lock = threading.Lock()
    total = len(stocks)
    completed = [0]

    def _fetch_one(stock: dict) -> Optional[dict]:
        code = stock["종목코드"]
        name = stock["종목명"]
        time.sleep(0.05)  # API 부하 분산

        try:
            start_price, end_price, avg_volume = client.get_period_price(
                code, start_date, end_date)

            with lock:
                completed[0] += 1
                idx = completed[0]

            if start_price is None or end_price is None or start_price == 0:
                return None

            growth = round(
                (end_price - start_price) / start_price * 100, 2)

            if idx % 200 == 0 or idx == total:
                print(f"  [{idx}/{total}] {market} 진행 중...")

            return {
                "종목코드":    code,
                "종목명":      name,
                "시장":        market,
                "시작가":      start_price,
                "종료가":      end_price,
                "수익률(%)":   growth,
                "일평균거래량": avg_volume,
            }
        except Exception as e:
            with lock:
                completed[0] += 1
            print(f"  [{completed[0]}/{total}] {name}({code}) 오류: {e}")
            return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(_fetch_one, s) for s in stocks]
        for f in as_completed(futures):
            result = f.result()
            if result is not None:
                results.append(result)

    return results


# ── Top100 추출 ────────────────────────────────────────────

def get_top100(client: KISClient,
               start_date: str,
               end_date: str,
               market_code: str = "J",
               limit: Optional[int] = None) -> pd.DataFrame:
    """단일 시장 수익률 Top100 추출

    Args:
        client:      KISClient 인스턴스
        start_date:  분석 시작일 (YYYYMMDD)
        end_date:    분석 종료일 (YYYYMMDD)
        market_code: "J" (코스피) 또는 "Q" (코스닥)
        limit:       테스트용 종목 수 제한 (None=전체)

    Returns:
        수익률 내림차순 정렬된 Top100 DataFrame
        컬럼: 종목코드 | 종목명 | 시장 | 시작가 | 종료가 | 수익률(%)
    """
    market = "코스피" if market_code == "J" else "코스닥"
    print(f"\n[{market} Top{TOP_N}] {start_date} ~ {end_date} 분석 시작")

    client.get_access_token()
    stocks = client.download_stock_list(market_code)

    if limit is not None:
        stocks = stocks[:limit]
        print(f"  [테스트 모드] {limit}개 종목만 분석")

    results = fetch_growth_rates(client, stocks, start_date, end_date, market)

    if not results:
        print(f"  [{market}] 수익률 계산 가능한 종목 없음")
        return pd.DataFrame()

    # 수익률 내림차순 정렬 후 FETCH_N 추출 (재무필터 손실분 감안)
    results.sort(key=lambda x: x["수익률(%)"], reverse=True)
    top = results[:FETCH_N]

    df = pd.DataFrame(top)
    df["종목코드"] = df["종목코드"].astype(str).str.zfill(6)
    print(f"  [{market}] 전체 {len(results):,}개 → 상위{FETCH_N} 추출 완료")
    return df


def get_combined_top100(client: KISClient,
                        start_date: str,
                        end_date: str,
                        limit: Optional[int] = None) -> tuple[
                            pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """코스피+코스닥 통합 Top100 및 각 시장 Top100 추출 (재무 데이터 포함)

    흐름:
      1) 코스피/코스닥 각각 수익률 Top100 추출
      2) 세 DataFrame의 고유 종목코드에 대해 재무 데이터 일괄 조회
      3) 각 DataFrame에 ROE/영업이익률 병합
      4) 재무 필터(ROE_THRESHOLD, OP_MARGIN_THRESHOLD) 적용

    Args:
        client:     KISClient 인스턴스
        start_date: 분석 시작일
        end_date:   분석 종료일
        limit:      테스트용 시장별 종목 수 제한

    Returns:
        (통합_top100, 코스피_top100, 코스닥_top100) — 재무 데이터 포함 DataFrame
    """
    kospi_df = get_top100(client, start_date, end_date, "J", limit)
    kosdaq_df = get_top100(client, start_date, end_date, "Q", limit)

    # 통합: 두 시장 합산 후 수익률 내림차순 Top100
    frames = [df for df in [kospi_df, kosdaq_df] if not df.empty]
    if not frames:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined.sort_values("수익률(%)", ascending=False, inplace=True)
    combined = combined.head(FETCH_N).reset_index(drop=True)  # 필터 전 FETCH_N 유지

    # ── 재무 데이터 일괄 조회 (중복 API 호출 방지) ──────────
    # 세 df의 고유 종목 추출 → 한 번만 조회
    all_codes: set = set()
    for df in [combined, kospi_df, kosdaq_df]:
        if not df.empty:
            all_codes.update(df["종목코드"].tolist())

    unique_stocks = [{"종목코드": c, "종목명": ""} for c in all_codes]
    client.add_financial_data(unique_stocks)

    # 종목코드 → 재무 딕셔너리
    fin_map: dict = {
        s["종목코드"]: {"ROE": s["ROE"], "영업이익률": s["영업이익률"]}
        for s in unique_stocks
    }

    def _merge_fin(df: pd.DataFrame) -> pd.DataFrame:
        """DataFrame에 ROE/영업이익률 컬럼 추가"""
        if df.empty:
            return df
        df = df.copy()
        df["ROE"] = df["종목코드"].map(
            lambda c: fin_map.get(c, {}).get("ROE"))
        df["영업이익률"] = df["종목코드"].map(
            lambda c: fin_map.get(c, {}).get("영업이익률"))
        return df

    combined = _merge_fin(combined)
    kospi_df = _merge_fin(kospi_df)
    kosdaq_df = _merge_fin(kosdaq_df)

    # ── 재무 필터 → 복합 점수 정렬 → TOP_N 최종 컷 ──────────
    # 1) 마이너스 필터 (ROE_THRESHOLD, OP_MARGIN_THRESHOLD 기준)
    # 2) 풀 내 백분위 기반 복합 점수 산정 (수익률60 + ROE25 + OPM15)
    # 3) 복합 점수 내림차순 Top100 추출
    combined  = calculate_composite_score(
        filter_by_financials(combined)).head(TOP_N).reset_index(drop=True)
    kospi_df  = calculate_composite_score(
        filter_by_financials(kospi_df)).head(TOP_N).reset_index(drop=True)
    kosdaq_df = calculate_composite_score(
        filter_by_financials(kosdaq_df)).head(TOP_N).reset_index(drop=True)

    print(f"  [통합] 복합점수 Top{len(combined)} / "
          f"[코스피] {len(kospi_df)}개 / [코스닥] {len(kosdaq_df)}개")

    return combined, kospi_df, kosdaq_df


# ── 재무 필터 ──────────────────────────────────────────────

def filter_by_financials(df: pd.DataFrame) -> pd.DataFrame:
    """ROE/영업이익률 기준으로 종목 필터링

    ROE_THRESHOLD, OP_MARGIN_THRESHOLD 기준 미만 종목 제외.
    값이 None인 종목은 데이터 없음으로 간주하여 유지.

    Args:
        df: ROE, 영업이익률 컬럼이 포함된 DataFrame

    Returns:
        필터 통과 종목 DataFrame
    """
    if "ROE" not in df.columns or "영업이익률" not in df.columns:
        return df

    before = len(df)
    mask = (
        df["ROE"].isna() | (df["ROE"] >= ROE_THRESHOLD)
    ) & (
        df["영업이익률"].isna() | (df["영업이익률"] >= OP_MARGIN_THRESHOLD)
    )
    filtered = df[mask].copy()
    after = len(filtered)
    print(f"[재무 필터] {before}개 → {after}개 "
          f"(ROE<{ROE_THRESHOLD} 또는 OPM<{OP_MARGIN_THRESHOLD} 제외)")
    return filtered.reset_index(drop=True)


# ── 복합 점수 산정 ─────────────────────────────────────────

def calculate_composite_score(df: pd.DataFrame) -> pd.DataFrame:
    """수익률·ROE·영업이익률 백분위 가중합산으로 종합점수 계산

    각 지표를 그룹 내 백분위(0~100)로 정규화 후 SCORE_WEIGHTS로 가중합산.
    None/NaN은 중앙값으로 대체 (데이터 없음 = 중립 처리).

    Args:
        df: 수익률(%), ROE, 영업이익률 컬럼이 포함된 DataFrame

    Returns:
        종합점수 컬럼 추가 + 종합점수 내림차순 정렬된 DataFrame
    """
    df = df.copy()
    score = pd.Series(0.0, index=df.index)

    for col, weight in SCORE_WEIGHTS.items():
        if col not in df.columns:
            continue
        series = df[col].copy().astype(float)
        # None/NaN → 중앙값으로 대체 (데이터 미수집 종목에 패널티 없이 중립)
        series = series.fillna(series.median())
        # 백분위 변환 (0~100, 높을수록 좋음)
        pct = series.rank(pct=True, method="average") * 100
        score += pct * weight

    df["종합점수"] = score.round(2)
    df.sort_values("종합점수", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ── 재진입 포착 ────────────────────────────────────────────

def find_reentry_stocks(prev_df: pd.DataFrame,
                        curr_df: pd.DataFrame) -> pd.DataFrame:
    """이전 기간 하위 그룹 → 이번 기간 Top100 재진입 종목 탐색

    이전 기간에서 REENTRY_PREV_RANK 순위 초과(하위 그룹)였다가
    현재 기간 Top100에 재진입한 종목을 반환합니다.

    Args:
        prev_df: 이전 기간 Top100 (수익률 내림차순 정렬)
        curr_df: 현재 기간 Top100 (수익률 내림차순 정렬)

    Returns:
        재진입 종목 DataFrame (없으면 빈 DataFrame)
    """
    if prev_df.empty or len(prev_df) <= REENTRY_PREV_RANK:
        print(f"[재진입] 이전 데이터가 {REENTRY_PREV_RANK}개 이하 — 분석 불가")
        return pd.DataFrame()

    # 이전 기간 하위 그룹: REENTRY_PREV_RANK+1위 ~ 100위
    prev_lower = prev_df.iloc[REENTRY_PREV_RANK:TOP_N].copy()
    prev_lower["이전_순위"] = range(
        REENTRY_PREV_RANK + 1,
        REENTRY_PREV_RANK + 1 + len(prev_lower))

    curr = curr_df.copy()
    curr["현재_순위"] = range(1, len(curr) + 1)

    # 교집합 코드
    reentry_codes = set(prev_lower["종목코드"]) & set(curr["종목코드"])

    if not reentry_codes:
        print("[재진입] 해당 종목 없음")
        return pd.DataFrame()

    rows = []
    for code in reentry_codes:
        prev_row = prev_lower[prev_lower["종목코드"] == code].iloc[0]
        curr_row = curr[curr["종목코드"] == code].iloc[0]

        row = {
            "종목코드": code,
            "종목명": curr_row["종목명"],
            "이전_순위": int(prev_row["이전_순위"]),
            "이전_수익률(%)": prev_row["수익률(%)"],
            "현재_순위": int(curr_row["현재_순위"]),
            "현재_수익률(%)": curr_row["수익률(%)"],
        }
        # 재무 데이터가 있으면 포함
        if "ROE" in curr_row:
            row["ROE"] = curr_row["ROE"]
        if "영업이익률" in curr_row:
            row["영업이익률"] = curr_row["영업이익률"]
        rows.append(row)

    result = pd.DataFrame(rows)
    result.sort_values("현재_순위", inplace=True)
    result.reset_index(drop=True, inplace=True)
    print(f"[재진입] {len(result)}개 종목 발견")
    return result


# ── 이전 데이터 로드 ───────────────────────────────────────

def load_prev_combined(current_file: str = None) -> pd.DataFrame:
    """data/ 폴더에서 가장 최근 통합 Top100 CSV 로드

    Args:
        current_file: 현재 분석 파일 경로 (제외 대상)

    Returns:
        이전 분석 DataFrame (없으면 빈 DataFrame)
    """
    pattern = os.path.join(DATA_DIR, "combined_top100_*.csv")
    files = sorted(glob.glob(pattern))

    if current_file:
        current_abs = os.path.abspath(current_file)
        files = [f for f in files if os.path.abspath(f) != current_abs]

    if not files:
        return pd.DataFrame()

    prev_file = files[-1]
    print(f"[이전 데이터] {prev_file}")
    return pd.read_csv(prev_file, dtype={"종목코드": str})


# ── 관심종목 수익률 조회 ───────────────────────────────────────

def get_watchlist_performance(client: KISClient,
                              start_date: str,
                              end_date: str) -> pd.DataFrame:
    """관심종목(watchlist.json) 기간 수익률 + 재무 데이터 조회

    Args:
        client:     KISClient 인스턴스
        start_date: 분석 시작일 (YYYYMMDD)
        end_date:   분석 종료일 (YYYYMMDD)

    Returns:
        DataFrame(종목코드, 종목명, 시작가, 종료가, 수익률(%), ROE, 영업이익률)
        관심종목 없거나 조회 실패 시 빈 DataFrame
    """
    import json
    import time

    watchlist_path = os.path.join(DATA_DIR, "..", "data", "watchlist.json")
    try:
        with open(watchlist_path, "r", encoding="utf-8") as f:
            watchlist = json.load(f).get("watchlist", [])
    except Exception:
        return pd.DataFrame()

    if not watchlist:
        return pd.DataFrame()

    print(f"\n[관심종목] {len(watchlist)}개 수익률 조회 중...")
    client.get_access_token()

    rows = []
    for stock in watchlist:
        code = stock["종목코드"]
        name = stock["종목명"]
        time.sleep(0.05)
        try:
            start_price, end_price, avg_volume = client.get_period_price(
                code, start_date, end_date)
            if start_price is None or end_price is None or start_price == 0:
                print(f"  {name}({code}): 시세 데이터 없음")
                continue
            growth = round((end_price - start_price) / start_price * 100, 2)
            rows.append({
                "종목코드":    code,
                "종목명":      name,
                "시작가":      start_price,
                "종료가":      end_price,
                "수익률(%)":   growth,
                "일평균거래량": avg_volume,
            })
        except Exception as e:
            print(f"  {name}({code}) 오류: {e}")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["종목코드"] = df["종목코드"].astype(str).str.zfill(6)

    # 재무 데이터 추가
    records = df.to_dict("records")
    client.add_financial_data(records)
    df["ROE"] = [r["ROE"] for r in records]
    df["영업이익률"] = [r["영업이익률"] for r in records]

    df.sort_values("수익률(%)", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    print(f"[관심종목] {len(df)}개 조회 완료")
    return df


# ── CSV 저장 ───────────────────────────────────────────────

def save_combined_csv(df: pd.DataFrame,
                      start_date: str, end_date: str) -> str:
    """통합 Top100 결과를 CSV로 저장

    Returns:
        저장된 파일 경로
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    filename = f"combined_top100_{start_date}_{end_date}.csv"
    filepath = os.path.join(DATA_DIR, filename)
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"[CSV 저장] {filepath} ({len(df)}건)")
    return filepath


# ── 메인 실행 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="코스피/코스닥 수익률 Top100 분석")
    parser.add_argument("start_date", help="시작일 (YYYYMMDD)")
    parser.add_argument("end_date", help="종료일 (YYYYMMDD)")
    parser.add_argument("--limit", type=int, default=None,
                        help="테스트용: 시장별 종목 수 제한")
    args = parser.parse_args()

    # KIS API 키 확인
    app_key = os.environ.get("KIS_APP_KEY", "")
    app_secret = os.environ.get("KIS_APP_SECRET", "")
    if not app_key or not app_secret:
        print("오류: .env 파일에 KIS_APP_KEY, KIS_APP_SECRET을 설정해 주세요.")
        sys.exit(1)

    client = KISClient(app_key=app_key, app_secret=app_secret)

    try:
        # Top100 추출 (재무 데이터 포함, 필터 적용)
        combined_df, kospi_df, kosdaq_df = get_combined_top100(
            client, args.start_date, args.end_date, args.limit)

        if combined_df.empty:
            print("분석 결과 없음")
            sys.exit(1)

        # 이전 데이터 로드 → 재진입 분석
        csv_path = save_combined_csv(
            combined_df, args.start_date, args.end_date)
        prev_df = load_prev_combined(current_file=csv_path)

        reentry_df = pd.DataFrame()
        if not prev_df.empty:
            reentry_df = find_reentry_stocks(prev_df, combined_df)

        # 엑셀 리포트 생성
        excel_path = create_excel_report(
            combined_df, kospi_df, kosdaq_df, reentry_df,
            args.start_date, args.end_date)

        # 결과 출력 (터미널 요약)
        print(f"\n{'='*50}")
        print(f"통합 Top{TOP_N} ({args.start_date}~{args.end_date})")
        print(f"{'='*50}")
        print(combined_df[["종목코드", "종목명", "시장",
                            "수익률(%)"]].head(10).to_string(index=False))

        if not reentry_df.empty:
            print(f"\n재진입 포착: {len(reentry_df)}개")
            print(reentry_df[["종목코드", "종목명",
                               "이전_순위", "현재_순위",
                               "현재_수익률(%)"]].to_string(index=False))

        print(f"\n[완료] CSV  : {csv_path}")
        print(f"[완료] Excel: {excel_path}")

    except KeyboardInterrupt:
        print("\n중단됨")
        sys.exit(0)
    except Exception as e:
        print(f"오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
