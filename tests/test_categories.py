import uuid

import pytest


def _create_group(client, name="Essential", sort_order="1"):
    response = client.post("/categories/groups", json={"name": name, "sort_order": sort_order})
    assert response.status_code == 201
    return response.json()


def _create_category(client, name="Groceries", color="#4CAF50", icon="🥑", budget=None, group_id=None):
    payload = {"name": name, "color": color, "icon": icon}
    if budget is not None:
        payload["budget"] = budget
    if group_id is not None:
        payload["group_id"] = group_id
    response = client.post("/categories", json=payload)
    assert response.status_code == 201
    return response.json()


def _create_account(client, name="Checking"):
    response = client.post(
        "/accounts/manual",
        json={"name": name, "institution": "Chase", "account_type": "depository"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_transaction(client, account_id, category_id, amount, transaction_date):
    response = client.post("/transactions/manual", json={
        "account_id": account_id,
        "name": "Test txn",
        "amount": amount,
        "transaction_date": transaction_date,
        "category_id": category_id,
    })
    assert response.status_code == 201
    return response.json()


# ── Category group CRUD ──────────────────────────────────────────────────

def test_create_and_list_category_groups(client):
    _create_group(client, name="Essential", sort_order="1")
    _create_group(client, name="Neutral", sort_order="2")

    response = client.get("/categories/groups")
    assert response.status_code == 200
    names = [g["name"] for g in response.json()]
    assert names == ["Essential", "Neutral"]  # ordered by sort_order


def test_update_category_group(client):
    group = _create_group(client)
    response = client.patch(f"/categories/groups/{group['id']}", json={"name": "Renamed"})
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


def test_delete_category_group_ungroups_its_categories(client):
    group = _create_group(client)
    category = _create_category(client, group_id=group["id"])

    response = client.delete(f"/categories/groups/{group['id']}")
    assert response.status_code == 204

    get_category = client.get(f"/categories/{category['id']}")
    assert get_category.status_code == 200
    assert get_category.json()["group_id"] is None

    assert client.get(f"/categories/groups/{group['id']}").status_code == 404


# ── Category CRUD ─────────────────────────────────────────────────────────

def test_create_category_without_group(client):
    category = _create_category(client, name="Misc", budget="50.00")
    assert category["group_id"] is None
    assert category["budget"] == "50.00"


def test_create_category_unknown_group_404s(client):
    response = client.post("/categories", json={
        "name": "Groceries", "color": "#4CAF50", "icon": "🥑", "group_id": str(uuid.uuid4()),
    })
    assert response.status_code == 404


def test_list_categories_filters_by_group(client):
    group_a = _create_group(client, name="A")
    group_b = _create_group(client, name="B")
    _create_category(client, name="In A", group_id=group_a["id"])
    _create_category(client, name="In B", group_id=group_b["id"])

    response = client.get("/categories", params={"group_id": group_a["id"]})
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["name"] == "In A"


def test_update_category(client):
    category = _create_category(client)
    response = client.patch(f"/categories/{category['id']}", json={"budget": "100.00"})
    assert response.status_code == 200
    assert response.json()["budget"] == "100.00"


def test_delete_category_without_transactions_succeeds(client):
    category = _create_category(client)
    response = client.delete(f"/categories/{category['id']}")
    assert response.status_code == 204
    assert client.get(f"/categories/{category['id']}").status_code == 404


def test_delete_category_reassigns_its_transactions_to_other(client):
    category = _create_category(client)
    account_id = _create_account(client)
    txn = _create_transaction(client, account_id, category["id"], "10.00", "2026-07-15")

    response = client.delete(f"/categories/{category['id']}")
    assert response.status_code == 204
    assert client.get(f"/categories/{category['id']}").status_code == 404

    other = next(c for c in client.get("/categories").json() if c["is_default"])
    updated_txn = client.get(f"/transactions/{txn['id']}").json()
    assert updated_txn["category_id"] == other["id"]


def test_cannot_delete_the_default_category(client):
    other = next(c for c in client.get("/categories").json() if c["is_default"])
    response = client.delete(f"/categories/{other['id']}")
    assert response.status_code == 400
    assert client.get(f"/categories/{other['id']}").status_code == 200


# ── Overview aggregation ──────────────────────────────────────────────────

def test_overview_aggregates_spend_and_budget_status(client):
    account_id = _create_account(client)

    essential = _create_group(client, name="Essential", sort_order="1")
    rent = _create_category(client, name="Rent", budget="2000.00", group_id=essential["id"])
    utilities = _create_category(client, name="Utilities", budget="250.00", group_id=essential["id"])
    # No budget set -- should have status=None and not count toward the group's budget total
    fees = _create_category(client, name="Credit Card Fee", group_id=essential["id"])

    misc = _create_category(client, name="Misc", budget="50.00")  # ungrouped

    # In-month transactions
    _create_transaction(client, account_id, rent["id"], "2000.00", "2026-07-01")   # exactly at budget
    _create_transaction(client, account_id, utilities["id"], "230.00", "2026-07-05")  # 92% -- "near"
    _create_transaction(client, account_id, misc["id"], "75.00", "2026-07-10")  # over budget

    # Out-of-month transaction -- must be excluded from the July rollup
    _create_transaction(client, account_id, rent["id"], "500.00", "2026-06-15")

    response = client.get("/categories/overview", params={"year": 2026, "month": 7})
    assert response.status_code == 200
    body = response.json()

    assert body["year"] == 2026
    assert body["month"] == 7

    group = body["groups"][0]
    assert group["name"] == "Essential"
    by_name = {c["name"]: c for c in group["categories"]}

    assert by_name["Rent"]["spent"] == "2000.00"
    assert by_name["Rent"]["status"] == "under"  # exactly at budget, not over

    assert by_name["Utilities"]["spent"] == "230.00"
    assert by_name["Utilities"]["status"] == "near"

    assert by_name["Credit Card Fee"]["spent"] == "0"
    assert by_name["Credit Card Fee"]["budget"] is None
    assert by_name["Credit Card Fee"]["status"] is None

    # Credit Card Fee has no budget, so "Essential" isn't fully budgeted --
    # no meaningful group budget/status, just the plain total spend.
    assert group["budget"] is None
    assert group["status"] is None
    assert group["spent"] == "2230.00"  # 2000 + 230 + 0, every category counts now

    ungrouped_by_name = {c["name"]: c for c in body["ungrouped"]}
    assert ungrouped_by_name["Misc"]["spent"] == "75.00"
    assert ungrouped_by_name["Misc"]["status"] == "over"

    # total spent = 2000 + 230 + 0 + 75 = 2305 (June's 500 excluded)
    assert body["total_spent"] == "2305.00"
    # total budget = 2000 + 250 + 50 = 2300
    assert body["total_budget"] == "2300.00"


def test_unbudgeted_category_spend_excluded_from_totals_but_still_shown(client):
    """No budget = excluded from every aggregate (group + grand total),
    even though real spend happened -- but still listed in the response,
    matching the reference screenshot's "Credit Card Fee" row."""
    account_id = _create_account(client)
    group = _create_group(client, name="Essential")
    budgeted = _create_category(client, name="Rent", budget="1000.00", group_id=group["id"])
    unbudgeted = _create_category(client, name="Credit Card Fee", group_id=group["id"])

    _create_transaction(client, account_id, budgeted["id"], "1000.00", "2026-07-01")
    _create_transaction(client, account_id, unbudgeted["id"], "35.00", "2026-07-02")

    response = client.get("/categories/overview", params={"year": 2026, "month": 7})
    body = response.json()

    by_name = {c["name"]: c for c in body["groups"][0]["categories"]}
    assert by_name["Credit Card Fee"]["spent"] == "35.00"  # still shown
    assert by_name["Credit Card Fee"]["budget"] is None
    assert by_name["Credit Card Fee"]["status"] is None

    # The group isn't fully budgeted (Credit Card Fee has no budget), so
    # it shows no budget/status of its own -- just the plain total spend,
    # including the $35 fee.
    assert body["groups"][0]["spent"] == "1035.00"
    assert body["groups"][0]["budget"] is None
    assert body["groups"][0]["status"] is None

    # The grand total is unaffected by group-level "fully budgeted" status
    # -- it's a flat sum over individually-budgeted categories regardless
    # of grouping, so Rent's $1000 still counts; the $35 fee still doesn't.
    assert body["total_spent"] == "1000.00"
    assert body["total_budget"] == "1000.00"
    # all_categories_spent (grand total only, not on groups) includes it
    assert body["all_categories_spent"] == "1035.00"


def test_fully_budgeted_group_shows_a_budget_and_status(client):
    """The counterpart to the above -- when EVERY category in a group has
    a budget, the group gets a real budget/status, not just a spend total."""
    account_id = _create_account(client)
    group = _create_group(client, name="Essential")
    rent = _create_category(client, name="Rent", budget="1000.00", group_id=group["id"])
    internet = _create_category(client, name="Internet", budget="60.00", group_id=group["id"])

    _create_transaction(client, account_id, rent["id"], "1000.00", "2026-07-01")
    _create_transaction(client, account_id, internet["id"], "60.00", "2026-07-03")

    response = client.get("/categories/overview", params={"year": 2026, "month": 7})
    body = response.json()

    group_body = body["groups"][0]
    assert group_body["spent"] == "1060.00"
    assert group_body["budget"] == "1060.00"
    assert group_body["status"] == "under"  # exactly at budget


def test_empty_group_has_no_budget(client):
    """An empty group must not be treated as vacuously "fully budgeted"
    (Python's all([]) is True) -- there's nothing to budget for."""
    group = _create_group(client, name="Empty Group")

    response = client.get("/categories/overview")
    body = response.json()

    group_body = next(g for g in body["groups"] if g["group_id"] == group["id"])
    assert group_body["spent"] == "0"
    assert group_body["budget"] is None
    assert group_body["status"] is None


def test_recurring_transaction_boosts_effective_budget(client):
    """A category's effective budget = manual budget + that category's
    is_recurring transactions this month -- so a yearly charge landing in
    a given month doesn't make that month look over budget."""
    account_id = _create_account(client)
    subscriptions = _create_category(client, name="Subscriptions", budget="20.00")

    # Regular monthly charge (not recurring-flagged in this test, just normal spend)
    client.post("/transactions/manual", json={
        "account_id": account_id, "name": "Netflix", "amount": "15.00",
        "transaction_date": "2026-07-05", "category_id": subscriptions["id"],
    })
    # The yearly charge, flagged as recurring
    client.post("/transactions/manual", json={
        "account_id": account_id, "name": "Amazon Prime", "amount": "139.00",
        "transaction_date": "2026-07-10", "category_id": subscriptions["id"], "is_recurring": True,
    })

    response = client.get("/categories/overview", params={"year": 2026, "month": 7})
    body = response.json()

    ungrouped_by_name = {c["name"]: c for c in body["ungrouped"]}
    sub = ungrouped_by_name["Subscriptions"]
    assert sub["spent"] == "154.00"  # 15 + 139, all spend counts as normal
    assert sub["budget"] == "159.00"  # 20 manual + 139 recurring boost
    # 154/159 =~ 97%, so "near" rather than "over" -- the key point is it's
    # NOT "over": against the flat $20 budget alone, 154 would have been
    # wildly over (770%), not just near.
    assert sub["status"] == "near"


def test_overview_defaults_to_current_month(client):
    response = client.get("/categories/overview")
    assert response.status_code == 200
    body = response.json()
    import datetime
    today = datetime.date.today()
    assert body["year"] == today.year
    assert body["month"] == today.month
