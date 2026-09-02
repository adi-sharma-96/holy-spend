import { buildCalendarMonth, busiestDay, parseIsoDate } from "../calendar";
import { categoryIcon } from "../category-icons";
import { compactDate, money, percent } from "../format";
import { Icon } from "../icons";
import { DisplayAmount } from "./Money";
import type { ExpenseDashboard, ExpenseSnapshot, NutritionSummary, TrackerSection } from "../types";

type Props = {
  dashboard?: ExpenseDashboard;
  dashboardStatus: "loading" | "ready" | "error";
  displayName: string;
  expense?: ExpenseSnapshot;
  nutritionSummary?: NutritionSummary;
  surface: "overview" | "expense";
  busy?: string;
  notice?: string;
  onExpand: (section?: TrackerSection, trendView?: "months" | "calendar") => void;
  onAdd: () => void;
};

function merchantName(expense: ExpenseSnapshot): string {
  return (
    expense.transaction.merchant_name_normalized ||
    expense.transaction.merchant_name_raw ||
    "Expense draft"
  );
}

function daysElapsed(window: ExpenseDashboard["window"]): number {
  const start = new Date(`${window.current_start}T00:00:00Z`).getTime();
  const end = new Date(`${window.current_end}T00:00:00Z`).getTime();
  return Math.round((end - start) / 86_400_000) + 1;
}

const NUTRITION_RING_RADIUS = 37;
const NUTRITION_RING_CIRCUMFERENCE = 2 * Math.PI * NUTRITION_RING_RADIUS;

type NutritionRingSegment = { grade: string; dasharray: string; dashoffset: number };

function nutritionRingSegments(
  distribution: Array<{ grade: string; share_percent: string | number }>,
): NutritionRingSegment[] {
  let cumulative = 0;
  return distribution.map((bucket) => {
    const arcLength = (Number(bucket.share_percent) / 100) * NUTRITION_RING_CIRCUMFERENCE;
    const segment = {
      grade: bucket.grade,
      dasharray: `${arcLength} ${NUTRITION_RING_CIRCUMFERENCE - arcLength}`,
      dashoffset: -cumulative,
    };
    cumulative += arcLength;
    return segment;
  });
}

function nutritionGradeColor(grade: string): string {
  return grade === "unknown" ? "var(--border-strong)" : `var(--score-${grade})`;
}

function nutritionGradeBadgeStyle(grade: string): { background: string; color: string } {
  return { background: `var(--score-${grade}-soft)`, color: `var(--score-${grade})` };
}

