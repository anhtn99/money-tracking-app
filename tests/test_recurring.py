import uuid


def _create_account(client, account_type="depository", name="Joint Checking") -> str:
    response = client.post(
        "/accounts/manual",
        json={"name": name, "institution": "Chase", "account_type": account_type},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _rule_payload(**overrides):
    payload = {
        "name": "Chicago Rent",
        "icon": "🏠",
        "frequency": "monthly",
        "name_match_type": "partial",
        "name_pattern": "GOLD PROPERTIES",
        "amount_min": "1750.00",
        "amount_max": "1750.00",
        "expected_day_of_period": 1,
    }
    payload.update(overrides)
    return payload


def _create_rule(client, **overrides):
    response = client.post("/recurring", json=_rule_payload(**overrides))
    assert response.status_code == 201
    return response.json()


def _create_manual_transaction(client, account_id, **overrides):
    payload = {
        "account_id": account_id,
        "name": "Zelle payment to GOLD PROPERTIES LLC",
        "amount": "1750.00",
        "transaction_date": "2026-07-01",
    }
    payload.update(overrides)
    response = client.post("/transactions/manual", json=payload)
    assert response.status_code == 201
    return response.json()


# ── CRUD ─────────────────────────────────────────────────────────────────

def test_create_and_get_recurring_rule(client):
    created = _create_rule(client)
    response = client.get(f"/recurring/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Chicago Rent"
    assert response.json()["is_shared"] is False


def test_list_recurring_rules(client):
    _create_rule(client, name="Chicago Rent")
    _create_rule(client, name="Gym Membership", name_pattern="ACTIVE N FIT", amount_min="30.00", amount_max="30.00")
    response = client.get("/recurring")
    assert response.status_code == 200
    assert {r["name"] for r in response.json()} == {"Chicago Rent", "Gym Membership"}


def test_get_recurring_rule_404(client):
    response = client.get(f"/recurring/{uuid.uuid4()}")
    assert response.status_code == 404


def test_update_recurring_rule(client):
    created = _create_rule(client)
    response = client.patch(f"/recurring/{created['id']}", json={"is_shared": True})
    assert response.status_code == 200
    assert response.json()["is_shared"] is True


# ── Matching ─────────────────────────────────────────────────────────────

def test_manual_transaction_auto_matches_existing_rule(client):
    account_id = _create_account(client)
    rule = _create_rule(client)

    txn = _create_manual_transaction(client, account_id)
    assert txn["recurring_rule_id"] == rule["id"]
    assert txn["is_recurring"] is True
    assert txn["display_name"] == "Chicago Rent"
    assert txn["name"] == "Zelle payment to GOLD PROPERTIES LLC"


def test_manual_transaction_outside_amount_range_does_not_match(client):
    account_id = _create_account(client)
    _create_rule(client)

    txn = _create_manual_transaction(client, account_id, amount="1800.00")
    assert txn["recurring_rule_id"] is None
    assert txn["is_recurring"] is False
    assert txn["display_name"] == txn["name"]


def test_creating_rule_retroactively_matches_existing_transactions(client):
    account_id = _create_account(client)
    # Transaction exists BEFORE the rule does.
    txn = _create_manual_transaction(client, account_id)
    assert txn["recurring_rule_id"] is None

    rule = _create_rule(client)

    response = client.get(f"/transactions/{txn['id']}")
    body = response.json()
    assert body["recurring_rule_id"] == rule["id"]
    assert body["display_name"] == "Chicago Rent"
    assert body["is_recurring"] is True


def test_create_always_retroactively_matches_existing_transactions(client):
    """Unlike update, create has no apply_to_existing choice -- it always
    matches existing unmatched transactions, same as Copilot's own
    creation flow."""
    account_id = _create_account(client)
    # Transaction exists BEFORE the rule does.
    txn = _create_manual_transaction(client, account_id)
    assert txn["recurring_rule_id"] is None

    rule = _create_rule(client)

    matched = client.get(f"/transactions/{txn['id']}").json()
    assert matched["recurring_rule_id"] == rule["id"]
    assert matched["display_name"] == "Chicago Rent"


def test_update_with_apply_to_existing_false_only_affects_future_transactions(client):
    account_id = _create_account(client)
    rule = _create_rule(client)
    # Doesn't match the rule's current amount range, so it stays unmatched.
    txn = _create_manual_transaction(client, account_id, amount="1800.00")
    assert txn["recurring_rule_id"] is None

    # Widen the amount range so this transaction WOULD now match, but say
    # "only future payments."
    client.patch(f"/recurring/{rule['id']}", json={"amount_max": "1800.00", "apply_to_existing": False})

    still_unmatched = client.get(f"/transactions/{txn['id']}").json()
    assert still_unmatched["recurring_rule_id"] is None

    future_txn = _create_manual_transaction(client, account_id, amount="1800.00", transaction_date="2026-08-01")
    assert future_txn["recurring_rule_id"] == rule["id"]


def test_update_without_matching_field_change_skips_rescan(client, monkeypatch):
    """Toggling something unrelated (is_shared) shouldn't trigger the
    full-table rescan at all -- only a matching-relevant field change
    should. Patched at the point of use (app.routers.recurring), same as
    the transaction_sync tests patch get_plaid_client there rather than
    on the underlying module."""
    from app.routers import recurring as recurring_router

    rule = _create_rule(client)
    calls = []
    monkeypatch.setattr(
        recurring_router, "rematch_existing_transactions",
        lambda db, r: calls.append(r.id),
    )

    response = client.patch(f"/recurring/{rule['id']}", json={"is_shared": True})
    assert response.status_code == 200
    assert calls == []

    client.patch(f"/recurring/{rule['id']}", json={"amount_max": "2000.00"})
    assert [str(c) for c in calls] == [rule["id"]]


def test_renaming_rule_propagates_to_linked_transactions(client):
    account_id = _create_account(client)
    rule = _create_rule(client)
    txn = _create_manual_transaction(client, account_id)
    assert txn["display_name"] == "Chicago Rent"

    client.patch(f"/recurring/{rule['id']}", json={"name": "Apartment Rent"})

    response = client.get(f"/transactions/{txn['id']}")
    assert response.json()["display_name"] == "Apartment Rent"
    assert response.json()["name"] == "Zelle payment to GOLD PROPERTIES LLC"


def test_deleting_rule_unlinks_and_resets_display_name(client):
    account_id = _create_account(client)
    rule = _create_rule(client)
    txn = _create_manual_transaction(client, account_id)
    assert txn["is_recurring"] is True

    response = client.delete(f"/recurring/{rule['id']}")
    assert response.status_code == 204

    updated = client.get(f"/transactions/{txn['id']}").json()
    assert updated["recurring_rule_id"] is None
    assert updated["is_recurring"] is False
    assert updated["display_name"] == updated["name"] == "Zelle payment to GOLD PROPERTIES LLC"

    assert client.get(f"/recurring/{rule['id']}").status_code == 404


def test_manually_linking_and_unlinking_via_transaction_patch(client):
    account_id = _create_account(client)
    rule = _create_rule(client)
    # A transaction that doesn't match the rule's amount, so it stays unmatched.
    txn = _create_manual_transaction(client, account_id, amount="1800.00")
    assert txn["recurring_rule_id"] is None

    linked = client.patch(f"/transactions/{txn['id']}", json={"recurring_rule_id": rule["id"]})
    assert linked.status_code == 200
    assert linked.json()["display_name"] == "Chicago Rent"
    assert linked.json()["is_recurring"] is True

    unlinked = client.patch(f"/transactions/{txn['id']}", json={"recurring_rule_id": None})
    assert unlinked.status_code == 200
    assert unlinked.json()["display_name"] == "Zelle payment to GOLD PROPERTIES LLC"
    assert unlinked.json()["is_recurring"] is False


def test_patch_recurring_rule_id_404(client):
    account_id = _create_account(client)
    txn = _create_manual_transaction(client, account_id, amount="1800.00")
    response = client.patch(f"/transactions/{txn['id']}", json={"recurring_rule_id": str(uuid.uuid4())})
    assert response.status_code == 404
