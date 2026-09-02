import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { demoDashboard } from "./demo";
import type { ExpenseSnapshot, ToolResult } from "./types";

const mocks = vi.hoisted(() => ({
  callTool: vi.fn(),
  requestFullscreen: vi.fn().mockResolvedValue(undefined),
  persistWidgetState: vi.fn(),
  toolResultListener: undefined as ((result: ToolResult) => void) | undefined,
  hostContextListener: undefined as ((context: object) => void) | undefined,
  hostMode: "fullscreen" as "inline" | "fullscreen",
  hostPlatform: "desktop" as "desktop" | "mobile",
  hostLocale: "en-CA",
}));

vi.mock("./bridge", () => ({
  callTool: mocks.callTool,
  isDemoMode: false,
  openPrivateUrl: vi.fn(),
  persistWidgetState: mocks.persistWidgetState,
  privateMeta: vi.fn(),
  requestFullscreen: mocks.requestFullscreen,
  structured: <T,>(result: ToolResult): T => {
    const value = result.structuredContent || {};
    return ("result" in value ? value.result : value) as T;
  },
  subscribeToHostContext: (callback: (context: object) => void) => {
    mocks.hostContextListener = callback;
    callback({
      displayMode: mocks.hostMode,
      platform: mocks.hostPlatform,
      locale: mocks.hostLocale,
      safeAreaInsets: { top: 12, right: 4, bottom: 34, left: 4 },
    });
    return () => {
      mocks.hostContextListener = undefined;
    };
  },
  subscribeToToolResults: (callback: (result: ToolResult) => void) => {
    mocks.toolResultListener = callback;
    return () => {
      mocks.toolResultListener = undefined;
    };
  },
}));

import { App } from "./App";

const receiptExpense: ExpenseSnapshot = {
  transaction: {
    id: "11111111-1111-4111-8111-111111111111",
    status: "draft",
    source_type: "receipt",
    transaction_type: "expense",
    transaction_date: "2026-07-20",
    merchant_name_raw: "FreshCo",
    merchant_name_normalized: "FreshCo",
    currency: "CAD",
    subtotal_amount: "56.93",
    tax_amount: "0.46",
    discount_amount: null,
    total_amount: "57.39",
    reconciliation_delta_amount: "0",
    updated_at: "2026-07-28T18:00:00Z",
    items: Array.from({ length: 9 }, (_, index) => ({
      raw_name: `Item ${index + 1}`,
      normalized_name: `item-${index + 1}`,
      category_slug: "uncategorized",
      theme_slugs: [],
      line_total_amount: index === 8 ? "7.93" : String(index + 1),
    })),
    adjustments: [
      {
        type: "discount",
        amount: "2.60",
        raw_label: "TOTAL SAVINGS",
        affects_total: false,
        metadata: {},
      },
    ],
    validation_issues: [],
  },
  receipt: {
    receipt: {
      id: "22222222-2222-4222-8222-222222222222",
      transaction_id: "11111111-1111-4111-8111-111111111111",
    },
    files: [],
  },
};

function result(value: object): ToolResult {
  return { structuredContent: value as Record<string, unknown> };
}

function defaultTool(toolName: string): Promise<ToolResult> {
  if (toolName === "get_expense_taxonomy") {
    return Promise.resolve(
      result({
        categories: [
          {
            id: "33333333-3333-4333-8333-333333333333",
            slug: "uncategorized",
            name: "Uncategorized",
            is_assignable: true,
          },
        ],
        adjustment_types: ["discount", "tax", "fee", "tip", "deposit", "rounding"],
        supported_currencies: ["CAD", "USD"],
      }),
    );
  }
  if (toolName === "get_expense_dashboard") return Promise.resolve(result(demoDashboard));
  if (toolName === "get_expense") return Promise.resolve(result(receiptExpense));
  if (toolName === "list_expenses") {
    return Promise.resolve(
      result({ transactions: [receiptExpense.transaction], total: 1, limit: 10, offset: 0 }),
    );
  }
  return Promise.resolve(result({}));
}

