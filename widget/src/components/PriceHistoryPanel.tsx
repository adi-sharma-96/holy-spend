import { compactDate, money, quantityLabel } from "../format";
import { Icon } from "../icons";
import type { ItemPriceHistory } from "../types";

export function PriceHistoryPanel({
  history,
  onClose,
  embedded = false,
}: {
  history: ItemPriceHistory;
  onClose: () => void;
  embedded?: boolean;
}) {
  const series = history.series[0];
  const points = [...(series?.points || [])].reverse();
  const values = points.map((point) => Number(point.normalized_unit_price_amount));
  const rawMinimum = values.length ? Math.min(...values) : 0;
  const rawMaximum = values.length ? Math.max(...values) : 1;
  const rawRange = Math.max(rawMaximum - rawMinimum, rawMaximum * 0.08, 0.01);
  const minimum = Math.max(0, rawMinimum - rawRange * 0.15);
  const maximum = rawMaximum + rawRange * 0.15;
  const range = maximum - minimum;
  const coordinatePairs = points.map((point, index) => {
    const x = points.length === 1 ? 50 : (index / (points.length - 1)) * 100;
    const y = 88 - ((Number(point.normalized_unit_price_amount) - minimum) / range) * 70;
    return { x, y };
  });
  const coordinates = coordinatePairs.map(({ x, y }) => `${x},${y}`).join(" ");
  const finalPoint = points[points.length - 1];

  const content = (
    <>
        <header className="drawer-header">
          <button
            className="icon-button"
            onClick={onClose}
            aria-label={embedded ? "Back to Price Watch" : "Close price history"}
          >
            <Icon name={embedded ? "back" : "close"} />
          </button>
          <div className="drawer-title">
            <span className="transaction-mark price">
              <Icon name="chart" />
            </span>
            <div>
              <h2>{history.label}</h2>
              <p>
                {series?.currency} per {series?.normalized_unit}
              </p>
            </div>
          </div>
        </header>

        {series && series.points.length > 0 ? (
          <>
            <section className="price-summary">
              <span>
                Latest
                <strong>
                  {money(series.points[0]!.normalized_unit_price_amount, series.currency)}
                  <small>/{series.normalized_unit}</small>
                </strong>
              </span>
              <span>
                Lowest
                <strong>
                  {money(Math.min(...values), series.currency)}
                  <small>/{series.normalized_unit}</small>
                </strong>
              </span>
              <span>
                Highest
                <strong>
                  {money(Math.max(...values), series.currency)}
                  <small>/{series.normalized_unit}</small>
                </strong>
              </span>
              <span>
                Purchases
                <strong>{series.points.length}</strong>
              </span>
            </section>

            <section className="history-chart" aria-label="Price trend chart">
              <svg viewBox="0 0 100 100" preserveAspectRatio="none">
                <path d="M0 88H100" className="chart-axis" />
                <polyline points={coordinates} className="chart-line" />
                {points.map((point, index) => {
                  const coordinate = coordinatePairs[index]!;
                  return (
                    <circle
                      cx={coordinate.x}
                      cy={coordinate.y}
                      r="2.4"
                      key={point.transaction_item_id}
                    />
                  );
                })}
              </svg>
              <div className="chart-labels">
                <span>{points[0] ? compactDate(points[0].transaction_date) : ""}</span>
                <span>{finalPoint ? compactDate(finalPoint.transaction_date) : ""}</span>
              </div>
            </section>

            <section className="price-history-list">
              <div className="panel-heading">
                <h3>Purchase history</h3>
                <span>Newest first</span>
              </div>
              {series.points.map((point) => (
                <div className="history-point" key={point.transaction_item_id}>
                  <span className="history-date">{compactDate(point.transaction_date)}</span>
                  <span>
                    <strong>{point.display_name}</strong>
                    <small>
                      {point.merchant_name || "Unknown merchant"}
                      {" · "}
                      {quantityLabel(point)}
                    </small>
                  </span>
                  <strong>
                    {money(point.normalized_unit_price_amount, point.currency)}
                    <small>/{point.normalized_unit}</small>
                  </strong>
                </div>
              ))}
            </section>

          </>
        ) : (
          <div className="empty-state">
            <Icon name="chart" />
            <strong>Not enough comparable prices</strong>
            <span>Capture weight, volume, package size, or count to build this history.</span>
          </div>
        )}
    </>
  );

  if (embedded) {
    return (
      <section className="price-history-embedded" aria-label={`${history.label} price history`}>
        {content}
      </section>
    );
  }

  return (
    <div
      className="drawer-backdrop"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <aside className="price-drawer" aria-label={`${history.label} price history`}>
        {content}
      </aside>
    </div>
  );
}
