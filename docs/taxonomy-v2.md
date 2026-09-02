# Taxonomy v2

Taxonomy v2 is the single semantic classification system for receipt line
items, manually entered bills, income, refunds, and money movement. It replaces
hard-coded category lists with one versioned catalog used by Postgres, REST,
MCP, analytics, and the widget.

## Classification model

Every taxonomy path uses the same ordered reporting schema:

1. Domain
2. Group
3. Category
4. Subcategory
5. Class
6. Subclass

Paths may end before level six when no additional distinction is useful. The
six reporting columns are always exposed; unused deeper columns are `null`.
This is deliberate: the system does not duplicate a label or create fake
`General → General → Other` descendants merely to fill columns.

Only semantic leaves are assignable. Internal nodes are for browsing,
filtering, and rollups. Examples:

- `food_dining.groceries.produce.fruit.apples_pears`
- `food_dining.groceries.produce.vegetables.nightshades.tomatoes`
- `food_dining.groceries.dairy_eggs.cheese.fresh_soft`
- `housing_utilities.housing_payments.rent`
- `transportation.personal_vehicle.fuel.gasoline`
- `entertainment_leisure.cinema.admission`
- `income.employment`
- `money_movement.account_transfer`

`unclassified.needs_review` is a blocking temporary leaf.
`unclassified.user_approved_other` is allowed only after the owner deliberately
reviews and accepts that no more specific leaf fits.

## Transaction shape

Classification is attached to `transaction_items`, never directly to the
transaction header:

- `itemized`: one semantic line per purchased product or service;
- `whole_bill`: exactly one semantic line represents a non-itemized bill such
  as rent, home internet, a movie ticket, or a restaurant total;
- `mixed`: itemized lines plus one or more legitimate service lines.

Each line stores the taxonomy version and leaf, role, classification source,
confidence, review status, and optional facet values. Explicit transaction
confirmation marks non-blocking suggested classifications as reviewed while
preserving whether the suggestion came from the model, an alias, migration, or
the owner.

## Facets and origin dimensions

The hierarchy answers **what was purchased**. Orthogonal facets describe
attributes without duplicating branches, including product form, dietary
properties, sourcing, ingredient, sale format, use context, recurrence,
necessity, audience, deal type, fuel grade, and medication access.

Transaction origin is stored separately:

- ingestion method: manual, receipt, email, provider API, or import;
- purchase channel: in store, online, delivery, subscription, or unknown;
- provider key: optional normalized provider identity.

Taxes, fees, tips, deposits, discounts, and informational benefits remain
adjustments. They are not taxonomy categories and are never counted twice.

## Canonical source and generated artifacts

Edit only:

```text
taxonomy/v2/taxonomy.yaml
```

Then regenerate:

```powershell
.\.venv\Scripts\python.exe scripts\compile_taxonomy.py
```

The compiler validates keys, semantic versioning, parent/child depth,
assignability, transaction-type compatibility, facet cardinality, and legacy
mappings. It writes deterministic UUIDv5 identities and a content hash to:

- `taxonomy/v2/taxonomy.generated.json`
- `widget/src/taxonomy.generated.ts`
- `supabase/migrations/0013_taxonomy_v2.sql`

CI and release checks must also run:

```powershell
.\.venv\Scripts\python.exe scripts\compile_taxonomy.py --check
```

Never hand-edit a generated artifact.

## Runtime discovery

REST:

- `GET /v2/taxonomy/manifest`
- `GET /v2/taxonomy/branches/{stable_key}`
- `GET /v2/taxonomy/search?q=...`

MCP:

- `get_taxonomy_manifest`
- `get_taxonomy_branch`
- `search_taxonomy`
- `get_expense_taxonomy` for the complete v2 catalog plus legacy projections

Models and clients should search or browse before assigning a leaf. Stable keys
are persisted; display names are presentation only.

## Analytics

Closure-table rollups support any level from one through six without parsing
strings. Analytics may group or filter by taxonomy ancestor or assignable
leaf, facet value, ingestion method, purchase channel, provider, and legacy
theme during the compatibility period.

Confirmed transactions only are included. Currency remains an implicit
dimension unless a query explicitly filters to one currency.

## Migration and compatibility

Migration `0013_taxonomy_v2.sql`:

- creates the versioned nodes, closure, synonym, redirect, facet, history, and
  item-facet tables;
- backfills existing legacy category and theme data through explicit mappings;
- adds transaction shape and origin fields;
- adds line-level taxonomy, classification, and review fields;
- enforces active assignable leaves, transaction-type compatibility,
  single-select facets, owner scope, RLS, and classification history;
- keeps legacy category/theme reads and request aliases available during the
  compatibility window, but normalizes every accepted write to one v2 node;
  canonical app, MCP, and REST clients emit only v2 keys and facets.

Apply migrations before deploying code that requires them:

```powershell
psql $env:PAT_ADMIN_DATABASE_URL `
  -X `
  -v ON_ERROR_STOP=1 `
  --single-transaction `
  -f "supabase/migrations/0013_taxonomy_v2.sql"
```

Then rerun `supabase/bootstrap/001_runtime_role.sql` with the privileged
database URL. The running service must continue using the restricted
`expense_app` URL.

## Evolution rules

- Never change the meaning of a published stable key.
- Rename display text without changing the key when semantics are unchanged.
- Add new leaves only when they create a useful reporting distinction.
- Use a new semantic taxonomy version plus redirects when meaning or structure
  changes.
- Keep product identity, brand, package size, merchant, and channel out of the
  semantic tree unless they genuinely define what was purchased.
- Do not create a catch-all branch where a precise existing leaf applies.
