"""
Request/response models for the Recurring Rules API. Same layered
pattern as app/schemas/category.py.
"""
import uuid
from decimal import Decimal
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.models.recurring import RecurringFrequency, NameMatchType


class RecurringRuleBase(BaseModel):
    name: str
    icon: str
    frequency: RecurringFrequency

    name_match_type: NameMatchType = NameMatchType.partial
    name_pattern: str

    amount_min: Decimal
    amount_max: Decimal

    expected_day_of_period: int
    expected_date_tolerance_days: int = 3

    is_shared: bool = False


class RecurringRuleCreate(RecurringRuleBase):
    # No apply_to_existing choice here -- Copilot's own creation flow
    # always retroactively matches existing transactions (the choice only
    # appears when editing a rule's matching criteria afterward, see
    # RecurringRuleUpdate below). Removing an individual bad match from a
    # freshly-created rule is a PATCH /transactions/{id} with
    # recurring_rule_id: null away, same as Copilot's per-row "X" in that
    # screen.
    pass


class RecurringRuleUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    frequency: Optional[RecurringFrequency] = None
    name_match_type: Optional[NameMatchType] = None
    name_pattern: Optional[str] = None
    amount_min: Optional[Decimal] = None
    amount_max: Optional[Decimal] = None
    expected_day_of_period: Optional[int] = None
    expected_date_tolerance_days: Optional[int] = None
    is_shared: Optional[bool] = None
    # Request-only directive, not a stored column -- mirrors Copilot's
    # "Recurring Filter Changes" modal ("Only for future payments" vs
    # "Also recalculate previous payments"), shown when a matching-
    # relevant field (name_pattern/amount_min/amount_max/name_match_type)
    # is part of the update. True (the default) re-scans existing
    # unmatched transactions against the updated criteria.
    apply_to_existing: bool = True


class RecurringRuleResponse(RecurringRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
