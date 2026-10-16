import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import agent, audit, tools

app = FastAPI(title="StudentFin Agent")
STATIC = Path(__file__).parent / "static"
AUDIT_FILE = Path(__file__).parent / "data" / "audit.jsonl"


class ChatIn(BaseModel):
    message: str


class PendingIn(BaseModel):
    pending_id: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/chat")
def chat(body: ChatIn):
    msg = body.message.strip()
    if not msg or len(msg) > 1000:
        raise HTTPException(400, "Message must be 1-1000 characters")
    try:
        return agent.ask(msg)
    except Exception as e:
        audit.log("model_error", error=type(e).__name__)
        raise HTTPException(502, f"Model error ({type(e).__name__}). Try again in a moment.")


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


@app.get("/api/balance")
def balance():
    return tools.current_balances()


@app.get("/api/audit")
def audit_tail():
    if not AUDIT_FILE.exists():
        return []
    lines = AUDIT_FILE.read_text().strip().splitlines()[-25:]
    return [json.loads(line) for line in lines]
