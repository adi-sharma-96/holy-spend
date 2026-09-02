from app.personal_basket import exact_basket_identity


def identity(
    name: str,
    key: str,
    unit: str,
    merchant: str | None,
    brand: str | None = None,
) -> tuple[str, str] | None:
    result = exact_basket_identity(name, brand, key, unit, merchant)
    return (result.key, result.label) if result else None


def test_different_varieties_of_the_same_family_stay_separate() -> None:
    # Unlike Price Watch, which blends every apple variety into "Apples",
    # the basket identity must keep Honeycrisp and Gala as distinct series.
    honeycrisp = identity(
        "honeycrisp apples",
        "food_dining.groceries.produce.fruit.apples_pears",
        "kg",
        "FreshCo",
    )
    gala = identity(
        "gala apples",
        "food_dining.groceries.produce.fruit.apples_pears",
        "kg",
        "FreshCo",
    )
    assert honeycrisp is not None
    assert gala is not None
    assert honeycrisp != gala
    assert honeycrisp == ("honeycrisp-apples@kg@store:freshco", "FreshCo Honeycrisp Apples")


def test_merchant_is_now_part_of_the_identity_key() -> None:
    # This is a deliberate reversal of the old "merchant never affects
    # matching" design: the same product at two different stores is now two
    # separate exact-identity products.
    freshco = identity(
        "honeycrisp apples",
        "food_dining.groceries.produce.fruit.apples_pears",
        "kg",
        "FreshCo",
    )
    no_frills = identity(
        "honeycrisp apples",
        "food_dining.groceries.produce.fruit.apples_pears",
        "kg",
        "No Frills",
    )
    assert freshco is not None
    assert no_frills is not None
    assert freshco[0] != no_frills[0]
    # Produce rarely carries a real manufacturer brand, so the label falls
    # back to the merchant in its place for display consistency (merchant is
    # already unconditionally in the key above, so this doesn't affect
    # grouping, only how the two stay visually distinguishable as labels).
    assert freshco[1] == "FreshCo Honeycrisp Apples"
    assert no_frills[1] == "No Frills Honeycrisp Apples"


def test_missing_merchant_falls_back_to_a_stable_placeholder() -> None:
    result = exact_basket_identity(
        "honeycrisp apples",
        None,
        "food_dining.groceries.produce.fruit.apples_pears",
        "kg",
        None,
    )
    assert result is not None
    assert result.key.endswith("@store:unknown-store")


def test_brand_disambiguates_packaged_goods_when_present() -> None:
    oikos = identity(
        "greek yogurt",
        "food_dining.groceries.dairy_eggs.yogurt_fermented.yogurt",
        "kg",
        "Costco",
        brand="Oikos",
    )
    generic = identity(
        "greek yogurt",
        "food_dining.groceries.dairy_eggs.yogurt_fermented.yogurt",
        "kg",
        "Costco",
    )
    assert oikos is not None
    assert generic is not None
    assert oikos[0] != generic[0]
    assert oikos[1] == "Oikos Greek Yogurt"
    # Unlike produce, an unbranded dairy item's label stays bare — dairy
    # almost always carries a real brand, so a missing one is an ingestion
    # gap to flag/ask about, not something to paper over with the store name.
    assert generic[1] == "Greek Yogurt"


def test_brand_is_not_doubled_when_normalized_name_already_starts_with_it() -> None:
    # normalized_name commonly already has the brand baked in (receipt
    # extraction has no guarantee it's brand-free) - naively prepending
    # produced "Chalo Chalo Unripened Paneer" for a real purchase.
    paneer = identity(
        "Chalo Unripened Paneer",
        "food_dining.groceries.dairy_eggs.cheese.fresh_soft.paneer",
        "kg",
        "FreshCo",
        brand="Chalo",
    )
    assert paneer is not None
    assert paneer[1] == "Chalo Unripened Paneer"


