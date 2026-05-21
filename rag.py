"""rag.py — 고도화된 RAG 시스템
가중 복합 유사도 계산 + 시간 흐름 내러티브 생성
"""

from typing import Callable


# ── 유사도 계산 ──────────────────────────────────────────────

def _emotion_jaccard(emos_a: list[str], emos_b_str: str) -> float:
    a = set(emos_a)
    b = set(filter(None, emos_b_str.split(", ")))
    if not (a or b):
        return 0.0
    return len(a & b) / len(a | b)


def _situation_score(pol_a: str, pol_b: str) -> float:
    if pol_a == pol_b:
        return 1.0
    if "mixed" in (pol_a, pol_b):
        return 0.5
    return 0.2


def weighted_score(current: dict, past: dict) -> float:
    """
    가중 복합 유사도:
      0.5 × text_similarity  (ChromaDB 코사인)
      0.3 × emotion_similarity (Jaccard)
      0.2 × situation_similarity (극성 일치)
    """
    t = float(past.get("similarity", 0))
    e = _emotion_jaccard(
        current.get("emotions", []),
        past.get("emotions_preview", ""),
    )
    s = _situation_score(
        current.get("emotion_polarity", "mixed"),
        past.get("emotion_polarity", "mixed"),
    )
    return round(0.5 * t + 0.3 * e + 0.2 * s, 4)


def rerank(candidates: list[dict], current: dict) -> list[dict]:
    """후보 목록을 가중 유사도 기준으로 재정렬"""
    for c in candidates:
        c["weighted_score"] = weighted_score(current, c)
    return sorted(candidates, key=lambda x: x["weighted_score"], reverse=True)


# ── 프롬프트 컨텍스트 빌더 ────────────────────────────────────

def build_rag_context(best: dict | None) -> str:
    """Ollama 프롬프트에 삽입할 과거 기록 블록 생성"""
    if not best or best.get("weighted_score", best.get("similarity", 0)) < 0.55:
        return ""
    score_pct = round(best.get("weighted_score", best.get("similarity", 0)) * 100)
    resolved  = "이후 해소됨" if best.get("is_resolved") else "아직 진행 중"
    return (
        f"\n[과거 유사 기록 — {score_pct}% 유사]\n"
        f"요약: {best.get('summary', '')}\n"
        f"감정: {best.get('emotions_preview', '')}\n"
        f"상태: {resolved}\n"
    )
