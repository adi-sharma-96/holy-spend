from app.nutrition_score import compute_nutriscore, default_fvl_percent

GENERAL_CATEGORY = "food_dining.groceries.dairy_eggs"
PRODUCE_CATEGORY = "food_dining.groceries.produce.fruit.apples_pears"
MILK_CATEGORY = "food_dining.groceries.dairy_eggs.milk.cows_milk.fresh_milk"
CHEESE_CATEGORY = "food_dining.groceries.dairy_eggs.cheese.hard_aged.cheddar"
WATER_CATEGORY = "food_dining.groceries.beverages.water"
BEER_CATEGORY = "food_dining.groceries.beverages.beer"
SOFT_DRINK_CATEGORY = "food_dining.groceries.beverages.soft_drinks"
OLIVE_OIL_CATEGORY = "food_dining.groceries.pantry_cooking.oils_vinegars.olive_oil"
BEEF_CATEGORY = "food_dining.groceries.meat_seafood_alternatives.meat_poultry.beef"
CHICKEN_CATEGORY = "food_dining.groceries.meat_seafood_alternatives.meat_poultry.chicken"


def test_clear_a_grade_all_favorable_macros() -> None:
    result = compute_nutriscore(
        category_slug=PRODUCE_CATEGORY,
        energy_kcal_100g=40,
        sugars_100g=2,
        saturated_fat_100g=0,
        sodium_mg_100g=2,
        fiber_100g=6,
        protein_100g=3,
        fvl_percent=None,
    )

    assert result is not None
    assert result.grade == "a"


def test_clear_e_grade_all_unfavorable_macros() -> None:
    result = compute_nutriscore(
        category_slug=GENERAL_CATEGORY,
        energy_kcal_100g=600,
        sugars_100g=60,
        saturated_fat_100g=25,
        sodium_mg_100g=2000,
        fiber_100g=0,
        protein_100g=0,
        fvl_percent=0,
    )

    assert result is not None
    assert result.grade == "e"


def test_missing_required_input_returns_none() -> None:
    result = compute_nutriscore(
        category_slug=GENERAL_CATEGORY,
        energy_kcal_100g=100,
        sugars_100g=5,
        saturated_fat_100g=2,
        sodium_mg_100g=50,
        fiber_100g=None,
        protein_100g=5,
        fvl_percent=None,
    )

    assert result is None


def test_n_at_least_11_excludes_protein_points() -> None:
    result = compute_nutriscore(
        category_slug=GENERAL_CATEGORY,
        energy_kcal_100g=900,
        sugars_100g=20,
        saturated_fat_100g=10,
        sodium_mg_100g=1000,
        fiber_100g=5,
        protein_100g=17,
        fvl_percent=0,
    )

    assert result is not None
    # N = 10 (energy, capped) + 5 (sugar) + 9 (sat fat - the exact table awards 9 not
    # 10 points at exactly 10g: the ">10" step for point 10 isn't met at exactly 10)
    # + 12 (salt) = 36. P excludes protein once N>=11: P = 0 (fvl) + 2 (fiber - the
    # exact table awards 2 not 3 points at 5g fiber) = 2. Score = 36 - 2 = 34, same
    # final answer as the old linear approximation despite both intermediate
    # components differing - a coincidence of this particular input, not a general
    # guarantee.
    assert result.points == 34


def test_produce_category_defaults_high_fvl_without_explicit_percent() -> None:
    produce = compute_nutriscore(
        category_slug=PRODUCE_CATEGORY,
        energy_kcal_100g=50,
        sugars_100g=5,
        saturated_fat_100g=0,
        sodium_mg_100g=2,
        fiber_100g=2,
        protein_100g=1,
        fvl_percent=None,
    )
    other = compute_nutriscore(
        category_slug=GENERAL_CATEGORY,
        energy_kcal_100g=50,
        sugars_100g=5,
        saturated_fat_100g=0,
        sodium_mg_100g=2,
        fiber_100g=2,
        protein_100g=1,
        fvl_percent=None,
    )

    assert produce is not None
    assert other is not None
    assert produce.points < other.points


