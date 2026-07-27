"""
FastAPI entrypoint.
"""
from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import accounts, transactions, categories, recurring, shared_expenses, household_members

app = FastAPI(title="Money Tracking App API")
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(recurring.router)
app.include_router(shared_expenses.router)
app.include_router(household_members.router)

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Confirms both the app AND the database connection are alive --
    a health check that only pings the app process would miss a real
    failure mode (DB unreachable), which matters once this runs in ECS
    behind a load balancer doing health checks."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
