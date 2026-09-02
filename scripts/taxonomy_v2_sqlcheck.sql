\set ON_ERROR_STOP on

insert into auth.users (id, email)
values ('11111111-1111-4111-8111-111111111111', 'taxonomy-check@example.invalid')
on conflict (id) do nothing;

insert into profiles (id, display_name, default_currency)
values ('11111111-1111-4111-8111-111111111111', 'Taxonomy Check', 'CAD')
on conflict (id) do nothing;

begin;
set local role expense_app;

do $$
begin
    if (select count(*) from taxonomy_nodes) <> 0 then
        raise exception 'Global taxonomy must not be visible without owner context.';
    end if;
end;
$$;

select set_config(
    'app.current_user_id',
    '11111111-1111-4111-8111-111111111111',
    true
);

do $$
begin
    if (select count(*) from taxonomy_versions where status = 'active') <> 1 then
        raise exception 'Exactly one active taxonomy version is required.';
    end if;
    if (select version from taxonomy_versions where status = 'active') <> '2.0.0' then
        raise exception 'Taxonomy version 2.0.0 must be active.';
    end if;
    if (select count(*) from taxonomy_nodes) <> 388 then
        raise exception 'Expected 388 canonical taxonomy nodes.';
    end if;
    if (select count(*) from taxonomy_nodes where is_assignable) <> 319 then
        raise exception 'Expected 319 assignable taxonomy leaves.';
    end if;
    if exists (
        select 1
        from taxonomy_nodes parent
        join taxonomy_nodes child on child.parent_id = parent.id
        where parent.is_assignable
    ) then
        raise exception 'An internal taxonomy node is incorrectly assignable.';
    end if;
    if exists (
        select 1
        from taxonomy_nodes node
        left join taxonomy_node_closure self_path
          on self_path.version_id = node.version_id
         and self_path.ancestor_id = node.id
         and self_path.descendant_id = node.id
         and self_path.distance = 0
        where self_path.ancestor_id is null
    ) then
        raise exception 'Every node must have a zero-distance closure row.';
    end if;
    if exists (
        select 1
        from categories category
        left join legacy_category_taxonomy_map mapping on mapping.category_id = category.id
        where category.is_active and mapping.category_id is null
    ) then
        raise exception 'Every active legacy category must have a v2 mapping.';
    end if;
end;
$$;

insert into transactions (
    id, user_id, transaction_type, source_type, classification_mode,
    ingestion_method, purchase_channel, status, transaction_date,
    merchant_name_raw, currency, subtotal_amount, total_amount
)
values (
    '22222222-2222-4222-8222-222222222222',
    '11111111-1111-4111-8111-111111111111',
    'expense', 'receipt', 'itemized', 'receipt', 'in_store', 'draft',
    current_date, 'Taxonomy Check Market', 'CAD', 3.99, 3.99
);

insert into transaction_items (
    id, user_id, transaction_id, raw_name, interpreted_name, normalized_name,
    taxonomy_node_id, item_role, classification_source,
    classification_confidence, classification_review_status,
    quantity, unit, line_subtotal_amount, line_total_amount
)
select
    '33333333-3333-4333-8333-333333333333',
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
    'APPLES', 'Apples', 'apples',
    node.id, 'purchase', 'model', 0.98, 'suggested',
    1, 'kg', 3.99, 3.99
from taxonomy_nodes node
join taxonomy_versions version on version.id = node.version_id
where version.status = 'active'
  and node.stable_key = 'food_dining.groceries.produce.fruit.apples_pears';

do $$
begin
    if (
        select count(*)
        from transaction_item_classification_history
        where item_id = '33333333-3333-4333-8333-333333333333'
    ) <> 1 then
        raise exception 'Classification history trigger did not record the insert.';
    end if;
end;
$$;

insert into transaction_item_facets (
    user_id, item_id, facet_value_id, source, confidence
)
select
    '11111111-1111-4111-8111-111111111111',
    '33333333-3333-4333-8333-333333333333',
    value.id, 'model', 0.95
from taxonomy_facet_values value
where value.stable_key = 'product_form.fresh';

do $$
begin
    begin
        insert into transaction_item_facets (
            user_id, item_id, facet_value_id, source, confidence
        )
        select
            '11111111-1111-4111-8111-111111111111',
            '33333333-3333-4333-8333-333333333333',
            value.id, 'model', 0.95
        from taxonomy_facet_values value
        where value.stable_key = 'product_form.frozen';
        raise exception 'A second value for a single-select facet was accepted.';
    exception
        when unique_violation then null;
    end;

    begin
        insert into transaction_items (
            id, user_id, transaction_id, raw_name, normalized_name,
            taxonomy_node_id, line_total_amount
        )
        select
            '44444444-4444-4444-8444-444444444444',
            '11111111-1111-4111-8111-111111111111',
            '22222222-2222-4222-8222-222222222222',
            'Invalid internal node', 'invalid internal node',
            node.id, 1
        from taxonomy_nodes node
        where node.stable_key = 'food_dining.groceries';
        raise exception 'An internal taxonomy node was accepted.';
    exception
        when check_violation then null;
    end;

    begin
        insert into transaction_items (
            id, user_id, transaction_id, raw_name, normalized_name,
            taxonomy_node_id, line_total_amount
        )
        select
            '55555555-5555-4555-8555-555555555555',
            '11111111-1111-4111-8111-111111111111',
            '22222222-2222-4222-8222-222222222222',
            'Invalid income leaf', 'invalid income leaf',
            node.id, 1
        from taxonomy_nodes node
        where node.stable_key = 'income.employment';
        raise exception 'An income-only leaf was accepted for an expense.';
    exception
        when check_violation then null;
    end;
end;
$$;

rollback;
