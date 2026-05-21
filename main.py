from dotenv import load_dotenv
load_dotenv()

import os
import logging
import json
import requests
from pathlib import Path
from collections import Counter, defaultdict
from pydantic import BaseModel, validator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from auth import hash_pw, verify_pw, create_token, decode_token
from emotion import classify as classify_emotions
from ner import extract_persons
from embedding import get_embedding
from vector_db import add as vector_add, find_similar
from prompt import make_analysis_prompt
from cbt import classify_cognitive_distortions
import rag as rag_module
from maru import generate_maru, get_level_info
from db import (
    create_user, get_user_by_username, get_user_by_id, update_user_profile,
    save_diary, get_all_diaries, get_diary_by_id, delete_diary,
    get_maru_state, upsert_maru_state,
)
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


# ── 정적 파일 라우트 ──────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse(BASE_DIR / "login.html")

@app.get("/app")
def app_page():
    return FileResponse(BASE_DIR / "index.html")

@app.get("/setup")
def setup_page():
    return FileResponse(BASE_DIR / "setup.html")

@app.get("/styles.css")
def serve_css():
    return FileResponse(BASE_DIR / "styles.css", media_type="text/css")

@app.get("/script.js")
def serve_js():
    return FileResponse(BASE_DIR / "script.js", media_type="application/javascript")


# ── Ollama ────────────────────────────────────────────────────
def ask_ollama(prompt: str) -> str:
    res = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "llama3", "prompt": prompt, "stream": False},
        timeout=120,
    )
    return res.json()["response"]


# ── JWT 인증 ─────────────────────────────────────────────────
_security = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_security),
) -> dict:
    if not creds:
        raise HTTPException(status_code=401, detail="로그인이 필요해요")
    try:
        payload = decode_token(creds.credentials)
        return {
            "user_id":  int(payload["sub"]),
            "username": payload.get("username", ""),
            "name":     payload.get("name", "사용자"),
            "mbti":     payload.get("mbti", ""),
        }
    except Exception:
        raise HTTPException(status_code=401, detail="토큰이 유효하지 않아요. 다시 로그인해주세요.")


# ══════════════════════════════════════════════════════════════
# 요청 모델
# ══════════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    username: str
    password: str
    name: str = ""
    mbti: str = ""

    @validator("username")
    def username_valid(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError("아이디는 2자 이상이어야 해요")
        return v

    @validator("password")
    def password_valid(cls, v):
        if len(v) < 4:
            raise ValueError("비밀번호는 4자 이상이어야 해요")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


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


class UserProfileRequest(BaseModel):
    name: str = ""
    mbti: str = ""
    interests: list[str] = []

    @validator("mbti")
    def mbti_upper(cls, v):
        return v.upper().strip()


class SearchRequest(BaseModel):
    query: str
    filter_type: str = "all"
    top_k: int = 8

    @validator("query")
    def query_not_empty(cls, v):
        if not v.strip():
            raise ValueError("검색어를 입력해줘")
        return v.strip()


class ActionRequest(BaseModel):
    diary_id: int
    action_text: str


# ══════════════════════════════════════════════════════════════
# 인증 엔드포인트
# ══════════════════════════════════════════════════════════════

@app.post("/auth/register")
def register(req: RegisterRequest):
    try:
        user = create_user(
            req.username,
            hash_pw(req.password),
            req.name or req.username,
            req.mbti.upper().strip(),
        )
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=409, detail="이미 사용 중인 아이디예요")
        logger.error("회원가입 실패: %s", e)
        raise HTTPException(status_code=500, detail="회원가입 중 오류가 발생했어요")

    token = create_token(user["id"], user["username"], user["name"], user["mbti"])
    return {"token": token, "user_id": user["id"], "name": user["name"], "mbti": user["mbti"]}


@app.post("/auth/login")
def login(req: LoginRequest):
    user = get_user_by_username(req.username.strip())
    if not user or not verify_pw(req.password, user["password_h"]):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 틀렸어요")
    token = create_token(user["id"], user["username"], user["name"], user["mbti"])
    return {"token": token, "user_id": user["id"], "name": user["name"], "mbti": user["mbti"]}


# ══════════════════════════════════════════════════════════════
# 사용자 프로필
# ══════════════════════════════════════════════════════════════

@app.get("/user")
def get_user_profile(user: dict = Depends(get_current_user)):
    db_user = get_user_by_id(user["user_id"])
    if not db_user:
        return {"name": user["name"], "mbti": user["mbti"], "interests": []}
    import json as _json
    interests = []
    try:
        interests = _json.loads(db_user.get("interests") or "[]")
    except Exception:
        pass
    return {"name": db_user["name"], "mbti": db_user["mbti"], "interests": interests}