def test_explicit_fvl_percent_overrides_taxonomy_default() -> None:
    low_fvl = compute_nutriscore(
        category_slug=PRODUCE_CATEGORY,
        energy_kcal_100g=50,
        sugars_100g=5,
        saturated_fat_100g=0,
        sodium_mg_100g=2,
        fiber_100g=2,
        protein_100g=1,
        fvl_percent=10,
    )
    high_fvl = compute_nutriscore(
        category_slug=PRODUCE_CATEGORY,
        energy_kcal_100g=50,
        sugars_100g=5,
        saturated_fat_100g=0,
        sodium_mg_100g=2,
        fiber_100g=2,
        protein_100g=1,
        fvl_percent=95,
    )

    assert low_fvl is not None
    assert high_fvl is not None
    assert high_fvl.points < low_fvl.points


def test_default_fvl_percent_by_category() -> None:
    assert default_fvl_percent(PRODUCE_CATEGORY) == 90.0
    assert default_fvl_percent(GENERAL_CATEGORY) == 0.0


def test_water_is_always_grade_a_without_computation() -> None:
    result = compute_nutriscore(
        category_slug=WATER_CATEGORY,
        energy_kcal_100g=0,
        sugars_100g=0,
        saturated_fat_100g=0,
        sodium_mg_100g=500,  # deliberately unfavorable - must not matter for water
        fiber_100g=0,
        protein_100g=0,
        fvl_percent=None,
    )

    assert result is not None
    assert result.grade == "a"


def test_alcoholic_beverages_are_never_scored() -> None:
    result = compute_nutriscore(
        category_slug=BEER_CATEGORY,
        energy_kcal_100g=40,
        sugars_100g=0,
        saturated_fat_100g=0,
        sodium_mg_100g=5,
        fiber_100g=0,
        protein_100g=0.5,
        fvl_percent=None,
    )

    assert result is None


def test_milk_now_gets_a_real_beverage_grade_instead_of_none() -> None:
    # This is the motivating bug: milk previously fell under BEVERAGE_TAXONOMY_PREFIX
    # ("food_dining.groceries.beverages.*") only by string prefix, but milk actually
    # lives under dairy_eggs.milk.* in this taxonomy - so it silently got scored (or
    # rather, not scored at all) as neither beverage-excluded nor general-food, and
    # the pipeline treated it as "beverage -> always None". Real 2% milk macros
    # (Sealtest, from an actual purchase this session) now produce a real grade.
    result = compute_nutriscore(
        category_slug=MILK_CATEGORY,
        energy_kcal_100g=52,
        sugars_100g=4.4,
        saturated_fat_100g=1.2,
        sodium_mg_100g=42,
        fiber_100g=0,
        protein_100g=3.6,
        fvl_percent=0,
    )

    assert result is not None
    assert result.grade == "b"
    assert result.points == 1


def test_beverage_protein_is_never_excluded_unlike_general_food() -> None:
    # A very unfavorable beverage (N well past what would trigger exclusion in the
    # general-food formula) must still get full protein credit - beverages have no
    # N-based protein exclusion at all, per the 2023 update.
    result = compute_nutriscore(
        category_slug=SOFT_DRINK_CATEGORY,
        energy_kcal_100g=400,
        sugars_100g=12,
        saturated_fat_100g=8,
        sodium_mg_100g=300,
        fiber_100g=0,
        protein_100g=3.5,
        fvl_percent=0,
    )
    assert result is not None
    # protein=3.5 exceeds every beverage protein threshold (max 7 g/100mL tier),
    # so it must contribute the full 7 points to P regardless of how large N is.
    without_protein_credit = compute_nutriscore(
        category_slug=SOFT_DRINK_CATEGORY,
        energy_kcal_100g=400,
        sugars_100g=12,
        saturated_fat_100g=8,
        sodium_mg_100g=300,
        fiber_100g=0,
        protein_100g=0,
        fvl_percent=0,
    )
    assert without_protein_credit is not None
    assert without_protein_credit.points - result.points == 7


