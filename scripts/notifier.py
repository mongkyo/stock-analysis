"""
[notifier.py] 텔레그램 알림 발송 모듈
──────────────────────────────────────────────────────
역할:
  - 텔레그램 Bot API를 통한 메시지/파일 발송
  - 골든크로스 신호 알림 (즉시 발송)
  - 일일 종합 리포트 발송 (텍스트 요약 + 엑셀 첨부)

주요 함수:
  send_message(text)
      → 텍스트 메시지 발송
  send_document(filepath, caption="")
      → 파일(엑셀 등) 발송
  send_golden_cross_alert(signals)
      → 골든크로스 신호 발생 종목 알림
      → signals: scan_watchlist() 반환값
  send_daily_report(kospi_df, kosdaq_df, reentry_df, excel_path, start, end)
      → 일일 Top100 요약 + 엑셀 리포트 첨부 발송

환경변수:
  TELEGRAM_BOT_TOKEN  — BotFather에서 발급
  TELEGRAM_CHAT_ID    — 메시지 수신 채팅방 ID

채팅방 ID 확인 방법:
  1) 봇에게 아무 메시지 전송
  2) https://api.telegram.org/bot<TOKEN>/getUpdates 접속
  3) result[0].message.chat.id 값 사용

의존성: requests, pandas, python-dotenv
환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (.env)

수정 이력:
  2026-03-19  최초 작성 — Phase 4
              python-telegram-bot 라이브러리 없이 requests로 직접 구현
              (의존성 최소화, 동기 방식)
──────────────────────────────────────────────────────
"""

import os
from typing import Optional

import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── 설정 ──────────────────────────────────────────────────
_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

_BASE_URL = f"https://api.telegram.org/bot{_TOKEN}"
_TIMEOUT  = 30  # 파일 전송 시 여유 있게


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _check_config() -> bool:
    """토큰/채팅방 ID 설정 여부 확인"""
    if not _TOKEN or not _CHAT_ID:
        print("[알림] .env에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 미설정 — 발송 건너뜀")
        return False
    return True


def _post(endpoint: str, **kwargs) -> Optional[dict]:
    """텔레그램 API POST 요청 공통 헬퍼

    Args:
        endpoint: API 엔드포인트 (예: "sendMessage")
        **kwargs: requests.post에 전달할 인자

    Returns:
        응답 JSON dict, 실패 시 None
    """
    try:
        url = f"{_BASE_URL}/{endpoint}"
        resp = requests.post(url, timeout=_TIMEOUT, **kwargs)
        data = resp.json()
        if not data.get("ok"):
            print(f"[알림 오류] {endpoint}: {data.get('description')}")
            return None
        return data
    except Exception as e:
        print(f"[알림 오류] {endpoint}: {e}")
        return None


# ── 공개 함수 ──────────────────────────────────────────────

def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """텍스트 메시지 발송

    Args:
        text:       발송할 메시지 (HTML 태그 사용 가능)
        parse_mode: "HTML" 또는 "Markdown"

    Returns:
        성공 시 True
    """
    if not _check_config():
        return False

    result = _post("sendMessage", json={
        "chat_id": _CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
    })
    return result is not None


def send_document(filepath: str, caption: str = "") -> bool:
    """파일 발송 (엑셀, PDF 등)

    Args:
        filepath: 발송할 파일 경로
        caption:  파일 설명 텍스트

    Returns:
        성공 시 True
    """
    if not _check_config():
        return False

    if not os.path.exists(filepath):
        print(f"[알림 오류] 파일 없음: {filepath}")
        return False

    try:
        with open(filepath, "rb") as f:
            result = _post("sendDocument", data={
                "chat_id": _CHAT_ID,
                "caption": caption,
            }, files={"document": f})
        return result is not None
    except Exception as e:
        print(f"[알림 오류] 파일 발송 실패: {e}")
        return False


def send_golden_cross_alert(signals: list[dict]) -> bool:
    """골든크로스 신호 알림 발송

    골든크로스 감지 시 즉시 호출.
    신호 종목이 없으면 발송하지 않습니다.

    Args:
        signals: golden_cross.scan_watchlist() 반환값
                 [{"종목코드", "종목명", "datetime",
                   "close", "ma3", "ma5", "reason"}, ...]

    Returns:
        성공 시 True (신호 없으면 False)
    """
    if not signals:
        return False

    lines = ["🚨 <b>골든크로스 신호 감지</b>", ""]

    for s in signals:
        lines += [
            f"📌 <b>{s['종목명']}</b> ({s['종목코드']})",
            f"   🕐 시각: {_fmt_time(s['datetime'])}",
            f"   💰 종가: {s['close']:,.0f}원",
            f"   📈 MA3: {s['ma3']:,.2f}  /  MA5: {s['ma5']:,.2f}",
            "",
        ]

    lines.append(f"📊 총 {len(signals)}개 종목 신호 발생")
    return send_message("\n".join(lines))