@app.put("/user")
def update_user(req: UserProfileRequest, user: dict = Depends(get_current_user)):
    update_user_profile(user["user_id"], req.name, req.mbti, req.interests)
    return {"ok": True}


# ══════════════════════════════════════════════════════════════
# 마루 레벨 상태
# ══════════════════════════════════════════════════════════════

def _get_or_init_state(user_id: int) -> dict:
    state = get_maru_state(user_id)
    if not state:
        state = {
            "user_id":       user_id,
            "level":         1,
            "personality":   "gentle",
            "memory":        [],
            "relationship":  "new",
            "total_sessions": 0,
        }
    return state


def _update_state(user_id: int, state: dict, new_summary: str, new_emotions: list) -> dict:
    """분석 완료 후 마루 상태 업데이트"""
    total = state.get("total_sessions", 0) + 1
    memory = state.get("memory", [])
    if new_summary:
        memory = (memory + [{"summary": new_summary, "emotions": new_emotions}])[-10:]

    level_info = get_level_info(total)
    relationship_map = [(50, "soulmate"), (30, "deep"), (15, "familiar"), (5, "growing"), (0, "new")]
    relationship = next(r for t, r in relationship_map if total >= t)

    updated = {
        "level":          level_info["level"],
        "personality":    level_info["personality"],
        "memory":         memory,
        "relationship":   relationship,
        "total_sessions": total,
    }
    upsert_maru_state(user_id, updated)
    return updated


# ══════════════════════════════════════════════════════════════
# 일기 분석 (/analyze)
# ══════════════════════════════════════════════════════════════

