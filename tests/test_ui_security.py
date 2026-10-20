from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "app" / "static" / "index.html").read_text(encoding="utf-8")


def test_login_screen_present_with_password_manager_hints():
    assert 'id="auth-form"' in HTML
    assert 'autocomplete="username"' in HTML
    assert 'autocomplete="current-password"' in HTML
    assert 'autocomplete="new-password"' in HTML


def test_page_never_writes_html_from_strings():
    for bad in (".innerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert bad not in HTML, bad


def test_password_never_stored_in_browser_storage():
    assert "localStorage.setItem(HKEY" in HTML
    assert 'setItem("pass' not in HTML
    assert 'sessionStorage.setItem("sf_shared"' in HTML


def test_profile_and_home_screens_present():
    for marker in ('id="tab-home"', 'id="tab-profile"', 'id="acct-export"', 'id="acct-delete-go"'):
        assert marker in HTML, marker