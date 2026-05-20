"""
cbt.py — CBT 기반 웰니스 자기성찰 보조 분석

로컬 Hugging Face zero-shot 모델로 사고 패턴 후보를 감지하고,
서비스에서 바로 보여줄 수 있는 자기성찰 워크시트 데이터를 만든다.
진단/치료/상담이 아니라 일상 웰니스와 자기이해를 돕는 보조 기능으로만 사용한다.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from transformers import pipeline

# 한국어 일기에 바로 매핑하기 쉬운 CBT 인지 왜곡 라벨
DISTORTION_LABELS = [
    "흑백논리",
    "과잉일반화",
    "파국화",
    "정신적 여과",
    "긍정 무시",
    "독심술",
    "미래 예측",
    "감정적 추론",
    "당위적 사고",
    "낙인찍기",
    "자기비난",
    "개인화",
]

# 룰 기반 보강: 짧은 일기/구어체에서는 zero-shot 점수가 흔들릴 수 있어 보수적으로 보완한다.
RULE_KEYWORDS = {
    "흑백논리": ["전부", "완전히", "아예", "무조건", "항상", "절대"],
    "과잉일반화": ["항상", "매번", "언제나", "한 번도", "다들", "모두"],
    "파국화": ["끝났어", "망했어", "최악", "다 소용없어", "돌이킬 수 없어"],
    "정신적 여과": ["그것만", "하나 때문에", "계속 그 장면", "그 말만"],
    "긍정 무시": ["별거 아니야", "운이 좋았을 뿐", "칭찬은 그냥", "잘한 게 아니야"],
    "독심술": ["분명 날", "나를 싫어", "무시하는 것 같", "속으로", "생각할 거야"],
    "미래 예측": ["앞으로도", "또 그럴", "안 될 거야", "실패할 거야"],
    "감정적 추론": ["느껴지니까", "불안하니까", "기분이 이러니까", "사실일 거야"],
    "당위적 사고": ["해야만", "해야 해", "당연히", "반드시", "그러면 안 돼"],
    "낙인찍기": ["나는 쓰레기", "나는 실패자", "난 최악", "바보 같"],
    "자기비난": ["내 탓", "내가 문제", "나 때문", "난 왜 이럴까"],
    "개인화": ["나 때문에", "내가 있어서", "내 책임", "전부 내 잘못"],
}

TREATMENT_HINTS = {
    "흑백논리": "0점/100점 대신 중간 점수를 매기며 회색지대를 찾아보기",
    "과잉일반화": "예외 사례 1개를 찾아 '항상'을 '가끔'으로 바꿔보기",
    "파국화": "최악·최선·가장 현실적인 결과를 나눠 적어보기",
    "정신적 여과": "놓치고 있는 중립/긍정 근거를 1개 추가하기",
    "긍정 무시": "작은 성취도 사실로 인정하는 문장으로 다시 쓰기",
    "독심술": "상대의 생각을 증거와 추측으로 분리하기",
    "미래 예측": "예측이 아니라 확인 가능한 다음 행동 1개로 바꾸기",
    "감정적 추론": "'느낌'과 '사실'을 두 줄로 나눠 적기",
    "당위적 사고": "'해야만 해'를 '하면 도움이 돼'로 완화하기",
    "낙인찍기": "나 전체가 아니라 특정 행동/상황으로 표현 바꾸기",
    "자기비난": "내 책임/타인 책임/상황 요인을 3등분해 보기",
    "개인화": "내가 통제한 것과 통제하지 못한 것을 구분하기",
}

_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
_classifier = None


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+|[\n\r]+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _rule_matches(text: str) -> tuple[list[str], list[dict[str, str]]]:
    labels: list[str] = []
    spans: list[dict[str, str]] = []
    for sentence in _sentences(text) or [text.strip()]:
        for label, keywords in RULE_KEYWORDS.items():
            if any(keyword in sentence for keyword in keywords):
                if label not in labels:
                    labels.append(label)
                spans.append({"sentence": sentence, "distortion_type": label})
                break
    return labels, spans[:5]


def _load_classifier():
    global _classifier
    if _classifier is None:
        _classifier = pipeline(
            "zero-shot-classification",
            model=_MODEL,
            device=-1,
        )
    return _classifier


def classify_cognitive_distortions(
    text: str,
    *,
    top_k: int = 4,
    threshold: float = 0.24,
) -> dict[str, Any]:
    """사고 패턴 후보와 웰니스 재구성 힌트를 반환한다.

    모델 로드/추론 실패 시에도 룰 기반 결과만으로 graceful degradation 한다.
    결과는 진단이 아니라 자기성찰용 후보로만 다룬다.
    """

    rule_labels, rule_spans = _rule_matches(text)
    model_labels: list[str] = []
    model_scores: dict[str, float] = {}

    try:
        result = _load_classifier()(
            text,
            candidate_labels=DISTORTION_LABELS,
            multi_label=True,
            hypothesis_template="이 일기에는 {} 인지 왜곡이 나타난다.",
        )
        for label, score in zip(result.get("labels", []), result.get("scores", [])):
            score = float(score)
            if score >= threshold:
                model_labels.append(label)
                model_scores[label] = round(score, 4)
            if len(model_labels) >= top_k:
                break
    except Exception:
        # 네트워크/캐시/런타임 이슈가 있어도 일기 분석 전체가 실패하지 않게 한다.
        pass

    # 명시적 표현이 잡힌 경우에는 룰 결과를 우선한다.
    # zero-shot NLI는 한국어 심리 문장에서 점수가 과신될 수 있어,
    # 키워드 단서가 없을 때만 모델 후보를 보조 신호로 사용한다.
    source_labels = rule_labels if rule_labels else model_labels
    merged = []
    for label in source_labels:
        if label not in merged:
            merged.append(label)

    primary = merged[0] if merged else None
    return {
        "cognitive_distortions": merged[:top_k],
        "distortion_sentences": rule_spans,
        "cbt_model": {
            "name": _MODEL,
            "strategy": "zero-shot + Korean rule fallback",
            "scores": model_scores,
        },
        "reframe_question": _make_reframe_question(primary),
        "recovery_hint": TREATMENT_HINTS.get(primary) if primary else None,
    }


@lru_cache(maxsize=128)
def _make_reframe_question(label: str | None) -> str | None:
    if not label:
        return None
    questions = {
        "독심술": "상대가 정말 그렇게 생각한다는 증거와, 아직 확인하지 못한 추측은 무엇일까?",
        "파국화": "최악의 결말 말고 가장 현실적인 결말은 무엇일까?",
        "자기비난": "이 일이 전부 내 탓이라는 근거와 상황 요인을 나눠보면 어떨까?",
        "과잉일반화": "항상 그렇다는 생각을 반박하는 예외가 하나라도 있을까?",
        "당위적 사고": "'반드시 해야 해'를 '하면 도움이 돼'로 바꾸면 부담이 얼마나 줄어들까?",
    }
    return questions.get(label, "이 생각을 뒷받침하는 근거와 반대 근거를 각각 하나씩 적어볼 수 있을까?")
