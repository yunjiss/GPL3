"""auth.py — JWT 기반 인증 헬퍼"""

import os
import hashlib
import secrets
from datetime import datetime, timedelta

from jose import JWTError, jwt

SECRET_KEY   = os.getenv("JWT_SECRET", "readmesecret-change-in-production-2024")
ALGORITHM    = "HS256"
EXPIRE_DAYS  = 7
_ITERS       = 260_000


def hash_pw(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), _ITERS)
    return f"{salt}:{h.hex()}"


def verify_pw(plain: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":", 1)
        check = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), _ITERS)
        return secrets.compare_digest(check.hex(), h)
    except Exception:
        return False


def create_token(user_id: int, username: str, name: str = "", mbti: str = "") -> str:
    payload = {
        "sub":      str(user_id),
        "username": username,
        "name":     name,
        "mbti":     mbti,
        "exp":      datetime.utcnow() + timedelta(days=EXPIRE_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """유효한 페이로드 반환, 만료·위변조 시 JWTError 발생"""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
