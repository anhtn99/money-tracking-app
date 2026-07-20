"""
Accounts tab data model.

Design note on Plaid credentials: the raw access_token is deliberately
NOT stored in this table. Storing bank credentials directly in an
application database is bad practice even for a personal project --
plaid_access_token_ref holds a reference (e.g. an AWS Secrets Manager
secret ARN) instead, and the actual token lookup happens through that
secrets store at sync time.
"""
import enum
import uuid
from sqlalchemy import Column, String, Boolean, Numeric, DateTime, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class AccountType(str, enum.Enum):
    investment = "investment"
    depository = "depository"
    credit_card = "credit_card"


class AccountStatus(str, enum.Enum):
    active = "active"
    needs_reverification = "needs_reverification"
    hidden = "hidden"
    closed = "closed"


class Account(Base):
    __tablename__ = "accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    institution = Column(String, nullable=False)  # e.g. "Chase", "Fidelity", "Venmo"
    account_type = Column(Enum(AccountType), nullable=False)
    status = Column(Enum(AccountStatus), nullable=False, default=AccountStatus.active)

    is_manual = Column(Boolean, nullable=False, default=False)
    current_balance = Column(Numeric(12, 2), nullable=True)

    # Only set for Plaid-linked accounts -- null for manual ones
    plaid_item_id = Column(String, nullable=True)
    plaid_account_id = Column(String, nullable=True, unique=True)
    plaid_access_token_ref = Column(String, nullable=True)  # secrets manager ARN, not the token itself

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