def test_merchant_is_not_doubled_when_produce_name_already_starts_with_it() -> None:
    vegetable = identity(
        "FreshCo Red Onions",
        "food_dining.groceries.produce.vegetables.alliums",
        "kg",
        "FreshCo",
    )
    assert vegetable is not None
    assert vegetable[1] == "Freshco Red Onions"


def test_unbranded_produce_label_falls_back_to_merchant_not_bare_name() -> None:
    vegetable = identity(
        "carrots",
        "food_dining.groceries.produce.vegetables.roots_tubers",
        "kg",
        "No Frills",
    )
    assert vegetable is not None
    assert vegetable == ("carrots@kg@store:no-frills", "No Frills Carrots")


def test_same_exact_product_unit_and_store_share_one_identity() -> None:
    # Name casing is normalized (via .title()); merchant casing is held
    # constant here deliberately — the identity_key itself is
    # merchant-casing-insensitive too (see the placeholder-slug test below),
    # but the display label for unbranded produce now echoes the merchant
    # text as-is, so differently-cased merchant input is a separate, expected
    # source of label variation, not something this test is checking.
    first = identity(
        "honeycrisp apples",
        "food_dining.groceries.produce.fruit.apples_pears",
        "kg",
        "Costco",
    )
    second = identity(
        "Honeycrisp Apples",
        "food_dining.groceries.produce.fruit.apples_pears",
        "kg",
        "Costco",
    )
    assert first == second


def test_merchant_casing_collapses_the_key_but_can_vary_the_produce_label() -> None:
    first = identity(
        "carrots",
        "food_dining.groceries.produce.vegetables.roots_tubers",
        "kg",
        "Costco",
    )
    second = identity(
        "carrots",
        "food_dining.groceries.produce.vegetables.roots_tubers",
        "kg",
        "costco",
    )
    assert first is not None
    assert second is not None
    assert first[0] == second[0] == "carrots@kg@store:costco"


def test_tracking_is_broad_by_design_unlike_price_watchs_curated_staples() -> None:
    # My Inflation deliberately covers any repeat purchase in a trackable
    # category - not just Price Watch's curated commodity staples - so a
    # non-staple item like a chocolate bar is still tracked as long as it's
    # an exact repeat purchase.
    assert (
        exact_basket_identity(
            "kinder bueno chocolate bar",
            None,
            "food_dining.groceries.snacks_confectionery.chocolate",
            "kg",
            "Metro",
        )
        is not None
    )
    # Coffee is still excluded outright, regardless of how broad the general
    # inclusion policy is.
    assert (
        exact_basket_identity(
            "ground coffee",
            None,
            "food_dining.groceries.beverages.coffee",
            "kg",
            "Metro",
        )
        is None
    )


def test_scope_now_matches_price_watchs_broadened_trackable_prefixes() -> None:
    # My Inflation and Deals share one definition of "trackable" — only the
    # grouping granularity differs between them.
    assert (
        exact_basket_identity(
            "charmin toilet paper",
            None,
            "housing_utilities.household_operations.paper_disposables",
            "each",
            "Costco",
        )
        is not None
    )
    assert (
        exact_basket_identity(
            "colgate toothpaste",
            None,
            "personal_care.products.oral",
            "each",
            "Shoppers Drug Mart",
        )
        is not None
    )
    # Durable one-time goods remain out of scope.
    assert (
        exact_basket_identity(
            "dyson cordless vacuum",
            None,
            "shopping_retail.appliances",
            "each",
            "Best Buy",
        )
        is None
    )


def test_missing_name_or_unit_is_rejected() -> None:
    assert (
        exact_basket_identity(
            None,
            None,
            "food_dining.groceries.produce.fruit.apples_pears",
            "kg",
            "FreshCo",
        )
        is None
    )
    assert (
        exact_basket_identity(
            "honeycrisp apples",
            None,
            "food_dining.groceries.produce.fruit.apples_pears",
            None,
            "FreshCo",
        )
        is None
    )
