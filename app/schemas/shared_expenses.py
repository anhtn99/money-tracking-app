"""
Request/response models for the Shared Expenses API. Same layered
pattern as app/schemas/category.py's overview shapes -- nothing here is a
stored column, all computed per-request in app/services/shared_expenses.py.
"""
import uuid
from decimal import Decimal
from datetime import date
from typing import Optional
from pydantic import BaseModel

from app.models.recurring import RecurringFrequency


class SharedExpenseTransaction(BaseModel):
    id: uuid.UUID
    display_name: str
    amount: Decimal
    transaction_date: date
    account_id: uuid.UUID
    account_name: str
    is_recurring: bool


class SharedRecurringStatus(BaseModel):
    """One shared recurring bill and whether its charge has actually
    landed inside this cycle yet (rent, internet, insurance...)."""
    recurring_rule_id: uuid.UUID
    name: str
    icon: str
    frequency: RecurringFrequency
    amount_min: Decimal
    amount_max: Decimal
    # Set only when the rule's range is a single fixed amount -- a rule
    # with a real range (e.g. a utility bill) has no single expected
    # number until it posts.
    expected_amount: Optional[Decimal]
    is_posted: bool
    posted_amount: Optional[Decimal]
    posted_date: Optional[date]
    transaction_id: Optional[uuid.UUID]


class SettlementTransfer(BaseModel):
    id: uuid.UUID
    display_name: str
    amount: Decimal  # positive = money moved INTO joint checking
    transaction_date: date


class PersonShare(BaseModel):
    name: str
    percentage: Decimal
    amount_owed: Decimal
    amount_paid: Decimal
    is_paid: bool
    settlement_transfers: list[SettlementTransfer]


class SharedExpensesOverviewResponse(BaseModel):
    year: int
    month: int
    cycle_start: date
    cycle_end: date
    total_shared_spend: Decimal
    shares: list[PersonShare]
    recurring: list[SharedRecurringStatus]
    transactions: list[SharedExpenseTransaction]
