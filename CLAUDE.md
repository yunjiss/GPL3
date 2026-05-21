# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# 서버 실행 (개발)
python -m uvicorn main:app --reload --port 8000

# 의존성 설치
pip install -r requirements.txt

# 가상환경 사용 시
source .venv/bin/activate
```

별도의 빌드/테스트 명령 없음. 모든 동작 확인은 브라우저(`http://localhost:8000`)에서 직접 한다.

## 아키텍처

### 전체 흐름

```
브라우저 (index.html / login.html / setup.html)
    ↓ POST /analyze
FastAPI (main.py)
    ├─ Step 1: emotion.py   → 감정 분류 (HF zero-shot, mDeBERTa-v3)
    ├─ Step 1: ner.py       → 인물 추출 (HF NER, KoELECTRA)
    ├─ Step 2: embedding.py → 문장 임베딩 (KR-SBERT, ko-sroberta-multitask)
    ├─ Step 3: vector_db.py → 유사 일기 검색 (ChromaDB, cosine)
    ├─ Step 4a: cbt.py      → 인지 왜곡 분류 (rule + zero-shot 혼합)
    ├─ Step 4b: prompt.py + Gemini 2.5 Flash → 구조적 분석 (ABC, 요약 등)
    ├─ Step 4c: maru.py     → 마루 메시지 생성 (Gemini 2.5 Flash)
    └─ Step 5: db.py        → SQLite 저장
```

각 단계는 독립적으로 실패해도 전체 분석이 중단되지 않도록 try/except로 감싸져 있다.

### 파일별 역할

| 파일 | 역할 |
|------|------|
| `main.py` | FastAPI 앱, 전체 파이프라인 조율, 정적 파일 서빙 (`/img` → 프로젝트 루트) |
| `emotion.py` | 24개 한국어 감정 레이블 zero-shot 분류, polarity/intensity 계산 |
| `ner.py` | 일기 내 등장인물(PS) 추출 |
| `embedding.py` | KR-SBERT 로컬 임베딩 (API 비용 없음) |
| `vector_db.py` | ChromaDB 래퍼 — add/delete/find_similar |
| `cbt.py` | 인지 왜곡 12종 분류. 룰 기반(RULE_KEYWORDS) 우선, zero-shot NLI 보조 |
| `prompt.py` | Gemini 분석 프롬프트 생성, 룰 기반 왜곡 사전 검출 포함 |
| `maru.py` | 마루 캐릭터 메시지 생성. 유사 과거 패턴 기반 CBT 소크라테스식 반문 포함 |
| `db.py` | SQLite `diary` 테이블 CRUD. 스키마 마이그레이션은 파일 import 시 자동 실행 |
| `utils.py` | `safe_parse()` — Gemini JSON 응답 파싱 |

### 프론트엔드

- 프레임워크 없는 순수 HTML/JS 단일 파일 (`index.html`)
- 페이지 전환은 show/hide 클래스 토글 (`pg-section.visible`)
- `go(page)` 함수로 홈/일기쓰기/서재/통계 탭 전환
- 마루 캐릭터: 일기 수에 따라 3단계 성장 (0–4개: 마루1.png, 5–19개: 마루2.png, 20+개: 마루3.png)
- 이미지 경로: `/img/web/%EB%A7%88%EB%A3%A81.png` (URL-encoded 한국어 파일명)

### 데이터 저장

- **SQLite** (`diary.db`): 일기 텍스트, 분석 결과 (JSON 직렬화), 메타데이터
- **ChromaDB** (`chroma_db/`): 임베딩 벡터 (cosine 유사도)
- 두 저장소의 `diary_id`로 연결됨. 삭제 시 양쪽 모두 제거 필요

### AI 연결

`.env`에 `GOOGLE_API_KEY`가 있으면 API Key 방식, 없으면 Vertex AI (`VERTEX_PROJECT_ID`, `VERTEX_LOCATION`)로 자동 전환. `maru.py`와 `main.py` 모두 동일한 패턴의 싱글턴 클라이언트를 각자 유지한다.

모델: `gemini-2.5-flash` (분석), `gemini-2.5-flash` (마루 메시지)

### 인지 왜곡 분류 전략

`cbt.py`의 `classify_cognitive_distortions()`는 두 단계로 동작:
1. `RULE_KEYWORDS` 딕셔너리로 문장 내 키워드 매칭 (우선)
2. HF zero-shot NLI로 12개 왜곡 레이블 분류 (보조)
- 룰 결과가 있으면 모델 결과는 무시. 한국어 심리 문장에서 NLI 점수 과신 방지.