@app.post("/analyze")
def analyze(req: DiaryRequest, user: dict = Depends(get_current_user)):
    user_id   = user["user_id"]
    user_name = user.get("name", "사용자") or "사용자"
    mbti      = user.get("mbti", "")

    # 프로필에서 관심사 조회
    interests: list[str] = []
    try:
        db_user   = get_user_by_id(user_id)
        interests = json.loads(db_user.get("interests") or "[]") if db_user else []
    except Exception:
        pass

    # ── Step 1: 로컬 HF — 감정 분류 + NER ───────────────────
    try:
        emotion_data = classify_emotions(req.text)
    except Exception as e:
        logger.warning("감정 분류 실패: %s", e)
        emotion_data = {"emotions": [], "emotion_polarity": "mixed", "emotion_intensity": "medium"}

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

    # ── Step 3: 벡터 검색 → 가중 재정렬 ────────────────────
    try:
        raw_similar = find_similar(embedding, user_id=user_id) if embedding else []
    except Exception as e:
        logger.warning("벡터 검색 실패: %s", e)
        raw_similar = []

    current_ctx = {
        "emotions":        emotion_data["emotions"],
        "emotion_polarity": emotion_data["emotion_polarity"],
    }
    similar_diaries = rag_module.rerank(raw_similar, current_ctx)
    best_past       = similar_diaries[0] if similar_diaries and similar_diaries[0].get("weighted_score", 0) >= 0.55 else None
    rag_context     = rag_module.build_rag_context(best_past)

    # ── Step 4a: CBT 로컬 분류 ───────────────────────────────
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
        "is_resolved":           False,
        "emotions":              emotion_data["emotions"],
        "persons":               persons,
        "emotion_intensity":     emotion_data["emotion_intensity"],
        "emotion_polarity":      emotion_data["emotion_polarity"],
        "interpretation":        None,
        "question":              None,
        "highlight":             None,
    }
    try:
        cbt_data = classify_cognitive_distortions(req.text)
        analysis.update({k: v for k, v in cbt_data.items() if v})
    except Exception as e:
        logger.warning("CBT 분류 실패: %s", e)

    # ── Step 4b: Ollama 통합 분석 ─────────────────────────────
    emotions_str = ", ".join(emotion_data["emotions"]) or "다양한"
    maru_memo    = f"{user_name}아, 오늘 {emotions_str} 감정이 느껴졌구나. 오늘도 수고했어."
    rag_narrative = None
    ai_available  = False
    ai_error      = None

    try:
        prompt = make_analysis_prompt(
            req.text,
            emotion_data["emotions"],
            persons,
            rag_context=rag_context,
            user_name=user_name,
            mbti=mbti,
            interests=interests,
        )
        raw    = ask_ollama(prompt)
        parsed = safe_parse(raw)

        if parsed.get("emotion"):
            analysis["emotions"] = parsed["emotion"]
        if parsed.get("distortion"):
            analysis["cognitive_distortions"] = [parsed["distortion"]]

        analysis.update({
            "interpretation":    parsed.get("interpretation"),
            "question":          parsed.get("question"),
            "highlight":         parsed.get("highlight"),
            "followup_question": parsed.get("question"),
            "summary":           parsed.get("interpretation"),
            "is_resolved":       bool(parsed.get("is_resolved", False)),
        })

        if parsed.get("maru_message"):
            maru_memo = parsed["maru_message"]
        if parsed.get("rag_narrative"):
            rag_narrative = parsed["rag_narrative"]

        ai_available = True
    except Exception as e:
        print("🔥 AI ERROR:", e)
        logger.warning("Ollama 분석 실패: %s", e)
        ai_error = "Ollama 연결 실패. http://localhost:11434 에서 실행 중인지 확인해주세요."

    # ── Step 4c: 마루 상태 기반 메시지 보강 (AI 연결 시) ──────
    maru_state = _get_or_init_state(user_id)
    if ai_available and maru_state.get("total_sessions", 0) >= 5:
        try:
            maru_memo = generate_maru(
                analysis,
                similar_diaries,
                user_name=user_name,
                mbti=mbti,
                maru_state=maru_state,
            )
        except Exception as e:
            logger.warning("마루 메시지 생성 실패: %s", e)

    # ── Step 5: DB 저장 ──────────────────────────────────────
    try:
        diary_id = save_diary(req.text, analysis, user_id=user_id)
    except Exception as e:
        logger.error("일기 저장 실패: %s", e)
        diary_id = -1

    if embedding is not None and diary_id != -1:
        try:
            vector_add(
                diary_id,
                embedding,
                metadata={
                    "user_id":          str(user_id),
                    "summary":          analysis.get("summary") or "",
                    "emotions_preview": ", ".join(analysis.get("emotions", [])),
                    "emotion_polarity": analysis.get("emotion_polarity") or "mixed",
                    "is_resolved":      analysis.get("is_resolved", False),
                },
            )
        except Exception as e:
            logger.error("벡터 저장 실패: %s", e)

    # ── Step 6: 마루 상태 업데이트 ──────────────────────────
    updated_state = _update_state(
        user_id, maru_state,
        analysis.get("summary") or "",
        analysis.get("emotions", []),
    )

    level_info = get_level_info(updated_state["total_sessions"])

    return {
        "diary_id":       diary_id,
        "analysis":       analysis,
        "maru_memo":      maru_memo,
        "interpretation": analysis.get("interpretation"),
        "question":       analysis.get("question"),
        "highlight":      analysis.get("highlight"),
        "rag_narrative":  rag_narrative,
        "past_connection": {
            "is_connected":     bool(best_past and best_past.get("weighted_score", 0) >= 0.70),
            "past_summary":     best_past.get("summary") if best_past else None,
            "similarity_score": float(best_past.get("weighted_score", 0)) if best_past else 0.0,
        },
        "maru_state": {
            "level":      updated_state["level"],
            "level_name": level_info["name"],
            "sessions":   updated_state["total_sessions"],
        },
        "ai_connected": ai_available,
        "ai_error":     ai_error,
    }


# ══════════════════════════════════════════════════════════════
# 감정 성장 분석 (/growth)
# ══════════════════════════════════════════════════════════════

