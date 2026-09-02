import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { demoDashboard } from "../demo";
import { InlineLauncher } from "./InlineLauncher";
import type { NutritionSummary } from "../types";

const nutritionSummaryFixture: NutritionSummary = {
  window: demoDashboard.window,
  currency: "CAD",
  overall_grade: "b",
  matched_item_count: 5,
  total_item_count: 7,
  coverage_percent: "71.4",
  confidence: "low",
  grade_distribution: [
    { grade: "a", spend_amount: "18.50", share_percent: "30.0" },
    { grade: "b", spend_amount: "6.00", share_percent: "10.0" },
    { grade: "unknown", spend_amount: "12.20", share_percent: "60.0" },
  ],
  signals: [
    {
      kind: "processing_level",
      title: "Mostly whole foods",
      detail: "3 of 5 matched items are minimally processed (NOVA 1-2), led by Fresh Milk 2%.",
      tone: "neutral",
    },
  ],
  groups: [
    {
      category_slug: "food_dining.groceries.dairy_eggs",
      category_name: "Dairy & Eggs",
      items: [
        {
          transaction_item_id: "d1111111-1111-4111-8111-111111111111",
          identity_key: "milk::farm-boy",
          display_name: "Fresh Milk 2%",
          status: "matched",
          purchase_count: 1,
          nutriscore_grade: "a",
          nova_group: 1,
          spend_amount: "6.50",
        },
        {
          transaction_item_id: "d2222222-2222-4222-8222-222222222222",
          identity_key: "cheese::no-frills",
          display_name: "Old Cheddar Cheese",
          status: "matched",
          purchase_count: 1,
          nutriscore_grade: "d",
          spend_amount: "12.00",
        },
      ],
    },
    {
      category_slug: "food_dining.groceries.snacks_pantry",
      category_name: "Snacks & Pantry",
      items: [
        {
          transaction_item_id: "d3333333-3333-4333-8333-333333333333",
          identity_key: "chips::no-frills",
          display_name: "Potato Chips, Original",
          status: "matched",
          purchase_count: 1,
          nutriscore_grade: "e",
          spend_amount: "6.00",
        },
      ],
    },
  ],
};

