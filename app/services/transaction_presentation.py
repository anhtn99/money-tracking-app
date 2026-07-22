"""
"Show this in green" / indicator-marker logic from the Transactions tab
spec. Deliberately kept out of the model (see the design note in
app/models/transaction.py) and out of the database -- both depend on
transaction_type + amount sign + the linked account's type, so they're
computed fresh from those three inputs every time a transaction is
serialized for a response, in app/routers/transactions.py.
"""
from typing import Optional

from app.models.account import Account, AccountType
from app.models.transaction import Transaction, TransactionType


def is_amount_green(transaction: Transaction, account: Account) -> bool:
    """Amount sign convention: positive = money out, negative = money in
    (Plaid's own convention, see app/models/transaction.py)."""
    if transaction.transaction_type == TransactionType.income:
        return True
    if (
        transaction.transaction_type == TransactionType.transfer
        and account.account_type == AccountType.depository
        and transaction.amount < 0
    ):
        return True
    if account.account_type == AccountType.credit_card and transaction.amount < 0:
        return True
    return False


# Single-letter indicator per the spec's table, which lists the four cases
# ([R]/[T]/[I]/none) as mutually exclusive rather than stackable -- so a
# transaction that's both recurring and income (e.g. a paycheck the user
# has also flagged as recurring) shows [R], the more specific/actionable
# fact for a recurring-detection feature that's still being built out.
def indicator(transaction: Transaction) -> Optional[str]:
    if transaction.is_recurring:
        return "R"
    if transaction.transaction_type == TransactionType.transfer:
        return "T"
    if transaction.transaction_type == TransactionType.income:
        return "I"
    return None
