# CLAUDE.md — 주식 분석 플랫폼

## 프로젝트 개요
- 목적: 한국 주식(코스피/코스닥) Top100 분석 + 골든크로스 알림 자동화
- 사용자: 관리자(본인) + 이사님(Premium) + 승인된 외부 사용자(Basic)
- 인프라: 맥북(개발) → 맥미니(운영 서버, 4월 1주 도착 예정)

## 기술 스택
- Language: Python 3.11+
- 주요 라이브러리: pandas, openpyxl, requests, APScheduler, FastAPI
- DB: PostgreSQL (Docker)
- 에디터: vim + iTerm2
- 버전관리: Git / GitHub

## 프로젝트 구조
```
stock-platform/
├── CLAUDE.md             # 이 파일 (프로젝트 컨텍스트)
├── TASKS.md              # 현재 작업 명세 (매 세션마다 업데이트)
├── README.md
├── .env                  # API 키 (git 제외)
├── .gitignore
│
├── data/
│   └── watchlist.json    # 관심종목 목록
│
├── scripts/              # 핵심 스크립트
│   ├── top100.py         # Top100 추출 메인 로직 (기존 스크립트)
│   ├── dart_api.py       # DART 재무데이터 수집 (ROE, 영업이익률)
│   ├── kis_api.py        # KIS API 시세/차트 데이터 수집
│   ├── golden_cross.py   # 골든크로스 감지 엔진
│   ├── report.py         # 엑셀 리포트 생성 (openpyxl)
│   └── notifier.py       # 카카오/텔레그램 알림 발송
│
├── scheduler/
│   └── jobs.py           # APScheduler 작업 정의
│
└── api/                  # FastAPI (맥미니 이전 후 작업)
    └── main.py
```

## 엑셀 리포트 시트 구조 (현행 유지)
1. 통합_TOP100   — 코스피+코스닥 전체 상승률 Top100
2. 코스피_TOP100 — 코스피 단독 Top100
3. 코스닥_TOP100 — 코스닥 단독 Top100
4. 재진입_포착   — 이전달 51위↓ → 이번달 Top100 재진입 종목
5. 관심종목      — 사용자 지정 종목 기간별 성과

## 컬럼 구조 (전 시트 공통)
종목코드 | 종목명 | 시작가 | 종료가 | 수익률(%) | ROE | 영업이익률

## 필터 기준 (scripts/top100.py 상단 변수로 관리)
```python
ROE_THRESHOLD = 0          # ROE 이 값 미만 종목 제외
OP_MARGIN_THRESHOLD = 0    # 영업이익률 이 값 미만 종목 제외
REENTRY_PREV_RANK = 50     # 재진입: 이전달 이 순위 초과였던 종목만
```

## 주요 API
- KIS Developers: 시세, 30분봉 차트 (증권계좌 기반 무료)
- DART OpenAPI: ROE, 영업이익률 등 재무데이터 (완전 무료)
- KRX 정보데이터시스템: 종목 마스터

## 알림 방식
- 장중: 골든크로스 감지 시 즉시 발송 (30분 폴링)
- 저녁 21:00 KST: 일일 종합 리포트 발송
- 채널: 텔레그램 우선 (카카오 나에게 보내기 대안)

## Claude에게 작업 요청 시 규칙
- 함수 단위로 작성 (파일 전체 재작성 금지)
- 기존 코드 수정 시 변경 부분만 표시
- 에러 처리 항상 포함 (try/except)
- 타입 힌트 사용
- 한국어 주석
