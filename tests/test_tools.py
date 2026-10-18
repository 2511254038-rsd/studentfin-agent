from app import tools


def test_compare_routes_known_numbers():
    r = tools.compare_routes(3000, days_available=2)
    by_id = {o["route_id"]: o for o in r["options"]}
    assert by_id["digital_transfer"]["total_fees_usd"] == 35.0
    assert by_id["bank_wire"]["total_fees_usd"] == 100.0
    assert by_id["card_portal"]["total_fees_usd"] == 132.0
    assert r["cheapest_overall"] == "digital_transfer"
    assert r["cheapest_on_time"] == "digital_transfer"


def test_deadline_excludes_slow_route():
    r = tools.compare_routes(3000, days_available=2)
    bank = next(o for o in r["options"] if o["route_id"] == "bank_wire")
    assert bank["meets_deadline"] is False


def test_zero_fixed_fee_route_is_not_cheapest():
    """The no-fixed-fee route hides its cost in the percentage fee and FX margin."""
    r = tools.compare_routes(3000)
    by_id = {o["route_id"]: o for o in r["options"]}
    assert by_id["card_portal"]["total_fees_usd"] > by_id["digital_transfer"]["total_fees_usd"]


def test_route_maximum_is_enforced():
    r = tools.compare_routes(20000)
    by_id = {o["route_id"]: o for o in r["options"]}
    assert by_id["bank_wire"]["eligible"] is True
    assert by_id["digital_transfer"]["eligible"] is False
    assert by_id["card_portal"]["eligible"] is False


def test_invalid_amount_returns_error():
    assert "error" in tools.compare_routes(0)
    assert "error" in tools.compare_routes(-50)


def test_unknown_currency_and_balance_errors():
    assert "error" in tools.get_fx_rate("XYZ")
    assert "error" in tools.get_balance("XYZ")


def test_fx_rate_lookup():
    assert tools.get_fx_rate("bdt")["rate"] == 122.0
