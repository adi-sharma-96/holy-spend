import httpx
import pytest

from app.errors import ExternalLookupError
from app.nutrition_external_lookup import (
    get_open_food_facts_by_barcode,
    get_usda_food_detail,
    search_open_food_facts,
    search_usda_foods,
)

USDA_SEARCH_FOOD = {
    "fdcId": 2429587,
    "description": "PANEER",
    "dataType": "Branded",
    "brandOwner": "Karoun Dairies Inc.",
    "brandName": "GOPI",
    "gtinUpc": "796252702143",
    "ingredients": "PASTEURIZED GRADE A MILK AND VINEGAR.",
    "servingSize": 28.0,
    "servingSizeUnit": "g",
    "foodNutrients": [
        {"nutrientNumber": "203", "nutrientName": "Protein", "unitName": "G", "value": 25.0},
        {"nutrientNumber": "204", "nutrientName": "Total lipid (fat)", "unitName": "G", "value": 25.0},
        {"nutrientNumber": "205", "nutrientName": "Carbohydrate, by difference", "unitName": "G", "value": 3.57},
        {"nutrientNumber": "208", "nutrientName": "Energy", "unitName": "KCAL", "value": 321},
        {"nutrientNumber": "269", "nutrientName": "Total Sugars", "unitName": "G", "value": 3.57},
        {"nutrientNumber": "291", "nutrientName": "Fiber, total dietary", "unitName": "G", "value": 0.0},
        {"nutrientNumber": "307", "nutrientName": "Sodium, Na", "unitName": "MG", "value": 481.0},
        {"nutrientNumber": "601", "nutrientName": "Cholesterol", "unitName": "MG", "value": 89.0},
        {"nutrientNumber": "606", "nutrientName": "Fatty acids, total saturated", "unitName": "G", "value": 17.86},
    ],
}


def client_for(handler: httpx.MockTransport, base_url: str = "https://example.test") -> httpx.Client:
    return httpx.Client(transport=handler, base_url=base_url)


def test_usda_search_maps_nutrient_numbers_to_named_fields() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"totalHits": 1, "foods": [USDA_SEARCH_FOOD]})
    )

    result = search_usda_foods(client_for(transport), "DEMO_KEY", "paneer")

    assert result.total_hits == 1
    candidate = result.candidates[0]
    assert candidate.fdc_id == 2429587
    assert candidate.brand_name == "GOPI"
    assert candidate.data_type == "Branded"
    assert candidate.source_url == "https://fdc.nal.usda.gov/food-details/2429587/nutrients"
    nutrients = candidate.nutrients_per_100g
    assert nutrients is not None
    assert nutrients.energy_kcal == 321
    assert nutrients.protein_g == 25.0
    assert nutrients.saturated_fat_g == 17.86
    assert nutrients.sodium_mg == 481.0
    assert candidate.data_quality_warning is None


def test_usda_search_request_uses_comma_joined_data_types() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["dataType"] = request.url.params.get("dataType", "")
        return httpx.Response(200, json={"totalHits": 0, "foods": []})

    search_usda_foods(
        client_for(httpx.MockTransport(handler)),
        "DEMO_KEY",
        "cauliflower",
        data_types=["Foundation", "SR Legacy"],
    )

    assert captured["dataType"] == "Foundation,SR Legacy"


def test_usda_search_rejects_unknown_data_type() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"foods": []}))

    with pytest.raises(ExternalLookupError, match="Unknown USDA dataType"):
        search_usda_foods(client_for(transport), "DEMO_KEY", "paneer", data_types=["Not A Real Type"])


def test_usda_search_rejects_empty_query() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"foods": []}))

    with pytest.raises(ExternalLookupError, match="must not be empty"):
        search_usda_foods(client_for(transport), "DEMO_KEY", "   ")


def test_usda_search_flags_internally_impossible_macros_instead_of_returning_them() -> None:
    bad_food = {
        **USDA_SEARCH_FOOD,
        "foodNutrients": [
            {"nutrientNumber": "205", "nutrientName": "Carbohydrate, by difference", "unitName": "G", "value": 3.57},
            {"nutrientNumber": "269", "nutrientName": "Total Sugars", "unitName": "G", "value": 28.0},
        ],
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"totalHits": 1, "foods": [bad_food]})
    )

    result = search_usda_foods(client_for(transport), "DEMO_KEY", "bad data")

    candidate = result.candidates[0]
    assert candidate.nutrients_per_100g is None
    assert candidate.data_quality_warning is not None
    assert "inconsistent" in candidate.data_quality_warning


def test_usda_search_last_value_wins_when_a_nutrient_number_repeats() -> None:
    duplicated_food = {
        **USDA_SEARCH_FOOD,
        "foodNutrients": [
            {"nutrientNumber": "208", "nutrientName": "Energy", "unitName": "KCAL", "value": 321},
            {"nutrientNumber": "208", "nutrientName": "Energy", "unitName": "KCAL", "value": 359},
        ],
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"totalHits": 1, "foods": [duplicated_food]})
    )

    result = search_usda_foods(client_for(transport), "DEMO_KEY", "duplicate")

    assert result.candidates[0].nutrients_per_100g is not None
    assert result.candidates[0].nutrients_per_100g.energy_kcal == 359


def test_usda_detail_reads_nested_nutrient_shape() -> None:
    detail_food = {
        "fdcId": 2429587,
        "description": "PANEER",
        "dataType": "Branded",
        "foodNutrients": [
            {"nutrient": {"number": "208", "name": "Energy", "unitName": "kcal"}, "amount": 321.0},
            {"nutrient": {"number": "203", "name": "Protein", "unitName": "g"}, "amount": 25.0},
        ],
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=detail_food))

    candidate = get_usda_food_detail(client_for(transport), "DEMO_KEY", 2429587)

    assert candidate.nutrients_per_100g is not None
    assert candidate.nutrients_per_100g.energy_kcal == 321.0
    assert candidate.nutrients_per_100g.protein_g == 25.0


