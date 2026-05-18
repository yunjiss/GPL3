from vertexai.generative_models import GenerativeModel, GenerationConfig

# vertexai.init()은 main.py 시작 시 1회 호출됨
_model = None


def _load():
    global _model
    if _model is None:
        _model = GenerativeModel("gemini-1.5-flash")
    return _model


def generate_maru(current: dict, past_diaries: list[dict]) -> str:
    best = past_diaries[0] if past_diaries else None

    if not best or best.get("similarity", 0) < 0.7:
        emotions_str = ", ".join(current.get("emotions", []))
        return f"오늘은 {emotions_str} 감정이 느껴졌구나. 푹 쉬면서 마음을 다독이는 시간을 가져보면 어떨까?"

    past_context = "\n".join(
        f"- 기록 {i + 1}: {d.get('summary', '')} "
        f"(감정: {d.get('emotions_preview', '')}, 유사도: {d.get('similarity', 0):.2f})"
        for i, d in enumerate(past_diaries[:3])
    )

    prompt = f"""너는 사용자의 과거를 기억하고 오늘을 다독이는 조언자 '마루'야.
아래 정보를 바탕으로 과거의 경험과 연결된 따뜻한 메시지를 작성해줘.

- 현재 요약: {current.get('summary')}
- 현재 감정: {", ".join(current.get("emotions", []))}
- 과거 유사 기록:
{past_context}

[규칙]
1. 한 줄로 공감하기.
2. 과거의 경험을 언급하며 "예전에도 비슷한 일이 있었는데, 그때와 비교하면 지금은 어때?"라는 뉘앙스로 묻기.
3. 현재 도움이 될만한 가벼운 행동 선택지 2개 제안하기.
4. 전체 3~4문장 이내.

메시지:"""

    response = _load().generate_content(
        prompt,
        generation_config=GenerationConfig(temperature=0.4),
    )
    return response.text
