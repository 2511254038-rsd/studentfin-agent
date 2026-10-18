import json

from app import audit, policy


def _args(amount=3000, route="digital_transfer"):
    return {"amount_usd": amount, "route_id": route}


def test_read_and_advice_tools_allowed():
    assert policy.check("get_balance", {}).allowed
    assert policy.check("compare_routes", {"amount_usd": 100}).allowed


def test_unknown_tool_is_denied():
    d = policy.check("delete_everything", {}, confirmed=True)
    assert not d.allowed and d.tier == policy.Tier.BLOCKED


def test_transfer_needs_confirmation():
    d = policy.check("simulate_transfer", _args(), confirmed=False)
    assert not d.allowed and d.tier == policy.Tier.TRANSFER


def test_confirmed_transfer_within_limit_allowed():
    assert policy.check("simulate_transfer", _args(), confirmed=True).allowed


def test_over_daily_limit_denied_even_if_confirmed():
    d = policy.check("simulate_transfer", _args(9000), confirmed=True)
    assert not d.allowed and "limit" in d.reason.lower()


def test_unknown_route_denied():
    assert not policy.check("simulate_transfer", _args(route="nope"), confirmed=True).allowed


def test_bad_amounts_denied():
    for bad in (0, -10, "100", None):
        d = policy.check("simulate_transfer", _args(bad), confirmed=True)
        assert not d.allowed, f"amount {bad!r} should be denied"


def test_every_decision_is_audited():
    policy.check("get_balance", {})
    policy.check("delete_everything", {})
    lines = [json.loads(x) for x in audit.LOG_FILE.read_text().splitlines()]
    assert [e["event"] for e in lines] == ["policy_decision", "policy_decision"]
    assert lines[1]["allowed"] is False
