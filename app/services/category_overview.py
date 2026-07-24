"""
Spend-vs-budget rollup for the Categories tab overview (categories-tab.png)
-- summing this month's transactions per category and per group. Nothing
here is a stored column; it's computed fresh on every request, same
philosophy as app/services/transaction_presentation.py.

Aggregation is done in Python rather than SQL SUM()/GROUP BY -- this is a
single-household app (hundreds of transactions, not millions), so there's
no real performance reason to push the aggregation into the database, and
it sidesteps any cross-dialect Decimal behavior differences between
Postgres and the SQLite used in tests.

Budget formula: a category's EFFECTIVE budget for a given month is its
manual `budget` PLUS the sum of that category's own `is_recurring`
transactions actually dated in that month -- not a projection from
Recurring Rules (Phase 5), which don't exist yet and (as modeled) have no
category link or anchor date to project from anyway. This is reactive,
not predictive: a category with a flat monthly budget that also happens
to have a yearly subscription charge post in March gets March's budget
bumped by that charge's amount, so that one month doesn't look "over
budget" just because a real, expected, recurring cost landed in it.

A category/group with NO manual budget set is excluded from every
aggregate here (group and grand totals) -- its spend still happened, it
just isn't part of "the budget" this tab is showing. It's still LISTED
in the response (per the reference screenshot, e.g. "Credit Card Fee"),
just with budget=None/status=None and excluded from the sums above it.
Total monthly spend/income regardless of budget status is a different,
broader metric -- see app/services/cash_flow.py.
"""
import calendar
import datetime
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.category import Category, CategoryGroup
from app.models.transaction import Transaction
from app.schemas.category import CategorySpend, CategoryGroupSpend, CategoriesOverviewResponse

# "Near" budget threshold. Not specified in the written spec, and not
# fully pinned down by the reference screenshot either (categories at
# similar spent/budget ratios sometimes rendered a different bar color
# than expected from a single fixed cutoff) -- this is a clear, documented
# judgment call rather than a silently-guessed value.
NEAR_BUDGET_RATIO = Decimal("0.9")


def _status(spent: Decimal, budget: Optional[Decimal]) -> Optional[str]:
    if budget is None:
        return None
    if spent > budget:
        return "over"
    if spent < budget * NEAR_BUDGET_RATIO:
        return "under"
    if spent < budget:
        return "near"
    return "under"  # spent == budget exactly -- still "on track", not a warning


def get_categories_overview(db: Session, year: int, month: int) -> CategoriesOverviewResponse:
    start = datetime.date(year, month, 1)
    end = datetime.date(year, month, calendar.monthrange(year, month)[1])

    rows = (
        db.query(Transaction.category_id, Transaction.amount, Transaction.is_recurring)
        .filter(
            Transaction.category_id.isnot(None),
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .all()
    )
    spent_by_category: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal(0))
    recurring_spent_by_category: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal(0))
    for category_id, amount, is_recurring in rows:
        spent_by_category[category_id] += amount
        if is_recurring:
            recurring_spent_by_category[category_id] += amount

    categories = db.query(Category).all()
    groups = db.query(CategoryGroup).order_by(CategoryGroup.sort_order).all()

    def effective_budget(category: Category) -> Optional[Decimal]:
        if category.budget is None:
            return None
        return category.budget + recurring_spent_by_category[category.id]

    def to_category_spend(category: Category) -> CategorySpend:
        spent = spent_by_category[category.id]
        budget = effective_budget(category)
        return CategorySpend(
            category_id=category.id,
            name=category.name,
            color=category.color,
            icon=category.icon,
            spent=spent,
            budget=budget,
            status=_status(spent, budget),
        )

    categories_by_group: dict[uuid.UUID, list[Category]] = defaultdict(list)
    ungrouped_categories = []
    for category in categories:
        if category.group_id is None:
            ungrouped_categories.append(category)
        else:
            categories_by_group[category.group_id].append(category)

    def budgeted_totals(categories_in_scope: list[Category]) -> tuple[Decimal, Optional[Decimal]]:
        """Sums spent/budget across only the categories that have a budget
        set -- shared by group and grand totals so the two stay consistent."""
        budgeted = [c for c in categories_in_scope if c.budget is not None]
        spent = sum((spent_by_category[c.id] for c in budgeted), Decimal(0))
        budget = sum((effective_budget(c) for c in budgeted), Decimal(0)) if budgeted else None
        return spent, budget

    def all_categories_spent(categories_in_scope: list[Category]) -> Decimal:
        """Every category's spend, budgeted or not -- the grand-total
        counterpart to `total_spent`, for "how much did this month actually
        cost" independent of what's being tracked against a budget."""
        return sum((spent_by_category[c.id] for c in categories_in_scope), Decimal(0))

    group_spends = []
    for group in groups:
        group_categories = categories_by_group[group.id]
        category_spends = [to_category_spend(c) for c in group_categories]

        # A group only gets a budget/status when EVERY one of its
        # categories has one -- a partial budget (some categories opted
        # in, some didn't) would compare total group spend against an
        # incomplete denominator, making the group look "over budget"
        # for reasons that have nothing to do with overspending. If it's
        # not fully budgeted, just show the plain total spend instead.
        group_spent = all_categories_spent(group_categories)
        fully_budgeted = bool(group_categories) and all(c.budget is not None for c in group_categories)
        group_budget = (
            sum((effective_budget(c) for c in group_categories), Decimal(0))
            if fully_budgeted else None
        )
        group_spends.append(CategoryGroupSpend(
            group_id=group.id,
            name=group.name,
            sort_order=group.sort_order,
            spent=group_spent,
            budget=group_budget,
            status=_status(group_spent, group_budget),
            categories=category_spends,
        ))

    ungrouped_spends = [to_category_spend(c) for c in ungrouped_categories]

    total_spent, total_budget = budgeted_totals(categories)

    return CategoriesOverviewResponse(
        year=year,
        month=month,
        total_spent=total_spent,
        total_budget=total_budget,
        all_categories_spent=all_categories_spent(categories),
        groups=group_spends,
        ungrouped=ungrouped_spends,
    )
