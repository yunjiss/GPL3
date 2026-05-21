import json
import re


def safe_parse(text: str) -> dict:
    """LLM 응답에서 JSON을 추출해 파싱한다. 마크다운 코드블록 및 전후 텍스트를 처리."""
    # 1) 마크다운 코드블록 제거
    clean = re.sub(r'```json|```', '', text).strip()

    # 2) 첫 번째 { ... } 블록 추출 (LLM이 앞뒤에 설명 텍스트를 붙이는 경우)
    match = re.search(r'\{[\s\S]*\}', clean)
    if match:
        clean = match.group(0)

    try:
        return json.loads(clean)
    except Exception:
        return {
            "emotion": [],
            "distortion": "",
            "interpretation": "",
            "question": "",
            "highlight": "",
            "maru_message": "",
        }
