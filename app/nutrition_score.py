"""Deterministic Nutri-Score computation from per-100g (or per-100mL for beverages)
macros, following the real category-specific 2022/2023 Scientific Committee update
algorithms - not a single general-food approximation applied everywhere.

Point tables and formulas below are copied verbatim from the two primary source
reports (not reconstructed or approximated):
  - "Update of the Nutri-Score algorithm" (general foods, fats/oils/nuts/seeds, meat),
    Scientific Committee of the Nutri-Score, voted 2022-06-29.
  - "Update of the Nutri-Score algorithm for beverages" (beverages incl. milk and
    plant-based drinks), Scientific Committee of the Nutri-Score, voted 2023-02-01.

Four distinct scoring paths, selected by category_slug:
  - General foods (default): unfavourable A-points (energy/sugars/sat fat/salt) minus
    favourable C-points (protein/fibre/fruit-veg-legume %), with protein EXCLUDED from
    C whenever A >= 11 (protein "cap" simplification from the 2022 update - no fruit/
    veg exemption to that exclusion any more).
  - Beverages (soft drinks, juice, tea/coffee, and - per the 2023 update - milk,
    plant-based milk, and drinkable fermented dairy): a completely different A/C point
    scale calibrated per-100mL, protein is NEVER excluded from C, non-nutritive
    sweetener presence adds a flat +4 unfavourable points, plain water is always grade
    A without computation, and final letter cutoffs are compressed (B/C/D/E only for
    anything that isn't water).
  - Cheese: uses the exact same general-food point tables, but protein is NEVER
    excluded from C regardless of how high A climbs (cheese is naturally high in A
    points from saturated fat, and the Scientific Committee grouped it with the
    protein-always-counted branch rather than the >=11 exclusion).
  - Fats, oils, nuts and seeds: energy is computed from saturated fat content only
    (kJ = saturated_fat_g * 37), the "saturated fat" unfavourable component is a
    saturated-fat-to-total-fat RATIO (%) instead of raw grams, protein is excluded
    when A >= 7 (not 11), and the final letter cutoffs are shifted deeply negative
    (a very favourable oil like olive oil can and should reach A).
  - Red meat (beef, pork, lamb/goat): general-food formula and cutoffs, but protein
    points are capped at 2 (out of a possible 7) regardless of actual protein content.

Alcoholic beverages (beer, wine, spirits) are outside Nutri-Score's scope entirely
and are never scored, matching the official exclusion.

Caveats:
  - Beverage macros are stored in this app as "per_100g" uniformly (no separate
    per-100mL field), and treated as equivalent to per-100mL here - standard practice
    for liquids (~1g/mL density) and how OFF/USDA data is normally interpreted too.
  - Fruit/veg/legume % (FVL) has no source field in this pipeline; it's either
    caller-supplied (rarely - most sources don't state it) or defaulted from grocery
    taxonomy (produce -> 90%, else 0%). The fats-category-specific FVL credit for
    olive/avocado oil ingredients is not implemented - a caller with real data can
    still supply fvl_percent explicitly.
  - Non-nutritive-sweetener presence defaults to false when not supplied; nothing in
    this pipeline currently infers it from an ingredient list.
"""

from dataclasses import dataclass
from enum import StrEnum

GROCERY_TAXONOMY_PREFIX = "food_dining.groceries."
PRODUCE_TAXONOMY_PREFIX = f"{GROCERY_TAXONOMY_PREFIX}produce"
DEFAULT_FVL_PERCENT_PRODUCE = 90.0
DEFAULT_FVL_PERCENT_OTHER = 0.0

_DAIRY = f"{GROCERY_TAXONOMY_PREFIX}dairy_eggs"
_BEVERAGES = f"{GROCERY_TAXONOMY_PREFIX}beverages"

