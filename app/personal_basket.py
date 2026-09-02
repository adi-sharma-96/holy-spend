import re
from dataclasses import dataclass

from app.price_watch import (
    EXCLUDED_KEY_PARTS,
    EXCLUDED_NAME_WORDS,
    GROCERY_PREFIX,
    TRACKABLE_PREFIXES,
)

PRODUCE_PREFIX = f"{GROCERY_PREFIX}produce."


@dataclass(frozen=True)
class BasketIdentity:
    key: str
    label: str


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _prefixed_label(prefix: str, name: str) -> str:
    """Prepend prefix (brand or merchant) to name for display, unless name
    already starts with it. normalized_name frequently already has the brand
    baked in (e.g. "Chalo Unripened Paneer"), since nothing about receipt
    extraction guarantees it's brand-free - blindly prepending in that case
    produced double-ups like "Chalo Chalo Unripened Paneer"."""
    title = name.title()
    if title.lower().startswith(prefix.strip().lower()):
        return title
    return f"{prefix} {title}"


def exact_basket_identity(
    normalized_name: str | None,
    brand: str | None,
    taxonomy_key: str | None,
    normalized_unit: str | None,
    merchant: str | None,
) -> BasketIdentity | None:
    """Exact product identity for personal inflation tracking.

    Unlike Price Watch's canonical_price_watch_identity, this never blends
    varieties together (Honeycrisp stays separate from Gala apples). Brand is
    folded into the key when known (packaged goods) but stays optional, since
    most historical purchases and unbranded produce have none. Merchant is
    folded into the key unconditionally — the same product bought at two
    different stores is deliberately tracked as two separate exact-identity
    products, per the "hyper specific: product + brand + store" design. This
    means the same staple bought across multiple stores needs its own repeat
    purchases at each store to build a trend, rather than blending into one
    series the way it used to.

    Unbranded produce shows the merchant in place of brand in the display
    label only (e.g. "Farm Boy Bananas") — merchant is already folded into
    identity_key unconditionally above, so this doesn't change grouping, it
    just keeps every basket card reading consistently instead of some rows
    showing a brand and others showing bare product names.
    """
    name = str(normalized_name or "").strip()
    key = str(taxonomy_key or "").strip().lower()
    unit = str(normalized_unit or "").strip()
    brand_clean = str(brand or "").strip()
    merchant_clean = str(merchant or "").strip()

    if not name or not unit:
        return None
    if not any(key.startswith(prefix) for prefix in TRACKABLE_PREFIXES):
        return None
    if any(part in key for part in EXCLUDED_KEY_PARTS):
        return None
    if any(word in f" {name.lower()} " for word in EXCLUDED_NAME_WORDS):
        return None

    name_slug = _slug(name)
    if not name_slug:
        return None

    merchant_slug = _slug(merchant_clean) if merchant_clean else "unknown-store"

    if brand_clean:
        identity_key = f"{name_slug}::{_slug(brand_clean)}@{unit}@store:{merchant_slug}"
        label = _prefixed_label(brand_clean, name)
    elif key.startswith(PRODUCE_PREFIX) and merchant_clean:
        # Most produce has no real manufacturer brand. Merchant is already
        # folded into identity_key below regardless, so this changes display
        # only — it keeps every basket card reading "<store> <product>"
        # instead of branded rows looking mismatched against bare ones.
        identity_key = f"{name_slug}@{unit}@store:{merchant_slug}"
        label = _prefixed_label(merchant_clean, name)
    else:
        identity_key = f"{name_slug}@{unit}@store:{merchant_slug}"
        label = name.title()
    return BasketIdentity(key=identity_key, label=label)
