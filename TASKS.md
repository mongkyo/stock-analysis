# TASKS.md — 프로젝트 전체 현황 명세서

> **새 Claude 세션 시작 시 요청 템플릿**
> ```
> CLAUDE.md와 TASKS.md를 읽고 [오늘 할 작업]을 진행해줘.
> ```

---

## 전체 구현 현황 (2026-03-24 기준)

| 영역 | 상태 |
|------|------|
| KIS API 클라이언트 | ✅ 완료 |
| Top100 분석 스크립트 | ✅ 완료 |
| 엑셀 리포트 생성 | ✅ 완료 |
| 골든크로스 감지 + 텔레그램 알림 | ✅ 완료 |
| APScheduler 자동화 | ✅ 완료 |
| FastAPI 웹 (인증/대시보드/분석/관심종목/관리자) | ✅ 완료 |
| StockPrice 일별 전 종목 종가 저장 | ✅ 완료 |
| 복합점수 기반 Top100 (백분위 가중합산) | ✅ 완료 |
| 분석 캐시 로직 (KIS 가격 API 재호출 없음) | ✅ 완료 |
| 누락 날짜 단독 fetch (시나리오 3) | ✅ 완료 |
| 실시간 조회 (분석 미실행 기간) | ✅ 완료 |
| GitHub Actions + self-hosted runner 자동 배포 | ✅ 완료 |
| Cloudflare 터널 (stock.upwaves.org) | ✅ 완료 |
| 맥북프로 서버 launchd 자동실행 | ✅ 완료 |
| 분석 실행 백그라운드 + 폴링 | ⏳ 미구현 (탭 닫으면 중단 이슈) |
| 맥미니 Docker 이전 | ⏳ 4월 1주차 도착 후 |

---

## 서버 / 배포 정보

| 항목 | 내용 |
|------|------|
| 개발 환경 | 맥북에어 (로컬) |
| 운영 서버 | 맥북프로 사무실 `/Users/mongkyo-server/Developer/stock-analysis` |
| 도메인 | stock.upwaves.org (Cloudflare Tunnel) |
| Python | `/usr/local/bin/python3.11` |
| DB | PostgreSQL (Homebrew), DB명: stock_analysis |
| 배포 방식 | git push → GitHub Actions self-hosted runner → uvicorn 재시작 |
| 서버 서비스 | launchd: `com.stock.uvicorn`(포트 8000), `com.stock.cloudflared`, `actions.runner` |
| 슬립 방지 | `sudo pmset -a sleep 0` |

### 자동 배포 흐름
```
맥북에어에서 git push
  → GitHub Actions (.github/workflows/deploy.yml)
  → self-hosted runner (맥북프로)
  → git pull → pip install → uvicorn 재시작
  → stock.upwaves.org 반영
```

---

## 프로젝트 구조 및 주요 파일

```
stock-analysis/
├── CLAUDE.md               # 프로젝트 컨텍스트 (Claude 지시사항)
├── TASKS.md                # 이 파일
├── .env                    # API 키 (git 제외)
├── requirements.txt        # pip 의존성
│
├── scripts/
│   ├── kis_api.py          # KIS API 클라이언트
│   ├── top100.py           # Top100 분석 메인 로직
│   ├── report.py           # 엑셀 리포트 생성 (6시트)
│   ├── golden_cross.py     # 골든크로스 감지 (MA3/MA5)
│   └── notifier.py         # 텔레그램 알림
│
├── scheduler/
│   └── jobs.py             # APScheduler 자동화 작업
│
└── web/
    ├── main.py             # FastAPI 진입점
    ├── create_admin.py     # admin 계정 초기 생성 CLI
    ├── alembic/            # DB 마이그레이션
    ├── api/
    │   ├── config.py       # 환경변수 중앙 관리
    │   ├── database.py     # SQLAlchemy 설정
    │   ├── auth.py         # JWT + bcrypt 인증
    │   ├── models/
    │   │   ├── user.py     # User, WatchlistItem
    │   │   └── stock.py    # AnalysisResult, StockPrice, GoldenCrossLog
    │   ├── routers/
    │   │   ├── auth.py     # /auth/login, /auth/logout
    │   │   ├── dashboard.py # /, /analysis, /reports
    │   │   ├── watchlist.py # /watchlist
    │   │   └── admin.py    # /admin/users
    │   └── services/
    │       └── analysis_service.py  # 분석 실행 서비스 (핵심)
    └── templates/
        ├── base.html
        ├── auth/login.html
        ├── dashboard/index.html
        ├── dashboard/reports.html
        ├── analysis/index.html
        ├── analysis/partials/table.html
        ├── watchlist/index.html
        ├── watchlist/partials/list.html
        ├── admin/users.html
        └── errors/403.html
```

