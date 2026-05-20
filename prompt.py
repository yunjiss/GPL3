"""
prompt.py — Read:Me 분석 프롬프트
추가: ABC 구조화, 인지 왜곡 문장 추출, 사고 재구성 제안
"""

COGNITIVE_DISTORTIONS = {
    "과잉일반화": ["항상", "절대", "매번", "언제나", "한 번도", "전혀"],
    "파국화":     ["끝났어", "최악이야", "망했어", "다 소용없어", "돌이킬 수 없어"],
    "자기비난":   ["내 탓", "내가 문제야", "나만", "내가 이러니", "나는 쓰레기", "난 왜 이럴까"],
    "독심술":     ["분명히 생각할거야", "날 싫어하는 게", "나를 무시하는", "다 알고 있어"],
    "당위적 사고": ["해야만 해", "해야 한다", "당연히", "반드시"],
    "감정적 추론": ["느껴지니까 사실", "기분이 이러니까"],
}


def detect_distortions(text: str) -> list[str]:
    return [d for d, kws in COGNITIVE_DISTORTIONS.items() if any(k in text for k in kws)]


def extract_distortion_sentences(text: str) -> list[dict]:
    """
    인지 왜곡 키워드가 포함된 실제 문장을 추출해서
    {sentence, distortion_type} 형태로 반환
    """
    results = []
    sentences = [s.strip() for s in text.replace(".", ".\n").replace("!", "!\n").replace("?", "?\n").split("\n") if s.strip()]
    for sentence in sentences:
        for distortion, keywords in COGNITIVE_DISTORTIONS.items():
            if any(kw in sentence for kw in keywords):
                results.append({"sentence": sentence, "distortion_type": distortion})
                break
    return results


def make_analysis_prompt(
    diary_text: str,
    emotions: list[str],
    persons: list[str],
    user_name: str = "사용자",
    mbti: str = "",
    interests: list[str] | None = None,
) -> str:
    emotions_str   = ", ".join(emotions)  if emotions  else "없음"
    persons_str    = ", ".join(persons)   if persons   else "없음"
    interests_str  = ", ".join(interests or [])
    distortions    = detect_distortions(diary_text)
    distortion_str = ", ".join(distortions) if distortions else "없음"

    profile_ctx = f"이름: {user_name}"
    if mbti:         profile_ctx += f"  |  MBTI: {mbti}"
    if interests_str: profile_ctx += f"  |  관심사: {interests_str}"

    return f"""너는 'Read:Me' 서비스의 웰니스 자기성찰 코치야.
진단/치료/상담을 제공하지 않고, CBT(인지행동치료)에서 영감을 받은 구조로 사용자의 일기를 정리해.
단정하지 말고 "~일 수 있어", "~처럼 보여"처럼 가능성 언어를 사용해.

[사용자 프로필]
{profile_ctx}

[로컬 모델 사전 추출]
- 감지된 감정: {emotions_str}
- 등장인물: {persons_str}
- 룰 기반 인지 왜곡: {distortion_str}

[분석 지침]
1. ABC 구조로 일기를 재정리해
    - A (Activating Event): 실제 있었던 사건 — 객관적 상황만
    - B (Belief/자동적 사고): 그 순간 머릿속에 스친 생각
    - C (Consequence/감정): 그 생각 때문에 온 감정 결과
2. cognitive_distortions: 다음 범주 안에서만 골라: 흑백논리, 과잉일반화, 파국화, 정신적 여과, 긍정 무시, 독심술, 미래 예측, 감정적 추론, 당위적 사고, 낙인찍기, 자기비난, 개인화
3. distortion_sentences: 인지 왜곡이 담긴 실제 문장을 그대로 발췌
4. reframe_question: B(자동적 사고)에 대한 소크라테스식 반문 1개
    예) "그 사람이 정말 나를 무시한 게 맞을까? 다른 이유가 있을 수도 있을까?"
4. is_resolved: 일기에서 감정이 이미 해소됐는지
5. recovery_hint: 오늘 바로 할 수 있는 5분짜리 웰니스 행동 1개
6. 위기/자해/자살 표현이 있으면 분석보다 안전 안내를 우선하도록 recovery_hint에 전문가/긴급 도움 권유를 포함

[출력 — 순수 JSON, 마크다운 없이]
{{
    "summary": "오늘 하루 한 줄 요약 (감정 + 핵심 사건)",
    "events": ["주요 사건1", "사건2"],
    "is_resolved": true,
    "abc": {{
        "A": "오늘 있었던 일 (사건)",
        "B": "그때 들었던 생각",
        "C": "그래서 온 감정"
    }},
    "followup_question": "자기이해를 돕는 반문형 질문 1개",
    "reframe_question": "B(자동적 사고)를 부드럽게 반박하는 소크라테스식 질문 1개",
    "implicit_emotions": ["맥락 추론 감정1", "감정2"],
    "cognitive_distortions": ["인지 왜곡명1", "인지 왜곡명2"],
    "distortion_sentences": [
        {{"sentence": "인지 왜곡 포함 실제 문장1", "distortion_type": "인지 왜곡명"}}
    ],
    "hidden_need": "단정하지 않는 심리적 욕구 추정 한 줄",
    "recovery_hint": "지금 당장 할 수 있는 웰니스 행동 제안"
}}

[일기]
{diary_text}
"""