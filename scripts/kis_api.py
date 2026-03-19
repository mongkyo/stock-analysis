"""
[kis_api.py] 한국투자증권(KIS) REST API 클라이언트
──────────────────────────────────────────────────────
역할:
  - KIS API 인증(토큰 발급/갱신)
  - 종목 마스터 다운로드 (코스피/코스닥 MST 파일)
  - 기간별 시작가/종료가 조회
  - ROE, 영업이익률 조회 (KIS /finance 엔드포인트)

주요 클래스/메서드:
  KISClient
    .get_access_token()       → 토큰 발급 (유효 토큰 재사용)
    .download_stock_list(mc)  → 종목 마스터 리스트 반환
    .get_period_price(code, start, end) → (시작가, 종료가)
    .get_financial_data(code) → {"ROE": float|None, "영업이익률": float|None}
    .add_financial_data(list) → 리스트에 ROE/영업이익률 병렬 추가
    .get_minute_ohlcv(code, end_time, interval) → 분봉 raw 레코드 리스트

의존성: requests (pip install requests)
환경변수: KIS_APP_KEY, KIS_APP_SECRET (.env)

수정 이력:
  2026-03-19  최초 작성 (stock-scanner/kis_client.py 기반 재구성)
              top100.py에 필요한 기능만 발췌, 함수명 한글 친화적으로 변경
  2026-03-19  get_minute_ohlcv() 추가 — golden_cross.py 에서 사용
──────────────────────────────────────────────────────
"""

import io
import os
import time
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


