import { useCallback, useEffect, useRef, useState } from "react";
import {
  callTool,
  isDemoMode,
  openPrivateUrl,
  persistWidgetState,
  privateMeta,
  requestFullscreen,
  structured,
  subscribeToHostContext,
  subscribeToToolResults,
} from "./bridge";
import { ExpenseEditor } from "./components/ExpenseEditor";
import { InlineLauncher } from "./components/InlineLauncher";
import { Overview } from "./components/Overview";
import { TransactionDetail } from "./components/TransactionDetail";
import { draftFromSnapshot, emptyDraft, savePayload, type DraftForm } from "./draft";
import { Icon } from "./icons";
import { taxonomyHasChildren, taxonomyLevelName, taxonomyNode } from "./taxonomy";
import type {
  AnalyticsQueryResponse,
  Category,
  DashboardCategory,
  DashboardPeriod,
  ExpenseDashboard,
  ExpenseSnapshot,
  ExpenseTransaction,
  HostContext,
  ItemPriceHistory,
  MerchantBreakdownResponse,
  NutritionItem,
  NutritionSummary,
  PersonalBasketIndex,
  PriceChange,
  TrackerSection,
  ToolResult,
  TransactionListResponse,
} from "./types";

type ActivityFilter = "all" | "draft" | "confirmed";

const ROOT_ROUTES = new Set([
  "/overview",
  "/transactions",
  "/trends",
  "/prices",
  "/nutrition",
  "/expenses/new",
]);

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}

function expenseFromResult(result: ToolResult): ExpenseSnapshot | undefined {
  const value = structured<Record<string, unknown>>(result);
  if (value.expense && typeof value.expense === "object") {
    const nested = value.expense as Record<string, unknown>;
    if (nested.transaction) return nested as unknown as ExpenseSnapshot;
  }
  if (value.transaction) return value as unknown as ExpenseSnapshot;
  return undefined;
}

function expenseRoute(route: string): { transactionId?: string; review: boolean } {
  const match = route.match(
    /^\/expenses\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})(\/review)?$/i,
  );
  return { transactionId: match?.[1], review: Boolean(match?.[2]) };
}

function validRoute(route: unknown): route is string {
  return (
    typeof route === "string" &&
    (ROOT_ROUTES.has(route) || Boolean(expenseRoute(route).transactionId))
  );
}

function initialRoute(): string {
  const saved = window.openai?.widgetState?.route;
  if (validRoute(saved)) return saved;
  const path = window.location.pathname;
  return validRoute(path) ? path : "/overview";
}

function sectionForRoute(route: string): TrackerSection {
  if (route === "/transactions") return "transactions";
  if (route === "/trends") return "trends";
  if (route === "/prices") return "prices";
  if (route === "/nutrition") return "nutrition";
  return "overview";
}

function routeForSection(section: TrackerSection): string {
  if (section === "transactions") return "/transactions";
  if (section === "trends") return "/trends";
  if (section === "prices") return "/prices";
  if (section === "nutrition") return "/nutrition";
  return "/overview";
}

function LoadingOverview() {
  return (
    <main className="overview loading-overview" aria-label="Loading expense overview">
      <div className="skeleton toolbar-skeleton" />
      <div className="skeleton hero-skeleton" />
      <div className="overview-grid">
        <div className="skeleton panel-skeleton" />
        <div className="skeleton panel-skeleton" />
      </div>
      <div className="skeleton list-skeleton" />
    </main>
  );
}

function DashboardUnavailable({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="overview dashboard-unavailable" role="status">
      <div className="unavailable-card">
        <span className="unavailable-icon"><Icon name="refresh" size={20} /></span>
        <div>
          <strong>Your overview took too long to load</strong>
          <p>Your expense data is safe. Retry the private connection without leaving this view.</p>
        </div>
        <button className="primary-button" type="button" onClick={onRetry}>
          Try again
        </button>
      </div>
    </main>
  );
}

function ExpenseUnavailable({
  message,
  onRetry,
  onBack,
}: {
  message: string;
  onRetry: () => void;
  onBack: () => void;
}) {
  return (
    <main className="overview dashboard-unavailable" role="status">
      <div className="unavailable-card">
        <span className="unavailable-icon"><Icon name="refresh" size={20} /></span>
        <div>
          <strong>Transaction details did not load</strong>
          <p>{message}</p>
        </div>
        <div className="unavailable-actions">
          <button className="secondary-button" type="button" onClick={onBack}>Back</button>
          <button className="primary-button" type="button" onClick={onRetry}>Try again</button>
        </div>
      </div>
    </main>
  );
}

