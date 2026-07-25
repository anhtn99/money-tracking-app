"""
Recurring tab endpoints: RecurringRule CRUD, with matching
(app/services/recurring_matching.py) wired in at the points where it
matters --
  - create: always retroactively matches existing unmatched transactions
    against the new rule (so setting up "Chicago Rent" today also
    relabels past occurrences, not just future ones) -- no opt-out here,
    matching Copilot's own creation flow. Unwanted individual matches can
    be unlinked afterward via PATCH /transactions/{id}.
  - update: same retroactive matching, but only when a matching-relevant
    field changes (criteria may now catch previously-unmatched
    transactions), and only if the caller doesn't opt out via
    apply_to_existing=False ("only future payments," mirroring Copilot's
    "Recurring Filter Changes" modal). Renaming a rule always propagates
    to transactions already linked to it regardless of apply_to_existing
    -- that's just keeping an existing label in sync, not "applying the
    rule to more transactions."
  - delete: unlinks rather than blocking -- linked transactions fall back
    to their original name instead of losing history, same reasoning as
    Categories' delete-reassigns-to-Other and CategoryGroup's
    delete-ungroups.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.recurring import RecurringRule
from app.models.transaction import Transaction
from app.schemas.recurring import RecurringRuleCreate, RecurringRuleUpdate, RecurringRuleResponse
from app.services.recurring_matching import rematch_existing_transactions

router = APIRouter(prefix="/recurring", tags=["recurring"])

# Fields that actually affect which transactions a rule matches -- an
# update touching only e.g. is_shared/icon has nothing to recalculate,
# so update_recurring_rule skips the full-table rematch scan entirely
# unless one of these was part of the request.
_MATCHING_FIELDS = {"name_pattern", "amount_min", "amount_max", "name_match_type"}


def _get_recurring_rule_or_404(rule_id: uuid.UUID, db: Session) -> RecurringRule:
    rule = db.get(RecurringRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Recurring rule not found")
    return rule


@router.post("", response_model=RecurringRuleResponse, status_code=201)
def create_recurring_rule(payload: RecurringRuleCreate, db: Session = Depends(get_db)):
    rule = RecurringRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)

    rematch_existing_transactions(db, rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("", response_model=list[RecurringRuleResponse])
def list_recurring_rules(db: Session = Depends(get_db)):
    return db.query(RecurringRule).order_by(RecurringRule.name).all()


@router.get("/{rule_id}", response_model=RecurringRuleResponse)
def get_recurring_rule(rule_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_recurring_rule_or_404(rule_id, db)


@router.patch("/{rule_id}", response_model=RecurringRuleResponse)
def update_recurring_rule(rule_id: uuid.UUID, payload: RecurringRuleUpdate, db: Session = Depends(get_db)):
    rule = _get_recurring_rule_or_404(rule_id, db)
    updates = payload.model_dump(exclude_unset=True)
    # Not a stored column -- read the directive, then drop it so the
    # setattr loop below doesn't choke on an unknown RecurringRule field.
    apply_to_existing = updates.pop("apply_to_existing", True)

    for field, value in updates.items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)

    if "name" in updates:
        db.query(Transaction).filter(Transaction.recurring_rule_id == rule.id).update(
            {"display_name": rule.name}
        )
        db.commit()
    if apply_to_existing and _MATCHING_FIELDS & updates.keys():
        rematch_existing_transactions(db, rule)
        db.commit()
        db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
def delete_recurring_rule(rule_id: uuid.UUID, db: Session = Depends(get_db)):
    rule = _get_recurring_rule_or_404(rule_id, db)
    linked = db.query(Transaction).filter(Transaction.recurring_rule_id == rule.id).all()
    for transaction in linked:
        transaction.recurring_rule_id = None
        transaction.is_recurring = False
        transaction.display_name = transaction.name
    db.delete(rule)
    db.commit()
