from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "0014_repair_taxonomy_reporting.sql"
)


def test_reporting_repair_is_transactional_and_data_driven() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert sql.lstrip().startswith("-- keep review-state")
    assert "\nbegin;\n" in sql
    assert sql.rstrip().endswith("commit;")
    assert "create temporary table taxonomy_v2_item_repairs" in sql
    assert "owner_user_id" not in sql
    assert "classification_source = 'migration'" in sql
    assert "classification_review_status = 'reviewed'" in sql


def test_reporting_repair_covers_known_unclassified_grocery_items() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    expected_targets = {
        "food_dining.groceries.meat_seafood_alternatives.plant_proteins.tofu_tempeh",
        "food_dining.groceries.produce.vegetables.squash_gourds",
        "food_dining.groceries.produce.vegetables.nightshades.peppers",
        "food_dining.groceries.frozen_food.ice_cream_desserts",
        "food_dining.groceries.dairy_eggs.cheese.fresh_soft",
        "food_dining.groceries.pantry_cooking.canned_jarred",
        "food_dining.groceries.pantry_cooking.baking_ingredients",
    }

    for stable_key in expected_targets:
        assert stable_key in sql

    assert "user_product_aliases" in sql
    assert "product_concepts" in sql
    assert "validation_issues" in sql
