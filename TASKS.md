# TASKS.md — 작업 현황 및 명세

> **사용법**: 새 Claude CLI 세션 시작 시 아래 템플릿으로 요청
> ```
> CLAUDE.md와 TASKS.md를 읽고 [오늘 할 작업]을 진행해줘.
> ```

---

## 전체 Phase 현황

| Phase | 내용 | 상태 |
|-------|------|------|
| 0 | 환경 세팅 (Python, Git, API 키) | ✅ 완료 |
| 1 | 핵심 스크립트 작성 | ✅ 완료 |
| 2 | 실데이터 테스트 | ⏳ KIS/텔레그램 키 준비 후 |
| 3 | 골든크로스 감지 | ✅ 완료 |
| 4 | 텔레그램 알림 | ✅ 완료 |
| 5 | APScheduler 자동화 | ✅ 완료 |
| 6 | FastAPI 웹 개발 | 🔨 진행 중 (맥북에어 개발) |
| 7 | 맥미니 배포 (Docker + CI/CD) | ⏳ 맥미니 도착 후 (4월 1주차) |

---

## Phase 1 완료 — 핵심 스크립트

### 파일 목록
```
stock-analysis/
├── scripts/
│   ├── kis_api.py          ✅ KIS API 클라이언트
│   │     KISClient 클래스: 토큰 발급, 시세, 재무(ROE/영업이익률), 30분봉
│   │     add_financial_data(): 병렬 재무 조회
│   ├── top100.py           ✅ Top100 추출 메인 로직
│   │     get_top100(client, start, end, market_code, limit)
│   │     get_combined_top100(client, start, end, limit)
│   │     filter_by_financials(df) — ROE/영업이익률 필터
│   │     find_reentry_stocks(prev_df, curr_df) — 재진입 포착
│   │     get_watchlist_performance(client, start, end)
│   ├── report.py           ✅ 엑셀 5시트 생성
│   │     create_excel_report(combined, kospi, kosdaq, reentry, start, end)
│   │     시트: 통합/코스피/코스닥 TOP100, 재진입_포착, 관심종목
│   ├── golden_cross.py     ✅ 골든크로스 감지
│   │     scan_watchlist(client) — MA3/MA5 상향돌파 감지
│   │     load/save/add/remove_watchlist()
│   └── notifier.py         ✅ 텔레그램 알림
│         send_golden_cross_alert(signals)
│         send_daily_report(kospi_df, kosdaq_df, reentry_df, excel_path, start, end)
└── scheduler/
    └── jobs.py             ✅ APScheduler
          scan_job()  — 평일 09:00~15:30 30분 간격
          report_job() — 매일 21:00 KST
```

### 실행 방법 (Phase 2 테스트)
```bash
# 1. .env 작성 (stock-analysis/.env)
KIS_APP_KEY=...
KIS_APP_SECRET=...
KIS_ACCOUNT_NO=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# 2. 패키지 설치
pip install pandas openpyxl requests python-dotenv apscheduler

# 3. 단발 테스트
python scripts/top100.py 20260101 20260228 --limit 10
python scheduler/jobs.py --now scan    # 관심종목 추가 후
python scheduler/jobs.py --now report

# 4. 상시 실행
python scheduler/jobs.py
```

---

## Phase 6 — FastAPI 웹 개발 (진행 중)

### 기술 스택
- FastAPI + Jinja2 템플릿
- HTMX (페이지 전환 없이 부분 갱신)
- Tailwind CSS (CDN, 빌드 불필요)
- Alpine.js (날짜 선택 등 간단한 상태관리)
- PostgreSQL 15 (Homebrew 설치) + SQLAlchemy 2.0
- JWT 인증 (python-jose) + bcrypt (직접 사용, passlib 미사용)

### 서버 실행
```bash
cd stock-analysis/web
python3.11 create_admin.py    # 최초 1회만 — admin 계정 생성
uvicorn main:app --reload --port 8000
# 접속: http://localhost:8000
# 계정: admin / admin1234!
```

