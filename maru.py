"""maru.py — 레벨·메모리 기반 마루 캐릭터 시스템"""

import requests

# ── 레벨 정의 ──────────────────────────────────────────────────
_LEVELS = [
    (50, 5, "현자 마루",  "sage",        "철학적이고 성찰적인 시각으로"),
    (30, 4, "어른 마루",  "wise",        "깊이 있고 사려 깊게"),
    (15, 3, "청년 마루",  "insightful",  "패턴을 언급하며 통찰 있게"),
    (5,  2, "소년 마루",  "warm",        "공감적이고 호기심 있게"),
    (0,  1, "아기 마루",  "gentle",      "짧고 따뜻하게"),
]

# 관계 단계
_RELATIONSHIP = [
    (50, "soulmate",  "오래된 친구처럼"),
    (30, "deep",      "깊이 이해하는 관계로"),
    (15, "familiar",  "친숙하게"),
    (5,  "growing",   "점점 친해지듯"),
    (0,  "new",       "조심스럽고 따뜻하게"),
]


def get_level_info(total_sessions: int) -> dict:
    for threshold, lvl, name, personality, style in _LEVELS:
        if total_sessions >= threshold:
            return {"level": lvl, "name": name, "personality": personality, "style": style}
    return {"level": 1, "name": "아기 마루", "personality": "gentle", "style": "짧고 따뜻하게"}


def get_relationship(total_sessions: int) -> str:
    for threshold, rel, _ in _RELATIONSHIP:
        if total_sessions >= threshold:
            return rel
    return "new"


# ── Ollama ──────────────────────────────────────────────────────

def ask_ollama(prompt: str) -> str:
    res = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "llama3", "prompt": prompt, "stream": False},
        timeout=120,
    )
    return res.json()["response"]


# ── 패턴 요약 ───────────────────────────────────────────────────

def _pattern_summary(past_diaries: list[dict]) -> str:
    if not past_diaries:
        return ""
    total    = len(past_diaries)
    resolved = sum(1 for d in past_diaries if d.get("is_resolved"))
    lines = [
        f"- {d.get('summary', '')} (유사도 {d.get('weighted_score', d.get('similarity', 0)):.0%})"
        for d in past_diaries[:3]
        if d.get("summary")
    ]
    trend = f"유사 상황 {total}건 중 {resolved}건 회복" if resolved else "회복 패턴 누적 중"
    return "\n".join(lines) + f"\n→ {trend}"


# ── 메인 생성 함수 ───────────────────────────────────────────────

def generate_maru(
    current: dict,
    past_diaries: list[dict],
    user_name: str  = "사용자",
    mbti: str       = "",
    maru_state: dict | None = None,
) -> str:
    state     = maru_state or {}
    sessions  = state.get("total_sessions", 0)
    level_info = get_level_info(sessions)
    level     = level_info["level"]
    memory    = state.get("memory", [])

    emotions_str = ", ".join(current.get("emotions", [])) or "복잡한"
    distortions  = current.get("cognitive_distortions", [])

    # 레벨 1 또는 유사도 낮으면 → 단순 공감
    best = past_diaries[0] if past_diaries else None
    best_score = best.get("weighted_score", best.get("similarity", 0)) if best else 0
    if level == 1 or best_score < 0.55:
        question = (
            f"그 {emotions_str} 감정, 오늘 어떤 순간에 가장 크게 느껴졌어?"
            if emotions_str != "복잡한"
            else "오늘 하루 중 가장 마음에 걸리는 장면이 있다면 어떤 순간이었어?"
        )
        return f"{user_name}아, 오늘 {emotions_str} 감정이 느껴졌구나. 털어놓아줘서 고마워. {question} 🌙"

    # 메모리 컨텍스트 (레벨 2+)
    memory_ctx = ""
    if level >= 2 and memory:
        recent = memory[-3:]
        lines  = [
            f"- {m.get('summary', '')} (감정: {', '.join(m.get('emotions', []))})"
            for m in recent if m.get("summary")
        ]
        if lines:
            memory_ctx = "\n[마루의 기억]\n" + "\n".join(lines)

    # 패턴
    pattern_ctx = _pattern_summary(past_diaries)

    # CBT 반문 힌트
    cbt_hint = ""
    cbt_examples = {
        "과잉일반화": "정말 항상 그랬어? 딱 한 번이라도 달랐던 적이 있었을까?",
        "파국화":     "가장 나쁜 상황을 상상하고 있는 건 아닐까?",
        "자기비난":   "같은 상황의 친구에게 뭐라고 말해줄 것 같아?",
        "독심술":     "그 사람이 정말 그렇게 생각한다는 걸 어떻게 알았어?",
    }
    reframe = next((v for k, v in cbt_examples.items() if k in distortions), None)
    if reframe:
        cbt_hint = f'\n[인지 재구성 반문] "{reframe}"'

    prompt = f"""너는 'Read:Me'의 감정 동반자 마루야.
현재 성장 단계: {level_info['name']} (레벨 {level}) — {level_info['style']} 응답해줘.

[사용자] {user_name}{f" | MBTI: {mbti}" if mbti else ""}
[오늘 감정] {emotions_str}
[인지 왜곡] {", ".join(distortions) or "없음"}
[근본 욕구] {current.get("hidden_need") or "미파악"}
[해소 여부] {"이미 풀렸어" if current.get("is_resolved") else "아직 풀리지 않은 것 같아"}
{memory_ctx}

[과거 유사 기록]
{pattern_ctx or "없음"}
{cbt_hint}

[응답 규칙]
1. {user_name} 이름 호명 + 공감 (1문장)
2. 과거 패턴 연결 (1~2문장, 자연스럽게 재표현)
3. 인지 왜곡 소크라테스 반문 (있으면 1문장)
4. 레벨 {level}에 맞는 깊이의 질문 1개
5. 전체 4~5문장, 반말체, 이모지 1개 이하
6. "~해야 해" 명령형 금지

마루 메시지:"""

    try:
        return ask_ollama(prompt).strip()
    except Exception as e:
        print("🔥 AI ERROR (maru):", e)
        return f"{user_name}아, 오늘 {emotions_str} 감정이 느껴졌구나. 함께 이야기해볼까? 🌙"