---

## DB 스키마

### users
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | int PK | |
| email | str unique | 로그인 ID |
| name | str | 표시명 |
| hashed_password | str | bcrypt |
| role | enum | admin / premium / basic |
| auth_provider | str | local (OAuth 확장 예비) |
| is_active | bool | 계정 활성화 여부 |
| created_at | datetime | |

### watchlist_items
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | int PK | |
| user_id | FK → users | |
| code | str | 종목코드 6자리 |
| name | str | 종목명 |
| created_at | datetime | |

### analysis_results
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | int PK | |
| start_date | str | 분석 시작일 YYYYMMDD |
| end_date | str | 분석 종료일 YYYYMMDD |
| market | str | 통합 / 코스피 / 코스닥 |
| rank | int | 순위 |
| code | str | 종목코드 |
| name | str | 종목명 |
| growth_rate | float | 수익률(%) |
| roe | float\|null | ROE |
| op_margin | float\|null | 영업이익률 |
| score | float\|null | 복합점수 (저장 시점 가중치 기준) |
| created_at | datetime | |

> **주의**: score는 저장 시점 가중치 기준. 조회 시 `_recalc_scores()`로 현재 가중치로 재계산.
> start_price / end_price 컬럼은 제거됨 → StockPrice 테이블에서 JOIN으로 조회.

### stock_prices
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | int PK | |
| code | str | 종목코드 |
| name | str | 종목명 |
| date | str | 날짜 YYYYMMDD |
| close_price | int | 종가 |
| created_at | datetime | |
| UNIQUE | (code, date) | 중복 방지 |

> **역할**: KIS 가격 API 재호출 없이 수익률 계산을 위한 원본 데이터 저장소.
> daily_price_job이 매일 15:35 전 종목(~2,500개) 저장.

### golden_cross_logs
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | int PK | |
| code | str | 종목코드 |
| name | str | 종목명 |
| price | int | 감지 시점 가격 |
| ma3 | float | 3봉 이동평균 |
| ma5 | float | 5봉 이동평균 |
| detected_at | datetime | 감지 시각 |

---

## 핵심 로직 설명

### 복합점수 산정 (top100.py)
```python
SCORE_WEIGHTS = {
    "수익률(%)":    0.70,  # 모멘텀
    "ROE":          0.15,  # 자본 효율성
    "영업이익률":   0.10,  # 사업 안정성
    "일평균거래량": 0.05,  # 유동성
}
```
- 각 지표를 그룹 내 백분위(0~100)로 정규화 후 가중합산
- None/NaN → 중앙값 대체 (중립 처리)
- FETCH_N=500: 수익률 상위 500 추출 → 재무조회 → 복합점수 정렬 → Top100

### 분석 실행 흐름 (analysis_service.py)

