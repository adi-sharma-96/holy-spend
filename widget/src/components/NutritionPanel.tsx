import { useState } from "react";
import { compactDate, humanizeToken, money } from "../format";
import { Icon } from "../icons";
import { NutritionFactsDrawer, displayNumber, scaled } from "./NutritionFactsDrawer";
import type { NutritionItem, NutritionSummary, ProteinCostSummary } from "../types";

function displayShare(value: string | number): number {
  return Number(value);
}

function CountBadge({ count }: { count: number }) {
  if (count <= 1) return null;
  return <span className="n-count">×{count}</span>;
}

function GradeTile({
  item,
  mode,
  onSelect,
}: {
  item: NutritionItem;
  mode: "100g" | "serving";
  onSelect: (item: NutritionItem) => void;
}) {
  const grade = item.nutriscore_grade?.toLowerCase();
  const hasServing = item.serving_size_g != null && item.serving_label != null;
  const factor = mode === "serving" && hasServing ? Number(item.serving_size_g) / 100 : 1;
  const kcalLabel = mode === "serving" && hasServing ? item.serving_label ?? `${item.serving_size_g}g` : "100g";
  const kcal = scaled(item.energy_kcal_100g, factor);
  const novaFilled = item.nova_group ?? 0;

  if (item.status === "pending") {
    return (
      <div className="n-tile unmatched">
        <div className="n-badge unmatched">?</div>
        <div className="n-tile-body">
          <strong>{item.display_name}</strong>
          <small>{item.brand ? `${item.brand} · ` : ""}not yet matched</small>
        </div>
        <div className="n-meta">
          <span className="n-unmatched-label">Pending</span>
          <CountBadge count={item.purchase_count} />
        </div>
      </div>
    );
  }

  if (item.status === "no_match" || item.status === "error") {
    return (
      <div className="n-tile unmatched no-match">
        <div className="n-badge unmatched">–</div>
        <div className="n-tile-body">
          <strong>{item.display_name}</strong>
          <small>{item.brand ? `${item.brand} · ` : ""}no nutrition source found</small>
        </div>
        <div className="n-meta">
          <span className="n-unmatched-label">Not found</span>
          <CountBadge count={item.purchase_count} />
        </div>
      </div>
    );
  }

  return (
    <button className="n-tile tappable" type="button" onClick={() => onSelect(item)}>
      <div className={grade ? `n-badge grade-${grade}` : "n-badge unmatched"}>
        {grade ? grade.toUpperCase() : "·"}
      </div>
      <div className="n-tile-body">
        <strong>{item.display_name}</strong>
        <small>{item.brand || item.source || ""}</small>
      </div>
      <div className="n-meta">
        {kcal !== null && kcal !== undefined && (
          <span className="n-kcal">
            {displayNumber(kcal)}
            <small>/{kcalLabel}</small>
          </span>
        )}
        {item.nova_group && (
          <div
            aria-label={`NOVA ${item.nova_group}${item.nova_group_estimated ? " (estimated)" : ""}`}
            className={item.nova_group_estimated ? "nova nova-estimated" : "nova"}
          >
            {[1, 2, 3, 4].map((step) => (
              <span className={step <= novaFilled ? "filled" : ""} key={step} />
            ))}
          </div>
        )}
        <CountBadge count={item.purchase_count} />
      </div>
    </button>
  );
}