WATER_TAXONOMY_PREFIX = f"{_BEVERAGES}.water"
ALCOHOLIC_BEVERAGE_PREFIXES = (
    f"{_BEVERAGES}.beer",
    f"{_BEVERAGES}.wine",
    f"{_BEVERAGES}.spirits",
)
BEVERAGE_TAXONOMY_PREFIXES = (
    f"{_BEVERAGES}.coffee",
    f"{_BEVERAGES}.tea",
    f"{_BEVERAGES}.juice",
    f"{_BEVERAGES}.soft_drinks",
    f"{_BEVERAGES}.energy_sports",
    f"{_BEVERAGES}.non_alcoholic",
    f"{_DAIRY}.milk",
    f"{_DAIRY}.dairy_alternatives.plant_milk",
    f"{_DAIRY}.yogurt_fermented.fermented_drinks",
)
CHEESE_TAXONOMY_PREFIX = f"{_DAIRY}.cheese"
FATS_OILS_NUTS_SEEDS_PREFIXES = (
    f"{_DAIRY}.butter_fats",
    f"{_DAIRY}.cream",
    f"{GROCERY_TAXONOMY_PREFIX}pantry_cooking.oils_vinegars.olive_oil",
    f"{GROCERY_TAXONOMY_PREFIX}pantry_cooking.oils_vinegars.cooking_oil",
    f"{GROCERY_TAXONOMY_PREFIX}snacks_confectionery.nuts_seeds",
    f"{GROCERY_TAXONOMY_PREFIX}pantry_cooking.spreads.peanut_butter",
    f"{GROCERY_TAXONOMY_PREFIX}pantry_cooking.spreads.nut_butter",
)
RED_MEAT_TAXONOMY_PREFIXES = (
    f"{GROCERY_TAXONOMY_PREFIX}meat_seafood_alternatives.meat_poultry.beef",
    f"{GROCERY_TAXONOMY_PREFIX}meat_seafood_alternatives.meat_poultry.pork",
    f"{GROCERY_TAXONOMY_PREFIX}meat_seafood_alternatives.meat_poultry.lamb_goat",
)


class NutriScoreCategory(StrEnum):
    GENERAL = "general"
    CHEESE = "cheese"
    BEVERAGE = "beverage"
    WATER = "water"
    FATS_OILS_NUTS_SEEDS = "fats_oils_nuts_seeds"
    EXCLUDED = "excluded"


def classify_category(category_slug: str) -> NutriScoreCategory:
    if any(category_slug.startswith(prefix) for prefix in ALCOHOLIC_BEVERAGE_PREFIXES):
        return NutriScoreCategory.EXCLUDED
    if category_slug.startswith(WATER_TAXONOMY_PREFIX):
        return NutriScoreCategory.WATER
    if any(category_slug.startswith(prefix) for prefix in BEVERAGE_TAXONOMY_PREFIXES):
        return NutriScoreCategory.BEVERAGE
    if category_slug.startswith(CHEESE_TAXONOMY_PREFIX):
        return NutriScoreCategory.CHEESE
    if any(category_slug.startswith(prefix) for prefix in FATS_OILS_NUTS_SEEDS_PREFIXES):
        return NutriScoreCategory.FATS_OILS_NUTS_SEEDS
    return NutriScoreCategory.GENERAL


def _is_red_meat(category_slug: str) -> bool:
    return any(category_slug.startswith(prefix) for prefix in RED_MEAT_TAXONOMY_PREFIXES)


# --- General foods / cheese point tables (also reused by beverages/fats where the
# official tables happen to coincide, e.g. salt) ---
GENERAL_ENERGY_THRESHOLDS_KJ = (335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350)
GENERAL_SUGAR_THRESHOLDS_G = (3.4, 6.8, 10, 14, 17, 20, 24, 27, 31, 34, 37, 41, 44, 48, 51)
GENERAL_SATURATED_FAT_THRESHOLDS_G = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
SALT_THRESHOLDS_G = (
    0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0,
    2.2, 2.4, 2.6, 2.8, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0,
)
GENERAL_PROTEIN_THRESHOLDS_G = (2.4, 4.8, 7.2, 9.6, 12, 14, 17)
GENERAL_FIBER_THRESHOLDS_G = (3.0, 4.1, 5.2, 6.3, 7.4)
RED_MEAT_PROTEIN_POINT_CAP = 2

GENERAL_CUTOFFS = ((1, "a"), (3, "b"), (11, "c"), (19, "d"))

