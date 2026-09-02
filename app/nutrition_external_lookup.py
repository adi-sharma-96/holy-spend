"""Thin server-side proxies for USDA FoodData Central and Open Food Facts.

The real USDA API key lives only in this process's environment, read once here and
never sent to or through a connecting client - a scheduled task calls these MCP tools
like any other and never needs its own key. These functions fetch and unit-normalize
candidate data; they never pick a winner or decide which source to trust. That
judgment (is this the right product, is this value plausible for the food type) stays
with the calling agent, same as when it read raw web pages directly.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from app.errors import ExternalLookupError
from app.plugin_models import (
    NutrimentsInput,
    OpenFoodFactsCandidate,
    OpenFoodFactsSearchResponse,
    UsdaFoodCandidate,
    UsdaFoodSearchResponse,
)

USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"
USDA_ALLOWED_DATA_TYPES = frozenset({"Foundation", "SR Legacy", "Survey (FNDDS)", "Branded"})
OFF_BASE_URL = "https://world.openfoodfacts.org"
OFF_FIELDS = (
    "code,product_name,brands,quantity,serving_size,nutrition_data_per,nutriscore_grade,nova_group,nutriments,url"
)
# Open Food Facts' usage policy asks integrations to identify themselves.
OFF_USER_AGENT = "HolySpend-NutritionLookup/1.0 (personal single-user expense tracker)"

# USDA FoodData Central nutrient numbers -> this app's NutrimentsInput field names.
# Numbers, not names, are the stable key: nutrientName strings vary slightly across
# USDA's own datasets, but the number for a given nutrient is fixed.
_USDA_NUTRIENT_FIELDS: dict[str, str] = {
    "208": "energy_kcal",
    "203": "protein_g",
    "204": "fat_g",
    "606": "saturated_fat_g",
    "605": "trans_fat_g",
    "205": "carbohydrates_g",
    "269": "sugars_g",
    "539": "added_sugars_g",
    "291": "fiber_g",
    "307": "sodium_mg",
    "601": "cholesterol_mg",
    "306": "potassium_mg",
    "301": "calcium_mg",
    "303": "iron_mg",
}

# Open Food Facts field keys -> this app's NutrimentsInput field names.
_OFF_NUTRIENT_KEYS: dict[str, str] = {
    "energy_kcal": "energy-kcal_100g",
    "protein_g": "proteins_100g",
    "fat_g": "fat_100g",
    "saturated_fat_g": "saturated-fat_100g",
    "trans_fat_g": "trans-fat_100g",
    "carbohydrates_g": "carbohydrates_100g",
    "sugars_g": "sugars_100g",
    "added_sugars_g": "added-sugars_100g",
    "fiber_g": "fiber_100g",
    "sodium_mg": "sodium_100g",
    "cholesterol_mg": "cholesterol_100g",
    "potassium_mg": "potassium_100g",
    "calcium_mg": "calcium_100g",
    "iron_mg": "iron_100g",
}
# Open Food Facts reports these five in grams per 100g, not milligrams.
_OFF_GRAM_TO_MG_FIELDS = frozenset({"sodium_mg", "cholesterol_mg", "potassium_mg", "calcium_mg", "iron_mg"})


def new_usda_client(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(base_url=USDA_BASE_URL, timeout=httpx.Timeout(timeout_seconds))


def new_off_client(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(
        base_url=OFF_BASE_URL,
        timeout=httpx.Timeout(timeout_seconds),
        headers={"User-Agent": OFF_USER_AGENT},
    )


def _request(
    client: httpx.Client,
    path: str,
    *,
    params: dict[str, Any],
    source_name: str,
) -> dict[str, Any]:
    try:
        response = client.get(path, params=params)
    except httpx.TimeoutException as error:
        raise ExternalLookupError(f"{source_name} lookup timed out") from error
    except httpx.HTTPError as error:
        raise ExternalLookupError(f"{source_name} lookup failed: {error}") from error
    if response.status_code == 429:
        raise ExternalLookupError(
            f"{source_name} rate limit exceeded. If this is USDA's DEMO_KEY, request a free personal API "
            "key at https://fdc.nal.usda.gov/api-key-signup.html for a much higher limit."
        )
    if response.status_code == 404:
        return {}
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise ExternalLookupError(f"{source_name} lookup failed with HTTP {response.status_code}") from error
    result: dict[str, Any] = response.json()
    return result


def _as_float(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _build_nutriments(fields: dict[str, float | None]) -> tuple[NutrimentsInput | None, str | None]:
    if not any(value is not None for value in fields.values()):
        return None, None
    try:
        return NutrimentsInput(basis="per_100g", **fields), None
    except ValidationError as error:
        return None, f"Excluded - source data is internally inconsistent: {error}"


def _usda_nutriments(pairs: list[tuple[str, float | None]]) -> tuple[NutrimentsInput | None, str | None]:
    by_field: dict[str, float | None] = {}
    for number, amount in pairs:
        field = _USDA_NUTRIENT_FIELDS.get(number)
        if field is not None and amount is not None:
            by_field[field] = amount
    return _build_nutriments({field: by_field.get(field) for field in _USDA_NUTRIENT_FIELDS.values()})


def _search_result_pairs(food: dict[str, Any]) -> list[tuple[str, float | None]]:
    return [
        (str(nutrient.get("nutrientNumber")), _as_float(nutrient.get("value")))
        for nutrient in food.get("foodNutrients", [])
    ]


def _detail_pairs(food: dict[str, Any]) -> list[tuple[str, float | None]]:
    return [
        (str(entry.get("nutrient", {}).get("number")), _as_float(entry.get("amount")))
        for entry in food.get("foodNutrients", [])
    ]


def _usda_candidate(food: dict[str, Any], pairs: list[tuple[str, float | None]]) -> UsdaFoodCandidate:
    nutrients, warning = _usda_nutriments(pairs)
    fdc_id = food["fdcId"]
    return UsdaFoodCandidate(
        fdc_id=fdc_id,
        description=food.get("description", ""),
        data_type=food.get("dataType", ""),
        brand_owner=food.get("brandOwner"),
        brand_name=food.get("brandName"),
        gtin_upc=food.get("gtinUpc"),
        ingredients=food.get("ingredients"),
        serving_size=_as_float(food.get("servingSize")),
        serving_size_unit=food.get("servingSizeUnit"),
        nutrients_per_100g=nutrients,
        data_quality_warning=warning,
        source_url=f"https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients",
    )


def search_usda_foods(
    client: httpx.Client,
    api_key: str,
    query: str,
    *,
    page_size: int = 10,
    data_types: list[str] | None = None,
) -> UsdaFoodSearchResponse:
    if not query.strip():
        raise ExternalLookupError("USDA FDC search query must not be empty")
    params: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "pageSize": max(1, min(page_size, 25)),
    }
    if data_types:
        invalid = sorted(set(data_types) - USDA_ALLOWED_DATA_TYPES)
        if invalid:
            raise ExternalLookupError(
                f"Unknown USDA dataType(s) {invalid}; valid values are {sorted(USDA_ALLOWED_DATA_TYPES)}"
            )
        # The search endpoint only honors this filter as a single comma-joined value;
        # passing it as repeated query params (httpx's default for a list) silently
        # keeps only the last one.
        params["dataType"] = ",".join(data_types)
    payload = _request(client, "/foods/search", params=params, source_name="USDA FoodData Central")
    foods = payload.get("foods", [])
    candidates = [_usda_candidate(food, _search_result_pairs(food)) for food in foods]
    return UsdaFoodSearchResponse(total_hits=payload.get("totalHits", len(candidates)), candidates=candidates)


def get_usda_food_detail(client: httpx.Client, api_key: str, fdc_id: int) -> UsdaFoodCandidate:
    payload = _request(client, f"/food/{fdc_id}", params={"api_key": api_key}, source_name="USDA FoodData Central")
    if not payload:
        raise ExternalLookupError(f"USDA FDC has no food with fdcId {fdc_id}")
    return _usda_candidate(payload, _detail_pairs(payload))


def _off_nutriments(nutriments: dict[str, Any]) -> tuple[NutrimentsInput | None, str | None]:
    fields: dict[str, float | None] = {}
    for our_field, off_key in _OFF_NUTRIENT_KEYS.items():
        value = _as_float(nutriments.get(off_key))
        if value is not None and our_field in _OFF_GRAM_TO_MG_FIELDS:
            value = value * 1000
        fields[our_field] = value
    if fields.get("energy_kcal") is None:
        kilojoules = _as_float(nutriments.get("energy_100g"))
        if kilojoules is not None:
            fields["energy_kcal"] = kilojoules / 4.184
    return _build_nutriments(fields)


def _off_candidate(product: dict[str, Any]) -> OpenFoodFactsCandidate:
    nutrients, warning = _off_nutriments(product.get("nutriments", {}))
    code = str(product.get("code", ""))
    nova = _as_float(product.get("nova_group"))
    return OpenFoodFactsCandidate(
        barcode=code,
        product_name=product.get("product_name") or None,
        brands=product.get("brands") or None,
        quantity=product.get("quantity") or None,
        serving_size=product.get("serving_size") or None,
        nutrition_data_per=product.get("nutrition_data_per") or None,
        nutriscore_grade=product.get("nutriscore_grade") or None,
        nova_group=int(nova) if nova is not None else None,
        nutrients_per_100g=nutrients,
        data_quality_warning=warning,
        source_url=product.get("url") or f"https://world.openfoodfacts.org/product/{code}",
    )


def search_open_food_facts(
    client: httpx.Client,
    query: str,
    *,
    page_size: int = 10,
    brand: str | None = None,
) -> OpenFoodFactsSearchResponse:
    if not query.strip():
        raise ExternalLookupError("Open Food Facts search query must not be empty")
    params: dict[str, Any] = {
        "search_terms": query,
        "search_simple": 1,
        "json": 1,
        "page_size": max(1, min(page_size, 25)),
        "fields": OFF_FIELDS,
    }
    if brand and brand.strip():
        params.update(tagtype_0="brands", tag_contains_0="contains", tag_0=brand.strip())
    payload = _request(client, "/cgi/search.pl", params=params, source_name="Open Food Facts")
    products = payload.get("products", [])
    candidates = [_off_candidate(product) for product in products]
    return OpenFoodFactsSearchResponse(total_hits=payload.get("count", len(candidates)), candidates=candidates)


def get_open_food_facts_by_barcode(client: httpx.Client, barcode: str) -> OpenFoodFactsSearchResponse:
    normalized = barcode.strip()
    if not normalized.isdigit():
        raise ExternalLookupError("Open Food Facts barcode must be numeric (a UPC/EAN)")
    payload = _request(
        client,
        f"/api/v2/product/{normalized}.json",
        params={"fields": OFF_FIELDS},
        source_name="Open Food Facts",
    )
    if payload.get("status") != 1 or "product" not in payload:
        return OpenFoodFactsSearchResponse(total_hits=0, candidates=[])
    return OpenFoodFactsSearchResponse(total_hits=1, candidates=[_off_candidate(payload["product"])])
