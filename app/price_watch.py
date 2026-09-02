import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PriceWatchIdentity:
    key: str
    label: str


# Every taxonomy branch that is a recurring, repeat-purchase consumable —
# never a service and never a durable one-time good (electronics, furniture,
# appliances, clothing, kitchenware live outside these prefixes entirely, so
# they can never appear in Deals no matter what matches). This tuple is the
# single source of truth for "trackable" shared by both Price Watch (blended)
# and My Inflation (exact) identity.
TRACKABLE_PREFIXES: tuple[str, ...] = (
    "food_dining.groceries.",
    "housing_utilities.household_operations.",
    "personal_care.products.",
    "family_dependants_pets.children.baby_food_formula",
    "family_dependants_pets.children.diapers_hygiene",
    "family_dependants_pets.pets.food",
    "family_dependants_pets.pets.treats",
    "family_dependants_pets.pets.supplies",
    "health_wellness.pharmacy.otc",
    "health_wellness.pharmacy.first_aid",
    "health_wellness.pharmacy.vitamins_supplements",
    "health_wellness.pharmacy.medical_supplies",
    "transportation.personal_vehicle.fuel",
)

EXCLUDED_KEY_PARTS = (
    ".prepared_food.",
    ".beverages.coffee",
)

# Guards against prepared/eating-out-style items leaking into a trackable
# category by name. Used by the household/personal-care text-matching track
# below and by My Inflation's exact identity (app/personal_basket.py), which
# still relies on normalized_name matching for every category — groceries
# under Deals no longer need this at all (see canonical_price_watch_identity)
# since a real taxonomy leaf can't be fooled by a name the way text search
# could.
EXCLUDED_NAME_WORDS = (
    "coffee",
    "latte",
    "cappuccino",
    "breakfast wrap",
    "sandwich",
)

GROCERY_PREFIX = "food_dining.groceries."

# Grocery leaves that are technically under a trackable prefix but are either
# explicit catch-alls (nothing to compare — "Mixed & Other Fruit" isn't a
# product) or driven by ingredient/recipe quality rather than category:
# "$/kg of chocolate" isn't meaningful across a 70%-dark bar and a hazelnut
# praline bar the way "$/kg of broccoli" is, no matter how deep the taxonomy
# goes. This is the small, stable maintenance surface for Deals now — flag a
# bad bucket here rather than hand-typing every possible product name.
EXCLUDED_TAXONOMY_LEAVES: frozenset[str] = frozenset(
    f"{GROCERY_PREFIX}{suffix}"
    for suffix in (
        "produce.fruit.mixed_fruit",
        "produce.fruit.tropical.tropical_other",
        "produce.fruit.berries.mixed_berries",
        "produce.vegetables.mixed_vegetables",
        "produce.salads_kits",
        "produce.herbs_aromatics.other_herbs",
        "meat_seafood_alternatives.seafood.fish.other_fish",
        "pantry_cooking.spices_seasonings",
        "pantry_cooking.canned_jarred",
        "pantry_cooking.baking_ingredients",
        "snacks_confectionery.chocolate",
        "snacks_confectionery.candy",
        "snacks_confectionery.cookies",
        "snacks_confectionery.popcorn",
        "frozen_food.frozen_meals",
        "frozen_food.frozen_snacks",
        "beverages.spirits",
    )
)

# Parents that were split into real children (see taxonomy/v2/taxonomy.yaml
# and the 0018/0019 backfill migrations) are no longer assignable — but an
# item can still be *sitting* on one if the backfill's regex didn't match it
# (e.g. "acai berry powder" isn't strawberry/blueberry/raspberry/blackberry,
# so it stays on the old "berries" parent). Without this exclusion those
# leftovers would silently re-create the exact "blend non-comparable things"
# bug the split was meant to fix, just relabeled with the parent's generic
# name ("Berries", "Tropical Fruit", "Sauces & Condiments") instead of
# disappearing until backfilled further or a future purchase resolves them
# to a real child.
EXCLUDED_SPLIT_PARENT_LEAVES: frozenset[str] = frozenset(
    f"{GROCERY_PREFIX}{suffix}"
    for suffix in (
        "produce.fruit.apples_pears",
        "produce.fruit.bananas_plantains",
        "produce.fruit.berries",
        "produce.fruit.citrus",
        "produce.fruit.melons",
        "produce.fruit.stone_fruit",
        "produce.fruit.tropical",
        "produce.vegetables.leafy_greens",
        "produce.vegetables.cruciferous",
        "produce.vegetables.roots_tubers",
        "produce.vegetables.potatoes",
        "produce.vegetables.alliums",
        "produce.vegetables.squash_gourds",
        "produce.vegetables.stalk_pod",
        "produce.herbs_aromatics",
        "dairy_eggs.milk.cows_milk",
        "dairy_eggs.dairy_alternatives.plant_milk",
        "dairy_eggs.cheese.fresh_soft",
        "dairy_eggs.cheese.hard_aged",
        "dairy_eggs.butter_fats",
        "meat_seafood_alternatives.seafood.fish",
        "meat_seafood_alternatives.seafood.shellfish",
        "meat_seafood_alternatives.plant_proteins.tofu_tempeh",
        "bread_bakery.flatbreads",
        "bread_bakery.pastries",
        "grains_pasta.noodles",
        "grains_pasta.whole_grains",
        "grains_pasta.flour",
        "pantry_cooking.pulses_legumes.beans",
        "pantry_cooking.oils_vinegars",
        "pantry_cooking.cooking_bases",
        "pantry_cooking.spreads",
        "pantry_cooking.sweeteners",
        "pantry_cooking.sauces_condiments",
        "snacks_confectionery.nuts_seeds",
    )
)

