from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from fastapi import Request
from fastapi.responses import RedirectResponse
from .config import ADMIN_PASSWORD_HASH, API_TOKEN_HASH

def verify_password(password: str) -> bool:
    try:
        method, salt, rounds, digest = ADMIN_PASSWORD_HASH.split("$", 3)
        if method != "pbkdf2_sha256": return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt),
                                     int(rounds), dklen=32).hex()
        return hmac.compare_digest(actual, digest)
    except Exception:
        return False

def verify_api_token(token: str) -> bool:
    actual = hashlib.sha256(token.encode()).hexdigest()
    return bool(API_TOKEN_HASH) and hmac.compare_digest(actual, API_TOKEN_HASH)

def make_session(csrf: str) -> str:
    payload = {"admin": True, "exp": int(time.time()) + 86400, "csrf": csrf}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    secret = os.environ.get("EASTMONEY_SESSION_SECRET", "")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return body + "." + sig

def read_session(request: Request):
    value = request.cookies.get("eastmoney_session", "")
    if "." not in value: return None
    body, sig = value.rsplit(".", 1)
    secret = os.environ.get("EASTMONEY_SESSION_SECRET", "")
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected): return None
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if not payload.get("admin") or int(payload.get("exp", 0)) < int(time.time()): return None
        return payload
    except Exception:
        return None

def new_csrf() -> str:
    return secrets.token_urlsafe(24)
