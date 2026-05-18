def make_analysis_prompt(diary_text: str, emotions: list[str], persons: list[str]) -> str:
    emotions_str = ", ".join(emotions) if emotions else "없음"
    persons_str = ", ".join(persons) if persons else "없음"

    return f"""너는 'Read:Me' 서비스의 일기 분석 전문가야.
감정과 인물은 이미 로컬 AI가 추출했으니, 아래 추출 정보를 활용해
일기의 요약·사건·추가질문만 JSON 형식으로 응답해.
절대 마크다운(```json)이나 부연 설명 없이 순수 JSON만 출력해.

[사전 추출 정보]
- 감정: {emotions_str}
- 등장인물: {persons_str}

[출력 형식]
{{
    "summary": "오늘 하루를 정의하는 한 줄 요약",
    "events": ["주요 사건1", "사건2"],
    "followup_question": "사용자의 회고를 돕는 추가 질문 1개"
}}

일기 내용:
{diary_text}
"""