### 완료된 파일
```
web/
├── main.py                 ✅ FastAPI 앱 진입점 + 라우터 등록 + DB 초기화
├── create_admin.py         ✅ 관리자 계정 생성 스크립트
├── alembic/                ✅ DB 마이그레이션 설정
│   └── env.py              (DATABASE_URL + 모델 메타데이터 연결)
├── api/
│   ├── database.py         ✅ SQLAlchemy 설정 (PostgreSQL)
│   ├── auth.py             ✅ JWT 발급/검증 + bcrypt 비밀번호 + 의존성 주입
│   ├── models/
│   │   ├── user.py         ✅ User (admin/premium/basic) + watchlist 관계
│   │   └── stock.py        ✅ AnalysisResult, WatchlistItem, GoldenCrossLog
│   └── routers/
│       ├── auth.py         ✅ GET/POST /auth/login, GET /auth/logout
│       ├── dashboard.py    ✅ GET /, /analysis, /analysis/result, /reports, /reports/download
│       └── watchlist.py    ✅ GET/POST /watchlist, DELETE /watchlist/{code}
└── templates/
    ├── base.html           ✅ 사이드바 + 헤더 레이아웃
    ├── auth/login.html     ✅ 로그인 페이지 (standalone)
    ├── dashboard/
    │   ├── index.html      ✅ 대시보드 (요약 카드 + Top5 + 골든크로스)
    │   └── reports.html    ✅ 리포트 다운로드 목록
    ├── analysis/
    │   ├── index.html      ✅ Top100 분석 (기간 선택 버튼 + HTMX 조회)
    │   └── partials/table.html  ✅ Top100 결과 테이블 (HTMX 부분 렌더링)
    └── watchlist/
        ├── index.html      ✅ 관심종목 페이지
        └── partials/list.html   ✅ 관심종목 목록 (HTMX)
```

---

## Phase 6 — 남은 작업 (다음 세션에서 진행)

### ✅ 완료: 분석 실행 → DB 저장 연결 (방법 A)

**구현 내용:**
- `web/api/config.py` — 환경변수 중앙 관리 (KIS 키, DB URL, JWT 키 등)
- `web/api/services/analysis_service.py` — KIS API 호출 → DB upsert 서비스
- `POST /analysis/run` — admin 전용 엔드포인트 (require_role(admin) 보호)
- 분석 실행 버튼 — admin 로그인 시에만 표시 (premium/basic은 조회만 가능)
- 로딩 스피너 — 분석 중 상태 표시
- 에러 처리 — KIS 키 미설정, API 오류 시 에러 메시지 표시

**사용 방법:**
1. `.env`에 KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO 입력
2. admin으로 로그인 → `/analysis` → 기간 선택 → `⚡ 분석 실행`
3. 완료 후 결과 테이블 자동 표시 (DB에 저장됨)
4. 이후 premium/basic 사용자도 같은 기간 `조회` 가능

---

### 🟡 남은 작업 (우선순위 순)

1. **관리자 페이지** — 사용자 목록/권한 변경 (`/admin/users`)
   - 현재 계정 생성은 `create_admin.py` CLI로만 가능
   - 웹에서 premium/basic 계정 추가·비활성화 기능 필요
2. **Alembic 마이그레이션** — 현재 `Base.metadata.create_all()`로 동작 중
   - 운영 환경(맥미니)에서는 Alembic 권장
   - `alembic revision --autogenerate -m "init"` + `alembic upgrade head`
3. **스케줄러 DB 연동** — `scheduler/jobs.py` report_job()에서도 DB 저장
   - 21:00 자동 분석 결과가 웹에도 반영되게 연결

---

## 주요 결정사항 메모

| 항목 | 결정 |
|------|------|
| 재무데이터 출처 | DART 제거 → KIS API로 통합 |
| 알림 채널 | 텔레그램 우선 (카카오는 장기) |
| DB | PostgreSQL 15 (Homebrew, Docker 없이) |
| 웹 프레임워크 | FastAPI + HTMX + Tailwind + Alpine.js |
| 비밀번호 해시 | bcrypt 직접 사용 (passlib은 bcrypt 5.x 비호환) |
| 배포 환경 | 맥미니 (4월 1주차 도착) + Docker Compose |
| CI/CD | GitHub Actions (맥미니 도착 후) |
| 필터 기준 | 이사님과 협의 후 확정 예정 |

---

## Claude 요청 템플릿 (복붙용)

```
CLAUDE.md와 TASKS.md를 읽고 아래 작업을 진행해줘.

[오늘 작업]
Phase 6 남은 작업 중 "방법 A — 웹에서 직접 분석 실행" 구현
- /analysis/run 엔드포인트 추가
- analysis_service.py 작성 (KIS API → DB upsert)
- 분석 실행 버튼 + 로딩 UI 추가

[참고]
- web/api/routers/dashboard.py: 현재 엔드포인트 확인
- web/api/models/stock.py: AnalysisResult 모델 확인
- scripts/top100.py: 분석 로직 참고
```
