"""
Request/response models for the Transactions API. Same pattern as
app/schemas/account.py.
"""
import uuid
from decimal import Decimal
from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict

from app.models.transaction import Transaction, TransactionType
from app.services import transaction_presentation


class TransactionBase(BaseModel):
    name: str
    amount: Decimal  # Plaid convention: positive = money out, negative = money in
    transaction_date: date
    transaction_type: TransactionType = TransactionType.regular
    category_id: Optional[uuid.UUID] = None
    is_recurring: bool = False
    recurring_rule_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None


class ManualTransactionCreate(TransactionBase):
    account_id: uuid.UUID


class TransactionUpdate(BaseModel):
    """All fields optional -- callers only send what they want to change.
    account_id IS included here (manual transactions may move accounts),
    but the router rejects it for synced transactions -- see the
    "Synced Transaction Restriction" in the spec: every field but the
    account may be edited on a synced transaction."""
    name: Optional[str] = None
    amount: Optional[Decimal] = None
    transaction_date: Optional[date] = None
    transaction_type: Optional[TransactionType] = None
    category_id: Optional[uuid.UUID] = None
    is_recurring: Optional[bool] = None
    recurring_rule_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    account_id: Optional[uuid.UUID] = None


class TransactionResponse(TransactionBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    is_manual: bool
    is_pending: bool
    plaid_transaction_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Presentation logic (app/services/transaction_presentation.py) --
    # not stored columns, computed per-request from type + sign + the
    # linked account's type.
    is_amount_green: bool
    indicator: Optional[str] = None

    @classmethod
    def from_transaction(cls, transaction: Transaction) -> "TransactionResponse":
        """Builds the response explicitly rather than relying purely on
        from_attributes, since is_amount_green/indicator aren't columns
        on the ORM object -- both need the linked Account too."""
        return cls(
            **{
                field: getattr(transaction, field)
                for field in TransactionBase.model_fields
            },
            id=transaction.id,
            account_id=transaction.account_id,
            is_manual=transaction.is_manual,
            is_pending=transaction.is_pending,
            plaid_transaction_id=transaction.plaid_transaction_id,
            created_at=transaction.created_at,
            updated_at=transaction.updated_at,
            is_amount_green=transaction_presentation.is_amount_green(transaction, transaction.account),
            indicator=transaction_presentation.indicator(transaction),
        )


class SyncResult(BaseModel):
    added: int
    modified: int
    removed: int
    needs_reverification: list[uuid.UUID]