def test_usda_detail_raises_a_clear_error_for_an_unknown_fdc_id() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404))

    with pytest.raises(ExternalLookupError, match="no food with fdcId 999"):
        get_usda_food_detail(client_for(transport), "DEMO_KEY", 999)


def test_usda_rate_limit_raises_a_descriptive_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(429))

    with pytest.raises(ExternalLookupError, match="rate limit"):
        search_usda_foods(client_for(transport), "DEMO_KEY", "paneer")


def test_usda_timeout_raises_external_lookup_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(ExternalLookupError, match="timed out"):
        search_usda_foods(client_for(httpx.MockTransport(handler)), "DEMO_KEY", "paneer")


OFF_NUTRIMENTS: dict[str, float] = {
    "energy-kcal_100g": 233.333333333333,
    "proteins_100g": 16.6666666666667,
    "fat_100g": 16.6666666666667,
    "saturated-fat_100g": 11.6666666666667,
    "trans-fat_100g": 0.666666666666667,
    "carbohydrates_100g": 3.33333333333333,
    "sugars_100g": 0.0,
    "fiber_100g": 0.0,
    "sodium_100g": 0.0333333333333333,
    "cholesterol_100g": 0.0833333333333333,
    "potassium_100g": 0.1,
    "calcium_100g": 0.333333333333333,
    "iron_100g": 0.0,
}

OFF_PRODUCT: dict[str, object] = {
    "code": "0627985001008",
    "product_name": "Chalo Paneer",
    "brands": "Chalo Fresh",
    "quantity": "300 g",
    "serving_size": "3 cm cube (30 g)",
    "nutrition_data_per": "100g",
    "nutriscore_grade": "c",
    "nova_group": 4,
    "url": "https://world.openfoodfacts.org/product/0627985001008/chalo-paneer",
    "nutriments": OFF_NUTRIMENTS,
}


def test_off_search_converts_gram_fields_to_milligrams() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"count": 1, "products": [OFF_PRODUCT]})
    )

    result = search_open_food_facts(client_for(transport), "chalo paneer")

    candidate = result.candidates[0]
    assert candidate.barcode == "0627985001008"
    assert candidate.nutriscore_grade == "c"
    assert candidate.nova_group == 4
    nutrients = candidate.nutrients_per_100g
    assert nutrients is not None
    assert nutrients.sodium_mg is not None and nutrients.sodium_mg == pytest.approx(33.333, rel=1e-3)
    assert nutrients.cholesterol_mg is not None and nutrients.cholesterol_mg == pytest.approx(83.333, rel=1e-3)
    assert nutrients.calcium_mg is not None and nutrients.calcium_mg == pytest.approx(333.333, rel=1e-3)


def test_off_falls_back_to_kilojoules_when_kcal_is_missing() -> None:
    nutriments_without_kcal = {k: v for k, v in OFF_NUTRIMENTS.items() if k != "energy-kcal_100g"}
    product = {**OFF_PRODUCT, "nutriments": {**nutriments_without_kcal, "energy_100g": 956.666666666667}}
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"count": 1, "products": [product]})
    )

    result = search_open_food_facts(client_for(transport), "chalo paneer")

    nutrients = result.candidates[0].nutrients_per_100g
    assert nutrients is not None
    assert nutrients.energy_kcal == pytest.approx(228.6, rel=1e-2)


def test_off_search_with_brand_filters_by_brand_tag() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.url.params)
        return httpx.Response(200, json={"count": 0, "products": []})

    search_open_food_facts(client_for(httpx.MockTransport(handler)), "partly skimmed milk", brand="Natrel")

    assert captured["tagtype_0"] == "brands"
    assert captured["tag_contains_0"] == "contains"
    assert captured["tag_0"] == "Natrel"


def test_off_search_without_brand_omits_brand_filter_params() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.url.params)
        return httpx.Response(200, json={"count": 0, "products": []})

    search_open_food_facts(client_for(httpx.MockTransport(handler)), "partly skimmed milk")

    assert "tagtype_0" not in captured


def test_off_search_rejects_empty_query() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"products": []}))

    with pytest.raises(ExternalLookupError, match="must not be empty"):
        search_open_food_facts(client_for(transport), "  ")


def test_off_barcode_lookup_returns_the_product() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"code": "0627985001008", "product": OFF_PRODUCT, "status": 1})
    )

    result = get_open_food_facts_by_barcode(client_for(transport), "0627985001008")

    assert result.total_hits == 1
    assert result.candidates[0].product_name == "Chalo Paneer"


def test_off_barcode_lookup_returns_empty_for_unknown_barcode() -> None:
    body = {"code": "00000000", "status": 0, "status_verbose": "no code or invalid code"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))

    result = get_open_food_facts_by_barcode(client_for(transport), "0000000000000")

    assert result.total_hits == 0
    assert result.candidates == []


def test_off_barcode_lookup_rejects_a_non_numeric_barcode() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))

    with pytest.raises(ExternalLookupError, match="numeric"):
        get_open_food_facts_by_barcode(client_for(transport), "not-a-barcode")


def test_off_rate_limit_raises_a_descriptive_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(429))

    with pytest.raises(ExternalLookupError, match="rate limit"):
        search_open_food_facts(client_for(transport), "paneer")
