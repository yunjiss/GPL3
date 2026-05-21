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
    update_diary_chat, update_diary_coping, update_diary_followup,
    get_pending_followup,
    save_action_log, get_pending_action_log, complete_action_log,
    save_chat_message, get_diary_chat_messages,
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
_SYSTEM_PROMPT = """너는 감정 분석 AI '마루'다.

반드시 한국어로만 답변해야 한다.
절대 영어를 사용하지 마라.

말투:
- 따뜻하고 부드럽게
- 친구처럼 자연스럽게
- 약간 귀엽게 (과하지 않게)

역할:
1. 감정 공감
2. 감정 분석
3. 자연스러운 질문
4. 해결 방향 제시

출력 규칙:
- 3~6문장 자연스럽게 작성
- 설명 금지 (예: "~식 질문", "~를 유도하는" 같은 메타 설명 금지)
- 대화처럼 말하기"""


# ── 질문 템플릿 ──────────────────────────────────────────────
import random as _random

_QUESTIONS = [
    "오늘 감정이 시작된 순간이 있었을까?",
    "그때 어떤 생각이 들었을까?",
    "혹시 다른 해석도 가능할까?",
    "그 상황을 조금 멀리서 보면 어때 보여?",
    "너무 스스로를 몰아붙이고 있는 건 아닐까?",
    "그 사람이 정말 그런 의도였을까?",
    "지금 가장 크게 느껴지는 감정은 뭐야?",
    "이 감정이 너에게 말해주는 건 뭘까?",
    "지금 네가 가장 필요로 하는 건 뭐야?",
    "조금 나아지려면 어떤 게 도움이 될까?",
    "비슷한 상황을 겪은 적 있었어?",
    "그때는 어떻게 지나갔었지?",
    "지금 가장 힘든 부분은 뭐야?",
    "이 상황이 전부 네 탓일까?",
    "지금 너에게 가장 따뜻한 말은 뭐일까?",
    "이 감정이 계속 이어질 것 같아?",
    "조금이라도 가벼워지려면 뭐가 필요할까?",
    "너무 앞서 걱정하고 있는 건 아닐까?",
    "지금 이 순간에 집중하면 어떤 느낌일까?",
    "너 자신에게 조금 더 부드럽게 대해줄 수 있을까?",
]

_EMOTION_QUESTIONS: dict[str, str] = {
    "불안함":      "혹시 아직 일어나지 않은 일을 미리 걱정하고 있는 건 아닐까?",
    "불안":        "혹시 아직 일어나지 않은 일을 미리 걱정하고 있는 건 아닐까?",
    "걱정":        "혹시 아직 일어나지 않은 일을 미리 걱정하고 있는 건 아닐까?",
    "두려움":      "지금 가장 두렵게 느껴지는 게 정확히 뭔지 말해줄 수 있어?",
    "우울함":      "요즘 가장 기운 빠지게 만드는 게 뭐야?",
    "우울":        "요즘 가장 기운 빠지게 만드는 게 뭐야?",
    "슬픔":        "지금 이 슬픔 안에 뭔가 그리운 게 있는 걸까?",
    "외로움":      "지금 옆에 있어줬으면 하는 사람이 있어?",
    "분노":        "그 상황에서 가장 억울했던 부분이 뭐였을까?",
    "짜증남":      "그 상황에서 가장 억울했던 부분이 뭐였을까?",
    "원망":        "혹시 그 마음 뒤에 상처받은 부분이 있는 건 아닐까?",
    "혼란스러움":  "무엇이 가장 헷갈리게 만들고 있는 걸까?",
    "싱숭생숭함":  "지금 마음이 여러 방향으로 당기는 것 같은데, 어떤 게 제일 강하게 느껴져?",
    "무기력함":    "요즘 뭔가 하고 싶다는 마음이 들지 않아?",
    "지침":        "언제부터 이렇게 지쳐있었던 것 같아?",
}


def generate_question(emotions: list[str]) -> str:
    for e in emotions:
        if e in _EMOTION_QUESTIONS:
            return _EMOTION_QUESTIONS[e]
    return _random.choice(_QUESTIONS)