describe("single-resource app lifecycle", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/overview");
    window.openai = undefined;
    mocks.callTool.mockReset();
    mocks.callTool.mockImplementation(defaultTool);
    mocks.requestFullscreen.mockReset();
    mocks.requestFullscreen.mockResolvedValue(undefined);
    mocks.persistWidgetState.mockClear();
    mocks.toolResultListener = undefined;
    mocks.hostContextListener = undefined;
    mocks.hostMode = "fullscreen";
    mocks.hostPlatform = "desktop";
    mocks.hostLocale = "en-CA";
  });

  it("opens manual entry with one tap and exposes no receipt picker", async () => {
    render(<App />);
    await screen.findByRole("button", { name: /add expense/i });
    fireEvent.click(screen.getByRole("button", { name: /add expense/i }));

    await screen.findByText("New expense");
    expect(screen.getByText(/attach an image or pdf directly in this chat/i)).toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
    expect(mocks.requestFullscreen).toHaveBeenCalledOnce();
    expect(window.location.pathname).toBe("/overview");
    await waitFor(() =>
      expect(mocks.persistWidgetState).toHaveBeenLastCalledWith(
        expect.objectContaining({ route: "/expenses/new" }),
      ),
    );
  });

  it("keeps manual entry usable on a mobile host when fullscreen promotion fails", async () => {
    mocks.hostMode = "inline";
    mocks.requestFullscreen.mockRejectedValueOnce(new Error("Host rejected display mode"));
    render(<App />);
    await screen.findByRole("button", { name: /add expense/i });
    fireEvent.click(screen.getByRole("button", { name: /add expense/i }));

    await screen.findByText("New expense");
    expect(screen.queryByText(/host rejected|unexpected error/i)).not.toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });

  it("expands straight into the Trends calendar view from the inline calendar card", async () => {
    mocks.hostMode = "inline";
    render(<App />);

    const calendarCard = await screen.findByRole("button", { name: /calendar/i });
    fireEvent.click(calendarCard);

    await waitFor(() => expect(mocks.requestFullscreen).toHaveBeenCalledOnce());
    expect(await screen.findByRole("heading", { name: /july 2026/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /last six months/i })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /trends/i })).toHaveClass("active");
  });

  it("opens a transaction in place without changing route or display mode", async () => {
    render(<App />);
    await screen.findByRole("tab", { name: /activity/i });
    fireEvent.click(screen.getByRole("tab", { name: /activity/i }));

    const transactionButton = await screen.findByRole("button", { name: /FreshCo/i });
    fireEvent.click(transactionButton);

    await waitFor(() =>
      expect(mocks.callTool).toHaveBeenCalledWith("get_expense", {
        transaction_id: receiptExpense.transaction.id,
      }),
    );
    const detail = await screen.findByRole("complementary", { name: /transaction details/i });
    expect(detail).toBeInTheDocument();
    expect(detail.closest(".app-shell")).toHaveClass("transaction-detail-open");
    expect(detail.closest(".app-shell")).not.toHaveClass("transaction-detail-page-mode");
    expect(screen.getByRole("heading", { name: "FreshCo" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /line items/i })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/overview");
    expect(mocks.persistWidgetState).toHaveBeenLastCalledWith(
      expect.objectContaining({ route: "/transactions" }),
    );
    expect(mocks.requestFullscreen).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /close transaction details/i }));
    expect(screen.queryByRole("complementary", { name: /transaction details/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /FreshCo/i })).toBeInTheDocument();
    expect(screen.getByRole("main").closest(".app-shell")).not.toHaveClass("transaction-detail-open");
    expect(mocks.persistWidgetState).toHaveBeenLastCalledWith(
      expect.objectContaining({ route: "/transactions" }),
    );
  });

  it("returns to a compact activity launcher when the host closes fullscreen", async () => {
    render(<App />);
    await screen.findByRole("tab", { name: /activity/i });
    fireEvent.click(screen.getByRole("tab", { name: /activity/i }));
    fireEvent.click(await screen.findByRole("button", { name: /FreshCo/i }));
    expect(await screen.findByRole("complementary", { name: /transaction details/i })).toBeInTheDocument();

    act(() => {
      mocks.hostContextListener?.({
        displayMode: "inline",
        locale: "en-CA",
        safeAreaInsets: { top: 12, right: 4, bottom: 34, left: 4 },
      });
    });

    expect(await screen.findByRole("main", { name: "Holy Spend" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: /transaction details/i })).not.toBeInTheDocument();
    expect(window.location.pathname).toBe("/overview");
    await waitFor(() =>
      expect(mocks.persistWidgetState).toHaveBeenLastCalledWith(
        expect.objectContaining({ route: "/transactions" }),
      ),
    );
  });

  it("uses a document page instead of a fixed drawer layer on mobile hosts", async () => {
    mocks.hostPlatform = "mobile";
    render(<App />);
    await screen.findByRole("tab", { name: /activity/i });
    fireEvent.click(screen.getByRole("tab", { name: /activity/i }));
    fireEvent.click(await screen.findByRole("button", { name: /FreshCo/i }));

    const detail = await screen.findByRole("complementary", { name: /transaction details/i });
    expect(detail.closest(".app-shell")).toHaveClass("transaction-detail-page-mode");
    expect(screen.getByRole("heading", { name: "FreshCo" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /close transaction details/i }));
    expect(screen.queryByRole("complementary", { name: /transaction details/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /FreshCo/i })).toBeInTheDocument();
  });

  it("renders a directly opened transaction when a mobile host starts inline", async () => {
    mocks.hostMode = "inline";
    mocks.hostPlatform = "mobile";
    mocks.hostLocale = "en_CA";
    const mobileExpense: ExpenseSnapshot = {
      ...receiptExpense,
      transaction: {
        ...receiptExpense.transaction,
        items: receiptExpense.transaction.items?.map((item, index) =>
          index === 0
            ? {
                ...item,
                taxonomy_path: {} as NonNullable<typeof item.taxonomy_path>,
              }
            : item,
        ),
      },
    };
    mocks.callTool.mockImplementation((toolName: string) =>
      toolName === "get_expense"
        ? Promise.resolve(result(mobileExpense))
        : defaultTool(toolName),
    );
    window.history.replaceState(
      {},
      "",
      `/expenses/${receiptExpense.transaction.id}`,
    );

    render(<App />);

    const detail = await screen.findByRole("complementary", {
      name: /transaction details/i,
    });
    expect(detail.closest(".app-shell")).toHaveClass("transaction-detail-page-mode");
    expect(screen.getByRole("heading", { name: "FreshCo" })).toBeInTheDocument();
    expect(mocks.callTool).toHaveBeenCalledWith("get_expense", {
      transaction_id: receiptExpense.transaction.id,
    });

    fireEvent.click(screen.getByRole("button", { name: /close transaction details/i }));
    await screen.findByRole("main", { name: "Holy Spend" });
    expect(screen.queryByRole("complementary", { name: /transaction details/i })).not.toBeInTheDocument();
  });

  it("renders a chat receipt summary then reviews it in the same mounted app", async () => {
    mocks.hostMode = "inline";
    render(<App />);
    await waitFor(() => expect(mocks.toolResultListener).toBeTypeOf("function"));

    act(() => {
      mocks.toolResultListener?.(
        result({
          route: `/expenses/${receiptExpense.transaction.id}/review`,
          expense: receiptExpense,
          validation: { issues: [], confirmation_eligible: true },
          stateVersion: receiptExpense.transaction.updated_at,
          data: { message: "Receipt draft ready for review." },
        }),
      );
    });

    expect(await screen.findByText("FreshCo")).toBeInTheDocument();
    expect(screen.getByText(/9 items · 0 warnings/i)).toBeInTheDocument();
    expect(screen.getByText("$57.39")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    expect(await screen.findByText("Review expense")).toBeInTheDocument();
    expect(screen.getAllByDisplayValue(/Item \d/)).toHaveLength(9);
    expect(mocks.requestFullscreen).toHaveBeenCalledOnce();
    expect(window.location.pathname).toBe("/overview");
    await waitFor(() =>
      expect(mocks.persistWidgetState).toHaveBeenLastCalledWith(
        expect.objectContaining({
          route: `/expenses/${receiptExpense.transaction.id}/review`,
        }),
      ),
    );
  });

  it("refetches authoritative state on focus and persists navigation preferences only", async () => {
    render(<App />);
    await waitFor(() => expect(mocks.toolResultListener).toBeTypeOf("function"));
    act(() => {
      mocks.toolResultListener?.(
        result({
          route: `/expenses/${receiptExpense.transaction.id}/review`,
          expense: receiptExpense,
          stateVersion: receiptExpense.transaction.updated_at,
        }),
      );
    });
    await screen.findByText("Review expense");
    mocks.callTool.mockClear();
    const confirmedExpense: ExpenseSnapshot = {
      ...receiptExpense,
      transaction: {
        ...receiptExpense.transaction,
        status: "confirmed",
        updated_at: "2026-07-28T18:01:00Z",
      },
    };
    mocks.callTool.mockImplementation((toolName: string) =>
      toolName === "get_expense"
        ? Promise.resolve(result(confirmedExpense))
        : defaultTool(toolName),
    );

    fireEvent.focus(window);
    await waitFor(() =>
      expect(mocks.callTool).toHaveBeenCalledWith("get_expense", {
        transaction_id: receiptExpense.transaction.id,
      }),
    );
    expect(await screen.findByText("Expense confirmed")).toBeInTheDocument();
    expect(mocks.persistWidgetState).toHaveBeenLastCalledWith(
      expect.objectContaining({
        route: `/expenses/${receiptExpense.transaction.id}/review`,
        period: "month",
        activityFilter: "all",
      }),
    );
    const persisted = mocks.persistWidgetState.mock.calls.at(-1)?.[0];
    expect(persisted).not.toHaveProperty("expense");
    expect(persisted).not.toHaveProperty("status");
    expect(persisted).not.toHaveProperty("imageIds");
  });
});