@app.get("/growth")
def get_growth(user: dict = Depends(get_current_user)):
    diaries = get_all_diaries(user["user_id"])
    total   = len(diaries)

    if total < 3:
        return {
            "message": None,
            "trends":  [],
            "total":   total,
            "streak":  0,
        }

    sorted_ds = sorted(diaries, key=lambda d: d.get("created_at") or "")

    # 감정별 기록 분리
    by_emotion: dict[str, list] = defaultdict(list)
    all_emotions: list[str]     = []
    for d in sorted_ds:
        for e in (d.get("emotions") or []):
            by_emotion[e].append(d)
            all_emotions.append(e)

    trends = []
    for emotion, recs in by_emotion.items():
        if len(recs) < 3:
            continue
        mid   = len(recs) // 2
        early = sum(1 for r in recs[:mid]  if r.get("is_resolved"))
        late  = sum(1 for r in recs[mid:]  if r.get("is_resolved"))
        total_resolved = sum(1 for r in recs if r.get("is_resolved"))
        improving = late > early

        trends.append({
            "emotion":       emotion,
            "count":         len(recs),
            "improving":     improving,
            "recovery_rate": round(total_resolved / len(recs) * 100, 1),
        })
    trends.sort(key=lambda t: (-t["count"], not t["improving"]))

    # 연속 기록 streak
    streak = 0
    from datetime import datetime, timedelta
    today = datetime.now().date()
    for d in sorted_ds[::-1]:
        try:
            day = datetime.fromisoformat(d.get("created_at", "").replace(" ", "T")).date()
            expected = today - timedelta(days=streak)
            if day == expected:
                streak += 1
            else:
                break
        except Exception:
            break

    # 성장 메시지 생성
    improving_list = [t for t in trends if t["improving"]]
    growth_msg: str | None = None

    if improving_list:
        top = improving_list[0]
        growth_msg = (
            f"'{top['emotion']}' 감정의 회복 패턴이 눈에 띄게 좋아지고 있어. "
            f"감정 근육이 성장하고 있는 거야 💪"
        )
    elif total >= 10:
        growth_msg = f"벌써 {total}개의 일기를 썼어. 이렇게 꾸준히 기록하는 것 자체가 이미 대단한 성장이야 ✨"
    elif total >= 5:
        growth_msg = f"{total}개의 기록이 쌓였어. 조금씩 네 감정 패턴이 보이기 시작하고 있어 🌱"

    # Ollama로 성장 메시지 풍부화
    if growth_msg and all_emotions:
        try:
            top_emo = Counter(all_emotions).most_common(1)[0][0]
            prompt  = f"""사용자의 감정 성장 패턴을 분석해서 따뜻한 피드백 메시지를 만들어줘.

[데이터]
총 일기: {total}개
연속 기록: {streak}일
회복 개선 감정: {', '.join(t['emotion'] for t in improving_list[:2]) or '없음'}
가장 자주 기록한 감정: {top_emo}

규칙: 구체적 수치 포함, 따뜻하게, 2문장, 반말체, 이모지 1개

메시지:"""
            result = ask_ollama(prompt).strip()
            if result:
                growth_msg = result
        except Exception:
            pass

    return {
        "message": growth_msg,
        "trends":  trends[:5],
        "total":   total,
        "streak":  streak,
    }


# ══════════════════════════════════════════════════════════════
# 검색 (/search)
# ══════════════════════════════════════════════════════════════

@app.post("/search")
def search_diaries(req: SearchRequest, user: dict = Depends(get_current_user)):
    results: list[dict] = []
    seen_ids: set[int]  = set()

    try:
        emb = get_embedding(req.query)
        for hit in find_similar(emb, user_id=user["user_id"]):
            if hit.get("id") not in seen_ids:
                results.append(hit)
                seen_ids.add(hit.get("id"))
    except Exception as e:
        logger.warning("벡터 검색 실패: %s", e)

    try:
        q = req.query.lower()
        for d in get_all_diaries(user["user_id"]):
            if d.get("id") in seen_ids:
                continue
            target = " ".join(filter(None, [
                d.get("text", ""), d.get("summary", ""),
                " ".join(d.get("emotions", [])),
                " ".join(d.get("persons", [])),
            ])).lower()
            if q in target:
                d["similarity"] = 0.0
                results.append(d)
                seen_ids.add(d["id"])
    except Exception as e:
        logger.warning("키워드 검색 실패: %s", e)

    if req.filter_type == "emotion":
        results = [d for d in results if req.query in " ".join(d.get("emotions", []))]
    elif req.filter_type == "person":
        results = [d for d in results if req.query in " ".join(d.get("persons", []))]

    results.sort(key=lambda d: d.get("similarity", 0), reverse=True)
    return results[: req.top_k]


# ══════════════════════════════════════════════════════════════
# 일기 CRUD
# ══════════════════════════════════════════════════════════════

@app.get("/diaries")
def list_diaries(user: dict = Depends(get_current_user)):
    return get_all_diaries(user["user_id"])


@app.get("/diaries/{diary_id}")
def get_diary(diary_id: int, user: dict = Depends(get_current_user)):
    entry = get_diary_by_id(diary_id, user["user_id"])
    if not entry:
        raise HTTPException(status_code=404, detail="Not found")
    return entry


