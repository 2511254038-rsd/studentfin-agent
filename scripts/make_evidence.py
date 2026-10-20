"""Execution evidence generator for the competition submission.

Runs a scripted scenario through the real API code (sign-up, profile, comparison, prepare,
confirm, refusals, isolation, lockout, export, delete) using a temporary data folder, then
writes the audit log, a ledger and a readable report to docs/evidence/.
No model calls are made and no real data is touched.

Run from the project root:  python3 scripts/make_evidence.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GEMINI_API_KEY", "evidence-run-not-a-real-key")
os.environ.setdefault("MODEL", "evidence-run-model")

from fastapi.testclient import TestClient  # noqa: E402

from app import audit, auth, main, tools  # noqa: E402
from app import student_profile as profile_store  # noqa: E402

os.environ.pop("INVITE_CODE", None)
os.environ["ALLOW_REGISTRATION"] = "1"
main.COOKIE_SECURE = False

TMP = Path(tempfile.mkdtemp(prefix="sf_evidence_"))
audit.LOG_FILE = TMP / "audit.jsonl"
auth.USERS_FILE = TMP / "users.json"
tools.LEDGER_DIR = TMP / "ledgers"
profile_store.DIR = TMP / "profiles"

PASSWORD = "correct-horse-42"
rows = []


def mask(payload):
    if isinstance(payload, dict):
        return {k: ("***" if k == "password" else v) for k, v in payload.items()}
    return payload


def short(body, limit=420):
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[:limit] + " ..."


def summarize(body):
    if isinstance(body, dict):
        if isinstance(body.get("result"), dict):
            r = body["result"]
            return r.get("status", "") + (": " + r["reason"] if r.get("reason") else "")
        if "detail" in body:
            return str(body["detail"])[:140]
        if body.get("next"):
            n = body["next"]
            rec = (n.get("recommended") or {}).get("route_id", "no route")
            return f"next: {n['label']} in {n['days_left']} days, recommended {rec}, send by {n['send_by']}"
        if "cheapest_on_time" in body:
            return f"cheapest on time: {body['cheapest_on_time']}, cheapest overall: {body['cheapest_overall']}"
        if "BDT" in body and "USD" in body:
            return f"balance BDT {body['BDT']:,.2f}, USD {body['USD']:,.2f}"
    return short(body, 140)


def step(client, label, method, path, expect, payload=None):
    if payload is not None:
        r = client.request(method, path, json=payload)
    else:
        r = client.request(method, path)
    try:
        body = r.json()
    except ValueError:
        body = r.text
    rows.append({"label": label, "request": f"{method} {path}", "payload": mask(payload),
                 "status": r.status_code, "expected": expect, "body": body})
    if r.status_code != expect:
        raise SystemExit(f"UNEXPECTED STATUS in step '{label}': got {r.status_code}, "
                         f"expected {expect}: {short(body)}")
    return body


# ---------------- Scenario ----------------
anon = TestClient(main.app)
step(anon, "Anonymous visitor cannot read a balance", "GET", "/api/balance", 401)
step(anon, "Anonymous visitor cannot confirm a transfer", "POST", "/api/confirm", 401,
     {"pending_id": "PEND-FAKE"})

weak = TestClient(main.app)
step(weak, "Weak password is rejected at registration", "POST", "/api/auth/register", 400,
     {"username": "weak_user", "password": "short1"})

alice = TestClient(main.app)
step(alice, "Register a demo student", "POST", "/api/auth/register", 200,
     {"username": "demo_student", "password": PASSWORD})

due = (date.today() + timedelta(days=20)).isoformat()
profile = {
    "display_name": "Demo Student", "university": "Demo University",
    "home_country": "Bangladesh", "study_country": "United States",
    "home_currency": "BDT", "study_currency": "USD", "monthly_support_usd": 400,
    "instalments": [{"label": "Spring tuition", "amount": 3000, "currency": "USD",
                     "due": due, "paid": False}],
}
step(alice, "Save the student profile", "PUT", "/api/profile", 200, profile)
step(alice, "Profile refuses a passport number", "PUT", "/api/profile", 422,
     dict(profile, passport_number="A1234567"))
dash = step(alice, "Dashboard plans the next payment", "GET", "/api/dashboard", 200)
assert dash["next"]["recommended"]["route_id"] == "digital_transfer"

cmp_ = step(alice, "Compare routes for $3,000 with 17 days of budget", "POST", "/api/compare", 200,
            {"amount_usd": 3000, "days_available": 17})
assert cmp_["cheapest_on_time"] == "digital_transfer"

before = step(alice, "Balance before any transfer", "GET", "/api/balance", 200)
prop = step(alice, "Prepare a $3,000 transfer (no money moves yet)", "POST", "/api/propose", 200,
            {"amount_usd": 3000, "route_id": "digital_transfer"})
assert prop["result"]["status"] == "awaiting_user_confirmation"
pid = prop["result"]["pending_id"]
mid = step(alice, "Balance unchanged while the request is pending", "GET", "/api/balance", 200)
assert mid == before

done = step(alice, "Owner confirms the transfer", "POST", "/api/confirm", 200, {"pending_id": pid})
assert done["result"]["status"] == "completed"
after = step(alice, "Balance after the confirmed transfer", "GET", "/api/balance", 200)
assert after["BDT"] == before["BDT"] - 370270.0

again = step(alice, "Confirming the same request again is refused", "POST", "/api/confirm", 200,
             {"pending_id": pid})
assert again["result"]["status"] == "refused"

second = step(alice, "A second $3,000 the same day is refused (cumulative daily limit)",
              "POST", "/api/propose", 200, {"amount_usd": 3000, "route_id": "digital_transfer"})
assert second["result"]["status"] == "refused" and "daily" in second["result"]["reason"].lower()
big = step(alice, "A $9,000 transfer is refused", "POST", "/api/propose", 200,
           {"amount_usd": 9000, "route_id": "digital_transfer"})
assert big["result"]["status"] == "refused"
unk = step(alice, "An unknown route is refused", "POST", "/api/propose", 200,
           {"amount_usd": 100, "route_id": "invented_route"})
assert unk["result"]["status"] == "refused"

pend2 = step(alice, "Prepare a $500 transfer", "POST", "/api/propose", 200,
             {"amount_usd": 500, "route_id": "digital_transfer"})
pid2 = pend2["result"]["pending_id"]

bob = TestClient(main.app)
step(bob, "Register a second student", "POST", "/api/auth/register", 200,
     {"username": "student_two", "password": PASSWORD})
bp = step(bob, "Second student sees no pending requests", "GET", "/api/pending", 200)
assert bp == {}
bb = step(bob, "Second student has an untouched balance", "GET", "/api/balance", 200)
assert bb["BDT"] == 450000.0
steal = step(bob, "Second student cannot confirm the first student's request", "POST",
             "/api/confirm", 200, {"pending_id": pid2})
assert steal["result"]["status"] == "refused"
baudit = step(bob, "Second student's audit view holds only their own events", "GET", "/api/audit", 200)
assert all(e.get("user") == "student_two" for e in baudit)
step(alice, "Owner cancels the $500 request", "POST", "/api/cancel", 200, {"pending_id": pid2})

lock = TestClient(main.app)
step(lock, "Register a student to test lockout", "POST", "/api/auth/register", 200,
     {"username": "lockout_user", "password": PASSWORD})
guest = TestClient(main.app)
for n in range(1, auth.MAX_FAILS + 1):
    step(guest, f"Wrong password, attempt {n}", "POST", "/api/auth/login", 401,
         {"username": "lockout_user", "password": "wrong-password-1"})
step(guest, "Correct password is refused while the account is locked", "POST",
     "/api/auth/login", 429, {"username": "lockout_user", "password": PASSWORD})

exp = step(alice, "Owner downloads their own data", "GET", "/api/me/export", 200)
assert "profile" in exp and "transfers" in exp and "salt" not in json.dumps(exp)

step(bob, "Account deletion with the wrong password is refused", "POST", "/api/me/delete", 403,
     {"password": "wrong-password-1"})
step(bob, "Account deletion with the right password succeeds", "POST", "/api/me/delete", 200,
     {"password": PASSWORD})
step(guest, "A deleted account can no longer log in", "POST", "/api/auth/login", 401,
     {"username": "student_two", "password": PASSWORD})

step(alice, "Logout ends the session", "POST", "/api/auth/logout", 200)
step(alice, "The old session no longer works", "GET", "/api/auth/me", 401)

# ---------------- Write evidence ----------------
OUT = ROOT / "docs" / "evidence"
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy(audit.LOG_FILE, OUT / "audit_log.jsonl")
shutil.copy(tools.LEDGER_DIR / "demo_student.jsonl", OUT / "ledger_demo_student.jsonl")
(OUT / "scenario_steps.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

events = [json.loads(x) for x in audit.LOG_FILE.read_text().splitlines() if x.strip()]
counts = {}
for e in events:
    counts[e["event"]] = counts.get(e["event"], 0) + 1
decisions = [e for e in events if e["event"] == "policy_decision"]
awaiting = sum(1 for e in decisions if not e["allowed"] and e.get("reason", "").startswith("Needs explicit user confirmation"))
denied = sum(1 for e in decisions if not e["allowed"]) - awaiting
allowed = len(decisions) - denied - awaiting

lines = [
    "# Execution evidence: StudentFin Agent", "",
    f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}", "",
    "Simulated data only. This run used a temporary data folder, made no model calls and "
    "moved no real money. It was produced by `scripts/make_evidence.py`, which exercises the "
    "real API code and stops if any step behaves differently than expected.", "",
    "## Summary", "",
    f"- Scenario steps executed: {len(rows)}, all with the expected HTTP status",
    f"- Policy decisions recorded: {allowed} allowed, {awaiting} awaiting owner confirmation, {denied} refused",
    f"- Completed simulated transfers: {counts.get('transfer_executed', 0)}",
    f"- Audit events recorded: {len(events)}", "",
    "## Audit events by type", "", "| Event | Count |", "|---|---|",
]
for name in sorted(counts):
    lines.append(f"| {name} | {counts[name]} |")
lines += ["", "## Steps", "", "| # | What happened | Request | Status | Outcome |", "|---|---|---|---|---|"]
for i, r in enumerate(rows, 1):
    cells = [str(i), r["label"], f"`{r['request']}`", str(r["status"]), summarize(r["body"])]
    lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
lines += ["", "## Files", "",
          "- `audit_log.jsonl`: every decision, tool call, login and transfer from this run",
          "- `ledger_demo_student.jsonl`: the simulated transfer recorded for the demo student",
          "- `scenario_steps.json`: each request and response (passwords masked)",
          "- `pytest_output.txt`: the automated test run"]
(OUT / "scenario_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

print(f"Evidence written to {OUT}")
print(f"{len(rows)} steps, {len(events)} audit events, {allowed} allowed / {denied} denied decisions")