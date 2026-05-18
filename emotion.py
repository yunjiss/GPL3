from transformers import pipeline

# 24개 감정 레이블 — 긍정/부정 이분법 대신 세분화된 한국어 감정 표현
EMOTION_LABELS = [
    "기쁨", "행복감", "환희", "설렘", "감사함",
    "슬픔", "우울함", "외로움", "허무함", "그리움",
    "불안함", "걱정", "두려움", "긴장감",
    "분노", "짜증남", "원망", "억울함",
    "무기력함", "지침", "싱숭생숭함", "혼란스러움",
    "평온함", "무감각함",
]

_POSITIVE = frozenset({"기쁨", "행복감", "환희", "설렘", "감사함"})

_classifier = None


def _load():
    global _classifier
    if _classifier is None:
        # mDeBERTa-v3: multilingual NLI 모델 — 한국어 zero-shot 분류 지원
        # 한국어 전용 모델(hun3359/klue-bert-base-sentiment)은 7개 고정 레이블만
        # 지원하므로, 커스텀 레이블 확장이 가능한 zero-shot 방식 채택
        _classifier = pipeline(
            "zero-shot-classification",
            model="MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
            device=-1,  # CPU
        )
    return _classifier


def classify(text: str, top_k: int = 3, threshold: float = 0.12) -> dict:
    result = _load()(
        text,
        candidate_labels=EMOTION_LABELS,
        multi_label=True,
        hypothesis_template="이 일기에서 느껴지는 감정은 {}이다.",
    )

    pairs = [
        (lbl, sc)
        for lbl, sc in zip(result["labels"], result["scores"])
        if sc >= threshold
    ][:top_k]

    emotions = [lbl for lbl, _ in pairs]
    top_score = pairs[0][1] if pairs else 0.0

    pos = sum(1 for e in emotions if e in _POSITIVE)
    neg = len(emotions) - pos
    polarity = "positive" if pos > neg else "negative" if neg > pos else "mixed"
    intensity = "high" if top_score >= 0.5 else "medium" if top_score >= 0.25 else "low"

    return {
        "emotions": emotions,
        "emotion_polarity": polarity,
        "emotion_intensity": intensity,
    }
