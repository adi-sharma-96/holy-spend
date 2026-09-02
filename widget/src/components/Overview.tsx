import { useEffect, useMemo, useRef, useState } from "react";
import {
  buildCalendarMonth,
  parseIsoDate,
  shiftMonth,
  type CalendarDay,
} from "../calendar";
import { categoryIcon } from "../category-icons";
import { compactDate, fullDate, money, percent } from "../format";
import { Icon, type IconName } from "../icons";
import type {
  BasketProduct,
  DashboardCategory,
  DashboardPeriod,
  ExpenseDashboard,
  ExpenseTransaction,
  ItemPriceHistory,
  MerchantBreakdownResponse,
  MerchantSpend,
  NutritionItem,
  NutritionSummary,
  PersonalBasketIndex,
  PriceChange,
  TrackerSection,
  TransactionListResponse,
} from "../types";
import { taxonomyGroupLabel } from "../taxonomy";
import { ConfirmSheet } from "./ConfirmSheet";
import { DisplayAmount } from "./Money";
import { NutritionPanel } from "./NutritionPanel";
import { PriceHistoryPanel } from "./PriceHistoryPanel";

const periodOptions: Array<{ value: DashboardPeriod; label: string }> = [
  { value: "month", label: "Month" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
  { value: "year", label: "Year" },
];

const sectionOptions: Array<{
  value: TrackerSection;
  label: string;
  icon: IconName;
}> = [
  { value: "overview", label: "Overview", icon: "home" },
  { value: "transactions", label: "Activity", icon: "receipt" },
  { value: "trends", label: "Trends", icon: "chart" },
  { value: "prices", label: "Price Watch", icon: "sparkle" },
  { value: "nutrition", label: "Nutrition", icon: "leaf" },
];

type LoadStatus = "idle" | "loading" | "ready" | "error";

type Props = {
  dashboard: ExpenseDashboard;
  period: DashboardPeriod;
  section: TrackerSection;
  initialTrendView?: "months" | "calendar";
  transactions?: TransactionListResponse;
  transactionStatus: LoadStatus;
  activityFilter?: "all" | "draft" | "confirmed";
  onSectionChange: (section: TrackerSection) => void;
  onPeriodChange: (period: DashboardPeriod) => void;
  onRefresh: () => void;
  onLoadTransactions: (loadMore?: boolean) => void;
  onActivityFilterChange?: (filter: "all" | "draft" | "confirmed") => void;
  onAdd: () => void;
  onReview: () => void;
  onLoadCategoryBreakdown: (
    parent: DashboardCategory,
    currency: string,
    window: ExpenseDashboard["window"],
  ) => Promise<DashboardCategory[]>;
  onOpenTransaction: (transaction: ExpenseTransaction) => void;
  onDeleteTransaction?: (transaction: ExpenseTransaction) => void;
  onLoadDayTransactions?: (isoDate: string, currency: string) => Promise<ExpenseTransaction[]>;
  onOpenPrice: (change: PriceChange) => void;
  onLoadPersonalBasket?: (currency: string) => Promise<PersonalBasketIndex>;
  onOpenBasketProduct?: (product: BasketProduct) => void;
  priceHistory?: ItemPriceHistory;
  onClosePriceHistory?: () => void;
  onLoadMerchantBreakdown?: (
    currency: string,
    period: DashboardPeriod,
  ) => Promise<MerchantBreakdownResponse>;
  onLoadMerchantTransactions?: (
    merchant: string,
    currency: string,
  ) => Promise<ExpenseTransaction[]>;
  nutritionSummary?: NutritionSummary;
  nutritionStatus?: LoadStatus;
  nutritionItem?: NutritionItem;
  onOpenNutritionItem?: (item: NutritionItem) => void;
  onCloseNutritionItem?: () => void;
};

function SpendTrend({
  dashboard,
  currency,
  onCurrencyChange,
}: {
  dashboard: ExpenseDashboard;
  currency: string;
  onCurrencyChange: (currency: string) => void;
}) {
  const points = dashboard.spend_trend.filter((point) => point.currency === currency);
  const maximum = Math.max(...points.map((point) => Number(point.amount)), 1);
  const latest = points[points.length - 1];

  return (
    <section className="surface trend-panel" aria-label={`Six month ${currency} spending trend`}>
      <div className="panel-heading">
        <div>
          <h3>Last six months</h3>
          {latest && (
            <strong className="trend-latest">{money(latest.amount, latest.currency)}</strong>
          )}
        </div>
        <div className="trend-currencies" aria-label="Trend currency">
          {dashboard.totals.map((total) => (
            <button
              className={currency === total.currency ? "active" : ""}
              key={total.currency}
              onClick={() => onCurrencyChange(total.currency)}
              type="button"
            >
              {total.currency}
            </button>
          ))}
        </div>
      </div>
      {points.length ? (
        <div className="trend-columns">
          {points.map((point, index) => (
            <div
              className={`trend-column ${index === points.length - 1 ? "current" : ""}`}
              key={`${point.currency}-${point.period_start}`}
              title={`${point.label}: ${money(point.amount, point.currency)}`}
            >
              <span className="trend-value">{money(point.amount, point.currency)}</span>
              <span className="trend-bar-track">
                <span
                  style={{ height: `${Math.max(8, (Number(point.amount) / maximum) * 100)}%` }}
                />
              </span>
              <small>{point.label}</small>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <Icon name="chart" />
          <strong>No monthly trend for {currency} yet</strong>
          <span>Confirmed expenses will build this view month by month.</span>
        </div>
      )}
    </section>
  );
}

function SpendCalendar({
  dashboard,
  currency,
  onCurrencyChange,
  onLoadDayTransactions,
  onOpenTransaction,
}: {
  dashboard: ExpenseDashboard;
  currency: string;
  onCurrencyChange: (currency: string) => void;
  onLoadDayTransactions?: (isoDate: string, currency: string) => Promise<ExpenseTransaction[]>;
  onOpenTransaction: (transaction: ExpenseTransaction) => void;
}) {
  const windowEnd = parseIsoDate(dashboard.window.current_end);
  const [view, setView] = useState({ year: windowEnd.year, month: windowEnd.month });
  const [selectedDay, setSelectedDay] = useState<CalendarDay>();
  const [dayTransactions, setDayTransactions] = useState<ExpenseTransaction[]>();
  const [dayStatus, setDayStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");

  const calendar = useMemo(
    () => buildCalendarMonth(view.year, view.month, dashboard.daily_spend, currency),
    [view, dashboard.daily_spend, currency],
  );
  const atCurrentMonth = view.year === windowEnd.year && view.month === windowEnd.month;
  const monthsBack =
    windowEnd.year * 12 + windowEnd.month - (view.year * 12 + view.month);

  function moveMonth(delta: number) {
    setView((current) => shiftMonth(current.year, current.month, delta));
    setSelectedDay(undefined);
    setDayTransactions(undefined);
    setDayStatus("idle");
  }

  async function openDay(day: CalendarDay) {
    setSelectedDay(day);
    setDayTransactions(undefined);
    if (!day.count || !onLoadDayTransactions) {
      setDayStatus("idle");
      return;
    }
    setDayStatus("loading");
    try {
      setDayTransactions(await onLoadDayTransactions(day.date, currency));
      setDayStatus("ready");
    } catch {
      setDayStatus("error");
    }
  }

  return (
    <section
      className="surface trend-panel calendar-panel"
      aria-label={`${calendar.label} spending calendar`}
    >
      <div className="panel-heading calendar-heading">
        <div className="calendar-nav">
          <button
            aria-label="Previous month"
            className="icon-button calendar-arrow"
            disabled={monthsBack >= 11}
            onClick={() => moveMonth(-1)}
            type="button"
          >
            <Icon name="back" size={16} />
          </button>
          <h3>{calendar.label}</h3>
          <button
            aria-label="Next month"
            className="icon-button calendar-arrow"
            disabled={atCurrentMonth}
            onClick={() => moveMonth(1)}
            type="button"
          >
            <Icon name="chevron" size={16} />
          </button>
        </div>
        <div className="calendar-heading-side">
          <div className="trend-currencies" aria-label="Calendar currency">
            {dashboard.totals.map((total) => (
              <button
                className={currency === total.currency ? "active" : ""}
                key={total.currency}
                onClick={() => onCurrencyChange(total.currency)}
                type="button"
              >
                {total.currency}
              </button>
            ))}
          </div>
          <strong className="calendar-total">{money(calendar.total, currency)}</strong>
        </div>
      </div>

      <div className="calendar-dow" aria-hidden="true">
        {["M", "T", "W", "T", "F", "S", "S"].map((weekday, index) => (
          <span key={`${weekday}-${index}`}>{weekday}</span>
        ))}
      </div>
      <div className="calendar-grid">
        {Array.from({ length: calendar.leadingBlanks }, (_, index) => (
          <span aria-hidden="true" className="calendar-blank" key={`blank-${index}`} />
        ))}
        {calendar.days.map((day) => (
          <button
            aria-label={
              day.count
                ? `${compactDate(day.date)}: ${money(day.amount, currency)} across ${day.count} expense${day.count === 1 ? "" : "s"}`
                : `${compactDate(day.date)}: no confirmed spending`
            }
            className={`calendar-day level-${day.level} ${
              selectedDay?.date === day.date ? "selected" : ""
            }`}
            key={day.date}
            onClick={() => void openDay(day)}
            type="button"
          >
            {day.day}
          </button>
        ))}
      </div>
      <div className="calendar-legend" aria-hidden="true">
        <span>Less</span>
        <i className="level-0" />
        <i className="level-1" />
        <i className="level-2" />
        <i className="level-3" />
        <i className="level-4" />
        <span>More</span>
      </div>

      {selectedDay && (
        <div className="calendar-day-detail">
          <div className="calendar-day-heading">
            <strong>{fullDate(selectedDay.date)}</strong>
            {selectedDay.count > 0 && (
              <span className="status-chip success">
                {selectedDay.count} expense{selectedDay.count === 1 ? "" : "s"}
              </span>
            )}
            <strong className="calendar-day-total">
              {money(selectedDay.amount, currency)}
            </strong>
          </div>
          {selectedDay.count === 0 ? (
            <p className="empty-copy">No confirmed spending this day.</p>
          ) : dayStatus === "loading" ? (
            <p className="empty-copy">Loading this day…</p>
          ) : dayStatus === "error" ? (
            <p className="empty-copy">This day did not load. Tap it again.</p>
          ) : !dayTransactions?.length ? (
            <p className="empty-copy">No matching transactions found.</p>
          ) : (
            <div className="transaction-list">
              {dayTransactions.map((transaction) => (
                <button
                  className="transaction-row"
                  key={transaction.id}
                  onClick={() => onOpenTransaction(transaction)}
                  type="button"
                >
                  <span className={`transaction-mark ${transaction.status}`}>
                    <Icon
                      name={transaction.source_type === "receipt" ? "receipt" : "file"}
                      size={18}
                    />
                  </span>
                  <span className="transaction-copy">
                    <strong>
                      {transaction.merchant_name_normalized ||
                        transaction.merchant_name_raw ||
                        "Manual expense"}
                    </strong>
                    <small>
                      {transaction.item_count ?? transaction.items?.length ?? 0} item
                      {(transaction.item_count ?? transaction.items?.length ?? 0) === 1
                        ? ""
                        : "s"}
                    </small>
                  </span>
                  <strong className="transaction-amount">
                    {money(transaction.total_amount, transaction.currency)}
                  </strong>
                  <Icon name="chevron" size={17} />
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function previousWindowLabel(window: ExpenseDashboard["window"]): string {
  const start = compactDate(window.previous_start);
  const end = compactDate(window.previous_end);
  return start === end ? `vs ${start}` : `vs ${start}–${end}`;
}

function Delta({
  value,
  suffix = "",
}: {
  value: string | number | null | undefined;
  suffix?: string;
}) {
  if (value === null || value === undefined) {
    return <span className="delta neutral">New{suffix ? ` ${suffix}` : ""}</span>;
  }
  const numeric = Number(value);
  if (numeric === 0) {
    return <span className="delta neutral">0%{suffix ? ` ${suffix}` : ""}</span>;
  }
  return (
    <span className={`delta ${numeric > 0 ? "up" : numeric < 0 ? "down" : "neutral"}`}>
      <Icon name={numeric > 0 ? "arrow-up" : "arrow-down"} size={13} />
      {percent(numeric)} {suffix}
    </span>
  );
}

function PriceSparkline({ prices }: { prices?: Array<string | number> }) {
  const values = (prices || []).map(Number).filter((value) => Number.isFinite(value));
  if (values.length < 2) return <span className="price-spark" aria-hidden="true" />;
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = Math.max(maximum - minimum, maximum * 0.02, 0.01);
  const points = values.map((value, index) => ({
    x: (index / (values.length - 1)) * 100,
    y: 27 - ((value - minimum) / range) * 24,
  }));
  const last = points[points.length - 1]!;
  return (
    <span className="price-spark" aria-hidden="true">
      <svg viewBox="0 0 100 30" preserveAspectRatio="none">
        <polyline points={points.map((point) => `${point.x},${point.y}`).join(" ")} />
        <polyline className="spark-dot" points={`${last.x},${last.y} ${last.x},${last.y}`} />
      </svg>
    </span>
  );
}

function PriceWatchSignal({ change }: { change: PriceChange }) {
  const savings = Number(change.savings_amount);
  const bestMerchant = change.best_merchant || "the best recorded store";
  const bestQuantity = change.best_quantity_label;
  const differentVendor =
    change.best_merchant &&
    change.comparison_merchant &&
    change.best_merchant !== change.comparison_merchant;
  const title =
    savings > 0 && differentVendor
      ? `${change.label} was ${percent(change.savings_percent)} cheaper at ${bestMerchant}`
      : bestQuantity
        ? `${change.label} was cheapest when you bought ${bestQuantity}`
        : `${change.label}'s best recorded price was at ${bestMerchant}`;
  const purchaseContext = bestQuantity ? ` when you bought ${bestQuantity}` : "";
  const savingsContext =
    savings > 0
      ? ` That's ${money(change.savings_amount, change.currency)}/${change.normalized_unit} below ${change.comparison_merchant ? `${change.comparison_merchant}'s recorded price` : "another recorded purchase"}.`
      : " That is the lowest price in your history.";

  return (
    <article className="price-watch-signal">
      <span><Icon name="sparkle" size={17} /></span>
      <div>
        <strong>{title}</strong>
        <p>
          {money(change.best_price, change.currency)}/{change.normalized_unit}
          {purchaseContext} at {bestMerchant}.{savingsContext}
        </p>
      </div>
    </article>
  );
}

function PriceCard({
  change,
  onOpenPrice,
}: {
  change: PriceChange;
  onOpenPrice: (change: PriceChange) => void;
}) {
  const movement =
    change.delta_amount === null || change.delta_amount === undefined
      ? undefined
      : Number(change.delta_amount);
  const direction =
    movement === undefined ? "tracking" : movement > 0 ? "up" : movement < 0 ? "down" : "steady";
  return (
    <button className={`price-tile ${direction}`} onClick={() => onOpenPrice(change)} type="button">
      <span className="price-tile-row">
        <span className={`price-direction ${direction}`}>
          <Icon
            name={
              movement === undefined
                ? "sparkle"
                : movement > 0
                  ? "arrow-up"
                  : movement < 0
                    ? "arrow-down"
                    : "chart"
            }
          />
        </span>
        <strong className="price-tile-name">{change.label}</strong>
        {change.sample_size > 1 ? (
          <Delta value={change.delta_percent} suffix="" />
        ) : (
          <span className="delta neutral">Watching</span>
        )}
      </span>
      <span className="price-tile-row price-tile-row-bottom">
        <small className="price-tile-store">
          {change.current_merchant || "Latest purchase"} · {change.sample_size}×
        </small>
        <PriceSparkline prices={change.recent_prices} />
        <strong className="price-tile-price">
          {money(change.current_price, change.currency)}
          <small>/{change.normalized_unit}</small>
        </strong>
      </span>
    </button>
  );
}

type DealsListEntry = { label: string; items: PriceChange[] };

function DealsList({
  priceChanges,
  currency,
  onOpenPrice,
}: {
  priceChanges: PriceChange[];
  currency: string;
  onOpenPrice: (change: PriceChange) => void;
}) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  useEffect(() => {
    setExpandedGroups(new Set());
  }, [currency]);

  const entries = useMemo<DealsListEntry[]>(() => {
    // Group by a fixed, broad taxonomy level (Subcategory, e.g. "Fruit",
    // "Vegetables", "Milk", "Cheese", "Pulses & Legumes") so every product —
    // even a category of one — sits under a recognizable, collapsible
    // heading rather than a narrow, awkward-sounding one (e.g. "Roots &
    // Tubers") or a flat, ungrouped row.
    const byLabel = new Map<string, PriceChange[]>();
    const order: string[] = [];
    for (const change of priceChanges) {
      const label = (change.taxonomy_key && taxonomyGroupLabel(change.taxonomy_key)) || "Other";
      const existing = byLabel.get(label);
      if (existing) existing.push(change);
      else {
        byLabel.set(label, [change]);
        order.push(label);
      }
    }
    return order.map((label) => ({ label, items: byLabel.get(label)! }));
  }, [priceChanges]);

  return (
    <div className="price-cards">
      {entries.map((entry) => {
        const isExpanded = expandedGroups.has(entry.label);
        return (
          <div className="price-category-group" key={entry.label}>
            <button
              aria-expanded={isExpanded}
              className="price-category-header"
              onClick={() =>
                setExpandedGroups((current) => {
                  const next = new Set(current);
                  if (next.has(entry.label)) next.delete(entry.label);
                  else next.add(entry.label);
                  return next;
                })
              }
              type="button"
            >
              <span>{entry.label}</span>
              <span>
                <small>
                  {entry.items.length} product{entry.items.length === 1 ? "" : "s"}
                </small>{" "}
                <Icon name={isExpanded ? "arrow-up" : "arrow-down"} size={14} />
              </span>
            </button>
            {isExpanded && (
              <div className="price-tile-grid">
                {entry.items.map((change) => (
                  <PriceCard
                    change={change}
                    onOpenPrice={onOpenPrice}
                    key={`${change.identity_key}-${change.currency}-${change.normalized_unit}`}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
      {!priceChanges.length && (
        <div className="empty-state price-empty">
          <Icon name="chart" />
          <strong>No trackable prices in {currency} yet</strong>
          <span>
            Add a line-item count, weight, volume, or package size to start watching it.
          </span>
        </div>
      )}
    </div>
  );
}

function PersonalBasketPanel({
  currency,
  onLoadPersonalBasket,
  onOpenBasketProduct,
}: {
  currency: string;
  onLoadPersonalBasket: (currency: string) => Promise<PersonalBasketIndex>;
  onOpenBasketProduct: (product: BasketProduct) => void;
}) {
  const [index, setIndex] = useState<PersonalBasketIndex>();
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [expanded, setExpanded] = useState(false);
  const [methodologyOpen, setMethodologyOpen] = useState(false);

  useEffect(() => {
    setExpanded(false);
    setMethodologyOpen(false);
  }, [currency]);

  useEffect(() => {
    let cancelled = false;
    setIndex(undefined);
    setStatus("loading");
    onLoadPersonalBasket(currency)
      .then((result) => {
        if (!cancelled) {
          setIndex(result);
          setStatus("ready");
        }
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [currency, onLoadPersonalBasket]);

  const overallNumeric =
    index?.overall_delta_percent !== null && index?.overall_delta_percent !== undefined
      ? Number(index.overall_delta_percent)
      : null;
  const coveredSpend = index ? Number(index.covered_spend) || 0 : 0;

  return (
    <div className="basket-panel" aria-label={`${currency} personal basket index`}>
      {status === "loading" || status === "idle" ? (
        <div className="empty-state compact">
          <Icon name="refresh" />
          <span>Comparing your repeat purchases…</span>
        </div>
      ) : status === "error" ? (
        <div className="empty-state">
          <Icon name="refresh" />
          <strong>This did not load</strong>
          <span>The rest of the tracker is still available.</span>
        </div>
      ) : !index || index.product_count === 0 ? (
        <div className="empty-state">
          <Icon name="chart" />
          <strong>Not enough repeat purchases yet</strong>
          <span>
            Buy the exact same product, brand, and store at least twice within{" "}
            {index?.window_days ?? 180} days to start tracking your own cost of living.
          </span>
        </div>
      ) : (
        <>
          <div className="basket-hero">
            <div className="basket-hero-top">
              <span className="basket-hero-icon">
                <Icon name="chart" size={14} />
              </span>
              <strong>Your comparable basket</strong>
              <button
                aria-expanded={methodologyOpen}
                aria-label="How this is calculated"
                className="basket-info-button"
                onClick={() => setMethodologyOpen((current) => !current)}
                type="button"
              >
                i
              </button>
            </div>
            {overallNumeric !== null ? (
              <div className="basket-num">
                <strong
                  className={
                    overallNumeric > 0 ? "up" : overallNumeric < 0 ? "down" : "neutral"
                  }
                >
                  {overallNumeric > 0 ? "+" : overallNumeric < 0 ? "−" : ""}
                  {percent(index.overall_delta_percent)}
                </strong>
                <span>vs. earliest purchases</span>
              </div>
            ) : (
              <p className="empty-copy">Not enough matched purchases to compute a trend yet.</p>
            )}
            <p className="basket-note">
              Based on <strong>{index.product_count}</strong> exact product
              {index.product_count === 1 ? "" : "s"} covering{" "}
              <strong>{percent(index.coverage_percent)}</strong> of tracked spend.
            </p>
            {methodologyOpen && (
              <div className="basket-methodology">
                <p>
                  Only the exact same product, brand, and store, bought twice or more, same unit —
                  a different store or a different brand starts its own separate product.
                </p>
                <p>
                  Weighted by recent spend, with any single product's influence capped so it
                  can't dominate the headline number.
                </p>
                <p>
                  Compares your earliest purchases against your most recent ones (averaging up
                  to 3 on each side when you've bought it that often) within the last{" "}
                  {index.window_days} days — smoothing out a single sale or one-off price.
                </p>
              </div>
            )}
            <div className="basket-conf-row">
              <span className={`conf-chip ${index.confidence === "high" ? "high" : "low"}`}>
                {index.confidence === "high" ? "High confidence" : "Low confidence"}
              </span>
            </div>
          </div>

          <button
            aria-expanded={expanded}
            className="basket-expand-button"
            onClick={() => setExpanded((current) => !current)}
            type="button"
          >
            <span>
              {expanded ? "Hide" : "See"} the {index.product_count} product
              {index.product_count === 1 ? "" : "s"}
            </span>
            <Icon name={expanded ? "arrow-up" : "arrow-down"} size={14} />
          </button>

          {expanded && (
            <div className="basket-list">
              {index.products.map((product) => {
                const share = coveredSpend > 0 ? (Number(product.spend_amount) / coveredSpend) * 100 : 0;
                return (
                  <button
                    className="basket-item"
                    key={product.identity_key}
                    onClick={() => onOpenBasketProduct(product)}
                    type="button"
                  >
                    <span className="basket-item-copy">
                      <strong>{product.label}</strong>
                      <small>
                        {product.merchant_name ? `at ${product.merchant_name} · ` : ""}
                        {percent(share)} of basket spend
                      </small>
                    </span>
                    <Delta value={product.delta_percent} suffix="" />
                    <Icon name="chevron" size={14} />
                  </button>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MerchantBreakdownPanel({
  currency,
  period,
  onLoadMerchantBreakdown,
  onSelectMerchant,
}: {
  currency: string;
  period: DashboardPeriod;
  onLoadMerchantBreakdown: (
    currency: string,
    period: DashboardPeriod,
  ) => Promise<MerchantBreakdownResponse>;
  onSelectMerchant: (merchant: MerchantSpend) => void;
}) {
  const [data, setData] = useState<MerchantBreakdownResponse>();
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");

  useEffect(() => {
    let cancelled = false;
    setData(undefined);
    setStatus("loading");
    onLoadMerchantBreakdown(currency, period)
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setStatus("ready");
        }
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [currency, period, onLoadMerchantBreakdown]);

  if (status === "loading" || status === "idle") {
    return <p className="empty-copy">Loading merchants…</p>;
  }
  if (status === "error") {
    return <p className="empty-copy">This did not load. Try again.</p>;
  }
  if (!data || data.merchants.length === 0) {
    return <p className="empty-copy">No expenses this period. Add one to see merchants here.</p>;
  }

  return (
    <div className="category-bars">
      {data.merchants.map((merchant) => (
        <button
          className="merchant-row"
          key={merchant.merchant_name}
          onClick={() => onSelectMerchant(merchant)}
          type="button"
        >
          <span className="merchant-label">
            <strong>{merchant.merchant_name}</strong>
            <small>
              {merchant.visit_count} visit{merchant.visit_count === 1 ? "" : "s"} · avg{" "}
              {money(merchant.average_amount, merchant.currency)}
            </small>
          </span>
          <span className="category-meta">
            <span className="category-meta-text">
              {Number(merchant.share_percent).toFixed(0) !== "0" && (
                <span>{Number(merchant.share_percent).toFixed(0)}%</span>
              )}
              <Delta value={merchant.delta_percent} suffix="" />
            </span>
            <Icon name="chevron" size={14} />
          </span>
        </button>
      ))}
    </div>
  );
}

function MerchantTransactionList({
  merchant,
  onLoadMerchantTransactions,
  onOpenTransaction,
}: {
  merchant: MerchantSpend;
  onLoadMerchantTransactions?: (merchant: string, currency: string) => Promise<ExpenseTransaction[]>;
  onOpenTransaction: (transaction: ExpenseTransaction) => void;
}) {
  const [rows, setRows] = useState<ExpenseTransaction[]>();
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");

  useEffect(() => {
    let cancelled = false;
    setRows(undefined);
    if (!onLoadMerchantTransactions) {
      setStatus("idle");
      return undefined;
    }
    setStatus("loading");
    onLoadMerchantTransactions(merchant.merchant_name, merchant.currency)
      .then((result) => {
        if (!cancelled) {
          setRows(result);
          setStatus("ready");
        }
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [merchant.merchant_name, merchant.currency, onLoadMerchantTransactions]);

  return (
    <>
      <p className="breakdown-level">{money(merchant.current_amount, merchant.currency)} total</p>
      {status === "loading" || status === "idle" ? (
        <p className="empty-copy">Loading these transactions…</p>
      ) : status === "error" ? (
        <p className="empty-copy">This did not load. Go back and try again.</p>
      ) : !rows?.length ? (
        <p className="empty-copy">No matching transactions found.</p>
      ) : (
        <div className="transaction-list">
          {rows.map((transaction) => (
            <button
              className="transaction-row"
              key={transaction.id}
              onClick={() => onOpenTransaction(transaction)}
              type="button"
            >
              <span className={`transaction-mark ${transaction.status}`}>
                <Icon
                  name={transaction.source_type === "receipt" ? "receipt" : "file"}
                  size={18}
                />
              </span>
              <span className="transaction-copy">
                <strong>{compactDate(transaction.transaction_date)}</strong>
                <small>
                  {transaction.item_count ?? transaction.items?.length ?? 0} item
                  {(transaction.item_count ?? transaction.items?.length ?? 0) === 1 ? "" : "s"}
                </small>
              </span>
              <strong className="transaction-amount">
                {money(transaction.total_amount, transaction.currency)}
              </strong>
              <Icon name="chevron" size={17} />
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function TransactionRow({
  transaction,
  onOpen,
  onDelete,
}: {
  transaction: ExpenseTransaction;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const [revealed, setRevealed] = useState(false);
  const touchStart = useRef<number | undefined>(undefined);
  const merchant =
    transaction.merchant_name_normalized ||
    transaction.merchant_name_raw ||
    (transaction.source_type === "manual" ? "Manual expense" : "Unknown merchant");
  const itemCount = transaction.item_count ?? transaction.items?.length ?? 0;

  return (
    <div
      className={`transaction-row-wrap ${revealed ? "revealed" : ""}`}
      onTouchStart={(event) => {
        touchStart.current = event.touches[0]?.clientX;
      }}
      onTouchEnd={(event) => {
        const start = touchStart.current;
        const end = event.changedTouches[0]?.clientX;
        if (start === undefined || end === undefined) return;
        if (start - end > 40) setRevealed(true);
        if (end - start > 40) setRevealed(false);
      }}
    >
    <button className="transaction-row" onClick={onOpen} type="button">
      <span className={`transaction-mark ${transaction.status}`}>
        <Icon name={transaction.source_type === "receipt" ? "receipt" : "file"} size={18} />
      </span>
      <span className="transaction-copy">
        <strong>{merchant}</strong>
        <small>
          {compactDate(transaction.transaction_date)}
          <span aria-hidden="true"> · </span>
          {itemCount} item{itemCount === 1 ? "" : "s"}
        </small>
      </span>
      {transaction.status === "draft" && <span className="status-chip attention">Review</span>}
      <strong className="transaction-amount">
        {money(transaction.total_amount, transaction.currency)}
      </strong>
      <Icon name="chevron" size={17} />
    </button>
      <button
        className="row-delete-action"
        type="button"
        onClick={onDelete}
        aria-label={transaction.status === "draft" ? "Discard draft" : "Delete expense"}
      >
        <Icon name="trash" size={16} />
        {transaction.status === "draft" ? "Discard" : "Delete"}
      </button>
    </div>
  );
}

function PeriodToolbar({
  period,
  onPeriodChange,
  onRefresh,
}: {
  period: DashboardPeriod;
  onPeriodChange: (period: DashboardPeriod) => void;
  onRefresh: () => void;
}) {
  return (
    <section className="overview-toolbar">
      <div className="period-control" aria-label="Dashboard period">
        {periodOptions.map((option) => (
          <button
            className={period === option.value ? "active" : ""}
            key={option.value}
            onClick={() => onPeriodChange(option.value)}
            type="button"
          >
            {option.label}
          </button>
        ))}
      </div>
      <button className="icon-button" onClick={onRefresh} title="Refresh overview" type="button">
        <Icon name="refresh" />
      </button>
    </section>
  );
}

export function Overview({
  dashboard,
  period,
  section,
  initialTrendView,
  transactions,
  transactionStatus,
  activityFilter = "all",
  onSectionChange,
  onPeriodChange,
  onRefresh,
  onLoadTransactions,
  onActivityFilterChange = () => undefined,
  onAdd,
  onReview,
  onLoadCategoryBreakdown,
  onOpenTransaction,
  onDeleteTransaction = () => undefined,
  onLoadDayTransactions,
  onOpenPrice,
  onLoadPersonalBasket,
  onOpenBasketProduct = () => undefined,
  priceHistory,
  onClosePriceHistory = () => undefined,
  onLoadMerchantBreakdown,
  onLoadMerchantTransactions,
  nutritionSummary,
  nutritionStatus = "idle",
  nutritionItem,
  onOpenNutritionItem = () => undefined,
  onCloseNutritionItem = () => undefined,
}: Props) {
  const initialCurrency =
    dashboard.totals.find((total) => total.currency === dashboard.default_currency)?.currency ||
    dashboard.totals[0]?.currency ||
    dashboard.default_currency;
  const [currency, setCurrency] = useState(initialCurrency);
  // Price Watch and My Inflation track repeat purchases of the same product over time,
  // which is a per-currency question on its own terms - it shouldn't go silent just
  // because the spend-totals toggle above happens to be set to a currency with no
  // repeat purchases yet. Independent state, same currency options.
  const [pricesCurrency, setPricesCurrency] = useState(initialCurrency);
  const [trendView, setTrendView] = useState<"months" | "calendar">(
    initialTrendView ?? "months",
  );
  const [priceView, setPriceView] = useState<"deals" | "inflation">("deals");
  const [breakdownView, setBreakdownView] = useState<"categories" | "merchants">("categories");
  const [confirmTarget, setConfirmTarget] = useState<ExpenseTransaction>();
  const [breakdownStack, setBreakdownStack] = useState<
    Array<{ focus: DashboardCategory; items: DashboardCategory[] }>
  >([]);
  const [breakdownStatus, setBreakdownStatus] = useState<"idle" | "loading" | "error">("idle");
  const [selectedMerchant, setSelectedMerchant] = useState<MerchantSpend>();

  useEffect(() => {
    if (!dashboard.totals.some((total) => total.currency === currency)) {
      setCurrency(initialCurrency);
    }
  }, [currency, dashboard.totals, initialCurrency]);

  useEffect(() => {
    if (!dashboard.totals.some((total) => total.currency === pricesCurrency)) {
      setPricesCurrency(initialCurrency);
    }
  }, [pricesCurrency, dashboard.totals, initialCurrency]);

  useEffect(() => {
    if (section === "transactions" && transactionStatus === "idle") {
      onLoadTransactions();
    }
  }, [section, transactionStatus, onLoadTransactions]);

  const categories = useMemo(
    () => dashboard.categories.filter((category) => category.currency === currency),
    [currency, dashboard.categories],
  );
  const breakdown = breakdownStack[breakdownStack.length - 1];
  const visibleCategories = breakdown?.items || categories;
  const listedCategories = visibleCategories;

  useEffect(() => {
    setBreakdownStack([]);
    setBreakdownStatus("idle");
    setSelectedMerchant(undefined);
  }, [currency, period]);

  async function openBreakdown(category: DashboardCategory) {
    if (!category.has_children || breakdownStatus === "loading") return;
    setBreakdownStatus("loading");
    try {
      const items = await onLoadCategoryBreakdown(category, currency, dashboard.window);
      if (items.length) {
        setBreakdownStack((current) => [...current, { focus: category, items }]);
      }
      setBreakdownStatus("idle");
    } catch {
      setBreakdownStatus("error");
    }
  }
  const activeTotal =
    dashboard.totals.find((total) => total.currency === currency) || dashboard.totals[0];
  const priceChanges = useMemo(
    () => dashboard.price_changes.filter((change) => change.currency === pricesCurrency),
    [pricesCurrency, dashboard.price_changes],
  );
  const listedTransactions = transactions?.transactions || [];
  const hasMoreTransactions =
    Boolean(transactions) &&
    transactions!.offset + listedTransactions.length < transactions!.total;

  return (
    <main className="overview">
      <nav className="app-tabs" aria-label="Expense tracker sections" role="tablist">
        {sectionOptions.map((option) => {
          const count =
            option.value === "transactions"
              ? transactions?.total ?? dashboard.recent_transactions.length
              : option.value === "prices"
                ? dashboard.price_changes.length
                : option.value === "nutrition"
                  ? nutritionSummary?.total_item_count
                  : undefined;
          return (
            <button
              aria-controls={`tracker-panel-${option.value}`}
              aria-selected={section === option.value}
              className={section === option.value ? "active" : ""}
              key={option.value}
              onClick={() => onSectionChange(option.value)}
              role="tab"
              type="button"
            >
              <Icon name={option.icon} size={17} />
              <span>{option.label}</span>
              {count !== undefined && count > 0 && <small>{count}</small>}
            </button>
          );
        })}
      </nav>

      {section === "overview" && (
        <PeriodToolbar period={period} onPeriodChange={onPeriodChange} onRefresh={onRefresh} />
      )}

      {section === "overview" && (
        <div className="tracker-screen" id="tracker-panel-overview" role="tabpanel">
          <section className="spend-hero">
            <div className="hero-heading">
              <p className="section-kicker">
                CONFIRMED SPEND · {dashboard.window.label.toUpperCase()}
              </p>
              {dashboard.totals.length > 1 && (
                <div className="currency-toggle" aria-label="Currency">
                  {dashboard.totals.map((total) => (
                    <button
                      className={currency === total.currency ? "active" : ""}
                      key={total.currency}
                      onClick={() => setCurrency(total.currency)}
                      type="button"
                    >
                      {total.currency}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {activeTotal ? (
              <>
                <strong className="hero-amount">
                  <DisplayAmount value={money(activeTotal.current_amount, activeTotal.currency)} />
                </strong>
                <div className="hero-meta">
                  {Number(activeTotal.current_amount) !== 0 && (
                    <Delta
                      value={activeTotal.delta_percent}
                      suffix={previousWindowLabel(dashboard.window)}
                    />
                  )}
                  {dashboard.needs_review_count > 0 && (
                    <button className="review-chip" onClick={onReview} type="button">
                      <span>{dashboard.needs_review_count}</span> to review
                    </button>
                  )}
                </div>
              </>
            ) : (
              <div className="empty-state compact">
                <Icon name="chart" />
                <span>Confirm an expense to start your overview.</span>
              </div>
            )}
          </section>

          <div className="overview-grid">
            <section className="surface category-panel">
              <div className="panel-heading">
                <div>
                  <h3>
                    {breakdown
                      ? breakdown.focus.category_name
                      : selectedMerchant
                        ? selectedMerchant.merchant_name
                        : "Where it went"}
                  </h3>
                  {breakdown && (
                    <p className="breakdown-level">
                      {`${breakdown.items[0]?.taxonomy_level_name || "Deeper"} breakdown`}
                    </p>
                  )}
                </div>
                <div className="breakdown-actions">
                  {breakdown && (
                    <button
                      className="micro-link breakdown-back"
                      type="button"
                      onClick={() => {
                        setBreakdownStack((current) => current.slice(0, -1));
                        setBreakdownStatus("idle");
                      }}
                    >
                      <span aria-hidden="true">←</span> Back
                    </button>
                  )}
                  {!breakdown && selectedMerchant && (
                    <button
                      className="micro-link breakdown-back"
                      type="button"
                      onClick={() => setSelectedMerchant(undefined)}
                    >
                      <span aria-hidden="true">←</span> Back
                    </button>
                  )}
                  <span className="currency-label">{currency}</span>
                </div>
              </div>
              {breakdownStack.length > 0 && (
                <nav className="breakdown-breadcrumb" aria-label="Spending taxonomy">
                  <button type="button" onClick={() => setBreakdownStack([])}>All groups</button>
                  {breakdownStack.map((frame, index) => (
                    <span key={frame.focus.category_slug}>
                      <Icon name="chevron" size={11} />
                      <button
                        type="button"
                        onClick={() => setBreakdownStack((current) => current.slice(0, index + 1))}
                      >
                        {frame.focus.category_name}
                      </button>
                    </span>
                  ))}
                </nav>
              )}
              {!breakdown && !selectedMerchant && onLoadMerchantBreakdown && (
                <div className="view-toggle" role="group" aria-label="Where it went view">
                  <button
                    className={breakdownView === "categories" ? "active" : ""}
                    onClick={() => setBreakdownView("categories")}
                    type="button"
                  >
                    Categories
                  </button>
                  <button
                    className={breakdownView === "merchants" ? "active" : ""}
                    onClick={() => setBreakdownView("merchants")}
                    type="button"
                  >
                    Merchants
                  </button>
                </div>
              )}
              {selectedMerchant ? (
                <MerchantTransactionList
                  merchant={selectedMerchant}
                  onLoadMerchantTransactions={onLoadMerchantTransactions}
                  onOpenTransaction={onOpenTransaction}
                />
              ) : breakdownView === "merchants" && !breakdown && onLoadMerchantBreakdown ? (
                <MerchantBreakdownPanel
                  currency={currency}
                  period={period}
                  onLoadMerchantBreakdown={onLoadMerchantBreakdown}
                  onSelectMerchant={setSelectedMerchant}
                />
              ) : (
              <div className="category-bars">
                {listedCategories.map((category) => (
                  <button
                    className={`category-row ${category.has_children ? "drillable" : ""}`}
                    disabled={!category.has_children}
                    key={category.category_slug}
                    onClick={() => void openBreakdown(category)}
                    type="button"
                  >
                    <div className="category-label">
                      <span className="category-row-symbol">
                        <Icon name={categoryIcon(category.category_slug)} size={15} />
                      </span>
                      <span>
                        <strong>{category.category_name}</strong>
                        <small>{money(category.current_amount, category.currency)}</small>
                      </span>
                    </div>
                    <div className="category-track">
                      <span style={{ width: `${Math.max(3, Number(category.share_percent))}%` }} />
                    </div>
                    <div className="category-meta">
                      <div className="category-meta-text">
                        {Number(category.share_percent).toFixed(0) !== "0" && (
                          <span>{Number(category.share_percent).toFixed(0)}%</span>
                        )}
                        <Delta value={category.delta_percent} suffix="" />
                      </div>
                      {category.has_children && <Icon name="chevron" size={14} />}
                    </div>
                  </button>
                ))}
                {breakdownStatus === "loading" && (
                  <p className="empty-copy">Loading the next taxonomy level…</p>
                )}
                {breakdownStatus === "error" && (
                  <p className="empty-copy">That breakdown did not load. Go back and try again.</p>
                )}
                {!listedCategories.length && !visibleCategories.length && breakdownStatus !== "loading" && (
                  <p className="empty-copy">No expenses this period. Add one to see categories here.</p>
                )}
              </div>
              )}
            </section>

            <section className="surface insights-panel">
              <div className="panel-heading">
                <h3>Useful signals</h3>
              </div>
              <div className="insight-list">
                {dashboard.insights.slice(0, 3).map((insight) => (
                  <article
                    className={`insight ${insight.tone}`}
                    key={`${insight.kind}-${insight.title}`}
                  >
                    <span className="insight-icon">
                      <Icon
                        name={
                          insight.kind === "price"
                            ? "chart"
                            : insight.kind === "review"
                              ? "receipt"
                              : "sparkle"
                        }
                      />
                    </span>
                    <div>
                      <strong>{insight.title}</strong>
                      <p>{insight.detail}</p>
                    </div>
                  </article>
                ))}
                {!dashboard.insights.length && (
                  <p className="empty-copy">More signals appear as expenses are confirmed.</p>
                )}
              </div>
            </section>
          </div>
        </div>
      )}

      {section === "trends" && (
        <div className="tracker-screen" id="tracker-panel-trends" role="tabpanel">
          <div className="trend-view-bar">
            <div className="view-toggle" role="group" aria-label="Trends view">
              <button
                className={trendView === "months" ? "active" : ""}
                onClick={() => setTrendView("months")}
                type="button"
              >
                Months
              </button>
              <button
                className={trendView === "calendar" ? "active" : ""}
                onClick={() => setTrendView("calendar")}
                type="button"
              >
                Calendar
              </button>
            </div>
          </div>
          {trendView === "months" ? (
            <SpendTrend
              dashboard={dashboard}
              currency={currency}
              onCurrencyChange={setCurrency}
            />
          ) : (
            <SpendCalendar
              dashboard={dashboard}
              currency={currency}
              onCurrencyChange={setCurrency}
              onLoadDayTransactions={onLoadDayTransactions}
              onOpenTransaction={onOpenTransaction}
            />
          )}
        </div>
      )}

      {section === "transactions" && (
        <section
          className="surface recent-panel tab-panel tracker-screen"
          id="tracker-panel-transactions"
          role="tabpanel"
        >
          <div className="panel-heading transaction-heading">
            <h2>Activity</h2>
            <button className="text-button" onClick={onAdd} type="button">
              <Icon name="add" size={16} /> Add
            </button>
          </div>
          <div className="activity-filters" aria-label="Activity filters">
            {(["all", "draft", "confirmed"] as const).map((filter) => (
              <button
                type="button"
                className={activityFilter === filter ? "active" : ""}
                onClick={() => onActivityFilterChange(filter)}
                key={filter}
              >
                {filter === "all" ? "All" : filter === "draft" ? "Drafts" : "Confirmed"}
              </button>
            ))}
          </div>

          {transactionStatus === "loading" && !listedTransactions.length ? (
            <div className="transaction-skeletons" aria-label="Loading transactions">
              <span />
              <span />
              <span />
              <span />
            </div>
          ) : transactionStatus === "error" && !listedTransactions.length ? (
            <div className="empty-state">
              <Icon name="refresh" />
              <strong>Transaction history did not load</strong>
              <span>The rest of the tracker is still available.</span>
              <button className="primary-button small" onClick={() => onLoadTransactions()} type="button">
                Try again
              </button>
            </div>
          ) : (
            <>
              <div className="transaction-list">
                {listedTransactions.map((transaction) => (
                  <TransactionRow
                    key={transaction.id}
                    transaction={transaction}
                    onOpen={() => onOpenTransaction(transaction)}
                    onDelete={() => setConfirmTarget(transaction)}
                  />
                ))}
                {!listedTransactions.length && (
                  <div className="empty-state">
                    <Icon name="receipt" />
                    <strong>No expenses yet</strong>
                    <span>Scan a receipt or add one manually.</span>
                    <button className="primary-button small" onClick={onAdd} type="button">
                      Add your first expense
                    </button>
                  </div>
                )}
              </div>
              {hasMoreTransactions && (
                <button
                  className="load-more-button"
                  disabled={transactionStatus === "loading"}
                  onClick={() => onLoadTransactions(true)}
                  type="button"
                >
                  {transactionStatus === "loading" ? "Loading…" : "Load older transactions"}
                </button>
              )}
            </>
          )}
          {confirmTarget && (
            <ConfirmSheet
              title={confirmTarget.status === "draft" ? "Discard draft?" : "Delete expense?"}
              message="This permanently removes the expense and any owned receipt files."
              confirmLabel={confirmTarget.status === "draft" ? "Discard draft" : "Delete expense"}
              onCancel={() => setConfirmTarget(undefined)}
              onConfirm={() => {
                onDeleteTransaction(confirmTarget);
                setConfirmTarget(undefined);
              }}
            />
          )}
        </section>
      )}

      {section === "prices" && (
        <section
          className="surface price-panel tab-panel tracker-screen"
          id="tracker-panel-prices"
          role="tabpanel"
        >
          {priceHistory ? (
            <PriceHistoryPanel
              embedded
              history={priceHistory}
              onClose={onClosePriceHistory}
            />
          ) : (
            <>
              <div className="panel-heading">
                <h2>Tracked prices</h2>
                {dashboard.totals.length > 1 && (
                  <div className="trend-currencies" aria-label="Price Watch currency">
                    {dashboard.totals.map((total) => (
                      <button
                        className={pricesCurrency === total.currency ? "active" : ""}
                        key={total.currency}
                        onClick={() => setPricesCurrency(total.currency)}
                        type="button"
                      >
                        {total.currency}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="price-view-bar">
                <div className="view-toggle" role="group" aria-label="Price Watch view">
                  <button
                    className={priceView === "deals" ? "active" : ""}
                    onClick={() => setPriceView("deals")}
                    type="button"
                  >
                    Deals
                  </button>
                  <button
                    className={priceView === "inflation" ? "active" : ""}
                    onClick={() => setPriceView("inflation")}
                    type="button"
                  >
                    My Inflation
                  </button>
                </div>
              </div>
              {priceView === "inflation" ? (
                onLoadPersonalBasket ? (
                  <PersonalBasketPanel
                    currency={pricesCurrency}
                    onLoadPersonalBasket={onLoadPersonalBasket}
                    onOpenBasketProduct={onOpenBasketProduct}
                  />
                ) : null
              ) : (
            <>
              {priceChanges.some((change) => change.sample_size > 1) && (
                <div className="price-watch-signals" aria-label="Price Watch insights">
                  {priceChanges
                    .filter((change) => change.sample_size > 1)
                    .slice(0, 2)
                    .map((change) => (
                      <PriceWatchSignal
                        change={change}
                        key={`signal-${change.identity_key}-${change.normalized_unit}`}
                      />
                    ))}
                </div>
              )}
              <DealsList
                currency={pricesCurrency}
                priceChanges={priceChanges}
                onOpenPrice={onOpenPrice}
              />
            </>
              )}
            </>
          )}
        </section>
      )}

      {section === "nutrition" && (
        <section
          className="surface price-panel tab-panel tracker-screen"
          id="tracker-panel-nutrition"
          role="tabpanel"
        >
          <PeriodToolbar period={period} onPeriodChange={onPeriodChange} onRefresh={onRefresh} />
          <NutritionPanel
            currency={currency}
            onCloseItem={onCloseNutritionItem}
            onSelectItem={onOpenNutritionItem}
            selectedItem={nutritionItem}
            status={nutritionStatus}
            summary={nutritionSummary}
          />
        </section>
      )}
    </main>
  );
}