def _time_ago(created_at_str: str) -> str:
    from datetime import datetime as _dt
    try:
        past = _dt.fromisoformat(str(created_at_str).replace(" ", "T"))
        days = (_dt.now() - past).days
        if days >= 90: return f"{days // 30}개월 전"
        if days >= 14: return f"{days // 7}주 전"
        if days >= 1:  return f"{days}일 전"
        return "오늘"
    except Exception:
        return "예전에"

_OLLAMA_CHAT_OPTIONS = {"temperature": 0.7, "num_predict": 300}
_OLLAMA_JSON_OPTIONS  = {"temperature": 0.3, "num_predict": 500}


def ask_ollama(prompt: str) -> str:
    """자연어 한국어 응답 (채팅·마루 메시지 등)"""
    res = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "llama3",
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            "stream":  False,
            "options": _OLLAMA_CHAT_OPTIONS,
        },
        timeout=120,
    )
    return res.json()["message"]["content"]


def _ask_ollama_json(prompt: str) -> str:
    """JSON 분석 응답 전용 (/api/generate — 시스템 프롬프트 없음, JSON 파싱 안정성 우선)"""
    res = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model":  "llama3",
            "prompt": prompt,
            "stream": False,
            "options": _OLLAMA_JSON_OPTIONS,
        },
        timeout=120,
    )
    return res.json()["response"]


def ask_ollama_chat(messages: list[dict]) -> str:
    """대화 히스토리 포함 멀티턴 채팅"""
    res = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "llama3",
            "messages": [{"role": "system", "content": _SYSTEM_PROMPT}] + messages,
            "stream":  False,
            "options": _OLLAMA_CHAT_OPTIONS,
        },
        timeout=120,
    )
    return res.json()["message"]["content"]


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
    emotion_tags: list[str] = []

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


class ChatRequest(BaseModel):
    diary_id: int
    user_message: str

    @validator("user_message")
    def msg_not_empty(cls, v):
        if not v.strip():
            raise ValueError("메시지를 입력해줘")
        return v.strip()


class CopingRequest(BaseModel):
    action: str

    @validator("action")
    def action_not_empty(cls, v):
        if not v.strip():
            raise ValueError("행동을 입력해줘")
        return v.strip()


class FollowupRequest(BaseModel):
    done: bool
    reason: str = ""
    result: str = ""


class SaveActionRequest(BaseModel):
    diary_id: int
    action: str

    @validator("action")
    def action_not_empty(cls, v):
        if not v.strip():
            raise ValueError("행동을 입력해줘")
        return v.strip()


class CompleteActionRequest(BaseModel):
    log_id:    int
    diary_id:  int
    completed: bool
    note:      str = ""


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
        raw    = _ask_ollama_json(prompt)
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

        # question 폴백: Ollama가 비어 있으면 감정별 템플릿 사용
        if not analysis.get("question"):
            analysis["question"]          = generate_question(analysis.get("emotions", []))
            analysis["followup_question"] = analysis["question"]

        ai_available = True
    except Exception as e:
        print("🔥 AI ERROR:", e)
        logger.warning("Ollama 분석 실패: %s", e)
        ai_error = "Ollama 연결 실패. http://localhost:11434 에서 실행 중인지 확인해주세요."
        # AI 없을 때도 question 생성
        analysis["question"]          = generate_question(analysis.get("emotions", []))
        analysis["followup_question"] = analysis["question"]

    # ── Step 4b-2: RAG 시간 인식 내러티브 (LLM 재해석) ─────────
    if ai_available and best_past and best_past.get("weighted_score", 0) >= 0.65:
        past_summary = best_past.get("summary") or best_past.get("emotions_preview") or ""
        if past_summary:
            time_str = _time_ago(best_past.get("created_at", ""))
            try:
                rag_prompt = (
                    f"{time_str}에 비슷한 기록이 있어.\n"
                    f"그때 기록: \"{past_summary}\"\n"
                    f"오늘 기록과 자연스럽게 연결해서 따뜻하게 2~3문장으로 말해줘. "
                    f"시간 흐름({time_str})을 포함해서, 대화체로."
                )
                rag_narrative = ask_ollama(rag_prompt)
            except Exception:
                rag_narrative = f"{time_str}에도 비슷한 감정이 있었어. 그때도 결국 괜찮아졌잖아."

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
        diary_id = save_diary(req.text, analysis, user_id=user_id,
                              emotion_tags=req.emotion_tags)
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
# 마루 채팅 이어가기 (/chat)
# ══════════════════════════════════════════════════════════════

