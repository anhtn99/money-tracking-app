"""
Transactions tab endpoints:
  - Manual transaction CRUD (add/edit/remove) -- works against any
    account, manual or Plaid-linked (e.g. logging a cash purchase before
    it posts, or the day-to-day CRUD on a manual-only account).
  - POST /transactions/sync -- pulls new transactions from every active
    Plaid-linked account (app/services/transaction_sync.py). Runs on
    demand for now; wiring this to a schedule is a deploy-time concern
    (Phase 6), same as how the existing plaid-sheets-sync Lambda runs on
    EventBridge Scheduler today.

Synced-transaction restriction from the spec: every field may be edited
except the associated account -- enforced below in update_transaction().
"""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.account import Account
from app.models.transaction import Transaction, TransactionType
from app.schemas.transaction import ManualTransactionCreate, TransactionUpdate, TransactionResponse, SyncResult
from app.services.transaction_sync import sync_all_accounts

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _get_transaction_or_404(transaction_id: uuid.UUID, db: Session) -> Transaction:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction


def _get_account_or_404(account_id: uuid.UUID, db: Session) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.post("/manual", response_model=TransactionResponse, status_code=201)
def create_manual_transaction(payload: ManualTransactionCreate, db: Session = Depends(get_db)):
    _get_account_or_404(payload.account_id, db)
    transaction = Transaction(
        account_id=payload.account_id,
        name=payload.name,
        amount=payload.amount,
        transaction_date=payload.transaction_date,
        transaction_type=payload.transaction_type,
        category_id=payload.category_id,
        is_recurring=payload.is_recurring,
        recurring_rule_id=payload.recurring_rule_id,
        notes=payload.notes,
        is_manual=True,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return TransactionResponse.from_transaction(transaction)


@router.get("", response_model=list[TransactionResponse])
def list_transactions(
    account_id: Optional[uuid.UUID] = None,
    transaction_type: Optional[TransactionType] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Transaction)
    if account_id is not None:
        query = query.filter(Transaction.account_id == account_id)
    if transaction_type is not None:
        query = query.filter(Transaction.transaction_type == transaction_type)
    if start_date is not None:
        query = query.filter(Transaction.transaction_date >= start_date)
    if end_date is not None:
        query = query.filter(Transaction.transaction_date <= end_date)
    transactions = query.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).all()
    return [TransactionResponse.from_transaction(t) for t in transactions]


@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction(transaction_id: uuid.UUID, db: Session = Depends(get_db)):
    transaction = _get_transaction_or_404(transaction_id, db)
    return TransactionResponse.from_transaction(transaction)


@router.patch("/{transaction_id}", response_model=TransactionResponse)
def update_transaction(transaction_id: uuid.UUID, payload: TransactionUpdate, db: Session = Depends(get_db)):
    transaction = _get_transaction_or_404(transaction_id, db)
    updates = payload.model_dump(exclude_unset=True)

    if "account_id" in updates:
        if not transaction.is_manual and updates["account_id"] != transaction.account_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot change the account on a synced transaction",
            )
        _get_account_or_404(updates["account_id"], db)

    for field, value in updates.items():
        setattr(transaction, field, value)
    db.commit()
    db.refresh(transaction)
    return TransactionResponse.from_transaction(transaction)


@router.delete("/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: uuid.UUID, db: Session = Depends(get_db)):
    transaction = _get_transaction_or_404(transaction_id, db)
    db.delete(transaction)
    db.commit()


@router.post("/sync", response_model=SyncResult)
def sync_transactions(db: Session = Depends(get_db)):
    return sync_all_accounts(db)
