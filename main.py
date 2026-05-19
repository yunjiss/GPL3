import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from google import genai
from google.genai import types as genai_types

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from emotion import classify as classify_emotions
from ner import extract_persons
from embedding import get_embedding
from vector_db import add as vector_add, find_similar
from prompt import make_analysis_prompt
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


@app.get("/")
def root():
    return FileResponse(BASE_DIR / "index.html")


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


class DiaryRequest(BaseModel):
    text: str


@app.post("/analyze")
def analyze(req: DiaryRequest):
    # Step 1 — Local HF: 감정 분류 + NER 인물 추출
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

    # Step 2 — Local KR-SBERT: 임베딩 생성
    try:
        embedding = get_embedding(req.text)
    except Exception as e:
        logger.warning("임베딩 실패: %s", e)
        embedding = None

    # Step 3 — Local ChromaDB: 유사 과거 일기 검색
    try:
        similar_diaries = find_similar(embedding) if embedding is not None else []
    except Exception as e:
        logger.warning("벡터 검색 실패: %s", e)
        similar_diaries = []

    analysis = {
        "summary": None,
        "events": [],
        "followup_question": None,
        "emotions": emotion_data["emotions"],
        "persons": persons,
        "emotion_intensity": emotion_data["emotion_intensity"],
        "emotion_polarity": emotion_data["emotion_polarity"],
    }
    ai_available = False
    emotions_str = ", ".join(emotion_data["emotions"]) or "다양한"
    maru_memo = f"오늘은 {emotions_str} 감정이 느껴졌구나. 오늘 하루도 수고했어."

    # Step 4a — Gemini: 구조적 분석
    try:
        analysis_prompt = make_analysis_prompt(req.text, emotion_data["emotions"], persons)
        response = _get_client().models.generate_content(
            model="gemini-2.5-flash",
            contents=analysis_prompt,
            config=genai_types.GenerateContentConfig(temperature=0.2),
        )
        parsed = safe_parse(response.text)
        analysis.update({
            "summary": parsed.get("summary"),
            "events": parsed.get("events", []),
            "followup_question": parsed.get("followup_question"),
        })
        ai_available = True
    except Exception as e:
        logger.warning("Gemini 분석 실패: %s", e)

    # Step 4b — Gemini: 마루 메시지 생성 (RAG)
    try:
        maru_memo = generate_maru(analysis, similar_diaries)
    except Exception as e:
        logger.warning("마루 메시지 생성 실패: %s", e)

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
                    "summary": analysis.get("summary") or "",
                    "emotions_preview": ", ".join(analysis.get("emotions", [])),
                    "emotion_polarity": analysis.get("emotion_polarity") or "mixed",
                },
            )
        except Exception:
            pass

    best = similar_diaries[0] if similar_diaries else None
    return {
        "analysis": analysis,
        "maru_memo": maru_memo,
        "past_connection": {
            "is_connected": bool(best and best.get("similarity", 0) >= 0.7),
            "past_summary": best.get("summary") if best else None,
            "similarity_score": float(best.get("similarity", 0)) if best else 0.0,
        },
        "ai_connected": ai_available,
    }


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


@app.get("/stats")
def get_stats():
    from collections import Counter
    diaries = get_all_diaries()
    if not diaries:
        return {
            "total": 0, "emotion_freq": {}, "polarity_dist": {},
            "intensity_dist": {}, "recent_emotions": []
        }

    all_emotions = []
    polarities = []
    intensities = []
    for d in diaries:
        all_emotions.extend(d.get("emotions") or [])
        if d.get("emotion_polarity"):
            polarities.append(d["emotion_polarity"])
        if d.get("emotion_intensity"):
            intensities.append(d["emotion_intensity"])

    total = len(diaries)
    # 마루 성장 단계 계산
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
        "total": total,
        "emotion_freq": dict(Counter(all_emotions).most_common(10)),
        "polarity_dist": dict(Counter(polarities)),
        "intensity_dist": dict(Counter(intensities)),
        "unique_emotions": unique_emotions,
        "maru": {
            "stage": stage,
            "stage_name": stage_name,
            "next_at": next_at,
            "progress": round(progress, 2),
        },
    }

