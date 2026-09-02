from app.nutrition_identity import nutrition_identity_key


def test_combines_slugified_name_and_brand() -> None:
    assert nutrition_identity_key("2% Milk", "Kirkland Signature") == "2-milk::kirkland-signature"


def test_missing_brand_leaves_empty_second_half() -> None:
    assert nutrition_identity_key("Bananas", None) == "bananas::"
    assert nutrition_identity_key("Bananas", "") == "bananas::"


def test_missing_name_leaves_empty_first_half() -> None:
    assert nutrition_identity_key(None, "Kirkland Signature") == "::kirkland-signature"


def test_punctuation_and_multiple_spaces_collapse_to_single_hyphen() -> None:
    assert nutrition_identity_key("Ching's  Ginger & Garlic  Paste", None) == "ching-s-ginger-garlic-paste::"


def test_case_folding() -> None:
    assert nutrition_identity_key("CATELLI Protein+ Pasta", "Catelli") == nutrition_identity_key(
        "catelli protein+ pasta", "CATELLI"
    )


def test_brand_is_ignored_for_produce_category() -> None:
    branded = nutrition_identity_key("Cauliflower", "Dole", "food_dining.groceries.produce")
    unbranded = nutrition_identity_key("Cauliflower", None, "food_dining.groceries.produce")
    assert branded == unbranded == "cauliflower::"


def test_brand_still_matters_outside_produce() -> None:
    branded = nutrition_identity_key("Pasta Sauce", "Classico", "food_dining.groceries.pantry_cooking")
    unbranded = nutrition_identity_key("Pasta Sauce", None, "food_dining.groceries.pantry_cooking")
    assert branded != unbranded
    assert branded == "pasta-sauce::classico"
    assert unbranded == "pasta-sauce::"


def test_produce_brand_blindness_applies_to_deeper_taxonomy_leaves_too() -> None:
    # A leaf like food_dining.groceries.produce.fruit.bananas_plantains.bananas should
    # be treated as produce, not just the exact "food_dining.groceries.produce" slug.
    key = nutrition_identity_key(
        "Bananas", "Dole", "food_dining.groceries.produce.fruit.bananas_plantains.bananas"
    )
    assert key == "bananas::"


def test_matches_the_enqueue_sql_expression_for_representative_inputs() -> None:
    """Parity check against the SQL in NutritionRepository._enqueue_new -
    trim(both '-' from regexp_replace(lower(x), '[^a-z0-9]+', '-', 'g'))."""
    cases = [
        ("Your Fresh Market Red Onions (1.36 kg)", "Your Fresh Market"),
        ("8 = 24 Regular Rolls", "Spongetowels"),
        ("  leading and trailing  ", None),
    ]
    for name, brand in cases:
        key = nutrition_identity_key(name, brand)
        assert not key.startswith("-")
        assert "::" in key
        name_part, brand_part = key.split("::")
        assert not name_part.startswith("-") and not name_part.endswith("-")
        assert not brand_part.startswith("-") and not brand_part.endswith("-")
