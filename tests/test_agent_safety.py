from app import agent, tools


def test_model_cannot_confirm_or_execute():
    """Core security claim: the model has no tool that moves money."""
    names = {getattr(t, "__name__", str(t)) for t in agent._config.tools}
    assert "confirm_transfer" not in names
    assert "simulate_transfer" not in names
    assert "propose_transfer" in names


def test_propose_does_not_move_money():
    before = tools.current_balances()["BDT"]
    out = agent.propose_transfer(3000, "digital_transfer")
    assert out["status"] == "awaiting_user_confirmation"
    assert tools.current_balances()["BDT"] == before
    assert len(agent.PENDING) == 1


def test_propose_over_limit_is_refused_and_not_queued():
    out = agent.propose_transfer(9000, "digital_transfer")
    assert out["status"] == "refused"
    assert agent.PENDING == {}


def test_unknown_route_not_queued():
    assert agent.propose_transfer(100, "nope")["status"] == "refused"
    assert agent.PENDING == {}


def test_human_confirmation_executes_and_debits():
    pid = agent.propose_transfer(3000, "digital_transfer")["pending_id"]
    res = agent.confirm_transfer(pid)
    assert res["status"] == "completed"
    assert tools.current_balances()["BDT"] == 450000.0 - 370270.0


def test_pending_cannot_be_confirmed_twice():
    pid = agent.propose_transfer(3000, "digital_transfer")["pending_id"]
    assert agent.confirm_transfer(pid)["status"] == "completed"
    assert agent.confirm_transfer(pid)["status"] == "refused"


def test_unknown_pending_id_refused():
    assert agent.confirm_transfer("PEND-FAKE00")["status"] == "refused"


def test_insufficient_funds_refused():
    first = agent.propose_transfer(3000, "digital_transfer")["pending_id"]
    assert agent.confirm_transfer(first)["status"] == "completed"
    second = agent.propose_transfer(1000, "digital_transfer")["pending_id"]
    res = agent.confirm_transfer(second)
    assert res["status"] == "refused" and "Insufficient" in res["reason"]


def test_daily_total_is_enforced_across_transfers():
    first = agent.propose_transfer(3000, "digital_transfer")["pending_id"]
    assert agent.confirm_transfer(first)["status"] == "completed"
    second = agent.propose_transfer(3000, "digital_transfer")
    assert second["status"] == "refused"
    assert "daily" in second["reason"].lower()
    assert agent.PENDING == {}
