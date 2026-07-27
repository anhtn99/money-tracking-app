from decimal import Decimal

# The August 2026 statement cycle (7/14 - 8/13) is the default test
# window -- it's the first cycle under the statement-cycle scheme, so it
# exercises the non-calendar boundaries rather than accidentally passing
# because the bounds happened to line up with a calendar month.
CYCLE = {"year": 2026, "month": 8}
IN_CYCLE = "2026-07-20"


def _create_account(client, is_shared=False, account_type="depository", name="Joint Checking") -> str:
    response = client.post(
        "/accounts/manual",
        json={"name": name, "institution": "Chase", "account_type": account_type, "is_shared": is_shared},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _make_txn(client, account_id, amount, transaction_type="regular", date_=IN_CYCLE, **overrides):
    payload = {
        "account_id": account_id,
        "name": "Test txn",
        "amount": amount,
        "transaction_date": date_,
        "transaction_type": transaction_type,
    }
    payload.update(overrides)
    response = client.post("/transactions/manual", json=payload)
    assert response.status_code == 201
    return response.json()


def _create_rule(client, is_shared, **overrides):
    payload = {
        "name": "Renter's Insurance", "icon": "🛡️", "frequency": "monthly",
        "name_match_type": "partial", "name_pattern": "STATE FARM",
        "amount_min": "40.00", "amount_max": "40.00", "expected_day_of_period": 5,
        "is_shared": is_shared,
    }
    payload.update(overrides)
    response = client.post("/recurring", json=payload)
    assert response.status_code == 201
    return response.json()


def _overview(client, **params):
    response = client.get("/shared-expenses/overview", params={**CYCLE, **params})
    assert response.status_code == 200
    return response.json()


def test_account_defaults_to_not_shared(client):
    response = client.post("/accounts/manual", json={
        "name": "Personal Checking", "institution": "Chase", "account_type": "depository",
    })
    assert response.status_code == 201
    assert response.json()["is_shared"] is False


def test_account_is_shared_togglable_via_patch(client):
    account_id = _create_account(client, is_shared=False)
    response = client.patch(f"/accounts/{account_id}", json={"is_shared": True})
    assert response.status_code == 200
    assert response.json()["is_shared"] is True


def test_regular_transaction_on_shared_account_is_included(client):
    account_id = _create_account(client, is_shared=True)
    _make_txn(client, account_id, "100.00")

    body = _overview(client)
    assert body["total_shared_spend"] == "100.00"
    assert len(body["transactions"]) == 1


def test_regular_transaction_on_non_shared_account_is_excluded(client):
    account_id = _create_account(client, is_shared=False)
    _make_txn(client, account_id, "100.00")

    body = _overview(client)
    assert Decimal(body["total_shared_spend"]) == Decimal("0.00")
    assert body["transactions"] == []


def test_transfer_and_income_on_shared_account_are_excluded_by_default(client):
    account_id = _create_account(client, is_shared=True)
    _make_txn(client, account_id, "500.00", transaction_type="transfer")  # e.g. credit card autopay
    _make_txn(client, account_id, "-2000.00", transaction_type="income")  # stray paycheck

    assert _overview(client)["transactions"] == []


def test_shared_recurring_rule_force_includes_transfer_typed_match(client):
    account_id = _create_account(client, is_shared=True)
    rule = _create_rule(client, is_shared=True)
    txn = _make_txn(
        client, account_id, "40.00", transaction_type="transfer",
        name="State Farm Insurance ACH", recurring_rule_id=rule["id"],
    )
    assert txn["is_recurring"] is True

    body = _overview(client)
    assert body["total_shared_spend"] == "40.00"
    assert len(body["transactions"]) == 1
    assert body["transactions"][0]["display_name"] == "Renter's Insurance"


def test_non_shared_recurring_rule_does_not_force_include_transfer(client):
    account_id = _create_account(client, is_shared=True)
    rule = _create_rule(client, is_shared=False)
    _make_txn(
        client, account_id, "40.00", transaction_type="transfer",
        name="State Farm Insurance ACH", recurring_rule_id=rule["id"],
    )

    assert _overview(client)["transactions"] == []


def test_split_sums_exactly_to_total_including_remainder(client):
    account_id = _create_account(client, is_shared=True)
    # $100.01 * 0.70 = $70.007 -> rounds to $70.01; Michelle absorbs the
    # remainder ($100.01 - $70.01 = $30.00) rather than independently
    # rounding 0.30 (which could land a penny off).
    _make_txn(client, account_id, "100.01")

    shares = {s["name"]: Decimal(s["amount_owed"]) for s in _overview(client)["shares"]}
    assert shares["Anh"] + shares["Michelle"] == Decimal("100.01")
    assert shares["Anh"] == Decimal("70.01")
    assert shares["Michelle"] == Decimal("30.00")


def test_overview_defaults_to_current_month(client):
    import datetime
    response = client.get("/shared-expenses/overview")
    assert response.status_code == 200
    body = response.json()
    today = datetime.date.today()
    assert body["year"] == today.year
    assert body["month"] == today.month


def test_overview_rejects_invalid_month(client):
    response = client.get("/shared-expenses/overview", params={"year": 2026, "month": 13})
    assert response.status_code == 422


# --- statement-cycle bounds -------------------------------------------

def test_overview_reports_the_statement_cycle_bounds(client):
    body = _overview(client)
    assert body["cycle_start"] == "2026-07-14"
    assert body["cycle_end"] == "2026-08-13"


def test_transaction_lands_in_the_cycle_not_the_calendar_month(client):
    """7/20 is in the AUGUST cycle -- the whole point of the switch away
    from calendar months."""
    account_id = _create_account(client, is_shared=True)
    _make_txn(client, account_id, "100.00", date_="2026-07-20")

    assert len(_overview(client, month=8)["transactions"]) == 1
    assert _overview(client, month=7)["transactions"] == []


def test_cycle_boundary_days_are_inclusive(client):
    account_id = _create_account(client, is_shared=True)
    _make_txn(client, account_id, "10.00", date_="2026-07-13")  # last day of July cycle
    _make_txn(client, account_id, "20.00", date_="2026-07-14")  # first day of Aug cycle
    _make_txn(client, account_id, "40.00", date_="2026-08-13")  # last day of Aug cycle
    _make_txn(client, account_id, "80.00", date_="2026-08-14")  # first day of Sep cycle

    assert _overview(client, month=7)["total_shared_spend"] == "10.00"
    assert _overview(client, month=8)["total_shared_spend"] == "60.00"
    assert _overview(client, month=9)["total_shared_spend"] == "80.00"


# --- recurring checklist ----------------------------------------------

def test_shared_recurring_rule_appears_unposted_when_no_charge_landed(client):
    _create_rule(client, is_shared=True, name="Chicago Rent", amount_min="1750.00", amount_max="1750.00")

    recurring = _overview(client)["recurring"]
    assert len(recurring) == 1
    assert recurring[0]["name"] == "Chicago Rent"
    assert recurring[0]["is_posted"] is False
    assert recurring[0]["expected_amount"] == "1750.00"
    assert recurring[0]["posted_amount"] is None
    assert recurring[0]["transaction_id"] is None


def test_recurring_marked_posted_once_its_charge_lands_in_the_cycle(client):
    account_id = _create_account(client, is_shared=True)
    rule = _create_rule(client, is_shared=True)
    txn = _make_txn(client, account_id, "40.00", name="State Farm Insurance ACH")

    recurring = _overview(client)["recurring"]
    assert recurring[0]["is_posted"] is True
    assert recurring[0]["posted_amount"] == "40.00"
    assert recurring[0]["posted_date"] == IN_CYCLE
    assert recurring[0]["transaction_id"] == txn["id"]
    assert recurring[0]["recurring_rule_id"] == rule["id"]


def test_recurring_charge_in_a_different_cycle_does_not_count_as_posted(client):
    account_id = _create_account(client, is_shared=True)
    _create_rule(client, is_shared=True)
    _make_txn(client, account_id, "40.00", name="State Farm Insurance ACH", date_="2026-08-20")

    assert _overview(client, month=8)["recurring"][0]["is_posted"] is False
    assert _overview(client, month=9)["recurring"][0]["is_posted"] is True


def test_non_shared_recurring_rules_are_not_on_the_checklist(client):
    _create_rule(client, is_shared=False)
    assert _overview(client)["recurring"] == []


def test_recurring_with_an_amount_range_has_no_single_expected_amount(client):
    _create_rule(client, is_shared=True, name="Gas Bill", amount_min="20.00", amount_max="400.00")

    recurring = _overview(client)["recurring"]
    assert recurring[0]["expected_amount"] is None
    assert recurring[0]["amount_min"] == "20.00"
    assert recurring[0]["amount_max"] == "400.00"


# --- settle-up tracking -------------------------------------------------
# Settlement matching requires BOTH the bank's naming convention for that
# person's transfer AND the exact amount owed for the cycle -- a settle-up
# is always a single transaction, never split or partial, so name-only or
# amount-only matching would be too loose (name-only could grab an
# unrelated transfer; amount-only could grab a coincidentally-equal one).

def _shares_by_name(body):
    return {s["name"]: s for s in body["shares"]}


def test_nobody_is_paid_without_a_matching_transfer_in(client):
    account_id = _create_account(client, is_shared=True)
    _make_txn(client, account_id, "100.00")

    shares = _shares_by_name(_overview(client))
    assert shares["Anh"]["is_paid"] is False
    assert shares["Michelle"]["is_paid"] is False
    assert Decimal(shares["Anh"]["amount_paid"]) == Decimal("0.00")


def test_transfer_matching_name_and_exact_amount_settles_the_share(client):
    account_id = _create_account(client, is_shared=True)
    card_id = _create_account(client, is_shared=True, account_type="credit_card", name="Venture X")
    _make_txn(client, card_id, "100.00")
    # Money IN is negative (see the sign convention on models/transaction.py).
    _make_txn(
        client, account_id, "-30.00", transaction_type="transfer",
        name="Capital One Transfer 1234567890", date_="2026-08-14",
    )

    shares = _shares_by_name(_overview(client))
    assert shares["Michelle"]["amount_owed"] == "30.00"
    assert shares["Michelle"]["is_paid"] is True
    assert shares["Michelle"]["amount_paid"] == "30.00"
    assert len(shares["Michelle"]["settlement_transfers"]) == 1
    assert shares["Michelle"]["settlement_transfers"][0]["amount"] == "30.00"
    # Michelle's transfer doesn't match Anh's pattern, so his share is untouched.
    assert shares["Anh"]["is_paid"] is False
    assert shares["Anh"]["settlement_transfers"] == []


def test_anhs_settlement_pattern_also_matches(client):
    account_id = _create_account(client, is_shared=True)
    _make_txn(client, account_id, "100.00")
    _make_txn(
        client, account_id, "-70.00", transaction_type="transfer",
        name="Online Transfer from CHK ...3792 transaction#123", date_="2026-08-14",
    )

    assert _shares_by_name(_overview(client))["Anh"]["is_paid"] is True


def test_settle_up_transfer_is_not_counted_as_a_shared_expense(client):
    account_id = _create_account(client, is_shared=True)
    _make_txn(client, account_id, "100.00")
    _make_txn(client, account_id, "-30.00", transaction_type="transfer", name="Capital One Transfer 555")

    body = _overview(client)
    assert body["total_shared_spend"] == "100.00"
    assert len(body["transactions"]) == 1


def test_wrong_amount_does_not_settle_the_share_even_with_matching_name(client):
    account_id = _create_account(client, is_shared=True)
    _make_txn(client, account_id, "100.00")
    # Michelle owes $30.00 -- a transfer for a different amount, even
    # with her bank's naming convention, isn't treated as this cycle's
    # settlement (could be an unrelated transfer, or a typo amount).
    _make_txn(client, account_id, "-20.00", transaction_type="transfer", name="Capital One Transfer 999")

    michelle = _shares_by_name(_overview(client))["Michelle"]
    assert michelle["amount_paid"] == "0.00"
    assert michelle["is_paid"] is False


def test_matching_amount_with_wrong_naming_convention_does_not_settle(client):
    account_id = _create_account(client, is_shared=True)
    _make_txn(client, account_id, "100.00")
    # Right amount, but this isn't how either person's bank labels a
    # settle-up transfer -- shouldn't be mistaken for one.
    _make_txn(client, account_id, "-30.00", transaction_type="transfer", name="Zelle from Michelle")

    assert _shares_by_name(_overview(client))["Michelle"]["is_paid"] is False


def test_transfer_after_the_settlement_window_is_ignored(client):
    account_id = _create_account(client, is_shared=True)
    _make_txn(client, account_id, "100.00")
    # Cycle ends 8/13; the window closes 30 days later.
    _make_txn(
        client, account_id, "-30.00", transaction_type="transfer",
        name="Capital One Transfer 555", date_="2026-09-20",
    )

    assert _shares_by_name(_overview(client))["Michelle"]["is_paid"] is False


def test_transfer_into_a_non_shared_or_credit_account_is_not_a_settlement(client):
    shared_checking = _create_account(client, is_shared=True)
    personal = _create_account(client, is_shared=False, name="Anh Personal Checking")
    card = _create_account(client, is_shared=True, account_type="credit_card", name="Venture X")
    _make_txn(client, shared_checking, "100.00")
    _make_txn(client, personal, "-30.00", transaction_type="transfer", name="Capital One Transfer 555")
    # A credit card payment is a transfer in, but it isn't a settle-up.
    _make_txn(client, card, "-30.00", transaction_type="transfer", name="Capital One Transfer 555")

    assert _shares_by_name(_overview(client))["Michelle"]["is_paid"] is False


def test_money_out_of_joint_checking_is_not_a_settlement(client):
    account_id = _create_account(client, is_shared=True)
    _make_txn(client, account_id, "100.00")
    # Positive = money out, e.g. reimbursing Michelle rather than her paying in.
    _make_txn(client, account_id, "30.00", transaction_type="transfer", name="Capital One Transfer 555")

    assert _shares_by_name(_overview(client))["Michelle"]["is_paid"] is False


def test_zero_total_cycle_is_not_reported_as_paid(client):
    _create_account(client, is_shared=True)

    shares = _shares_by_name(_overview(client))
    assert shares["Anh"]["amount_owed"] == "0.00"
    assert shares["Anh"]["is_paid"] is False
