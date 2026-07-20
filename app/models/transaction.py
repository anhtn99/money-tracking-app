"""
Transactions tab data model.

Amount sign convention: matches Plaid's own convention, for consistency
with the sync pipelines already built elsewhere -- POSITIVE = money out
(an expense/charge), NEGATIVE = money in (income, a refund, a transfer
in). The "should this show green" rule from the spec is presentation
logic (depends on transaction_type + sign + account_type together), not
a stored column -- computed in the API response layer instead, added
when we build the Transactions endpoints in Phase 3.
"""
import enum
import uuid
from sqlalchemy import Column, String, Numeric, Date, Boolean, DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class TransactionType(str, enum.Enum):
    income = "income"       # shown with [I]
    transfer = "transfer"   # shown with [T]
    regular = "regular"     # no marker


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    account = relationship("Account")

    name = Column(String, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)  # see sign convention above
    transaction_date = Column(Date, nullable=False)
    transaction_type = Column(Enum(TransactionType), nullable=False, default=TransactionType.regular)

    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True)
    category = relationship("Category")

    recurring_rule_id = Column(UUID(as_uuid=True), ForeignKey("recurring_rules.id"), nullable=True)
    recurring_rule = relationship("RecurringRule")
    is_recurring = Column(Boolean, nullable=False, default=False)  # shown with [R]

    is_manual = Column(Boolean, nullable=False, default=False)  # manually-added vs synced
    is_pending = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)

    # Only set for Plaid-synced transactions -- used for dedup, same
    # pattern as the existing sync pipelines. Null for manual entries.
    plaid_transaction_id = Column(String, nullable=True, unique=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
