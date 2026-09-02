from app.price_watch import _contains_pattern, canonical_price_watch_identity


def identity(name: str, key: str, label: str, unit: str) -> tuple[str, str] | None:
    result = canonical_price_watch_identity(name, key, label, unit)
    return (result.key, result.label) if result else None


def test_grocery_identity_is_the_taxonomy_leaf_directly() -> None:
    # normalized_name text plays no role at all for groceries now — the
    # taxonomy leaf the classifier already assigned *is* the product.
    assert identity(
        "nova red onions",
        "food_dining.groceries.produce.vegetables.alliums.onions",
        "Onions",
        "kg",
    ) == ("product:onions", "Onions")
    assert identity(
        "anything at all, irrelevant",
        "food_dining.groceries.produce.vegetables.alliums.garlic",
        "Garlic",
        "each",
    ) == ("product:garlic", "Garlic")


def test_brand_names_can_never_collide_with_grocery_products_again() -> None:
    # This is the regression test for two real bugs found this session:
    # "Compliments Frozen Butter Croissants" used to match "Limes" because
    # the substring "lime" hides inside "Compliments", and "Butterball"
    # (a turkey brand) used to match "Butter". Both are now structurally
    # impossible for groceries — the classified taxonomy leaf decides the
    # product, never a text search of the name.
    assert identity(
        "Compliments Frozen Butter Croissants",
        "food_dining.groceries.bread_bakery.pastries.croissants",
        "Croissants",
        "kg",
    ) == ("product:croissants", "Croissants")
    assert identity(
        "Butterball Turkey Breast",
        "food_dining.groceries.meat_seafood_alternatives.meat_poultry.turkey",
        "Turkey",
        "kg",
    ) == ("product:turkey", "Turkey")


def test_taxonomy_splits_keep_previously_blended_products_distinct() -> None:
    # Ginger garlic paste is a blended product, not raw ginger or raw
    # garlic — it now has its own taxonomy leaf instead of an app-level
    # name-pattern override.
    assert identity(
        "ching's ginger garlic paste",
        "food_dining.groceries.pantry_cooking.cooking_bases.ginger_garlic_paste",
        "Ginger Garlic Paste",
        "kg",
    ) == ("product:ginger-garlic-paste", "Ginger Garlic Paste")
    assert identity(
        "fresh ginger root",
        "food_dining.groceries.produce.herbs_aromatics.ginger",
        "Ginger",
        "kg",
    ) == ("product:ginger", "Ginger")
    # Different nut types have different price points and are now separate
    # taxonomy leaves rather than one blended "nuts" bucket.
    assert identity(
        "roasted almonds",
        "food_dining.groceries.snacks_confectionery.nuts_seeds.almonds",
        "Almonds",
        "each",
    ) == ("product:almonds", "Almonds")
    assert identity(
        "roasted cashews",
        "food_dining.groceries.snacks_confectionery.nuts_seeds.cashews",
        "Cashews",
        "each",
    ) == ("product:cashews", "Cashews")
    # Rice was already split by grain type in the taxonomy before this
    # session; basmati and sushi rice stay distinct products.
    assert identity(
        "basmati rice",
        "food_dining.groceries.grains_pasta.rice.long_grain",
        "Long-Grain Rice",
        "kg",
    ) == ("product:long-grain-rice", "Long-Grain Rice")
    assert identity(
        "sushi rice",
        "food_dining.groceries.grains_pasta.rice.short_medium_grain",
        "Short & Medium-Grain Rice",
        "kg",
    ) == ("product:short-medium-grain-rice", "Short & Medium-Grain Rice")


def test_excluded_grocery_leaves_return_none_regardless_of_name_or_unit() -> None:
    # Catch-alls (nothing to compare) and recipe/quality-driven categories
    # (a 70%-dark chocolate bar isn't price-comparable to a hazelnut praline
    # bar just because both are "Chocolate") stay out of Deals no matter how
    # deep the taxonomy goes.
    assert identity(
        "kinder bueno chocolate bar",
        "food_dining.groceries.snacks_confectionery.chocolate",
        "Chocolate",
        "kg",
    ) is None
    assert identity(
        "chocolate chip cookies",
        "food_dining.groceries.snacks_confectionery.cookies",
        "Cookies, Biscuits & Wafers",
        "kg",
    ) is None
    assert identity(
        "orville redenbacher popcorn",
        "food_dining.groceries.snacks_confectionery.popcorn",
        "Popcorn",
        "each",
    ) is None
    assert identity(
        "kashmiri mirch",
        "food_dining.groceries.pantry_cooking.spices_seasonings",
        "Spices & Seasonings",
        "each",
    ) is None
    assert identity(
        "assorted canned goods",
        "food_dining.groceries.pantry_cooking.canned_jarred",
        "Canned & Jarred Foods",
        "each",
    ) is None
    assert identity(
        "mixed vegetable tray",
        "food_dining.groceries.produce.vegetables.mixed_vegetables",
        "Mixed & Other Vegetables",
        "kg",
    ) is None
    assert identity(
        "vodka",
        "food_dining.groceries.beverages.spirits",
        "Spirits",
        "each",
    ) is None
    # "Other Tropical Fruit" is a deliberate long-tail catch-all (its own
    # taxonomy synonyms list litchi, lychee, dragon fruit, passion fruit,
    # rambutan together) - real, unrelated fruits with unrelated prices, so
    # it can't be a single comparable product the way "Mangoes" can.
    assert identity(
        "Litchi",
        "food_dining.groceries.produce.fruit.tropical.tropical_other",
        "Other Tropical Fruit",
        "kg",
    ) is None
    assert identity(
        "Indian Amla",
        "food_dining.groceries.produce.fruit.tropical.tropical_other",
        "Other Tropical Fruit",
        "kg",
    ) is None


