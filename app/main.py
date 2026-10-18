import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import agent, audit, policy, tools

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="StudentFin Agent")
STATIC = Path(__file__).parent / "static"
AUDIT_FILE = Path(__file__).parent / "data" / "audit.jsonl"


class ChatIn(BaseModel):
    message: str


class PendingIn(BaseModel):
    pending_id: str


class CompareIn(BaseModel):
    amount_usd: float = Field(gt=0, le=1_000_000)
    days_available: int | None = Field(default=None, ge=0, le=365)


class ProposeIn(BaseModel):
    amount_usd: float = Field(gt=0, le=1_000_000)
    route_id: str = Field(min_length=1, max_length=40)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# ---------------- Chat (LLM) ----------------

@app.post("/api/chat")
def chat(body: ChatIn):
    msg = body.message.strip()
    if not msg or len(msg) > 1000:
        raise HTTPException(400, "Message must be 1-1000 characters")
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
def confirm(body: PendingIn):
    result = agent.confirm_transfer(body.pending_id)
    return {"result": result, "balances": tools.current_balances()}


@app.post("/api/cancel")
def cancel(body: PendingIn):
    agent.PENDING.pop(body.pending_id, None)
    audit.log("user_cancelled", pending_id=body.pending_id)
    return {"status": "cancelled"}


@app.post("/api/reset")
def reset():
    agent.reset()
    return {"status": "reset"}


# ---------------- Read endpoints ----------------

@app.get("/api/balance")
def balance():
    return tools.current_balances()


@app.get("/api/audit")
def audit_tail():
    if not AUDIT_FILE.exists():
        return []
    lines = AUDIT_FILE.read_text().strip().splitlines()[-25:]
    return [json.loads(line) for line in lines]


@app.get("/api/routes")
def route_list():
    return tools._load("routes")["routes"]


@app.get("/api/fx")
def fx_list():
    return tools._load("fx_rates")


@app.get("/api/transactions")
def transactions():
    return tools._read_ledger()[-10:][::-1]


@app.get("/api/pending")
def pending():
    return agent.PENDING


# ---------------- Option modules (no LLM, same policy + audit) ----------------

@app.post("/api/compare")
def compare(body: CompareIn):
    d = policy.check("compare_routes", body.model_dump())
    if not d.allowed:
        raise HTTPException(403, d.reason)
    return tools.compare_routes(body.amount_usd, body.days_available)


@app.post("/api/propose")
def propose(body: ProposeIn):
    result = agent.propose_transfer(body.amount_usd, body.route_id)
    return {"result": result, "pending": agent.PENDING}