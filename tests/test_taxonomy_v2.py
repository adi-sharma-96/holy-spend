from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from uuid import uuid5

from app.repositories import TaxonomyRepository
from scripts.compile_taxonomy import NAMESPACE, load_catalog, render_migration, render_snapshot

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "taxonomy" / "v2" / "taxonomy.yaml"
SNAPSHOT = ROOT / "taxonomy" / "v2" / "taxonomy.generated.json"
MIGRATION = ROOT / "supabase" / "migrations" / "0013_taxonomy_v2.sql"


def test_catalog_has_one_versioned_six_level_semantic_tree() -> None:
    catalog = load_catalog(SOURCE)
    keys = {node.stable_key for node in catalog.nodes}
    nodes_by_key = {node.stable_key: node for node in catalog.nodes}

    assert catalog.version == "2.0.0"
    assert catalog.level_names == (
        "Domain",
        "Group",
        "Category",
        "Subcategory",
        "Class",
        "Subclass",
    )
    assert len(keys) == len(catalog.nodes)
    assert len(catalog.nodes) >= 350
    assert len([node for node in catalog.nodes if node.is_assignable]) >= 300
    assert max(node.level for node in catalog.nodes) == 6
    assert all(1 <= node.level <= 6 for node in catalog.nodes)

    child_counts = Counter(node.parent_key for node in catalog.nodes if node.parent_key is not None)
    for node in catalog.nodes:
        assert node.is_assignable is (child_counts[node.stable_key] == 0)
        if node.parent_key is None:
            assert node.level == 1
        else:
            assert node.parent_key in keys
            assert node.level == nodes_by_key[node.parent_key].level + 1


def test_taxonomy_projection_casts_custom_enum_arrays_to_native_text_arrays() -> None:
    projection = TaxonomyRepository._node_projection()

    assert "node.allowed_transaction_types::text[] as allowed_transaction_types" in projection


def test_catalog_covers_representative_line_item_and_whole_bill_use_cases() -> None:
    catalog = load_catalog(SOURCE)
    nodes = {node.stable_key: node for node in catalog.nodes}
    expected_assignable = {
        "food_dining.groceries.produce.fruit.apples_pears.apples",
        "food_dining.groceries.produce.vegetables.nightshades.tomatoes",
        "food_dining.groceries.dairy_eggs.cheese.fresh_soft.paneer",
        "housing_utilities.housing_payments.rent",
        "housing_utilities.communications.home_internet",
        "transportation.personal_vehicle.fuel.gasoline",
        "transportation.public_transit.bus",
        "food_dining.eating_out.restaurants.full_service",
        "entertainment_leisure.cinema.admission",
        "income.employment",
        "money_movement.account_transfer",
        "unclassified.needs_review",
        "unclassified.user_approved_other",
    }

    assert expected_assignable <= nodes.keys()
    assert all(nodes[key].is_assignable for key in expected_assignable)
    assert "income" in nodes["income.employment"].allowed_transaction_types
    assert "transfer" in nodes["money_movement.account_transfer"].allowed_transaction_types
    assert "expense" in nodes["housing_utilities.housing_payments.rent"].allowed_transaction_types


def test_facets_are_orthogonal_unique_and_deterministically_identified() -> None:
    catalog = load_catalog(SOURCE)
    facet_keys = {facet.stable_key for facet in catalog.facets}
    value_keys = {
        value.stable_key
        for facet in catalog.facets
        for value in facet.values
    }

    assert len(catalog.facets) >= 10
    assert len(value_keys) >= 50
    assert len(facet_keys) == len(catalog.facets)
    assert len(value_keys) == sum(len(facet.values) for facet in catalog.facets)
    assert {
        "product_form",
        "dietary",
        "sourcing",
        "recurrence",
        "necessity",
        "use_context",
    } <= facet_keys
    assert {
        "product_form.fresh",
        "dietary.vegan",
        "recurrence.recurring",
    } <= value_keys
    for facet in catalog.facets:
        assert facet.id == uuid5(NAMESPACE, f"facet:{facet.stable_key}")
        for value in facet.values:
            assert value.id == uuid5(NAMESPACE, f"facet-value:{value.stable_key}")


def test_legacy_mappings_only_target_live_canonical_values() -> None:
    catalog = load_catalog(SOURCE)
    nodes = {node.stable_key: node for node in catalog.nodes}
    facet_values = {
        value.stable_key
        for facet in catalog.facets
        for value in facet.values
    }

    assert catalog.legacy_prefix_mappings
    assert catalog.legacy_theme_mappings
    assert all(target in nodes for _, target in catalog.legacy_prefix_mappings)
    assert all(target in facet_values for _, target in catalog.legacy_theme_mappings)
    assert any(source == "uncategorized" for source, _ in catalog.legacy_prefix_mappings)


def test_generated_snapshot_and_migration_are_current_and_complete() -> None:
    catalog = load_catalog(SOURCE)
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    migration = MIGRATION.read_text(encoding="utf-8")

    assert snapshot == render_snapshot(catalog)
    assert migration == render_migration(catalog)
    assert snapshot["content_hash"] == catalog.content_hash
    assert all(len(node["reporting_levels"]) == 6 for node in snapshot["nodes"])
    assert "create table if not exists taxonomy_versions" in migration.lower()
    assert "create table if not exists taxonomy_node_closure" in migration.lower()
    assert "create table if not exists transaction_item_classification_history" in migration.lower()
    assert "force row level security" in migration.lower()
    assert "enforce_transaction_item_taxonomy_node" in migration
    assert "record_taxonomy_classification_history" in migration


def test_compiler_check_mode_detects_no_generated_drift() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/compile_taxonomy.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
