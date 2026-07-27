"""
Household composition for the Shared Expenses split. No per-row CRUD --
just GET (the current set) and PUT (replace the whole set) -- because the
one hard invariant here (percentages summing to exactly 100%) spans every
row at once. Editing one member's percentage always means adjusting at
least one other's, so a single-row PATCH could easily leave the set in
an invalid state between two separate requests; a whole-set replace makes
that impossible; it's valid before the request or it's rejected.

Replacing the set assigns fresh ids and reorders display_order from list
position -- nothing else references household_members by id (unlike
Category/RecurringRule, which transactions link to), so there's no
history to preserve across an edit.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.household_member import HouseholdMember
from app.schemas.household_member import HouseholdMemberReplaceRequest, HouseholdMemberResponse

router = APIRouter(prefix="/household-members", tags=["household-members"])


@router.get("", response_model=list[HouseholdMemberResponse])
def list_household_members(db: Session = Depends(get_db)):
    return db.query(HouseholdMember).order_by(HouseholdMember.display_order).all()


@router.put("", response_model=list[HouseholdMemberResponse])
def replace_household_members(payload: HouseholdMemberReplaceRequest, db: Session = Depends(get_db)):
    if not payload.members:
        raise HTTPException(status_code=422, detail="At least one household member is required")

    total = sum((member.percentage for member in payload.members), Decimal("0"))
    if total != Decimal("1"):
        raise HTTPException(
            status_code=422,
            detail=f"Percentages must sum to exactly 100% (100.00%) -- got {total * 100}%",
        )

    db.query(HouseholdMember).delete()

    created = []
    for index, member in enumerate(payload.members):
        row = HouseholdMember(
            name=member.name,
            percentage=member.percentage,
            settlement_patterns=member.settlement_patterns,
            display_order=index,
        )
        db.add(row)
        created.append(row)

    db.commit()
    for row in created:
        db.refresh(row)
    return created