@app.delete("/diaries/{diary_id}")
def remove_diary(diary_id: int, user: dict = Depends(get_current_user)):
    from vector_db import delete as vector_delete
    ok = delete_diary(diary_id, user["user_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    vector_delete(diary_id)
    return {"deleted": diary_id}


# ══════════════════════════════════════════════════════════════
# 통계 (/stats)
# ══════════════════════════════════════════════════════════════

@app.get("/stats")
def get_stats(user: dict = Depends(get_current_user)):
    diaries = get_all_diaries(user["user_id"])
    state   = _get_or_init_state(user["user_id"])

    if not diaries:
        return {
            "total": 0,
            "emotion_freq": {},
            "polarity_dist": {},
            "unique_emotions": 0,
            "maru": {
                "stage": 1, "stage_name": "아기 마루",
                "next_at": 5, "progress": 0.0,
                "level": 1, "sessions": 0,
            },
        }

    all_emotions = []
    polarities   = []
    for d in diaries:
        all_emotions.extend(d.get("emotions") or [])
        if d.get("emotion_polarity"):
            polarities.append(d["emotion_polarity"])

    total           = len(diaries)
    unique_emotions = len(set(all_emotions))
    sessions        = state.get("total_sessions", total)
    level_info      = get_level_info(sessions)
    level           = level_info["level"]

    # UI 호환: stage 기반 진행률
    if total < 5:
        stage, stage_name, next_at, progress = 1, "아기 마루", 5, total / 5
    elif total < 20:
        stage, stage_name, next_at, progress = 2, "소년 마루", 20, (total - 5) / 15
    else:
        stage, stage_name, next_at, progress = 3, "현자 마루", None, 1.0

    return {
        "total":           total,
        "emotion_freq":    dict(Counter(all_emotions).most_common(10)),
        "polarity_dist":   dict(Counter(polarities)),
        "unique_emotions": unique_emotions,
        "maru": {
            "stage":      stage,
            "stage_name": stage_name,
            "next_at":    next_at,
            "progress":   round(progress, 2),
            "level":      level,
            "level_name": level_info["name"],
            "sessions":   sessions,
        },
    }


# ══════════════════════════════════════════════════════════════
# 감정 회복 트래킹 (/recovery-stats)
# ══════════════════════════════════════════════════════════════

@app.get("/recovery-stats")
def recovery_stats(user: dict = Depends(get_current_user)):
    diaries = get_all_diaries(user["user_id"])
    if not diaries:
        return {"groups": []}

    by_emotion: dict[str, list] = defaultdict(list)
    for d in diaries:
        primary = (d.get("emotions") or ["기타"])[0]
        by_emotion[primary].append(d)

    groups = []
    for emotion, ds in by_emotion.items():
        if len(ds) < 3:
            continue
        sorted_ds  = sorted(ds, key=lambda d: d.get("created_at") or "2000-01-01")
        resolved   = [d for d in sorted_ds if d.get("is_resolved")]
        if len(resolved) < 2:
            continue
        first_idx  = sorted_ds.index(resolved[0])  if resolved[0]  in sorted_ds else 0
        latest_idx = sorted_ds.index(resolved[-1]) if resolved[-1] in sorted_ds else 0
        groups.append({
            "emotion":               emotion,
            "total":                 len(ds),
            "resolved":              len(resolved),
            "first_recovery_count":  first_idx + 1,
            "latest_recovery_count": len(sorted_ds) - latest_idx,
            "improving":             (len(sorted_ds) - latest_idx) <= (first_idx + 1),
        })

    groups.sort(key=lambda g: (not g["improving"], -g["total"]))
    return {"groups": groups[:5]}


# ══════════════════════════════════════════════════════════════
# 행동 활성화 트래킹
# ══════════════════════════════════════════════════════════════

def _db_conn_raw():
    import sqlite3
    conn = sqlite3.connect(str(BASE_DIR / "diary.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_actions(conn):
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
def create_action(req: ActionRequest, user: dict = Depends(get_current_user)):
    conn = _db_conn_raw()
    _init_actions(conn)
    cur = conn.execute(
        "INSERT INTO actions (diary_id, action_text) VALUES (?, ?)",
        [req.diary_id, req.action_text],
    )
    conn.commit()
    return {"id": cur.lastrowid, "action_text": req.action_text, "completed": False}


@app.get("/actions/pending")
def get_pending_actions(user: dict = Depends(get_current_user)):
    conn = _db_conn_raw()
    _init_actions(conn)
    rows = conn.execute("""
        SELECT a.id, a.diary_id, a.action_text, a.suggested_at,
               d.summary AS diary_summary
        FROM   actions a
        LEFT JOIN diary d ON a.diary_id = d.id
        WHERE  a.completed = 0
        ORDER  BY a.suggested_at DESC LIMIT 5
    """).fetchall()
    return [dict(r) for r in rows]


@app.put("/actions/{action_id}/complete")
def complete_action(action_id: int, user: dict = Depends(get_current_user)):
    conn = _db_conn_raw()
    _init_actions(conn)
    conn.execute(
        "UPDATE actions SET completed=1, completed_at=CURRENT_TIMESTAMP WHERE id=?",
        [action_id],
    )
    conn.commit()
    return {"ok": True, "id": action_id}
