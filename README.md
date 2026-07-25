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
3. ~~Transactions tab~~ (Phase 3)
4. ~~Categories tab~~ (Phase 4)
5. ~~Recurrings tab~~ (Phase 5 -- this update)
6. **Shared Expenses tab** -- built entirely on top of Phase 5, no
   changes to Phases 1-5's own code (see the design note below)

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

### Phase 4: Categories tab

`Category`/`CategoryGroup` were already modeled in Phase 1 -- this phase
is all endpoints, no new migration.

Endpoints added:
- `POST /categories/groups`, `GET /categories/groups`,
  `GET /categories/groups/{id}`, `PATCH /categories/groups/{id}`,
  `DELETE /categories/groups/{id}` -- CategoryGroup CRUD
- `POST /categories`, `GET /categories` (filterable by `group_id`),
  `GET /categories/{id}`, `PATCH /categories/{id}`,
  `DELETE /categories/{id}` -- Category CRUD
- `GET /categories/overview?year=&month=` -- budget-vs-spend rollup per
  category and per group for a given month (defaults to the current
  month), matching `categories-tab.png`. Computed fresh from that month's
  transactions on every request (`app/services/category_overview.py`),
  not a stored/cached value.
- `GET /transactions/cashflow?year=&month=` -- total income minus total
  spend across *every* transaction that month, regardless of category or
  budget status (`app/services/cash_flow.py`). Lives on the transactions
  router rather than categories, since it isn't category-scoped at all.

**The budget model, after a design pass following user feedback** (the
first draft above was simpler and got revised before being used anywhere):
- A category's **effective budget** = its manual `budget` **+** the sum
  of that category's own `is_recurring` transactions actually dated in
  that month. Reasoning: a category can have both a monthly recurring
  cost and a yearly one (e.g. Netflix monthly + Amazon Prime yearly under
  "Subscriptions") -- a flat monthly budget would make the one month the
  yearly charge lands in look "over budget" even though it's expected.
  This is reactive (based on transactions that already happened), not a
  projection from Recurring Rules -- `RecurringRule` (Phase 5) has no
  `category_id` or anchor date to project "which month is this due in"
  from yet, so building that projection now would mean front-loading
  Phase 5 work into Phase 4.
- **A category with no budget set is excluded from the grand total's
  `total_spent`/`total_budget`** -- even though its spend is real. It's
  still *listed* (matching the reference screenshot's "Credit Card Fee"
  row) with `budget: null`. That real spend isn't lost, though -- the
  top-level response also carries `all_categories_spent`, which sums
  every category regardless of budget status (distinct from
  `/transactions/cashflow`, which is scoped even wider -- literally every
  transaction, categorized or not, not just categorized-but-unbudgeted).
- **`CategoryGroup` deliberately has no budget of its own** -- Copilot's
  real app lets a group carry an independent "umbrella" budget that can
  cover unbudgeted categories underneath it, but mixing budgeted and
  unbudgeted categories under one number was judged more confusing than
  it's worth here.