```
run_analysis(db, start, end)
  │
  ├─ _ensure_date(start) ← start 날짜 StockPrice에 없으면 KIS API fetch + 저장
  ├─ _ensure_date(end)   ← end 날짜 StockPrice에 없으면 KIS API fetch + 저장
  │
  ├─ _find_cache_dates(db, start, end)
  │    ├─ start 이하 최신 거래일 탐색 (주말/공휴일 → 이전 거래일)
  │    └─ end 이하 최신 거래일 탐색
  │
  ├─ 캐시 가능하면 → _run_from_cache()
  │    ├─ StockPrice에서 start/end 종가 조회 → 수익률 계산
  │    ├─ 종목 마스터 zip 다운로드 (코스피/코스닥 구분)
  │    ├─ KIS 재무 API 호출 (ROE/OPM, 여전히 필요)
  │    └─ 복합점수 계산 → Top100 반환  [KIS 가격 API 0번 호출]
  │
  └─ 캐시 불가하면 → get_combined_top100(client, start, end)
       └─ 기존 방식 (전 종목 KIS 가격 API 호출, 30~40분 소요)
```

### 조회 흐름 (dashboard.py)

```
GET /analysis/result?start=&end=&market=
  │
  ├─ _query_results_with_prices() → AnalysisResult + StockPrice JOIN
  │    └─ 결과 있으면 → _recalc_scores() (현재 가중치로 점수 재계산)
  │
  └─ 결과 없으면 → _quick_query_from_prices()  [API 0번 호출]
       ├─ _find_cache_dates() → 실제 매매일 탐색
       ├─ StockPrice에서 종가 조회 → 수익률 계산
       ├─ 이전 AnalysisResult에서 ROE/OPM 재사용 (가장 최근 값)
       ├─ 이전 AnalysisResult 이력에서 코스피/코스닥 구분 추론
       └─ _recalc_scores() → Top100 반환 + is_live=True (배지 표시)
```

### 실시간 점수 재계산 (_recalc_scores)
- DB 조회 후 항상 현재 SCORE_WEIGHTS로 재계산
- DB의 score 컬럼 값은 무시 (저장 시점 가중치와 다를 수 있음)
- 일평균거래량은 DB에 없으므로 나머지 3개 지표(수익률/ROE/OPM)의 비율로 정규화

---

## 자동화 스케줄 (scheduler/jobs.py)

| 작업 | 실행 시간 | 내용 |
|------|----------|------|
| scan_job | 평일 09:00~15:30 (30분 간격) | 관심종목 골든크로스 감지 → 텔레그램 알림 → GoldenCrossLog DB 저장 |
| report_job | 매일 21:00 KST | Top100 분석 → 엑셀 생성 → 텔레그램 리포트 발송 |
| daily_price_job | 평일 15:35 KST | 전 종목(~2,500개) 종가 → StockPrice DB 저장 |

### 수동 실행
```bash
cd stock-analysis
python scheduler/jobs.py --now scan    # 골든크로스 스캔
python scheduler/jobs.py --now report  # 리포트 생성
python scheduler/jobs.py --now price   # 오늘 종가 저장
```

---

## 엑셀 리포트 시트 구조 (report.py)

| 시트명 | 내용 | 정렬 기준 |
|--------|------|----------|
| 통합_TOP100 | 코스피+코스닥 전체 | 수익률 내림차순 |
| 코스피_TOP100 | 코스피 단독 | 수익률 내림차순 |
| 코스닥_TOP100 | 코스닥 단독 | 수익률 내림차순 |
| 복합점수_TOP100 | 통합 복합점수 기준 | 종합점수 내림차순 |
| 재진입_포착 | 이전달 51위↓ → 이번달 Top100 | 현재순위 |
| 관심종목 | watchlist.json 기간 수익률 | 수익률 내림차순 |

컬럼: 종목코드 \| 종목명 \| 시장 \| 시작가 \| 종료가 \| 수익률(%) \| ROE \| 영업이익률 \| (종합점수)

---

## 권한 체계

| 역할 | 접근 가능 페이지 |
|------|----------------|
| admin | 전체 + 분석 실행 + 관리자 페이지 |
| premium | 대시보드, 분석 조회, 리포트 다운로드, 관심종목 |
| basic | 대시보드, 분석 조회, 관심종목 |
| 미로그인 | 로그인 페이지로 리다이렉트 |

