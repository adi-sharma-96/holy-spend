from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "taxonomy" / "v2" / "taxonomy.yaml"
DEFAULT_MIGRATION = ROOT / "supabase" / "migrations" / "0013_taxonomy_v2.sql"
DEFAULT_SNAPSHOT = ROOT / "taxonomy" / "v2" / "taxonomy.generated.json"
DEFAULT_WIDGET_SNAPSHOT = ROOT / "widget" / "src" / "taxonomy.generated.ts"
NAMESPACE = UUID("bf82066d-e6b2-4b44-a6c5-4e15950b8b53")
KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
TRANSACTION_TYPES = {"expense", "refund", "income", "transfer"}


@dataclass(frozen=True)
class Node:
    id: UUID
    stable_key: str
    local_key: str
    name: str
    description: str
    parent_key: str | None
    level: int
    sort_order: int
    is_assignable: bool
    allowed_transaction_types: tuple[str, ...]
    synonyms: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class FacetValue:
    id: UUID
    facet_key: str
    stable_key: str
    name: str
    description: str
    sort_order: int


@dataclass(frozen=True)
class Facet:
    id: UUID
    stable_key: str
    name: str
    description: str
    selection_mode: str
    values: tuple[FacetValue, ...]


@dataclass(frozen=True)
class Catalog:
    version: str
    version_id: UUID
    content_hash: str
    level_names: tuple[str, ...]
    nodes: tuple[Node, ...]
    facets: tuple[Facet, ...]
    legacy_prefix_mappings: tuple[tuple[str, str], ...]
    legacy_theme_mappings: tuple[tuple[str, str], ...]


def _canonical_hash(raw: dict[str, Any]) -> str:
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_local_key(value: object, context: str) -> str:
    if not isinstance(value, str) or not KEY_PATTERN.fullmatch(value):
        raise ValueError(f"{context} key must match {KEY_PATTERN.pattern}: {value!r}")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value.strip()