@app.post("/chat")
def chat_endpoint(req: ChatRequest, user: dict = Depends(get_current_user)):
    user_id   = user["user_id"]
    user_name = user.get("name", "사용자") or "사용자"

    diary = get_diary_by_id(req.diary_id, user_id)
    if not diary:
        raise HTTPException(status_code=404, detail="일기를 찾을 수 없어요")

    # DB에서 대화 히스토리 로드
    db_history = get_diary_chat_messages(req.diary_id, user_id)

    # 일기 맥락을 첫 메시지 쌍으로 주입
    emotions_str = ", ".join(diary.get("emotions", [])) or "복잡한"
    summary_str  = diary.get("interpretation") or diary.get("summary") or ""
    ctx_msg = (
        f"오늘 {user_name}의 일기야. 감정: {emotions_str}. "
        f"내용 요약: {summary_str}\n"
        f"이 일기를 바탕으로 {user_name}와 따뜻하게 대화해줘."
    )
    ollama_messages: list[dict] = [
        {"role": "user",      "content": ctx_msg},
        {"role": "assistant", "content": "응, 잘 읽었어. 이야기 들을게."},
    ]
    for msg in db_history[-12:]:
        role = "user" if msg["role"] == "user" else "assistant"
        ollama_messages.append({"role": role, "content": msg["content"]})
    ollama_messages.append({"role": "user", "content": req.user_message})

    try:
        response = ask_ollama_chat(ollama_messages).strip()
    except Exception as e:
        logger.warning("채팅 Ollama 실패: %s", e)
        response = "지금은 연결이 어렵네. 하지만 네 말은 잘 들었어. 더 이야기해줄 수 있어?"

    try:
        save_chat_message(user_id, req.diary_id, "user",  req.user_message)
        save_chat_message(user_id, req.diary_id, "maru",  response)
        # diary.chat_history 컬럼도 동기화
        all_history = db_history + [
            {"role": "user",  "content": req.user_message},
            {"role": "maru",  "content": response},
        ]
        update_diary_chat(req.diary_id, user_id,
                          [{"role": m["role"], "content": m["content"]} for m in all_history])
    except Exception as e:
        logger.warning("채팅 저장 실패: %s", e)

    return {"response": response}


@app.get("/diaries/{diary_id}/messages")
def get_diary_messages(diary_id: int, user: dict = Depends(get_current_user)):
    diary = get_diary_by_id(diary_id, user["user_id"])
    if not diary:
        raise HTTPException(status_code=404, detail="일기를 찾을 수 없어요")
    msgs = get_diary_chat_messages(diary_id, user["user_id"])
    # fallback: chat_messages 비어있으면 diary.chat_history 사용
    if not msgs:
        msgs = [{"role": m.get("role","user"), "content": m.get("content",""), "timestamp":""}
                for m in (diary.get("chat_history") or [])]
    return msgs


# ══════════════════════════════════════════════════════════════
# 행동 선택 저장 (/diaries/{id}/coping)
# ══════════════════════════════════════════════════════════════

@app.post("/diaries/{diary_id}/coping")
def save_coping(diary_id: int, req: CopingRequest, user: dict = Depends(get_current_user)):
    diary = get_diary_by_id(diary_id, user["user_id"])
    if not diary:
        raise HTTPException(status_code=404, detail="일기를 찾을 수 없어요")
    update_diary_coping(diary_id, user["user_id"], req.action)
    return {"ok": True, "action": req.action}


