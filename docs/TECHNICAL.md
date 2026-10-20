# StudentFin Agent: Technical Documentation

Competition: 2026 Shenzhen International FinTech Competition (FinTechathon), International Track
Topic: C, Cross-border and Student Finance Assistant
Team: [Team name] | [Member names, universities, countries]
Repository: https://github.com/2511254038-rsd/studentfin-agent

> All accounts, exchange rates, fees and providers are simulated. No real money moves and no real bank is connected.

## 1. Overview

StudentFin Agent helps international students and their families decide how to send money across borders. It compares payment routes by true total cost, picks the cheapest route that arrives before a deadline, plans tuition payments from the student's own schedule, and prepares simulated transfers that only the signed-in person can confirm.

Design principle: **the language model talks, code computes, policy decides, and a human confirms.**

## 2. Problem and users

Students and families lose money on hidden exchange-rate margins, risk missing tuition deadlines, and are targets for payment fraud. A route with no fixed fee can cost more than one with a small fee, because its cost sits in percentages and the exchange-rate margin. Our target user is a student from South Asia (Bangladesh as the primary case) paying tuition and living costs abroad, funded by family in a different currency.

## 3. System architecture

```
Browser (login, Home plan, Chat, Compare, Send, Balance, Rates, Profile)
        |  HTTPS in deployment; session cookie (HttpOnly, SameSite=Strict)
FastAPI (app/main.py): authentication, rate limits, security headers, validation
        |
        |-- per-request user context (app/userctx.py)
        |
   +----+------------------------+---------------------------+
   |                             |                           |
Agent (app/agent.py)      Option endpoints             Profile / Dashboard
Gemini + 4 tools          (no LLM)                     (app/student_profile.py)
   |                             |                           |
   +-----> Policy (app/policy.py): tiers, default deny, limits <----+
                         |
              Tools (app/tools.py): cost model, balances, ledger
                         |
         Data files (app/data/*), per-user ledger and profile files
                         |
              Audit log (app/audit.py, append-only JSONL, user-attributed)
```

| Module | Responsibility |
|---|---|
| `main.py` | HTTP API, authentication endpoints, per-user chat rate limit, security headers, input validation |
| `auth.py` | Registration, login, scrypt password hashing, server-side sessions, lockout, invite code |
| `userctx.py` | Carries the current user through each request so tools, policy and audit act for the right person |
| `agent.py` | Gemini agent with four tools, retry and model fallback, per-user chat and pending-request state |
| `tools.py` | Cost model, balances, simulated transfer, per-user ledger |
| `policy.py` | Permission tiers, default deny, per-route and cumulative daily limits |
| `student_profile.py` | Strictly validated student profile and the Home dashboard planner |
| `audit.py` | Append-only JSONL record of decisions, tool calls, logins and transfers |
| `static/index.html` | Single-page UI built without HTML string injection |

## 4. Core algorithms

### 4.1 Total cost of a transfer
For an amount in USD and each route:

```
total_fees   = fixed_fee + amount * percent_fee/100 + amount * fx_margin/100
total_payable = amount + total_fees
total_payable_BDT = total_payable * simulated USD/BDT rate
```

Worked example, $3,000 (simulated routes):

| Route | Fixed | Percent | FX margin | Total fees | Arrives |
|---|---|---|---|---|---|
| Digital transfer | $2 | $18 (0.6%) | $15 (0.5%) | **$35** | 1 day |
| Traditional bank wire | $25 | $0 | $75 (2.5%) | $100 | 3 days |
| University portal card | $0 | $87 (2.9%) | $45 (1.5%) | $132 | same day |

The route with no fixed fee costs the most, because its cost is hidden in the percentages. Routes whose maximum amount is below the request are marked ineligible.

### 4.2 Cheapest route that meets a deadline
Eligible routes are sorted by total fees. With a deadline in days, routes slower than the deadline are excluded, and the cheapest remaining route is `cheapest_on_time`. With no deadline, it is the cheapest overall.

### 4.3 Payment planner (Home dashboard)
For each tuition instalment in the profile:

```
days_left   = due_date - today
budget_days = max(days_left - 3, 0)          # 3-day safety buffer
route       = cheapest_on_time(amount_usd, budget_days)
send_by     = due_date - (3 + route.speed_days)
```

