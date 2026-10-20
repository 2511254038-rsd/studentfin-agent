"""Authentication: registration, login with hashed passwords, server-side sessions.
Standard library only (scrypt for hashing). Demo-grade: see docs/SECURITY.md for limits."""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request

from app import audit

USERS_FILE = Path(__file__).parent / "data" / "users.json"
COOKIE_NAME = "sf_session"
SESSION_TTL_S = 2 * 60 * 60      # session expires after 2 hours of inactivity
MAX_FAILS = 5                    # failed logins before a temporary lock
LOCK_S = 5 * 60                  # lock duration
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
COMMON_PASSWORDS = {"password123", "1234567890", "qwertyuiop", "iloveyou123", "admin12345"}

_lock = threading.Lock()
_sessions: dict[str, dict] = {}   # sha256(token) -> {"user": str, "exp": float}
_fails: dict[str, dict] = {}      # username -> {"count": int, "locked_until": float}

# Unknown usernames still pay the hashing cost, so timing does not reveal who exists.
_DUMMY_SALT = b"\x00" * 16


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)


def _save_users(users: dict) -> None:
    tmp = USERS_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(users, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, USERS_FILE)


def validate_password(password: str, username: str) -> str | None:
    """Return an error message, or None if the password is acceptable."""
    if len(password) < 10:
        return "Password must be at least 10 characters"
    if len(password) > 128:
        return "Password must be at most 128 characters"
    if username.lower() in password.lower():
        return "Password must not contain the username"
    if password.lower() in COMMON_PASSWORDS:
        return "Password is too common"
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        return "Password must contain letters and digits"
    return None


def register(username: str, password: str, invite_code: str = "") -> None:
    if os.getenv("ALLOW_REGISTRATION", "1") != "1":
        raise ValueError("Registration is closed")
    required = os.getenv("INVITE_CODE", "")
    if required and not hmac.compare_digest(invite_code.encode(), required.encode()):
        audit.log("register_denied", reason="bad_invite_code")
        raise ValueError("Invalid invite code")
    if not USERNAME_RE.match(username):
        raise ValueError("Username must be 3-32 characters: letters, digits, underscore")
    problem = validate_password(password, username)
    if problem:
        raise ValueError(problem)
    key = username.lower()
    with _lock:
        users = _load_users()
        if key in users:
            raise ValueError("That username is taken")
        salt = secrets.token_bytes(16)
        users[key] = {"salt": salt.hex(), "hash": _hash(password, salt).hex(), "created": time.time()}
        _save_users(users)
    audit.log("user_registered", user=key)


def login(username: str, password: str) -> str:
    """Return a session token. ValueError = bad credentials, PermissionError = locked."""
    key = username.lower()
    now = time.time()
    with _lock:
        f = _fails.get(key)
        if f and f["locked_until"] > now:
            audit.log("login_blocked", user=key)
            raise PermissionError("Too many failed attempts. Try again in a few minutes.")
        users = _load_users()
    rec = users.get(key)
    salt = bytes.fromhex(rec["salt"]) if rec else _DUMMY_SALT
    candidate = _hash(password, salt)
    ok = bool(rec) and hmac.compare_digest(candidate, bytes.fromhex(rec["hash"]))
    with _lock:
        if not ok:
            if len(_fails) > 10000:
                _fails.clear()            # bound memory against random-username floods
            f = _fails.setdefault(key, {"count": 0, "locked_until": 0.0})
            f["count"] += 1
            if f["count"] >= MAX_FAILS:
                f["locked_until"] = now + LOCK_S
                f["count"] = 0
            audit.log("login_failed", user=key)
            raise ValueError("Invalid username or password")
        _fails.pop(key, None)
        token = secrets.token_urlsafe(32)
        _sessions[_digest(token)] = {"user": key, "exp": now + SESSION_TTL_S}
    audit.log("login_ok", user=key)
    return token


def logout(token: str | None) -> None:
    if not token:
        return
    with _lock:
        s = _sessions.pop(_digest(token), None)
    if s:
        audit.log("logout", user=s["user"])


def user_for_token(token: str | None) -> str | None:
    if not token:
        return None
    now = time.time()
    with _lock:
        s = _sessions.get(_digest(token))
        if not s:
            return None
        if s["exp"] < now:
            _sessions.pop(_digest(token), None)
            return None
        s["exp"] = now + SESSION_TTL_S    # sliding expiry
        return s["user"]


def require_user(request: Request) -> str:
    """FastAPI dependency: the logged-in username, or HTTP 401."""
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(401, "Please log in")
    return user