def send_daily_report(kospi_df: pd.DataFrame,
                      kosdaq_df: pd.DataFrame,
                      reentry_df: pd.DataFrame,
                      excel_path: str,
                      start_date: str,
                      end_date: str) -> bool:
    """일일 종합 리포트 발송 (텍스트 요약 + 엑셀 첨부)

    매일 21:00 KST 스케줄러에서 호출.

    Args:
        kospi_df:   코스피 Top100 DataFrame
        kosdaq_df:  코스닥 Top100 DataFrame
        reentry_df: 재진입 종목 DataFrame
        excel_path: 첨부할 엑셀 파일 경로
        start_date: 분석 시작일 (YYYYMMDD)
        end_date:   분석 종료일 (YYYYMMDD)

    Returns:
        텍스트+파일 모두 성공 시 True
    """
    text = _build_daily_message(
        kospi_df, kosdaq_df, reentry_df, start_date, end_date)

    msg_ok = send_message(text)

    caption = f"📎 Top100 리포트 ({start_date}~{end_date})"
    doc_ok = send_document(excel_path, caption=caption)

    return msg_ok and doc_ok


# ── 메시지 포맷 헬퍼 ───────────────────────────────────────

def _fmt_time(hhmmss: str) -> str:
    """HHMMSS → HH:MM 형태로 변환

    Args:
        hhmmss: "153000" 형태 문자열

    Returns:
        "15:30" 형태, 변환 실패 시 원본 반환
    """
    try:
        return f"{hhmmss[:2]}:{hhmmss[2:4]}"
    except Exception:
        return hhmmss


def _fmt_date(yyyymmdd: str) -> str:
    """YYYYMMDD → YYYY-MM-DD 형태로 변환"""
    try:
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    except Exception:
        return yyyymmdd


def _build_daily_message(kospi_df: pd.DataFrame,
                         kosdaq_df: pd.DataFrame,
                         reentry_df: pd.DataFrame,
                         start_date: str,
                         end_date: str) -> str:
    """일일 리포트 텍스트 메시지 생성

    Args:
        kospi_df, kosdaq_df, reentry_df: 분석 결과 DataFrames
        start_date, end_date: 분석 기간

    Returns:
        HTML 형식의 메시지 문자열
    """
    lines = [
        "📊 <b>코스피/코스닥 수익률 분석 완료</b>",
        f"📅 기간: {_fmt_date(start_date)} ~ {_fmt_date(end_date)}",
        "",
    ]

    # 코스피 Top3
    lines.append("🏆 <b>코스피 Top 3</b>")
    for i, (_, row) in enumerate(kospi_df.head(3).iterrows(), 1):
        rate = row["수익률(%)"]
        sign = "+" if rate >= 0 else ""
        lines.append(f"  {i}. {row['종목명']} ({sign}{rate:.2f}%)")

    lines.append("")

    # 코스닥 Top3
    lines.append("🏆 <b>코스닥 Top 3</b>")
    for i, (_, row) in enumerate(kosdaq_df.head(3).iterrows(), 1):
        rate = row["수익률(%)"]
        sign = "+" if rate >= 0 else ""
        lines.append(f"  {i}. {row['종목명']} ({sign}{rate:.2f}%)")

    lines.append("")

    # 재진입 요약
    reentry_count = len(reentry_df) if not reentry_df.empty else 0
    lines.append(f"🔄 재진입 포착: <b>{reentry_count}개</b>")

    if reentry_count > 0:
        for _, row in reentry_df.head(3).iterrows():
            lines.append(
                f"  • {row['종목명']} "
                f"({int(row['이전_순위'])}위 → {int(row['현재_순위'])}위)")
        if reentry_count > 3:
            lines.append(f"  ... 외 {reentry_count - 3}개 (엑셀 참조)")

    lines.append("")
    lines.append("📎 상세 리포트 첨부")

    return "\n".join(lines)
