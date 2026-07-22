# Money Tracking App

A personal-finance app modeled on Copilot Money, built as a learning
project. FastAPI + Postgres, containerized, eventually deployed to
ECS Fargate + Aurora Serverless v2.

## Architecture

- **FastAPI** -- the API layer. Auto-generates interactive docs at
  `/docs` for free (try it once running).
- **SQLAlchemy** -- ORM / data model.
- **Alembic** -- schema migrations (never edit the database by hand;
  every schema change goes through a migration).
- **Postgres** -- relational database, a genuinely better fit here than
  DynamoDB given how interrelated accounts/transactions/categories/
  recurring-rules are (real joins, real aggregate queries).

## Data model (Phase 1 -- done)

- **Account** -- investment/depository/credit_card, manual or
  Plaid-linked, with a status (active/needs_reverification/hidden/closed)
- **Transaction** -- income/transfer/regular, linked to an account,
  optionally a category and a recurring rule
- **CategoryGroup** / **Category** -- grouped categories with optional
  budgets
- **RecurringRule** -- frequency, name-matching pattern, amount range,
  expected-date window

A few deliberate design choices worth knowing about:
- **Plaid access tokens are never stored directly** -- `Account.plaid_access_token_ref`
  holds a reference (e.g. a Secrets Manager ARN), not the token itself.
- **Transaction amount sign** follows Plaid's own convention (positive =
  money out) for consistency with the existing sync pipelines.
- **The "show this amount in green" rule** from the spec is presentation
  logic (depends on type + sign + account type together) -- computed in
  the API response layer in Phase 3, not stored as a column.

## Local development

```bash
cp .env.example .env
docker compose up --build
```

This starts Postgres + the API with live-reload. Once it's up:

```bash
# Apply the schema (first time, and after any future model changes)
docker compose exec app alembic revision --autogenerate -m "initial schema"
docker compose exec app alembic upgrade head
```

Then check:
- http://localhost:8000/health -- confirms the app AND database connection are both alive
- http://localhost:8000/docs -- interactive API explorer (empty for now, fills in as we build routers)

## Roadmap

1. ~~Infrastructure + data model~~ (Phase 1)
2. ~~Accounts tab~~ (Phase 2)
3. ~~Transactions tab~~ (Phase 3 -- this update)
4. **Categories tab** -- budgets, grouping
5. **Recurrings tab** -- manual rules, then auto-detection

### Phase 2: Accounts tab

Endpoints added (see `/docs` for the full interactive list):
- `POST /accounts/manual`, `GET /accounts`, `GET /accounts/{id}`,
  `PATCH /accounts/{id}`, `DELETE /accounts/{id}` -- manual account CRUD
- `POST /accounts/plaid/link-token`, `POST /accounts/plaid/exchange` --
  linking a new Plaid account
- `POST /accounts/{id}/reverify-link-token` -- Link in "update mode",
  for the "Reverify" flow when a connection stops syncing
- `POST /accounts/{id}/hide`, `POST /accounts/{id}/close` -- connection
  management

**What's fully testable right now** (via `/docs`, no extra setup): all
the manual account CRUD endpoints.

**What needs more setup to test**: the Plaid endpoints need
`PLAID_CLIENT_ID`/`PLAID_SECRET`/`PLAID_ENV` in your `.env` (same values
as your other Plaid projects), and the Secrets Manager calls need AWS
credentials available to the container (docker-compose passes through
your local `AWS_*` env vars automatically -- make sure you're logged in
locally, e.g. `aws sso login`, before starting the container).

**What's built but not fully end-to-end testable yet**: actually
completing Plaid Link requires their JS widget running in a browser
(same as `link_account.py` in your other project, just not built here
yet) -- `/accounts/plaid/exchange` is correct and ready, but you can't
get a real `public_token` to test it with until we build a frontend.

### Phase 3: Transactions tab

Endpoints added:
- `POST /transactions/manual`, `GET /transactions`, `GET /transactions/{id}`,
  `PATCH /transactions/{id}`, `DELETE /transactions/{id}` -- manual
  transaction CRUD, works against any account (manual or Plaid-linked).
  `GET /transactions` supports `account_id` / `transaction_type` /
  `start_date` / `end_date` filters.
- `POST /transactions/sync` -- pulls new transactions from every active,
  Plaid-linked account (`app/services/transaction_sync.py`), same
  cursor-based `transactions/sync` approach as the existing
  `plaid-sheets-sync` Lambda, adapted to write into Postgres. Runs
  on-demand for now; a schedule is a Phase 6 (AWS deployment) concern.

A few implementation notes worth knowing about:
- **Type classification** happens once, at creation -- Plaid's
  `personal_finance_category.primary` maps `INCOME` to `income` and
  `TRANSFER_IN`/`TRANSFER_OUT`/`LOAN_PAYMENTS` to `transfer`, everything
  else to `regular`. A later "modified" sync event refreshes
  Plaid-sourced fields (name/amount/date/pending) but never re-classifies
  the type or touches `category_id`/`notes`/`is_recurring` -- so a manual
  override (e.g. "Mark as internal transfer") or manually-set category
  survives future syncs.
- **Categories aren't assigned by sync** -- the Categories tab (Phase 4)
  doesn't exist yet, so synced transactions land with `category_id = null`
  until that's built.
- **The green-amount and `[R]`/`[T]`/`[I]` indicator** are computed
  per-request in `app/services/transaction_presentation.py`, not stored
  columns -- see the design note in `app/models/transaction.py`. The
  indicator is treated as mutually exclusive (recurring beats
  transfer/income beats regular), matching how the spec's reference
  images show it.
- **Sync cursor** lives on `Account.plaid_sync_cursor`. Since one Plaid
  Item (access token) can back multiple accounts, the cursor is written
  to every `Account` row sharing a `plaid_item_id` after a successful
  sync -- same duplication pattern already used for
  `plaid_access_token_ref`.
- A broken connection (e.g. `ITEM_LOGIN_REQUIRED`) flips just that
  account's `status` to `needs_reverification` and moves on to the next
  Item, rather than failing the whole sync run.

**What's fully testable right now**: everything -- manual CRUD via
`/docs`, and sync via `pytest` (mocks the Plaid client, see
`tests/test_transactions.py`) or by actually linking a sandbox account
via `/accounts/plaid/exchange` first.

## Running tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Tests run against an in-memory SQLite database (see `tests/conftest.py`
and the sqlite fallback in `app/database.py`) -- no Docker or Postgres
required. Plaid sync tests mock the Plaid client entirely, so no network
access or real credentials are needed either.

## Deploying to AWS (later phase, not yet done)

Not built yet -- once local dev is solid, next step is Aurora Serverless
v2 + ECS Fargate + an ECR repo for the container image. Will likely use
Terraform for this, given the IaC learning goal.
