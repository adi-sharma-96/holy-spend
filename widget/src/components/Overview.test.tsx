import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { demoDashboard } from "../demo";
import type { ExpenseTransaction, NutritionSummary, TrackerSection } from "../types";
import { Overview } from "./Overview";

const nutritionSummaryFixture: NutritionSummary = {
  window: demoDashboard.window,
  currency: "CAD",
  overall_grade: "b",
  matched_item_count: 1,
  total_item_count: 2,
  coverage_percent: "50.0",
  confidence: "low",
  grade_distribution: [
    { grade: "b", spend_amount: "6.00", share_percent: "50.0" },
    { grade: "unknown", spend_amount: "6.00", share_percent: "50.0" },
  ],
  signals: [],
  groups: [
    {
      category_slug: "food_dining.groceries.dairy_eggs",
      category_name: "Dairy & Eggs",
      items: [
        {
          transaction_item_id: "d1111111-1111-4111-8111-111111111111",
          identity_key: "milk::farm-boy",
          display_name: "Fresh Milk 2%",
          brand: "Farm Boy",
          status: "matched",
          purchase_count: 1,
          nutriscore_grade: "b",
          nova_group: 1,
          source: "Open Food Facts",
          source_ref: "https://world.openfoodfacts.org/product/example",
          spend_amount: "6.00",
          energy_kcal_100g: 61,
        },
      ],
    },
  ],
};

