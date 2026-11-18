import { useCallback, useEffect, useMemo, useState } from "react";
import { compactDate, money } from "./format";
import { Overview } from "./components/Overview";
import { TransactionDetail } from "./components/TransactionDetail";
import {
  exchangeTrackerLaunch,
  logoutTracker,
  TRACKER_PATH,
  trackerData,
  type SpendingRow,
  type TrackerData,
} from "./hosted-data";
import { dashboardCategoryBreakdown } from "./taxonomy";
import type {
  DashboardPeriod,
  ExpenseDashboard,
  ExpenseSnapshot,
  ItemPriceHistory,
  NutritionItem,
  NutritionSummary,
  TrackerSection,
  TransactionListResponse,
} from "./types";

type LoadStatus = "idle" | "loading" | "ready" | "error";
type ActivityFilter = "all" | "draft" | "confirmed";

let launchSecret: string | undefined;

function captureLaunchFragment(): boolean {
  const fragment = window.location.hash.slice(1);
  if (!fragment) return false;
  window.history.replaceState(null, "", TRACKER_PATH);
  launchSecret = /^[A-Za-z0-9_-]{43}$/.test(fragment) ? fragment : undefined;
  return true;
}

export function isHostedTrackerPage(): boolean {
  if (window.self !== window.top || window.location.pathname !== TRACKER_PATH) return false;
  captureLaunchFragment();
  return true;
}