function ProteinCost({ summary, currency, onReview, onPage }: {
  summary: ProteinCostSummary;
  currency: string;
  onReview?: () => void;
  onPage?: (offset: number) => void;
}) {
  const hasReviewableEvidence = Object.keys(summary.reasons).some((reason) => reason.startsWith("unverified_")
    || reason === "missing_physical_quantity");
  return (
    <section className="protein-cost" aria-label="Cost per 100 g protein">
      <h3>Cost per 100 g of purchased protein</h3>
      {summary.groups.map((group) => (
        <p key={group.match_type}>
          <strong>{group.match_type === "exact" ? "Exact matches" : "Generic estimates"}</strong>{" · "}
          {group.cost_per_100g == null ? "No eligible lines" : (
            <>{money(group.cost_per_100g, currency)} per 100 g · {group.eligible_count} of {summary.total_count} lines · {money(group.eligible_spend, currency)}</>
          )}
        </p>
      ))}
      <p>
        {summary.excluded_count} of {summary.total_count} lines excluded ({money(summary.excluded_spend, currency)} of {money(summary.total_spend, currency)}).
        {" "}{summary.denominator}.
      </p>
      {summary.lines.length > 0 && (
        <details>
          <summary>Purchase evidence and exclusions</summary>
          <ul>
            {summary.lines.map((line) => (
              <li key={line.item_id}>
                <strong>{line.display_name}</strong> · {compactDate(line.purchase_date)} · {money(line.price_amount, currency)}
                {" "}({humanizeToken(line.price_source, "purchase record")})
                {line.purchase_quantity != null && <> · {displayNumber(Number(line.purchase_quantity))} {line.purchase_unit} purchased</>}
                {line.exclusion_reason
                  ? <> · {humanizeToken(line.exclusion_reason, "Excluded")}</>
                  : <> · {displayNumber(Number(line.purchased_protein_g))} g protein · {money(line.cost_per_100g!, currency)} per 100 g ({line.match_type})</>}
                {line.nutrition_source && (
                  <small className="spending-comparison-note">
                    {line.nutrition_source} {line.nutrition_source_ref}
                    {line.nutrition_recorded_at && <> · recorded {line.nutrition_recorded_at.slice(0, 10)}</>}
                    {line.protein_label && <>
                      {" · "}{line.protein_label.protein_g} g protein {humanizeToken(line.protein_label.basis)}
                      {line.protein_label.serving_size_g && <> ({line.protein_label.serving_size_g} g serving)</>}
                      {line.protein_label.source_date && <> · label dated {line.protein_label.source_date}</>}
                    </>}
                  </small>
                )}
              </li>
            ))}
          </ul>
          {onPage && <div className="view-toggle" aria-label="Purchase evidence pages">
            {summary.detail_offset > 0 && (
              <button type="button" onClick={() => onPage(Math.max(0, summary.detail_offset - 25))}>Previous lines</button>
            )}
            {summary.detail_offset + summary.lines.length < summary.total_count && (
              <button type="button" onClick={() => onPage(summary.detail_offset + 25)}>More lines</button>
            )}
          </div>}
        </details>
      )}
      {onReview && hasReviewableEvidence && (
        <button type="button" className="text-button" onClick={onReview}>Open product match review</button>
      )}
    </section>
  );
}