# Household operations / personal care / baby / pet / OTC pharmacy taxonomy
# is currently very shallow (a handful of leaves cover each entire branch),
# so a leaf isn't fine-grained enough to be a Deals product on its own there
# yet — text matching against normalized_name is still how product-level
# granularity is reached for this track. Groceries never reach this list
# (see canonical_price_watch_identity): once a taxonomy leaf is itself one
# comparable product, matching text against brand names is pure downside —
# a "Compliments"-branded item once matched "Limes" because the substring
# "lime" hides inside "Compliments", and "Butterball" (a turkey brand)
# matches "Butter" — the taxonomy leaf sidesteps that class of bug entirely.
PRODUCT_PATTERNS: tuple[tuple[str, tuple[str, ...], frozenset[str]], ...] = (
    # --- Household operations ---
    (
        "Toilet paper",
        ("toilet paper", "toilet roll", "bath tissue"),
        frozenset({"each"}),
    ),
    (
        "Paper towels",
        ("paper towel", "kitchen roll", "kitchen towel"),
        frozenset({"each"}),
    ),
    ("Facial tissues", ("facial tissue", "tissue box"), frozenset({"each"})),
    ("Napkins", ("napkin",), frozenset({"each"})),
    (
        "Dish soap",
        ("dish soap", "dishwashing liquid", "dish detergent"),
        frozenset({"L", "each"}),
    ),
    (
        "Dishwasher detergent",
        ("dishwasher detergent", "dishwasher tablet", "dishwasher pod"),
        frozenset({"each"}),
    ),
    (
        "Laundry detergent",
        ("laundry detergent", "laundry pod"),
        frozenset({"L", "each"}),
    ),
    ("Fabric softener", ("fabric softener",), frozenset({"L", "each"})),
    (
        "Trash bags",
        ("trash bag", "garbage bag", "bin bag"),
        frozenset({"each"}),
    ),
    (
        "Aluminum foil",
        ("aluminum foil", "aluminium foil", "tin foil"),
        frozenset({"each"}),
    ),
    (
        "Plastic wrap",
        ("plastic wrap", "cling film", "cling wrap"),
        frozenset({"each"}),
    ),
    (
        "Ziplock bags",
        ("ziplock", "storage bag", "freezer bag"),
        frozenset({"each"}),
    ),
    ("Air freshener", ("air freshener",), frozenset({"each"})),
    (
        "Bug spray",
        ("bug spray", "insect spray", "pest spray"),
        frozenset({"each"}),
    ),
    # --- Personal care ---
    ("Toothpaste", ("toothpaste",), frozenset({"each"})),
    ("Toothbrushes", ("toothbrush",), frozenset({"each"})),
    ("Mouthwash", ("mouthwash",), frozenset({"L", "each"})),
    ("Shampoo", ("shampoo",), frozenset({"L", "each"})),
    ("Conditioner", ("conditioner",), frozenset({"L", "each"})),
    ("Body wash", ("body wash",), frozenset({"L", "each"})),
    ("Bar soap", ("bar soap", "soap bar"), frozenset({"each"})),
    ("Hand soap", ("hand soap", "hand wash"), frozenset({"L", "each"})),
    ("Deodorant", ("deodorant", "antiperspirant"), frozenset({"each"})),
    ("Razors", ("razor",), frozenset({"each"})),
    ("Sunscreen", ("sunscreen", "sunblock"), frozenset({"each"})),
    (
        "Lotion",
        ("lotion", "moisturizer", "moisturiser"),
        frozenset({"each"}),
    ),
    (
        "Feminine hygiene products",
        ("tampon", "sanitary pad", "menstrual pad", "panty liner"),
        frozenset({"each"}),
    ),
    (
        "Cotton swabs",
        ("cotton swab", "cotton bud", "cotton ball"),
        frozenset({"each"}),
    ),
    # --- Baby ---
    ("Diapers", ("diaper", "nappy"), frozenset({"each"})),
    ("Baby wipes", ("baby wipe",), frozenset({"each"})),
    (
        "Baby formula",
        ("baby formula", "infant formula"),
        frozenset({"kg", "each"}),
    ),
    # --- Pets ---
    ("Dog food", ("dog food",), frozenset({"kg", "each"})),
    ("Cat food", ("cat food",), frozenset({"kg", "each"})),
    ("Cat litter", ("cat litter",), frozenset({"kg", "each"})),
    (
        "Pet treats",
        ("pet treat", "dog treat", "cat treat"),
        frozenset({"kg", "each"}),
    ),
    # --- Health & OTC ---
    ("Vitamins", ("vitamin", "multivitamin"), frozenset({"each"})),
    # Different active ingredients have different typical prices — these are
    # not interchangeable the way, say, pasta shapes are, so each drug gets
    # its own product instead of one blended "pain relievers" bucket.
    ("Ibuprofen", ("ibuprofen", "advil", "motrin"), frozenset({"each"})),
    (
        "Acetaminophen",
        ("acetaminophen", "paracetamol", "tylenol"),
        frozenset({"each"}),
    ),
    ("Aspirin", ("aspirin",), frozenset({"each"})),
    (
        "Bandages",
        ("bandage", "band-aid", "band aid", "plaster"),
        frozenset({"each"}),
    ),
    (
        "Cold medicine",
        ("cold medicine", "cough syrup", "cough medicine"),
        frozenset({"each"}),
    ),
    # --- Transportation ---
    # Scoped to "regular" specifically, not bare "gasoline" - premium/mid-grade
    # gas costs meaningfully more per litre, so a future fill-up at a higher
    # grade should get its own product rather than blending into this series
    # (same reasoning as Ibuprofen vs. Acetaminophen above).
    ("Regular gasoline", ("regular gasoline", "regular gas"), frozenset({"L"})),
)


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def _contains_pattern(name: str, pattern: str) -> bool:
    """True if `pattern` appears in `name` starting at a word boundary.

    Plain substring matching lets short words hide inside unrelated brand
    names — "lime" is a substring of "Compliments" (comp-LIME-nts), so a
    naive `in` check mislabeled the "Compliments" store-brand line as Limes.
    Requiring the match to start where the preceding character isn't a
    letter/digit closes that class of bug while still matching plurals and
    suffixes (e.g. "apple" still matches "apples") since no right-boundary
    is required. Used only by the household/personal-care text-matching
    track below — groceries no longer do any text matching at all.
    """
    start = 0
    while True:
        index = name.find(pattern, start)
        if index == -1:
            return False
        if index == 0 or not name[index - 1].isalnum():
            return True
        start = index + 1


