# Execution evidence: StudentFin Agent

Generated: 2026-10-20T11:57:28+00:00

Simulated data only. This run used a temporary data folder, made no model calls and moved no real money. It was produced by `scripts/make_evidence.py`, which exercises the real API code and stops if any step behaves differently than expected.

## Summary

- Scenario steps executed: 37, all with the expected HTTP status
- Policy decisions recorded: 2 allowed, 2 awaiting owner confirmation, 3 refused
- Completed simulated transfers: 1
- Audit events recorded: 35

## Audit events by type

| Event | Count |
|---|---|
| account_deleted | 1 |
| data_exported | 1 |
| login_blocked | 1 |
| login_failed | 7 |
| login_ok | 4 |
| logout | 2 |
| policy_decision | 7 |
| profile_updated | 1 |
| tool_call | 5 |
| transfer_executed | 1 |
| user_cancelled | 1 |
| user_confirmed | 1 |
| user_registered | 3 |

## Steps

| # | What happened | Request | Status | Outcome |
|---|---|---|---|---|
| 1 | Anonymous visitor cannot read a balance | `GET /api/balance` | 401 | Please log in |
| 2 | Anonymous visitor cannot confirm a transfer | `POST /api/confirm` | 401 | Please log in |
| 3 | Weak password is rejected at registration | `POST /api/auth/register` | 400 | Password must be at least 10 characters |
| 4 | Register a demo student | `POST /api/auth/register` | 200 | {"user": "demo_student"} |
| 5 | Save the student profile | `PUT /api/profile` | 200 | {"profile": {"display_name": "Demo Student", "home_country": "Bangladesh", "home_currency": "BDT", "instalments": [{"amount": 3000.0, "curre ... |
| 6 | Profile refuses a passport number | `PUT /api/profile` | 422 | [{'type': 'extra_forbidden', 'loc': ['body', 'passport_number'], 'msg': 'Extra inputs are not permitted', 'input': 'A1234567'}] |
| 7 | Dashboard plans the next payment | `GET /api/dashboard` | 200 | next: Spring tuition in 20 days, recommended digital_transfer, send by 2026-11-05 |
| 8 | Compare routes for $3,000 with 17 days of budget | `POST /api/compare` | 200 | cheapest on time: digital_transfer, cheapest overall: digital_transfer |
| 9 | Balance before any transfer | `GET /api/balance` | 200 | balance BDT 450,000.00, USD 1,200.00 |
| 10 | Prepare a $3,000 transfer (no money moves yet) | `POST /api/propose` | 200 | awaiting_user_confirmation |
| 11 | Balance unchanged while the request is pending | `GET /api/balance` | 200 | balance BDT 450,000.00, USD 1,200.00 |
| 12 | Owner confirms the transfer | `POST /api/confirm` | 200 | completed |
| 13 | Balance after the confirmed transfer | `GET /api/balance` | 200 | balance BDT 79,730.00, USD 1,200.00 |
| 14 | Confirming the same request again is refused | `POST /api/confirm` | 200 | refused: Unknown or expired pending id |
| 15 | A second $3,000 the same day is refused (cumulative daily limit) | `POST /api/propose` | 200 | refused: Would exceed the daily limit: $3,000 already sent today, limit $5,000 |
| 16 | A $9,000 transfer is refused | `POST /api/propose` | 200 | refused: Amount exceeds daily limit of $5,000 |
| 17 | An unknown route is refused | `POST /api/propose` | 200 | refused: Unknown route 'invented_route' |
| 18 | Prepare a $500 transfer | `POST /api/propose` | 200 | awaiting_user_confirmation |
| 19 | Register a second student | `POST /api/auth/register` | 200 | {"user": "student_two"} |
| 20 | Second student sees no pending requests | `GET /api/pending` | 200 | {} |
| 21 | Second student has an untouched balance | `GET /api/balance` | 200 | balance BDT 450,000.00, USD 1,200.00 |
| 22 | Second student cannot confirm the first student's request | `POST /api/confirm` | 200 | refused: Unknown or expired pending id |
| 23 | Second student's audit view holds only their own events | `GET /api/audit` | 200 | [{"event": "user_registered", "ts": "2026-10-20T11:57:27.947627+00:00", "user": "student_two"}, {"event": "login_ok", "ts": "2026-10-20T11:5 ... |
| 24 | Owner cancels the $500 request | `POST /api/cancel` | 200 | {"status": "cancelled"} |
| 25 | Register a student to test lockout | `POST /api/auth/register` | 200 | {"user": "lockout_user"} |
| 26 | Wrong password, attempt 1 | `POST /api/auth/login` | 401 | Invalid username or password |
| 27 | Wrong password, attempt 2 | `POST /api/auth/login` | 401 | Invalid username or password |
| 28 | Wrong password, attempt 3 | `POST /api/auth/login` | 401 | Invalid username or password |
| 29 | Wrong password, attempt 4 | `POST /api/auth/login` | 401 | Invalid username or password |
| 30 | Wrong password, attempt 5 | `POST /api/auth/login` | 401 | Invalid username or password |
| 31 | Correct password is refused while the account is locked | `POST /api/auth/login` | 429 | Too many failed attempts. Try again in a few minutes. |
| 32 | Owner downloads their own data | `GET /api/me/export` | 200 | {"exported_at": "2026-10-20T11:57:28.231877+00:00", "note": "Simulated data only. Security audit entries are kept separately.", "profile": { ... |
| 33 | Account deletion with the wrong password is refused | `POST /api/me/delete` | 403 | Wrong password |
| 34 | Account deletion with the right password succeeds | `POST /api/me/delete` | 200 | {"status": "deleted"} |
| 35 | A deleted account can no longer log in | `POST /api/auth/login` | 401 | Invalid username or password |
| 36 | Logout ends the session | `POST /api/auth/logout` | 200 | {"status": "logged_out"} |
| 37 | The old session no longer works | `GET /api/auth/me` | 401 | Please log in |

## Files

- `audit_log.jsonl`: every decision, tool call, login and transfer from this run
- `ledger_demo_student.jsonl`: the simulated transfer recorded for the demo student
- `scenario_steps.json`: each request and response (passwords masked)
- `pytest_output.txt`: the automated test run