def test_prepared_food_and_cafe_coffee_stay_excluded_by_taxonomy_key() -> None:
    assert identity(
        "breakfast wrap",
        "food_dining.eating_out.quick_service",
        "Quick-Service Restaurants",
        "kg",
    ) is None
    assert identity(
        "ground coffee",
        "food_dining.groceries.beverages.coffee",
        "Coffee",
        "kg",
    ) is None
    assert identity(
        "chicken pot pie ready meal",
        "food_dining.groceries.prepared_food.ready_meals",
        "Ready Meals",
        "each",
    ) is None


def test_grocery_item_without_a_normalized_unit_is_rejected() -> None:
    assert identity(
        "nova red onions",
        "food_dining.groceries.produce.vegetables.alliums.onions",
        "Onions",
        "",
    ) is None


def test_durable_one_time_goods_are_structurally_excluded() -> None:
    # These categories are never in TRACKABLE_PREFIXES, so nothing can ever
    # make a durable good appear in Deals, regardless of name or unit — this
    # is the "not a vacuum or charger" guarantee.
    assert identity(
        "dyson cordless vacuum",
        "shopping_retail.appliances",
        "Appliances",
        "each",
    ) is None
    assert identity(
        "iphone charger cable",
        "shopping_retail.electronics.accessories",
        "Electronic Accessories",
        "each",
    ) is None
    assert identity(
        "ceramic non-stick frying pan",
        "housing_utilities.furnishings_home_goods.kitchenware",
        "Kitchenware",
        "each",
    ) is None
    assert identity(
        "womens winter coat",
        "shopping_retail.clothing.womens",
        "Women's Clothing",
        "each",
    ) is None


def test_household_operations_still_use_curated_name_patterns() -> None:
    # Household/personal-care/baby/pet/OTC taxonomy is still too shallow for
    # leaf-level granularity, so this track is unchanged from before.
    assert identity(
        "charmin ultra soft toilet paper 12 rolls",
        "housing_utilities.household_operations.paper_disposables",
        "Paper & Disposable Goods",
        "each",
    ) == ("product:toilet-paper", "Toilet paper")
    assert identity(
        "colgate total toothpaste",
        "personal_care.products.oral",
        "Oral Care Products",
        "each",
    ) == ("product:toothpaste", "Toothpaste")
    assert identity(
        "purina dog food 15kg",
        "family_dependants_pets.pets.food",
        "Pet Food",
        "kg",
    ) == ("product:dog-food", "Dog food")
    assert identity(
        "centrum multivitamin",
        "health_wellness.pharmacy.vitamins_supplements",
        "Vitamins & Supplements",
        "each",
    ) == ("product:vitamins", "Vitamins")
    # A household key with no curated pattern match still yields nothing —
    # being in scope doesn't mean every item auto-matches on this track.
    assert identity(
        "generic air care spray",
        "housing_utilities.household_operations.air_care",
        "Air Care",
        "each",
    ) is None


def test_regular_gasoline_is_tracked_but_scoped_away_from_other_grades() -> None:
    # Transportation is outside TRACKABLE_PREFIXES by default (a durable-good
    # / service exclusion) except for personal-vehicle fuel, added because
    # gas is a genuine recurring, price-comparable consumable. Scoped to
    # "regular" specifically so a future premium/mid-grade fill-up doesn't
    # silently blend into the same series - same reasoning as Ibuprofen vs.
    # Acetaminophen above.
    assert identity(
        "Regular gasoline",
        "transportation.personal_vehicle.fuel.gasoline",
        "Gasoline",
        "L",
    ) == ("product:regular-gasoline", "Regular gasoline")
    assert identity(
        "Premium gasoline",
        "transportation.personal_vehicle.fuel.gasoline",
        "Gasoline",
        "L",
    ) is None


def test_word_boundary_matching_used_by_the_household_track() -> None:
    # This is the mechanism that made the mid-word bugs (Compliments/Limes,
    # Butterball/Butter) fixable in the first place — it still backs the
    # household/personal-care text-matching track, which groceries no
    # longer use at all. A left word boundary lets plurals/suffixes still
    # match ("soap" matches "soaps") while refusing a mid-word hit ("soap"
    # must not match "compliments soap-adjacent word" style embedding).
    assert _contains_pattern(" bar soaps on sale ", "bar soap")
    assert not _contains_pattern(" candybar soap on sale ", "bar soap")
    assert _contains_pattern(" apples ", "apple")
