"""
Matches transactions against RecurringRules -- the core job of the
Recurring tab: linking a transaction to a rule also renames its
display_name (see the design note on app/models/transaction.py), e.g. a
transaction named "Zelle payment to GOLD PROPERTIES LLC" displays as
"Chicago Rent" once matched to a rule by that name.

v1 scope: matching is name pattern + amount range only.
expected_day_of_period/expected_date_tolerance_days on RecurringRule are
NOT used here -- see the design note on app/models/recurring.py for why.

Tie-breaking: if a transaction could match more than one rule, the
earliest-created rule wins (query order below). There's no explicit
priority field -- in practice this hasn't mattered yet since rule
name_patterns for one household are all distinct merchants/payees.
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.recurring import RecurringRule, NameMatchType
from app.models.transaction import Transaction


def _matches(rule: RecurringRule, name: str, amount: Decimal) -> bool:
    if not (rule.amount_min <= amount <= rule.amount_max):
        return False
    haystack = name.lower()
    pattern = rule.name_pattern.lower()
    if rule.name_match_type == NameMatchType.exact:
        return haystack.strip() == pattern.strip()
    return pattern in haystack


def find_matching_rule(db: Session, name: str, amount: Decimal) -> Optional[RecurringRule]:
    for rule in db.query(RecurringRule).order_by(RecurringRule.created_at).all():
        if _matches(rule, name, amount):
            return rule
    return None


def apply_recurring_match(transaction: Transaction, rule: RecurringRule) -> None:
    transaction.recurring_rule_id = rule.id
    transaction.is_recurring = True
    transaction.display_name = rule.name


def match_transaction(db: Session, transaction: Transaction) -> bool:
    """Attempts to link an unmatched transaction to a rule. No-op (and
    returns False) if the transaction is already linked -- never steals a
    transaction from one rule to give it to another automatically."""
    if transaction.recurring_rule_id is not None:
        return False
    rule = find_matching_rule(db, transaction.name, transaction.amount)
    if rule is None:
        return False
    apply_recurring_match(transaction, rule)
    return True


def rematch_existing_transactions(db: Session, rule: RecurringRule) -> int:
    """Retroactively links a newly-created (or renamed/re-patterned) rule
    to historical transactions that already exist and aren't linked to
    some other rule. Returns the number of transactions matched."""
    unmatched = db.query(Transaction).filter(Transaction.recurring_rule_id.is_(None)).all()
    matched_count = 0
    for transaction in unmatched:
        if _matches(rule, transaction.name, transaction.amount):
            apply_recurring_match(transaction, rule)
            matched_count += 1
    return matched_count