function SpendingInspector({
  data, dashboard, period, currency, onClose, onOpen,
}: {
  data: TrackerData;
  dashboard: ExpenseDashboard;
  period: DashboardPeriod;
  currency: string;
  onClose: () => void;
  onOpen: (id: string) => void;
}) {
  const [interval, setInterval] = useState<"current" | "previous">("current");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<SpendingRow[]>();
  const [error, setError] = useState(false);
  const window = dashboard.window;
  const start = interval === "current" ? window.current_start : window.previous_start;
  const end = interval === "current" ? window.current_end : window.previous_end;

  useEffect(() => {
    const controller = new AbortController();
    setRows(undefined);
    setError(false);
    data.spending(period, currency, interval, offset, controller.signal)
      .then(setRows)
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [data, period, currency, interval, offset]);

  return (
    <div className="drawer-backdrop">
      <aside className="detail-drawer hosted-spending" aria-label="Included transactions">
        <header className="panel-heading">
          <h2>Included transactions</h2>
          <button className="secondary-button small" type="button" onClick={onClose}>Close</button>
        </header>
        <p>{compactDate(start)} to {compactDate(end)} · {currency}</p>
        <div className="view-toggle" aria-label="Comparison window">
          {(["current", "previous"] as const).map((choice) => (
            <button
              className={choice === interval ? "active" : ""} key={choice} type="button"
              onClick={() => { setOffset(0); setInterval(choice); }}
            >
              {choice === "current" ? "Current period" : "Previous period"}
            </button>
          ))}
        </div>
        {error ? <p role="alert">Included transactions could not load.</p> : !rows ? (
          <p role="status">Loading transactions…</p>
        ) : rows.length === 0 ? <p>No transactions on this page.</p> : (
          <ul className="hosted-spending-list">
            {rows.map((row) => (
              <li key={row.id}>
                <button type="button" className="text-button" onClick={() => onOpen(row.id)}>
                  {row.merchant || "Recorded expense"} · {money(row.amount, row.currency)}
                </button>
                <small className="spending-comparison-note">
                  {compactDate(row.transaction_date)} · {row.classification} ·{" "}
                  {row.recurrence.length ? row.recurrence.map((value) => value.split(".").pop()).join(", ") : "Recurrence unknown"}
                </small>
              </li>
            ))}
          </ul>
        )}
        <div className="view-toggle">
          {offset > 0 && <button type="button" onClick={() => setOffset(offset - 50)}>Previous page</button>}
          {rows?.length === 50 && <button type="button" onClick={() => setOffset(offset + 50)}>Next page</button>}
        </div>
        <p>To update a classification, ask in your connected chat.</p>
      </aside>
    </div>
  );
}

function HostedDashboard({ data }: { data: TrackerData }) {
  const [section, setSection] = useState<TrackerSection>("overview");
  const [period, setPeriod] = useState<DashboardPeriod>("month");
  const [refresh, setRefresh] = useState(0);
  const [dashboard, setDashboard] = useState<ExpenseDashboard>();
  const [dashboardStatus, setDashboardStatus] = useState<LoadStatus>("loading");
  const [nutrition, setNutrition] = useState<NutritionSummary>();
  const [nutritionItem, setNutritionItem] = useState<NutritionItem>();
  const [nutritionStatus, setNutritionStatus] = useState<LoadStatus>("idle");
  const [nutritionCurrency, setNutritionCurrency] = useState<string>();
  const [proteinOffset, setProteinOffset] = useState(0);
  const [transactions, setTransactions] = useState<TransactionListResponse>();
  const [transactionStatus, setTransactionStatus] = useState<LoadStatus>("idle");
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>("all");
  const [expense, setExpense] = useState<ExpenseSnapshot>();
  const [history, setHistory] = useState<ItemPriceHistory>();
  const [inspectCurrency, setInspectCurrency] = useState<string>();
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setDashboardStatus("loading");
    data.dashboard(period, controller.signal).then((response) => {
      if (controller.signal.aborted) return;
      setDashboard(response);
      setDashboardStatus("ready");
    }).catch(() => { if (!controller.signal.aborted) setDashboardStatus("error"); });
    return () => controller.abort();
  }, [data, period, refresh]);

  const selectedCurrency = nutritionCurrency || dashboard?.default_currency;
  useEffect(() => {
    if (section !== "nutrition" || !selectedCurrency) return;
    const controller = new AbortController();
    setNutritionStatus("loading");
    setNutritionItem(undefined);
    data.nutrition(period, selectedCurrency, proteinOffset, controller.signal).then((summary) => {
      if (controller.signal.aborted) return;
      setNutrition(summary);
      setNutritionStatus("ready");
    }).catch(() => { if (!controller.signal.aborted) setNutritionStatus("error"); });
    return () => controller.abort();
  }, [data, section, period, selectedCurrency, refresh, proteinOffset]);

  async function loadTransactions(more = false, filter = activityFilter) {
    setTransactionStatus("loading");
    try {
      const result = await data.transactions({
        status: filter === "all" ? undefined : filter,
        offset: more ? transactions?.transactions.length : 0,
        limit: 30,
      });
      setTransactions((previous) => ({
        ...result,
        offset: 0,
        transactions: more ? [...(previous?.transactions || []), ...result.transactions] : result.transactions,
      }));
      setTransactionStatus("ready");
    } catch {
      setTransactionStatus("error");
    }
  }

  const openExpense = async (id: string) => {
    setError("");
    try {
      setExpense(await data.expense(id));
      setInspectCurrency(undefined);
    } catch {
      setError("Transaction details could not load.");
    }
  };

  const openPrice = async (key: string, currency: string, unit?: string) => {
    setError("");
    try {
      setHistory(await data.prices(key, currency, unit));
    } catch {
      setError("Price history could not load.");
    }
  };

  const loadDay = useCallback(async (day: string, currency: string) => {
    const response = await data.transactions({ start_date: day, end_date: day, currency, status: "confirmed", limit: 100 });
    return response.transactions.filter((row) => row.transaction_type === "expense" || row.transaction_type === "refund");
  }, [data]);

  const loadMerchantTransactions = useCallback(async (merchant: string, currency: string) => {
    const response = await data.transactions({
      merchant, currency, start_date: dashboard?.window.current_start,
      end_date: dashboard?.window.current_end, status: "confirmed", limit: 50,
    });
    return response.transactions;
  }, [data, dashboard?.window.current_start, dashboard?.window.current_end]);

  if (!dashboard || dashboardStatus === "loading") {
    return dashboardStatus !== "error" ? <p role="status">Loading tracker…</p> : (
      <section><p role="alert">The dashboard could not load.</p>
        <button className="secondary-button" onClick={() => setRefresh(refresh + 1)} type="button">Try again</button>
      </section>
    );
  }

  return (
    <>
      {error && <p role="alert">{error}</p>}
      {dashboardStatus === "error" && <p role="alert">The dashboard could not refresh.</p>}
      <Overview
        readOnly
        dashboard={dashboard}
        period={period}
        section={section}
        onSectionChange={setSection}
        onPeriodChange={(value) => { setProteinOffset(0); setPeriod(value); }}
        onRefresh={() => { setProteinOffset(0); setRefresh(refresh + 1); }}
        onInspectSpending={setInspectCurrency}
        onLoadCategoryBreakdown={async (parent, currency) =>
          dashboardCategoryBreakdown(
            await data.categories(period, currency, parent.category_slug, parent.taxonomy_level + 1),
            parent.category_slug, currency,
          )}
        transactions={transactions}
        transactionStatus={transactionStatus}
        activityFilter={activityFilter}
        onActivityFilterChange={(filter) => {
          if (transactionStatus === "loading") return;
          setActivityFilter(filter);
          setTransactions(undefined);
          void loadTransactions(false, filter);
        }}
        onLoadTransactions={(more) => void loadTransactions(more)}
        onOpenTransaction={(transaction) => void openExpense(transaction.id)}
        onLoadDayTransactions={loadDay}
        onLoadMerchantBreakdown={(currency, selectedPeriod) => data.merchants(selectedPeriod, currency)}
        onLoadMerchantTransactions={loadMerchantTransactions}
        onOpenPrice={(change) => void openPrice(change.identity_key, change.currency, change.normalized_unit)}
        priceHistory={history}
        onClosePriceHistory={() => setHistory(undefined)}
        onLoadPersonalBasket={data.basket}
        onOpenBasketProduct={(product) => void openPrice(`basket:${product.identity_key}`, product.currency, product.normalized_unit)}
        nutritionStatus={nutritionStatus}
        nutritionSummary={nutrition?.currency === selectedCurrency ? nutrition : undefined}
        nutritionItem={nutritionItem}
        onOpenNutritionItem={setNutritionItem}
        onCloseNutritionItem={() => setNutritionItem(undefined)}
        onNutritionCurrencyChange={(value) => { setProteinOffset(0); setNutritionCurrency(value); }}
        onProteinEvidencePage={setProteinOffset}
      />
      {inspectCurrency && <SpendingInspector
        data={data} dashboard={dashboard} period={period} currency={inspectCurrency}
        onClose={() => setInspectCurrency(undefined)} onOpen={(id) => void openExpense(id)}
      />}
      {expense && <TransactionDetail
        snapshot={expense} onClose={() => setExpense(undefined)}
        onDownload={async () => undefined} onPriceHistory={(key, currency) => data.prices(key, currency)}
      />}
    </>
  );
}

