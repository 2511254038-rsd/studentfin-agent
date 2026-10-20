import time

import pytest
from fastapi import HTTPException

from app import auth

GOOD = "correct-horse-42"


@pytest.fixture(autouse=True)
def clean_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    auth._sessions.clear()
    auth._fails.clear()
    monkeypatch.delenv("INVITE_CODE", raising=False)
    monkeypatch.delenv("ALLOW_REGISTRATION", raising=False)
    yield


def test_register_and_login():
    auth.register("Alice_1", GOOD)
    token = auth.login("alice_1", GOOD)
    assert auth.user_for_token(token) == "alice_1"


def test_password_never_stored_in_plaintext():
    auth.register("alice", GOOD)
    assert GOOD not in auth.USERS_FILE.read_text()


def test_same_password_gets_different_hashes():
    auth.register("alice", GOOD)
    auth.register("bobby", GOOD)
    users = auth._load_users()
    assert users["alice"]["hash"] != users["bobby"]["hash"]


def test_wrong_password_and_unknown_user_give_same_error():
    auth.register("alice", GOOD)
    with pytest.raises(ValueError) as wrong:
        auth.login("alice", "wrong-password-1")
    with pytest.raises(ValueError) as unknown:
        auth.login("nobody", "wrong-password-1")
    assert str(wrong.value) == str(unknown.value)


def test_duplicate_username_rejected_case_insensitive():
    auth.register("Alice", GOOD)
    with pytest.raises(ValueError):
        auth.register("ALICE", GOOD)


@pytest.mark.parametrize("pw", ["short1", "alllettersnodigits", "alice12345678", "password123", "x" * 200])
def test_weak_passwords_rejected(pw):
    with pytest.raises(ValueError):
        auth.register("alice", pw)


@pytest.mark.parametrize("name", ["ab", "a b c", "../etc", "x" * 40, "bob;drop"])
def test_invalid_usernames_rejected(name):
    with pytest.raises(ValueError):
        auth.register(name, GOOD)


def test_lockout_after_repeated_failures():
    auth.register("alice", GOOD)
    for _ in range(auth.MAX_FAILS):
        with pytest.raises(ValueError):
            auth.login("alice", "wrong-password-1")
    with pytest.raises(PermissionError):
        auth.login("alice", GOOD)          # even the right password is refused while locked


def test_lock_expires(monkeypatch):
    auth.register("alice", GOOD)
    for _ in range(auth.MAX_FAILS):
        with pytest.raises(ValueError):
            auth.login("alice", "wrong-password-1")
    later = time.time() + auth.LOCK_S + 1
    monkeypatch.setattr(auth.time, "time", lambda: later)
    assert auth.login("alice", GOOD)


def test_logout_invalidates_session():
    auth.register("alice", GOOD)
    token = auth.login("alice", GOOD)
    auth.logout(token)
    assert auth.user_for_token(token) is None


def test_session_expires(monkeypatch):
    auth.register("alice", GOOD)
    token = auth.login("alice", GOOD)
    later = time.time() + auth.SESSION_TTL_S + 5
    monkeypatch.setattr(auth.time, "time", lambda: later)
    assert auth.user_for_token(token) is None


def test_garbage_tokens_rejected():
    assert auth.user_for_token("garbage") is None
    assert auth.user_for_token("") is None
    assert auth.user_for_token(None) is None


def test_invite_code_required_when_set(monkeypatch):
    monkeypatch.setenv("INVITE_CODE", "letmein-123")
    with pytest.raises(ValueError):
        auth.register("alice", GOOD)
    with pytest.raises(ValueError):
        auth.register("alice", GOOD, "wrong-code")
    auth.register("alice", GOOD, "letmein-123")


def test_registration_can_be_closed(monkeypatch):
    monkeypatch.setenv("ALLOW_REGISTRATION", "0")
    with pytest.raises(ValueError):
        auth.register("alice", GOOD)


def test_require_user_returns_401_without_login():
    class FakeRequest:
        cookies = {}

    with pytest.raises(HTTPException) as e:
        auth.require_user(FakeRequest())
    assert e.value.status_code == 401