# --- Beverages (per 100mL) ---
BEVERAGE_ENERGY_THRESHOLDS_KJ = (30, 90, 150, 210, 240, 270, 300, 330, 360, 390)
BEVERAGE_SUGAR_THRESHOLDS_G = (0.5, 2, 3.5, 5, 6, 7, 8, 9, 10, 11)
BEVERAGE_PROTEIN_THRESHOLDS_G = (1.2, 1.5, 1.8, 2.1, 2.4, 2.7, 3.0)
BEVERAGE_FIBER_THRESHOLDS_G = (3, 4.1, 5.2, 6.3, 7.4)
NON_NUTRITIVE_SWEETENER_PENALTY = 4
BEVERAGE_CUTOFFS = ((3, "b"), (7, "c"), (10, "d"))  # water is graded "a" separately, never via score

# --- Fats, oils, nuts and seeds ---
FATS_ENERGY_FROM_SATURATES_THRESHOLDS_KJ = (120, 240, 360, 480, 600, 720, 840, 960, 1080, 1200)
FATS_SATURATED_TO_TOTAL_FAT_RATIO_THRESHOLDS_PCT = (10, 16, 22, 28, 34, 40, 46, 52, 58, 64)
FATS_PROTEIN_EXCLUSION_THRESHOLD = 7
FATS_CUTOFFS = ((-5, "a"), (3, "b"), (11, "c"), (19, "d"))


@dataclass(frozen=True)
class NutriScoreResult:
    grade: str
    points: int


def default_fvl_percent(category_slug: str) -> float:
    if category_slug.startswith(PRODUCE_TAXONOMY_PREFIX):
        return DEFAULT_FVL_PERCENT_PRODUCE
    return DEFAULT_FVL_PERCENT_OTHER


def _points_above(value: float, thresholds: tuple[float, ...]) -> int:
    """Count of thresholds value strictly exceeds - the ">threshold" convention used
    by every official table except the fats-category saturated/fat ratio (see below)."""
    return sum(1 for threshold in thresholds if value > threshold)


def _points_at_or_above(value: float, thresholds: tuple[float, ...]) -> int:
    """The fats-category ratio table is phrased as cumulative "<X" bands (0: <10,
    1: <16, ..., 10: >=64), the opposite convention from every other table - a value
    exactly on a boundary belongs to the higher band, not the lower one."""
    return sum(1 for threshold in thresholds if value >= threshold)


def _fvl_points_max5(fvl_percent: float) -> int:
    if fvl_percent > 80:
        return 5
    if fvl_percent > 60:
        return 2
    if fvl_percent > 40:
        return 1
    return 0


def _fvl_points_max6(fvl_percent: float) -> int:
    if fvl_percent > 80:
        return 6
    if fvl_percent > 60:
        return 4
    if fvl_percent > 40:
        return 2
    return 0


def _grade_for_score(score: int, cutoffs: tuple[tuple[int, str], ...]) -> str:
    for cutoff, grade in cutoffs:
        if score < cutoff:
            return grade
    return "e"