- **A group only gets a `budget`/`status` when EVERY one of its
  categories has a budget set** -- a *partial* group budget (some
  categories opted in, some didn't) would compare the group's full spend
  against an incomplete denominator, making the group look "over budget"
  for reasons that have nothing to do with real overspending. If the
  group isn't fully budgeted, `budget`/`status` are `null` and `spent` is
  just the plain sum of every category in it (so the money's still
  visible, just without a misleading comparison). Note this makes
  `CategoryGroupSpend.spent` unconditional (always every category) unlike
  the top-level `total_spent`, which stays scoped to individually-
  budgeted categories regardless of their group's status -- a category's
  own budget still counts toward the grand total even if a sibling in the
  same group drags that group's own number down to `null`.
- **Budget status** (`under`/`near`/`over`) uses a judgment-call 90%
  threshold for "near" (`NEAR_BUDGET_RATIO` in `category_overview.py`) --
  the reference screenshot's exact color cutoffs aren't fully pinned down
  pixel-by-pixel, so this is a clearly documented choice, not a precise
  reverse-engineering of Copilot's own thresholds. Spending *exactly*
  equal to budget is treated as `under`, not `near` -- confirmed against
  the screenshot, where categories at exactly 100% of budget (Mortgage/
  Rent, Gym) still render fully green, not a warning color.
- **Deleting a group vs. deleting a category behave differently on
  purpose**: deleting a `CategoryGroup` un-groups its categories
  (`group_id -> null`), a low-stakes, reversible change. Deleting a
  `Category` **reassigns** its transactions to the default "Other"
  category instead (see below) rather than blocking or orphaning them --
  every transaction always has a category, so a deleted category can't
  just leave a dangling reference.
- **Found and fixed a real gap while testing this**: SQLite (used by the
  test suite) doesn't enforce `FOREIGN KEY` constraints by default the
  way Postgres does -- without `PRAGMA foreign_keys=ON` (now wired into
  `app/database.py`'s sqlite branch), FK-dependent behavior can silently
  pass in SQLite while only actually being enforced against the real
  Postgres database. Worth remembering any time a test passes
  suspiciously easily.

### Phase 5: Recurrings tab

`RecurringRule` was already modeled in Phase 1 but had no router and
nothing ever set `Transaction.recurring_rule_id`/`is_recurring` -- this
phase is the actual matching engine plus CRUD, and it's also where the
`Transaction.name`/`display_name` split was introduced.

Endpoints added:
- `POST /recurring`, `GET /recurring`, `GET /recurring/{id}`,
  `PATCH /recurring/{id}`, `DELETE /recurring/{id}` -- RecurringRule CRUD.
- `GET /transactions?search=` -- new filter, matches against
  `display_name` OR the original `name` OR the linked category's name
  (see the display_name design note below for why all three).

**`Transaction.name` vs `Transaction.display_name`:** `name` is the
original text synced from Plaid (or typed for a manual entry) and is
never touched by matching. `display_name` is what every list/search view
should render -- it defaults to `name`, but gets overwritten to the
linked `RecurringRule.name` once matched (`app/services/recurring_matching.py`),
e.g. a transaction named "Zelle payment to GOLD PROPERTIES LLC" displays
as "Chicago Rent". `GET /transactions/{id}` (a single-transaction detail
view) is the one place that still shows the original `name`. This is why
search checks all three fields: searching "zelle" still finds the
relabeled rent transaction (its `name` still has it), and searching
"rent" finds transactions filed under a Rent/Mortgage category even when
neither name field says "rent".

**Matching is name-pattern + amount-range only (v1 scope) --
`expected_day_of_period`/`expected_date_tolerance_days` are NOT used by
the matcher.** Those two fields can't cleanly generalize across every
`RecurringFrequency` as currently stored (no month for `yearly`,
ambiguous for `weekly`) -- they're kept on the model for a future
"predicted next due date"/overdue-bill feature, not dead columns. If a
transaction could match more than one rule, the earliest-created rule
wins; there's no explicit priority field yet.

Where matching runs (`app/services/recurring_matching.py`):
- **Manual creation** (`POST /transactions/manual`) -- auto-matches
  against existing rules unless an explicit `recurring_rule_id` is given.
- **Plaid sync** -- every newly `added` transaction is matched at
  creation; a `modified` transaction gets a second matching attempt (only
  if still unlinked) since Plaid sometimes cleans up merchant text
  between the pending and posted versions of the same transaction.
- **Creating a rule** always retroactively matches existing unmatched
  transactions -- setting up "Chicago Rent" today also relabels past
  occurrences, not just future ones. No opt-out on create, matching
  Copilot's own creation flow; an unwanted individual match can still be
  unlinked afterward via `PATCH /transactions/{id}` with
  `recurring_rule_id: null`.
- **Renaming a rule** (`PATCH /recurring/{id}` with a new `name`)
  propagates to every transaction already linked to it regardless of
  `apply_to_existing` below (renaming just keeps an existing label in
  sync, it isn't "matching more transactions"), and re-attempts
  retroactive matching if a matching-relevant field changed too (the new
  pattern/amount range might now catch transactions that didn't match
  before).
- **`apply_to_existing`** (`PATCH /recurring/{id}` only, default `true`)
  -- mirrors Copilot's own "Recurring Filter Changes" modal ("Only for
  future payments" vs "Also recalculate previous payments"), which only
  ever appears on the edit flow, not creation. `false` skips the
  retroactive scan: only transactions created/synced *after* the update
  will auto-match under the new criteria; anything already unmatched
  stays that way unless linked manually. Not a stored column -- it's a
  one-time request directive, stripped out before updating the
  `RecurringRule` row. The retroactive scan (and hence this flag) is
  skipped entirely unless the request actually touches a matching-
  relevant field (`name_pattern`, `amount_min`, `amount_max`,
  `name_match_type`) -- there's nothing to recalculate from e.g. toggling
  `is_shared` alone.
- **`PATCH /transactions/{id}`** accepts `recurring_rule_id` directly too
  -- setting it 404s on an unknown rule then links + sets the alias;
  explicitly clearing it (`null`) unlinks and resets `display_name` back
  to the original `name`.
- **Deleting a rule** unlinks its transactions (`recurring_rule_id` ->
  `null`, `is_recurring` -> `false`, `display_name` reset to `name`)
  rather than blocking or leaving a dangling reference -- same reasoning
  as Category's delete-reassigns-to-Other and CategoryGroup's
  delete-ungroups.

**Also shipped alongside this phase:** Zelle transactions are now always
classified `regular` (`app/services/transaction_sync.py::_classify_type`),
regardless of what Plaid's `personal_finance_category` says. Plaid tags
Zelle the same `TRANSFER_IN`/`TRANSFER_OUT` category as an actual
internal transfer, but in this household Zelle is only ever used to pay
someone back or buy something secondhand -- never a transfer between the
household's own accounts.

### Design note: Shared Expenses tab (Phase 6, not yet built)

Planned to sit entirely on top of Phase 5 without touching Phases 1-5's
code: `Account.is_shared` (new column), plus a settlement service that
sums a month's shared transactions and applies a fixed household split.
A transaction counts toward the split when:

```
account.is_shared AND (
    transaction_type == "regular"
    OR (is_recurring AND recurring_rule.is_shared)
)
```

Everything on a shared account (e.g. the joint credit card, joint
checking) counts by default except transfers/income; a
`RecurringRule.is_shared` rule force-includes its matches (rent,
insurance, internet) even when Plaid would otherwise classify them as a
transfer. `RecurringRule.is_shared` was added in this phase's migration
specifically so Phase 6 doesn't need one of its own just for that flag.

### Every transaction always has a category ("Other")

Added after Phase 4 initially shipped, once real usage surfaced the need:
`Transaction.category_id` is now `NOT NULL` at the DB level, and exactly
one `Category` row has `is_default=True` -- seeded by migration
`8d3bb1fb63ef` (a genuine *data* migration, not just schema: it also
backfills any pre-existing transaction with a null `category_id`, in the
correct order relative to the `NOT NULL` constraint being added).
`app/services/default_category.py` is the one place that looks this row
up (`Category.is_default.is_(True)`).

- **Manual creation** (`POST /transactions/manual`) falls back to
  "Other" when `category_id` is omitted; explicitly providing an unknown
  id 404s.
- **`PATCH`** treats an explicit `category_id: null` as "reset to
  Other," not "clear it" -- the column can never actually be null.
- **Plaid sync** (`transaction_sync.py`) assigns every newly-synced
  transaction to "Other" too -- Plaid's own category isn't mapped to
  ours (Categories is entirely user-managed), so there's nothing more
  specific to assign yet.
- **Deleting a category** reassigns every transaction pointing at it to
  "Other" first, then deletes it. "Other" itself can never be deleted
  (`is_default=True` is checked before any delete) -- it has to always
  exist, since it's the reassignment target.
- **`GET /transactions?category_id=...`** -- new filter, useful on its
  own and specifically for a future category-detail view (matching
  `category-overview.png`'s "TRANSACTIONS" list) -- composes with the
  existing `start_date`/`end_date` filters for "transactions in category
  X during month Y."
- Local test fixtures (`tests/conftest.py`) seed this same "Other" row
  by hand after `Base.metadata.create_all()`, since that path builds the
  schema straight from the models and never runs the Alembic migration
  that seeds it for real environments.

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