class KISClient:
    """한국투자증권 REST API 클라이언트"""

    REAL_URL = "https://openapi.koreainvestment.com:9443"
    VIRTUAL_URL = "https://openapivts.koreainvestment.com:29443"

    def __init__(self, app_key: str, app_secret: str,
                 base_url: str = None):
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = base_url or self.REAL_URL

        self.access_token: str | None = None
        self.token_expired_at = None
        self._token_lock = threading.Lock()

    # ── 인증 ──────────────────────────────────────────────

    def get_access_token(self) -> str:
        """접근 토큰 발급 (유효 토큰 존재 시 재사용)"""
        import datetime

        if self._is_token_valid():
            return self.access_token

        with self._token_lock:
            if self._is_token_valid():
                return self.access_token

            url = f"{self.base_url}/oauth2/tokenP"
            body = {
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
            }
            response = requests.post(url, json=body, timeout=10)
            if response.status_code != 200:
                raise RuntimeError(
                    f"토큰 발급 실패 (status={response.status_code}): "
                    f"{response.text}"
                )
            data = response.json()
            self.access_token = data["access_token"]
            self.token_expired_at = datetime.datetime.strptime(
                data["access_token_token_expired"], "%Y-%m-%d %H:%M:%S"
            )
            return self.access_token

    def _is_token_valid(self) -> bool:
        """토큰 유효 여부 확인 (만료 1분 전부터 무효 처리)"""
        import datetime

        if self.access_token is None or self.token_expired_at is None:
            return False
        buffer = datetime.timedelta(minutes=1)
        return datetime.datetime.now() < (self.token_expired_at - buffer)

    def _header(self, tr_id: str) -> dict:
        """API 요청 공통 헤더 생성"""
        if not self._is_token_valid():
            self.get_access_token()
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }

    # ── 종목 마스터 ────────────────────────────────────────

    def download_stock_list(self, market_code: str) -> list[dict]:
        """KIS 마스터 파일에서 종목 리스트 다운로드

        Args:
            market_code: "J" (코스피) 또는 "Q" (코스닥)

        Returns:
            [{"종목코드": "005930", "종목명": "삼성전자"}, ...]
        """
        if market_code == "J":
            url = ("https://new.real.download.dws.co.kr"
                   "/common/master/kospi_code.mst.zip")
            part2_len = 228
            market_name = "코스피"
        elif market_code == "Q":
            url = ("https://new.real.download.dws.co.kr"
                   "/common/master/kosdaq_code.mst.zip")
            part2_len = 222
            market_name = "코스닥"
        else:
            raise ValueError(
                f"지원하지 않는 market_code: {market_code} (J 또는 Q)")

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"마스터 파일 다운로드 실패: {e}")

        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            raw_data = zf.read(zf.namelist()[0])

        lines = raw_data.decode("cp949").strip().split("\n")
        stocks = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            part1 = line[:-part2_len]
            short_code = part1[0:9].rstrip()
            korean_name = part1[21:].strip()
            # 6자리 숫자 코드만 포함
            if len(short_code) == 6 and short_code.isdigit():
                stocks.append({
                    "종목코드": short_code,
                    "종목명": korean_name,
                })

        print(f"[종목 마스터] {market_name} {len(stocks):,}개 로드")
        return stocks

    # ── 시세 조회 ──────────────────────────────────────────

    def get_period_price(self, stock_code: str,
                         start_date: str, end_date: str) -> tuple:
        """기간별 시작가/종료가 조회

        Args:
            stock_code: 종목코드 (예: "005930")
            start_date: 시작일 (YYYYMMDD)
            end_date:   종료일 (YYYYMMDD)

        Returns:
            (시작 종가, 종료 종가) — 데이터 없으면 (None, None)
        """
        url = (f"{self.base_url}/uapi/domestic-stock/v1/quotations"
               "/inquire-daily-itemchartprice")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",
        }
        try:
            resp = requests.get(
                url, headers=self._header("FHKST03010100"),
                params=params, timeout=10)
            if resp.status_code != 200:
                return (None, None)
            data = resp.json()
            if data.get("rt_cd") != "0":
                return (None, None)

            records = [
                r for r in data.get("output2", [])
                if r.get("stck_clpr") and int(r["stck_clpr"]) > 0
            ]
            if len(records) < 2:
                return (None, None)

            # output2: 최신일이 앞, 과거일이 뒤
            end_price = int(records[0]["stck_clpr"])
            start_price = int(records[-1]["stck_clpr"])
            return (start_price, end_price)

        except Exception as e:
            print(f"  [시세 오류] {stock_code}: {e}")
            return (None, None)

    # ── 재무 데이터 ───────────────────────────────────────

    def get_financial_data(self, stock_code: str) -> dict:
        """KIS API에서 ROE와 영업이익률 조회

        Args:
            stock_code: 종목코드

        Returns:
            {"ROE": float | None, "영업이익률": float | None}
        """
        result: dict = {"ROE": None, "영업이익률": None}

        # ROE (재무비율)
        try:
            url = (f"{self.base_url}/uapi/domestic-stock/v1"
                   "/finance/financial-ratio")
            resp = requests.get(
                url, headers=self._header("FHKST66430300"),
                params={
                    "FID_DIV_CLS_CODE": "0",
                    "fid_cond_mrkt_div_code": "J",
                    "fid_input_iscd": stock_code,
                }, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("rt_cd") == "0":
                    output = data.get("output", [])
                    if output:
                        roe_val = output[0].get("roe_val", "").strip()
                        if roe_val:
                            result["ROE"] = float(roe_val)
        except Exception as e:
            print(f"  [ROE 오류] {stock_code}: {e}")

        time.sleep(0.3)

        # 영업이익률 (수익성비율)
        try:
            url = (f"{self.base_url}/uapi/domestic-stock/v1"
                   "/finance/profit-ratio")
            resp = requests.get(
                url, headers=self._header("FHKST66430400"),
                params={
                    "FID_DIV_CLS_CODE": "0",
                    "fid_cond_mrkt_div_code": "J",
                    "fid_input_iscd": stock_code,
                }, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("rt_cd") == "0":
                    output = data.get("output", [])
                    if output:
                        rate = output[0].get("sale_oper_rate", "").strip()
                        if not rate:
                            rate = output[0].get(
                                "sale_totl_rate", "").strip()
                        if rate:
                            result["영업이익률"] = float(rate)
        except Exception as e:
            print(f"  [영업이익률 오류] {stock_code}: {e}")

        return result

    def add_financial_data(self, results: list[dict],
                           max_workers: int = 5) -> list[dict]:
        """종목 리스트에 ROE/영업이익률 병렬 추가

        Args:
            results: [{"종목코드": ..., ...}, ...]
            max_workers: 병렬 스레드 수

        Returns:
            ROE, 영업이익률 컬럼이 추가된 리스트
        """
        self.get_access_token()
        total = len(results)
        print(f"\n[재무 데이터] {total}개 종목 조회 시작...")

        completed = [0]
        lock = threading.Lock()

        def _fetch(item: dict):
            time.sleep(0.05)
            fin = self.get_financial_data(item["종목코드"])
            item["ROE"] = fin["ROE"]
            item["영업이익률"] = fin["영업이익률"]
            with lock:
                completed[0] += 1
                idx = completed[0]
            if idx % 10 == 0 or idx == total:
                print(f"  [{idx}/{total}] 재무 조회 진행 중...")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_fetch, item) for item in results]
            for f in as_completed(futures):
                f.result()

        print(f"[재무 데이터] 조회 완료")
        return results

    def get_minute_ohlcv(self, stock_code: str,
                         end_time: str = "153000",
                         minute_interval: str = "30") -> list[dict]:
        """분봉 OHLCV 데이터 조회 (golden_cross.py에서 사용)

        Args:
            stock_code:      종목코드
            end_time:        조회 종료 시각 (HHMMSS, 기본 "153000")
            minute_interval: 분 단위 ("1","5","10","15","30","60")

        Returns:
            [{"stck_cntg_hour", "stck_oprc", "stck_hgpr",
              "stck_lwpr", "stck_prpr", "cntg_vol"}, ...]
            최신 시각이 먼저 정렬. 실패 시 빈 리스트.
        """
        url = (f"{self.base_url}/uapi/domestic-stock/v1/quotations"
               "/inquire-time-itemchartprice")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_HOUR_1": end_time,
            "FID_PW_DATA_INCU_YN": "Y",
            "FID_ETC_CLS_CODE": minute_interval,
        }

        try:
            resp = requests.get(
                url, headers=self._header("FHKST03010200"),
                params=params, timeout=10)
            if resp.status_code != 200:
                return []

            data = resp.json()
            if data.get("rt_cd") != "0":
                return []

            result = []
            for r in data.get("output2", []):
                hour_val = r.get("stck_cntg_hour", "")
                prpr = r.get("stck_prpr", "")
                if not hour_val or not prpr or int(prpr) == 0:
                    continue
                result.append({
                    "stck_cntg_hour": hour_val,
                    "stck_oprc": r.get("stck_oprc", "0"),
                    "stck_hgpr": r.get("stck_hgpr", "0"),
                    "stck_lwpr": r.get("stck_lwpr", "0"),
                    "stck_prpr": prpr,
                    "cntg_vol": r.get("cntg_vol", "0"),
                })
            return result

        except Exception as e:
            print(f"  [분봉 오류] {stock_code}: {e}")
            return []