def test_non_nutritive_sweetener_adds_a_flat_four_point_penalty() -> None:
    without_sweetener = compute_nutriscore(
        category_slug=SOFT_DRINK_CATEGORY,
        energy_kcal_100g=1,
        sugars_100g=0,
        saturated_fat_100g=0,
        sodium_mg_100g=10,
        fiber_100g=0,
        protein_100g=0,
        fvl_percent=0,
        contains_nonnutritive_sweeteners=False,
    )
    with_sweetener = compute_nutriscore(
        category_slug=SOFT_DRINK_CATEGORY,
        energy_kcal_100g=1,
        sugars_100g=0,
        saturated_fat_100g=0,
        sodium_mg_100g=10,
        fiber_100g=0,
        protein_100g=0,
        fvl_percent=0,
        contains_nonnutritive_sweeteners=True,
    )

    assert without_sweetener is not None
    assert with_sweetener is not None
    assert without_sweetener.points == 0
    assert without_sweetener.grade == "b"
    assert with_sweetener.points == 4
    assert with_sweetener.grade == "c"


def test_cheese_never_excludes_protein_unlike_general_food() -> None:
    # Same macros, only the category differs. Cheese is naturally high in N (mostly
    # from saturated fat), which would normally exclude protein under the general
    # formula - but the Scientific Committee grouped cheese with the
    # protein-always-counted branch specifically because of this.
    cheese = compute_nutriscore(
        category_slug=CHEESE_CATEGORY,
        energy_kcal_100g=350,
        sugars_100g=0,
        saturated_fat_100g=20,
        sodium_mg_100g=800,
        fiber_100g=0,
        protein_100g=25,
        fvl_percent=0,
    )
    general = compute_nutriscore(
        category_slug=GENERAL_CATEGORY,
        energy_kcal_100g=350,
        sugars_100g=0,
        saturated_fat_100g=20,
        sodium_mg_100g=800,
        fiber_100g=0,
        protein_100g=25,
        fvl_percent=0,
    )

    assert cheese is not None
    assert general is not None
    assert general.points == 23  # N=23, protein excluded (N>=11) -> P=0
    assert cheese.points == 16  # same N=23, but protein's 7 points are still credited
    assert cheese.grade == "d"
    assert general.grade == "e"


def test_fats_category_uses_saturated_to_fat_ratio_not_raw_grams() -> None:
    # Olive-oil-like macros: 100g fat, only 14g of it saturated (~14% ratio, a
    # favorable ratio) - the fats-category formula scores the ratio, not the 14g of
    # saturated fat in isolation, which the general-food formula would score harshly
    # (14g saturated fat alone maxes out the general sat-fat table at 10 points).
    result = compute_nutriscore(
        category_slug=OLIVE_OIL_CATEGORY,
        energy_kcal_100g=884,
        sugars_100g=0,
        saturated_fat_100g=14,
        sodium_mg_100g=0,
        fiber_100g=0,
        protein_100g=0,
        fvl_percent=0,
        fat_100g=100,
    )

    assert result is not None
    assert result.points == 5
    assert result.grade == "c"


def test_fats_category_returns_none_without_total_fat() -> None:
    result = compute_nutriscore(
        category_slug=OLIVE_OIL_CATEGORY,
        energy_kcal_100g=884,
        sugars_100g=0,
        saturated_fat_100g=14,
        sodium_mg_100g=0,
        fiber_100g=0,
        protein_100g=0,
        fvl_percent=0,
        fat_100g=None,
    )

    assert result is None


def test_red_meat_protein_points_are_capped_at_two() -> None:
    # protein=25 exceeds every protein threshold -> 7 uncapped points.
    beef = compute_nutriscore(
        category_slug=BEEF_CATEGORY,
        energy_kcal_100g=170,
        sugars_100g=0,
        saturated_fat_100g=4,
        sodium_mg_100g=340,
        fiber_100g=0,
        protein_100g=25,
        fvl_percent=0,
    )
    chicken = compute_nutriscore(
        category_slug=CHICKEN_CATEGORY,
        energy_kcal_100g=170,
        sugars_100g=0,
        saturated_fat_100g=4,
        sodium_mg_100g=340,
        fiber_100g=0,
        protein_100g=25,
        fvl_percent=0,
    )

    assert beef is not None
    assert chicken is not None
    # Same N=9 for both (protein doesn't affect N) - chicken keeps all 7 protein
    # points (P=7, score=2, grade B); beef's protein is capped at 2 (P=2, score=7,
    # grade C), a real letter-grade difference from the cap alone.
    assert chicken.points == 2
    assert chicken.grade == "b"
    assert beef.points == 7
    assert beef.grade == "c"
