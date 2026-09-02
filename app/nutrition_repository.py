from collections import defaultdict
from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.dashboard import dashboard_window
from app.nutrition_identity import PRODUCE_TAXONOMY_PREFIX, nutrition_identity_key
from app.nutrition_score import compute_nutriscore, default_fvl_percent
from app.plugin_models import (
    NutritionCategoryGroup,
    NutritionGradeBucket,
    NutritionItem,
    NutritionLookupMatch,
    NutritionQueueItem,
    NutritionQueueResponse,
    NutritionResultInput,
    NutritionResultResponse,
    NutritionSignal,
    NutritionSummary,
    NutritionSummaryRequest,
    SearchNutritionLookupsRequest,
    SearchNutritionLookupsResponse,
)

GROCERY_TAXONOMY_PREFIX = "food_dining.groceries."
NO_MATCH_MAX_ATTEMPTS = 5
PERCENT_QUANTUM = Decimal("0.1")
GRADE_POINTS = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
POINTS_GRADE = {value: key for key, value in GRADE_POINTS.items()}
NUTRITION_MAX_ITEM_WEIGHT_SHARE = Decimal("0.35")
NUTRITION_HIGH_CONFIDENCE_MIN_ITEMS = 8
NUTRITION_HIGH_CONFIDENCE_MIN_COVERAGE = Decimal("50")
NUTRITION_REPORTING_LEVEL = 3


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


