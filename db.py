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

# 기존 DB에 created_at 컬럼이 없으면 추가
try:
    cursor.execute("ALTER TABLE diary ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    conn.commit()
except Exception:
    pass


def _parse_row(row: dict) -> dict:
    for field in ("emotions", "events", "persons"):
        val = row.get(field)
        if isinstance(val, str):
            try:
                row[field] = json.loads(val)
            except Exception:
                row[field] = []
    return row


def save_diary(text: str, parsed: dict) -> int:
    cursor.execute(
        """INSERT INTO diary
        (text, summary, emotions, events, persons,
         emotion_intensity, emotion_polarity, followup_question)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            text,
            parsed.get("summary", ""),
            json.dumps(parsed.get("emotions", []), ensure_ascii=False),
            json.dumps(parsed.get("events", []), ensure_ascii=False),
            json.dumps(parsed.get("persons", []), ensure_ascii=False),
            parsed.get("emotion_intensity", "medium"),
            parsed.get("emotion_polarity", "mixed"),
            parsed.get("followup_question", ""),
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
