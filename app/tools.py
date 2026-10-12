import json
from pathlib import Path

DATA = Path(__file__).parent / "data"


def _load(name: str) -> dict:
    with open(DATA / f"{name}.json") as f:
        return json.load(f)


def get_balance(currency: str | None = None) -> dict:
    """Read-only: return account balance(s)."""
    balances = current_balances()
    if currency:
        c = currency.upper()
        if c not in balances:
            return {"error": f"No {c} balance in this account"}
        return {"currency": c, "balance": balances[c]}
    return {"balances": balances}


def get_fx_rate(currency: str) -> dict:
    """Read-only: simulated mid-market rate, 1 USD in the given currency."""
    rates = _load("fx_rates")["mid_market"]
    c = currency.upper()
    if c not in rates:
        return {"error": f"Unsupported currency: {c}"}
    return {"pair": f"USD/{c}", "rate": rates[c], "note": "Simulated rate"}


def compare_routes(amount_usd: float, days_available: int | None = None) -> dict:
    """Advice only: compare transfer routes for sending amount_usd.

    Cost model (all in USD):
      total_fees = fixed_fee + amount * percent_fee% + amount * fx_margin%
      total_payable = amount + total_fees
    Total in BDT uses the simulated mid-market rate.
    """
    if amount_usd <= 0:
        return {"error": "Amount must be greater than zero"}

    bdt_rate = _load("fx_rates")["mid_market"]["BDT"]
    options = []

    for r in _load("routes")["routes"]:
        eligible = amount_usd <= r["max_amount_usd"]
        option = {
            "route_id": r["id"],
            "name": r["name"],
            "eligible": eligible,
            "speed_days": r["speed_days"],
        }
        if not eligible:
            option["reason"] = f"Amount exceeds route limit of ${r['max_amount_usd']:,}"
        else:
            fees = (
                r["fixed_fee_usd"]
                + amount_usd * r["percent_fee"] / 100
                + amount_usd * r["fx_margin_percent"] / 100
            )
            payable_usd = amount_usd + fees
            option.update(
                total_fees_usd=round(fees, 2),
                total_payable_usd=round(payable_usd, 2),
                total_payable_bdt=round(payable_usd * bdt_rate, 2),
                meets_deadline=(
                    None if days_available is None
                    else r["speed_days"] <= days_available
                ),
            )
        options.append(option)

    eligible_opts = [o for o in options if o["eligible"]]
    eligible_opts.sort(key=lambda o: o["total_fees_usd"])
    on_time = [o for o in eligible_opts if o["meets_deadline"] in (None, True)]

    return {
        "amount_usd": amount_usd,
        "days_available": days_available,
        "options": options,
        "cheapest_overall": eligible_opts[0]["route_id"] if eligible_opts else None,
        "cheapest_on_time": on_time[0]["route_id"] if on_time else None,
    }


# ---------------------------------------------------------------
# Simulated transfers (Tier 2): ledger + policy-guarded execution
# ---------------------------------------------------------------
import uuid
from datetime import datetime, timezone

from app import audit, policy

LEDGER = DATA / "ledger.jsonl"


def _read_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    with open(LEDGER) as f:
        return [json.loads(line) for line in f if line.strip()]


def current_balances() -> dict:
    """Seed balances from account.json minus everything in the ledger."""
    balances = dict(_load("account")["balances"])
    for tx in _read_ledger():
        balances[tx["currency"]] -= tx["debit"]
    return balances


def simulate_transfer(amount_usd: float, route_id: str, confirmed: bool = False) -> dict:
    """Tier 2: simulated transfer. Refuses unless policy allows it."""
    decision = policy.check(
        "simulate_transfer",
        {"amount_usd": amount_usd, "route_id": route_id},
        confirmed,
    )
    if not decision.allowed:
        return {"status": "refused", "reason": decision.reason}

    quote = compare_routes(amount_usd)
    option = next(o for o in quote["options"] if o["route_id"] == route_id)
    debit_bdt = option["total_payable_bdt"]

    if current_balances()["BDT"] < debit_bdt:
        audit.log("transfer_failed", reason="insufficient_funds",
                  route_id=route_id, amount_usd=amount_usd)
        return {"status": "refused", "reason": "Insufficient BDT balance"}

    tx = {
        "txn_id": "TXN-" + uuid.uuid4().hex[:8].upper(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "route_id": route_id,
        "amount_usd": amount_usd,
        "fees_usd": option["total_fees_usd"],
        "currency": "BDT",
        "debit": debit_bdt,
    }
    with open(LEDGER, "a") as f:
        f.write(json.dumps(tx) + "\n")
    audit.log("transfer_executed", **tx)
    return {"status": "completed", **tx}
