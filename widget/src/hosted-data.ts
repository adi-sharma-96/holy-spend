import type {
  AnalyticsQueryResponse,
  DashboardPeriod,
  ExpenseDashboard,
  ExpenseSnapshot,
  ItemPriceHistory,
  MerchantBreakdownResponse,
  NutritionSummary,
  PersonalBasketIndex,
  TransactionListResponse,
} from "./types";

export const TRACKER_PATH = "/tracker";
export type SpendingRow = {
  id: string;
  transaction_date: string;
  merchant: string | null;
  amount: string;
  currency: string;
  classification: "ordinary" | "exceptional" | "unreviewed";
  recurrence: string[];
};

type Query = Record<string, string | number | undefined>;

async function request(path: string, init?: RequestInit): Promise<Response> {
  return fetch(TRACKER_PATH + path, {
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
    referrerPolicy: "no-referrer",
    ...init,
  });
}

export async function exchangeTrackerLaunch(secret: string): Promise<boolean> {
  const response = await request("/session/exchange", {
    method: "POST",
    headers: { "Content-Type": "text/plain;charset=UTF-8" },
    body: secret,
  });
  return response.status === 204;
}

export async function logoutTracker(): Promise<void> {
  const response = await request("/session/logout", { method: "POST" });
  if (!response.ok) throw new Error("Sign-out failed. Try again.");
}

export function trackerData(onExpired: () => void) {
  async function read<T>(path: string, query: Query = {}, signal?: AbortSignal): Promise<T> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) params.set(key, String(value));
    }
    const suffix = params.size ? `?${params}` : "";
    const response = await request(`/read/${path}${suffix}`, { signal });
    if (response.status === 401) onExpired();
    if (!response.ok) throw new Error("The tracker could not load this data.");
    return response.json() as Promise<T>;
  }

  return {
    dashboard: (period: DashboardPeriod, signal?: AbortSignal) =>
      read<ExpenseDashboard>("dashboard", { period, recent_limit: 12, category_limit: 30, price_change_limit: 24 }, signal),
    nutrition: (period: DashboardPeriod, currency: string, protein_detail_offset: number, signal?: AbortSignal) =>
      read<NutritionSummary>("nutrition", { period, currency, protein_detail_offset }, signal),
    transactions: (filters: Query) => read<TransactionListResponse>("transactions", filters),
    expense: (id: string) => read<ExpenseSnapshot>(`transactions/${encodeURIComponent(id)}`),
    merchants: (period: DashboardPeriod, currency: string) =>
      read<MerchantBreakdownResponse>("merchants", { period, currency }),
    basket: (currency: string) => read<PersonalBasketIndex>("basket", { currency }),
    prices: (identity_key: string, currency: string, normalized_unit?: string) =>
      read<ItemPriceHistory>("prices", { identity_key, currency, normalized_unit }),
    categories: (period: DashboardPeriod, currency: string, parent: string, level: number) =>
      read<AnalyticsQueryResponse>("categories", { period, currency, parent, level }),
    spending: (period: DashboardPeriod, currency: string, interval: "current" | "previous", offset: number, signal: AbortSignal) =>
      read<SpendingRow[]>("spending", { period, currency, interval, offset }, signal),
  };
}

export type TrackerData = ReturnType<typeof trackerData>;
