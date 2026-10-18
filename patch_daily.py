from pathlib import Path

p = Path("app/policy.py")
s = p.read_text()
assert "_spent_today_usd" not in s, "Already patched"


def swap(text, old, new):
    assert text.count(old) == 1, "Anchor missing or not unique: " + old
    return text.replace(old, new)


s = swap(s, "import json\n", "import json\nfrom datetime import datetime, timezone\n")

HELPER = '''def _spent_today_usd() -> float:
    """Sum of simulated transfers recorded in the ledger today (UTC)."""
    from app import tools  # local import avoids a circular import
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(t["amount_usd"] for t in tools._read_ledger() if t["ts"][:10] == today)


'''
s = swap(s, "def check(", HELPER + "def check(")

CHECK = '''    limit = account["daily_transfer_limit_usd"]
    spent = _spent_today_usd()
    if spent + amount > limit:
        return Decision(
            False, Tier.BLOCKED,
            f"Would exceed the daily limit: ${spent:,.0f} already sent today, limit ${limit:,}",
        )
'''
s = swap(s, "    if not confirmed:\n", CHECK + "    if not confirmed:\n")
p.write_text(s)

t = Path("tests/test_agent_safety.py")
if t.exists():
    ts = t.read_text()
    old = '    second = agent.propose_transfer(3000, "digital_transfer")["pending_id"]\n    res = agent.confirm_transfer(second)'
    new = '    second = agent.propose_transfer(1000, "digital_transfer")["pending_id"]\n    res = agent.confirm_transfer(second)'
    if ts.count(old) == 1:
        ts = ts.replace(old, new)
    ts += '''

def test_daily_total_is_enforced_across_transfers():
    first = agent.propose_transfer(3000, "digital_transfer")["pending_id"]
    assert agent.confirm_transfer(first)["status"] == "completed"
    second = agent.propose_transfer(3000, "digital_transfer")
    assert second["status"] == "refused"
    assert "daily" in second["reason"].lower()
    assert agent.PENDING == {}
'''
    t.write_text(ts)
    print("Tests updated")
else:
    print("tests/test_agent_safety.py not found, test update skipped")

print("Patched OK")
