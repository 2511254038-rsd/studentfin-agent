import pytest
from fastapi.testclient import TestClient

from app import agent, auth, main, tools, userctx

GOOD = "correct-horse-42"


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(tools, "LEDGER_DIR", tmp_path / "ledgers")
    monkeypatch.delenv("INVITE_CODE", raising=False)
    monkeypatch.delenv("ALLOW_REGISTRATION", raising=False)
    auth._sessions.clear()
    auth._fails.clear()
    agent._STATES.clear()
    main._chat_times.clear()
    yield


def make_client(name=None):
    c = TestClient(main.app)
    if name:
        r = c.post("/api/auth/register", json={"username": name, "password": GOOD})
        assert r.status_code == 200, r.text
    return c


PROTECTED = [
    ("get", "/api/auth/me", None),
    ("get", "/api/balance", None),
    ("get", "/api/audit", None),
    ("get", "/api/routes", None),
    ("get", "/api/fx", None),
    ("get", "/api/transactions", None),
    ("get", "/api/pending", None),
    ("post", "/api/chat", {"message": "hi"}),
    ("post", "/api/confirm", {"pending_id": "PEND-X"}),
    ("post", "/api/cancel", {"pending_id": "PEND-X"}),
    ("post", "/api/reset", {}),
    ("post", "/api/compare", {"amount_usd": 100}),
    ("post", "/api/propose", {"amount_usd": 100, "route_id": "bank_wire"}),
]


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_endpoints_require_login(method, path, body):
    c = make_client()
    r = c.get(path) if method == "get" else c.post(path, json=body)
    assert r.status_code == 401


def test_public_endpoints_stay_public():
    c = make_client()
    assert c.get("/health").status_code == 200
    assert c.get("/").status_code == 200


def test_cookie_flags_and_logout():
    c = TestClient(main.app)
    r = c.post("/api/auth/register", json={"username": "alice", "password": GOOD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/api/auth/me").json() == {"user": "alice"}
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_wrong_password_is_401_then_lockout_is_429():
    make_client("alice")
    c = TestClient(main.app)
    for _ in range(auth.MAX_FAILS):
        r = c.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass-1"})
        assert r.status_code == 401
    r = c.post("/api/auth/login", json={"username": "alice", "password": GOOD})
    assert r.status_code == 429


def test_weak_password_rejected_at_registration():
    c = TestClient(main.app)
    r = c.post("/api/auth/register", json={"username": "alice", "password": "short1"})
    assert r.status_code == 400


def test_users_are_isolated():
    alice, bob = make_client("alice"), make_client("bobby")
    pid = alice.post("/api/propose", json={"amount_usd": 3000, "route_id": "digital_transfer"}).json()["result"]["pending_id"]
    assert bob.get("/api/pending").json() == {}
    assert bob.post("/api/confirm", json={"pending_id": pid}).json()["result"]["status"] == "refused"
    assert alice.post("/api/confirm", json={"pending_id": pid}).json()["result"]["status"] == "completed"
    assert alice.get("/api/balance").json()["BDT"] == 450000.0 - 370270.0
    assert bob.get("/api/balance").json()["BDT"] == 450000.0
    assert len(alice.get("/api/transactions").json()) == 1
    assert bob.get("/api/transactions").json() == []


def test_daily_limit_is_per_user():
    for name in ("alice", "bobby"):
        c = make_client(name)
        pid = c.post("/api/propose", json={"amount_usd": 3000, "route_id": "digital_transfer"}).json()["result"]["pending_id"]
        assert c.post("/api/confirm", json={"pending_id": pid}).json()["result"]["status"] == "completed"


def test_audit_shows_only_own_events():
    alice, bob = make_client("alice"), make_client("bobby")
    alice.post("/api/compare", json={"amount_usd": 100})
    bob_rows = bob.get("/api/audit").json()
    assert all(e.get("user") == "bobby" for e in bob_rows)
    assert not any(e.get("tool") == "compare_routes" for e in bob_rows)
    alice_rows = alice.get("/api/audit").json()
    assert any(e.get("tool") == "compare_routes" for e in alice_rows)


def test_chat_rate_limit(monkeypatch):
    monkeypatch.setattr(agent, "ask", lambda m: {"reply": "ok", "trace": [], "pending": {}})
    monkeypatch.setattr(main, "CHAT_LIMIT", 3)
    c = make_client("alice")
    codes = [c.post("/api/chat", json={"message": "hi"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_security_headers_on_page():
    r = TestClient(main.app).get("/")
    assert r.status_code == 200
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_unsafe_user_name_cannot_reach_ledger_path():
    with userctx.as_user("../evil"):
        with pytest.raises(ValueError):
            tools._read_ledger()


def test_registration_user_cap(monkeypatch):
    monkeypatch.setattr(main, "MAX_USERS", 1)
    make_client("alice")
    c = TestClient(main.app)
    r = c.post("/api/auth/register", json={"username": "bobby", "password": GOOD})
    assert r.status_code == 400