export function HostedTracker() {
  const [status, setStatus] = useState<"launch" | "active" | "expired" | "signed-out">(
    launchSecret ? "launch" : "active",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const data = useMemo(() => trackerData(() => {
    if (!launchSecret) setStatus("expired");
  }), []);

  useEffect(() => {
    // Navigating to another launch URL in this tab can be a same-document hash change.
    const receiveLaunch = () => {
      if (captureLaunchFragment()) {
        setError("");
        setStatus(launchSecret ? "launch" : "expired");
      }
    };
    window.addEventListener("hashchange", receiveLaunch);
    return () => window.removeEventListener("hashchange", receiveLaunch);
  }, []);

  async function signIn(event: React.MouseEvent<HTMLButtonElement>) {
    if (!event.isTrusted || !launchSecret || busy) return;
    const secret = launchSecret;
    launchSecret = undefined;
    setBusy(true);
    try {
      const opened = await exchangeTrackerLaunch(secret);
      if (!launchSecret) setStatus(opened ? "active" : "expired");
    } catch {
      if (!launchSecret) setStatus("expired");
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    setError("");
    setBusy(true);
    try {
      await logoutTracker();
      if (!launchSecret) setStatus("signed-out");
    } catch {
      setError("Sign-out did not finish. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="hosted-tracker">
      <header className="hosted-header">
        <div><h1>Holy Spend</h1><small>Read-only tracker</small></div>
        {status === "active" && <button className="secondary-button" type="button" disabled={busy} onClick={() => void signOut()}>Sign out</button>}
      </header>
      {error && <p role="alert">{error}</p>}
      {status === "active" ? <HostedDashboard data={data} /> : (
        <main className="surface hosted-launch">
          <h2>{status === "launch" ? "Open your tracker" : status === "signed-out" ? "Signed out" : "Open a fresh tracker link"}</h2>
          {status === "launch" ? (
            <button className="primary-button" disabled={busy} type="button" onClick={signIn}>
              {busy ? "Opening…" : "Open tracker"}
            </button>
          ) : <p>Ask your connected chat to open the hosted tracker again.</p>}
        </main>
      )}
    </div>
  );
}
