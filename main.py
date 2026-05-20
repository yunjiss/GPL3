import os
import logging
import json
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, validator

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from google import genai
from google.genai import types as genai_types

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from emotion import classify as classify_emotions
from ner import extract_persons
from embedding import get_embedding
from vector_db import add as vector_add, find_similar
from prompt import make_analysis_prompt
from cbt import classify_cognitive_distortions
from maru import generate_maru
from db import save_diary, get_all_diaries, get_diary_by_id, delete_diary
from utils import safe_parse

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/img", StaticFiles(directory=BASE_DIR), name="img")


# ── 정적 페이지 ───────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse(BASE_DIR / "login.html")


@app.get("/app")
def app_page():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/setup")
def setup_page():
    return FileResponse(BASE_DIR / "setup.html")


# ── Gemini 클라이언트 (싱글턴) ────────────────────────────────
_genai_client = None


def _get_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if api_key:
            _genai_client = genai.Client(api_key=api_key)
        else:
            _genai_client = genai.Client(
                vertexai=True,
                project=os.getenv("VERTEX_PROJECT_ID"),
                location=os.getenv("VERTEX_LOCATION", "asia-northeast3"),
            )
    return _genai_client


# ── DB 연결 헬퍼 ──────────────────────────────────────────────
def _db_conn():
    import sqlite3
    db_path = Path(__file__).resolve().parent / "diary.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ══════════════════════════════════════════════════════════════
# 모델 정의
# ══════════════════════════════════════════════════════════════