class NutritionRepository:
    def __init__(self, conn: Any, user_id: UUID) -> None:
        self.conn = conn
        self.user_id = user_id

    def get_queue(self, limit: int) -> NutritionQueueResponse:
        expired = self._expire_out_of_scope()
        enqueued = self._enqueue_new()
        rows = self.conn.execute(
            """
            select id, product_name, brand
            from nutrition_lookups
            where owner_user_id = %(user_id)s
              and (
                  (status = 'pending' and next_attempt_at <= now())
                  or (status = 'no_match' and attempts < %(max_attempts)s)
              )
            order by next_attempt_at asc
            limit %(limit)s
            """,
            {"user_id": self.user_id, "limit": limit, "max_attempts": NO_MATCH_MAX_ATTEMPTS},
        ).fetchall()
        items = [
            NutritionQueueItem(id=row["id"], product_name=row["product_name"], brand=row["brand"])
            for row in rows
        ]
        return NutritionQueueResponse(enqueued=enqueued, expired=expired, items=items)

    def _expire_out_of_scope(self) -> int:
        # A row created while an item was classified under groceries stays keyed by
        # identity_key forever - it's never re-checked against the item's CURRENT
        # classification. If every purchase-item that ever produced this identity has
        # since been reclassified out of food_dining.groceries.* (e.g. "cinema
        # popcorn" corrected from a grocery guess to eating_out.quick_service), the
        # row is stale: nothing will ever again justify it being in the queue, so it
        # gets retried forever for a product that was never really groceries. Only
        # pending/no_match rows are removed - matched rows are left alone since
        # they're harmless (get_summary() already filters by current classification
        # independently, so a stray matched row is never shown) and deleting real
        # fetched nutrition data isn't something to do silently.
        result = self.conn.execute(
            """
            delete from nutrition_lookups nl
            where nl.owner_user_id = %(user_id)s
              and nl.status in ('pending', 'no_match')
              and not exists (
                  select 1
                  from transaction_items item
                  join transactions t on t.id = item.transaction_id
                  join taxonomy_nodes node on node.id = item.taxonomy_node_id
                  where item.user_id = nl.owner_user_id
                    and t.status = 'confirmed'
                    and node.stable_key like %(grocery_prefix)s
                    and item.normalized_name is not null
                    and item.normalized_name <> ''
                    and (
                        trim(both '-' from regexp_replace(lower(item.normalized_name), '[^a-z0-9]+', '-', 'g'))
                            || '::' ||
                            trim(both '-' from regexp_replace(
                                lower(case when node.stable_key like %(produce_prefix)s
                                      then '' else coalesce(item.brand, '') end),
                                '[^a-z0-9]+', '-', 'g'
                            ))
                    ) = nl.identity_key
              )
            """,
            {
                "user_id": self.user_id,
                "grocery_prefix": f"{GROCERY_TAXONOMY_PREFIX}%",
                "produce_prefix": f"{PRODUCE_TAXONOMY_PREFIX}%",
            },
        )
        return int(result.rowcount)

    def search_lookups(self, request: SearchNutritionLookupsRequest) -> SearchNutritionLookupsResponse:
        # get_nutrition_queue only ever returns pending/no_match rows, so once an
        # item is matched there's no way to find its nutrition_lookups.id again -
        # and save_nutrition_result requires that exact id to correct a wrong or
        # thin match (e.g. a source-stated grade saved with no real macros behind
        # it). This is a real substring search across every status so a bad match
        # can be found and fixed, not just new/failed items.
        escaped = request.query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        rows = self.conn.execute(
            """
            /* nutrition:search-lookups */
            select id, product_name, brand, status, category_slug,
                   matched_product_name, source, nutriscore_grade, attempts
            from nutrition_lookups
            where owner_user_id = %(user_id)s
              and (product_name ilike %(pattern)s escape '\\' or brand ilike %(pattern)s escape '\\')
            order by updated_at desc
            limit %(limit)s
            """,
            {"user_id": self.user_id, "pattern": pattern, "limit": request.limit},
        ).fetchall()
        items = [
            NutritionLookupMatch(
                id=row["id"],
                product_name=row["product_name"],
                brand=row["brand"],
                status=row["status"],
                category_slug=row["category_slug"],
                matched_product_name=row["matched_product_name"],
                source=row["source"],
                nutriscore_grade=row["nutriscore_grade"],
                attempts=row["attempts"],
            )
            for row in rows
        ]
        return SearchNutritionLookupsResponse(query=request.query, items=items)

    def _enqueue_new(self) -> int:
        result = self.conn.execute(
            """
            insert into nutrition_lookups (owner_user_id, identity_key, product_name, brand, category_slug)
            select distinct
                item.user_id,
                trim(both '-' from regexp_replace(lower(item.normalized_name), '[^a-z0-9]+', '-', 'g'))
                    || '::' ||
                    trim(both '-' from regexp_replace(
                        lower(case when node.stable_key like %(produce_prefix)s
                              then '' else coalesce(item.brand, '') end),
                        '[^a-z0-9]+', '-', 'g'
                    )),
                item.normalized_name,
                item.brand,
                node.stable_key
            from transaction_items item
            join transactions t on t.id = item.transaction_id
            join taxonomy_nodes node on node.id = item.taxonomy_node_id
            where item.user_id = %(user_id)s
              and t.status = 'confirmed'
              and node.stable_key like %(grocery_prefix)s
              and item.normalized_name is not null
              and item.normalized_name <> ''
            on conflict (owner_user_id, identity_key) do nothing
            """,
            {
                "user_id": self.user_id,
                "grocery_prefix": f"{GROCERY_TAXONOMY_PREFIX}%",
                "produce_prefix": f"{PRODUCE_TAXONOMY_PREFIX}%",
            },
        )
        return int(result.rowcount)

    def save_result(self, payload: NutritionResultInput) -> NutritionResultResponse:
        if payload.matched:
            nutriments = payload.nutriments.to_per_100g() if payload.nutriments else {}
            category_row = self.conn.execute(
                "select category_slug from nutrition_lookups where id = %(item_id)s and owner_user_id = %(user_id)s",
                {"item_id": payload.item_id, "user_id": self.user_id},
            ).fetchone()
            category_slug = (category_row["category_slug"] if category_row else None) or ""

            computed = compute_nutriscore(
                category_slug=category_slug,
                energy_kcal_100g=nutriments.get("energy_kcal_100g"),
                sugars_100g=nutriments.get("sugars_100g"),
                saturated_fat_100g=nutriments.get("saturated_fat_100g"),
                sodium_mg_100g=nutriments.get("sodium_mg_100g"),
                fiber_100g=nutriments.get("fiber_100g"),
                protein_100g=nutriments.get("protein_100g"),
                fvl_percent=payload.fvl_percent,
                fat_100g=nutriments.get("fat_100g"),
                contains_nonnutritive_sweeteners=payload.contains_nonnutritive_sweeteners,
            )
            if computed is not None:
                nutriscore_grade: str | None = computed.grade
                nutriscore_source: str | None = "computed"
                fvl_percent = (
                    payload.fvl_percent
                    if payload.fvl_percent is not None
                    else default_fvl_percent(category_slug)
                )
            elif payload.nutriscore_grade is not None:
                nutriscore_grade = payload.nutriscore_grade
                nutriscore_source = "source_stated"
                fvl_percent = None
            else:
                nutriscore_grade = None
                nutriscore_source = None
                fvl_percent = None

            self.conn.execute(
                """
                update nutrition_lookups
                set status = 'matched', matched_product_name = %(product_name)s, source = %(source)s,
                    source_ref = %(source_ref)s, nutriments = %(nutriments)s,
                    nutriscore_grade = %(nutriscore_grade)s, nutriscore_source = %(nutriscore_source)s,
                    fvl_percent = %(fvl_percent)s, nova_group = %(nova_group)s,
                    nova_group_estimated = %(nova_group_estimated)s,
                    match_confidence = %(confidence)s, last_error = null,
                    serving_size_g = %(serving_size_g)s, serving_label = %(serving_label)s
                where id = %(item_id)s and owner_user_id = %(user_id)s
                """,
                {
                    "item_id": payload.item_id,
                    "user_id": self.user_id,
                    "product_name": payload.product_name,
                    "source": payload.source,
                    "source_ref": payload.source_ref,
                    "nutriments": Jsonb(nutriments),
                    "nutriscore_grade": nutriscore_grade,
                    "nutriscore_source": nutriscore_source,
                    "fvl_percent": fvl_percent,
                    "nova_group": payload.nova_group,
                    "nova_group_estimated": payload.nova_group_estimated,
                    "confidence": payload.confidence,
                    "serving_size_g": payload.nutriments.serving_size_g if payload.nutriments else None,
                    "serving_label": payload.nutriments.serving_label if payload.nutriments else None,
                },
            )
            return NutritionResultResponse(status="matched")

        self.conn.execute(
            """
            update nutrition_lookups
            set status = 'no_match', attempts = attempts + 1,
                matched_product_name = null, source = null, source_ref = null, nutriments = null,
                nutriscore_grade = null, nutriscore_source = null, fvl_percent = null,
                nova_group = null, nova_group_estimated = false, match_confidence = null,
                serving_size_g = null, serving_label = null
            where id = %(item_id)s and owner_user_id = %(user_id)s
            """,
            {"item_id": payload.item_id, "user_id": self.user_id},
        )
        return NutritionResultResponse(status="no_match")

    def get_summary(
        self,
        request: NutritionSummaryRequest,
        *,
        today: Callable[[], date] = date.today,
    ) -> NutritionSummary:
        window = dashboard_window(request.period, today())
        lookups_by_identity = self._lookups_by_identity()

        current_rows = self._grocery_items(request.currency, window.current_start, window.current_end)
        previous_rows = self._grocery_items(request.currency, window.previous_start, window.previous_end)
        current_items = [self._build_item(row, lookups_by_identity) for row in current_rows]
        previous_items = [self._build_item(row, lookups_by_identity) for row in previous_rows]

        overall_grade = self._weighted_grade(current_items)
        previous_overall_grade = self._weighted_grade(previous_items)

        total_item_count = len(current_items)
        matched_item_count = sum(1 for item in current_items if item.status == "matched")
        coverage_percent = (
            (Decimal(matched_item_count) / Decimal(total_item_count) * Decimal("100")).quantize(
                PERCENT_QUANTUM, rounding=ROUND_HALF_UP
            )
            if total_item_count
            else Decimal("0")
        )
        confidence = (
            "high"
            if total_item_count >= NUTRITION_HIGH_CONFIDENCE_MIN_ITEMS
            and coverage_percent >= NUTRITION_HIGH_CONFIDENCE_MIN_COVERAGE
            else "low"
        )

        return NutritionSummary(
            window=window,
            currency=request.currency,
            overall_grade=overall_grade,
            matched_item_count=matched_item_count,
            total_item_count=total_item_count,
            coverage_percent=coverage_percent,
            confidence=confidence,
            grade_distribution=self._grade_distribution(current_items),
            signals=self._signals(current_items, overall_grade, previous_overall_grade),
            groups=self._group_by_category(current_rows, current_items),
        )

    def _lookups_by_identity(self) -> dict[str, dict[str, Any]]:
        rows = self.conn.execute(
            """
            select identity_key, status, matched_product_name, source, source_ref, nutriments,
                   nutriscore_grade, nutriscore_source, nova_group, nova_group_estimated,
                   serving_size_g, serving_label
            from nutrition_lookups
            where owner_user_id = %(user_id)s
            """,
            {"user_id": self.user_id},
        ).fetchall()
        return {row["identity_key"]: row for row in rows}

    def _grocery_items(self, currency: str, start: date, end: date) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select (array_agg(item.id))[1] as transaction_item_id,
                   (array_agg(item.normalized_name))[1] as normalized_name,
                   (array_agg(item.brand))[1] as brand,
                   sum(item.line_total_amount) as line_total_amount,
                   count(*) as purchase_count,
                   reporting_category.stable_key as category_slug,
                   reporting_category.name as category_name
            from transaction_items item
            join transactions t on t.id = item.transaction_id and t.user_id = item.user_id
            join taxonomy_nodes category on category.id = item.taxonomy_node_id
            join taxonomy_node_closure reporting_path
              on reporting_path.version_id = category.version_id
             and reporting_path.descendant_id = category.id
            join taxonomy_nodes reporting_category
              on reporting_category.id = reporting_path.ancestor_id
             and reporting_category.level = least(%(reporting_level)s, category.level)
            where item.user_id = %(user_id)s
              and t.status = 'confirmed'
              and t.transaction_type = 'expense'
              and t.currency = %(currency)s
              and t.transaction_date between %(start)s and %(end)s
              and category.stable_key like %(grocery_prefix)s
              and item.normalized_name is not null
              and item.normalized_name <> ''
            group by
              lower(item.normalized_name),
              case when category.stable_key like %(produce_prefix)s then '' else lower(coalesce(item.brand, '')) end,
              reporting_category.stable_key, reporting_category.name
            order by category_name, line_total_amount desc
            """,
            {
                "user_id": self.user_id,
                "currency": currency,
                "start": start,
                "end": end,
                "reporting_level": NUTRITION_REPORTING_LEVEL,
                "grocery_prefix": f"{GROCERY_TAXONOMY_PREFIX}%",
                "produce_prefix": f"{PRODUCE_TAXONOMY_PREFIX}%",
            },
        ).fetchall()
        return list(rows)

    def _build_item(self, row: dict[str, Any], lookups_by_identity: dict[str, dict[str, Any]]) -> NutritionItem:
        identity_key = nutrition_identity_key(row["normalized_name"], row["brand"], row["category_slug"])
        lookup = lookups_by_identity.get(identity_key)
        facts: dict[str, Any] = (lookup["nutriments"] or {}) if lookup else {}
        # display_name is always what the owner actually bought (normalized_name),
        # never the matched source's own product name (e.g. USDA's "Cauliflower,
        # raw") - that would show a different name here than Price Watch shows
        # for the identical purchase. matched_product_name still exists in the
        # lookup row and source/source_ref are surfaced separately for provenance.
        display_name = row["normalized_name"]
        return NutritionItem(
            transaction_item_id=row["transaction_item_id"],
            identity_key=identity_key,
            display_name=display_name,
            brand=row["brand"],
            status=lookup["status"] if lookup else "pending",
            purchase_count=row["purchase_count"],
            nutriscore_grade=lookup["nutriscore_grade"] if lookup else None,
            nutriscore_source=lookup["nutriscore_source"] if lookup else None,
            nova_group=lookup["nova_group"] if lookup else None,
            nova_group_estimated=bool(lookup["nova_group_estimated"]) if lookup else False,
            source=lookup["source"] if lookup else None,
            source_ref=lookup["source_ref"] if lookup else None,
            spend_amount=_decimal(row["line_total_amount"]),
            energy_kcal_100g=facts.get("energy_kcal_100g"),
            protein_100g=facts.get("protein_100g"),
            fat_100g=facts.get("fat_100g"),
            saturated_fat_100g=facts.get("saturated_fat_100g"),
            trans_fat_100g=facts.get("trans_fat_100g"),
            carbohydrates_100g=facts.get("carbohydrates_100g"),
            sugars_100g=facts.get("sugars_100g"),
            added_sugars_100g=facts.get("added_sugars_100g"),
            fiber_100g=facts.get("fiber_100g"),
            sodium_mg_100g=facts.get("sodium_mg_100g"),
            cholesterol_mg_100g=facts.get("cholesterol_mg_100g"),
            potassium_mg_100g=facts.get("potassium_mg_100g"),
            calcium_mg_100g=facts.get("calcium_mg_100g"),
            iron_mg_100g=facts.get("iron_mg_100g"),
            serving_size_g=lookup["serving_size_g"] if lookup else None,
            serving_label=lookup["serving_label"] if lookup else None,
        )

    @staticmethod
    def _weighted_grade(items: list[NutritionItem]) -> str | None:
        graded = [item for item in items if item.status == "matched" and item.nutriscore_grade]
        covered = sum((item.spend_amount for item in graded), Decimal("0"))
        if not graded or covered <= 0:
            return None
        cap = covered * NUTRITION_MAX_ITEM_WEIGHT_SHARE
        weighted_total = Decimal("0")
        weight_total = Decimal("0")
        for item in graded:
            grade = item.nutriscore_grade
            assert grade is not None
            weight = min(item.spend_amount, cap)
            weighted_total += Decimal(GRADE_POINTS[grade]) * weight
            weight_total += weight
        if weight_total <= 0:
            return None
        points = int((weighted_total / weight_total).to_integral_value(rounding=ROUND_HALF_UP))
        return POINTS_GRADE[min(max(points, 1), 5)]

    @staticmethod
    def _grade_distribution(items: list[NutritionItem]) -> list[NutritionGradeBucket]:
        totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for item in items:
            grade = item.nutriscore_grade if item.status == "matched" and item.nutriscore_grade else "unknown"
            totals[grade] += item.spend_amount
        total_spend = sum(totals.values(), Decimal("0"))
        buckets = []
        for grade in ("a", "b", "c", "d", "e", "unknown"):
            amount = totals.get(grade)
            if not amount:
                continue
            share = (
                (amount / total_spend * Decimal("100")).quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)
                if total_spend
                else Decimal("0")
            )
            buckets.append(NutritionGradeBucket(grade=grade, spend_amount=amount, share_percent=share))
        return buckets

    @staticmethod
    def _signals(
        items: list[NutritionItem],
        overall_grade: str | None,
        previous_overall_grade: str | None,
    ) -> list[NutritionSignal]:
        signals: list[NutritionSignal] = []

        graded_nova = [item for item in items if item.status == "matched" and item.nova_group is not None]
        if graded_nova:
            whole_food_count = sum(1 for item in graded_nova if item.nova_group is not None and item.nova_group <= 2)
            ultra_processed_count = sum(
                1 for item in graded_nova if item.nova_group is not None and item.nova_group == 4
            )
            if whole_food_count * 2 >= len(graded_nova):
                top_examples = sorted(
                    (item for item in graded_nova if item.nova_group is not None and item.nova_group <= 2),
                    key=lambda item: item.spend_amount,
                    reverse=True,
                )[:3]
                names = ", ".join(item.display_name for item in top_examples)
                signals.append(
                    NutritionSignal(
                        kind="processing_level",
                        title="Mostly whole foods",
                        detail=(
                            f"{whole_food_count} of {len(graded_nova)} matched items are minimally processed "
                            f"(NOVA 1-2), led by {names}."
                            if names
                            else f"{whole_food_count} of {len(graded_nova)} matched items are minimally processed."
                        ),
                        tone="neutral",
                    )
                )
            elif ultra_processed_count * 2 >= len(graded_nova):
                signals.append(
                    NutritionSignal(
                        kind="processing_level",
                        title="Many highly processed items",
                        detail=(
                            f"{ultra_processed_count} of {len(graded_nova)} matched items are ultra-processed "
                            "(NOVA 4)."
                        ),
                        tone="warn",
                    )
                )

        if overall_grade and previous_overall_grade:
            delta = GRADE_POINTS[overall_grade] - GRADE_POINTS[previous_overall_grade]
            if delta != 0:
                signals.append(
                    NutritionSignal(
                        kind="grade_trend",
                        title="Basket grade slipped" if delta > 0 else "Basket grade improved",
                        detail=(
                            f"Your spend-weighted grade moved from {previous_overall_grade.upper()} to "
                            f"{overall_grade.upper()} since last period."
                        ),
                        tone="warn" if delta > 0 else "neutral",
                    )
                )

        return signals

    @staticmethod
    def _group_by_category(
        rows: list[dict[str, Any]], items: list[NutritionItem]
    ) -> list[NutritionCategoryGroup]:
        groups: dict[str, NutritionCategoryGroup] = {}
        order: list[str] = []
        for row, item in zip(rows, items, strict=True):
            slug = row["category_slug"]
            if slug not in groups:
                groups[slug] = NutritionCategoryGroup(
                    category_slug=slug, category_name=row["category_name"], items=[]
                )
                order.append(slug)
            groups[slug].items.append(item)
        ordered = [groups[slug] for slug in order]
        ordered.sort(
            key=lambda group: sum((item.spend_amount for item in group.items), Decimal("0")),
            reverse=True,
        )
        return ordered
