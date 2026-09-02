import re

PRODUCE_TAXONOMY_PREFIX = "food_dining.groceries.produce"


def nutrition_identity_key(name: str | None, brand: str | None, category_slug: str | None = None) -> str:
    """Must stay byte-for-byte equivalent to the SQL expression in
    NutritionRepository._enqueue_new - this is a second implementation of the same rule,
    not a refactor of the first, since that one is a bulk INSERT...SELECT with an ON
    CONFLICT dedup and belongs in SQL, while this one correlates rows in Python for
    read-side reporting, matching how exact_basket_identity/canonical_price_watch_identity
    already do the same kind of correlation elsewhere in this codebase.

    Brand is ignored for produce: unbranded and branded raw produce (e.g. "Dole
    Cauliflower" vs "Cauliflower") are nutritionally identical, so treating them as
    separate identities only fragments purchases across duplicate tiles and duplicate
    (independently variable-quality) lookups for no benefit."""

    def slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    is_produce = (category_slug or "").startswith(PRODUCE_TAXONOMY_PREFIX)
    effective_brand = "" if is_produce else (brand or "")
    return f"{slug(name or '')}::{slug(effective_brand)}"
