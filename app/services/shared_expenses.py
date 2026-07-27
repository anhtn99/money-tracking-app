"""
Shared Expenses tab: aggregates one statement cycle's shared
transactions across every Account.is_shared account and splits the total
between household members -- the "what does each person need to transfer
into Joint Checking" number.

The cycle is a credit-card statement period, not a calendar month --
see app/services/billing_cycle.py for the boundary rule.

Inclusion rule for a transaction counting toward the shared total:
    account.is_shared AND (
        transaction_type == "regular"
        OR (is_recurring AND recurring_rule.is_shared)
    )
Everything on a shared account counts by default except transfers/income
(a credit card autopay from Joint Checking, or a stray paycheck landing
there, shouldn't net against the shared total) -- a RecurringRule flagged
is_shared force-includes its matches (rent, insurance, internet) even
when Plaid's own category would otherwise classify them as a transfer.
In practice the Zelle classification fix
(transaction_sync.py::_classify_type) already resolves the most common
case of this (rent paid via Zelle now classifies as `regular`), so the
recurring override mainly matters for non-Zelle recurring bills that
land as a transfer.

The total counts POSTED transactions only. A shared recurring bill that
hasn't hit the account yet is reported separately (`recurring`, with
is_posted=False) rather than folded into the total as a projection --
what each person owes should always be backed by real transactions, and
the unposted list is what tells you the cycle isn't finished settling.

Household composition (names, split percentages, settlement patterns) is
a user-editable DB-backed resource (app/models/household_member.py,
app/routers/household_members.py) -- not a hardcoded constant, since
percentages change and roommates come and go. `display_order` decides
who absorbs the rounding remainder (the last member, by that order) so
the shares always sum EXACTLY to the total (independently rounding each
percentage can leave the shares a penny short of, or over, the total for
an amount that doesn't divide evenly). Percentages across the whole set
are guaranteed to sum to exactly 1 -- enforced in the router at write
time, not re-validated here.
"""
import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.household_member import HouseholdMember
from app.models.recurring import RecurringRule
from app.models.transaction import Transaction, TransactionType
from app.schemas.shared_expenses import (
    SharedExpenseTransaction,
    SharedRecurringStatus,
    SettlementTransfer,
    PersonShare,
    SharedExpensesOverviewResponse,
)
from app.services.billing_cycle import get_cycle

# The household settles at the end of the cycle and does so within a few
# days -- 5 gives some slack (a weekend, a late Venmo/Zelle) without
# reaching far enough to risk picking up an unrelated transfer from the
# NEXT cycle's own settlement.
SETTLEMENT_WINDOW_DAYS = 5


def _household_members(db: Session) -> list[HouseholdMember]:
    return db.query(HouseholdMember).order_by(HouseholdMember.display_order).all()


def _amount_owed(members: list[HouseholdMember], total: Decimal) -> list[tuple[HouseholdMember, Decimal]]:
    owed = []
    running_total = Decimal("0.00")
    for index, member in enumerate(members):
        is_last = index == len(members) - 1
        if is_last:
            amount = total - running_total  # absorbs any rounding remainder
        else:
            amount = (total * member.percentage).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            running_total += amount
        owed.append((member, amount))
    return owed