class DiaryRequest(BaseModel):
    text: str

    @validator("text")
    def text_not_empty(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("일기 내용을 입력해줘")
        if len(v) > 3000:
            raise ValueError("일기는 3000자 이하여야 해")
        return v


class UserProfile(BaseModel):
    name: str = ""
    mbti: str = ""
    interests: list[str] = []

    @validator("name")
    def name_strip(cls, v):
        return v.strip()

    @validator("mbti")
    def mbti_upper(cls, v):
        return v.upper().strip()


class SearchRequest(BaseModel):
    query: str
    filter_type: str = "all"   # all | emotion | event | person
    top_k: int = 8

    @validator("query")
    def query_not_empty(cls, v):
        if not v.strip():
            raise ValueError("검색어를 입력해줘")
        return v.strip()


# ══════════════════════════════════════════════════════════════
# 사용자 프로필
# ══════════════════════════════════════════════════════════════

@app.get("/user")
def get_user():
    conn = _db_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS user_profile (data TEXT NOT NULL)")
    row = conn.execute("SELECT data FROM user_profile LIMIT 1").fetchone()
    if row:
        return json.loads(row[0])
    return {"name": "", "mbti": "", "interests": []}


@app.put("/user")
def update_user(profile: UserProfile):
    conn = _db_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS user_profile (data TEXT NOT NULL)")
    conn.execute("DELETE FROM user_profile")
    conn.execute("INSERT INTO user_profile VALUES (?)", [profile.json()])
    conn.commit()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════
# 일기 분석 (/analyze)
# ══════════════════════════════════════════════════════════════

@app.post("/analyze")
def analyze(req: DiaryRequest):
    # ── 프로필 조회 ──────────────────────────────────────────
    try:
        conn = _db_conn()
        conn.execute("CREATE TABLE IF NOT EXISTS user_profile (data TEXT)")
        row = conn.execute("SELECT data FROM user_profile LIMIT 1").fetchone()
        profile = json.loads(row[0]) if row else {}
    except Exception:
        profile = {}

    user_name = profile.get("name", "사용자") or "사용자"
    mbti      = profile.get("mbti", "")
    interests = profile.get("interests", [])

    # ── Step 1: 로컬 HF — 감정 분류 + NER ───────────────────
    try:
        emotion_data = classify_emotions(req.text)
    except Exception as e:
        logger.warning("감정 분류 실패: %s", e)
        emotion_data = {
            "emotions": [],
            "emotion_polarity": "mixed",
            "emotion_intensity": "medium",
        }

    try:
        persons = extract_persons(req.text)
    except Exception as e:
        logger.warning("NER 실패: %s", e)
        persons = []

    # ── Step 2: 임베딩 ───────────────────────────────────────
    try:
        embedding = get_embedding(req.text)
    except Exception as e:
        logger.warning("임베딩 실패: %s", e)
        embedding = None

    # ── Step 3: 유사 과거 일기 검색 ──────────────────────────
    try:
        similar_diaries = find_similar(embedding) if embedding else []
    except Exception as e:
        logger.warning("벡터 검색 실패: %s", e)
        similar_diaries = []

    analysis = {
        "summary":               None,
        "events":                [],
        "followup_question":     None,
        "implicit_emotions":     [],
        "cognitive_distortions": [],
        "distortion_sentences":  [],
        "abc":                  {"A": None, "B": None, "C": None},
        "reframe_question":     None,
        "hidden_need":           None,
        "recovery_hint":         None,
        "cbt_model":            None,
        "is_resolved":           False,
        "emotions":              emotion_data["emotions"],
        "persons":               persons,
        "emotion_intensity":     emotion_data["emotion_intensity"],
        "emotion_polarity":      emotion_data["emotion_polarity"],
    }

    # ── Step 4a: 로컬 HF — CBT 인지 왜곡 후보 분류 ─────────
    try:
        cbt_data = classify_cognitive_distortions(req.text)
        analysis.update({k: v for k, v in cbt_data.items() if v})
    except Exception as e:
        logger.warning("CBT 분류 실패: %s", e)

    emotions_str = ", ".join(emotion_data["emotions"]) or "다양한"
    maru_memo    = f"{user_name}아, 오늘 {emotions_str} 감정이 느껴졌구나. 오늘도 수고했어."
    ai_available = False

    # ── Step 4b: Gemini — 구조적 분석 ────────────────────────
    try:
        analysis_prompt = make_analysis_prompt(
            req.text,
            emotion_data["emotions"],
            persons,
            user_name=user_name,
            mbti=mbti,
            interests=interests,
        )
        response = _get_client().models.generate_content(
            model="gemini-2.5-flash",
            contents=analysis_prompt,
            config=genai_types.GenerateContentConfig(temperature=0.2),
        )
        parsed = safe_parse(response.text)
        analysis.update({
            "summary":               parsed.get("summary"),
            "events":                parsed.get("events", []),
            "followup_question":     parsed.get("followup_question"),
            "implicit_emotions":     parsed.get("implicit_emotions", []),
            "cognitive_distortions": parsed.get("cognitive_distortions") or analysis.get("cognitive_distortions", []),
            "distortion_sentences":  parsed.get("distortion_sentences") or analysis.get("distortion_sentences", []),
            "abc":                  parsed.get("abc") or analysis.get("abc"),
            "reframe_question":     parsed.get("reframe_question") or analysis.get("reframe_question"),
            "hidden_need":           parsed.get("hidden_need"),
            "recovery_hint":         parsed.get("recovery_hint") or analysis.get("recovery_hint"),
            "is_resolved":           bool(parsed.get("is_resolved", False)),
        })
        ai_available = True
    except Exception as e:
        logger.warning("Gemini 분석 실패: %s", e)

    # ── Step 4c: 마루 메시지 생성 ─────────────────────────────
    try:
        maru_memo = generate_maru(
            analysis,
            similar_diaries,
            user_name=user_name,
            mbti=mbti,
        )
    except Exception as e:
        logger.warning("마루 메시지 생성 실패: %s", e)

    # ── Step 5: DB 저장 ──────────────────────────────────────
    try:
        diary_id = save_diary(req.text, analysis)
    except Exception as e:
        logger.error("일기 저장 실패: %s", e)
        diary_id = -1

    if embedding is not None and diary_id != -1:
        try:
            vector_add(
                diary_id,
                embedding,
                metadata={
                    "summary":          analysis.get("summary") or "",
                    "emotions_preview": ", ".join(analysis.get("emotions", [])),
                    "emotion_polarity": analysis.get("emotion_polarity") or "mixed",
                    "is_resolved":      analysis.get("is_resolved", False),
                },
            )
        except Exception as e:
            logger.error("벡터 저장 실패 diary_id=%s: %s", diary_id, e)

    best = similar_diaries[0] if similar_diaries else None
    return {
        "diary_id":  diary_id,
        "analysis":  analysis,
        "maru_memo": maru_memo,
        "past_connection": {
            "is_connected":    bool(best and best.get("similarity", 0) >= 0.65),
            "past_summary":    best.get("summary") if best else None,
            "similarity_score": float(best.get("similarity", 0)) if best else 0.0,
        },
        "ai_connected": ai_available,
    }


# ══════════════════════════════════════════════════════════════
# 검색 (/search)
# ══════════════════════════════════════════════════════════════

@app.post("/search")
def search_diaries(req: SearchRequest):
    results: list[dict] = []
    seen_ids: set[int]  = set()

    # 1) 벡터 시맨틱 검색
    try:
        emb = get_embedding(req.query)
        for hit in find_similar(emb):
            if hit.get("id") not in seen_ids:
                results.append(hit)
                seen_ids.add(hit["id"])
    except Exception as e:
        logger.warning("벡터 검색 실패: %s", e)

    # 2) 키워드 텍스트 매칭 (fallback)
    try:
        q = req.query.lower()
        for d in get_all_diaries():
            if d.get("id") in seen_ids:
                continue
            target = " ".join(filter(None, [
                d.get("text", ""),
                d.get("summary", ""),
                " ".join(d.get("emotions", [])),
                " ".join(d.get("persons", [])),
                " ".join(d.get("events", [])),
            ])).lower()
            if q in target:
                d["similarity"] = 0.0
                results.append(d)
                seen_ids.add(d["id"])
    except Exception as e:
        logger.warning("키워드 검색 실패: %s", e)

    # 3) 필터 타입 적용
    if req.filter_type == "emotion":
        results = [d for d in results if req.query in " ".join(d.get("emotions", []))]
    elif req.filter_type == "person":
        results = [d for d in results if req.query in " ".join(d.get("persons", []))]
    elif req.filter_type == "event":
        results = [d for d in results if req.query in " ".join(d.get("events", []))]

    results.sort(key=lambda d: d.get("similarity", 0), reverse=True)
    return results[: req.top_k]


# ══════════════════════════════════════════════════════════════
# 일기 CRUD
# ══════════════════════════════════════════════════════════════

@app.get("/diaries")
def list_diaries():
    return get_all_diaries()


@app.get("/diaries/{diary_id}")
def get_diary(diary_id: int):
    from fastapi import HTTPException
    entry = get_diary_by_id(diary_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Not found")
    return entry


@app.delete("/diaries/{diary_id}")
def remove_diary(diary_id: int):
    from fastapi import HTTPException
    from vector_db import delete as vector_delete
    ok = delete_diary(diary_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    vector_delete(diary_id)
    return {"deleted": diary_id}


# ══════════════════════════════════════════════════════════════
# 통계 (/stats)
# ══════════════════════════════════════════════════════════════

@app.get("/stats")
def get_stats():
    from collections import Counter
    diaries = get_all_diaries()
    if not diaries:
        return {
            "total": 0,
            "emotion_freq": {},
            "polarity_dist": {},
            "intensity_dist": {},
            "unique_emotions": 0,
            "maru": {"stage": 1, "stage_name": "아기 마루", "next_at": 5, "progress": 0.0},
        }

    all_emotions = []
    polarities   = []
    intensities  = []
    for d in diaries:
        all_emotions.extend(d.get("emotions") or [])
        if d.get("emotion_polarity"):
            polarities.append(d["emotion_polarity"])
        if d.get("emotion_intensity"):
            intensities.append(d["emotion_intensity"])

    total          = len(diaries)
    unique_emotions = len(set(all_emotions))

    if total < 5:
        stage, stage_name, next_at = 1, "아기 마루", 5
        progress = total / 5
    elif total < 20:
        stage, stage_name, next_at = 2, "소년 마루", 20
        progress = (total - 5) / 15
    else:
        stage, stage_name, next_at = 3, "현자 마루", None
        progress = 1.0

    return {
        "total":          total,
        "emotion_freq":   dict(Counter(all_emotions).most_common(10)),
        "polarity_dist":  dict(Counter(polarities)),
        "intensity_dist": dict(Counter(intensities)),
        "unique_emotions": unique_emotions,
        "maru": {
            "stage":      stage,
            "stage_name": stage_name,
            "next_at":    next_at,
            "progress":   round(progress, 2),
        },
    }
    
"""
main.py 추가 코드 — 기존 main.py 맨 아래에 붙여넣기
행동 활성화 트래킹 + 감정 회복 시간 통계
"""

# ══════════════════════════════════════════════════════════════
# 행동 활성화 트래킹
# ══════════════════════════════════════════════════════════════

class ActionRequest(BaseModel):
    diary_id: int
    action_text: str


def _init_actions_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS actions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            diary_id     INTEGER NOT NULL,
            action_text  TEXT    NOT NULL,
            suggested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed    INTEGER DEFAULT 0,
            completed_at TIMESTAMP
        )
    """)
    conn.commit()


@app.post("/actions")
def create_action(req: ActionRequest):
    """마루가 제안한 행동 저장"""
    conn = _db_conn()
    _init_actions_table(conn)
    cur = conn.execute(
        "INSERT INTO actions (diary_id, action_text) VALUES (?, ?)",
        [req.diary_id, req.action_text],
    )
    conn.commit()
    return {"id": cur.lastrowid, "action_text": req.action_text, "completed": False}


@app.get("/actions/pending")
def get_pending_actions():
    """완료 안 된 행동 제안 목록 (홈 체크인용)"""
    conn = _db_conn()
    _init_actions_table(conn)
    rows = conn.execute("""
        SELECT a.id, a.diary_id, a.action_text, a.suggested_at,
            d.summary AS diary_summary
        FROM   actions a
        LEFT JOIN diary d ON a.diary_id = d.id
        WHERE  a.completed = 0
        ORDER  BY a.suggested_at DESC
        LIMIT  5
    """).fetchall()
    return [dict(r) for r in rows]


@app.put("/actions/{action_id}/complete")
def complete_action(action_id: int):
    """행동 완료 체크"""
    conn = _db_conn()
    _init_actions_table(conn)
    conn.execute(
        "UPDATE actions SET completed=1, completed_at=CURRENT_TIMESTAMP WHERE id=?",
        [action_id],
    )
    conn.commit()
    return {"ok": True, "id": action_id}


@app.get("/actions/stats")
def action_stats():
    """완료율 통계"""
    conn = _db_conn()
    _init_actions_table(conn)
    total     = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
    completed = conn.execute("SELECT COUNT(*) FROM actions WHERE completed=1").fetchone()[0]
    return {
        "total": total,
        "completed": completed,
        "rate": round(completed / total * 100, 1) if total else 0,
    }


# ══════════════════════════════════════════════════════════════
# 감정 회복 시간 트래킹
# ══════════════════════════════════════════════════════════════

@app.get("/recovery-stats")
def recovery_stats():
    """
    유사 감정 그룹별 평균 회복 시간 비교.
    같은 주요 감정이 반복될 때 처음 vs 최근 회복 속도를 반환.
    """
    import sqlite3
    from collections import defaultdict
    from datetime import datetime

    diaries = get_all_diaries()
    if not diaries:
        return {"groups": []}

    # 감정별로 묶기
    by_emotion: dict[str, list] = defaultdict(list)
    for d in diaries:
        primary = (d.get("emotions") or ["기타"])[0]
        by_emotion[primary].append(d)

    groups = []
    for emotion, ds in by_emotion.items():
        # 3개 이상 기록이 있어야 비교 의미 있음
        if len(ds) < 3:
            continue

        # created_at 기준 정렬
        sorted_ds = sorted(
            ds,
            key=lambda d: d.get("created_at") or "2000-01-01",
        )

        # 회복된 일기만 (is_resolved=True)
        resolved = [d for d in sorted_ds if d.get("is_resolved")]
        if len(resolved) < 2:
            continue

        # 첫 번째 회복까지 걸린 인덱스 차이 (간략 추정)
        first_idx  = sorted_ds.index(resolved[0])  if resolved[0]  in sorted_ds else 0
        latest_idx = sorted_ds.index(resolved[-1]) if resolved[-1] in sorted_ds else 0

        first_gap  = first_idx  + 1   # 몇 번째 기록에서 처음 회복
        latest_gap = (len(sorted_ds) - latest_idx)  # 최근엔 얼마 만에 회복

        groups.append({
            "emotion":    emotion,
            "total":      len(ds),
            "resolved":   len(resolved),
            "first_recovery_count":  first_gap,
            "latest_recovery_count": latest_gap,
            "improving":  latest_gap <= first_gap,
        })

    # 개선 중인 그룹 우선 정렬
    groups.sort(key=lambda g: (not g["improving"], -g["total"]))
    return {"groups": groups[:5]}