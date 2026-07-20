"""
Accounts tab endpoints:
  - Manual account CRUD (add/edit/remove) -- fully testable right now
  - Plaid linking (create Link token, exchange public_token) -- requires
    a frontend (or Plaid's own tools) to actually get a public_token,
    since that only comes from completing the Plaid Link widget in a
    browser. The endpoints are correct and ready; full end-to-end testing
    of this half waits until we build a frontend.
  - Connection management: reverify (Link in "update mode"), hide, close
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.accounts_get_request import AccountsGetRequest

from app.database import get_db
from app.models.account import Account, AccountType, AccountStatus
from app.schemas.account import (
    ManualAccountCreate,
    AccountUpdate,
    AccountResponse,
    PlaidLinkTokenResponse,
    PlaidExchangeRequest,
)
from app.core.plaid_client import get_plaid_client
from app.core.secrets import store_plaid_access_token, get_plaid_access_token

router = APIRouter(prefix="/accounts", tags=["accounts"])

# This is a single-household app (just the two of you), not a
# multi-tenant product -- so a single static Plaid client_user_id is
# fine, unlike a real product where every signed-up user needs their own.
PLAID_CLIENT_USER_ID = "household"

PLAID_TYPE_TO_ACCOUNT_TYPE = {
    "investment": AccountType.investment,
    "depository": AccountType.depository,
    "credit": AccountType.credit_card,
}


def _get_account_or_404(account_id: uuid.UUID, db: Session) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


# ── Manual account CRUD ─────────────────────────────────────────────────

@router.post("/manual", response_model=AccountResponse, status_code=201)
def create_manual_account(payload: ManualAccountCreate, db: Session = Depends(get_db)):
    account = Account(
        name=payload.name,
        institution=payload.institution,
        account_type=payload.account_type,
        current_balance=payload.current_balance,
        is_manual=True,
        status=AccountStatus.active,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("", response_model=list[AccountResponse])
def list_accounts(db: Session = Depends(get_db)):
    return db.query(Account).order_by(Account.created_at).all()


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(account_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_account_or_404(account_id, db)


@router.patch("/{account_id}", response_model=AccountResponse)
def update_account(account_id: uuid.UUID, payload: AccountUpdate, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: uuid.UUID, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)
    db.delete(account)
    db.commit()


# ── Plaid linking ────────────────────────────────────────────────────────

@router.post("/plaid/link-token", response_model=PlaidLinkTokenResponse)
def create_link_token():
    """Creates a Link token for linking a BRAND NEW account. The frontend
    passes this to Plaid's Link widget, which returns a public_token on
    success -- that gets sent to /plaid/exchange below."""
    client = get_plaid_client()
    request = LinkTokenCreateRequest(
        products=[Products("transactions")],
        client_name="Copilot Clone",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=PLAID_CLIENT_USER_ID),
    )
    response = client.link_token_create(request)
    return {"link_token": response["link_token"]}


@router.post("/plaid/exchange", response_model=list[AccountResponse], status_code=201)
def exchange_public_token(payload: PlaidExchangeRequest, db: Session = Depends(get_db)):
    """Exchanges a public_token (from completing Plaid Link) for a real
    access_token, stores it in Secrets Manager, fetches the linked
    account(s) from Plaid, and creates an Account row for each -- a
    single Plaid Item can represent multiple accounts (e.g. checking +
    savings at the same bank)."""
    client = get_plaid_client()

    exchange_response = client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=payload.public_token)
    )
    access_token = exchange_response["access_token"]
    item_id = exchange_response["item_id"]

    accounts_response = client.accounts_get(AccountsGetRequest(access_token=access_token))
    institution_name = accounts_response.get("item", {}).get("institution_id") or "Unknown"

    secret_ref = store_plaid_access_token(item_id, access_token)

    created = []
    for plaid_account in accounts_response["accounts"]:
        account_type = PLAID_TYPE_TO_ACCOUNT_TYPE.get(str(plaid_account["type"]), AccountType.depository)
        account = Account(
            name=plaid_account["name"],
            institution=institution_name,
            account_type=account_type,
            current_balance=plaid_account["balances"]["current"],
            is_manual=False,
            status=AccountStatus.active,
            plaid_item_id=item_id,
            plaid_account_id=plaid_account["account_id"],
            plaid_access_token_ref=secret_ref,
        )
        db.add(account)
        created.append(account)

    db.commit()
    for account in created:
        db.refresh(account)
    return created


# ── Connection management ───────────────────────────────────────────────

@router.post("/{account_id}/reverify-link-token", response_model=PlaidLinkTokenResponse)
def create_reverify_link_token(account_id: uuid.UUID, db: Session = Depends(get_db)):
    """Creates a Link token in Plaid's "update mode" (passing the
    existing access_token) for re-authenticating a connection that's
    stopped syncing -- the "Reverify" button from the reference images."""
    account = _get_account_or_404(account_id, db)
    if account.is_manual or not account.plaid_access_token_ref:
        raise HTTPException(status_code=400, detail="This account isn't Plaid-linked")

    access_token = get_plaid_access_token(account.plaid_access_token_ref)

    client = get_plaid_client()
    request = LinkTokenCreateRequest(
        client_name="Copilot Clone",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=PLAID_CLIENT_USER_ID),
        access_token=access_token,  # presence of access_token = update mode
    )
    response = client.link_token_create(request)
    return {"link_token": response["link_token"]}


@router.post("/{account_id}/hide", response_model=AccountResponse)
def hide_account(account_id: uuid.UUID, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)
    account.status = AccountStatus.hidden
    db.commit()
    db.refresh(account)
    return account


@router.post("/{account_id}/close", response_model=AccountResponse)
def close_account(account_id: uuid.UUID, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)
    account.status = AccountStatus.closed
    db.commit()
    db.refresh(account)
    return account
