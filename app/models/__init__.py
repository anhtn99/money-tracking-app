"""
Import every model here so Base.metadata knows about all of them --
required for Alembic's autogenerate to detect the full schema, and
convenient for `from app.models import Account, Transaction, ...`
elsewhere.
"""
from app.models.account import Account, AccountType, AccountStatus
from app.models.category import Category, CategoryGroup
from app.models.recurring import RecurringRule, RecurringFrequency, NameMatchType
from app.models.transaction import Transaction, TransactionType

__all__ = [
    "Account", "AccountType", "AccountStatus",
    "Category", "CategoryGroup",
    "RecurringRule", "RecurringFrequency", "NameMatchType",
    "Transaction", "TransactionType",
]
