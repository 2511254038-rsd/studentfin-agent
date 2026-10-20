from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import agent, audit, auth, main, tools
from app import student_profile as profile_store

GOOD = "correct-horse-42"


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(tools, "LEDGER_DIR", tmp_path / "ledgers")
    monkeypatch.setattr(profile_store, "DIR", tmp_path / "profiles")
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


def sample(days=20, amount=3000, currency="USD", paid=False):
    return {
        "display_name": "Rashed", "university": "Demo University",
        "home_country": "Bangladesh", "study_country": "United States",
        "home_currency": "BDT", "study_currency": "USD", "monthly_support_usd": 400,
        "instalments": [{
            "label": "Spring tuition", "amount": amount, "currency": currency,
            "due": (date.today() + timedelta(days=days)).isoformat(), "paid": paid,
        }],
    }


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/profile", None), ("put", "/api/profile", {}),
    ("get", "/api/dashboard", None), ("get", "/api/me/export", None),
    ("post", "/api/me/delete", {"password": "x"}),
])
def test_profile_endpoints_require_login(method, path, body):
    c = make_client()
    r = c.request(method.upper(), path, json=body) if body is not None else c.get(path)
    assert r.status_code == 401


def test_empty_profile_and_dashboard():
    c = make_client("alice")
    assert c.get("/api/profile").json() == {"profile": None}
    d = c.get("/api/dashboard").json()
    assert d["next"] is None and d["balances"]["BDT"] == 450000.0


def test_save_and_read_back():
    c = make_client("alice")
    assert c.put("/api/profile", json=sample()).status_code == 200
    p = c.get("/api/profile").json()["profile"]
    assert p["university"] == "Demo University" and len(p["instalments"]) == 1


def test_sensitive_or_unknown_fields_are_rejected():
    c = make_client("alice")
    bad = sample()
    bad["passport_number"] = "A1234567"
    assert c.put("/api/profile", json=bad).status_code == 422
    bad2 = sample()
    bad2["instalments"][0]["bank_account"] = "123"
    assert c.put("/api/profile", json=bad2).status_code == 422


def test_invalid_values_are_rejected():
    c = make_client("alice")
    p = sample(); p["home_currency"] = "JPY"
    assert c.put("/api/profile", json=p).status_code == 422
    p = sample(amount=-5)
    assert c.put("/api/profile", json=p).status_code == 422
    p = sample(); p["instalments"] = p["instalments"] * 7
    assert c.put("/api/profile", json=p).status_code == 422
    p = sample(); p["instalments"][0]["due"] = "1999-01-01"
    assert c.put("/api/profile", json=p).status_code == 422


def test_profiles_are_isolated_between_users():
    alice, bob = make_client("alice"), make_client("bobby")
    alice.put("/api/profile", json=sample())
    assert bob.get("/api/profile").json() == {"profile": None}
    assert bob.get("/api/dashboard").json()["next"] is None


def test_dashboard_recommends_cheapest_on_time_route():
    c = make_client("alice")
    c.put("/api/profile", json=sample(days=20))
    n = c.get("/api/dashboard").json()["next"]
    assert n["days_left"] == 20 and n["budget_days"] == 17
    assert n["recommended"]["route_id"] == "digital_transfer"
    due = date.today() + timedelta(days=20)
    assert n["send_by"] == (due - timedelta(days=4)).isoformat()


def test_dashboard_converts_currency():
    c = make_client("alice")
    c.put("/api/profile", json=sample(amount=122000, currency="BDT"))
    assert c.get("/api/dashboard").json()["next"]["amount_usd"] == 1000.0


def test_tight_deadline_forces_instant_route():
    c = make_client("alice")
    c.put("/api/profile", json=sample(days=2))
    assert c.get("/api/dashboard").json()["next"]["recommended"]["route_id"] == "card_portal"


def test_unreachable_deadline_gives_warning_not_a_route():
    c = make_client("alice")
    c.put("/api/profile", json=sample(days=1, amount=20000))
    n = c.get("/api/dashboard").json()["next"]
    assert n["recommended"] is None and n["warning"]


def test_overdue_and_paid_are_not_next():
    c = make_client("alice")
    c.put("/api/profile", json=sample(days=-5))
    d = c.get("/api/dashboard").json()
    assert d["next"] is None and d["instalments"][0]["status"] == "overdue"
    c.put("/api/profile", json=sample(days=20, paid=True))
    d = c.get("/api/dashboard").json()
    assert d["next"] is None and d["instalments"][0]["status"] == "paid"


def test_profile_values_are_not_written_to_audit_log():
    c = make_client("alice")
    c.put("/api/profile", json=sample())
    assert "Demo University" not in audit.LOG_FILE.read_text()


def test_export_contains_own_data_and_no_secrets():
    c = make_client("alice")
    c.put("/api/profile", json=sample())
    pid = c.post("/api/propose", json={"amount_usd": 3000, "route_id": "digital_transfer"}).json()["result"]["pending_id"]
    c.post("/api/confirm", json={"pending_id": pid})
    r = c.get("/api/me/export")
    assert "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["profile"]["university"] == "Demo University" and len(data["transfers"]) == 1
    assert "salt" not in r.text and "hash" not in r.text


def test_delete_needs_correct_password_then_erases_everything():
    c = make_client("alice")
    c.put("/api/profile", json=sample())
    assert c.post("/api/me/delete", json={"password": "wrong-password-1"}).status_code == 403
    assert c.get("/api/auth/me").status_code == 200
    assert c.post("/api/me/delete", json={"password": GOOD}).status_code == 200
    assert c.get("/api/auth/me").status_code == 401
    assert profile_store.load("alice") is None
    r = TestClient(main.app).post("/api/auth/login", json={"username": "alice", "password": GOOD})
    assert r.status_code == 401