Statuses are `paid`, `overdue` (past due), `due_soon` (14 days or fewer) and `upcoming`. The next unpaid instalment drives the recommendation. If no route fits both the amount and the time left, the dashboard shows a warning and no recommendation. Amounts in other currencies are converted with the simulated rates.

### 4.4 Transfer lifecycle
1. The user (or the AI on the user's behalf) asks to **prepare** a transfer. Policy checks everything except the human confirmation. If it passes, a pending request is stored for that user (maximum 5).
2. The user presses **Confirm**. This endpoint is not available to the model.
3. Policy runs again, now including cumulative daily total, balance and route limits. If allowed, the transfer is written to that user's ledger and the audit log.

## 5. AI agent design

- **Model:** Google Gemini through the `google-genai` SDK, with automatic tool calling at low temperature.
- **Tools the model can call:** `get_balance`, `get_fx_rate`, `compare_routes`, `propose_transfer`. There is no tool that executes a transfer.
- **System rules:** the model must not calculate fees or totals itself, must not invent figures, must never claim a transfer completed unless a tool result says so, must state that data is simulated, must refuse out-of-scope or rule-bypassing requests, and gives general information only.
- **Reliability:** temporary model errors (503, 429) are retried after 2, 5 and 10 seconds, then the chat continues on a fallback model with its history. Every retry and fallback is audited.
- **Isolation:** each signed-in user has a separate chat, pending list and trace, guarded by a per-user lock.
- **Hybrid design:** the option tabs (Compare, Send, Balance, Rates, Home) call the same tools and policy without the model, so they work when the model is slow or busy.

## 6. Security design (summary)

Full detail and the known-risk list are in `docs/SECURITY.md`.

- **Permission tiers:** read, advise, transfer (human confirmation required), blocked. Any tool not listed is denied by default.
- **Human-only confirmation,** re-checked by policy at the moment of confirmation.
- **Limits in code, not in prompts:** per-route maximum, verified-account check, cumulative daily limit, valid amounts only.
- **Authentication:** scrypt password hashing with a unique salt, server-side sessions with a 2-hour sliding expiry, lockout after repeated failures, optional invite code, per-user data isolation.
- **Web hardening:** HttpOnly SameSite=Strict cookies, content-security-policy and other security headers, no HTML built from strings in the page, chat rate limit.
- **Privacy:** the profile rejects unknown fields (no passport, ID or bank account numbers), the user can download or delete their data, and profile values are never written to the audit log.

## 7. Data and storage

Current storage is plain files under `app/data/`: static simulated data (account, rates, routes), per-user ledger files, per-user profile files, a user file with hashed passwords, and an append-only audit file. This keeps the prototype dependency-free and easy to inspect.

Known consequence: balance and daily-limit checks read the ledger and then append to it as separate steps, so truly simultaneous confirmations could both pass the check. The planned fix is a database transaction (see section 9).

## 8. Testing

The repository contains 93 automated tests, all passing at the time of writing. They need no API key and no network, and use temporary files so they never touch real data. They cover:
- the cost model and deadline selection with known numbers,
- the permission tiers, default deny, per-route and cumulative limits,
- the confirmation flow, double-confirm refusal and insufficient funds,
- the claim that the model has no money-moving tool,
- authentication: hashing, lockout, expiry, sessions, invite code,
- all protected endpoints returning 401 without login, and isolation between two users,
- the profile: strict validation, rejection of sensitive fields, the dashboard planner, export and delete,
- page-level checks that unsafe HTML-writing calls are absent.

Run with `pytest -q`.

## 9. Limitations and roadmap

- Simulated data only: no live rates or provider quotes.
- Files instead of a database. **Planned:** SQLite with transactions (users, profiles, instalments, transfers, pending requests, audit events), then PostgreSQL for production, which makes the limit check and debit one atomic step.
- Sessions are in memory and end on restart. No two-factor login or password reset.
- Exchange rates have no timestamps or freshness checks. Planned: carry a source and timestamp on every rate and refuse stale ones.
- The explanation text is written by the model. Numbers are tool-grounded, but the explanation is not independently verified.
- Single-model chain, not a multi-agent system.
- Bangla-language support and local regulatory context are not implemented. This is the main product gap and our planned focus for Bangladeshi students.