describe("InlineLauncher", () => {
  it("shows useful swipeable previews for every core workflow", () => {
    const onExpand = vi.fn();
    const onAdd = vi.fn();
    render(
      <InlineLauncher
        dashboard={demoDashboard}
        dashboardStatus="ready"
        displayName="Adi"
        surface="overview"
        onExpand={onExpand}
        onAdd={onAdd}
      />,
    );

    expect(screen.getByText("Good to see you, Adi.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Available tracker sections")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /overview/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /transactions/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /price watch/i })).toBeInTheDocument();
    expect(screen.getByText("Farm Boy")).toBeInTheDocument();
    expect(screen.getByLabelText("Six-month spending chart").children).toHaveLength(6);
    const categories = screen.getByLabelText("Top spending categories");
    expect(categories.children).toHaveLength(4);
    expect(within(categories).getByText("Groceries")).toBeInTheDocument();
    expect(within(categories).getByText("Eating out")).toBeInTheDocument();
    expect(within(categories).getByText("General Merchandise")).toBeInTheDocument();
    expect(within(categories).getByText("Personal Vehicle")).toBeInTheDocument();
    expect(within(categories).getByText("$226.84")).toBeInTheDocument();
    const categoryIcons = categories.querySelectorAll("svg");
    expect(categoryIcons).toHaveLength(4);
    expect(categoryIcons[0]?.innerHTML).not.toBe(categoryIcons[1]?.innerHTML);

    expect(screen.getByText(/jul 26 · 5 items/i)).toBeInTheDocument();

    const trendsCard = screen.getByRole("button", { name: /trends/i });
    expect(within(trendsCard).getByText("↑ 12.8%")).toBeInTheDocument();
    expect(within(trendsCard).getByText(/up 12.8% vs jun/i)).toBeInTheDocument();

    const pricesCard = screen.getByRole("button", { name: /price watch/i });
    expect(within(pricesCard).getByText("Apples")).toBeInTheDocument();
    expect(within(pricesCard).getByText("Pasta")).toBeInTheDocument();
    expect(within(pricesCard).getByText("+18.1%")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /transactions/i }));
    expect(onExpand).toHaveBeenCalledWith("transactions");

    fireEvent.click(screen.getByRole("button", { name: /add expense/i }));
    expect(onAdd).toHaveBeenCalledOnce();
  });

  it("shows a reassuring note instead of forced content when a month is just getting started", () => {
    const sparseDashboard = {
      ...demoDashboard,
      window: {
        ...demoDashboard.window,
        current_start: "2026-08-01",
        current_end: "2026-08-02",
      },
      categories: [
        {
          category_slug: "food_dining.groceries",
          category_name: "Groceries",
          taxonomy_level: 2,
          taxonomy_level_name: "Group",
          has_children: true,
          currency: "CAD",
          current_amount: "12.99",
          previous_amount: "0",
          delta_percent: null,
          share_percent: "100.0",
        },
      ],
    };
    render(
      <InlineLauncher
        dashboard={sparseDashboard}
        dashboardStatus="ready"
        displayName="Adi"
        surface="overview"
        onExpand={vi.fn()}
        onAdd={vi.fn()}
      />,
    );

    expect(screen.getByText(/2 days into/i)).toBeInTheDocument();
    expect(
      screen.getByText(/more categories will show up here as you add expenses/i),
    ).toBeInTheDocument();
  });

  it("shows a fifth calendar card with a filled month grid", () => {
    const onExpand = vi.fn();
    render(
      <InlineLauncher
        dashboard={demoDashboard}
        dashboardStatus="ready"
        displayName="Adi"
        surface="overview"
        onExpand={onExpand}
        onAdd={vi.fn()}
      />,
    );

    const calendarCard = screen.getByRole("button", { name: /calendar/i });
    const grid = within(calendarCard).getByLabelText(/daily spending/i);
    expect(grid.children.length).toBeGreaterThanOrEqual(27);
    expect(grid.querySelectorAll("i:not(.blank)").length).toBeGreaterThan(0);

    fireEvent.click(calendarCard);
    expect(onExpand).toHaveBeenCalledWith("trends", "calendar");
  });

  it("shows a sixth nutrition card with the basket grade and a matched-count line", () => {
    const onExpand = vi.fn();
    const { container } = render(
      <InlineLauncher
        dashboard={demoDashboard}
        dashboardStatus="ready"
        displayName="Adi"
        nutritionSummary={nutritionSummaryFixture}
        surface="overview"
        onExpand={onExpand}
        onAdd={vi.fn()}
      />,
    );

    const nutritionCard = screen.getByRole("button", { name: /nutrition/i });
    expect(within(nutritionCard).getByText("B")).toBeInTheDocument();
    expect(within(nutritionCard).getByText("71%")).toBeInTheDocument();
    expect(within(nutritionCard).getByText("5/7")).toBeInTheDocument();
    expect(within(nutritionCard).getByText("Mostly whole foods")).toBeInTheDocument();
    expect(
      within(nutritionCard).getByText(/3 of 5 matched items are minimally processed/i),
    ).toBeInTheDocument();
    expect(nutritionCard.querySelectorAll(".inline-nutrition-ring circle")).toHaveLength(4);

    expect(within(nutritionCard).getByText("Best")).toBeInTheDocument();
    expect(within(nutritionCard).getByText("Fresh Milk 2%")).toBeInTheDocument();
    expect(within(nutritionCard).getByText("Worst offenders")).toBeInTheDocument();
    expect(within(nutritionCard).getByText("Old Cheddar Cheese")).toBeInTheDocument();
    expect(within(nutritionCard).getByText("Potato Chips, Original")).toBeInTheDocument();

    const dots = container.querySelector(".inline-rail-dots");
    expect(dots?.children).toHaveLength(6);

    fireEvent.click(nutritionCard);
    expect(onExpand).toHaveBeenCalledWith("nutrition");
  });

  it("shows a placeholder instead of a grade badge when nothing has been matched yet", () => {
    render(
      <InlineLauncher
        dashboard={demoDashboard}
        dashboardStatus="ready"
        displayName="Adi"
        nutritionSummary={{
          ...nutritionSummaryFixture,
          overall_grade: null,
          matched_item_count: 0,
          grade_distribution: [],
          signals: [],
          groups: [],
        }}
        surface="overview"
        onExpand={vi.fn()}
        onAdd={vi.fn()}
      />,
    );

    const nutritionCard = screen.getByRole("button", { name: /nutrition/i });
    expect(within(nutritionCard).getByText("?")).toBeInTheDocument();
    expect(within(nutritionCard).getByText("Building your basket grade")).toBeInTheDocument();
    expect(nutritionCard.querySelectorAll(".inline-nutrition-ring circle")).toHaveLength(1);
    expect(within(nutritionCard).queryByText("Best")).not.toBeInTheDocument();
    expect(within(nutritionCard).queryByText("Worst offenders")).not.toBeInTheDocument();
  });

  it("ranks best/worst by grade quality first, spend only as a tiebreaker", () => {
    render(
      <InlineLauncher
        dashboard={demoDashboard}
        dashboardStatus="ready"
        displayName="Adi"
        nutritionSummary={{
          ...nutritionSummaryFixture,
          groups: [
            {
              category_slug: "food_dining.groceries.dairy_eggs",
              category_name: "Dairy & Eggs",
              items: [
                {
                  transaction_item_id: "e1111111-1111-4111-8111-111111111111",
                  identity_key: "big-spend-b-item",
                  display_name: "Big Spend B Item",
                  status: "matched",
                  purchase_count: 1,
                  nutriscore_grade: "b",
                  spend_amount: "50.00",
                },
                {
                  transaction_item_id: "e2222222-2222-4222-8222-222222222222",
                  identity_key: "small-spend-a-item",
                  display_name: "Small Spend A Item",
                  status: "matched",
                  purchase_count: 1,
                  nutriscore_grade: "a",
                  spend_amount: "1.00",
                },
                {
                  transaction_item_id: "e3333333-3333-4333-8333-333333333333",
                  identity_key: "big-spend-d-item",
                  display_name: "Big Spend D Item",
                  status: "matched",
                  purchase_count: 1,
                  nutriscore_grade: "d",
                  spend_amount: "50.00",
                },
                {
                  transaction_item_id: "e4444444-4444-4444-8444-444444444444",
                  identity_key: "small-spend-e-item",
                  display_name: "Small Spend E Item",
                  status: "matched",
                  purchase_count: 1,
                  nutriscore_grade: "e",
                  spend_amount: "1.00",
                },
              ],
            },
          ],
        }}
        surface="overview"
        onExpand={vi.fn()}
        onAdd={vi.fn()}
      />,
    );

    const nutritionCard = screen.getByRole("button", { name: /nutrition/i });
    const groups = nutritionCard.querySelectorAll(".inline-nutrition-highlight-group");
    expect(groups).toHaveLength(2);
    const bestNames = Array.from(groups[0]!.querySelectorAll("strong")).map((node) => node.textContent);
    const worstNames = Array.from(groups[1]!.querySelectorAll("strong")).map((node) => node.textContent);

    // A ($1) must outrank B ($50) despite the huge spend gap - grade wins first.
    expect(bestNames).toEqual(["Small Spend A Item", "Big Spend B Item"]);
    // E ($1) must outrank D ($50) for the same reason.
    expect(worstNames).toEqual(["Small Spend E Item", "Big Spend D Item"]);
  });

  it("omits the nutrition card entirely when no nutrition summary is available", () => {
    render(
      <InlineLauncher
        dashboard={demoDashboard}
        dashboardStatus="ready"
        displayName="Adi"
        surface="overview"
        onExpand={vi.fn()}
        onAdd={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /nutrition/i })).not.toBeInTheDocument();
  });
});
