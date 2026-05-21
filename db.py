"""db.py — SQLite CRUD (멀티유저, WAL 모드)"""

import sqlite3
import json
from pathlib import Path

DB_PATH = str(Path(__file__).resolve().parent / "diary.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ══════════════════════════════════════════════════════════════
# 초기화 & 마이그레이션
# ══════════════════════════════════════════════════════════════

def _init():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT    NOT NULL UNIQUE,
            password_h TEXT    NOT NULL,
            name       TEXT    NOT NULL DEFAULT '',
            mbti       TEXT    NOT NULL DEFAULT '',
            interests  TEXT    NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS diary (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id           INTEGER DEFAULT 1,
            text              TEXT,
            summary           TEXT,
            emotions          TEXT,
            events            TEXT,
            persons           TEXT,
            emotion_intensity TEXT,
            emotion_polarity  TEXT,
            followup_question TEXT,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS maru_state (
            user_id        INTEGER PRIMARY KEY,
            level          INTEGER   DEFAULT 1,
            personality    TEXT      DEFAULT 'gentle',
            memory_json    TEXT      DEFAULT '[]',
            relationship   TEXT      DEFAULT 'new',
            total_sessions INTEGER   DEFAULT 0,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_profile (
            data TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS actions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            diary_id     INTEGER NOT NULL,
            action_text  TEXT    NOT NULL,
            suggested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed    INTEGER DEFAULT 0,
            completed_at TIMESTAMP
        );
    """)

    _migrations = [
        "ALTER TABLE diary ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE diary ADD COLUMN implicit_emotions TEXT DEFAULT '[]'",
        "ALTER TABLE diary ADD COLUMN cognitive_distortions TEXT DEFAULT '[]'",
        "ALTER TABLE diary ADD COLUMN distortion_sentences TEXT DEFAULT '[]'",
        "ALTER TABLE diary ADD COLUMN abc TEXT DEFAULT '{}'",
        "ALTER TABLE diary ADD COLUMN reframe_question TEXT DEFAULT ''",
        "ALTER TABLE diary ADD COLUMN hidden_need TEXT DEFAULT ''",
        "ALTER TABLE diary ADD COLUMN recovery_hint TEXT DEFAULT ''",
        "ALTER TABLE diary ADD COLUMN is_resolved INTEGER DEFAULT 0",
        "ALTER TABLE diary ADD COLUMN cbt_model TEXT DEFAULT '{}'",
        "ALTER TABLE diary ADD COLUMN user_id INTEGER DEFAULT 1",
        "ALTER TABLE diary ADD COLUMN interpretation TEXT DEFAULT ''",
        "ALTER TABLE diary ADD COLUMN question TEXT DEFAULT ''",
        "ALTER TABLE diary ADD COLUMN highlight TEXT DEFAULT ''",
    ]
    for sql in _migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass

    conn.close()


_init()


# ══════════════════════════════════════════════════════════════
# JSON 헬퍼
# ══════════════════════════════════════════════════════════════

def _jdump(v, fallback):
    return json.dumps(v if v is not None else fallback, ensure_ascii=False)


def _jload(v, fallback):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return fallback
    return v if v is not None else fallback


def _parse_row(row: dict) -> dict:
    for f in ("emotions", "events", "persons", "implicit_emotions",
              "cognitive_distortions", "distortion_sentences"):
        row[f] = _jload(row.get(f), [])
    row["abc"]       = _jload(row.get("abc"), {})
    row["cbt_model"] = _jload(row.get("cbt_model"), {})
    row["is_resolved"] = bool(row.get("is_resolved"))
    return row


# ══════════════════════════════════════════════════════════════
# Users
# ══════════════════════════════════════════════════════════════

def create_user(username: str, password_h: str, name: str, mbti: str) -> dict:
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_h, name, mbti) VALUES (?, ?, ?, ?)",
            [username, password_h, name, mbti],
        )
        conn.commit()
        return {"id": cur.lastrowid, "username": username, "name": name, "mbti": mbti}
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", [username]
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", [user_id]
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_user_profile(user_id: int, name: str, mbti: str, interests: list) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE users SET name=?, mbti=?, interests=? WHERE id=?",
            [name, mbti, _jdump(interests, []), user_id],
        )
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════
# Diary CRUD
# ══════════════════════════════════════════════════════════════

def save_diary(text: str, parsed: dict, user_id: int = 1) -> int:
    conn = _get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO diary
            (user_id, text, summary, emotions, events, persons,
             emotion_intensity, emotion_polarity, followup_question,
             implicit_emotions, cognitive_distortions, distortion_sentences,
             abc, reframe_question, hidden_need, recovery_hint,
             is_resolved, cbt_model, interpretation, question, highlight)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                text,
                parsed.get("summary") or "",
                _jdump(parsed.get("emotions"), []),
                _jdump(parsed.get("events"), []),
                _jdump(parsed.get("persons"), []),
                parsed.get("emotion_intensity", "medium"),
                parsed.get("emotion_polarity", "mixed"),
                parsed.get("followup_question") or "",
                _jdump(parsed.get("implicit_emotions"), []),
                _jdump(parsed.get("cognitive_distortions"), []),
                _jdump(parsed.get("distortion_sentences"), []),
                _jdump(parsed.get("abc"), {}),
                parsed.get("reframe_question") or "",
                parsed.get("hidden_need") or "",
                parsed.get("recovery_hint") or "",
                1 if parsed.get("is_resolved") else 0,
                _jdump(parsed.get("cbt_model"), {}),
                parsed.get("interpretation") or "",
                parsed.get("question") or "",
                parsed.get("highlight") or "",
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_all_diaries(user_id: int = 1) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM diary WHERE user_id=? ORDER BY id DESC", [user_id]
        ).fetchall()
        return [_parse_row(dict(r)) for r in rows]
    finally:
        conn.close()


def get_diary_by_id(diary_id: int, user_id: int = 1) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM diary WHERE id=? AND user_id=?", [diary_id, user_id]
        ).fetchone()
        return _parse_row(dict(row)) if row else None
    finally:
        conn.close()


def delete_diary(diary_id: int, user_id: int = 1) -> bool:
    conn = _get_conn()
    try:
        conn.execute(
            "DELETE FROM diary WHERE id=? AND user_id=?", [diary_id, user_id]
        )
        conn.commit()
        chg = conn.execute("SELECT changes()").fetchone()[0]
        return chg > 0
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════
# Maru State
# ══════════════════════════════════════════════════════════════

def get_maru_state(user_id: int) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM maru_state WHERE user_id=?", [user_id]
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["memory"] = _jload(d.get("memory_json"), [])
        return d
    finally:
        conn.close()


def upsert_maru_state(user_id: int, state: dict) -> None:
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO maru_state
                (user_id, level, personality, memory_json, relationship, total_sessions, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                level          = excluded.level,
                personality    = excluded.personality,
                memory_json    = excluded.memory_json,
                relationship   = excluded.relationship,
                total_sessions = excluded.total_sessions,
                updated_at     = CURRENT_TIMESTAMP
        """, [
            user_id,
            state.get("level", 1),
            state.get("personality", "gentle"),
            _jdump(state.get("memory", []), []),
            state.get("relationship", "new"),
            state.get("total_sessions", 0),
        ])
        conn.commit()
    finally:
        conn.close()
