alter type adjustment_type add value if not exists 'tip';

alter table transactions
    add column if not exists tip_amount numeric(12, 2),
    add column if not exists deposit_amount numeric(12, 2),
    add column if not exists rounding_amount numeric(12, 2);

alter table transactions
    drop constraint if exists transactions_summary_amounts_nonnegative;

alter table transactions
    add constraint transactions_summary_amounts_nonnegative check (
        (subtotal_amount is null or subtotal_amount >= 0)
        and (tax_amount is null or tax_amount >= 0)
        and (fee_amount is null or fee_amount >= 0)
        and (discount_amount is null or discount_amount >= 0)
        and (tip_amount is null or tip_amount >= 0)
        and (deposit_amount is null or deposit_amount >= 0)
    );

comment on column transactions.subtotal_amount is
    'Printed gross subtotal before transaction summary components are applied.';
comment on column transactions.discount_amount is
    'Printed aggregate discount. Item and adjustment rows may allocate this amount but do not add to it.';
comment on column transactions.tax_amount is
    'Printed aggregate tax. Item and adjustment rows may allocate this amount but do not add to it.';
comment on column transactions.fee_amount is
    'Printed aggregate fee. Item and adjustment rows may allocate this amount but do not add to it.';
comment on column transactions.tip_amount is
    'Printed aggregate gratuity. Item and adjustment rows may allocate this amount but do not add to it.';
comment on column transactions.deposit_amount is
    'Printed aggregate refundable or container deposit. Detail adjustments do not add to it.';
comment on column transactions.rounding_amount is
    'Signed printed cash or receipt rounding component.';
comment on table transaction_adjustments is
    'Breakdown or fallback detail. A matching non-null transaction summary component is authoritative.';