def _shared_transactions(db: Session, start: datetime.date, end: datetime.date) -> list[Transaction]:
    return (
        db.query(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .outerjoin(RecurringRule, Transaction.recurring_rule_id == RecurringRule.id)
        .filter(
            Account.is_shared.is_(True),
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
            or_(
                Transaction.transaction_type == TransactionType.regular,
                and_(Transaction.is_recurring.is_(True), RecurringRule.is_shared.is_(True)),
            ),
        )
        .order_by(Transaction.transaction_date, Transaction.created_at)
        .all()
    )


def _recurring_status(db: Session, transactions: list[Transaction]) -> list[SharedRecurringStatus]:
    """Checklist of every shared recurring bill and whether its charge
    has posted inside this cycle. Reads from the already-fetched cycle
    transactions, so "posted" always means "counted in the total above"
    -- the two can never disagree."""
    posted_by_rule: dict = {}
    for transaction in transactions:
        if transaction.recurring_rule_id is not None:
            posted_by_rule.setdefault(transaction.recurring_rule_id, transaction)

    rules = (
        db.query(RecurringRule)
        .filter(RecurringRule.is_shared.is_(True))
        .order_by(RecurringRule.expected_day_of_period, RecurringRule.name)
        .all()
    )

    statuses = []
    for rule in rules:
        posted = posted_by_rule.get(rule.id)
        statuses.append(
            SharedRecurringStatus(
                recurring_rule_id=rule.id,
                name=rule.name,
                icon=rule.icon,
                frequency=rule.frequency,
                amount_min=rule.amount_min,
                amount_max=rule.amount_max,
                expected_amount=rule.amount_min if rule.amount_min == rule.amount_max else None,
                is_posted=posted is not None,
                posted_amount=posted.amount if posted else None,
                posted_date=posted.transaction_date if posted else None,
                transaction_id=posted.id if posted else None,
            )
        )
    return statuses


def _settlement_transfers(db: Session, start: datetime.date, end: datetime.date) -> list[Transaction]:
    """Money moved INTO a shared depository account (joint checking)
    during the settle-up window. Per the sign convention on
    app/models/transaction.py, money in is NEGATIVE."""
    return (
        db.query(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .filter(
            Account.is_shared.is_(True),
            Account.account_type == AccountType.depository,
            Transaction.transaction_type == TransactionType.transfer,
            Transaction.amount < 0,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end + datetime.timedelta(days=SETTLEMENT_WINDOW_DAYS),
        )
        .order_by(Transaction.transaction_date, Transaction.created_at)
        .all()
    )


def _shares(db: Session, total: Decimal, start: datetime.date, end: datetime.date) -> list[PersonShare]:
    transfers = _settlement_transfers(db, start, end)
    members = _household_members(db)

    shares = []
    for member, amount_owed in _amount_owed(members, total):
        # A settle-up is always a single transaction for the exact amount
        # owed -- both the bank's naming convention AND the amount have
        # to match, so an unrelated transfer that happens to reuse the
        # same wording (e.g. a past cycle's leftover transfer) can't be
        # mistaken for this cycle's settlement.
        matched = [
            transfer
            for transfer in transfers
            if -transfer.amount == amount_owed
            and any(
                pattern in (transfer.name or "").lower() or pattern in (transfer.display_name or "").lower()
                for pattern in member.settlement_patterns
            )
        ]
        amount_paid = sum((-transfer.amount for transfer in matched), Decimal("0.00"))
        shares.append(
            PersonShare(
                name=member.name,
                percentage=member.percentage,
                amount_owed=amount_owed,
                amount_paid=amount_paid,
                is_paid=amount_owed > 0 and len(matched) > 0,
                settlement_transfers=[
                    SettlementTransfer(
                        id=transfer.id,
                        display_name=transfer.display_name,
                        amount=-transfer.amount,
                        transaction_date=transfer.transaction_date,
                    )
                    for transfer in matched
                ],
            )
        )
    return shares


def get_shared_expenses_overview(db: Session, year: int, month: int) -> SharedExpensesOverviewResponse:
    start, end = get_cycle(year, month)
    transactions = _shared_transactions(db, start, end)
    total = sum((t.amount for t in transactions), Decimal("0.00"))

    return SharedExpensesOverviewResponse(
        year=year,
        month=month,
        cycle_start=start,
        cycle_end=end,
        total_shared_spend=total,
        shares=_shares(db, total, start, end),
        recurring=_recurring_status(db, transactions),
        transactions=[
            SharedExpenseTransaction(
                id=t.id,
                display_name=t.display_name,
                amount=t.amount,
                transaction_date=t.transaction_date,
                account_id=t.account_id,
                account_name=t.account.name,
                is_recurring=t.is_recurring,
            )
            for t in transactions
        ],
    )
