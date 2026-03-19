"""
[scheduler/jobs.py] APScheduler 자동화 작업 정의
──────────────────────────────────────────────────────
역할:
  - 장중 30분 폴링: 관심종목 골든크로스 스캔 → 텔레그램 즉시 알림
  - 매일 21:00 KST: Top100 분석 → 엑셀 리포트 → 텔레그램 발송
  - 스케줄러 시작/종료 관리

스케줄 구성:
  scan_job()    — 평일 09:00~15:30 KST, 30분 간격 실행
  report_job()  — 매일 21:00 KST 실행 (당월 1일~오늘 기준)

실행 예:
  python scheduler/jobs.py          # 스케줄러 시작 (Ctrl+C로 종료)
  python scheduler/jobs.py --now scan    # 스캔 즉시 1회 실행 (테스트)
  python scheduler/jobs.py --now report  # 리포트 즉시 1회 실행 (테스트)

의존성:
  APScheduler (pip install apscheduler)
  scripts/kis_api.py, golden_cross.py, top100.py, report.py, notifier.py

환경변수: KIS_APP_KEY, KIS_APP_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

수정 이력:
  2026-03-19  최초 작성 — Phase 5
              BackgroundScheduler + CronTrigger (Asia/Seoul 기준)
              평일 장 시간만 스캔, 주말 자동 제외
  2026-03-19  report_job()에 관심종목 수익률 조회 연결
              get_watchlist_performance() → create_excel_report(watchlist_df)
──────────────────────────────────────────────────────
"""

import os
import sys
import argparse
import datetime

# scripts/ 폴더를 import 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from kis_api import KISClient
from golden_cross import scan_watchlist
from top100 import (get_combined_top100, save_combined_csv,
                    load_prev_combined, find_reentry_stocks,
                    get_watchlist_performance)
from report import create_excel_report
from notifier import send_golden_cross_alert, send_daily_report

# ── 설정 ──────────────────────────────────────────────────
TZ = "Asia/Seoul"

# 스캔 시간대: 평일 09:00~15:30, 30분 간격
SCAN_START_HOUR  = 9
SCAN_END_HOUR    = 15
SCAN_END_MINUTE  = 30
SCAN_INTERVAL    = 30  # 분

# 일일 리포트 시각
REPORT_HOUR   = 21
REPORT_MINUTE = 0

# KIS 클라이언트 (전역 공유 — 토큰 재사용 목적)
_client: KISClient | None = None


def _get_client() -> KISClient:
    """KISClient 싱글턴 반환"""
    global _client
    if _client is None:
        app_key    = os.environ.get("KIS_APP_KEY", "")
        app_secret = os.environ.get("KIS_APP_SECRET", "")
        if not app_key or not app_secret:
            raise RuntimeError(
                ".env에 KIS_APP_KEY, KIS_APP_SECRET을 설정해 주세요.")
        _client = KISClient(app_key=app_key, app_secret=app_secret)
    return _client


# ── 작업 함수 ──────────────────────────────────────────────

def scan_job() -> None:
    """골든크로스 스캔 작업 (30분 간격 실행)

    평일 장 운영 시간(09:00~15:30)에만 실제 스캔을 수행합니다.
    장 외 시간에 트리거되면 조용히 종료합니다.
    """
    now = datetime.datetime.now(
        tz=datetime.timezone(datetime.timedelta(hours=9)))  # KST

    # 주말 제외 (weekday: 0=월 ~ 4=금, 5=토, 6=일)
    if now.weekday() >= 5:
        return

    # 장 운영 시간 외 제외
    market_open  = now.replace(hour=SCAN_START_HOUR, minute=0,
                                second=0, microsecond=0)
    market_close = now.replace(hour=SCAN_END_HOUR, minute=SCAN_END_MINUTE,
                                second=0, microsecond=0)
    if not (market_open <= now <= market_close):
        return

    print(f"\n[스캔 작업] {now.strftime('%Y-%m-%d %H:%M')} KST 시작")

    try:
        client  = _get_client()
        signals = scan_watchlist(client)

        if signals:
            send_golden_cross_alert(signals)
        else:
            print("  신호 없음")

    except Exception as e:
        print(f"[스캔 작업 오류] {e}")