def compute_nutriscore(
    *,
    category_slug: str,
    energy_kcal_100g: float | None,
    sugars_100g: float | None,
    saturated_fat_100g: float | None,
    sodium_mg_100g: float | None,
    fiber_100g: float | None,
    protein_100g: float | None,
    fvl_percent: float | None,
    fat_100g: float | None = None,
    contains_nonnutritive_sweeteners: bool = False,
) -> NutriScoreResult | None:
    """Returns None for alcoholic beverages (out of scope), or when a macro required
    by the item's category is missing - never guesses a grade from partial data."""
    category = classify_category(category_slug)
    if category is NutriScoreCategory.EXCLUDED:
        return None
    if category is NutriScoreCategory.WATER:
        return NutriScoreResult(grade="a", points=0)

    required = (energy_kcal_100g, sugars_100g, saturated_fat_100g, sodium_mg_100g, fiber_100g, protein_100g)
    if any(value is None for value in required):
        return None
    assert energy_kcal_100g is not None
    assert sugars_100g is not None
    assert saturated_fat_100g is not None
    assert sodium_mg_100g is not None
    assert fiber_100g is not None
    assert protein_100g is not None

    salt_g = sodium_mg_100g * 2.5 / 1000
    fvl = fvl_percent if fvl_percent is not None else default_fvl_percent(category_slug)

    if category is NutriScoreCategory.BEVERAGE:
        energy_kj = energy_kcal_100g * 4.184
        energy_pts = _points_above(energy_kj, BEVERAGE_ENERGY_THRESHOLDS_KJ)
        sugar_pts = _points_above(sugars_100g, BEVERAGE_SUGAR_THRESHOLDS_G)
        sat_fat_pts = _points_above(saturated_fat_100g, GENERAL_SATURATED_FAT_THRESHOLDS_G)
        salt_pts = _points_above(salt_g, SALT_THRESHOLDS_G)
        sweetener_pts = NON_NUTRITIVE_SWEETENER_PENALTY if contains_nonnutritive_sweeteners else 0
        n = energy_pts + sugar_pts + sat_fat_pts + salt_pts + sweetener_pts

        protein_pts = _points_above(protein_100g, BEVERAGE_PROTEIN_THRESHOLDS_G)
        fiber_pts = _points_above(fiber_100g, BEVERAGE_FIBER_THRESHOLDS_G)
        fvl_pts = _fvl_points_max6(fvl)
        p = protein_pts + fiber_pts + fvl_pts  # protein is never excluded for beverages

        score = n - p
        return NutriScoreResult(grade=_grade_for_score(score, BEVERAGE_CUTOFFS), points=score)

    if category is NutriScoreCategory.FATS_OILS_NUTS_SEEDS:
        if fat_100g is None or fat_100g <= 0:
            return None
        energy_from_saturates_kj = saturated_fat_100g * 37
        energy_pts = _points_above(energy_from_saturates_kj, FATS_ENERGY_FROM_SATURATES_THRESHOLDS_KJ)
        sugar_pts = _points_above(sugars_100g, GENERAL_SUGAR_THRESHOLDS_G)
        ratio_pct = (saturated_fat_100g / fat_100g) * 100
        ratio_pts = _points_at_or_above(ratio_pct, FATS_SATURATED_TO_TOTAL_FAT_RATIO_THRESHOLDS_PCT)
        salt_pts = _points_above(salt_g, SALT_THRESHOLDS_G)
        n = energy_pts + sugar_pts + ratio_pts + salt_pts

        protein_pts = _points_above(protein_100g, GENERAL_PROTEIN_THRESHOLDS_G)
        fiber_pts = _points_above(fiber_100g, GENERAL_FIBER_THRESHOLDS_G)
        fvl_pts = _fvl_points_max5(fvl)
        p = fvl_pts + fiber_pts + (protein_pts if n < FATS_PROTEIN_EXCLUSION_THRESHOLD else 0)

        score = n - p
        return NutriScoreResult(grade=_grade_for_score(score, FATS_CUTOFFS), points=score)

    # General foods and cheese share the same point tables and cutoffs; only the
    # protein-exclusion rule differs (cheese never excludes it).
    energy_kj = energy_kcal_100g * 4.184
    energy_pts = _points_above(energy_kj, GENERAL_ENERGY_THRESHOLDS_KJ)
    sugar_pts = _points_above(sugars_100g, GENERAL_SUGAR_THRESHOLDS_G)
    sat_fat_pts = _points_above(saturated_fat_100g, GENERAL_SATURATED_FAT_THRESHOLDS_G)
    salt_pts = _points_above(salt_g, SALT_THRESHOLDS_G)
    n = energy_pts + sugar_pts + sat_fat_pts + salt_pts

    fiber_pts = _points_above(fiber_100g, GENERAL_FIBER_THRESHOLDS_G)
    protein_pts = _points_above(protein_100g, GENERAL_PROTEIN_THRESHOLDS_G)
    if _is_red_meat(category_slug):
        protein_pts = min(RED_MEAT_PROTEIN_POINT_CAP, protein_pts)
    fvl_pts = _fvl_points_max5(fvl)
    protein_excluded = category is not NutriScoreCategory.CHEESE and n >= 11
    p = fvl_pts + fiber_pts + (0 if protein_excluded else protein_pts)

    score = n - p
    return NutriScoreResult(grade=_grade_for_score(score, GENERAL_CUTOFFS), points=score)
