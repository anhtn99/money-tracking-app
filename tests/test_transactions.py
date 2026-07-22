import datetime
import uuid

import pytest

from app.database import SessionLocal
from app.models.account import Account, AccountType, AccountStatus
from app.models.transaction import Transaction, TransactionType
from app.services import transaction_sync


def _create_account(client, account_type="depository", name="Joint Checking") -> str:
    response = client.post(
        "/accounts/manual",
        json={"name": name, "institution": "Chase", "account_type": account_type},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_linked_account(item_id: str, plaid_account_id: str, account_type: AccountType, secret_ref: str) -> Account:
    """Bypasses the API -- there's no manual-CRUD endpoint for Plaid-linked
    accounts (they're created via /accounts/plaid/exchange), so tests that
    need one insert directly."""
    db = SessionLocal()
    account = Account(
        name=plaid_account_id,
        institution="Chase",
        account_type=account_type,
        status=AccountStatus.active,
        is_manual=False,
        plaid_item_id=item_id,
        plaid_account_id=plaid_account_id,
        plaid_access_token_ref=secret_ref,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    db.close()
    return account


# ── Manual CRUD ──────────────────────────────────────────────────────────

def test_create_and_get_manual_transaction(client):
    account_id = _create_account(client)
    response = client.post(
        "/transactions/manual",
        json={
            "account_id": account_id,
            "name": "Coffee",
            "amount": "4.50",
            "transaction_date": "2026-07-15",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Coffee"
    assert body["is_manual"] is True
    assert body["transaction_type"] == "regular"

    get_response = client.get(f"/transactions/{body['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Coffee"


def test_create_manual_transaction_unknown_account_404s(client):
    response = client.post(
        "/transactions/manual",
        json={
            "account_id": str(uuid.uuid4()),
            "name": "Coffee",
            "amount": "4.50",
            "transaction_date": "2026-07-15",
        },
    )
    assert response.status_code == 404


def test_list_transactions_filters_by_account(client):
    account_a = _create_account(client, name="Checking A")
    account_b = _create_account(client, name="Checking B")
    client.post("/transactions/manual", json={
        "account_id": account_a, "name": "A txn", "amount": "10.00", "transaction_date": "2026-07-01",
    })
    client.post("/transactions/manual", json={
        "account_id": account_b, "name": "B txn", "amount": "20.00", "transaction_date": "2026-07-02",
    })

    response = client.get("/transactions", params={"account_id": account_a})
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["name"] == "A txn"


def test_update_manual_transaction(client):
    account_id = _create_account(client)
    created = client.post("/transactions/manual", json={
        "account_id": account_id, "name": "Coffee", "amount": "4.50", "transaction_date": "2026-07-15",
    }).json()

    response = client.patch(f"/transactions/{created['id']}", json={"name": "Latte", "amount": "5.25"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Latte"
    assert body["amount"] == "5.25"


def test_manual_transaction_account_can_be_moved(client):
    account_a = _create_account(client, name="Checking A")
    account_b = _create_account(client, name="Checking B")
    created = client.post("/transactions/manual", json={
        "account_id": account_a, "name": "Coffee", "amount": "4.50", "transaction_date": "2026-07-15",
    }).json()

    response = client.patch(f"/transactions/{created['id']}", json={"account_id": account_b})
    assert response.status_code == 200
    assert response.json()["account_id"] == account_b


def test_synced_transaction_account_is_immutable(client):
    account_a = _create_linked_account("item-1", "plaid-acc-1", AccountType.depository, "secret-ref-1")
    account_b = _create_account(client, name="Some Other Account")

    db = SessionLocal()
    txn = Transaction(
        account_id=account_a.id,
        name="Synced txn",
        amount=10,
        transaction_date=datetime.date(2026, 7, 15),
        transaction_type=TransactionType.regular,
        is_manual=False,
        plaid_transaction_id="plaid-txn-1",
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    txn_id = str(txn.id)
    db.close()

    # Every other field may still be edited.
    ok_response = client.patch(f"/transactions/{txn_id}", json={"name": "Renamed"})
    assert ok_response.status_code == 200
    assert ok_response.json()["name"] == "Renamed"

    blocked_response = client.patch(f"/transactions/{txn_id}", json={"account_id": account_b})
    assert blocked_response.status_code == 400


def test_delete_transaction(client):
    account_id = _create_account(client)
    created = client.post("/transactions/manual", json={
        "account_id": account_id, "name": "Coffee", "amount": "4.50", "transaction_date": "2026-07-15",
    }).json()

    response = client.delete(f"/transactions/{created['id']}")
    assert response.status_code == 204
    assert client.get(f"/transactions/{created['id']}").status_code == 404


# ── Presentation logic (green amount / [R][T][I] indicator) ─────────────

@pytest.mark.parametrize(
    "account_type,transaction_type,amount,is_recurring,expected_green,expected_indicator",
    [
        # Income is always green, indicator [I]
        ("depository", "income", "-2000.00", False, True, "I"),
        # Transfer IN (negative = money in) to a depository account is green, [T]
        ("depository", "transfer", "-500.00", False, True, "T"),
        # Transfer OUT (positive = money out) of a depository account is not green
        ("depository", "transfer", "500.00", False, False, "T"),
        # Negative balance (refund) on a credit card is green, regardless of type
        ("credit_card", "regular", "-25.00", False, True, None),
        # A normal charge on a credit card is not green
        ("credit_card", "regular", "25.00", False, False, None),
        # A regular expense from a depository account is not green
        ("depository", "regular", "25.00", False, False, None),
        # Recurring takes priority over the type-based indicator
        ("depository", "income", "-2000.00", True, True, "R"),
    ],
)
def test_amount_presentation(
    client, account_type, transaction_type, amount, is_recurring, expected_green, expected_indicator
):
    account_id = _create_account(client, account_type=account_type)
    response = client.post("/transactions/manual", json={
        "account_id": account_id,
        "name": "Test txn",
        "amount": amount,
        "transaction_date": "2026-07-15",
        "transaction_type": transaction_type,
        "is_recurring": is_recurring,
    })
    assert response.status_code == 201
    body = response.json()
    assert body["is_amount_green"] is expected_green
    assert body["indicator"] == expected_indicator


# ── Plaid sync ────────────────────────────────────────────────────────────

class FakePlaidClient:
    def __init__(self, responses_by_cursor):
        # responses_by_cursor: {cursor_key: [page1, page2, ...]} -- a list
        # of pages to return in order for successive has_more=True calls
        # starting from that cursor.
        self._responses_by_cursor = responses_by_cursor
        self._page_index = {}

    def transactions_sync(self, request):
        cursor_key = getattr(request, "cursor", None)
        pages = self._responses_by_cursor[cursor_key]
        index = self._page_index.get(cursor_key, 0)
        self._page_index[cursor_key] = index + 1
        return pages[index]


class RaisingPlaidClient:
    def transactions_sync(self, request):
        from plaid.exceptions import ApiException
        raise ApiException(status=400, reason="ITEM_LOGIN_REQUIRED")


def _txn(transaction_id, account_id, name, amount, pending=False, category=None, date_=datetime.date(2026, 7, 15)):
    return {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "name": name,
        "merchant_name": None,
        "amount": amount,
        "date": date_,
        "pending": pending,
        "personal_finance_category": {"primary": category} if category else None,
    }


@pytest.fixture
def patch_secrets(monkeypatch):
    monkeypatch.setattr(transaction_sync, "get_plaid_access_token", lambda ref: f"access-token-for-{ref}")


def test_sync_classifies_and_creates_transactions(client, monkeypatch, patch_secrets):
    account = _create_linked_account("item-1", "plaid-acc-1", AccountType.depository, "secret-ref-1")

    page = {
        "added": [
            _txn("t-income", "plaid-acc-1", "Payroll", -2000.00, category="INCOME"),
            _txn("t-transfer", "plaid-acc-1", "Card autopay", 500.00, category="LOAN_PAYMENTS"),
            _txn("t-regular", "plaid-acc-1", "Groceries", 45.00, pending=True),
        ],
        "modified": [],
        "removed": [],
        "has_more": False,
        "next_cursor": "cursor-1",
    }
    fake_client = FakePlaidClient({None: [page]})
    monkeypatch.setattr(transaction_sync, "get_plaid_client", lambda: fake_client)

    response = client.post("/transactions/sync")
    assert response.status_code == 200
    result = response.json()
    assert result["added"] == 3
    assert result["modified"] == 0
    assert result["removed"] == 0
    assert result["needs_reverification"] == []

    db = SessionLocal()
    by_plaid_id = {t.plaid_transaction_id: t for t in db.query(Transaction).all()}
    assert by_plaid_id["t-income"].transaction_type == TransactionType.income
    assert by_plaid_id["t-transfer"].transaction_type == TransactionType.transfer
    assert by_plaid_id["t-regular"].transaction_type == TransactionType.regular
    assert by_plaid_id["t-regular"].is_pending is True
    assert db.get(Account, account.id).plaid_sync_cursor == "cursor-1"
    db.close()


def test_sync_is_idempotent_on_dedup_and_applies_modified_and_removed(client, monkeypatch, patch_secrets):
    account = _create_linked_account("item-2", "plaid-acc-2", AccountType.depository, "secret-ref-2")

    first_page = {
        "added": [_txn("t-1", "plaid-acc-2", "Groceries", 45.00, pending=True)],
        "modified": [],
        "removed": [],
        "has_more": False,
        "next_cursor": "cursor-1",
    }
    second_page = {
        "added": [],
        "modified": [_txn("t-1", "plaid-acc-2", "Groceries", 47.50, pending=False)],
        "removed": [],
        "has_more": False,
        "next_cursor": "cursor-2",
    }
    third_page = {
        "added": [],
        "modified": [],
        "removed": [{"transaction_id": "t-1", "account_id": "plaid-acc-2"}],
        "has_more": False,
        "next_cursor": "cursor-3",
    }
    fake_client = FakePlaidClient({None: [first_page], "cursor-1": [second_page], "cursor-2": [third_page]})
    monkeypatch.setattr(transaction_sync, "get_plaid_client", lambda: fake_client)

    first = client.post("/transactions/sync").json()
    assert first["added"] == 1

    second = client.post("/transactions/sync").json()
    assert second["added"] == 0
    assert second["modified"] == 1
    db = SessionLocal()
    txn = db.query(Transaction).filter_by(plaid_transaction_id="t-1").one()
    assert txn.amount == 47.50
    assert txn.is_pending is False
    db.close()

    third = client.post("/transactions/sync").json()
    assert third["removed"] == 1
    db = SessionLocal()
    assert db.query(Transaction).filter_by(plaid_transaction_id="t-1").first() is None
    db.close()


def test_sync_shares_cursor_across_accounts_on_same_item(client, monkeypatch, patch_secrets):
    account_1 = _create_linked_account("item-3", "plaid-acc-3a", AccountType.depository, "secret-ref-3")
    account_2 = _create_linked_account("item-3", "plaid-acc-3b", AccountType.credit_card, "secret-ref-3")

    page = {
        "added": [_txn("t-a", "plaid-acc-3a", "Groceries", 10.00)],
        "modified": [], "removed": [], "has_more": False, "next_cursor": "shared-cursor",
    }
    fake_client = FakePlaidClient({None: [page]})
    monkeypatch.setattr(transaction_sync, "get_plaid_client", lambda: fake_client)

    client.post("/transactions/sync")

    db = SessionLocal()
    assert db.get(Account, account_1.id).plaid_sync_cursor == "shared-cursor"
    assert db.get(Account, account_2.id).plaid_sync_cursor == "shared-cursor"
    db.close()


def test_sync_marks_account_needs_reverification_on_plaid_error(client, monkeypatch, patch_secrets):
    account = _create_linked_account("item-4", "plaid-acc-4", AccountType.depository, "secret-ref-4")
    monkeypatch.setattr(transaction_sync, "get_plaid_client", lambda: RaisingPlaidClient())

    response = client.post("/transactions/sync")
    assert response.status_code == 200
    result = response.json()
    assert str(account.id) in result["needs_reverification"]

    db = SessionLocal()
    assert db.get(Account, account.id).status == AccountStatus.needs_reverification
    db.close()
