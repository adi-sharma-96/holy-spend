from pathlib import Path

from app.price_watch import canonical_price_watch_identity
from scripts.compile_taxonomy import load_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_named_fruits_and_yogurt_types_are_distinct_comparison_groups() -> None:
    catalog = load_catalog(ROOT / "taxonomy/v2/taxonomy.yaml")
    nodes = {node.stable_key: node for node in catalog.nodes}
    suffixes = (
        "produce.fruit.tropical.kiwis",
        "produce.fruit.tropical.lychees",
        "produce.fruit.tropical.rambutans",
        "produce.fruit.tropical.dragon_fruit",
        "produce.fruit.tropical.passion_fruit",
        "dairy_eggs.yogurt_fermented.greek_yogurt.plain",
        "dairy_eggs.yogurt_fermented.greek_yogurt.flavoured",
        "dairy_eggs.yogurt_fermented.regular_yogurt.plain",
        "dairy_eggs.yogurt_fermented.regular_yogurt.flavoured",
        "dairy_eggs.yogurt_fermented.dahi",
        "dairy_eggs.yogurt_fermented.skyr",
    )
    identities = set()
    for suffix in suffixes:
        node = nodes[f"food_dining.groceries.{suffix}"]
        assert node.is_assignable
        result = canonical_price_watch_identity("receipt text", node.stable_key, node.name, "kg")
        assert result is not None
        identities.add(result.key)
    assert len(identities) == len(suffixes)


def test_unknown_and_legacy_buckets_never_become_comparison_products() -> None:
    for suffix in (
        "produce.fruit.tropical.tropical_other",
        "dairy_eggs.yogurt_fermented.yogurt",
        "dairy_eggs.yogurt_fermented.greek_yogurt",
        "dairy_eggs.yogurt_fermented.greek_yogurt.unspecified",
        "dairy_eggs.yogurt_fermented.regular_yogurt",
    ):
        assert canonical_price_watch_identity(
            "tempting specific name", f"food_dining.groceries.{suffix}", "Generic bucket", "kg"
        ) is None


def test_upgrade_seeds_the_same_catalog_as_clean_install() -> None:
    migration = (ROOT / "supabase/migrations/0030_specific_fruit_and_yogurt.sql").read_text()
    migration += (ROOT / "supabase/migrations/0034_specific_grains_and_frozen_produce.sql").read_text()
    catalog = load_catalog(ROOT / "taxonomy/v2/taxonomy.yaml")
    assert catalog.content_hash in migration
    for node in catalog.nodes:
        if ".tropical.kiwis" in node.stable_key or ".yogurt_fermented." in node.stable_key:
            assert str(node.id) in migration


def test_mixed_pepper_and_frozen_produce_buckets_are_not_comparable() -> None:
    cases = (
        ("Thai chilli", "produce.vegetables.nightshades.peppers", "Peppers"),
        ("Green bell pepper", "produce.vegetables.nightshades.peppers", "Peppers"),
        ("Mixed berries", "frozen_food.frozen_produce", "Frozen Produce"),
        ("Green peas", "frozen_food.frozen_produce", "Frozen Produce"),
        ("Shredded coconut", "frozen_food.frozen_produce", "Frozen Produce"),
    )
    for name, suffix, label in cases:
        assert canonical_price_watch_identity(
            name, f"food_dining.groceries.{suffix}", label, "kg"
        ) is None
