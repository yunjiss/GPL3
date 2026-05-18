import json
import re

def safe_parse(text):
    try:
        # LLM이 마크다운 블록을 붙일 경우를 대비해 제거
        clean_text = re.sub(r'```json|```', '', text).strip()
        return json.loads(clean_text)
    except Exception as e:
        # 파싱 에러 발생 시 기본값 반환 (앱이 터지지 않도록)
        return {
            "summary": "분석에 실패했습니다.",
            "emotions": [],
            "events": [],
            "persons": [],
            "emotion_intensity": "medium",
            "emotion_polarity": "mixed",
            "followup_question": "오늘 하루는 어떠셨나요?"
        }