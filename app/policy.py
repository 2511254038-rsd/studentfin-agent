import json
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from app import audit

DATA = Path(__file__).parent / "data"


class Tier(IntEnum):
    READ = 0       # read-only data
    ADVISE = 1     # calculations and advice, no side effects
    TRANSFER = 2   # simulated money movement (needs confirmation)
    BLOCKED = 3    # never allowed


# Every tool must be listed here. Anything not listed is blocked.
TOOL_TIERS = {
    "get_balance": Tier.READ,
    "get_fx_rate": Tier.READ,
    "compare_routes": Tier.ADVISE,
    "simulate_transfer": Tier.TRANSFER,
}


@dataclass
class Decision:
    allowed: bool
    tier: Tier
    reason: str


def _load(name: str) -> dict:
    with open(DATA / f"{name}.json") as f:
        return json.load(f)


def _spent_today_usd() -> float:
    """Sum of simulated transfers recorded in the ledger today (UTC)."""
    from app import tools  # local import avoids a circular import
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(t["amount_usd"] for t in tools._read_ledger() if t["ts"][:10] == today)


def check(tool: str, args: dict, confirmed: bool = False) -> Decision:
    """Decide whether a tool call may run. Default deny. Every decision is logged."""
    decision = _decide(tool, args, confirmed)
    audit.log(
        "policy_decision",
        tool=tool,
        args=args,
        confirmed=confirmed,
        allowed=decision.allowed,
        tier=decision.tier.name,
        reason=decision.reason,
    )
    return decision


def _decide(tool: str, args: dict, confirmed: bool) -> Decision:
    tier = TOOL_TIERS.get(tool)
    if tier is None:
        return Decision(False, Tier.BLOCKED, f"Unknown tool '{tool}' (default deny)")

    if tier in (Tier.READ, Tier.ADVISE):
        return Decision(True, tier, "Read/advice actions are allowed")

    # --- Tier.TRANSFER rules (simulated money movement) ---
    account = _load("account")
    amount = args.get("amount_usd")
    route_id = args.get("route_id")

    if not account.get("verified"):
        return Decision(False, Tier.BLOCKED, "Account is not verified")
    if not isinstance(amount, (int, float)) or amount <= 0:
        return Decision(False, Tier.BLOCKED, "Amount must be a positive number")
    if amount > account["daily_transfer_limit_usd"]:
        return Decision(
            False, Tier.BLOCKED,
            f"Amount exceeds daily limit of ${account['daily_transfer_limit_usd']:,}",
        )
    route = next((r for r in _load("routes")["routes"] if r["id"] == route_id), None)
    if route is None:
        return Decision(False, Tier.BLOCKED, f"Unknown route '{route_id}'")
    if amount > route["max_amount_usd"]:
        return Decision(False, Tier.BLOCKED, "Amount exceeds this route's maximum")
    limit = account["daily_transfer_limit_usd"]
    spent = _spent_today_usd()
    if spent + amount > limit:
        return Decision(
            False, Tier.BLOCKED,
            f"Would exceed the daily limit: ${spent:,.0f} already sent today, limit ${limit:,}",
        )
    if not confirmed:
        return Decision(False, Tier.TRANSFER, "Needs explicit user confirmation first")

    return Decision(True, Tier.TRANSFER, "Transfer allowed: verified, within limits, confirmed")
