"""
Net cash flow for a given month: total income minus total spend, across
ALL transactions regardless of category or budget status -- the
counterpart to app/services/category_overview.py, which is deliberately
narrower (only budgeted categories). This is the broader "how much did
the household actually take in vs. spend" number.

Transfers are excluded from both sides -- they're money moving between
the household's own accounts (see the transfer classification note in
app/services/transaction_sync.py), not real income or a real expense, so
counting them here would double up the same dollar on both sides for no
reason.

Amount sign convention (see app/models/transaction.py): positive = money
out, negative = money in. So income transactions are stored negative --
total_income is negated to read as a normal positive number.
"""
import calendar
import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.transaction import Transaction, TransactionType
from app.schemas.transaction import CashFlowResponse


def get_cash_flow(db: Session, year: int, month: int) -> CashFlowResponse:
    start = datetime.date(year, month, 1)
    end = datetime.date(year, month, calendar.monthrange(year, month)[1])

    rows = (
        db.query(Transaction.transaction_type, Transaction.amount)
        .filter(
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
            Transaction.transaction_type != TransactionType.transfer,
        )
        .all()
    )

    total_income = Decimal(0)
    total_spend = Decimal(0)
    for transaction_type, amount in rows:
        if transaction_type == TransactionType.income:
            total_income += -amount
        else:
            total_spend += amount

    return CashFlowResponse(
        year=year,
        month=month,
        total_income=total_income,
        total_spend=total_spend,
        net_cash_flow=total_income - total_spend,
    )
