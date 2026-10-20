from datetime import date, timedelta
from pathlib import Path

from app import student_profile as sp

HTML = (Path(__file__).resolve().parent.parent / "app" / "static" / "index.html").read_text(encoding="utf-8")


def _profile(days):
    due = (date.today() + timedelta(days=days)).isoformat()
    return {"monthly_support_usd": 0, "instalments": [
        {"label": "x", "amount": 300, "currency": "USD", "due": due, "paid": False}]}


def test_sidebar_avatar_and_preferences_present():
    for marker in ("id=\"sidebar\"", "id=\"sb-toggle\"", "id=\"sb-userbtn\"",
                   "class=\"avatar\"", "id=\"acc-sw\"", "id=\"av-sw\"", "id=\"sb-new\""):
        assert marker in HTML, marker


def test_history_lives_in_sidebar_only():
    assert HTML.count("id=\"history\"") == 1


def test_preferences_are_validated_before_use():
    assert "HEX.test" in HTML
    assert ".innerHTML" not in HTML


def test_send_now_when_send_by_date_has_passed():
    d = sp.build_dashboard(_profile(2), {"BDT": 1, "USD": 1}, date.today())
    assert d["next"]["send_now"] is True


def test_send_now_false_with_time_to_spare():
    d = sp.build_dashboard(_profile(30), {"BDT": 1, "USD": 1}, date.today())
    assert d["next"]["send_now"] is False
