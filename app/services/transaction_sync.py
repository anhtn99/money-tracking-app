"""
Plaid transactions/sync logic for the Transactions tab. Same cursor-based
approach as plaid-sheets-sync's sync_transactions.py (see that project's
household-expenses repo for the original pattern this borrows from),
adapted to write into Postgres via SQLAlchemy instead of a Google Sheet.

One deliberate difference from that pipeline: this app tracks everything
Plaid returns rather than excluding whole categories (transfers, loan
payments, etc.) -- that's the point of a real transaction ledger with its
own transfer/income/regular types, instead of a sheet meant to total up
"real" household expenses only.
"""
import uuid
from collections import defaultdict
from typing import Optional

from plaid.exceptions import ApiException
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from sqlalchemy.orm import Session

from app.core.plaid_client import get_plaid_client
from app.core.secrets import get_plaid_access_token
from app.models.account import Account, AccountStatus
from app.models.transaction import Transaction, TransactionType
from app.schemas.transaction import SyncResult

# Plaid's personal_finance_category.primary values that represent money
# moving between the household's own accounts rather than a real
# income/expense event -- LOAN_PAYMENTS covers credit card autopay from
# checking, same reasoning as the household's existing sync pipelines
# (see claude-context/project-overview.md for the full household context).
TRANSFER_PRIMARY_CATEGORIES = {"TRANSFER_IN", "TRANSFER_OUT", "LOAN_PAYMENTS"}
INCOME_PRIMARY_CATEGORIES = {"INCOME"}


def _classify_type(txn) -> TransactionType:
    pfc = txn.get("personal_finance_category")
    primary = pfc["primary"] if pfc else None
    if primary in TRANSFER_PRIMARY_CATEGORIES:
        return TransactionType.transfer
    if primary in INCOME_PRIMARY_CATEGORIES:
        return TransactionType.income
    return TransactionType.regular


def _fetch_all(client, access_token: str, cursor: Optional[str]):
    """Pages through transactions_sync until has_more is False. The SDK
    rejects cursor=None outright (a known gotcha, see
    plaid-sheets-sync/sync_transactions.py) -- omit the kwarg entirely on
    the first sync, when there's no cursor yet."""
    added, modified, removed = [], [], []
    has_more = True
    while has_more:
        kwargs = {"access_token": access_token}
        if cursor is not None:
            kwargs["cursor"] = cursor
        response = client.transactions_sync(TransactionsSyncRequest(**kwargs))
        added.extend(response["added"])
        modified.extend(response["modified"])
        removed.extend(r["transaction_id"] for r in response["removed"])
        has_more = response["has_more"]
        cursor = response["next_cursor"]
    return added, modified, removed, cursor


def sync_all_accounts(db: Session) -> SyncResult:
    """Syncs every active, Plaid-linked account. Grouped by plaid_item_id
    since transactions_sync is per-Item (one access token can back
    multiple accounts, e.g. checking + savings at the same bank) -- see
    the design note on Account.plaid_sync_cursor."""
    client = get_plaid_client()

    linked_accounts = (
        db.query(Account)
        .filter(
            Account.is_manual.is_(False),
            Account.plaid_access_token_ref.isnot(None),
            Account.status == AccountStatus.active,
        )
        .all()
    )
    by_item: dict[str, list[Account]] = defaultdict(list)
    for account in linked_accounts:
        by_item[account.plaid_item_id].append(account)

    added_count = modified_count = removed_count = 0
    needs_reverification: list[uuid.UUID] = []

    for accounts in by_item.values():
        account_by_plaid_id = {a.plaid_account_id: a for a in accounts}
        # Every account sharing an item was linked from the same
        # /plaid/exchange call, so they all carry the same access token
        # ref and (once synced at least once) the same cursor -- any one
        # is representative of the whole item.
        representative = accounts[0]
        access_token = get_plaid_access_token(representative.plaid_access_token_ref)
        cursor = representative.plaid_sync_cursor

        try:
            added, modified, removed_ids, new_cursor = _fetch_all(client, access_token, cursor)
        except ApiException:
            # Most commonly ITEM_LOGIN_REQUIRED -- the credential needs
            # the "Reverify" flow (app/routers/accounts.py). Don't let one
            # broken connection abort syncing every other account.
            for account in accounts:
                account.status = AccountStatus.needs_reverification
            db.commit()
            needs_reverification.append(representative.id)
            continue

        relevant_ids = [t["transaction_id"] for t in added + modified] + removed_ids
        existing_by_plaid_id = {
            t.plaid_transaction_id: t
            for t in db.query(Transaction)
            .filter(Transaction.plaid_transaction_id.in_(relevant_ids))
            .all()
        }

        for txn in added:
            if txn["transaction_id"] in existing_by_plaid_id:
                continue  # dedup safety net -- already present (e.g. a retried sync)
            account = account_by_plaid_id.get(txn["account_id"])
            if account is None:
                continue  # belongs to an account we're not tracking (e.g. removed after linking)
            db.add(Transaction(
                account_id=account.id,
                name=txn["merchant_name"] or txn["name"],
                amount=txn["amount"],
                transaction_date=txn["date"],
                transaction_type=_classify_type(txn),
                is_manual=False,
                is_pending=txn["pending"],
                plaid_transaction_id=txn["transaction_id"],
            ))
            added_count += 1

        for txn in modified:
            existing = existing_by_plaid_id.get(txn["transaction_id"])
            if existing is None:
                continue  # never synced in the first place -- nothing to update
            # Only overwrite Plaid-sourced fields. category_id/notes/
            # is_recurring/recurring_rule_id/transaction_type are left
            # alone once set -- transaction_type in particular may have
            # been manually overridden via the "mark as income/transfer/
            # regular" flow (transaction-type-edit.png reference image),
            # and re-classifying it here on every pending->posted
            # correction would silently undo that override.
            existing.name = txn["merchant_name"] or txn["name"]
            existing.amount = txn["amount"]
            existing.transaction_date = txn["date"]
            existing.is_pending = txn["pending"]
            modified_count += 1

        for tid in removed_ids:
            existing = existing_by_plaid_id.get(tid)
            if existing is not None:
                db.delete(existing)
                removed_count += 1

        # Commit the transaction changes, then the cursor, so the cursor
        # is only ever saved alongside changes that actually landed --
        # mirrors the "commit cursor last" safety rule in the sheet-based
        # pipeline this borrows from.
        db.commit()
        for account in accounts:
            account.plaid_sync_cursor = new_cursor
        db.commit()

    return SyncResult(
        added=added_count,
        modified=modified_count,
        removed=removed_count,
        needs_reverification=needs_reverification,
    )
