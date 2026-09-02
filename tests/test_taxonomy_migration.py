from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "0006_taxonomy_leaf_categories.sql"


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_taxonomy_migration_adds_practical_food_leaves() -> None:
    sql = migration_sql()

    expected_slugs = {
        "grocery.food.sweets_desserts.cookies_biscuits_wafers",
        "grocery.food.sweets_desserts.candy_confectionery",
        "grocery.food.snacks.chips_crackers",
        "grocery.food.beverages.coffee_tea",
        "grocery.food.bakery.bread_buns",
        "grocery.food.meat_seafood_alternatives.plant_based",
    }
    assert all(slug in sql for slug in expected_slugs)


def test_every_internal_branch_gets_an_assignable_fallback() -> None:
    sql = migration_sql()

    assert "parent.slug || '.other'" in sql
    assert "'other ' || parent.name" in sql
    assert "child.parent_id = parent.id" in sql
    assert "set is_assignable = not exists" in sql


def test_category_assignment_is_enforced_across_owned_records() -> None:
    sql = migration_sql()

    assert "create or replace function app.enforce_assignable_category()" in sql
    assert "transaction_items_assignable_category" in sql
    assert "user_product_aliases_assignable_category" in sql
    assert "product_concepts_assignable_category" in sql
    assert "category_assignable is not true" in sql


def test_existing_assignments_are_reclassified_with_history() -> None:
    sql = migration_sql()

    assert "taxonomy_item_reclassifications" in sql
    assert "insert into user_corrections" in sql
    assert "insert into audit_events" in sql
    assert "where change.status = 'confirmed'" in sql
    assert "validation_effect" in sql


def test_chocolate_is_modeled_as_a_cross_cutting_theme() -> None:
    sql = migration_sql()

    assert "values (" in sql
    assert "'chocolate'," in sql
    assert "taxonomy_chocolate_theme_backfills" in sql
    assert "insert into transaction_item_themes" in sql
    assert "'taxonomy_theme_backfilled'" in sql
