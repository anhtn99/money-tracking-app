"""
Shared Expenses tab: a single read-only endpoint, everything computed
fresh per-request by app/services/shared_expenses.py -- there's no
CRUD here, "shared" is a property of Accounts (app/routers/accounts.py)
and RecurringRules (app/routers/recurring.py), not its own resource.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.shared_expenses import SharedExpensesOverviewResponse
from app.services.shared_expenses import get_shared_expenses_overview

router = APIRouter(prefix="/shared-expenses", tags=["shared-expenses"])


@router.get("/overview", response_model=SharedExpensesOverviewResponse)
def get_overview(
    year: Optional[int] = Query(default=None, ge=2000, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    db: Session = Depends(get_db),
):
    today = date.today()
    return get_shared_expenses_overview(
        db,
        year if year is not None else today.year,
        month if month is not None else today.month,
    )