def report_job() -> None:
    """일일 Top100 리포트 작업 (매일 21:00 KST 실행)

    당월 1일 ~ 오늘을 분석 기간으로 자동 설정합니다.
    """
    today = datetime.date.today()
    start_date = today.strftime("%Y%m01")   # 당월 1일
    end_date   = today.strftime("%Y%m%d")   # 오늘

    print(f"\n[리포트 작업] {today} 21:00 KST 시작 "
          f"({start_date}~{end_date})")

    try:
        client = _get_client()

        # Top100 추출 (재무 데이터 포함)
        combined_df, kospi_df, kosdaq_df = get_combined_top100(
            client, start_date, end_date)

        if combined_df.empty:
            print("[리포트 작업] 분석 결과 없음 — 발송 건너뜀")
            return

        # CSV 저장 + 재진입 분석
        csv_path = save_combined_csv(combined_df, start_date, end_date)
        prev_df  = load_prev_combined(current_file=csv_path)
        reentry_df = find_reentry_stocks(prev_df, combined_df) \
            if not prev_df.empty else __import__("pandas").DataFrame()

        # 관심종목 수익률 조회
        watchlist_df = get_watchlist_performance(client, start_date, end_date)

        # 엑셀 리포트 생성 (관심종목 시트 포함)
        excel_path = create_excel_report(
            combined_df, kospi_df, kosdaq_df, reentry_df,
            start_date, end_date,
            watchlist_df=watchlist_df if not watchlist_df.empty else None)

        # 텔레그램 발송
        send_daily_report(
            kospi_df, kosdaq_df, reentry_df,
            excel_path, start_date, end_date)

        print("[리포트 작업] 완료")

    except Exception as e:
        print(f"[리포트 작업 오류] {e}")


# ── 스케줄러 실행 ──────────────────────────────────────────

def start_scheduler() -> None:
    """스케줄러 시작 (Ctrl+C로 종료)"""
    scheduler = BlockingScheduler(timezone=TZ)

    # 30분 간격 스캔 (매 시각 :00, :30)
    scheduler.add_job(
        scan_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=f"{SCAN_START_HOUR}-{SCAN_END_HOUR}",
            minute=f"0/{SCAN_INTERVAL}",
            timezone=TZ,
        ),
        id="scan_job",
        name="골든크로스 스캔",
        misfire_grace_time=60,   # 1분 내 지연 허용
    )

    # 매일 21:00 리포트
    scheduler.add_job(
        report_job,
        trigger=CronTrigger(
            hour=REPORT_HOUR,
            minute=REPORT_MINUTE,
            timezone=TZ,
        ),
        id="report_job",
        name="일일 리포트",
        misfire_grace_time=300,  # 5분 내 지연 허용
    )

    print("=" * 50)
    print("스케줄러 시작")
    print(f"  골든크로스 스캔: 평일 {SCAN_START_HOUR:02d}:00~"
          f"{SCAN_END_HOUR:02d}:{SCAN_END_MINUTE:02d}, "
          f"{SCAN_INTERVAL}분 간격")
    print(f"  일일 리포트:     매일 {REPORT_HOUR:02d}:{REPORT_MINUTE:02d} KST")
    print("  Ctrl+C로 종료")
    print("=" * 50)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\n스케줄러 종료")
        scheduler.shutdown()


# ── 메인 ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="APScheduler 자동화")
    parser.add_argument(
        "--now",
        choices=["scan", "report"],
        help="즉시 1회 실행 (테스트용): scan | report",
    )
    args = parser.parse_args()

    # 환경변수 확인
    if not os.environ.get("KIS_APP_KEY"):
        print("오류: .env에 KIS_APP_KEY, KIS_APP_SECRET을 설정해 주세요.")
        sys.exit(1)

    if args.now == "scan":
        print("[즉시 실행] 골든크로스 스캔")
        # 장 시간 제한 우회하여 바로 실행
        client  = _get_client()
        signals = scan_watchlist(client)
        if signals:
            send_golden_cross_alert(signals)
        return

    if args.now == "report":
        print("[즉시 실행] 일일 리포트")
        report_job()
        return

    # 기본: 스케줄러 시작
    start_scheduler()


if __name__ == "__main__":
    main()
