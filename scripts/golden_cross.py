"""
[golden_cross.py] 관심종목 골든크로스 감지 엔진
──────────────────────────────────────────────────────
역할:
  - KIS API 30분봉 데이터 수집
  - MA3/MA5 골든크로스 신호 판단
  - 관심종목(data/watchlist.json) 일괄 스캔
  - 신호 발생 종목 결과 반환 (notifier.py에서 알림 발송)

주요 함수:
  load_watchlist()
      → data/watchlist.json 에서 관심종목 리스트 반환
  save_watchlist(watchlist)
      → 관심종목 리스트를 JSON에 저장
  add_to_watchlist(code, name)
      → 관심종목 추가 (중복 방지)
  remove_from_watchlist(code)
      → 관심종목 삭제

  fetch_minute_ohlcv(client, code, interval, candles)
      → 분봉 OHLCV DataFrame 반환

  check_golden_cross(df)
      → {"signal": bool, "datetime", "close", "ma3", "ma5", "reason"}

  scan_watchlist(client)
      → 관심종목 전체 스캔 → 신호 발생 종목 리스트 반환

골든크로스 조건:
  이전 캔들: MA3 <= MA5
  현재 캔들: MA3 > MA5 (상향 돌파)

설정값:
  MINUTE_INTERVAL = "30"   # 30분봉
  MINUTE_CANDLES  = 30     # 수집 캔들 수

의존성: pandas, kis_api.py
환경변수: KIS_APP_KEY, KIS_APP_SECRET (.env)

실행 예:
  python golden_cross.py                  # 관심종목 전체 스캔
  python golden_cross.py --add 005930 삼성전자
  python golden_cross.py --remove 005930

수정 이력:
  2026-03-19  최초 작성 — Phase 3
              stock-scanner/analysis_engine.py 기반 재구성
              관심종목 관리(CRUD) 및 스캔 로직 통합
──────────────────────────────────────────────────────
"""

import os
import sys
import json
import argparse
import time

import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from kis_api import KISClient

# ── 설정값 ────────────────────────────────────────────────
MINUTE_INTERVAL = "30"   # 분봉 간격 (KIS API: "1","5","10","15","30","60")
MINUTE_CANDLES  = 30     # 수집할 캔들 수 (MA5 계산에 최소 6개 필요)

WATCHLIST_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "watchlist.json")


# ── 관심종목 관리 ──────────────────────────────────────────

def load_watchlist() -> list[dict]:
    """data/watchlist.json 에서 관심종목 로드

    Returns:
        [{"종목코드": "005930", "종목명": "삼성전자"}, ...]
    """
    try:
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("watchlist", [])
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[관심종목] 로드 오류: {e}")
        return []


