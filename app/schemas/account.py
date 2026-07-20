"""
Request/response models for the Accounts API. Pydantic validates
incoming requests automatically (reject bad data before it ever reaches
our logic) and serializes outgoing responses -- FastAPI wires these in
via the `response_model=` parameter on each route.
"""
import uuid
from decimal import Decimal
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.models.account import AccountType, AccountStatus


class AccountBase(BaseModel):
    name: str
    institution: str
    account_type: AccountType


class ManualAccountCreate(AccountBase):
    current_balance: Optional[Decimal] = None


class AccountUpdate(BaseModel):
    """All fields optional -- callers only send what they want to change.
    Deliberately does NOT include is_manual or plaid_* fields -- those are
    set once at creation and shouldn't be editable afterward."""
    name: Optional[str] = None
    current_balance: Optional[Decimal] = None
    status: Optional[AccountStatus] = None


class AccountResponse(AccountBase):
    # Lets Pydantic build this response directly from a SQLAlchemy model
    # instance (account.name, account.id, etc.) instead of requiring a
    # plain dict.
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: AccountStatus
    is_manual: bool
    current_balance: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime


class PlaidLinkTokenResponse(BaseModel):
    link_token: str


class PlaidExchangeRequest(BaseModel):
    public_token: str