def load_catalog(path: Path = DEFAULT_SOURCE) -> Catalog:
    raw_value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw_value, dict):
        raise ValueError("taxonomy source must be a mapping")
    raw: dict[str, Any] = raw_value

    version = _string(raw.get("version"), "version")
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("version must use semantic x.y.z form")
    levels_value = raw.get("levels")
    if not isinstance(levels_value, list) or len(levels_value) != 6:
        raise ValueError("levels must contain exactly six reporting levels")
    level_names = tuple(_string(value, "level name") for value in levels_value)

    nodes: list[Node] = []
    seen_keys: set[str] = set()

    def visit(
        entries: object,
        *,
        parent_key: str | None,
        parent_allowed: tuple[str, ...],
        level: int,
    ) -> None:
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"children for {parent_key or 'root'} must be a non-empty list")
        if level > len(level_names):
            raise ValueError(f"taxonomy exceeds maximum depth at {parent_key}")
        for index, entry_value in enumerate(entries, start=1):
            if not isinstance(entry_value, dict):
                raise ValueError(f"node under {parent_key or 'root'} must be a mapping")
            entry: dict[str, Any] = entry_value
            local_key = _validate_local_key(entry.get("key"), f"node under {parent_key or 'root'}")
            stable_key = f"{parent_key}.{local_key}" if parent_key else local_key
            if stable_key in seen_keys:
                raise ValueError(f"duplicate taxonomy key: {stable_key}")
            seen_keys.add(stable_key)
            name = _string(entry.get("name"), stable_key)
            description = _string(entry.get("description", name), f"{stable_key}.description")
            children = entry.get("children")
            has_children = children is not None
            allowed_value = entry.get("transaction_types")
            if allowed_value is None:
                allowed = parent_allowed
            else:
                if not isinstance(allowed_value, list) or not allowed_value:
                    raise ValueError(f"{stable_key}.transaction_types must be a non-empty list")
                allowed = tuple(_string(value, f"{stable_key}.transaction_types") for value in allowed_value)
                unknown = sorted(set(allowed) - TRANSACTION_TYPES)
                if unknown:
                    raise ValueError(f"{stable_key} has unknown transaction types: {', '.join(unknown)}")
            synonyms_value = entry.get("synonyms", [])
            if not isinstance(synonyms_value, list):
                raise ValueError(f"{stable_key}.synonyms must be a list")
            synonyms = tuple(_string(value, f"{stable_key}.synonyms") for value in synonyms_value)
            metadata_value = entry.get("metadata", {})
            if not isinstance(metadata_value, dict):
                raise ValueError(f"{stable_key}.metadata must be a mapping")
            explicit_assignable = entry.get("assignable")
            inferred_assignable = not has_children
            if explicit_assignable is not None and bool(explicit_assignable) != inferred_assignable:
                raise ValueError(
                    f"{stable_key}.assignable must match leaf status; internal nodes are never assignable"
                )
            nodes.append(
                Node(
                    id=uuid5(NAMESPACE, f"taxonomy:{version}:{stable_key}"),
                    stable_key=stable_key,
                    local_key=local_key,
                    name=name,
                    description=description,
                    parent_key=parent_key,
                    level=level,
                    sort_order=int(entry.get("sort_order", index * 10)),
                    is_assignable=inferred_assignable,
                    allowed_transaction_types=allowed,
                    synonyms=synonyms,
                    metadata=dict(metadata_value),
                )
            )
            if has_children:
                visit(children, parent_key=stable_key, parent_allowed=allowed, level=level + 1)

    root_nodes = raw.get("nodes")
    visit(root_nodes, parent_key=None, parent_allowed=("expense", "refund"), level=1)

    facets_value = raw.get("facets", [])
    if not isinstance(facets_value, list):
        raise ValueError("facets must be a list")
    facets: list[Facet] = []
    seen_facets: set[str] = set()
    seen_facet_values: set[str] = set()
    for facet_value in facets_value:
        if not isinstance(facet_value, dict):
            raise ValueError("facet must be a mapping")
        facet_key = _validate_local_key(facet_value.get("key"), "facet")
        if facet_key in seen_facets:
            raise ValueError(f"duplicate facet key: {facet_key}")
        seen_facets.add(facet_key)
        selection_mode = str(facet_value.get("selection_mode", "multiple"))
        if selection_mode not in {"single", "multiple"}:
            raise ValueError(f"{facet_key}.selection_mode must be single or multiple")
        values_value = facet_value.get("values")
        if not isinstance(values_value, list) or not values_value:
            raise ValueError(f"{facet_key}.values must be a non-empty list")
        values: list[FacetValue] = []
        for value_index, item_value in enumerate(values_value, start=1):
            if not isinstance(item_value, dict):
                raise ValueError(f"{facet_key} value must be a mapping")
            local_value_key = _validate_local_key(item_value.get("key"), f"{facet_key} value")
            stable_value_key = f"{facet_key}.{local_value_key}"
            if stable_value_key in seen_facet_values:
                raise ValueError(f"duplicate facet value: {stable_value_key}")
            seen_facet_values.add(stable_value_key)
            values.append(
                FacetValue(
                    id=uuid5(NAMESPACE, f"facet-value:{stable_value_key}"),
                    facet_key=facet_key,
                    stable_key=stable_value_key,
                    name=_string(item_value.get("name"), stable_value_key),
                    description=_string(
                        item_value.get("description", item_value.get("name")),
                        f"{stable_value_key}.description",
                    ),
                    sort_order=int(item_value.get("sort_order", value_index * 10)),
                )
            )
        facets.append(
            Facet(
                id=uuid5(NAMESPACE, f"facet:{facet_key}"),
                stable_key=facet_key,
                name=_string(facet_value.get("name"), facet_key),
                description=_string(
                    facet_value.get("description", facet_value.get("name")),
                    f"{facet_key}.description",
                ),
                selection_mode=selection_mode,
                values=tuple(values),
            )
        )

    node_keys = {node.stable_key for node in nodes}
    facet_value_keys = {
        value.stable_key for facet in facets for value in facet.values
    }

    def mappings(name: str, valid_targets: set[str]) -> tuple[tuple[str, str], ...]:
        value = raw.get(name, [])
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")
        result: list[tuple[str, str]] = []
        seen_sources: set[str] = set()
        for entry in value:
            if not isinstance(entry, dict):
                raise ValueError(f"{name} entry must be a mapping")
            source = _string(entry.get("source"), f"{name}.source")
            target = _string(entry.get("target"), f"{name}.target")
            if source in seen_sources:
                raise ValueError(f"duplicate {name} source: {source}")
            if target not in valid_targets:
                raise ValueError(f"{name} target does not exist: {target}")
            seen_sources.add(source)
            result.append((source, target))
        return tuple(result)

    legacy_prefix_mappings = mappings("legacy_prefix_mappings", node_keys)
    if not any(source in {"miscellaneous", "uncategorized"} for source, _ in legacy_prefix_mappings):
        raise ValueError("legacy mappings must include an uncategorized fallback")
    legacy_theme_mappings = mappings("legacy_theme_mappings", facet_value_keys)

    return Catalog(
        version=version,
        version_id=uuid5(NAMESPACE, f"taxonomy-version:{version}"),
        content_hash=_canonical_hash(raw),
        level_names=level_names,
        nodes=tuple(nodes),
        facets=tuple(facets),
        legacy_prefix_mappings=legacy_prefix_mappings,
        legacy_theme_mappings=legacy_theme_mappings,
    )


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_uuid(value: UUID) -> str:
    return f"'{value}'::uuid"


def _sql_json(value: Any) -> str:
    return _sql_string(json.dumps(value, sort_keys=True, separators=(",", ":"))) + "::jsonb"


def _values(rows: Sequence[Sequence[str]], indent: str = "    ") -> str:
    return ",\n".join(indent + "(" + ", ".join(row) + ")" for row in rows)


