"""
Household composition for the Shared Expenses split -- previously a
hardcoded `HOUSEHOLD_SPLIT` constant in app/services/shared_expenses.py,
now user-editable (percentages change, roommates come and go).

`display_order` decides which member absorbs the rounding remainder when
splitting a total (the last one, by this order) -- see
app/services/shared_expenses.py::_amount_owed. It's assigned from list
position on write (app/routers/household_members.py), not user-supplied,
so there's never a gap or a tie to resolve.

There's no CRUD on individual rows -- see the router for why the whole
set is replaced atomically instead. Percentages across all rows must
always sum to exactly 1, enforced there, not here (a single row's
percentage is meaningless in isolation).
"""
import uuid
from sqlalchemy import Column, String, Integer, Numeric, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class HouseholdMember(Base):
    __tablename__ = "household_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)

    # Fraction of the shared total this member owes, e.g. 0.7000 for 70%.
    percentage = Column(Numeric(5, 4), nullable=False)

    # Case-insensitive substrings identifying this member's settle-up
    # transfer into a shared depository account -- their bank's own
    # naming convention for an external transfer (e.g. "capital one
    # transfer"), matched against the transaction's name/display_name.
    # Stored as JSON (not a child table) since these are only ever read
    # or replaced as a whole list, never queried individually.
    settlement_patterns = Column(JSON, nullable=False, default=list)

    display_order = Column(Integer, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
