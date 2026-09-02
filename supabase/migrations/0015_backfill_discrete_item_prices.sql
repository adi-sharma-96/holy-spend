-- Make existing receipt rows using the common "item/items" unit comparable.
-- New writes are handled by app.measurements; this repairs historical data so
-- repeat purchases become visible in Price Watch immediately after migration.

update transaction_items
set normalized_unit = 'each',
    normalized_unit_price_amount = round(
        (
            abs(
                case
                    when line_subtotal_amount is not null then
                        line_subtotal_amount - coalesce(line_discount_amount, 0)
                    else
                        line_total_amount
                        - coalesce(line_tax_amount, 0)
                        - coalesce(line_fee_amount, 0)
                end
            ) / quantity
        )::numeric,
        6
    )
where normalized_unit_price_amount is null
  and quantity is not null
  and quantity > 0
  and lower(trim(coalesce(unit, ''))) in ('item', 'items');
