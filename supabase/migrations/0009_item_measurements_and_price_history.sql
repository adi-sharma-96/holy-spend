alter table transaction_items
    add column measured_value numeric(14, 4),
    add column measured_unit text,
    add column package_value numeric(14, 4),
    add column package_unit text,
    add column unit_price_basis_value numeric(14, 4),
    add column unit_price_basis_unit text,
    add column normalized_unit text,
    add column normalized_unit_price_amount numeric(14, 6);

alter table transaction_items
    add constraint transaction_items_measured_value_positive
        check (measured_value is null or measured_value > 0),
    add constraint transaction_items_measured_pair
        check ((measured_value is null) = (measured_unit is null)),
    add constraint transaction_items_package_value_positive
        check (package_value is null or package_value > 0),
    add constraint transaction_items_package_pair
        check ((package_value is null) = (package_unit is null)),
    add constraint transaction_items_unit_price_basis_value_positive
        check (unit_price_basis_value is null or unit_price_basis_value > 0),
    add constraint transaction_items_unit_price_basis_pair
        check ((unit_price_basis_value is null) = (unit_price_basis_unit is null)),
    add constraint transaction_items_normalized_price_pair
        check (
            (normalized_unit is null) = (normalized_unit_price_amount is null)
            and (
                normalized_unit_price_amount is null
                or normalized_unit_price_amount >= 0
            )
        );

-- Preserve immediate value from existing receipts where quantity + unit already
-- provide a mass, volume, or discrete basis. A missing unit follows the runtime's
-- conservative per-item default. Package sizes and
-- ambiguous units remain unset until reviewed rather than being guessed.
with comparable_existing_items as (
    select
        id,
        case
            when unit is null then 'each'
            when lower(replace(trim(unit), '.', '')) in
                ('kg', 'kgs', 'kilogram', 'kilograms', 'g', 'gram', 'grams',
                 'lb', 'lbs', 'pound', 'pounds', 'oz', 'ounce', 'ounces')
                then 'kg'
            when lower(replace(trim(unit), '.', '')) in
                ('l', 'liter', 'liters', 'litre', 'litres',
                 'ml', 'milliliter', 'milliliters', 'millilitre', 'millilitres')
                then 'L'
            when lower(replace(trim(unit), '.', '')) in
                ('ea', 'each', 'ct', 'count', 'pc', 'pcs', 'piece', 'pieces', 'unit', 'units')
                then 'each'
        end as target_unit,
        quantity * case
            when unit is null then 1::numeric
            when lower(replace(trim(unit), '.', '')) in ('kg', 'kgs', 'kilogram', 'kilograms')
                then 1::numeric
            when lower(replace(trim(unit), '.', '')) in ('g', 'gram', 'grams')
                then 0.001::numeric
            when lower(replace(trim(unit), '.', '')) in ('lb', 'lbs', 'pound', 'pounds')
                then 0.45359237::numeric
            when lower(replace(trim(unit), '.', '')) in ('oz', 'ounce', 'ounces')
                then 0.028349523125::numeric
            when lower(replace(trim(unit), '.', '')) in ('l', 'liter', 'liters', 'litre', 'litres')
                then 1::numeric
            when lower(replace(trim(unit), '.', '')) in
                ('ml', 'milliliter', 'milliliters', 'millilitre', 'millilitres')
                then 0.001::numeric
            when lower(replace(trim(unit), '.', '')) in
                ('ea', 'each', 'ct', 'count', 'pc', 'pcs', 'piece', 'pieces', 'unit', 'units')
                then 1::numeric
        end as target_quantity,
        abs(
            case
                when line_subtotal_amount is not null
                    then line_subtotal_amount - coalesce(line_discount_amount, 0)
                else line_total_amount
                    - coalesce(line_tax_amount, 0)
                    - coalesce(line_fee_amount, 0)
            end
        ) as paid_amount
    from transaction_items
    where quantity is not null
      and quantity > 0
)
update transaction_items as item
set normalized_unit = candidate.target_unit,
    normalized_unit_price_amount = round(
        candidate.paid_amount / candidate.target_quantity,
        6
    )
from comparable_existing_items as candidate
where item.id = candidate.id
  and candidate.target_unit is not null
  and candidate.target_quantity > 0;

create index transaction_items_user_normalized_price_idx
    on transaction_items(user_id, normalized_unit, normalized_name, updated_at desc)
    where normalized_unit_price_amount is not null;

create index transaction_items_variant_price_idx
    on transaction_items(user_id, variant_id, normalized_unit, updated_at desc)
    where variant_id is not null and normalized_unit_price_amount is not null;

create index transaction_items_concept_price_idx
    on transaction_items(user_id, concept_id, normalized_unit, updated_at desc)
    where concept_id is not null and normalized_unit_price_amount is not null;

comment on column transaction_items.measured_value is
    'Original receipt weight or volume when it differs from quantity/package count.';
comment on column transaction_items.package_value is
    'Size of one repeated package; combine with quantity for normalized price.';
comment on column transaction_items.unit_price_basis_value is
    'Printed receipt price basis, for example 1 with unit lb in $2.99/lb.';
comment on column transaction_items.normalized_unit_price_amount is
    'Server-derived comparable price in normalized_unit; never combine across currency or unit.';