---

## 웹 엔드포인트 목록

| Method | URL | 권한 | 설명 |
|--------|-----|------|------|
| GET | / | 로그인 | 대시보드 (Top5 + 골든크로스 신호) |
| GET | /analysis | basic+ | Top100 분석 페이지 |
| GET | /analysis/result | basic+ | HTMX: DB 조회 or 실시간 계산 |
| POST | /analysis/run | admin | HTMX: KIS API 분석 실행 + 저장 |
| GET | /reports | premium+ | 엑셀 리포트 목록 |
| GET | /reports/download/{filename} | premium+ | 엑셀 다운로드 |
| GET | /watchlist | basic+ | 관심종목 페이지 |
| POST | /watchlist | basic+ | 관심종목 추가 |
| DELETE | /watchlist/{code} | basic+ | 관심종목 삭제 |
| GET | /admin/users | admin | 사용자 관리 |
| POST | /admin/users/{id}/role | admin | 권한 변경 |
| GET | /auth/login | 전체 | 로그인 페이지 |
| POST | /auth/login | 전체 | 로그인 처리 |
| GET | /auth/logout | 로그인 | 로그아웃 |

---

## Alembic 마이그레이션 이력

| 파일 | 내용 |
|------|------|
| 001_add_stock_prices_remove_price_columns.py | stock_prices 테이블 생성, analysis_results에서 start_price/end_price 제거 |
| 002_add_score_column.py | analysis_results에 score 컬럼 추가 |

### 서버에서 마이그레이션 실행
```bash
cd /Users/mongkyo-server/Developer/stock-analysis/web
alembic upgrade head
```

---

## 환경변수 (.env)

```
KIS_APP_KEY=...
KIS_APP_SECRET=...
KIS_ACCOUNT_NO=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
DATABASE_URL=postgresql://localhost/stock_analysis
SECRET_KEY=...  # JWT 서명 키
```

---

## 알려진 이슈 및 다음 작업

### 🔴 잠재적 문제
- **분석 실행 타임아웃**: 전체 KIS API 분석은 30~40분 소요. 브라우저 탭 유지 필요.
  → 해결책: 백그라운드 작업(Celery/BackgroundTasks) + 폴링 방식으로 전환 필요

### 🟡 다음에 할 작업 (우선순위 순)
1. **분석 실행 백그라운드화**: FastAPI BackgroundTasks + 진행률 SSE/폴링
2. **맥미니 Docker 이전**: 4월 1주차 도착 후 Docker Compose로 전환
3. **관심종목 골든크로스 웹 연동**: 스캔 결과를 웹 대시보드에 실시간 표시
4. **사용자 자체 가입/승인 플로우**: 현재 admin이 CLI로만 계정 생성 가능

### ✅ 최근 완료 (이번 세션)
- 복합점수 가중치 조정: 수익률 55→70%, ROE 20→15%, OPM 15→10%, 거래량 10→5%
- 조회 시 현재 가중치로 점수 실시간 재계산 (`_recalc_scores`)
- 분석 미실행 기간 실시간 조회 (`_quick_query_from_prices`, API 0번 호출)
- 주말/공휴일 → 이전 거래일 자동 조정 (`_find_cache_dates` 수정)
- 누락 날짜 단독 fetch (`_fetch_and_save_date`)
- StockPrice 캐시 로직 구현 (`_run_from_cache`, `_find_cache_dates`)
- 403 권한 없음 전용 에러 페이지
- GitHub Actions self-hosted runner 자동 배포 완성
- 맥북프로 서버 launchd + Cloudflare 터널 세팅 완료

---

## 로컬 개발 시작

```bash
# PostgreSQL 시작
brew services start postgresql@15

# 웹 서버 실행
cd stock-analysis/web
uvicorn main:app --reload --port 8000

# 스케줄러 실행 (별도 터미널)
cd stock-analysis
python scheduler/jobs.py
```
