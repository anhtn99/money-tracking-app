from decimal import Decimal


def test_default_household_members_are_seeded(client):
    """conftest.py seeds the same two rows migration 585d580c5b49 seeds in
    real Postgres -- this pins that the app is usable out of the box
    without anyone having to configure a household first."""
    response = client.get("/household-members")
    assert response.status_code == 200
    members = response.json()
    assert [m["name"] for m in members] == ["Anh", "Michelle"]
    assert members[0]["percentage"] == "0.7000"
    assert members[1]["percentage"] == "0.3000"
    assert members[0]["settlement_patterns"] == ["online transfer from chk"]


def test_replace_updates_the_whole_set(client):
    response = client.put("/household-members", json={"members": [
        {"name": "Anh", "percentage": "0.5000", "settlement_patterns": ["online transfer from chk"]},
        {"name": "Michelle", "percentage": "0.3000", "settlement_patterns": ["capital one transfer"]},
        {"name": "Roommate", "percentage": "0.2000", "settlement_patterns": ["venmo"]},
    ]})
    assert response.status_code == 200
    members = response.json()
    assert [m["name"] for m in members] == ["Anh", "Michelle", "Roommate"]
    assert [m["display_order"] for m in members] == [0, 1, 2]

    refetched = client.get("/household-members").json()
    assert [m["name"] for m in refetched] == ["Anh", "Michelle", "Roommate"]


def test_replace_assigns_fresh_ids(client):
    """Nothing else references household_members by id (unlike Category/
    RecurringRule, which transactions link to), so a replace doesn't need
    to preserve them."""
    before = {m["name"]: m["id"] for m in client.get("/household-members").json()}
    client.put("/household-members", json={"members": [
        {"name": "Anh", "percentage": "0.7000", "settlement_patterns": []},
        {"name": "Michelle", "percentage": "0.3000", "settlement_patterns": []},
    ]})
    after = {m["name"]: m["id"] for m in client.get("/household-members").json()}
    assert before["Anh"] != after["Anh"]


def test_replace_rejects_percentages_that_dont_sum_to_one(client):
    response = client.put("/household-members", json={"members": [
        {"name": "Anh", "percentage": "0.7000", "settlement_patterns": []},
        {"name": "Michelle", "percentage": "0.2000", "settlement_patterns": []},
    ]})
    assert response.status_code == 422


def test_replace_rejects_an_empty_list(client):
    response = client.put("/household-members", json={"members": []})
    assert response.status_code == 422


def test_replace_rejects_a_zero_or_negative_percentage(client):
    response = client.put("/household-members", json={"members": [
        {"name": "Anh", "percentage": "1.0000", "settlement_patterns": []},
        {"name": "Michelle", "percentage": "0.0000", "settlement_patterns": []},
    ]})
    assert response.status_code == 422


def test_replace_rejects_a_percentage_over_one_hundred_percent(client):
    response = client.put("/household-members", json={"members": [
        {"name": "Anh", "percentage": "1.5000", "settlement_patterns": []},
    ]})
    assert response.status_code == 422


def test_a_single_member_at_100_percent_is_valid(client):
    response = client.put("/household-members", json={"members": [
        {"name": "Anh", "percentage": "1.0000", "settlement_patterns": ["online transfer from chk"]},
    ]})
    assert response.status_code == 200
    assert len(response.json()) == 1


# --- effect on the Shared Expenses split -------------------------------

def _create_account(client, is_shared=True):
    response = client.post("/accounts/manual", json={
        "name": "Joint Checking", "institution": "Chase", "account_type": "depository", "is_shared": is_shared,
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_updated_split_percentages_are_reflected_in_the_overview(client):
    account_id = _create_account(client)
    client.post("/transactions/manual", json={
        "account_id": account_id, "name": "Costco", "amount": "100.00",
        "transaction_date": "2026-07-20", "transaction_type": "regular",
    })

    client.put("/household-members", json={"members": [
        {"name": "Anh", "percentage": "0.5000", "settlement_patterns": []},
        {"name": "Michelle", "percentage": "0.5000", "settlement_patterns": []},
    ]})

    body = client.get("/shared-expenses/overview", params={"year": 2026, "month": 8}).json()
    shares = {s["name"]: s for s in body["shares"]}
    assert shares["Anh"]["amount_owed"] == "50.00"
    assert shares["Michelle"]["amount_owed"] == "50.00"


def test_last_member_by_order_absorbs_the_rounding_remainder(client):
    account_id = _create_account(client)
    client.post("/transactions/manual", json={
        "account_id": account_id, "name": "Costco", "amount": "100.01",
        "transaction_date": "2026-07-20", "transaction_type": "regular",
    })

    # Michelle listed last -- she should absorb the remainder, same as
    # before this was configurable.
    client.put("/household-members", json={"members": [
        {"name": "Anh", "percentage": "0.7000", "settlement_patterns": []},
        {"name": "Michelle", "percentage": "0.3000", "settlement_patterns": []},
    ]})

    body = client.get("/shared-expenses/overview", params={"year": 2026, "month": 8}).json()
    shares = {s["name"]: Decimal(s["amount_owed"]) for s in body["shares"]}
    assert shares["Anh"] + shares["Michelle"] == Decimal("100.01")
    assert shares["Anh"] == Decimal("70.01")
    assert shares["Michelle"] == Decimal("30.00")


def test_a_new_members_settlement_pattern_is_picked_up(client):
    account_id = _create_account(client)
    client.post("/transactions/manual", json={
        "account_id": account_id, "name": "Costco", "amount": "100.00",
        "transaction_date": "2026-07-20", "transaction_type": "regular",
    })
    client.put("/household-members", json={"members": [
        {"name": "Anh", "percentage": "0.6000", "settlement_patterns": ["online transfer from chk"]},
        {"name": "Roommate", "percentage": "0.4000", "settlement_patterns": ["venmo"]},
    ]})
    client.post("/transactions/manual", json={
        "account_id": account_id, "name": "Venmo from Roommate", "amount": "-40.00",
        "transaction_date": "2026-08-01", "transaction_type": "transfer",
    })

    body = client.get("/shared-expenses/overview", params={"year": 2026, "month": 8}).json()
    shares = {s["name"]: s for s in body["shares"]}
    assert shares["Roommate"]["is_paid"] is True
