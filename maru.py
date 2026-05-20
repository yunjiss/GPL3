"""
maru.py — Read:Me 마루 메시지 생성
개선: 과거 패턴 구체적 참조, 이름 호명, CBT 소크라테스 질문, 회복 패턴 감지
"""

import os
from google import genai
from google.genai import types as genai_types

_client = None


def _load() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if api_key:
            _client = genai.Client(api_key=api_key)
        else:
            _client = genai.Client(
                vertexai=True,
                project=os.getenv("VERTEX_PROJECT_ID"),
                location=os.getenv("VERTEX_LOCATION", "asia-northeast3"),
            )
    return _client


def _build_pattern_summary(past_diaries: list[dict]) -> str:
    """과거 유사 일기에서 회복 패턴을 요약"""
    if not past_diaries:
        return "패턴 데이터 없음"

    total   = len(past_diaries)
    resolved = [d for d in past_diaries if d.get("is_resolved")]
    pct      = int(len(resolved) / total * 100) if total else 0

    summaries = [
        f"- [{i+1}] {d.get('summary', '')} "
        f"(감정: {d.get('emotions_preview', '')}, "
        f"해소됨: {'✓' if d.get('is_resolved') else '✗'}, "
        f"유사도: {d.get('similarity', 0):.0%})"
        for i, d in enumerate(past_diaries[:3])
    ]
    pattern_line = f"유사 상황 {total}건 중 {len(resolved)}건 결국 회복됨 ({pct}%)" if resolved else "회복 패턴 데이터 부족"

    return "\n".join(summaries) + f"\n→ {pattern_line}"


def generate_maru(
    current: dict,
    past_diaries: list[dict],
    user_name: str = "사용자",
    mbti: str = "",
) -> str:
    """
    마루 메시지 생성.

    핵심 로직:
    1. 유사 과거 일기가 없거나 유사도 낮으면 → 공감형 단문
    2. 과거 패턴이 있으면 → 패턴 참조 + CBT 소크라테스 반문 + 행동 제안
    """
    emotions     = current.get("emotions", [])
    emotions_str = ", ".join(emotions) or "복잡한"
    distortions  = current.get("cognitive_distortions", [])
    hidden_need  = current.get("hidden_need", "")

    # ── 과거 데이터 없음 → 간단 공감 ──────────────────────────
    best = past_diaries[0] if past_diaries else None
    if not best or best.get("similarity", 0) < 0.55:
        return (
            f"{user_name}아, 오늘 {emotions_str} 감정이 느껴졌구나. "
            "그 마음을 솔직하게 털어놓아줘서 고마워. "
            "오늘 하루도 수고했어 🌙"
        )

    # ── 패턴 분석 ─────────────────────────────────────────────
    pattern_summary = _build_pattern_summary(past_diaries)

    # CBT 반문 여부
    cbt_note = ""
    if distortions:
        examples = {
            "과잉일반화": "정말 항상 그랬어? 딱 한 번이라도 달랐던 순간이 있었을까?",
            "파국화":     "가장 나쁜 상황을 상상하고 있는 건 아닐까? 실제로 그렇게 될 가능성은?",
            "자기비난":   "같은 상황에 친구가 있었다면 뭐라고 말해줬을 것 같아?",
            "독심술":     "그 사람이 정말 그렇게 생각한다는 걸 어떻게 알았어?",
            "당위적 사고": "~해야 한다는 기준은 누가 만든 거야? 정말 그래야 할 이유가 있어?",
        }
        reframe = next(
            (v for k, v in examples.items() if k in distortions), None
        )
        if reframe:
            cbt_note = f"\n[인지 재구성 힌트] 마루가 부드럽게 물어볼 것: \"{reframe}\""

    # MBTI 어조 힌트
    tone_hint = ""
    if mbti:
        if mbti.startswith("I"):
            tone_hint = "조용하고 내면적인 어조로, 혼자 생각할 시간을 주는 방식으로"
        elif mbti.startswith("E"):
            tone_hint = "활기차고 대화를 이어가는 어조로"
        if "F" in mbti:
            tone_hint += ", 감정에 충분히 공감한 뒤 질문"
        elif "T" in mbti:
            tone_hint += ", 논리적 근거를 살짝 곁들여"

    prompt = f"""너는 'Read:Me'의 감정 동반자 '마루'야.
귀엽고 따뜻한 부엉이 캐릭터로, 사용자의 과거 기록 패턴을 기억하고 오늘과 연결해주는 역할이야.

[사용자]
이름: {user_name}{f"  |  MBTI: {mbti}" if mbti else ""}
{f"[어조 힌트] {tone_hint}" if tone_hint else ""}

[오늘 일기 분석]
- 요약: {current.get("summary", "")}
- 감정: {emotions_str}
- 인지 왜곡: {", ".join(distortions) or "없음"}
- 근본 욕구: {hidden_need or "미파악"}
- 해소 여부: {"이미 풀렸어" if current.get("is_resolved") else "아직 풀리지 않은 것 같아"}
{cbt_note}

[유사 과거 기록 & 패턴]
{pattern_summary}

[마루 응답 규칙 — 반드시 순서대로]
1. {user_name} 이름을 직접 불러 공감 (1문장)
   예) "{user_name}아, 오늘 [감정]을 느꼈구나, 그럴 만해."
2. 과거 패턴을 구체적으로 연결 (1~2문장)
   예) "예전에도 [유사 상황]이 있었는데, 그때 결국 [결과]였잖아."
   ※ 과거 요약을 그대로 쓰지 말고 자연스럽게 재표현할 것
3. 인지 왜곡이 있으면 소크라테스식 반문 (1문장) — 없으면 생략
4. 지금 바로 할 수 있는 아주 작은 행동 1개 제안 (1문장)
5. 전체 4~5문장, 반말체, 이모지 1개 이하
6. 절대 "~해야 해", "~해봐" 식의 명령형 금지 — 질문과 제안만

메시지:"""

    response = _load().models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=genai_types.GenerateContentConfig(temperature=0.42),
    )
    return response.text.strip()