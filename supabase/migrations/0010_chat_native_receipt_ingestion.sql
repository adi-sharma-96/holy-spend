alter table transaction_adjustments
    add column subtype text,
    add column raw_label text,
    add column affects_total boolean not null default true,
    add column metadata jsonb not null default '{}'::jsonb,
    add constraint transaction_adjustments_metadata_object
        check (jsonb_typeof(metadata) = 'object'),
    add constraint transaction_adjustments_subtype_vocabulary
        check (
            subtype is null
            or (
                type = 'fee'
                and subtype in ('bag_fee', 'delivery_fee', 'service_fee', 'other_fee')
            )
            or (
                type in ('coupon', 'discount')
                and subtype in (
                    'membership_benefit',
                    'delivery_discount',
                    'offer',
                    'other_discount'
                )
            )
        );

comment on column transaction_adjustments.subtype is
    'Small controlled vocabulary for consistently useful fee and discount distinctions.';
comment on column transaction_adjustments.raw_label is
    'Exact printed receipt wording when available.';
comment on column transaction_adjustments.affects_total is
    'False for informational savings that must not participate in charged-total arithmetic.';
comment on column transaction_adjustments.metadata is
    'Optional provider-specific structured detail that does not expand the normalized subtype vocabulary.';

create table receipt_ingestion_requests (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    source_file_id_hash text not null,
    target_identity text not null,
    metadata_fingerprint text not null,
    transaction_id uuid not null references transactions(id) on delete cascade,
    receipt_id uuid not null references receipts(id) on delete cascade,
    receipt_file_id uuid not null references receipt_files(id) on delete cascade,
    created_at timestamptz not null default now(),
    constraint receipt_ingestion_requests_source_hash_shape
        check (source_file_id_hash ~ '^[a-f0-9]{64}$'),
    constraint receipt_ingestion_requests_target_not_blank
        check (length(trim(target_identity)) between 3 and 128),
    constraint receipt_ingestion_requests_metadata_fingerprint_shape
        check (metadata_fingerprint ~ '^[a-f0-9]{64}$'),
    unique (user_id, source_file_id_hash, target_identity)
);

create index receipt_ingestion_requests_transaction_idx
    on receipt_ingestion_requests(user_id, transaction_id);
create index receipt_ingestion_requests_receipt_idx
    on receipt_ingestion_requests(user_id, receipt_id);

alter table receipt_ingestion_requests enable row level security;
alter table receipt_ingestion_requests force row level security;

create policy receipt_ingestion_requests_crud_own on receipt_ingestion_requests
    for all
    using (user_id = app.current_user_id())
    with check (user_id = app.current_user_id());

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'expense_app') then
        grant select, insert, update, delete on table receipt_ingestion_requests to expense_app;
    end if;
end;
$$;