describe("Overview", () => {
  it("mounts one focused fullscreen screen at a time", () => {
    function Harness() {
      const [section, setSection] = useState<TrackerSection>("overview");
      return (
        <Overview
          dashboard={demoDashboard}
          period="month"
          section={section}
          transactions={{
            transactions: demoDashboard.recent_transactions,
            total: demoDashboard.recent_transactions.length,
            limit: 10,
            offset: 0,
          }}
          transactionStatus="ready"
          onSectionChange={setSection}
          onPeriodChange={vi.fn()}
          onRefresh={vi.fn()}
          onLoadTransactions={vi.fn()}
          onReview={vi.fn()}
          onLoadCategoryBreakdown={vi.fn().mockResolvedValue([])}
          onAdd={vi.fn()}
          onOpenTransaction={vi.fn()}
          onOpenPrice={vi.fn()}
        />
      );
    }

    render(
      <Harness />,
    );

    expect(screen.getByRole("heading", { name: /where it went/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /last six months/i })).not.toBeInTheDocument();
    expect(screen.getByText("Cinema")).toBeInTheDocument();
    const rowIcons = document.querySelectorAll(".category-row-symbol");
    const groceriesIcon = rowIcons[0]?.querySelector("svg");
    const diningIcon = rowIcons[1]?.querySelector("svg");
    expect(groceriesIcon?.innerHTML).not.toBe(diningIcon?.innerHTML);

    fireEvent.click(screen.getByRole("tab", { name: /activity/i }));
    expect(screen.getByRole("heading", { name: "Activity" })).toBeInTheDocument();
    expect(screen.getByText("Farm Boy")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /where it went/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /trends/i }));
    expect(screen.getByRole("heading", { name: /last six months/i })).toBeInTheDocument();
    expect(screen.getByText("Feb")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /price watch/i }));
    expect(screen.getByRole("heading", { name: /tracked prices/i })).toBeInTheDocument();
    expect(screen.getByText("Fruit")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Fruit/i }));
    expect(screen.getByText("Apples")).toBeInTheDocument();
    expect(screen.getByLabelText("Price Watch insights")).toHaveTextContent(
      "Apples was 15.4% cheaper at No Frills",
    );
    expect(screen.getByLabelText("Price Watch insights")).toHaveTextContent(
      "when you bought 2.1 lb",
    );
    const sparklines = document.querySelectorAll(".price-spark");
    expect(sparklines.length).toBeGreaterThan(0);
    expect(sparklines[0]!.querySelector("svg polyline")).not.toBeNull();
    expect(sparklines[0]!.querySelector("polyline.spark-dot")).not.toBeNull();
  });

  it("keeps Price Watch's currency independent of the Overview spend-currency toggle", () => {
    // Regression test: switching Overview's own currency (spend totals, categories,
    // trends) used to also drive Price Watch/My Inflation off the same state, so
    // picking USD there went blank even though every tracked price in the demo data
    // is CAD - Price Watch has no USD repeat purchases, which is a different fact
    // than "the user is currently looking at USD elsewhere on the screen."
    function Harness() {
      const [section, setSection] = useState<TrackerSection>("overview");
      return (
        <Overview
          dashboard={demoDashboard}
          period="month"
          section={section}
          transactionStatus="idle"
          onSectionChange={setSection}
          onPeriodChange={vi.fn()}
          onRefresh={vi.fn()}
          onLoadTransactions={vi.fn()}
          onReview={vi.fn()}
          onLoadCategoryBreakdown={vi.fn().mockResolvedValue([])}
          onAdd={vi.fn()}
          onOpenTransaction={vi.fn()}
          onOpenPrice={vi.fn()}
        />
      );
    }

    render(<Harness />);

    fireEvent.click(within(screen.getByLabelText("Currency")).getByRole("button", { name: "USD" }));

    fireEvent.click(screen.getByRole("tab", { name: /price watch/i }));
    // Price Watch keeps its own default (CAD, where the demo data actually lives)
    // rather than inheriting the USD just picked on Overview.
    expect(screen.getByText("Fruit")).toBeInTheDocument();
    expect(screen.queryByText(/no trackable prices/i)).not.toBeInTheDocument();

    fireEvent.click(
      within(screen.getByLabelText("Price Watch currency")).getByRole("button", { name: "USD" }),
    );
    expect(screen.getByText(/no trackable prices in usd yet/i)).toBeInTheDocument();
  });

  it("renders a Nutrition tab that shows the basket grade, category groups, and a working period toolbar", () => {
    const onPeriodChange = vi.fn();
    function Harness() {
      const [section, setSection] = useState<TrackerSection>("overview");
      const [nutritionItem, setNutritionItem] = useState(
        undefined as (typeof nutritionSummaryFixture.groups)[number]["items"][number] | undefined,
      );
      return (
        <Overview
          dashboard={demoDashboard}
          nutritionItem={nutritionItem}
          nutritionSummary={nutritionSummaryFixture}
          nutritionStatus="ready"
          onCloseNutritionItem={() => setNutritionItem(undefined)}
          onOpenNutritionItem={setNutritionItem}
          period="month"
          section={section}
          transactionStatus="idle"
          onSectionChange={setSection}
          onPeriodChange={onPeriodChange}
          onRefresh={vi.fn()}
          onLoadTransactions={vi.fn()}
          onReview={vi.fn()}
          onLoadCategoryBreakdown={vi.fn().mockResolvedValue([])}
          onAdd={vi.fn()}
          onOpenTransaction={vi.fn()}
          onOpenPrice={vi.fn()}
        />
      );
    }

    render(<Harness />);

    fireEvent.click(screen.getByRole("tab", { name: /nutrition/i }));
    expect(screen.getByRole("heading", { name: "Nutrition" })).toBeInTheDocument();
    expect(screen.getByText(/your spend-weighted basket grade: b/i)).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 grocery items matched/i)).toBeInTheDocument();

    expect(screen.getByLabelText("Dashboard period")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^year$/i }));
    expect(onPeriodChange).toHaveBeenCalledWith("year");

    fireEvent.click(screen.getByRole("button", { name: /dairy & eggs/i }));
    const tile = screen.getByRole("button", { name: /fresh milk 2%/i });
    expect(tile).toBeInTheDocument();

    fireEvent.click(tile);
    expect(screen.getByText("Fresh Milk 2%")).toBeInTheDocument();
    expect(screen.getByText("61")).toBeInTheDocument();
  });

  it("loads transaction history only when its screen is selected", () => {
    const onLoadTransactions = vi.fn();
    render(
      <Overview
        dashboard={demoDashboard}
        period="month"
        section="transactions"
        transactionStatus="idle"
        onSectionChange={vi.fn()}
        onPeriodChange={vi.fn()}
        onRefresh={vi.fn()}
        onLoadTransactions={onLoadTransactions}
        onReview={vi.fn()}
        onLoadCategoryBreakdown={vi.fn().mockResolvedValue([])}
        onAdd={vi.fn()}
        onOpenTransaction={vi.fn()}
        onOpenPrice={vi.fn()}
      />,
    );

    expect(onLoadTransactions).toHaveBeenCalledOnce();
  });

  it("renders lightweight server summaries that do not contain item arrays", () => {
    const summary = {
      ...demoDashboard.recent_transactions[0]!,
      items: undefined,
      item_count: 5,
    };
    render(
      <Overview
        dashboard={{ ...demoDashboard, recent_transactions: [summary] }}
        period="month"
        section="transactions"
        transactions={{ transactions: [summary], total: 1, limit: 10, offset: 0 }}
        transactionStatus="ready"
        onSectionChange={vi.fn()}
        onPeriodChange={vi.fn()}
        onRefresh={vi.fn()}
        onLoadTransactions={vi.fn()}
        onReview={vi.fn()}
        onLoadCategoryBreakdown={vi.fn().mockResolvedValue([])}
        onAdd={vi.fn()}
        onOpenTransaction={vi.fn()}
        onOpenPrice={vi.fn()}
      />,
    );

    expect(screen.getByText("Farm Boy")).toBeInTheDocument();
    expect(screen.getByText(/5 items/i)).toBeInTheDocument();
  });

  it("drills from level-two spending groups into the next taxonomy level", async () => {
    const onLoadCategoryBreakdown = vi.fn().mockResolvedValue([
      {
        category_slug: "food_dining.groceries.produce",
        category_name: "Produce",
        taxonomy_level: 3,
        taxonomy_level_name: "Category",
        has_children: true,
        currency: "CAD",
        current_amount: "120",
        previous_amount: "0",
        delta_percent: null,
        share_percent: "100",
      },
    ]);
    render(
      <Overview
        dashboard={demoDashboard}
        period="month"
        section="overview"
        transactionStatus="idle"
        onSectionChange={vi.fn()}
        onPeriodChange={vi.fn()}
        onRefresh={vi.fn()}
        onLoadTransactions={vi.fn()}
        onReview={vi.fn()}
        onLoadCategoryBreakdown={onLoadCategoryBreakdown}
        onAdd={vi.fn()}
        onOpenTransaction={vi.fn()}
        onOpenPrice={vi.fn()}
      />,
    );

    fireEvent.click(screen.getAllByRole("button", { name: /Groceries/i })[0]!);

    expect(await screen.findByText("Produce")).toBeInTheDocument();
    expect(screen.getByText("Category breakdown")).toBeInTheDocument();
    expect(onLoadCategoryBreakdown).toHaveBeenCalledWith(
      expect.objectContaining({ category_slug: "food_dining.groceries", taxonomy_level: 2 }),
      "CAD",
      demoDashboard.window,
    );
  });

  it("switches Trends to a calendar view and drills into a day's transactions", async () => {
    const dayTransaction: ExpenseTransaction = {
      ...demoDashboard.recent_transactions[0]!,
      id: "99999999-9999-4999-8999-999999999999",
      merchant_name_normalized: "Corner Store",
      merchant_name_raw: "Corner Store",
      total_amount: "35.00",
      currency: "CAD",
      transaction_date: "2026-07-01",
      item_count: 2,
    };
    const onLoadDayTransactions = vi.fn().mockResolvedValue([dayTransaction]);
    const onOpenTransaction = vi.fn();
    render(
      <Overview
        dashboard={demoDashboard}
        period="month"
        section="trends"
        transactionStatus="idle"
        onSectionChange={vi.fn()}
        onPeriodChange={vi.fn()}
        onRefresh={vi.fn()}
        onLoadTransactions={vi.fn()}
        onReview={vi.fn()}
        onLoadCategoryBreakdown={vi.fn().mockResolvedValue([])}
        onAdd={vi.fn()}
        onOpenTransaction={onOpenTransaction}
        onLoadDayTransactions={onLoadDayTransactions}
        onOpenPrice={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: /last six months/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Calendar" }));
    expect(screen.queryByRole("heading", { name: /last six months/i })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /july 2026/i })).toBeInTheDocument();

    const dayButton = screen.getByRole("button", {
      name: /jul 1:.*2 expenses/i,
    });
    fireEvent.click(dayButton);

    await waitFor(() =>
      expect(onLoadDayTransactions).toHaveBeenCalledWith("2026-07-01", "CAD"),
    );
    const detail = await screen.findByText("Corner Store");
    expect(within(detail.closest(".transaction-row")!).getByText("$35.00")).toBeInTheDocument();

    fireEvent.click(detail);
    expect(onOpenTransaction).toHaveBeenCalledWith(dayTransaction);
  });

  it("switches Price Watch to My Inflation and drills into a basket product", async () => {
    const basketIndex = {
      currency: "CAD",
      window_days: 90,
      overall_delta_percent: "3.8",
      product_count: 2,
      total_tracked_spend: "377.00",
      covered_spend: "282.00",
      coverage_percent: "74.8",
      confidence: "low" as const,
      products: [
        {
          identity_key: "greek-yogurt@kg@store:costco",
          label: "Greek Yogurt",
          merchant_name: "Costco",
          currency: "CAD",
          normalized_unit: "kg",
          baseline_price: "8.00",
          baseline_date: "2026-05-05",
          current_price: "7.00",
          current_date: "2026-07-15",
          delta_percent: "-12.5",
          spend_amount: "150.00",
          purchase_count: 2,
        },
        {
          identity_key: "honeycrisp-apples@kg@store:no-frills",
          label: "Honeycrisp Apples",
          merchant_name: "No Frills",
          currency: "CAD",
          normalized_unit: "kg",
          baseline_price: "5.00",
          baseline_date: "2026-05-10",
          current_price: "6.00",
          current_date: "2026-07-20",
          delta_percent: "20.0",
          spend_amount: "132.00",
          purchase_count: 2,
        },
      ],
    };
    const onLoadPersonalBasket = vi.fn().mockResolvedValue(basketIndex);
    const onOpenBasketProduct = vi.fn();
    render(
      <Overview
        dashboard={demoDashboard}
        period="month"
        section="prices"
        transactionStatus="idle"
        onSectionChange={vi.fn()}
        onPeriodChange={vi.fn()}
        onRefresh={vi.fn()}
        onLoadTransactions={vi.fn()}
        onReview={vi.fn()}
        onLoadCategoryBreakdown={vi.fn().mockResolvedValue([])}
        onAdd={vi.fn()}
        onOpenTransaction={vi.fn()}
        onOpenPrice={vi.fn()}
        onLoadPersonalBasket={onLoadPersonalBasket}
        onOpenBasketProduct={onOpenBasketProduct}
      />,
    );

    expect(screen.getByRole("heading", { name: /tracked prices/i })).toBeInTheDocument();
    expect(screen.getByText("Fruit")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Fruit/i }));
    expect(screen.getByText("Apples")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "My Inflation" }));

    await waitFor(() => expect(onLoadPersonalBasket).toHaveBeenCalledWith("CAD"));
    expect(screen.queryByText("Apples")).not.toBeInTheDocument();
    expect(await screen.findByText("+3.8%")).toBeInTheDocument();
    expect(document.querySelector(".basket-note")?.textContent).toContain(
      "2 exact products",
    );
    expect(document.querySelector(".basket-note")?.textContent).toContain(
      "74.8% of tracked spend",
    );
    expect(screen.getByText("Low confidence")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /see the 2 products/i }));
    const yogurtRow = screen.getByRole("button", { name: /greek yogurt/i });
    expect(yogurtRow.textContent).toContain("at Costco");
    expect(yogurtRow.textContent).toContain("53.2%");

    fireEvent.click(yogurtRow);
    expect(onOpenBasketProduct).toHaveBeenCalledWith(basketIndex.products[0]);

    fireEvent.click(screen.getByRole("button", { name: "Deals" }));
    expect(screen.getByText("Fruit")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Fruit/i }));
    expect(screen.getByText("Apples")).toBeInTheDocument();
  });

  it("hides zero-percent share badges and uses New/0%/arrow delta wording", () => {
    const categories = [
      {
        category_slug: "food_dining.groceries",
        category_name: "Groceries",
        taxonomy_level: 2,
        taxonomy_level_name: "Group",
        has_children: true,
        currency: "CAD",
        current_amount: "120.00",
        previous_amount: "100.00",
        delta_percent: "20.0",
        share_percent: "82.0",
      },
      {
        category_slug: "entertainment_leisure.cinema",
        category_name: "Cinema",
        taxonomy_level: 2,
        taxonomy_level_name: "Group",
        has_children: false,
        currency: "CAD",
        current_amount: "12.00",
        previous_amount: "0",
        delta_percent: null,
        share_percent: "8.2",
      },
      {
        category_slug: "transportation.personal_vehicle",
        category_name: "Personal Vehicle",
        taxonomy_level: 2,
        taxonomy_level_name: "Group",
        has_children: false,
        currency: "CAD",
        current_amount: "10.00",
        previous_amount: "10.00",
        delta_percent: "0",
        share_percent: "6.8",
      },
      {
        category_slug: "food_dining.eating_out",
        category_name: "Eating out",
        taxonomy_level: 2,
        taxonomy_level_name: "Group",
        has_children: false,
        currency: "CAD",
        current_amount: "0.30",
        previous_amount: "0.10",
        delta_percent: "200.0",
        share_percent: "0.2",
      },
    ];
    render(
      <Overview
        dashboard={{ ...demoDashboard, categories }}
        period="month"
        section="overview"
        transactionStatus="idle"
        onSectionChange={vi.fn()}
        onPeriodChange={vi.fn()}
        onRefresh={vi.fn()}
        onLoadTransactions={vi.fn()}
        onReview={vi.fn()}
        onLoadCategoryBreakdown={vi.fn().mockResolvedValue([])}
        onAdd={vi.fn()}
        onOpenTransaction={vi.fn()}
        onOpenPrice={vi.fn()}
      />,
    );

    const groceriesRow = screen.getByRole("button", { name: /groceries/i });
    expect(groceriesRow.textContent).toContain("82%");
    expect(groceriesRow.textContent).toContain("20.0%");

    const cinemaRow = screen.getByRole("button", { name: /cinema/i });
    expect(cinemaRow.textContent).toContain("New");
    expect(cinemaRow.textContent).not.toContain("New this period");

    const vehicleRow = screen.getByRole("button", { name: /personal vehicle/i });
    expect(vehicleRow.textContent).toContain("0%");
    expect(vehicleRow.textContent).not.toContain("Stable");

    const eatingRow = screen.getByRole("button", { name: /eating out/i });
    const eatingMetaSpans = eatingRow.querySelectorAll(".category-meta-text > span");
    expect(eatingMetaSpans).toHaveLength(1);
    expect(eatingMetaSpans[0]?.textContent).toContain("200.0%");
  });

  it("hides the total delta chip when there is no confirmed spend this period", () => {
    render(
      <Overview
        dashboard={{
          ...demoDashboard,
          totals: [
            {
              currency: "CAD",
              current_amount: "0",
              previous_amount: "0",
              delta_amount: "0",
              delta_percent: null,
            },
          ],
          categories: [],
        }}
        period="month"
        section="overview"
        transactionStatus="idle"
        onSectionChange={vi.fn()}
        onPeriodChange={vi.fn()}
        onRefresh={vi.fn()}
        onLoadTransactions={vi.fn()}
        onReview={vi.fn()}
        onLoadCategoryBreakdown={vi.fn().mockResolvedValue([])}
        onAdd={vi.fn()}
        onOpenTransaction={vi.fn()}
        onOpenPrice={vi.fn()}
      />,
    );

    expect(screen.queryByText("New")).not.toBeInTheDocument();
    expect(screen.queryByText(/vs previous/i)).not.toBeInTheDocument();
    expect(
      screen.getByText("No expenses this period. Add one to see categories here."),
    ).toBeInTheDocument();
  });

  it("switches Where it went to Merchants and drills into a merchant's transactions", async () => {
    const merchantBreakdown = {
      window: demoDashboard.window,
      currency: "CAD",
      merchants: [
        {
          merchant_name: "Farm Boy",
          currency: "CAD",
          current_amount: "203.40",
          previous_amount: "181.02",
          delta_percent: "12.4",
          share_percent: "41.8",
          visit_count: 6,
          average_amount: "33.90",
        },
        {
          merchant_name: "Pizzeria Libretto",
          currency: "CAD",
          current_amount: "48.60",
          previous_amount: "0",
          delta_percent: null,
          share_percent: "10.0",
          visit_count: 1,
          average_amount: "48.60",
        },
        {
          merchant_name: "TTC",
          currency: "CAD",
          current_amount: "25.00",
          previous_amount: "25.00",
          delta_percent: "0",
          share_percent: "5.1",
          visit_count: 1,
          average_amount: "25.00",
        },
      ],
    };
    const merchantTransaction: ExpenseTransaction = {
      ...demoDashboard.recent_transactions[0]!,
      id: "88888888-8888-4888-8888-888888888888",
      merchant_name_normalized: "Farm Boy",
      merchant_name_raw: "Farm Boy",
      total_amount: "56.28",
      currency: "CAD",
      transaction_date: "2026-07-26",
      item_count: 5,
    };
    const onLoadMerchantBreakdown = vi.fn().mockResolvedValue(merchantBreakdown);
    const onLoadMerchantTransactions = vi.fn().mockResolvedValue([merchantTransaction]);
    const onOpenTransaction = vi.fn();

    render(
      <Overview
        dashboard={demoDashboard}
        period="month"
        section="overview"
        transactionStatus="idle"
        onSectionChange={vi.fn()}
        onPeriodChange={vi.fn()}
        onRefresh={vi.fn()}
        onLoadTransactions={vi.fn()}
        onReview={vi.fn()}
        onLoadCategoryBreakdown={vi.fn().mockResolvedValue([])}
        onAdd={vi.fn()}
        onOpenTransaction={onOpenTransaction}
        onOpenPrice={vi.fn()}
        onLoadMerchantBreakdown={onLoadMerchantBreakdown}
        onLoadMerchantTransactions={onLoadMerchantTransactions}
      />,
    );

    expect(screen.getByText("Cinema")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Merchants" }));

    await waitFor(() =>
      expect(onLoadMerchantBreakdown).toHaveBeenCalledWith("CAD", "month"),
    );
    expect(await screen.findByText("Farm Boy")).toBeInTheDocument();
    expect(screen.queryByText("Cinema")).not.toBeInTheDocument();

    const farmBoyRow = screen.getByRole("button", { name: /farm boy/i });
    expect(farmBoyRow.textContent).toContain("42%");
    expect(farmBoyRow.textContent).toContain("12.4%");

    const pizzaRow = screen.getByRole("button", { name: /pizzeria libretto/i });
    expect(pizzaRow.textContent).toContain("New");

    const ttcRow = screen.getByRole("button", { name: /ttc/i });
    expect(ttcRow.textContent).toContain("0%");
    expect(ttcRow.textContent).not.toContain("Stable");

    fireEvent.click(farmBoyRow);
    await waitFor(() =>
      expect(onLoadMerchantTransactions).toHaveBeenCalledWith("Farm Boy", "CAD"),
    );
    // The merchant list is replaced in place - like a category drill-down -
    // rather than appended below it, so the detail is never buried offscreen.
    expect(screen.getByRole("heading", { name: "Farm Boy" })).toBeInTheDocument();
    expect(screen.queryByText("TTC")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Merchants" })).not.toBeInTheDocument();
    const amountCell = await screen.findByText("$56.28");
    fireEvent.click(amountCell.closest(".transaction-row")!);
    expect(onOpenTransaction).toHaveBeenCalledWith(merchantTransaction);

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => expect(onLoadMerchantBreakdown).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("TTC")).toBeInTheDocument();
    expect(screen.getByText("Farm Boy")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Categories" }));
    expect(screen.getByText("Cinema")).toBeInTheDocument();
  });

  it("groups every Deals product under a broad taxonomy category and expands to reveal them", () => {
    const priceChanges = [
      {
        identity_key: "product:broccoli",
        label: "Broccoli",
        taxonomy_key: "food_dining.groceries.produce.vegetables.cruciferous.broccoli",
        currency: "CAD",
        normalized_unit: "kg",
        current_price: "3.99",
        previous_price: null,
        delta_amount: null,
        delta_percent: null,
        current_date: "2026-07-20",
        current_merchant: "Farm Boy",
        best_price: "3.99",
        best_date: "2026-07-20",
        best_merchant: "Farm Boy",
        savings_amount: "0",
        savings_percent: "0",
        sample_size: 1,
        recent_prices: ["3.99"],
      },
      {
        identity_key: "product:cauliflower",
        label: "Cauliflower",
        taxonomy_key: "food_dining.groceries.produce.vegetables.cruciferous.cauliflower",
        currency: "CAD",
        normalized_unit: "each",
        current_price: "4.49",
        previous_price: null,
        delta_amount: null,
        delta_percent: null,
        current_date: "2026-07-18",
        current_merchant: "FreshCo",
        best_price: "4.49",
        best_date: "2026-07-18",
        best_merchant: "FreshCo",
        savings_amount: "0",
        savings_percent: "0",
        sample_size: 1,
        recent_prices: ["4.49"],
      },
      {
        identity_key: "product:bananas",
        label: "Bananas",
        taxonomy_key: "food_dining.groceries.produce.fruit.bananas_plantains.bananas",
        currency: "CAD",
        normalized_unit: "kg",
        current_price: "1.52",
        previous_price: null,
        delta_amount: null,
        delta_percent: null,
        current_date: "2026-07-19",
        current_merchant: "Farm Boy",
        best_price: "1.52",
        best_date: "2026-07-19",
        best_merchant: "Farm Boy",
        savings_amount: "0",
        savings_percent: "0",
        sample_size: 1,
        recent_prices: ["1.52"],
      },
    ];
    const onOpenPrice = vi.fn();
    render(
      <Overview
        dashboard={{ ...demoDashboard, price_changes: priceChanges }}
        period="month"
        section="prices"
        transactionStatus="idle"
        onSectionChange={vi.fn()}
        onPeriodChange={vi.fn()}
        onRefresh={vi.fn()}
        onLoadTransactions={vi.fn()}
        onReview={vi.fn()}
        onLoadCategoryBreakdown={vi.fn().mockResolvedValue([])}
        onAdd={vi.fn()}
        onOpenTransaction={vi.fn()}
        onOpenPrice={onOpenPrice}
      />,
    );

    // Broccoli and cauliflower are both grouped under the broad "Vegetables"
    // subcategory (not the narrower "Cruciferous Vegetables" class); Bananas
    // still gets its own collapsible "Fruit" group even though it's alone.
    expect(screen.getByText("Vegetables")).toBeInTheDocument();
    expect(screen.getByText("2 products")).toBeInTheDocument();
    expect(screen.queryByText("Broccoli")).not.toBeInTheDocument();
    expect(screen.queryByText("Cauliflower")).not.toBeInTheDocument();
    expect(screen.getByText("Fruit")).toBeInTheDocument();
    expect(screen.getByText("1 product")).toBeInTheDocument();
    expect(screen.queryByText("Bananas")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Vegetables/i }));
    expect(screen.getByText("Broccoli")).toBeInTheDocument();
    expect(screen.getByText("Cauliflower")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Fruit/i }));
    expect(screen.getByText("Bananas")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Broccoli").closest("button")!);
    expect(onOpenPrice).toHaveBeenCalledWith(
      expect.objectContaining({ identity_key: "product:broccoli" }),
    );
  });
});
