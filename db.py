import sqlite3
import json

conn = sqlite3.connect("diary.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS diary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    summary TEXT,
    emotions TEXT,
    events TEXT,
    persons TEXT,
    emotion_intensity TEXT,
    emotion_polarity TEXT,
    followup_question TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# 기존 DB 마이그레이션: CBT 분석 필드 추가
_MIGRATIONS = {
    "created_at": "ALTER TABLE diary ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "implicit_emotions": "ALTER TABLE diary ADD COLUMN implicit_emotions TEXT DEFAULT '[]'",
    "cognitive_distortions": "ALTER TABLE diary ADD COLUMN cognitive_distortions TEXT DEFAULT '[]'",
    "distortion_sentences": "ALTER TABLE diary ADD COLUMN distortion_sentences TEXT DEFAULT '[]'",
    "abc": "ALTER TABLE diary ADD COLUMN abc TEXT DEFAULT '{}'",
    "reframe_question": "ALTER TABLE diary ADD COLUMN reframe_question TEXT DEFAULT ''",
    "hidden_need": "ALTER TABLE diary ADD COLUMN hidden_need TEXT DEFAULT ''",
    "recovery_hint": "ALTER TABLE diary ADD COLUMN recovery_hint TEXT DEFAULT ''",
    "is_resolved": "ALTER TABLE diary ADD COLUMN is_resolved INTEGER DEFAULT 0",
    "cbt_model": "ALTER TABLE diary ADD COLUMN cbt_model TEXT DEFAULT '{}'",
}

for sql in _MIGRATIONS.values():
    try:
        cursor.execute(sql)
        conn.commit()
    except Exception:
        pass


def _json_dump(value, fallback):
    return json.dumps(value if value is not None else fallback, ensure_ascii=False)


def _parse_json(value, fallback):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return fallback
    return value if value is not None else fallback


def _parse_row(row: dict) -> dict:
    for field in (
        "emotions",
        "events",
        "persons",
        "implicit_emotions",
        "cognitive_distortions",
        "distortion_sentences",
    ):
        row[field] = _parse_json(row.get(field), [])
    row["abc"] = _parse_json(row.get("abc"), {})
    row["cbt_model"] = _parse_json(row.get("cbt_model"), {})
    row["is_resolved"] = bool(row.get("is_resolved"))
    return row


def save_diary(text: str, parsed: dict) -> int:
    cursor.execute(
        """INSERT INTO diary
        (text, summary, emotions, events, persons,
         emotion_intensity, emotion_polarity, followup_question,
         implicit_emotions, cognitive_distortions, distortion_sentences,
         abc, reframe_question, hidden_need, recovery_hint, is_resolved, cbt_model)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            text,
            parsed.get("summary", ""),
            _json_dump(parsed.get("emotions"), []),
            _json_dump(parsed.get("events"), []),
            _json_dump(parsed.get("persons"), []),
            parsed.get("emotion_intensity", "medium"),
            parsed.get("emotion_polarity", "mixed"),
            parsed.get("followup_question", ""),
            _json_dump(parsed.get("implicit_emotions"), []),
            _json_dump(parsed.get("cognitive_distortions"), []),
            _json_dump(parsed.get("distortion_sentences"), []),
            _json_dump(parsed.get("abc"), {}),
            parsed.get("reframe_question", ""),
            parsed.get("hidden_need", ""),
            parsed.get("recovery_hint", ""),
            1 if parsed.get("is_resolved") else 0,
            _json_dump(parsed.get("cbt_model"), {}),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def get_all_diaries() -> list[dict]:
    cursor.execute("SELECT * FROM diary ORDER BY id DESC")
    return [_parse_row(dict(row)) for row in cursor.fetchall()]


def delete_diary(diary_id: int) -> bool:
    cursor.execute("DELETE FROM diary WHERE id = ?", (diary_id,))
    conn.commit()
    return cursor.rowcount > 0


def get_diary_by_id(diary_id: int) -> dict | None:
    cursor.execute("SELECT * FROM diary WHERE id = ?", (diary_id,))
    row = cursor.fetchone()
    return _parse_row(dict(row)) if row else None
