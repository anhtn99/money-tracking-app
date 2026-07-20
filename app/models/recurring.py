"""
Recurrings tab data model.

Design note on the "expected date range": rather than a fixed calendar
date (which doesn't generalize across weekly/monthly/yearly frequencies),
this stores a day-within-the-period (e.g. "day 1" for a monthly rent rule)
plus a tolerance window in days -- reused the same way regardless of
frequency.
"""
import enum
import uuid
from sqlalchemy import Column, String, Integer, Numeric, DateTime, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class RecurringFrequency(str, enum.Enum):
    weekly = "weekly"
    every_2_weeks = "every_2_weeks"
    monthly = "monthly"
    every_2_months = "every_2_months"
    every_3_months = "every_3_months"
    every_4_months = "every_4_months"
    every_6_months = "every_6_months"
    yearly = "yearly"


class NameMatchType(str, enum.Enum):
    exact = "exact"
    partial = "partial"


class RecurringRule(Base):
    __tablename__ = "recurring_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    icon = Column(String, nullable=False)
    frequency = Column(Enum(RecurringFrequency), nullable=False)

    name_match_type = Column(Enum(NameMatchType), nullable=False, default=NameMatchType.partial)
    name_pattern = Column(String, nullable=False)

    amount_min = Column(Numeric(12, 2), nullable=False)
    amount_max = Column(Numeric(12, 2), nullable=False)

    expected_day_of_period = Column(Integer, nullable=False)  # e.g. 1 for "around the 1st"
    expected_date_tolerance_days = Column(Integer, nullable=False, default=3)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