export function InlineLauncher({
  dashboard,
  dashboardStatus,
  displayName,
  expense,
  nutritionSummary,
  surface,
  busy,
  notice,
  onExpand,
  onAdd,
}: Props) {
  const defaultTotal =
    dashboard?.totals.find((total) => total.currency === dashboard.default_currency) ||
    dashboard?.totals[0];
  const topCategories =
    dashboard?.categories
      .filter((category) => category.currency === defaultTotal?.currency)
      .slice(0, 4) || [];
  const recent = dashboard?.recent_transactions.slice(0, 4) || [];
  const priceChanges = dashboard?.price_changes.slice(0, 2) || [];
  const trendPoints =
    dashboard?.spend_trend.filter((point) => point.currency === defaultTotal?.currency) || [];
  const latestTrend = trendPoints[trendPoints.length - 1];
  const previousTrend = trendPoints[trendPoints.length - 2];
  const trendDeltaPercent =
    latestTrend && previousTrend && Number(previousTrend.amount) > 0
      ? ((Number(latestTrend.amount) - Number(previousTrend.amount)) / Number(previousTrend.amount)) *
        100
      : undefined;
  const trendMaximum = Math.max(...trendPoints.map((point) => Number(point.amount)), 1);
  const avgPerDay =
    dashboard && defaultTotal
      ? Number(defaultTotal.current_amount) / Math.max(1, daysElapsed(dashboard.window))
      : undefined;
  const secondaryTotal = dashboard?.totals.find(
    (total) => total.currency !== defaultTotal?.currency,
  );
  const recentSameCurrency = recent.every((transaction) => transaction.currency === defaultTotal?.currency);
  const recentTotalAmount = recentSameCurrency
    ? recent.reduce((sum, transaction) => sum + Number(transaction.total_amount), 0)
    : undefined;
  const priceUpCount =
    dashboard?.price_changes.filter(
      (change) => change.sample_size > 1 && Number(change.delta_percent) > 0,
    ).length ?? 0;
  const priceDownCount =
    dashboard?.price_changes.filter(
      (change) => change.sample_size > 1 && Number(change.delta_percent) < 0,
    ).length ?? 0;
  const priceTrackedCount = dashboard?.price_changes.length ?? 0;
  const nutritionGradeDistribution =
    nutritionSummary?.grade_distribution?.filter((bucket) => Number(bucket.share_percent) > 0) || [];
  const nutritionSegments = nutritionRingSegments(nutritionGradeDistribution);
  const nutritionProcessingSignal = nutritionSummary?.signals?.find(
    (signal) => signal.kind === "processing_level",
  );
  const nutritionItems = nutritionSummary?.groups?.flatMap((group) => group.items) || [];
  const nutritionGradeRank = (grade: string | null | undefined): number =>
    grade === "a" ? 0 : grade === "b" ? 1 : grade === "c" ? 2 : grade === "d" ? 3 : grade === "e" ? 4 : 5;
  // Best/worst within the pool must rank by grade first, spend only as a tiebreaker -
  // ranking by spend alone (the original approach) could show a highly-purchased B
  // ahead of a lower-spend A, which defeats the point of a "best"/"worst" list.
  const nutritionBest = nutritionItems
    .filter((item) => item.status === "matched" && (item.nutriscore_grade === "a" || item.nutriscore_grade === "b"))
    .sort((a, b) => {
      const gradeDiff = nutritionGradeRank(a.nutriscore_grade) - nutritionGradeRank(b.nutriscore_grade);
      return gradeDiff !== 0 ? gradeDiff : Number(b.spend_amount) - Number(a.spend_amount);
    })
    .slice(0, 2);
  const nutritionWorst = nutritionItems
    .filter((item) => item.status === "matched" && (item.nutriscore_grade === "d" || item.nutriscore_grade === "e"))
    .sort((a, b) => {
      const gradeDiff = nutritionGradeRank(b.nutriscore_grade) - nutritionGradeRank(a.nutriscore_grade);
      return gradeDiff !== 0 ? gradeDiff : Number(b.spend_amount) - Number(a.spend_amount);
    })
    .slice(0, 2);
  const windowEnd = dashboard ? parseIsoDate(dashboard.window.current_end) : undefined;
  const calendar =
    dashboard && windowEnd
      ? buildCalendarMonth(
          windowEnd.year,
          windowEnd.month,
          dashboard.daily_spend,
          defaultTotal?.currency || dashboard.default_currency,
        )
      : undefined;
  const calendarPeak = calendar ? busiestDay(calendar) : undefined;

  if (surface === "expense" && expense) {
    const transaction = expense.transaction;
    return (
      <main className="inline-launcher" aria-label="Expense ready to review">
        <header className="inline-launcher-header">
          <span className="brand-mark"><Icon name="receipt" size={20} /></span>
          <div>
            <p>Holy Spend</p>
            <h1>Review before it counts.</h1>
          </div>
        </header>
        <section className="inline-expense-summary">
          <span className={`transaction-mark ${transaction.status}`}>
            <Icon name={transaction.source_type === "receipt" ? "receipt" : "file"} size={18} />
          </span>
          <div>
            <p className="section-kicker">EXPENSE DRAFT</p>
            <strong>{merchantName(expense)}</strong>
            <small>
              {compactDate(transaction.transaction_date)} · {transaction.items?.length || 0} item
              {transaction.items?.length === 1 ? "" : "s"} · {transaction.validation_issues?.length || 0} warning
              {transaction.validation_issues?.length === 1 ? "" : "s"}
            </small>
          </div>
          <strong>{money(transaction.total_amount, transaction.currency)}</strong>
        </section>
        <button
          className="primary-button inline-review-button"
          type="button"
          onClick={() => onExpand()}
          disabled={Boolean(busy)}
        >
          Review
        </button>
        {notice && <p className="inline-review-notice">{notice}</p>}
      </main>
    );
  }

  return (
    <main className="inline-launcher inline-home" aria-label="Holy Spend">
      <header className="inline-launcher-header">
        <span className="brand-mark"><Icon name="receipt" size={20} /></span>
        <div>
          <p>Holy Spend</p>
          <h1>Good to see you, {displayName}.</h1>
        </div>
        <button
          className="inline-add-button"
          type="button"
          onClick={onAdd}
          disabled={Boolean(busy)}
          aria-label="Add expense"
        >
          <Icon name="add" size={18} />
        </button>
      </header>

      {dashboard ? (
        <>
          <div className="inline-card-rail" aria-label="Expense tracker highlights">
            <button
              className="inline-feature-card spend"
              type="button"
              onClick={() => onExpand("overview")}
            >
              <span className="inline-feature-heading">
                <span>
                  <Icon name="chart" size={16} /> Overview
                </span>
                <Icon name="chevron" size={15} />
              </span>
              <strong>
                <DisplayAmount
                  value={
                    defaultTotal
                      ? money(defaultTotal.current_amount, defaultTotal.currency)
                      : money(0, dashboard.default_currency)
                  }
                />
              </strong>
              <small>{dashboard.window.label} confirmed spend</small>
              {(avgPerDay !== undefined || secondaryTotal) && (
                <span className="inline-mini-stats">
                  {avgPerDay !== undefined && (
                    <span>
                      <small>Avg/day</small>
                      <strong>{money(avgPerDay, defaultTotal?.currency || dashboard.default_currency)}</strong>
                    </span>
                  )}
                  {secondaryTotal && (
                    <span>
                      <small>Also in {secondaryTotal.currency}</small>
                      <strong>{money(secondaryTotal.current_amount, secondaryTotal.currency)}</strong>
                    </span>
                  )}
                </span>
              )}
              <span className="inline-category-preview" aria-label="Top spending categories">
                {topCategories.map((category, index) => (
                  <span key={category.category_slug}>
                    <span className={`inline-category-icon tone-${index + 1}`}>
                      <Icon name={categoryIcon(category.category_slug)} size={15} />
                    </span>
                    <strong>{category.category_name}</strong>
                    <span className="inline-category-amount">
                      <strong>{money(category.current_amount, category.currency)}</strong>
                      <small>{Number(category.share_percent).toFixed(0)}%</small>
                    </span>
                  </span>
                ))}
                {!topCategories.length && (
                  <small>Spending-group insights will appear here</small>
                )}
                {topCategories.length > 0 && topCategories.length < 3 && (
                  <small className="inline-empty-note">
                    {daysElapsed(dashboard.window)} day
                    {daysElapsed(dashboard.window) === 1 ? "" : "s"} into {dashboard.window.label}.
                    More categories will show up here as you add expenses.
                  </small>
                )}
              </span>
            </button>

            <button
              className="inline-feature-card activity"
              type="button"
              onClick={() => onExpand("transactions")}
            >
              <span className="inline-feature-heading">
                <span>
                  <Icon name="receipt" size={16} /> Transactions
                </span>
                <Icon name="chevron" size={15} />
              </span>
              <span className="inline-mini-list">
                {recent.map((transaction) => {
                  const itemCount = transaction.item_count ?? transaction.items?.length ?? 0;
                  return (
                    <span key={transaction.id}>
                      <span>
                        <strong>
                          {transaction.merchant_name_normalized ||
                            transaction.merchant_name_raw ||
                            "Manual expense"}
                        </strong>
                        <small>
                          {compactDate(transaction.transaction_date)} · {itemCount} item
                          {itemCount === 1 ? "" : "s"}
                        </small>
                      </span>
                      <strong>{money(transaction.total_amount, transaction.currency)}</strong>
                    </span>
                  );
                })}
                {!recent.length && <small>No transactions yet</small>}
              </span>
              <span className="inline-feature-signal">
                {dashboard.needs_review_count
                  ? `${dashboard.needs_review_count} waiting for review`
                  : "Everything is reviewed"}
                {recentTotalAmount !== undefined && recent.length > 0 && (
                  <>
                    {" "}
                    · {money(recentTotalAmount, defaultTotal?.currency || dashboard.default_currency)}{" "}
                    shown
                  </>
                )}
              </span>
            </button>

            <button
              className="inline-feature-card trends"
              type="button"
              onClick={() => onExpand("trends")}
            >
              <span className="inline-feature-heading">
                <span>
                  <Icon name="chart" size={16} /> Trends
                </span>
                {trendDeltaPercent !== undefined ? (
                  <span className={`inline-trend-badge ${trendDeltaPercent >= 0 ? "up" : "down"}`}>
                    {trendDeltaPercent >= 0 ? "↑" : "↓"} {percent(trendDeltaPercent)}
                  </span>
                ) : (
                  <Icon name="chevron" size={15} />
                )}
              </span>
              <span className="inline-mini-trend" aria-label="Six-month spending chart">
                {trendPoints.map((point, index) => (
                  <span
                    className={index === trendPoints.length - 1 ? "current" : ""}
                    key={`${point.currency}-${point.period_start}`}
                  >
                    <i
                      style={{
                        height: `${Math.max(8, (Number(point.amount) / trendMaximum) * 100)}%`,
                      }}
                    />
                    <small>{point.label}</small>
                  </span>
                ))}
              </span>
              <span className="inline-feature-signal">
                {latestTrend ? (
                  <>
                    {latestTrend.label} · <strong>{money(latestTrend.amount, latestTrend.currency)}</strong>
                    {trendDeltaPercent !== undefined && previousTrend && (
                      <>
                        {" "}
                        · {trendDeltaPercent >= 0 ? "up" : "down"} {percent(trendDeltaPercent)} vs{" "}
                        {previousTrend.label}
                      </>
                    )}
                  </>
                ) : (
                  "Monthly spending will appear here"
                )}
              </span>
            </button>

            <button
              className="inline-feature-card prices"
              type="button"
              onClick={() => onExpand("prices")}
            >
              <span className="inline-feature-heading">
                <span>
                  <Icon name="sparkle" size={16} /> Price Watch
                </span>
                <Icon name="chevron" size={15} />
              </span>
              {priceChanges.length ? (
                <span className="inline-price-list">
                  {priceChanges.map((change) => {
                    const movement =
                      change.delta_percent === null || change.delta_percent === undefined
                        ? undefined
                        : Number(change.delta_percent);
                    return (
                      <span
                        className="inline-price-sig"
                        key={`${change.identity_key}-${change.normalized_unit}`}
                      >
                        <span
                          className={`inline-price-dir ${
                            movement === undefined ? "" : movement > 0 ? "up" : "down"
                          }`}
                        >
                          <Icon
                            name={
                              movement === undefined
                                ? "sparkle"
                                : movement > 0
                                  ? "arrow-up"
                                  : "arrow-down"
                            }
                            size={14}
                          />
                        </span>
                        <span className="inline-price-copy">
                          <strong>{change.label}</strong>
                          <small>
                            {money(change.current_price, change.currency)}/{change.normalized_unit}
                            {change.current_merchant ? ` at ${change.current_merchant}` : ""}
                          </small>
                        </span>
                        {movement !== undefined ? (
                          <span className={`inline-price-pct ${movement > 0 ? "up" : "down"}`}>
                            {movement > 0 ? "+" : "−"}
                            {percent(change.delta_percent)}
                          </span>
                        ) : (
                          <span className="inline-price-pct neutral">Watching</span>
                        )}
                      </span>
                    );
                  })}
                </span>
              ) : (
                <>
                  <strong>Building price history</strong>
                  <small>Same product · same currency · same unit</small>
                  <span className="inline-feature-signal">
                    More comparable purchases unlock trends
                  </span>
                </>
              )}
              {priceTrackedCount > 0 && (
                <span className="inline-feature-signal">
                  {priceTrackedCount} product{priceTrackedCount === 1 ? "" : "s"} tracked
                  {priceUpCount > 0 && ` · ${priceUpCount} up`}
                  {priceDownCount > 0 && ` · ${priceDownCount} down`}
                </span>
              )}
            </button>

            {calendar && (
              <button
                className="inline-feature-card calendar"
                type="button"
                onClick={() => onExpand("trends", "calendar")}
              >
                <span className="inline-feature-heading">
                  <span>
                    <Icon name="calendar" size={16} /> Calendar
                  </span>
                  <Icon name="chevron" size={15} />
                </span>
                <strong>
                  <DisplayAmount
                    value={money(calendar.total, defaultTotal?.currency || dashboard.default_currency)}
                  />
                </strong>
                <small>
                  {calendar.label}
                  {calendarPeak
                    ? ` · Busiest day: ${compactDate(calendarPeak.date)} · ${money(
                        calendarPeak.amount,
                        defaultTotal?.currency || dashboard.default_currency,
                      )}`
                    : ""}
                </small>
                <span className="inline-cal-dow" aria-hidden="true">
                  <span>M</span>
                  <span>T</span>
                  <span>W</span>
                  <span>T</span>
                  <span>F</span>
                  <span>S</span>
                  <span>S</span>
                </span>
                <span
                  className="inline-mini-cal"
                  aria-label={`${calendar.label} daily spending`}
                >
                  {Array.from({ length: calendar.leadingBlanks }, (_, index) => (
                    <i className="blank" key={`blank-${index}`} />
                  ))}
                  {calendar.days.map((day) => (
                    <i className={`level-${day.level}`} key={day.date} />
                  ))}
                </span>
              </button>
            )}

            {nutritionSummary && (
              <button
                className="inline-feature-card nutrition"
                type="button"
                onClick={() => onExpand("nutrition")}
              >
                <span className="inline-feature-heading">
                  <span>
                    <Icon name="leaf" size={16} /> Nutrition
                  </span>
                  <Icon name="chevron" size={15} />
                </span>
                <span className="inline-nutrition-body">
                  <span className="inline-nutrition-ring">
                    <svg width="86" height="86" viewBox="0 0 86 86">
                      <circle cx="43" cy="43" r={NUTRITION_RING_RADIUS} fill="none" stroke="var(--surface-soft)" strokeWidth="7" />
                      {nutritionSegments.map((segment) => (
                        <circle
                          key={segment.grade}
                          cx="43"
                          cy="43"
                          r={NUTRITION_RING_RADIUS}
                          fill="none"
                          stroke={nutritionGradeColor(segment.grade)}
                          strokeWidth="7"
                          strokeLinecap="round"
                          strokeDasharray={segment.dasharray}
                          strokeDashoffset={segment.dashoffset}
                          transform="rotate(-90 43 43)"
                        />
                      ))}
                    </svg>
                    <span
                      className="inline-nutrition-ring-grade"
                      style={{
                        color: nutritionSummary.overall_grade
                          ? nutritionGradeColor(nutritionSummary.overall_grade.toLowerCase())
                          : "var(--text-faint)",
                      }}
                    >
                      {nutritionSummary.overall_grade ? nutritionSummary.overall_grade.toUpperCase() : "?"}
                    </span>
                  </span>
                  <span className="inline-nutrition-stats">
                    <span className="inline-nutrition-stats-row">
                      <span>
                        <strong>{Math.round(Number(nutritionSummary.coverage_percent))}%</strong>
                        <small>Coverage</small>
                      </span>
                      <span>
                        <strong>
                          {nutritionSummary.matched_item_count}/{nutritionSummary.total_item_count}
                        </strong>
                        <small>Matched</small>
                      </span>
                    </span>
                    {nutritionSummary.overall_grade ? (
                      <span className="inline-nutrition-legend">
                        {nutritionGradeDistribution.map((bucket) => (
                          <span key={bucket.grade}>
                            <i style={{ background: nutritionGradeColor(bucket.grade) }} />
                            {bucket.grade === "unknown" ? "?" : bucket.grade.toUpperCase()}{" "}
                            {Math.round(Number(bucket.share_percent))}%
                          </span>
                        ))}
                      </span>
                    ) : (
                      <span className="inline-nutrition-legend muted">Building your basket grade</span>
                    )}
                  </span>
                </span>
                {(nutritionBest.length > 0 || nutritionWorst.length > 0) && (
                  <span className="inline-nutrition-highlights">
                    {nutritionBest.length > 0 && (
                      <span className="inline-nutrition-highlight-group">
                        <small>Best</small>
                        {nutritionBest.map((item) => (
                          <span className="inline-nutrition-highlight-item" key={item.identity_key}>
                            <i style={nutritionGradeBadgeStyle(item.nutriscore_grade || "unknown")}>
                              {item.nutriscore_grade?.toUpperCase()}
                            </i>
                            <strong>{item.display_name}</strong>
                          </span>
                        ))}
                      </span>
                    )}
                    {nutritionWorst.length > 0 && (
                      <span className="inline-nutrition-highlight-group">
                        <small>Worst offenders</small>
                        {nutritionWorst.map((item) => (
                          <span className="inline-nutrition-highlight-item" key={item.identity_key}>
                            <i style={nutritionGradeBadgeStyle(item.nutriscore_grade || "unknown")}>
                              {item.nutriscore_grade?.toUpperCase()}
                            </i>
                            <strong>{item.display_name}</strong>
                          </span>
                        ))}
                      </span>
                    )}
                  </span>
                )}
                {nutritionProcessingSignal && (
                  <span
                    className={`inline-nutrition-footer${
                      nutritionProcessingSignal.tone === "warn" ? " warn" : ""
                    }`}
                  >
                    <span className="inline-nutrition-footer-icon">
                      <Icon name="leaf" size={13} />
                    </span>
                    <span className="inline-nutrition-footer-text">
                      <strong>{nutritionProcessingSignal.title}</strong>
                      <small>{nutritionProcessingSignal.detail}</small>
                    </span>
                  </span>
                )}
              </button>
            )}
          </div>
          <div className="inline-rail-dots" aria-hidden="true">
            <span className="on" />
            <span />
            <span />
            <span />
            {calendar && <span />}
            {nutritionSummary && <span />}
          </div>
        </>
      ) : (
        <section className="inline-loading" aria-live="polite">
          <span className="inline-loading-mark"><Icon name="refresh" size={18} /></span>
          <div>
            <strong>
              {dashboardStatus === "error"
                ? "Your overview needs another try"
                : "Loading your private tracker"}
            </strong>
            <p>Your saved expenses remain safe.</p>
          </div>
        </section>
      )}
    </main>
  );
}