def render_snapshot(catalog: Catalog) -> dict[str, Any]:
    parents = {node.stable_key: node for node in catalog.nodes}
    rendered_nodes: list[dict[str, Any]] = []
    for node in catalog.nodes:
        path: list[Node] = []
        cursor: Node | None = node
        while cursor is not None:
            path.append(cursor)
            cursor = parents.get(cursor.parent_key) if cursor.parent_key else None
        path.reverse()
        levels: list[dict[str, Any] | None] = [
            {"key": item.stable_key, "name": item.name} for item in path
        ]
        levels.extend([None] * (6 - len(levels)))
        rendered_nodes.append(
            {
                "id": str(node.id),
                "stable_key": node.stable_key,
                "parent_key": node.parent_key,
                "name": node.name,
                "description": node.description,
                "level": node.level,
                "sort_order": node.sort_order,
                "is_assignable": node.is_assignable,
                "allowed_transaction_types": list(node.allowed_transaction_types),
                "path": [
                    {
                        "id": str(item.id),
                        "stable_key": item.stable_key,
                        "level": item.level,
                        "level_name": catalog.level_names[item.level - 1],
                        "name": item.name,
                    }
                    for item in path
                ],
                "reporting_levels": levels,
                "synonyms": list(node.synonyms),
                "metadata": node.metadata,
            }
        )
    return {
        "version": catalog.version,
        "version_id": str(catalog.version_id),
        "content_hash": catalog.content_hash,
        "levels": list(catalog.level_names),
        "nodes": rendered_nodes,
        "facets": [
            {
                "id": str(facet.id),
                "stable_key": facet.stable_key,
                "name": facet.name,
                "description": facet.description,
                "selection_mode": facet.selection_mode,
                "values": [
                    {
                        "id": str(value.id),
                        "stable_key": value.stable_key,
                        "name": value.name,
                        "description": value.description,
                        "sort_order": value.sort_order,
                    }
                    for value in facet.values
                ],
            }
            for facet in catalog.facets
        ],
    }


