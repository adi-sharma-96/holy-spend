create extension if not exists pgcrypto;

create type transaction_status as enum ('draft', 'confirmed', 'void');
create type transaction_type as enum ('expense', 'refund', 'income', 'transfer');
create type source_type as enum ('receipt', 'manual', 'email', 'instacart', 'uber_eats', 'import');
create type adjustment_type as enum ('coupon', 'discount', 'tax', 'fee', 'deposit', 'refund', 'rounding');
create type validation_severity as enum ('info', 'warning', 'blocking');
create type alias_source as enum ('user_merchant', 'user_global', 'curated_global');

create table profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    display_name text,
    default_currency char(3) not null default 'USD',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint profiles_default_currency_uppercase check (default_currency = upper(default_currency))
);

create table categories (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    parent_id uuid references categories(id) on delete restrict,
    name text not null,
    depth integer not null,
    path_slug text not null unique,
    sort_order integer not null default 0,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint categories_slug_format check (slug ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'),
    constraint categories_depth_nonnegative check (depth >= 0)
);

create index categories_parent_id_idx on categories(parent_id);
create index categories_active_path_idx on categories(path_slug) where is_active = true;

create table themes (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    name text not null,
    description text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint themes_slug_format check (slug ~ '^[a-z0-9]+([_-][a-z0-9]+)*$')
);

create table merchants (
    id uuid primary key default gen_random_uuid(),
    owner_user_id uuid references auth.users(id) on delete cascade,
    canonical_name text not null,
    normalized_name text not null,
    website text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint merchants_normalized_name_not_blank check (length(trim(normalized_name)) > 0)
);

create unique index merchants_global_normalized_unique
    on merchants(normalized_name)
    where owner_user_id is null;

create unique index merchants_user_normalized_unique
    on merchants(owner_user_id, normalized_name)
    where owner_user_id is not null;

create table product_concepts (
    id uuid primary key default gen_random_uuid(),
    owner_user_id uuid references auth.users(id) on delete cascade,
    slug text,
    canonical_name text not null,
    primary_category_id uuid not null references categories(id) on delete restrict,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint product_concepts_slug_format check (
        slug is null or slug ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'
    )
);

create unique index product_concepts_global_slug_unique
    on product_concepts(slug)
    where owner_user_id is null and slug is not null;

create unique index product_concepts_user_slug_unique
    on product_concepts(owner_user_id, slug)
    where owner_user_id is not null and slug is not null;

create index product_concepts_category_idx on product_concepts(primary_category_id);
create index product_concepts_owner_idx on product_concepts(owner_user_id);

create table product_variants (
    id uuid primary key default gen_random_uuid(),
    owner_user_id uuid references auth.users(id) on delete cascade,
    concept_id uuid not null references product_concepts(id) on delete restrict,
    canonical_name text not null,
    brand text,
    size_text text,
    attributes jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index product_variants_concept_idx on product_variants(concept_id);
create index product_variants_owner_idx on product_variants(owner_user_id);

create table product_concept_themes (
    concept_id uuid not null references product_concepts(id) on delete cascade,
    theme_id uuid not null references themes(id) on delete restrict,
    primary key (concept_id, theme_id)
);

create table product_variant_themes (
    variant_id uuid not null references product_variants(id) on delete cascade,
    theme_id uuid not null references themes(id) on delete restrict,
    primary key (variant_id, theme_id)
);

create table transactions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    transaction_type transaction_type not null,
    source_type source_type not null,
    status transaction_status not null default 'draft',
    transaction_date date not null,
    merchant_id uuid references merchants(id) on delete restrict,
    merchant_name_raw text,
    merchant_name_normalized text,
    currency char(3) not null,
    subtotal_amount numeric(12, 2),
    tax_amount numeric(12, 2),
    fee_amount numeric(12, 2),
    discount_amount numeric(12, 2),
    total_amount numeric(12, 2) not null,
    reconciliation_delta_amount numeric(12, 2),
    confirmed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint transactions_currency_uppercase check (currency = upper(currency)),
    constraint transactions_confirmed_at_status check (
        (status = 'confirmed' and confirmed_at is not null)
        or (status <> 'confirmed')
    ),
    constraint transactions_merchant_present check (
        merchant_id is not null or merchant_name_raw is not null or source_type = 'manual'
    )
);

create index transactions_user_status_date_idx
    on transactions(user_id, status, transaction_date desc);

create index transactions_confirmed_user_date_idx
    on transactions(user_id, transaction_date desc)
    where status = 'confirmed';

create index transactions_user_merchant_name_idx
    on transactions(user_id, merchant_name_normalized);

create index transactions_merchant_id_idx on transactions(merchant_id);

create table receipts (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    transaction_id uuid not null unique references transactions(id) on delete cascade,
    receipt_date date,
    receipt_number text,
    raw_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index receipts_user_idx on receipts(user_id);

create table receipt_files (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    receipt_id uuid not null references receipts(id) on delete cascade,
    object_key text not null unique,
    filename text not null,
    mime_type text not null,
    byte_size bigint,
    sha256 text,
    uploaded_at timestamptz not null default now(),
    constraint receipt_files_byte_size_positive check (byte_size is null or byte_size >= 0),
    constraint receipt_files_sha256_format check (sha256 is null or sha256 ~ '^[a-f0-9]{64}$')
);

create index receipt_files_user_receipt_idx on receipt_files(user_id, receipt_id);

create table transaction_items (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    transaction_id uuid not null references transactions(id) on delete cascade,
    raw_name text,
    interpreted_name text,
    normalized_name text,
    concept_id uuid references product_concepts(id) on delete restrict,
    variant_id uuid references product_variants(id) on delete restrict,
    category_id uuid not null references categories(id) on delete restrict,
    quantity numeric(14, 4),
    unit text,
    unit_price_amount numeric(12, 4),
    line_subtotal_amount numeric(12, 2),
    line_discount_amount numeric(12, 2),
    line_tax_amount numeric(12, 2),
    line_fee_amount numeric(12, 2),
    line_total_amount numeric(12, 2) not null,
    confidence numeric(5, 4),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint transaction_items_quantity_nonnegative check (quantity is null or quantity >= 0),
    constraint transaction_items_confidence_range check (
        confidence is null or (confidence >= 0 and confidence <= 1)
    ),
    constraint transaction_items_name_present check (
        raw_name is not null or interpreted_name is not null or normalized_name is not null
    )
);

create index transaction_items_user_transaction_idx on transaction_items(user_id, transaction_id);
create index transaction_items_category_idx on transaction_items(category_id);
create index transaction_items_concept_idx on transaction_items(concept_id);
create index transaction_items_variant_idx on transaction_items(variant_id);

create table transaction_item_themes (
    user_id uuid not null references auth.users(id) on delete cascade,
    item_id uuid not null references transaction_items(id) on delete cascade,
    theme_id uuid not null references themes(id) on delete restrict,
    primary key (item_id, theme_id)
);

create index transaction_item_themes_user_theme_idx
    on transaction_item_themes(user_id, theme_id, item_id);

create table transaction_adjustments (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    transaction_id uuid not null references transactions(id) on delete cascade,
    item_id uuid references transaction_items(id) on delete cascade,
    type adjustment_type not null,
    amount numeric(12, 2) not null,
    description text,
    created_at timestamptz not null default now()
);

create index transaction_adjustments_user_transaction_idx
    on transaction_adjustments(user_id, transaction_id);

create index transaction_adjustments_item_idx on transaction_adjustments(item_id);

create table user_product_aliases (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    merchant_id uuid references merchants(id) on delete restrict,
    merchant_normalized text,
    raw_name_normalized text not null,
    concept_id uuid references product_concepts(id) on delete restrict,
    variant_id uuid references product_variants(id) on delete restrict,
    category_id uuid references categories(id) on delete restrict,
    source alias_source not null,
    confidence numeric(5, 4),
    confirmed_count integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint user_product_aliases_confidence_range check (
        confidence is null or (confidence >= 0 and confidence <= 1)
    ),
    constraint user_product_aliases_target_present check (
        concept_id is not null or variant_id is not null or category_id is not null
    )
);

create unique index user_product_aliases_user_merchant_id_name_unique
    on user_product_aliases(user_id, merchant_id, raw_name_normalized)
    where merchant_id is not null;

create unique index user_product_aliases_user_merchant_text_name_unique
    on user_product_aliases(user_id, merchant_normalized, raw_name_normalized)
    where merchant_id is null and merchant_normalized is not null;

create unique index user_product_aliases_user_global_name_unique
    on user_product_aliases(user_id, raw_name_normalized)
    where merchant_id is null and merchant_normalized is null;

create index user_product_aliases_lookup_idx
    on user_product_aliases(user_id, raw_name_normalized, merchant_id);

create table validation_issues (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    transaction_id uuid not null references transactions(id) on delete cascade,
    item_id uuid references transaction_items(id) on delete cascade,
    severity validation_severity not null,
    code text not null,
    message text not null,
    metadata jsonb not null default '{}'::jsonb,
    resolved_at timestamptz,
    created_at timestamptz not null default now()
);

create index validation_issues_user_transaction_idx
    on validation_issues(user_id, transaction_id, severity);

create table user_corrections (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    transaction_id uuid not null references transactions(id) on delete cascade,
    item_id uuid references transaction_items(id) on delete cascade,
    field_name text not null,
    old_value jsonb,
    new_value jsonb,
    accepted_as_alias boolean not null default false,
    created_at timestamptz not null default now()
);

create index user_corrections_user_transaction_idx
    on user_corrections(user_id, transaction_id);

create table audit_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    entity_type text not null,
    entity_id uuid not null,
    action text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index audit_events_user_entity_idx on audit_events(user_id, entity_type, entity_id);
create index audit_events_user_created_idx on audit_events(user_id, created_at desc);

create table personal_access_tokens (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    token_hash text not null unique,
    name text not null,
    scopes text[] not null default array[]::text[],
    last_used_at timestamptz,
    expires_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz not null default now()
);

create index personal_access_tokens_user_idx on personal_access_tokens(user_id);

create function set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger profiles_set_updated_at
    before update on profiles
    for each row execute function set_updated_at();

create trigger categories_set_updated_at
    before update on categories
    for each row execute function set_updated_at();

create trigger themes_set_updated_at
    before update on themes
    for each row execute function set_updated_at();

create trigger merchants_set_updated_at
    before update on merchants
    for each row execute function set_updated_at();

create trigger product_concepts_set_updated_at
    before update on product_concepts
    for each row execute function set_updated_at();

create trigger product_variants_set_updated_at
    before update on product_variants
    for each row execute function set_updated_at();

create trigger transactions_set_updated_at
    before update on transactions
    for each row execute function set_updated_at();

create trigger receipts_set_updated_at
    before update on receipts
    for each row execute function set_updated_at();

create trigger transaction_items_set_updated_at
    before update on transaction_items
    for each row execute function set_updated_at();

create trigger user_product_aliases_set_updated_at
    before update on user_product_aliases
    for each row execute function set_updated_at();

create function assert_category_depth()
returns trigger
language plpgsql
as $$
declare
    parent_depth integer;
begin
    if new.parent_id is null then
        if new.depth <> 0 then
            raise exception 'Root category depth must be 0';
        end if;
    else
        select depth into parent_depth from categories where id = new.parent_id;
        if parent_depth is null then
            raise exception 'Parent category does not exist';
        end if;
        if new.depth <> parent_depth + 1 then
            raise exception 'Category depth must equal parent depth + 1';
        end if;
    end if;
    return new;
end;
$$;

create trigger categories_assert_depth
    before insert or update of parent_id, depth on categories
    for each row execute function assert_category_depth();

create function assert_receipt_user_matches_transaction()
returns trigger
language plpgsql
as $$
begin
    if not exists (
        select 1 from transactions
        where id = new.transaction_id and user_id = new.user_id
    ) then
        raise exception 'Receipt user_id must match parent transaction user_id';
    end if;
    return new;
end;
$$;

create trigger receipts_assert_user_matches_transaction
    before insert or update of user_id, transaction_id on receipts
    for each row execute function assert_receipt_user_matches_transaction();

create function assert_receipt_file_user_matches_receipt()
returns trigger
language plpgsql
as $$
begin
    if not exists (
        select 1 from receipts
        where id = new.receipt_id and user_id = new.user_id
    ) then
        raise exception 'Receipt file user_id must match receipt user_id';
    end if;
    return new;
end;
$$;

create trigger receipt_files_assert_user_matches_receipt
    before insert or update of user_id, receipt_id on receipt_files
    for each row execute function assert_receipt_file_user_matches_receipt();

create function assert_item_user_matches_transaction()
returns trigger
language plpgsql
as $$
begin
    if not exists (
        select 1 from transactions
        where id = new.transaction_id and user_id = new.user_id
    ) then
        raise exception 'Item user_id must match parent transaction user_id';
    end if;
    return new;
end;
$$;

create trigger transaction_items_assert_user_matches_transaction
    before insert or update of user_id, transaction_id on transaction_items
    for each row execute function assert_item_user_matches_transaction();

create function assert_item_theme_user_matches_item()
returns trigger
language plpgsql
as $$
begin
    if not exists (
        select 1 from transaction_items
        where id = new.item_id and user_id = new.user_id
    ) then
        raise exception 'Item theme user_id must match item user_id';
    end if;
    return new;
end;
$$;

create trigger transaction_item_themes_assert_user_matches_item
    before insert or update of user_id, item_id on transaction_item_themes
    for each row execute function assert_item_theme_user_matches_item();

create function assert_adjustment_user_matches_transaction_and_item()
returns trigger
language plpgsql
as $$
begin
    if not exists (
        select 1 from transactions
        where id = new.transaction_id and user_id = new.user_id
    ) then
        raise exception 'Adjustment user_id must match parent transaction user_id';
    end if;

    if new.item_id is not null and not exists (
        select 1 from transaction_items
        where id = new.item_id
          and transaction_id = new.transaction_id
          and user_id = new.user_id
    ) then
        raise exception 'Adjustment item_id must belong to the same transaction and user';
    end if;

    return new;
end;
$$;

create trigger transaction_adjustments_assert_user_matches_parent
    before insert or update of user_id, transaction_id, item_id on transaction_adjustments
    for each row execute function assert_adjustment_user_matches_transaction_and_item();

create function assert_issue_user_matches_parent()
returns trigger
language plpgsql
as $$
begin
    if not exists (
        select 1 from transactions
        where id = new.transaction_id and user_id = new.user_id
    ) then
        raise exception 'Validation issue user_id must match parent transaction user_id';
    end if;

    if new.item_id is not null and not exists (
        select 1 from transaction_items
        where id = new.item_id
          and transaction_id = new.transaction_id
          and user_id = new.user_id
    ) then
        raise exception 'Validation issue item_id must belong to the same transaction and user';
    end if;

    return new;
end;
$$;

create trigger validation_issues_assert_user_matches_parent
    before insert or update of user_id, transaction_id, item_id on validation_issues
    for each row execute function assert_issue_user_matches_parent();

create function assert_correction_user_matches_parent()
returns trigger
language plpgsql
as $$
begin
    if not exists (
        select 1 from transactions
        where id = new.transaction_id and user_id = new.user_id
    ) then
        raise exception 'Correction user_id must match parent transaction user_id';
    end if;

    if new.item_id is not null and not exists (
        select 1 from transaction_items
        where id = new.item_id
          and transaction_id = new.transaction_id
          and user_id = new.user_id
    ) then
        raise exception 'Correction item_id must belong to the same transaction and user';
    end if;

    return new;
end;
$$;

create trigger user_corrections_assert_user_matches_parent
    before insert or update of user_id, transaction_id, item_id on user_corrections
    for each row execute function assert_correction_user_matches_parent();

create function assert_variant_owner_matches_concept()
returns trigger
language plpgsql
as $$
declare
    concept_owner uuid;
begin
    select owner_user_id into concept_owner from product_concepts where id = new.concept_id;
    if concept_owner is not null and concept_owner is distinct from new.owner_user_id then
        raise exception 'Variant owner_user_id must match user-owned concept owner_user_id';
    end if;
    return new;
end;
$$;

create trigger product_variants_assert_owner_matches_concept
    before insert or update of owner_user_id, concept_id on product_variants
    for each row execute function assert_variant_owner_matches_concept();

create function assert_alias_resolution_order_shape()
returns trigger
language plpgsql
as $$
begin
    if new.source = 'user_merchant' and new.merchant_id is null and new.merchant_normalized is null then
        raise exception 'Merchant alias must include merchant_id or merchant_normalized';
    end if;

    if new.source = 'user_global' and (new.merchant_id is not null or new.merchant_normalized is not null) then
        raise exception 'User-global alias must not include merchant fields';
    end if;

    return new;
end;
$$;

create trigger user_product_aliases_assert_resolution_shape
    before insert or update of source, merchant_id, merchant_normalized on user_product_aliases
    for each row execute function assert_alias_resolution_order_shape();