export function App() {
  const [route, setRoute] = useState(initialRoute);
  const [period, setPeriod] = useState<DashboardPeriod>(
    (window.openai?.widgetState?.period as DashboardPeriod) || "month",
  );
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>(
    (window.openai?.widgetState?.activityFilter as ActivityFilter) || "all",
  );
  const [dashboard, setDashboard] = useState<ExpenseDashboard>();
  const [dashboardStatus, setDashboardStatus] = useState<"loading" | "ready" | "error">("loading");
  const [nutritionSummary, setNutritionSummary] = useState<NutritionSummary>();
  const [nutritionStatus, setNutritionStatus] = useState<"idle" | "loading" | "ready" | "error">(
    "idle",
  );
  const [nutritionItem, setNutritionItem] = useState<NutritionItem>();
  const [transactions, setTransactions] = useState<TransactionListResponse>();
  const [transactionStatus, setTransactionStatus] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");
  const [form, setForm] = useState<DraftForm>(() => emptyDraft());
  const [expense, setExpense] = useState<ExpenseSnapshot>();
  const [selectedExpense, setSelectedExpense] = useState<ExpenseSnapshot>();
  const [expenseStatus, setExpenseStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [expenseError, setExpenseError] = useState<string>();
  const [inlineExpenseSummary, setInlineExpenseSummary] = useState(false);
  const [priceHistory, setPriceHistory] = useState<ItemPriceHistory>();
  const [categories, setCategories] = useState<Category[]>([]);
  const [currencies, setCurrencies] = useState(["CAD", "USD"]);
  const [adjustmentTypes, setAdjustmentTypes] = useState([
    "discount",
    "tax",
    "fee",
    "tip",
    "deposit",
    "rounding",
  ]);
  const [issues, setIssues] = useState<
    Array<{ severity: string; code: string; message: string }>
  >([]);
  const [approved, setApproved] = useState(false);
  const [hostContext, setHostContext] = useState<HostContext>({});
  const [busy, setBusy] = useState<string>();
  const [notice, setNotice] = useState(
    "Ready for a manual expense. To scan a receipt, attach it directly in this chat.",
  );
  const [error, setError] = useState<string>();
  const [successVisible, setSuccessVisible] = useState(false);
  const [pendingTrendView, setPendingTrendView] = useState<"months" | "calendar">();
  const routeRef = useRef(route);
  const expenseRef = useRef(expense);
  const previousDisplayMode = useRef<HostContext["displayMode"]>(undefined);

  useEffect(() => {
    routeRef.current = route;
  }, [route]);

  useEffect(() => {
    expenseRef.current = expense;
  }, [expense]);

  const navigate = useCallback((nextRoute: string) => {
    if (!validRoute(nextRoute)) return;
    routeRef.current = nextRoute;
    setRoute(nextRoute);
  }, []);

  const applyExpense = useCallback((next: ExpenseSnapshot) => {
    setExpense(next);
    expenseRef.current = next;
    setForm(draftFromSnapshot(next));
    setIssues(next.transaction.validation_issues || []);
    setApproved(false);
    setExpenseStatus("ready");
    setExpenseError(undefined);
  }, []);

  function invalidateSummaries() {
    setDashboard(undefined);
    setDashboardStatus("loading");
    setTransactions(undefined);
    setTransactionStatus("idle");
  }

  async function run<T>(label: string, action: () => Promise<T>): Promise<T | undefined> {
    if (busy) return undefined;
    setBusy(label);
    setError(undefined);
    try {
      return await action();
    } catch (caught) {
      setError(errorMessage(caught));
      return undefined;
    } finally {
      setBusy(undefined);
    }
  }

  const loadDashboard = useCallback(async (nextPeriod: DashboardPeriod) => {
    setDashboardStatus("loading");
    try {
      const result = await callTool("get_expense_dashboard", {
        request: {
          period: nextPeriod,
          recent_limit: 12,
          category_limit: 30,
          price_change_limit: 24,
        },
      });
      setDashboard(structured<ExpenseDashboard>(result));
      setPeriod(nextPeriod);
      setDashboardStatus("ready");
    } catch (caught) {
      setDashboardStatus("error");
      setError(errorMessage(caught));
    }
  }, []);

  const loadCategoryBreakdown = useCallback(
    async (
      parent: DashboardCategory,
      currency: string,
      window: ExpenseDashboard["window"],
    ): Promise<DashboardCategory[]> => {
      const nextLevel = parent.taxonomy_level + 1;
      const result = await callTool("get_expense_analytics", {
        query: {
          metrics: ["total_spend"],
          group_by: ["category"],
          taxonomy_rollup_level: nextLevel,
          filters: {
            start_date: window.current_start,
            end_date: window.current_end,
            currency,
            taxonomy_node_key: parent.category_slug,
            include_descendants: true,
          },
        },
      });
      const response = structured<AnalyticsQueryResponse>(result);
      const rows = response.rows
        .map((row) => {
          const stableKey = row.dimensions.category;
          if (!stableKey || stableKey === parent.category_slug || stableKey.startsWith("unclassified.")) {
            return undefined;
          }
          const node = taxonomyNode(stableKey);
          const amount = Number(row.metrics.total_spend || 0);
          if (!node || !Number.isFinite(amount) || amount === 0) return undefined;
          return { stableKey, node, amount };
        })
        .filter((row): row is NonNullable<typeof row> => Boolean(row));
      const total = rows.reduce((sum, row) => sum + row.amount, 0);
      return rows
        .sort((left, right) => right.amount - left.amount || left.node.name.localeCompare(right.node.name))
        .map(({ stableKey, node, amount }) => ({
          category_slug: stableKey,
          category_name: node.name,
          taxonomy_level: node.level,
          taxonomy_level_name: taxonomyLevelName(node.level),
          has_children: taxonomyHasChildren(stableKey),
          currency,
          current_amount: amount,
          previous_amount: 0,
          delta_percent: null,
          share_percent: total ? (amount / total) * 100 : 0,
        }));
    },
    [],
  );

  const loadDayTransactions = useCallback(
    async (isoDate: string, currencyCode: string): Promise<ExpenseTransaction[]> => {
      const result = await callTool("list_expenses", {
        filters: {
          start_date: isoDate,
          end_date: isoDate,
          status: "confirmed",
          currency: currencyCode,
          limit: 50,
        },
      });
      return structured<TransactionListResponse>(result).transactions;
    },
    [],
  );

  const loadPersonalBasket = useCallback(
    async (currencyCode: string): Promise<PersonalBasketIndex> => {
      const result = await callTool("get_personal_basket_index", {
        request: { currency: currencyCode },
      });
      return structured<PersonalBasketIndex>(result);
    },
    [],
  );

  const loadMerchantBreakdown = useCallback(
    async (currencyCode: string, periodValue: DashboardPeriod): Promise<MerchantBreakdownResponse> => {
      const result = await callTool("get_merchant_breakdown", {
        request: { currency: currencyCode, period: periodValue },
      });
      return structured<MerchantBreakdownResponse>(result);
    },
    [],
  );

  const loadNutritionSummary = useCallback(
    async (currencyCode: string, periodValue: DashboardPeriod) => {
      setNutritionStatus("loading");
      try {
        const result = await callTool("get_nutrition_summary", {
          request: { currency: currencyCode, period: periodValue },
        });
        setNutritionSummary(structured<NutritionSummary>(result));
        setNutritionStatus("ready");
      } catch (caught) {
        setNutritionStatus("error");
        setError(errorMessage(caught));
      }
    },
    [],
  );

  const loadMerchantTransactions = useCallback(
    async (merchant: string, currencyCode: string): Promise<ExpenseTransaction[]> => {
      const result = await callTool("list_expenses", {
        filters: {
          merchant,
          status: "confirmed",
          currency: currencyCode,
          limit: 50,
        },
      });
      return structured<TransactionListResponse>(result).transactions;
    },
    [],
  );

  const loadTransactions = useCallback(
    async (loadMore = false, statusFilter: ActivityFilter = activityFilter) => {
      if (transactionStatus === "loading") return;
      const offset = loadMore ? transactions?.transactions.length || 0 : 0;
      setTransactionStatus("loading");
      try {
        const result = await callTool("list_expenses", {
          filters: {
            limit: 10,
            offset,
            status: statusFilter === "all" ? undefined : statusFilter,
          },
        });
        const page = structured<TransactionListResponse>(result);
        setTransactions((current) => {
          if (!loadMore || !current) return page;
          const known = new Set(current.transactions.map((transaction) => transaction.id));
          return {
            ...page,
            offset: 0,
            transactions: [
              ...current.transactions,
              ...page.transactions.filter((transaction) => !known.has(transaction.id)),
            ],
          };
        });
        setTransactionStatus("ready");
      } catch (caught) {
        setTransactionStatus("error");
        setError(errorMessage(caught));
      }
    },
    [activityFilter, transactionStatus, transactions?.transactions.length],
  );

  const refreshExpense = useCallback(async (transactionId: string) => {
    setExpenseStatus("loading");
    setExpenseError(undefined);
    try {
      const result = await callTool("get_expense", { transaction_id: transactionId });
      const next = expenseFromResult(result);
      if (!next) throw new Error("The expense tracker returned an empty transaction response.");
      applyExpense(next);
      return next;
    } catch (caught) {
      setExpenseStatus("error");
      setExpenseError(errorMessage(caught));
      throw caught;
    }
  }, [applyExpense]);

  useEffect(() => {
    let receivedEmbeddedDashboard = false;
    const unsubscribeResults = subscribeToToolResults((result) => {
      try {
        const value = structured<Record<string, unknown>>(result);
        if (validRoute(value.route)) navigate(value.route);
        if (value.expense && typeof value.expense === "object") {
          applyExpense(value.expense as ExpenseSnapshot);
          if (typeof value.route === "string" && expenseRoute(value.route).review) {
            setInlineExpenseSummary(true);
          }
        }
        if (value.validation && typeof value.validation === "object") {
          const validation = value.validation as {
            issues?: Array<{ severity: string; code: string; message: string }>;
          };
          if (validation.issues) setIssues(validation.issues);
        }
        if (value.data && typeof value.data === "object") {
          const data = value.data as Record<string, unknown>;
          if (data.dashboard && typeof data.dashboard === "object") {
            receivedEmbeddedDashboard = true;
            setDashboard(data.dashboard as ExpenseDashboard);
            setDashboardStatus("ready");
          } else if (typeof data.dashboard_error === "string") {
            setDashboardStatus("error");
            setError(data.dashboard_error);
          }
          if (typeof data.message === "string") setNotice(data.message);
        }
      } catch {
        // Data-only tool results also arrive through this channel.
      }
    });
    const unsubscribeHost = subscribeToHostContext((context) => {
      setHostContext(context);
      if (context.theme) {
        document.documentElement.dataset.hostTheme = context.theme;
        document.documentElement.style.colorScheme = context.theme;
      }
      if (context.locale) document.documentElement.lang = context.locale;
      if (context.displayMode) document.documentElement.dataset.displayMode = context.displayMode;
      const availableHeight =
        context.containerDimensions?.height || context.containerDimensions?.maxHeight;
      if (typeof availableHeight === "number" && availableHeight > 0) {
        document.documentElement.style.setProperty(
          "--host-available-height",
          `${Math.round(availableHeight)}px`,
        );
      }
      const insets = context.safeAreaInsets;
      if (insets) {
        document.documentElement.style.setProperty("--safe-top", `${insets.top || 0}px`);
        document.documentElement.style.setProperty("--safe-right", `${insets.right || 0}px`);
        document.documentElement.style.setProperty("--safe-bottom", `${insets.bottom || 0}px`);
        document.documentElement.style.setProperty("--safe-left", `${insets.left || 0}px`);
      }
    });

    void callTool("get_expense_taxonomy", {})
      .then((result) => {
        const taxonomy = structured<{
          assignable_nodes?: Array<Category & { stable_key: string }>;
          categories?: Category[];
          adjustment_types: string[];
          supported_currencies: string[];
        }>(result);
        setCategories(
          taxonomy.assignable_nodes?.map((node) => ({ ...node, slug: node.stable_key }))
            || taxonomy.categories
            || [],
        );
        setAdjustmentTypes(taxonomy.adjustment_types);
        setCurrencies(taxonomy.supported_currencies);
      })
      .catch(() => {
        // Taxonomy powers the editor but is not part of the overview contract.
        // A background hydration failure must not cover a healthy dashboard.
      });

    const inputRoute = window.openai?.toolInput?.route;
    if (validRoute(inputRoute)) navigate(inputRoute);

    const fallbackTimer = window.setTimeout(() => {
      if (!receivedEmbeddedDashboard && routeRef.current === "/overview") void loadDashboard("month");
    }, 2500);
    return () => {
      window.clearTimeout(fallbackTimer);
      unsubscribeResults();
      unsubscribeHost();
    };
  }, [loadDashboard, navigate]);

  useEffect(() => {
    const wasFullscreen = previousDisplayMode.current === "fullscreen";
    const returnedInline = wasFullscreen && hostContext.displayMode === "inline";
    previousDisplayMode.current = hostContext.displayMode;

    if (returnedInline) {
      setSelectedExpense(undefined);
    }
    const active = expenseRoute(route);
    if (
      returnedInline &&
      active.transactionId &&
      !active.review &&
      !inlineExpenseSummary
    ) {
      setPriceHistory(undefined);
      navigate("/transactions");
    }
  }, [hostContext.displayMode, inlineExpenseSummary, navigate, route]);

  useEffect(() => {
    persistWidgetState({ route, period, activityFilter });
    const active = expenseRoute(route);
    if (route === "/expenses/new") {
      setExpense(undefined);
      expenseRef.current = undefined;
      setExpenseStatus("idle");
      setExpenseError(undefined);
      setInlineExpenseSummary(false);
      setForm(emptyDraft());
      setIssues([]);
      setApproved(false);
      setSuccessVisible(false);
      setNotice("Manual expense. To scan a receipt, attach it directly in this chat.");
      return;
    }
    if (active.transactionId && expenseRef.current?.transaction.id !== active.transactionId) {
      setExpense(undefined);
      expenseRef.current = undefined;
      void refreshExpense(active.transactionId).catch(() => undefined);
      return;
    }
    if (route === "/overview" && !dashboard) void loadDashboard(period);
    if (route === "/transactions" && !transactions) void loadTransactions(false);
    if ((route === "/trends" || route === "/prices" || route === "/nutrition") && !dashboard) {
      void loadDashboard(period);
    }
  }, [
    activityFilter,
    dashboard,
    loadDashboard,
    loadTransactions,
    period,
    refreshExpense,
    route,
    transactions,
  ]);

  // Fires once dashboard first resolves, regardless of route, so the inline-launcher
  // card has real preview data on first render - not just when the user navigates to
  // the Nutrition tab directly. Currency comes from dashboard.default_currency, which
  // isn't known until the dashboard load itself resolves.
  useEffect(() => {
    if (dashboard && nutritionStatus === "idle") {
      void loadNutritionSummary(dashboard.default_currency, period);
    }
  }, [dashboard, loadNutritionSummary, nutritionStatus, period]);

  useEffect(() => {
    const refreshVisibleState = () => {
      if (document.visibilityState === "hidden") return;
      const active = expenseRoute(routeRef.current);
      if (active.transactionId) {
        void refreshExpense(active.transactionId).catch(() => undefined);
      } else {
        void loadDashboard(period);
        if (routeRef.current === "/transactions") void loadTransactions(false);
      }
    };
    window.addEventListener("focus", refreshVisibleState);
    document.addEventListener("visibilitychange", refreshVisibleState);
    return () => {
      window.removeEventListener("focus", refreshVisibleState);
      document.removeEventListener("visibilitychange", refreshVisibleState);
    };
  }, [loadDashboard, loadTransactions, period, refreshExpense]);

  useEffect(() => {
    const active = expenseRoute(route);
    if (!active.review || !active.transactionId) return;
    let checks = 0;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden" || checks >= 20) return;
      checks += 1;
      void refreshExpense(active.transactionId as string)
        .then((next) => {
          if (next?.transaction.status === "confirmed") {
            setSuccessVisible(true);
            setNotice("This expense was confirmed and is included in your insights.");
            invalidateSummaries();
            window.clearInterval(timer);
          }
        })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [refreshExpense, route]);

  async function saveDraftFor(nextForm: DraftForm): Promise<ExpenseSnapshot | undefined> {
    if (!nextForm.total.trim()) {
      setError("Total is required.");
      return undefined;
    }
    const result = await run("Saving draft", () =>
      callTool("save_expense_draft", {
        payload: savePayload(nextForm, crypto.randomUUID()),
      }),
    );
    if (!result) return undefined;
    const next = expenseFromResult(result);
    if (next) {
      applyExpense(next);
      invalidateSummaries();
      navigate(`/expenses/${next.transaction.id}/review`);
      setNotice("Draft saved privately.");
    }
    return next;
  }

  async function saveDraft() {
    return saveDraftFor(form);
  }

  async function validateDraft() {
    const saved = await saveDraft();
    if (!saved) return;
    const result = await run("Validating expense", () =>
      callTool("validate_expense", { transaction_id: saved.transaction.id }),
    );
    if (!result) return;
    const validation = structured<{
      issues: Array<{ severity: string; code: string; message: string }>;
    }>(result);
    setIssues(validation.issues);
    await refreshExpense(saved.transaction.id);
    setNotice(
      validation.issues.some((candidate) => candidate.severity === "blocking")
        ? "Resolve the blocking issues before confirmation."
        : "Validated. Review once more, then confirm.",
    );
  }

  async function confirmDraft() {
    if (!expense?.transaction.id || !approved) return;
    const result = await run("Confirming expense", () =>
      callTool("confirm_expense", {
        transaction_id: expense.transaction.id,
        explicit_approval: true,
      }),
    );
    if (!result) return;
    const next = expenseFromResult(result);
    if (next) applyExpense(next);
    invalidateSummaries();
    setSuccessVisible(true);
    setNotice("Success. This expense is confirmed and included in your insights.");
  }

  async function correctConfirmed(reason: string): Promise<boolean> {
    if (!expense?.transaction.id || !form.revision || !approved) return false;
    const payload = savePayload(form, `correction:${crypto.randomUUID()}`);
    const result = await run("Applying correction", () =>
      callTool("correct_confirmed_expense", {
        payload: {
          transaction_id: expense.transaction.id,
          expected_revision: form.revision,
          draft: payload.draft,
          correction_reason: reason,
          explicit_approval: true,
          client_request_id: `correction:${crypto.randomUUID()}`,
        },
      }),
    );
    if (!result) return false;
    const next = expenseFromResult(result);
    if (next) applyExpense(next);
    invalidateSummaries();
    setSuccessVisible(true);
    setNotice("Correction saved and included in your insights.");
    return true;
  }

  async function openPriceHistory(
    identityKey: string,
    currency?: string,
    normalizedUnit?: string,
  ): Promise<ItemPriceHistory | undefined> {
    const result = await run("Loading price history", () =>
      callTool("get_item_price_history", {
        request: {
          identity_key: identityKey,
          currency,
          normalized_unit: normalizedUnit,
          limit: 36,
        },
      }),
    );
    if (!result) return undefined;
    const history = structured<ItemPriceHistory>(result);
    setPriceHistory(history);
    setSelectedExpense(undefined);
    navigate("/prices");
    return history;
  }

  async function deleteCurrent() {
    if (!expense) return;
    const result = await run("Deleting expense", () =>
      callTool("delete_expense", {
        transaction_id: expense.transaction.id,
        explicit_confirmation: true,
      }),
    );
    if (!result) return;
    const outcome = structured<{ ok: boolean; message: string }>(result);
    if (!outcome.ok) {
      setError(outcome.message);
      return;
    }
    setExpense(undefined);
    expenseRef.current = undefined;
    invalidateSummaries();
    navigate("/transactions");
    setNotice("Expense and its owned receipt files were permanently deleted.");
  }

  async function deleteFromActivity(transaction: ExpenseTransaction) {
    const result = await run(
      transaction.status === "draft" ? "Discarding draft" : "Deleting expense",
      () =>
        callTool("delete_expense", {
          transaction_id: transaction.id,
          explicit_confirmation: true,
        }),
    );
    if (!result) return;
    const outcome = structured<{ ok: boolean; message: string }>(result);
    if (!outcome.ok) {
      setError(outcome.message);
      return;
    }
    invalidateSummaries();
    await Promise.all([loadDashboard(period), loadTransactions(false, activityFilter)]);
  }

  async function downloadReceipt(fileId: string, target = expense) {
    const receiptId = target?.receipt?.receipt.id;
    if (!receiptId) return;
    const result = await run("Opening receipt", () =>
      callTool("get_receipt_download_url", {
        receipt_id: receiptId,
        file_id: fileId,
      }),
    );
    if (!result) return;
    const url = privateMeta<string>(result, "downloadUrl");
    if (!url) {
      setError("The private download URL was not available to the widget.");
      return;
    }
    await openPrivateUrl(url);
  }

  async function deleteReceiptFile(fileId: string) {
    const receiptId = expense?.receipt?.receipt.id;
    const transactionId = expense?.transaction.id;
    if (!receiptId || !transactionId) return;
    const result = await run("Deleting receipt", () =>
      callTool("delete_receipt_file", {
        receipt_id: receiptId,
        file_id: fileId,
        explicit_confirmation: true,
      }),
    );
    if (!result) return;
    const outcome = structured<{ ok: boolean; message: string }>(result);
    if (!outcome.ok) {
      setError(outcome.message);
      return;
    }
    await refreshExpense(transactionId);
    setNotice("Receipt file permanently deleted.");
  }

  async function launchManualEntry() {
    setError(undefined);
    setInlineExpenseSummary(false);
    navigate("/expenses/new");
    try {
      await requestFullscreen();
      setHostContext((current) => ({ ...current, displayMode: "fullscreen" }));
    } catch {
      // One-tap manual entry remains usable inline when promotion is unavailable.
    }
  }

  async function enterFullscreen(
    nextSection?: TrackerSection,
    trendView?: "months" | "calendar",
  ) {
    setInlineExpenseSummary(false);
    setPendingTrendView(trendView);
    await run("Opening fullscreen", async () => {
      await requestFullscreen();
      setHostContext((current) => ({ ...current, displayMode: "fullscreen" }));
      if (nextSection) navigate(routeForSection(nextSection));
      return true;
    });
  }

  async function openTransaction(transaction: ExpenseTransaction) {
    setError(undefined);
    const result = await run("Loading transaction", () =>
      callTool("get_expense", { transaction_id: transaction.id }),
    );
    if (!result) return;
    const next = expenseFromResult(result);
    if (next) setSelectedExpense(next);
  }

  async function deleteSelected() {
    if (!selectedExpense) return;
    const result = await run("Deleting expense", () =>
      callTool("delete_expense", {
        transaction_id: selectedExpense.transaction.id,
        explicit_confirmation: true,
      }),
    );
    if (!result) return;
    const outcome = structured<{ ok: boolean; message: string }>(result);
    if (!outcome.ok) {
      setError(outcome.message);
      return;
    }
    setSelectedExpense(undefined);
    invalidateSummaries();
    setNotice("Expense and its owned receipt files were permanently deleted.");
    await Promise.all([loadDashboard(period), loadTransactions(false, activityFilter)]);
  }

  function openReviewQueue() {
    setActivityFilter("draft");
    setTransactions(undefined);
    setTransactionStatus("idle");
    navigate("/transactions");
    void loadTransactions(false, "draft");
  }

  async function backToActivity() {
    invalidateSummaries();
    navigate("/transactions");
    await Promise.all([loadDashboard(period), loadTransactions(false, activityFilter)]);
  }

  const activeExpenseRoute = expenseRoute(route);
  const isEditor = route === "/expenses/new" || activeExpenseRoute.review;
  const isDetail = Boolean(activeExpenseRoute.transactionId) && !activeExpenseRoute.review;
  const isRoot =
    route === "/overview" ||
    route === "/transactions" ||
    route === "/trends" ||
    route === "/prices" ||
    route === "/nutrition";
  const activeExpenseMatches =
    Boolean(activeExpenseRoute.transactionId) &&
    expense?.transaction.id === activeExpenseRoute.transactionId;
  const transactionDetailOpen =
    Boolean(selectedExpense) || (isDetail && activeExpenseMatches && Boolean(expense));
  const inlineMode =
    !transactionDetailOpen &&
    hostContext.displayMode !== "fullscreen" &&
    (isRoot || (inlineExpenseSummary && Boolean(expense)));
  const mobileDetailPage =
    transactionDetailOpen &&
    (hostContext.platform === "mobile" ||
      /Android|iPhone|iPad|iPod|Mobile/i.test(
        hostContext.userAgent || window.navigator.userAgent,
      ) ||
      window.innerWidth <= 480);
  const displayName = dashboard?.display_name?.trim() || "there";

  if (inlineMode) {
    return (
      <div className="app-shell inline-shell">
        {error && (
          <div className="app-error" role="alert">
            <span>{error}</span>
            <button onClick={() => setError(undefined)} aria-label="Dismiss error">
              <Icon name="close" />
            </button>
          </div>
        )}
        <InlineLauncher
          dashboard={dashboard}
          dashboardStatus={dashboardStatus}
          displayName={displayName}
          expense={!isRoot ? expense : undefined}
          nutritionSummary={nutritionSummary}
          surface={!isRoot && expense ? "expense" : "overview"}
          busy={busy}
          notice={notice}
          onExpand={(section, trendView) => void enterFullscreen(section, trendView)}
          onAdd={() => void launchManualEntry()}
        />
        {busy && <div className="busy-pill"><span />{busy}</div>}
      </div>
    );
  }

  return (
    <div
      className={[
        "app-shell",
        transactionDetailOpen && "transaction-detail-open",
        mobileDetailPage && "transaction-detail-page-mode",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {isRoot && (
        <header className="app-header">
          <div className="brand-mark"><Icon name="receipt" size={21} /></div>
          <div className="welcome">
            <p>Welcome back, {displayName}</p>
            <h1>Here’s where your money went.</h1>
          </div>
          <div className="header-actions">
            {isDemoMode && <span className="preview-chip">Preview</span>}
            <button className="primary-button add-button" onClick={() => void launchManualEntry()}>
              <Icon name="add" size={17} /> Add expense
            </button>
          </div>
        </header>
      )}

      {error && (
        <div className="app-error" role="alert">
          <span>{error}</span>
          <button onClick={() => setError(undefined)} aria-label="Dismiss error">
            <Icon name="close" />
          </button>
        </div>
      )}

      {isRoot ? (
        dashboard ? (
          <Overview
            dashboard={dashboard}
            period={period}
            section={sectionForRoute(route)}
            initialTrendView={pendingTrendView}
            transactions={transactions}
            transactionStatus={transactionStatus}
            activityFilter={activityFilter}
            onSectionChange={(section) => navigate(routeForSection(section))}
            onPeriodChange={(nextPeriod) => {
              void loadDashboard(nextPeriod);
              if (nutritionStatus !== "idle") {
                void loadNutritionSummary(dashboard.default_currency, nextPeriod);
              }
            }}
            onRefresh={() => {
              void loadDashboard(period);
              if (nutritionStatus !== "idle") {
                void loadNutritionSummary(dashboard.default_currency, period);
              }
            }}
            onLoadTransactions={(loadMore) => void loadTransactions(loadMore)}
            onActivityFilterChange={(nextFilter) => {
              setActivityFilter(nextFilter);
              setTransactions(undefined);
              setTransactionStatus("idle");
              void loadTransactions(false, nextFilter);
            }}
            onAdd={() => void launchManualEntry()}
            onReview={openReviewQueue}
            onLoadCategoryBreakdown={loadCategoryBreakdown}
            onOpenTransaction={(transaction) => void openTransaction(transaction)}
            onDeleteTransaction={(transaction) => void deleteFromActivity(transaction)}
            onLoadDayTransactions={loadDayTransactions}
            onOpenPrice={(change: PriceChange) =>
              void openPriceHistory(change.identity_key, change.currency, change.normalized_unit)
            }
            onLoadPersonalBasket={loadPersonalBasket}
            onOpenBasketProduct={(product) =>
              void openPriceHistory(
                `basket:${product.identity_key}`,
                product.currency,
                product.normalized_unit,
              )
            }
            priceHistory={priceHistory}
            onClosePriceHistory={() => setPriceHistory(undefined)}
            onLoadMerchantBreakdown={loadMerchantBreakdown}
            onLoadMerchantTransactions={loadMerchantTransactions}
            nutritionSummary={nutritionSummary}
            nutritionStatus={nutritionStatus}
            nutritionItem={nutritionItem}
            onOpenNutritionItem={setNutritionItem}
            onCloseNutritionItem={() => setNutritionItem(undefined)}
          />
        ) : dashboardStatus === "error" ? (
          <DashboardUnavailable onRetry={() => void loadDashboard(period)} />
        ) : (
          <LoadingOverview />
        )
      ) : isEditor ? (
        <ExpenseEditor
          form={form}
          snapshot={expense}
          categories={categories}
          currencies={currencies}
          adjustmentTypes={adjustmentTypes}
          issues={issues}
          approved={approved}
          busy={busy}
          notice={notice}
          onFormChange={setForm}
          onApprovedChange={setApproved}
          successVisible={successVisible}
          onBack={() => void backToActivity()}
          onDone={() => void backToActivity()}
          onNew={() => void launchManualEntry()}
          onDownload={downloadReceipt}
          onDeleteFile={deleteReceiptFile}
          onSave={saveDraft}
          onValidate={validateDraft}
          onConfirm={confirmDraft}
          onCorrect={correctConfirmed}
          onDiscard={deleteCurrent}
        />
      ) : isDetail && activeExpenseMatches && expense ? (
        <TransactionDetail
          snapshot={expense}
          busy={busy}
          onClose={() => void backToActivity()}
          onEdit={() => navigate(`/expenses/${expense.transaction.id}/review`)}
          onDelete={deleteCurrent}
          onDownload={downloadReceipt}
          onPriceHistory={openPriceHistory}
        />
      ) : isDetail && expenseStatus === "error" ? (
        <ExpenseUnavailable
          message={expenseError || "The private transaction connection was interrupted."}
          onBack={() => void backToActivity()}
          onRetry={() => {
            if (activeExpenseRoute.transactionId) {
              void refreshExpense(activeExpenseRoute.transactionId).catch(() => undefined);
            }
          }}
        />
      ) : (
        <main className="overview loading-overview" aria-label="Loading expense">
          <div className="skeleton hero-skeleton" />
          <div className="skeleton list-skeleton" />
        </main>
      )}

      {selectedExpense && (
        <TransactionDetail
          snapshot={selectedExpense}
          busy={busy}
          onClose={() => setSelectedExpense(undefined)}
          onEdit={() => {
            applyExpense(selectedExpense);
            setSelectedExpense(undefined);
            navigate(`/expenses/${selectedExpense.transaction.id}/review`);
          }}
          onDelete={deleteSelected}
          onDownload={(fileId) => downloadReceipt(fileId, selectedExpense)}
          onPriceHistory={openPriceHistory}
        />
      )}

      {busy && <div className="busy-pill"><span />{busy}</div>}
    </div>
  );
}