def canonical_price_watch_identity(
    normalized_name: str | None,
    taxonomy_key: str | None,
    taxonomy_name: str | None,
    normalized_unit: str | None,
) -> PriceWatchIdentity | None:
    """Map a classified purchase to a measurable, comparable Deals product.

    Groceries: the taxonomy leaf the classifying LLM already assigned *is*
    the product — no text matching, no collision risk. Household operations,
    personal care, baby, pet, and OTC pharmacy: taxonomy there is still too
    shallow for leaf-level granularity, so normalized_name text matching
    against a curated PRODUCT_PATTERNS catalog is still how product-level
    identity is reached. Durable one-time goods (electronics, furniture,
    appliances) are excluded structurally: their taxonomy branches never
    appear in TRACKABLE_PREFIXES.
    """

    name = f" {str(normalized_name or '').strip().lower()} "
    key = str(taxonomy_key or "").strip().lower()
    unit = str(normalized_unit or "").strip()

    if not any(key.startswith(prefix) for prefix in TRACKABLE_PREFIXES):
        return None
    if any(part in key for part in EXCLUDED_KEY_PARTS):
        return None

    if key.startswith(GROCERY_PREFIX):
        if (
            not unit
            or key in EXCLUDED_TAXONOMY_LEAVES
            or key in EXCLUDED_SPLIT_PARENT_LEAVES
            or not taxonomy_name
        ):
            return None
        return PriceWatchIdentity(f"product:{_slug(taxonomy_name)}", taxonomy_name)

    if any(word in name for word in EXCLUDED_NAME_WORDS):
        return None

    for product_label, patterns, allowed_units in PRODUCT_PATTERNS:
        if unit in allowed_units and any(
            _contains_pattern(name, pattern) for pattern in patterns
        ):
            return PriceWatchIdentity(f"product:{_slug(product_label)}", product_label)

    return None
