"""
Categories tab endpoints:
  - CategoryGroup CRUD (add/edit/remove groups)
  - Category CRUD (add/edit/remove categories, optionally under a group)
  - GET /categories/overview -- spend-vs-budget rollup for a given month
    (app/services/category_overview.py)

Route ordering note: "/groups" and "/overview" are registered before
"/{category_id}" deliberately -- both are single path segments, same
shape as the wildcard, so FastAPI would otherwise match e.g.
GET /categories/overview against "/{category_id}" with
category_id="overview" (first-registered-route-wins), the same gotcha
covered for the Accounts router's path-parameter binding.
"""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.category import Category, CategoryGroup
from app.models.transaction import Transaction
from app.schemas.category import (
    CategoryGroupCreate,
    CategoryGroupUpdate,
    CategoryGroupResponse,
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
    CategoriesOverviewResponse,
)
from app.services.category_overview import get_categories_overview
from app.services.default_category import get_default_category

router = APIRouter(prefix="/categories", tags=["categories"])


def _get_group_or_404(group_id: uuid.UUID, db: Session) -> CategoryGroup:
    group = db.get(CategoryGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Category group not found")
    return group


def _get_category_or_404(category_id: uuid.UUID, db: Session) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


# ── Category groups ──────────────────────────────────────────────────────

@router.post("/groups", response_model=CategoryGroupResponse, status_code=201)
def create_category_group(payload: CategoryGroupCreate, db: Session = Depends(get_db)):
    group = CategoryGroup(name=payload.name, sort_order=payload.sort_order)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.get("/groups", response_model=list[CategoryGroupResponse])
def list_category_groups(db: Session = Depends(get_db)):
    return db.query(CategoryGroup).order_by(CategoryGroup.sort_order).all()


@router.get("/groups/{group_id}", response_model=CategoryGroupResponse)
def get_category_group(group_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_group_or_404(group_id, db)


@router.patch("/groups/{group_id}", response_model=CategoryGroupResponse)
def update_category_group(group_id: uuid.UUID, payload: CategoryGroupUpdate, db: Session = Depends(get_db)):
    group = _get_group_or_404(group_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/groups/{group_id}", status_code=204)
def delete_category_group(group_id: uuid.UUID, db: Session = Depends(get_db)):
    """Deleting a group doesn't delete its categories -- they become
    ungrouped (group_id -> null) rather than losing budget/transaction
    history, which would be a much more destructive side effect for a
    single misclick."""
    group = _get_group_or_404(group_id, db)
    db.query(Category).filter(Category.group_id == group_id).update({"group_id": None})
    db.delete(group)
    db.commit()


# ── Categories ───────────────────────────────────────────────────────────

@router.get("/overview", response_model=CategoriesOverviewResponse)
def get_overview(
    year: Optional[int] = Query(default=None, ge=2000, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    db: Session = Depends(get_db),
):
    # `year if year is not None else ...`, not `year or ...` -- the latter
    # would treat an explicit month=0 as "not given" (0 is falsy) and
    # silently substitute today's month instead of rejecting it. The
    # ge=1 bound above already rejects 0 with a clean 422, but the
    # explicit None-check is what makes that guarantee actually hold.
    today = date.today()
    return get_categories_overview(
        db,
        year if year is not None else today.year,
        month if month is not None else today.month,
    )


@router.post("", response_model=CategoryResponse, status_code=201)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    if payload.group_id is not None:
        _get_group_or_404(payload.group_id, db)
    category = Category(
        name=payload.name,
        color=payload.color,
        icon=payload.icon,
        budget=payload.budget,
        group_id=payload.group_id,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.get("", response_model=list[CategoryResponse])
def list_categories(group_id: Optional[uuid.UUID] = None, db: Session = Depends(get_db)):
    query = db.query(Category)
    if group_id is not None:
        query = query.filter(Category.group_id == group_id)
    return query.order_by(Category.name).all()


@router.get("/{category_id}", response_model=CategoryResponse)
def get_category(category_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_category_or_404(category_id, db)


@router.patch("/{category_id}", response_model=CategoryResponse)
def update_category(category_id: uuid.UUID, payload: CategoryUpdate, db: Session = Depends(get_db)):
    category = _get_category_or_404(category_id, db)
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("group_id") is not None:
        _get_group_or_404(updates["group_id"], db)
    for field, value in updates.items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: uuid.UUID, db: Session = Depends(get_db)):
    """Every transaction always has a category (Transaction.category_id
    is NOT NULL), so deleting one can't just leave its transactions
    dangling -- they're reassigned to "Other" first, then the category
    is deleted. "Other" itself can never be deleted -- it's the
    reassignment target, so it must always exist."""
    category = _get_category_or_404(category_id, db)
    if category.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default category")

    default_category = get_default_category(db)
    db.query(Transaction).filter(Transaction.category_id == category_id).update(
        {"category_id": default_category.id}
    )
    db.delete(category)
    db.commit()