def save_watchlist(watchlist: list[dict]) -> None:
    """관심종목 리스트를 data/watchlist.json 에 저장

    Args:
        watchlist: [{"종목코드": ..., "종목명": ...}, ...]
    """
    os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)
    try:
        with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
            json.dump({"watchlist": watchlist}, f,
                      ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[관심종목] 저장 오류: {e}")


def add_to_watchlist(code: str, name: str) -> bool:
    """관심종목 추가

    Args:
        code: 6자리 종목코드
        name: 종목명

    Returns:
        True=추가됨, False=이미 존재
    """
    watchlist = load_watchlist()
    codes = {s["종목코드"] for s in watchlist}
    if code in codes:
        print(f"[관심종목] {name}({code}) 이미 등록됨")
        return False
    watchlist.append({"종목코드": code, "종목명": name})
    save_watchlist(watchlist)
    print(f"[관심종목] {name}({code}) 추가 완료")
    return True


def remove_from_watchlist(code: str) -> bool:
    """관심종목 삭제

    Args:
        code: 6자리 종목코드

    Returns:
        True=삭제됨, False=미존재
    """
    watchlist = load_watchlist()
    before = len(watchlist)
    watchlist = [s for s in watchlist if s["종목코드"] != code]
    if len(watchlist) == before:
        print(f"[관심종목] {code} 등록 내역 없음")
        return False
    save_watchlist(watchlist)
    print(f"[관심종목] {code} 삭제 완료")
    return True


# ── 분봉 데이터 수집 ───────────────────────────────────────

def fetch_minute_ohlcv(client: KISClient,
                       stock_code: str,
                       interval: str = MINUTE_INTERVAL,
                       candles: int = MINUTE_CANDLES) -> pd.DataFrame:
    """KIS API로 분봉 OHLCV 수집

    Args:
        client:     KISClient 인스턴스
        stock_code: 종목코드
        interval:   분봉 간격 ("30" 기본)
        candles:    수집할 캔들 수

    Returns:
        DataFrame(datetime, open, high, low, close, volume) 오래된 순 정렬
        실패 시 빈 DataFrame
    """
    client.get_access_token()

    try:
        records = client.get_minute_ohlcv(
            stock_code, end_time="153000", minute_interval=interval)
    except Exception as e:
        print(f"  [분봉 오류] {stock_code}: {e}")
        return pd.DataFrame()

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df = df.rename(columns={
        "stck_cntg_hour": "datetime",
        "stck_oprc": "open",
        "stck_hgpr": "high",
        "stck_lwpr": "low",
        "stck_prpr": "close",
        "cntg_vol": "volume",
    })

    # 숫자 변환
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 중복 제거, 오래된 순 정렬
    df = df.drop_duplicates(subset="datetime")
    df = df.sort_values("datetime").reset_index(drop=True)

    # 필요한 캔들 수만큼 자르기
    if len(df) > candles:
        df = df.tail(candles).reset_index(drop=True)

    return df


# ── 골든크로스 판단 ────────────────────────────────────────

def check_golden_cross(df: pd.DataFrame) -> dict:
    """MA3/MA5 골든크로스 신호 판단

    조건:
      이전 캔들: MA3 <= MA5
      현재 캔들: MA3 > MA5  (상향 돌파 = 골든크로스)

    Args:
        df: fetch_minute_ohlcv() 반환 DataFrame

    Returns:
        {
          "signal"  : bool,
          "datetime": str | None,   # 신호 발생 시각 (HHMMSS)
          "close"   : float | None, # 현재 종가
          "ma3"     : float | None,
          "ma5"     : float | None,
          "reason"  : str,          # 신호 발생/미발생 이유
        }
    """
    result = {
        "signal": False,
        "datetime": None,
        "close": None,
        "ma3": None,
        "ma5": None,
        "reason": "",
    }

    if df.empty or len(df) < 6:
        result["reason"] = "데이터 부족 (최소 6개 캔들 필요)"
        return result

    df = df.copy()
    df["ma3"] = df["close"].rolling(window=3).mean()
    df["ma5"] = df["close"].rolling(window=5).mean()

    latest = df.iloc[-1]
    prev   = df.iloc[-2]

    result["datetime"] = latest["datetime"]
    result["close"] = float(latest["close"])
    result["ma3"] = (round(float(latest["ma3"]), 2)
                     if pd.notna(latest["ma3"]) else None)
    result["ma5"] = (round(float(latest["ma5"]), 2)
                     if pd.notna(latest["ma5"]) else None)

    if pd.isna(latest["ma3"]) or pd.isna(latest["ma5"]):
        result["reason"] = "이동평균 계산 불가 (데이터 부족)"
        return result

    if pd.isna(prev["ma3"]) or pd.isna(prev["ma5"]):
        result["reason"] = "이전 캔들 이동평균 계산 불가"
        return result

    prev_below = prev["ma3"] <= prev["ma5"]
    curr_above = latest["ma3"] > latest["ma5"]

    if prev_below and curr_above:
        result["signal"] = True
        result["reason"] = "MA3이 MA5를 상향 돌파 (골든크로스)"
    elif not prev_below:
        result["reason"] = "이전 캔들에서 이미 MA3 > MA5 (신호 아님)"
    else:
        result["reason"] = "MA3이 아직 MA5 하회 중"

    return result


# ── 관심종목 일괄 스캔 ─────────────────────────────────────

def scan_watchlist(client: KISClient) -> list[dict]:
    """관심종목 전체 골든크로스 스캔

    Args:
        client: KISClient 인스턴스

    Returns:
        신호 발생 종목 결과 리스트:
        [{"종목코드", "종목명", "signal", "datetime",
          "close", "ma3", "ma5", "reason"}, ...]
        (signal=True 인 항목만 포함)
    """
    watchlist = load_watchlist()
    if not watchlist:
        print("[스캔] 관심종목 없음. --add 종목코드 종목명 으로 추가하세요.")
        return []

    print(f"[스캔] 관심종목 {len(watchlist)}개 스캔 시작 "
          f"({MINUTE_INTERVAL}분봉 MA3/MA5)")

    signals = []

    for stock in watchlist:
        code = stock["종목코드"]
        name = stock["종목명"]
        time.sleep(0.1)  # API 호출 간격

        try:
            df = fetch_minute_ohlcv(client, code)

            if df.empty:
                print(f"  {name}({code}): 데이터 없음")
                continue

            result = check_golden_cross(df)
            status = "🚨 신호" if result["signal"] else "  -"
            print(f"  {status} {name}({code}): {result['reason']}")

            if result["signal"]:
                signals.append({
                    "종목코드": code,
                    "종목명": name,
                    **result,
                })

        except Exception as e:
            print(f"  {name}({code}) 오류: {e}")
            continue

    print(f"\n[스캔 완료] {len(watchlist)}개 종목 중 "
          f"{len(signals)}개 골든크로스 신호")
    return signals


# ── 메인 실행 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="골든크로스 스캔 / 관심종목 관리")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--add", nargs=2, metavar=("코드", "종목명"),
                       help="관심종목 추가 (예: --add 005930 삼성전자)")
    group.add_argument("--remove", metavar="코드",
                       help="관심종목 삭제 (예: --remove 005930)")
    group.add_argument("--list", action="store_true",
                       help="관심종목 목록 출력")
    args = parser.parse_args()

    # 관심종목 관리 (API 키 불필요)
    if args.add:
        add_to_watchlist(args.add[0].zfill(6), args.add[1])
        return
    if args.remove:
        remove_from_watchlist(args.remove.zfill(6))
        return
    if args.list:
        watchlist = load_watchlist()
        if not watchlist:
            print("등록된 관심종목 없음")
        else:
            print(f"관심종목 ({len(watchlist)}개):")
            for i, s in enumerate(watchlist, 1):
                print(f"  {i}. {s['종목명']} ({s['종목코드']})")
        return

    # 스캔 실행
    app_key = os.environ.get("KIS_APP_KEY", "")
    app_secret = os.environ.get("KIS_APP_SECRET", "")
    if not app_key or not app_secret:
        print("오류: .env 파일에 KIS_APP_KEY, KIS_APP_SECRET을 설정해 주세요.")
        sys.exit(1)

    client = KISClient(app_key=app_key, app_secret=app_secret)

    try:
        signals = scan_watchlist(client)

        if signals:
            print("\n[골든크로스 신호 종목]")
            for s in signals:
                print(f"  {s['종목명']}({s['종목코드']}) "
                      f"| {s['datetime']} "
                      f"| 종가 {s['close']:,.0f}원 "
                      f"| MA3 {s['ma3']:,.2f} / MA5 {s['ma5']:,.2f}")

    except KeyboardInterrupt:
        print("\n중단됨")
        sys.exit(0)
    except Exception as e:
        print(f"오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
