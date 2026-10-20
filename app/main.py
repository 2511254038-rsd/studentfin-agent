import json
import logging
import os
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import agent, audit, auth, policy, tools, userctx

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="StudentFin Agent")
STATIC = Path(__file__).parent / "static"

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"   # set to 1 when served over HTTPS
MAX_USERS = 200
CHAT_LIMIT = 15          # chat messages allowed per user ...
CHAT_WINDOW_S = 60       # ... per this many seconds
_chat_times: dict[str, list[float]] = {}


class RegisterIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)
    invite_code: str = Field(default="", max_length=100)


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)


class ChatIn(BaseModel):
    message: str


class PendingIn(BaseModel):
    pending_id: str = Field(min_length=1, max_length=40)


class CompareIn(BaseModel):
    amount_usd: float = Field(gt=0, le=1_000_000)
    days_available: int | None = Field(default=None, ge=0, le=365)


class ProposeIn(BaseModel):
    amount_usd: float = Field(gt=0, le=1_000_000)
    route_id: str = Field(min_length=1, max_length=40)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path == "/":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
    return response


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth.COOKIE_NAME, token, max_age=auth.SESSION_TTL_S, httponly=True,
        samesite="strict", secure=COOKIE_SECURE, path="/",
    )


def _check_chat_rate(user: str) -> None:
    now = time.time()
    times = [t for t in _chat_times.get(user, []) if now - t < CHAT_WINDOW_S]
    if len(times) >= CHAT_LIMIT:
        raise HTTPException(429, "Too many messages. Please wait a minute.")
    times.append(now)
    _chat_times[user] = times


# ---------------- Public ----------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# ---------------- Authentication ----------------

@app.post("/api/auth/register")
def register(body: RegisterIn, response: Response):
    if len(auth._load_users()) >= MAX_USERS:
        raise HTTPException(400, "Registration is full")
    try:
        auth.register(body.username, body.password, body.invite_code)
        token = auth.login(body.username, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(429, str(e))
    _set_cookie(response, token)
    return {"user": body.username.lower()}


@app.post("/api/auth/login")
def login(body: LoginIn, response: Response):
    try:
        token = auth.login(body.username, body.password)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    except ValueError as e:
        raise HTTPException(401, str(e))
    _set_cookie(response, token)
    return {"user": body.username.lower()}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.COOKIE_NAME))
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"status": "logged_out"}


@app.get("/api/auth/me")
def me(user: str = Depends(auth.require_user)):
    return {"user": user}


# ---------------- Chat (LLM) ----------------

@app.post("/api/chat")
def chat(body: ChatIn, user: str = Depends(auth.require_user)):
    msg = body.message.strip()
    if not msg or len(msg) > 1000:
        raise HTTPException(400, "Message must be 1-1000 characters")
    _check_chat_rate(user)
    with userctx.as_user(user):
        try:
            return agent.ask(msg)
        except Exception as e:
            logger.exception("chat failed")  # full traceback goes to the terminal only
            audit.log("model_error", error=type(e).__name__)
            text = str(e)
            if "429" in text or "RESOURCE_EXHAUSTED" in text:
                raise HTTPException(
                    429,
                    "The free AI quota is used up for now. The option tabs still work, "
                    "or try the chat again in a minute.",
                )
            raise HTTPException(502, f"Model error ({type(e).__name__}). Try again in a moment.")


# ---------------- Human-only actions (never exposed to the model) ----------------

@app.post("/api/confirm")
def confirm(body: PendingIn, user: str = Depends(auth.require_user)):
    with userctx.as_user(user):
        result = agent.confirm_transfer(body.pending_id)
        return {"result": result, "balances": tools.current_balances()}


@app.post("/api/cancel")
def cancel(body: PendingIn, user: str = Depends(auth.require_user)):
    with userctx.as_user(user):
        agent.cancel_pending(body.pending_id)
        audit.log("user_cancelled", pending_id=body.pending_id)
    return {"status": "cancelled"}


@app.post("/api/reset")
def reset(user: str = Depends(auth.require_user)):
    with userctx.as_user(user):
        agent.reset()
    return {"status": "reset"}


# ---------------- Read endpoints ----------------

@app.get("/api/balance")
def balance(user: str = Depends(auth.require_user)):
    with userctx.as_user(user):
        return tools.current_balances()


@app.get("/api/audit")
def audit_tail(user: str = Depends(auth.require_user)):
    if not audit.LOG_FILE.exists():
        return []
    rows = []
    for line in audit.LOG_FILE.read_text().strip().splitlines()[-500:]:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("user") == user:
            rows.append(entry)
    return rows[-25:]


@app.get("/api/routes")
def route_list(user: str = Depends(auth.require_user)):
    return tools._load("routes")["routes"]


@app.get("/api/fx")
def fx_list(user: str = Depends(auth.require_user)):
    return tools._load("fx_rates")


@app.get("/api/transactions")
def transactions(user: str = Depends(auth.require_user)):
    with userctx.as_user(user):
        return tools._read_ledger()[-10:][::-1]


@app.get("/api/pending")
def pending(user: str = Depends(auth.require_user)):
    with userctx.as_user(user):
        return agent.get_pending()


# ---------------- Option modules (no LLM, same policy + audit) ----------------

@app.post("/api/compare")
def compare(body: CompareIn, user: str = Depends(auth.require_user)):
    with userctx.as_user(user):
        d = policy.check("compare_routes", body.model_dump())
        if not d.allowed:
            raise HTTPException(403, d.reason)
        return tools.compare_routes(body.amount_usd, body.days_available)


@app.post("/api/propose")
def propose(body: ProposeIn, user: str = Depends(auth.require_user)):
    with userctx.as_user(user):
        result = agent.propose_transfer(body.amount_usd, body.route_id)
        return {"result": result, "pending": agent.get_pending()}