def render_migration(catalog: Catalog) -> str:
    nodes_by_key = {node.stable_key: node for node in catalog.nodes}
    fallback_node = nodes_by_key["unclassified.needs_review"]
    node_rows: list[tuple[str, ...]] = []
    for node in catalog.nodes:
        parent_id = (
            _sql_uuid(nodes_by_key[node.parent_key].id)
            if node.parent_key is not None
            else "null"
        )
        transaction_types = (
            "array["
            + ", ".join(_sql_string(value) for value in node.allowed_transaction_types)
            + "]::transaction_type[]"
        )
        node_rows.append(
            (
                _sql_uuid(node.id),
                _sql_uuid(catalog.version_id),
                _sql_string(node.stable_key),
                parent_id,
                str(node.level),
                _sql_string(node.name),
                _sql_string(node.description),
                str(node.sort_order),
                str(node.is_assignable).lower(),
                transaction_types,
                _sql_json(node.metadata),
            )
        )

    closure_rows: list[tuple[str, ...]] = []
    for descendant in catalog.nodes:
        distance = 0
        cursor: Node | None = descendant
        while cursor is not None:
            closure_rows.append(
                (
                    _sql_uuid(catalog.version_id),
                    _sql_uuid(cursor.id),
                    _sql_uuid(descendant.id),
                    str(distance),
                )
            )
            cursor = nodes_by_key.get(cursor.parent_key) if cursor.parent_key else None
            distance += 1

    synonym_rows = [
        (
            _sql_uuid(catalog.version_id),
            _sql_uuid(node.id),
            _sql_string(synonym),
            _sql_string("en"),
        )
        for node in catalog.nodes
        for synonym in node.synonyms
    ]
    facet_rows = [
        (
            _sql_uuid(facet.id),
            _sql_string(facet.stable_key),
            _sql_string(facet.name),
            _sql_string(facet.description),
            _sql_string(facet.selection_mode),
        )
        for facet in catalog.facets
    ]
    facet_value_rows = [
        (
            _sql_uuid(value.id),
            _sql_uuid(facet.id),
            _sql_string(value.stable_key),
            _sql_string(value.name),
            _sql_string(value.description),
            str(value.sort_order),
        )
        for facet in catalog.facets
        for value in facet.values
    ]
    legacy_prefix_rows = [
        (_sql_string(source), _sql_uuid(nodes_by_key[target].id))
        for source, target in catalog.legacy_prefix_mappings
    ]
    facet_values_by_key = {
        value.stable_key: value for facet in catalog.facets for value in facet.values
    }
    legacy_theme_rows = [
        (_sql_string(source), _sql_uuid(facet_values_by_key[target].id))
        for source, target in catalog.legacy_theme_mappings
    ]
    level_json = _sql_json(list(catalog.level_names))

    sql = f"""-- Generated by scripts/compile_taxonomy.py from taxonomy/v2/taxonomy.yaml.
-- Content hash: {catalog.content_hash}
-- Do not hand-edit this migration; change the canonical YAML and regenerate.

begin;

do $$
begin
    if not exists (select 1 from pg_type where typname = 'taxonomy_version_status') then
        create type taxonomy_version_status as enum ('draft', 'active', 'retired');
    end if;
    if not exists (select 1 from pg_type where typname = 'taxonomy_selection_mode') then
        create type taxonomy_selection_mode as enum ('single', 'multiple');
    end if;
    if not exists (select 1 from pg_type where typname = 'taxonomy_classification_source') then
        create type taxonomy_classification_source as enum ('user', 'alias', 'model', 'migration');
    end if;
    if not exists (select 1 from pg_type where typname = 'taxonomy_review_status') then
        create type taxonomy_review_status as enum ('reviewed', 'suggested', 'needs_review');
    end if;
    if not exists (select 1 from pg_type where typname = 'transaction_classification_mode') then
        create type transaction_classification_mode as enum ('itemized', 'whole_bill', 'mixed');
    end if;
    if not exists (select 1 from pg_type where typname = 'transaction_item_role') then
        create type transaction_item_role as enum ('purchase', 'service', 'whole_bill');
    end if;
    if not exists (select 1 from pg_type where typname = 'ingestion_method') then
        create type ingestion_method as enum ('manual', 'receipt', 'email', 'provider_api', 'import');
    end if;
    if not exists (select 1 from pg_type where typname = 'purchase_channel') then
        create type purchase_channel as enum ('in_store', 'online', 'delivery', 'subscription', 'unknown');
    end if;
end;
$$;

create table if not exists taxonomy_versions (
    id uuid primary key,
    version text not null unique,
    content_hash text not null unique,
    status taxonomy_version_status not null,
    level_names jsonb not null,
    max_depth smallint not null check (max_depth between 1 and 6),
    activated_at timestamptz,
    created_at timestamptz not null default now(),
    constraint taxonomy_versions_semver check (version ~ '^\\d+\\.\\d+\\.\\d+$'),
    constraint taxonomy_versions_hash check (content_hash ~ '^[a-f0-9]{{64}}$')
);

create unique index if not exists taxonomy_versions_one_active_uidx
    on taxonomy_versions(status) where status = 'active';

create table if not exists taxonomy_nodes (
    id uuid primary key,
    version_id uuid not null references taxonomy_versions(id) on delete restrict,
    stable_key text not null,
    parent_id uuid references taxonomy_nodes(id) on delete restrict,
    level smallint not null check (level between 1 and 6),
    name text not null,
    description text not null,
    sort_order integer not null default 0,
    is_assignable boolean not null,
    allowed_transaction_types transaction_type[] not null,
    metadata jsonb not null default '{{}}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (version_id, stable_key),
    constraint taxonomy_nodes_key check (stable_key ~ '^[a-z0-9]+([._][a-z0-9]+)*$'),
    constraint taxonomy_nodes_allowed_types check (cardinality(allowed_transaction_types) > 0)
);

create index if not exists taxonomy_nodes_parent_idx on taxonomy_nodes(version_id, parent_id, sort_order);
create index if not exists taxonomy_nodes_assignable_idx
    on taxonomy_nodes(version_id, stable_key) where is_assignable = true;

create or replace function app.enforce_taxonomy_tree_shape()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
declare
    selected_parent taxonomy_nodes%rowtype;
begin
    if new.parent_id is null then
        if new.level <> 1 then
            raise exception using errcode = '23514',
                message = 'Root taxonomy nodes must be level 1.';
        end if;
        return new;
    end if;

    select * into selected_parent from taxonomy_nodes where id = new.parent_id;
    if not found
       or selected_parent.version_id <> new.version_id
       or new.level <> selected_parent.level + 1 then
        raise exception using errcode = '23514',
            message = 'Taxonomy parent must be in the same version and exactly one level above.';
    end if;
    return new;
end;
$$;

drop trigger if exists taxonomy_nodes_tree_shape on taxonomy_nodes;
create trigger taxonomy_nodes_tree_shape
before insert or update of version_id, parent_id, level on taxonomy_nodes
for each row execute function app.enforce_taxonomy_tree_shape();

create table if not exists taxonomy_node_closure (
    version_id uuid not null references taxonomy_versions(id) on delete cascade,
    ancestor_id uuid not null references taxonomy_nodes(id) on delete cascade,
    descendant_id uuid not null references taxonomy_nodes(id) on delete cascade,
    distance smallint not null check (distance >= 0),
    primary key (version_id, ancestor_id, descendant_id)
);

create index if not exists taxonomy_node_closure_descendant_idx
    on taxonomy_node_closure(version_id, descendant_id, distance);

create table if not exists taxonomy_synonyms (
    version_id uuid not null references taxonomy_versions(id) on delete cascade,
    node_id uuid not null references taxonomy_nodes(id) on delete cascade,
    term text not null,
    locale text not null default 'en',
    primary key (version_id, node_id, term, locale)
);

create index if not exists taxonomy_synonyms_search_idx
    on taxonomy_synonyms(version_id, lower(term));

create table if not exists taxonomy_redirects (
    id uuid primary key default gen_random_uuid(),
    from_version_id uuid not null references taxonomy_versions(id) on delete restrict,
    from_stable_key text not null,
    to_version_id uuid not null references taxonomy_versions(id) on delete restrict,
    to_node_id uuid not null references taxonomy_nodes(id) on delete restrict,
    reason text not null,
    created_at timestamptz not null default now(),
    unique (from_version_id, from_stable_key, to_version_id)
);

create table if not exists taxonomy_facets (
    id uuid primary key,
    stable_key text not null unique,
    name text not null,
    description text not null,
    selection_mode taxonomy_selection_mode not null,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists taxonomy_facet_values (
    id uuid primary key,
    facet_id uuid not null references taxonomy_facets(id) on delete restrict,
    stable_key text not null unique,
    name text not null,
    description text not null,
    sort_order integer not null default 0,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists taxonomy_facet_values_facet_idx
    on taxonomy_facet_values(facet_id, sort_order, stable_key);

insert into taxonomy_versions (
    id, version, content_hash, status, level_names, max_depth, activated_at
)
values (
    {_sql_uuid(catalog.version_id)}, {_sql_string(catalog.version)},
    {_sql_string(catalog.content_hash)}, 'active', {level_json}, 6, now()
)
on conflict (version) do update set
    content_hash = excluded.content_hash,
    status = excluded.status,
    level_names = excluded.level_names,
    max_depth = excluded.max_depth,
    activated_at = coalesce(taxonomy_versions.activated_at, excluded.activated_at);

insert into taxonomy_nodes (
    id, version_id, stable_key, parent_id, level, name, description,
    sort_order, is_assignable, allowed_transaction_types, metadata
)
values
{_values(node_rows)}
on conflict (version_id, stable_key) do update set
    parent_id = excluded.parent_id,
    level = excluded.level,
    name = excluded.name,
    description = excluded.description,
    sort_order = excluded.sort_order,
    is_assignable = excluded.is_assignable,
    allowed_transaction_types = excluded.allowed_transaction_types,
    metadata = excluded.metadata,
    updated_at = now();

insert into taxonomy_node_closure (version_id, ancestor_id, descendant_id, distance)
values
{_values(closure_rows)}
on conflict (version_id, ancestor_id, descendant_id) do update
set distance = excluded.distance;
"""
    if synonym_rows:
        sql += f"""

insert into taxonomy_synonyms (version_id, node_id, term, locale)
values
{_values(synonym_rows)}
on conflict do nothing;
"""
    sql += f"""

insert into taxonomy_facets (id, stable_key, name, description, selection_mode)
values
{_values(facet_rows)}
on conflict (stable_key) do update set
    name = excluded.name,
    description = excluded.description,
    selection_mode = excluded.selection_mode,
    is_active = true,
    updated_at = now();

insert into taxonomy_facet_values (
    id, facet_id, stable_key, name, description, sort_order
)
values
{_values(facet_value_rows)}
on conflict (stable_key) do update set
    facet_id = excluded.facet_id,
    name = excluded.name,
    description = excluded.description,
    sort_order = excluded.sort_order,
    is_active = true,
    updated_at = now();

create temporary table taxonomy_v2_legacy_prefix_rules (
    source_prefix text primary key,
    target_node_id uuid not null
) on commit drop;

insert into taxonomy_v2_legacy_prefix_rules (source_prefix, target_node_id)
values
{_values(legacy_prefix_rows)};

create table if not exists legacy_category_taxonomy_map (
    category_id uuid primary key references categories(id) on delete restrict,
    taxonomy_node_id uuid not null references taxonomy_nodes(id) on delete restrict,
    mapping_source text not null default 'prefix',
    created_at timestamptz not null default now()
);

insert into legacy_category_taxonomy_map (category_id, taxonomy_node_id)
select category.id, mapping.target_node_id
from categories category
cross join lateral (
    select rule.target_node_id
    from taxonomy_v2_legacy_prefix_rules rule
    where category.slug = rule.source_prefix
       or category.slug like rule.source_prefix || '.%'
    order by length(rule.source_prefix) desc
    limit 1
) mapping
on conflict (category_id) do update
set taxonomy_node_id = excluded.taxonomy_node_id;

do $$
begin
    if exists (
        select 1
        from categories category
        left join legacy_category_taxonomy_map mapping on mapping.category_id = category.id
        where category.is_active = true and mapping.category_id is null
    ) then
        raise exception 'Taxonomy v2 migration has unmapped active legacy categories.';
    end if;
end;
$$;

alter table transactions
    add column if not exists classification_mode transaction_classification_mode,
    add column if not exists ingestion_method ingestion_method,
    add column if not exists purchase_channel purchase_channel,
    add column if not exists provider_key text;

update transactions transaction
set classification_mode = case
        when (
            select count(*) from transaction_items item
            where item.transaction_id = transaction.id and item.user_id = transaction.user_id
        ) <= 1 then 'whole_bill'::transaction_classification_mode
        else 'itemized'::transaction_classification_mode
    end,
    ingestion_method = case transaction.source_type::text
        when 'manual' then 'manual'::ingestion_method
        when 'receipt' then 'receipt'::ingestion_method
        when 'email' then 'email'::ingestion_method
        when 'import' then 'import'::ingestion_method
        else 'provider_api'::ingestion_method
    end,
    purchase_channel = case transaction.source_type::text
        when 'instacart' then 'delivery'::purchase_channel
        when 'uber_eats' then 'delivery'::purchase_channel
        else 'unknown'::purchase_channel
    end,
    provider_key = case transaction.source_type::text
        when 'instacart' then 'instacart'
        when 'uber_eats' then 'uber_eats'
        else null
    end
where classification_mode is null
   or ingestion_method is null
   or purchase_channel is null;

alter table transactions
    alter column classification_mode set default 'itemized',
    alter column classification_mode set not null,
    alter column ingestion_method set not null,
    alter column purchase_channel set default 'unknown',
    alter column purchase_channel set not null;

alter table transactions drop constraint if exists transactions_provider_origin;
alter table transactions add constraint transactions_provider_origin check (
    ingestion_method <> 'provider_api' or provider_key is not null
);

alter table transaction_items
    add column if not exists taxonomy_node_id uuid references taxonomy_nodes(id) on delete restrict,
    add column if not exists item_role transaction_item_role,
    add column if not exists classification_source taxonomy_classification_source,
    add column if not exists classification_confidence numeric(5, 4),
    add column if not exists classification_review_status taxonomy_review_status,
    add column if not exists classification_reviewed_at timestamptz;

update transaction_items item
set taxonomy_node_id = coalesce(
        (
            select mapping.taxonomy_node_id
            from legacy_category_taxonomy_map mapping
            where mapping.category_id = item.category_id
        ),
        {_sql_uuid(fallback_node.id)}
    ),
    item_role = case transaction.classification_mode
        when 'whole_bill' then 'whole_bill'::transaction_item_role
        else 'purchase'::transaction_item_role
    end,
    classification_source = 'migration',
    classification_confidence = case
        when exists (
            select 1
            from legacy_category_taxonomy_map mapping
            where mapping.category_id = item.category_id
        ) then 1 else 0
    end,
    classification_review_status = case
        when coalesce(
            (
                select mapping.taxonomy_node_id
                from legacy_category_taxonomy_map mapping
                where mapping.category_id = item.category_id
            ),
            {_sql_uuid(fallback_node.id)}
        ) = {_sql_uuid(fallback_node.id)}
            then 'needs_review'::taxonomy_review_status
        else 'reviewed'::taxonomy_review_status
    end,
    classification_reviewed_at = case
        when coalesce(
            (
                select mapping.taxonomy_node_id
                from legacy_category_taxonomy_map mapping
                where mapping.category_id = item.category_id
            ),
            {_sql_uuid(fallback_node.id)}
        ) <> {_sql_uuid(fallback_node.id)}
            then coalesce(transaction.confirmed_at, item.updated_at)
        else null
    end
from transactions transaction
where transaction.id = item.transaction_id
  and transaction.user_id = item.user_id
  and item.taxonomy_node_id is null;

alter table transaction_items
    alter column category_id drop not null,
    alter column taxonomy_node_id set not null,
    alter column item_role set default 'purchase',
    alter column item_role set not null,
    alter column classification_source set default 'model',
    alter column classification_source set not null,
    alter column classification_review_status set default 'suggested',
    alter column classification_review_status set not null;

alter table transaction_items drop constraint if exists transaction_items_classification_confidence;
alter table transaction_items add constraint transaction_items_classification_confidence check (
    classification_confidence is null
    or (classification_confidence >= 0 and classification_confidence <= 1)
);

alter table product_concepts
    add column if not exists primary_taxonomy_node_id uuid references taxonomy_nodes(id) on delete restrict;

update product_concepts concept
set primary_taxonomy_node_id = coalesce(
    (
        select mapping.taxonomy_node_id
        from legacy_category_taxonomy_map mapping
        where mapping.category_id = concept.primary_category_id
    ),
    {_sql_uuid(fallback_node.id)}
)
where concept.primary_taxonomy_node_id is null;

alter table product_concepts alter column primary_category_id drop not null;

alter table user_product_aliases
    add column if not exists taxonomy_node_id uuid references taxonomy_nodes(id) on delete restrict;

update user_product_aliases alias
set taxonomy_node_id = mapping.taxonomy_node_id
from legacy_category_taxonomy_map mapping
where mapping.category_id = alias.category_id
  and alias.taxonomy_node_id is null;

alter table user_product_aliases drop constraint if exists user_product_aliases_target_present;
alter table user_product_aliases add constraint user_product_aliases_target_present check (
    concept_id is not null
    or variant_id is not null
    or category_id is not null
    or taxonomy_node_id is not null
);

create table if not exists transaction_item_classification_history (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    item_id uuid not null references transaction_items(id) on delete cascade,
    taxonomy_node_id uuid not null references taxonomy_nodes(id) on delete restrict,
    source taxonomy_classification_source not null,
    confidence numeric(5, 4),
    review_status taxonomy_review_status not null,
    reason text,
    created_at timestamptz not null default now(),
    constraint transaction_item_classification_history_confidence check (
        confidence is null or (confidence >= 0 and confidence <= 1)
    )
);

create index if not exists transaction_item_classification_history_item_idx
    on transaction_item_classification_history(user_id, item_id, created_at desc);

insert into transaction_item_classification_history (
    user_id, item_id, taxonomy_node_id, source, confidence, review_status, reason
)
select item.user_id, item.id, item.taxonomy_node_id, item.classification_source,
       item.classification_confidence, item.classification_review_status,
       'Taxonomy v2 migration'
from transaction_items item
where not exists (
    select 1 from transaction_item_classification_history history
    where history.item_id = item.id
);

create table if not exists transaction_item_facets (
    user_id uuid not null references auth.users(id) on delete cascade,
    item_id uuid not null references transaction_items(id) on delete cascade,
    facet_value_id uuid not null references taxonomy_facet_values(id) on delete restrict,
    source taxonomy_classification_source not null default 'model',
    confidence numeric(5, 4),
    created_at timestamptz not null default now(),
    primary key (item_id, facet_value_id),
    constraint transaction_item_facets_confidence check (
        confidence is null or (confidence >= 0 and confidence <= 1)
    )
);

create index if not exists transaction_item_facets_user_value_idx
    on transaction_item_facets(user_id, facet_value_id, item_id);

create or replace function app.enforce_transaction_item_facet_owner()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
    if not exists (
        select 1 from transaction_items item
        where item.id = new.item_id and item.user_id = new.user_id
    ) then
        raise exception using errcode = '23514',
            message = 'Facet assignment owner must match the transaction item owner.';
    end if;
    return new;
end;
$$;

drop trigger if exists transaction_item_facets_owner on transaction_item_facets;
create trigger transaction_item_facets_owner
before insert or update of user_id, item_id on transaction_item_facets
for each row execute function app.enforce_transaction_item_facet_owner();

create or replace function app.enforce_single_select_facet()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
declare
    selected_facet_id uuid;
    selected_mode taxonomy_selection_mode;
begin
    select value.facet_id, facet.selection_mode
    into selected_facet_id, selected_mode
    from taxonomy_facet_values value
    join taxonomy_facets facet on facet.id = value.facet_id
    where value.id = new.facet_value_id;

    if selected_mode = 'single'
       and exists (
           select 1
           from transaction_item_facets existing
           join taxonomy_facet_values existing_value
             on existing_value.id = existing.facet_value_id
           where existing.item_id = new.item_id
             and existing_value.facet_id = selected_facet_id
             and existing.facet_value_id <> new.facet_value_id
       ) then
        raise exception using errcode = '23505',
            message = 'A single-select facet may only have one value per transaction item.';
    end if;
    return new;
end;
$$;

drop trigger if exists transaction_item_facets_single_value on transaction_item_facets;
create trigger transaction_item_facets_single_value
before insert or update of item_id, facet_value_id on transaction_item_facets
for each row execute function app.enforce_single_select_facet();

create temporary table taxonomy_v2_legacy_theme_rules (
    theme_slug text primary key,
    facet_value_id uuid not null
) on commit drop;

insert into taxonomy_v2_legacy_theme_rules (theme_slug, facet_value_id)
values
{_values(legacy_theme_rows)};

insert into transaction_item_facets (
    user_id, item_id, facet_value_id, source, confidence
)
select item_theme.user_id, item_theme.item_id, mapping.facet_value_id,
       'migration'::taxonomy_classification_source, 1
from transaction_item_themes item_theme
join themes theme on theme.id = item_theme.theme_id
join taxonomy_v2_legacy_theme_rules mapping on mapping.theme_slug = theme.slug
on conflict (item_id, facet_value_id) do nothing;

create or replace function app.enforce_assignable_taxonomy_node()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
declare
    selected_assignable boolean;
    selected_version_status taxonomy_version_status;
begin
    select node.is_assignable, version.status
    into selected_assignable, selected_version_status
    from taxonomy_nodes node
    join taxonomy_versions version on version.id = node.version_id
    where node.id = new.taxonomy_node_id;

    if not found or selected_assignable is not true
       or selected_version_status <> 'active' then
        raise exception using
            errcode = '23514',
            message = format(
                'Taxonomy node %s must be an assignable node in the active taxonomy.',
                new.taxonomy_node_id
            );
    end if;

    return new;
end;
$$;

drop trigger if exists transaction_items_assignable_taxonomy on transaction_items;
create or replace function app.enforce_transaction_item_taxonomy_node()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
    if not exists (
        select 1
        from taxonomy_nodes node
        join taxonomy_versions version
          on version.id = node.version_id and version.status = 'active'
        join transactions transaction
          on transaction.id = new.transaction_id and transaction.user_id = new.user_id
        where node.id = new.taxonomy_node_id
          and node.is_assignable = true
          and transaction.transaction_type = any(node.allowed_transaction_types)
    ) then
        raise exception using errcode = '23514',
            message = 'Transaction item taxonomy must be active, assignable, and compatible with its transaction type.';
    end if;
    return new;
end;
$$;

create trigger transaction_items_assignable_taxonomy
before insert or update of taxonomy_node_id, transaction_id, user_id on transaction_items
for each row execute function app.enforce_transaction_item_taxonomy_node();

drop trigger if exists user_product_aliases_assignable_taxonomy on user_product_aliases;
create trigger user_product_aliases_assignable_taxonomy
before insert or update of taxonomy_node_id on user_product_aliases
for each row
when (new.taxonomy_node_id is not null)
execute function app.enforce_assignable_taxonomy_node();

drop trigger if exists product_concepts_assignable_taxonomy on product_concepts;
create trigger product_concepts_assignable_taxonomy
before insert or update of primary_taxonomy_node_id on product_concepts
for each row
when (new.primary_taxonomy_node_id is not null)
execute function app.enforce_assignable_taxonomy_node();

create or replace function app.record_taxonomy_classification_history()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
    if tg_op = 'INSERT'
       or old.taxonomy_node_id is distinct from new.taxonomy_node_id
       or old.classification_source is distinct from new.classification_source
       or old.classification_confidence is distinct from new.classification_confidence
       or old.classification_review_status is distinct from new.classification_review_status then
        insert into transaction_item_classification_history (
            user_id, item_id, taxonomy_node_id, source, confidence, review_status, reason
        )
        values (
            new.user_id, new.id, new.taxonomy_node_id, new.classification_source,
            new.classification_confidence, new.classification_review_status,
            case when tg_op = 'INSERT' then 'Initial classification' else 'Classification changed' end
        );
    end if;
    return new;
end;
$$;

drop trigger if exists transaction_items_record_taxonomy_history on transaction_items;
create trigger transaction_items_record_taxonomy_history
after insert or update of taxonomy_node_id, classification_source,
    classification_confidence, classification_review_status
on transaction_items
for each row execute function app.record_taxonomy_classification_history();

alter table taxonomy_versions enable row level security;
alter table taxonomy_versions force row level security;
alter table taxonomy_nodes enable row level security;
alter table taxonomy_nodes force row level security;
alter table taxonomy_node_closure enable row level security;
alter table taxonomy_node_closure force row level security;
alter table taxonomy_synonyms enable row level security;
alter table taxonomy_synonyms force row level security;
alter table taxonomy_redirects enable row level security;
alter table taxonomy_redirects force row level security;
alter table taxonomy_facets enable row level security;
alter table taxonomy_facets force row level security;
alter table taxonomy_facet_values enable row level security;
alter table taxonomy_facet_values force row level security;
alter table legacy_category_taxonomy_map enable row level security;
alter table legacy_category_taxonomy_map force row level security;
alter table transaction_item_classification_history enable row level security;
alter table transaction_item_classification_history force row level security;
alter table transaction_item_facets enable row level security;
alter table transaction_item_facets force row level security;

drop policy if exists taxonomy_versions_read_with_app_context on taxonomy_versions;
create policy taxonomy_versions_read_with_app_context on taxonomy_versions
    for select using (app.current_user_id() is not null);
drop policy if exists taxonomy_nodes_read_with_app_context on taxonomy_nodes;
create policy taxonomy_nodes_read_with_app_context on taxonomy_nodes
    for select using (app.current_user_id() is not null);
drop policy if exists taxonomy_node_closure_read_with_app_context on taxonomy_node_closure;
create policy taxonomy_node_closure_read_with_app_context on taxonomy_node_closure
    for select using (app.current_user_id() is not null);
drop policy if exists taxonomy_synonyms_read_with_app_context on taxonomy_synonyms;
create policy taxonomy_synonyms_read_with_app_context on taxonomy_synonyms
    for select using (app.current_user_id() is not null);
drop policy if exists taxonomy_redirects_read_with_app_context on taxonomy_redirects;
create policy taxonomy_redirects_read_with_app_context on taxonomy_redirects
    for select using (app.current_user_id() is not null);
drop policy if exists taxonomy_facets_read_with_app_context on taxonomy_facets;
create policy taxonomy_facets_read_with_app_context on taxonomy_facets
    for select using (app.current_user_id() is not null and is_active = true);
drop policy if exists taxonomy_facet_values_read_with_app_context on taxonomy_facet_values;
create policy taxonomy_facet_values_read_with_app_context on taxonomy_facet_values
    for select using (app.current_user_id() is not null and is_active = true);
drop policy if exists legacy_category_taxonomy_map_read_with_app_context on legacy_category_taxonomy_map;
create policy legacy_category_taxonomy_map_read_with_app_context on legacy_category_taxonomy_map
    for select using (app.current_user_id() is not null);
drop policy if exists transaction_item_classification_history_crud_own
    on transaction_item_classification_history;
create policy transaction_item_classification_history_crud_own
    on transaction_item_classification_history
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());
drop policy if exists transaction_item_facets_crud_own on transaction_item_facets;
create policy transaction_item_facets_crud_own on transaction_item_facets
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'expense_app') then
        grant usage on type taxonomy_version_status, taxonomy_selection_mode,
            taxonomy_classification_source, taxonomy_review_status,
            transaction_classification_mode, transaction_item_role,
            ingestion_method, purchase_channel to expense_app;
        grant select on taxonomy_versions, taxonomy_nodes, taxonomy_node_closure,
            taxonomy_synonyms, taxonomy_redirects, taxonomy_facets,
            taxonomy_facet_values, legacy_category_taxonomy_map to expense_app;
        grant select, insert, update, delete on transaction_item_classification_history,
            transaction_item_facets to expense_app;
        grant execute on function app.enforce_assignable_taxonomy_node() to expense_app;
        grant execute on function app.enforce_transaction_item_taxonomy_node() to expense_app;
        grant execute on function app.enforce_taxonomy_tree_shape() to expense_app;
        grant execute on function app.enforce_transaction_item_facet_owner() to expense_app;
        grant execute on function app.enforce_single_select_facet() to expense_app;
        grant execute on function app.record_taxonomy_classification_history() to expense_app;
    end if;
end;
$$;

commit;
"""
    return sql


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and compile the canonical taxonomy catalog.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--migration", type=Path, default=DEFAULT_MIGRATION)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--widget-snapshot", type=Path, default=DEFAULT_WIDGET_SNAPSHOT)
    parser.add_argument("--check", action="store_true", help="Validate generated files without writing them.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = load_catalog(args.source)
    migration = render_migration(catalog)
    snapshot_value = render_snapshot(catalog)
    snapshot = json.dumps(snapshot_value, indent=2, ensure_ascii=False) + "\n"
    widget_snapshot = (
        "// Generated by scripts/compile_taxonomy.py. Do not edit by hand.\n"
        "export const TAXONOMY_V2 = "
        + json.dumps(snapshot_value, indent=2, ensure_ascii=False)
        + " as const;\n"
    )
    if args.check:
        expected = {
            args.migration: migration,
            args.snapshot: snapshot,
            args.widget_snapshot: widget_snapshot,
        }
        mismatches = [
            str(path)
            for path, content in expected.items()
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        if mismatches:
            raise SystemExit("Generated taxonomy artifacts are stale: " + ", ".join(mismatches))
    else:
        args.migration.parent.mkdir(parents=True, exist_ok=True)
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.widget_snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.migration.write_text(migration, encoding="utf-8", newline="\n")
        args.snapshot.write_text(snapshot, encoding="utf-8", newline="\n")
        args.widget_snapshot.write_text(widget_snapshot, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "version": catalog.version,
                "content_hash": catalog.content_hash,
                "nodes": len(catalog.nodes),
                "assignable_nodes": sum(node.is_assignable for node in catalog.nodes),
                "facets": len(catalog.facets),
                "facet_values": sum(len(facet.values) for facet in catalog.facets),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