# ══════════════════════════════════════════════════════════════
# 다음날 체크 (/pending-followup, /diaries/{id}/followup)
# ══════════════════════════════════════════════════════════════

@app.get("/pending-followup")
def pending_followup(user: dict = Depends(get_current_user)):
    diary = get_pending_followup(user["user_id"])
    if not diary:
        return {"pending": False}
    return {
        "pending":       True,
        "diary_id":      diary["id"],
        "coping_action": diary.get("coping_action", ""),
        "diary_date":    diary.get("created_at", ""),
        "summary":       diary.get("summary") or diary.get("interpretation") or "",
    }


@app.post("/save-action")
def save_action_endpoint(req: SaveActionRequest, user: dict = Depends(get_current_user)):
    from datetime import date as _date
    diary = get_diary_by_id(req.diary_id, user["user_id"])
    if not diary:
        raise HTTPException(status_code=404, detail="일기를 찾을 수 없어요")
    log_id = save_action_log(user["user_id"], req.diary_id, req.action, str(_date.today()))
    update_diary_coping(req.diary_id, user["user_id"], req.action)
    return {"ok": True, "log_id": log_id, "action": req.action}


@app.get("/check-action")
def check_action(user: dict = Depends(get_current_user)):
    log = get_pending_action_log(user["user_id"])
    if log:
        return {
            "pending":  True,
            "log_id":   log["id"],
            "diary_id": log["diary_id"],
            "action":   log["action"],
            "date":     log["created_at"],
            "summary":  log.get("summary") or "",
        }
    diary = get_pending_followup(user["user_id"])
    if not diary:
        return {"pending": False}
    return {
        "pending":  True,
        "log_id":   -1,
        "diary_id": diary["id"],
        "action":   diary.get("coping_action", ""),
        "date":     diary.get("created_at", ""),
        "summary":  diary.get("summary") or diary.get("interpretation") or "",
    }


@app.post("/complete-action")
def complete_action_endpoint(req: CompleteActionRequest, user: dict = Depends(get_current_user)):
    user_id = user["user_id"]
    if req.log_id > 0:
        complete_action_log(req.log_id, user_id, req.completed, req.note)
    update_diary_followup(
        req.diary_id, user_id,
        done=1 if req.completed else 0,
        reason="" if req.completed else req.note,
        result=req.note if req.completed else "",
    )
    if req.completed:
        diaries = get_all_diaries(user_id)
        same = [d for d in diaries
                if d.get("coping_action") == req.note.split("·")[0].strip()
                and d.get("followup_done") == 1]
        pattern_msg = None
        if len(same) >= 2:
            pattern_msg = f"이 방법이 너한테 잘 맞는 것 같아. 계속 이어나가봐 🌱"
        return {"ok": True, "pattern_message": pattern_msg}
    return {"ok": True, "maru_response": "어제 못 했구나, 괜찮아. 오늘 새로 도전해볼까?"}


@app.post("/diaries/{diary_id}/followup")
def save_followup(diary_id: int, req: FollowupRequest, user: dict = Depends(get_current_user)):
    user_id = user["user_id"]
    diary   = get_diary_by_id(diary_id, user_id)
    if not diary:
        raise HTTPException(status_code=404, detail="일기를 찾을 수 없어요")

    update_diary_followup(
        diary_id, user_id,
        done=1 if req.done else 0,
        reason=req.reason,
        result=req.result,
    )

    if req.done:
        diaries = get_all_diaries(user_id)
        same_action = [
            d for d in diaries
            if d.get("coping_action") == diary.get("coping_action")
               and d.get("followup_done") == 1
               and d.get("action_result")
        ]
        pattern_msg = None
        if len(same_action) >= 2:
            action = diary.get("coping_action", "")
            pattern_msg = f"'{action}'을 선택할 때마다 도움이 됐던 것 같아. 이게 너한테 잘 맞는 방법인가 봐 🌱"
        return {"ok": True, "pattern_message": pattern_msg}

    maru_response = f"어제 못 했구나, 괜찮아. 혹시 뭐가 어려웠는지 같이 생각해볼까?"
    return {"ok": True, "maru_response": maru_response}


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
