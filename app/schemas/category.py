"""
Request/response models for the Categories API. Same pattern as
app/schemas/account.py -- the overview shapes at the bottom back the
spend-vs-budget rollup (app/services/category_overview.py), which isn't
a stored column anywhere, just computed per-request from transactions.
"""
import uuid
from decimal import Decimal
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CategoryGroupBase(BaseModel):
    name: str
    sort_order: Decimal = Decimal(0)


class CategoryGroupCreate(CategoryGroupBase):
    pass


class CategoryGroupUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[Decimal] = None


class CategoryGroupResponse(CategoryGroupBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class CategoryBase(BaseModel):
    name: str
    color: str
    icon: str
    budget: Optional[Decimal] = None
    group_id: Optional[uuid.UUID] = None


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    budget: Optional[Decimal] = None
    group_id: Optional[uuid.UUID] = None


class CategoryResponse(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_default: bool  # read-only -- never settable via CategoryCreate/CategoryUpdate
    created_at: datetime
    updated_at: datetime


# ── Spend-vs-budget overview ────────────────────────────────────────────

class CategorySpend(BaseModel):
    category_id: uuid.UUID
    name: str
    color: str
    icon: str
    spent: Decimal
    budget: Optional[Decimal] = None
    # None when there's no budget to compare against -- matches the
    # reference UI showing no progress bar at all for unbudgeted categories.
    status: Optional[str] = None  # "under" | "near" | "over"


class CategoryGroupSpend(BaseModel):
    group_id: uuid.UUID
    name: str
    sort_order: Decimal
    # spent = every category in the group, budgeted or not -- always the
    # full total, unlike the top-level total_spent/all_categories_spent
    # split. budget/status are only present when EVERY category in the
    # group has a budget set -- otherwise a partial budget would compare
    # the full spend against an incomplete denominator.
    spent: Decimal
    budget: Optional[Decimal] = None
    status: Optional[str] = None
    categories: list[CategorySpend]


class CategoriesOverviewResponse(BaseModel):
    year: int
    month: int
    total_spent: Decimal  # budget-scoped, same distinction as CategoryGroupSpend.spent
    total_budget: Optional[Decimal] = None
    all_categories_spent: Decimal  # every category across every group + ungrouped, budgeted or not
    groups: list[CategoryGroupSpend]
    ungrouped: list[CategorySpend]
