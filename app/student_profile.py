"""Student profile: stored per user, strictly validated, no sensitive identifiers.
Also builds the dashboard (next payment, send-by date, recommended route)."""
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app import tools, userctx

DIR = Path(__file__).parent / "data" / "profiles"
SAFETY_DAYS = 3
Currency = Literal["USD", "BDT", "EUR", "GBP"]
DUE_MIN, DUE_MAX = date(2020, 1, 1), date(2100, 1, 1)


class Instalment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=40)
    amount: float = Field(gt=0, le=1_000_000)
    currency: Currency
    due: date = Field(ge=DUE_MIN, le=DUE_MAX)
    paid: bool = False


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    display_name: str = Field(default="", max_length=40)
    university: str = Field(default="", max_length=80)
    home_country: str = Field(default="Bangladesh", max_length=60)
    study_country: str = Field(default="", max_length=60)
    home_currency: Currency = "BDT"
    study_currency: Currency = "USD"
    monthly_support_usd: float = Field(default=0, ge=0, le=100_000)
    instalments: list[Instalment] = Field(default_factory=list, max_length=6)


def _path(user: str) -> Path:
    if not userctx.SAFE_NAME.match(user):
        raise ValueError("invalid user name")
    DIR.mkdir(parents=True, exist_ok=True)
    return DIR / f"{user}.json"


def load(user: str) -> dict | None:
    path = _path(user)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save(user: str, profile: Profile) -> None:
    path = _path(user)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(profile.model_dump(mode="json"), f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def delete(user: str) -> None:
    _path(user).unlink(missing_ok=True)


def build_dashboard(prof: dict | None, balances: dict, today: date | None = None) -> dict:
    """Turn the profile into a plan: statuses, next payment, send-by date, best on-time route."""
    today = today or date.today()
    out = {"profile": prof, "balances": balances, "monthly_support_usd": 0,
           "instalments": [], "next": None}
    if not prof:
        return out
    out["monthly_support_usd"] = prof.get("monthly_support_usd", 0)
    rates = tools._load("fx_rates")["mid_market"]

    items = []
    for inst in prof.get("instalments", []):
        due = date.fromisoformat(inst["due"])
        days_left = (due - today).days
        amount_usd = round(inst["amount"] / rates[inst["currency"]], 2)
        if inst.get("paid"):
            status = "paid"
        elif days_left < 0:
            status = "overdue"
        elif days_left <= 14:
            status = "due_soon"
        else:
            status = "upcoming"
        items.append({**inst, "days_left": days_left, "amount_usd": amount_usd, "status": status})
    items.sort(key=lambda i: i["due"])
    out["instalments"] = items

    upcoming = [i for i in items if i["status"] in ("due_soon", "upcoming")]
    if upcoming:
        i = upcoming[0]
        budget_days = max(i["days_left"] - SAFETY_DAYS, 0)
        plan = tools.compare_routes(i["amount_usd"], budget_days)
        rec = None
        if plan.get("cheapest_on_time"):
            rec = next(o for o in plan["options"] if o["route_id"] == plan["cheapest_on_time"])
        send_by, warning = None, None
        if rec:
            send_by = (date.fromisoformat(i["due"])
                       - timedelta(days=SAFETY_DAYS + rec["speed_days"])).isoformat()
        else:
            warning = "No simulated route fits both this amount and the time left."
        out["next"] = {
            "label": i["label"], "due": i["due"], "days_left": i["days_left"],
            "amount": i["amount"], "currency": i["currency"], "amount_usd": i["amount_usd"],
            "budget_days": budget_days, "safety_days": SAFETY_DAYS,
            "recommended": rec, "send_by": send_by, "warning": warning,
            "send_now": bool(send_by and date.fromisoformat(send_by) < today),
        }
    return out