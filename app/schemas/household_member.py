import uuid
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class HouseholdMemberWrite(BaseModel):
    name: str = Field(min_length=1)
    percentage: Decimal = Field(gt=0, le=1)
    settlement_patterns: list[str] = []


class HouseholdMemberReplaceRequest(BaseModel):
    # List order = settlement priority / rounding-remainder order -- the
    # LAST member in this list absorbs the remainder when a total doesn't
    # split evenly (see shared_expenses.py::_amount_owed).
    members: list[HouseholdMemberWrite]


class HouseholdMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    percentage: Decimal
    settlement_patterns: list[str]
    display_order: int
    created_at: datetime
    updated_at: datetime
