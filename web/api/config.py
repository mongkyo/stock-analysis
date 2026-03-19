"""
[web/api/config.py] 환경변수 중앙 관리
──────────────────────────────────────────────────────
역할:
  - .env 파일 로드 (stock-analysis/.env)
  - 앱 전체에서 사용하는 설정값을 한 곳에서 관리
  - analysis_service, auth 등에서 import해서 사용

설정 항목:
  DATABASE_URL       — PostgreSQL 접속 URL
  SECRET_KEY         — JWT 서명 키
  KIS_APP_KEY        — KIS API 앱키
  KIS_APP_SECRET     — KIS API 앱시크릿
  KIS_ACCOUNT_NO     — KIS 계좌번호 (XXXXXXXX-XX)
  TELEGRAM_BOT_TOKEN — 텔레그램 봇 토큰
  TELEGRAM_CHAT_ID   — 텔레그램 채팅 ID

수정 이력:
  2026-03-19  최초 작성
──────────────────────────────────────────────────────
"""

import os
from dotenv import load_dotenv

# stock-analysis/.env 로드 (web/ 기준 두 단계 상위)
_env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(_env_path, override=False)  # 이미 로드된 변수는 덮어쓰지 않음


class Settings:
    # DB
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        "postgresql://stockadmin:stockpass123@localhost:5432/stockdb",
    )

    # JWT
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

    # KIS API
    KIS_APP_KEY: str    = os.environ.get("KIS_APP_KEY", "")
    KIS_APP_SECRET: str = os.environ.get("KIS_APP_SECRET", "")
    KIS_ACCOUNT_NO: str = os.environ.get("KIS_ACCOUNT_NO", "")  # XXXXXXXX-XX

    # 텔레그램
    TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str   = os.environ.get("TELEGRAM_CHAT_ID", "")

    def kis_configured(self) -> bool:
        """KIS API 키가 모두 설정됐는지 확인"""
        return bool(self.KIS_APP_KEY and self.KIS_APP_SECRET and self.KIS_ACCOUNT_NO)


settings = Settings()