export function NutritionPanel({
  summary,
  status,
  currency,
  selectedItem,
  onSelectItem,
  onCloseItem,
  onReview,
  onProteinEvidencePage,
}: {
  summary?: NutritionSummary;
  status: "idle" | "loading" | "ready" | "error";
  currency: string;
  selectedItem?: NutritionItem;
  onSelectItem: (item: NutritionItem) => void;
  onCloseItem: () => void;
  onReview?: () => void;
  onProteinEvidencePage?: (offset: number) => void;
}) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<"100g" | "serving">("100g");

  if (selectedItem) {
    return <NutritionFactsDrawer embedded item={selectedItem} onClose={onCloseItem} />;
  }

  if (!summary) {
    if (status === "error") {
      return (
        <div className="empty-state">
          <Icon name="leaf" />
          <strong>Nutrition needs another try</strong>
          <span>Your saved expenses remain safe.</span>
        </div>
      );
    }
    return (
      <div className="empty-state">
        <Icon name="refresh" />
        <strong>Loading nutrition data</strong>
      </div>
    );
  }

  const grade = summary.overall_grade?.toLowerCase();
  const gradeDistribution = summary.grade_distribution.filter((bucket) => displayShare(bucket.spend_amount) > 0);
  const hasAnyServing = summary.groups.some((group) =>
    group.items.some((item) => item.serving_size_g != null && item.serving_label != null),
  );

  return (
    <>
      <div className="panel-heading">
        <h2>Nutrition</h2>
      </div>

      {summary.protein_cost && (
        <ProteinCost summary={summary.protein_cost} currency={summary.currency} onReview={onReview} onPage={onProteinEvidencePage} />
      )}

      {summary.total_item_count > 0 ? (
        <>
          <div className="nutrition-hero">
            <div className={grade ? `grade-badge grade-${grade}` : "grade-badge"}>
              {grade ? grade.toUpperCase() : "?"}
            </div>
            <div className="nutrition-hero-copy">
              <h1>
                {grade
                  ? `Your spend-weighted basket grade: ${grade.toUpperCase()}`
                  : "Building your basket grade"}
              </h1>
              <p>
                {summary.matched_item_count} of {summary.total_item_count} grocery products matched.
                The basket grade weights products with a grade by spend.
              </p>
            </div>
          </div>

          {gradeDistribution.length > 0 && (
            <div className="grade-distribution">
              <div className="grade-bar">
                {gradeDistribution.map((bucket) => (
                  <span
                    key={bucket.grade}
                    style={{
                      width: `${displayShare(bucket.share_percent)}%`,
                      background:
                        bucket.grade === "unknown" ? "var(--border-strong)" : `var(--score-${bucket.grade})`,
                    }}
                  />
                ))}
              </div>
              <div className="grade-legend">
                {gradeDistribution.map((bucket) => (
                  <span key={bucket.grade}>
                    <b
                      style={{
                        color: bucket.grade === "unknown" ? "var(--text-faint)" : `var(--score-${bucket.grade})`,
                      }}
                    >
                      {bucket.grade === "unknown" ? "?" : bucket.grade.toUpperCase()}
                    </b>{" "}
                    {Math.round(displayShare(bucket.share_percent))}%
                  </span>
                ))}
              </div>
            </div>
          )}

          {summary.signals.length > 0 && (
            <div className="price-watch-signals" aria-label="Nutrition insights">
              {summary.signals.map((signal) => (
                <article
                  className={signal.tone === "warn" ? "price-watch-signal warn" : "price-watch-signal"}
                  key={signal.kind}
                >
                  <span>
                    <Icon name="leaf" size={17} />
                  </span>
                  <div>
                    <strong>{signal.title}</strong>
                    <p>{signal.detail}</p>
                  </div>
                </article>
              ))}
            </div>
          )}

          {hasAnyServing && (
            <div className="nutrition-view-bar">
              <div className="view-toggle" role="group" aria-label="Nutrition tile display">
                <button className={mode === "100g" ? "active" : ""} onClick={() => setMode("100g")} type="button">
                  100g
                </button>
                <button className={mode === "serving" ? "active" : ""} onClick={() => setMode("serving")} type="button">
                  Serving
                </button>
              </div>
            </div>
          )}

          <div className="price-cards">
            {summary.groups.map((group) => {
              const isExpanded = expandedGroups.has(group.category_slug);
              const allUnmatched = group.items.every((item) => item.status !== "matched");
              return (
                <div className="price-category-group" key={group.category_slug}>
                  <button
                    aria-expanded={isExpanded}
                    className="price-category-header"
                    type="button"
                    onClick={() =>
                      setExpandedGroups((current) => {
                        const next = new Set(current);
                        if (next.has(group.category_slug)) next.delete(group.category_slug);
                        else next.add(group.category_slug);
                        return next;
                      })
                    }
                  >
                    <span>{group.category_name}</span>
                    <span>
                      <small>
                        {group.items.length} item{group.items.length === 1 ? "" : "s"}
                      </small>{" "}
                      <Icon name={isExpanded ? "arrow-up" : "arrow-down"} size={14} />
                    </span>
                  </button>
                  {isExpanded &&
                    (allUnmatched ? (
                      <div className="fresh-note">
                        <Icon name="leaf" size={16} />
                        {group.category_name} items haven't been matched to a nutrition source yet.
                      </div>
                    ) : (
                      <div className="price-tile-grid">
                        {group.items.map((item) => (
                          <GradeTile item={item} key={item.identity_key} mode={mode} onSelect={onSelectItem} />
                        ))}
                      </div>
                    ))}
                </div>
              );
            })}
          </div>

          <p className="data-footnote">
            Grades and nutrition facts come from the sources shown on each item, matched by product name and
            brand. Unmatched items don't affect your grade above.
          </p>
        </>
      ) : (
        <div className="empty-state price-empty">
          <Icon name="leaf" />
          <strong>No grocery items in {currency} yet</strong>
          <span>Confirmed grocery purchases will show up here once matched to a nutrition source.</span>
        </div>
      )}
    </>
  );
}
