import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NutritionPanel } from "./NutritionPanel";
import type { NutritionItem, NutritionSummary } from "../types";

const matchedItem: NutritionItem = {
  transaction_item_id: "d1111111-1111-4111-8111-111111111111",
  identity_key: "milk::farm-boy",
  display_name: "Fresh Milk 2%",
  brand: "Farm Boy",
  status: "matched",
  purchase_count: 1,
  nutriscore_grade: "a",
  nova_group: 1,
  source: "Open Food Facts",
  source_ref: "https://world.openfoodfacts.org/product/example",
  spend_amount: "6.00",
  energy_kcal_100g: 61,
};

const pendingItem: NutritionItem = {
  transaction_item_id: "d2222222-2222-4222-8222-222222222222",
  identity_key: "trail-mix::",
  display_name: "No Name Trail Mix",
  status: "pending",
  purchase_count: 1,
  spend_amount: "12.20",
};

const noMatchItem: NutritionItem = {
  transaction_item_id: "d6666666-6666-4666-8666-666666666666",
  identity_key: "mystery-snack::",
  display_name: "Mystery Snack",
  status: "no_match",
  purchase_count: 1,
  spend_amount: "3.00",
};

const matchedSnackItem: NutritionItem = {
  transaction_item_id: "d3333333-3333-4333-8333-333333333333",
  identity_key: "chips::no-frills",
  display_name: "Potato Chips",
  brand: "No Frills",
  status: "matched",
  purchase_count: 2,
  nutriscore_grade: "e",
  nova_group: 4,
  nova_group_estimated: true,
  spend_amount: "4.00",
  energy_kcal_100g: 536,
};

const summary: NutritionSummary = {
  window: {
    label: "August",
    current_start: "2026-08-01",
    current_end: "2026-08-31",
    previous_start: "2026-07-01",
    previous_end: "2026-07-31",
  },
  currency: "CAD",
  overall_grade: "a",
  matched_item_count: 1,
  total_item_count: 2,
  coverage_percent: "50.0",
  confidence: "low",
  grade_distribution: [
    { grade: "a", spend_amount: "6.00", share_percent: "33.0" },
    { grade: "unknown", spend_amount: "12.20", share_percent: "67.0" },
  ],
  signals: [
    { kind: "processing_level", title: "Mostly whole foods", detail: "1 of 1 matched items.", tone: "neutral" },
  ],
  groups: [
    {
      category_slug: "food_dining.groceries.dairy_eggs",
      category_name: "Dairy & Eggs",
      items: [matchedItem],
    },
    {
      category_slug: "food_dining.groceries.snacks_pantry",
      category_name: "Snacks & Pantry",
      items: [pendingItem, noMatchItem, matchedSnackItem],
    },
  ],
};

describe("NutritionPanel", () => {
  it("shows a loading state when there is no summary yet", () => {
    render(<NutritionPanel currency="CAD" onCloseItem={vi.fn()} onSelectItem={vi.fn()} status="loading" />);
    expect(screen.getByText(/loading nutrition data/i)).toBeInTheDocument();
  });

  it("shows an error state distinct from loading", () => {
    render(<NutritionPanel currency="CAD" onCloseItem={vi.fn()} onSelectItem={vi.fn()} status="error" />);
    expect(screen.getByText(/nutrition needs another try/i)).toBeInTheDocument();
  });

  it("renders the hero grade, distribution, and signals from a real summary", () => {
    render(
      <NutritionPanel currency="CAD" onCloseItem={vi.fn()} onSelectItem={vi.fn()} status="ready" summary={summary} />,
    );

    expect(screen.getByText(/your spend-weighted basket grade: a/i)).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 grocery items matched/i)).toBeInTheDocument();
    expect(screen.getByText("Mostly whole foods")).toBeInTheDocument();
  });

  it("expands a category and shows a matched tile as tappable", () => {
    const onSelectItem = vi.fn();
    render(
      <NutritionPanel
        currency="CAD"
        onCloseItem={vi.fn()}
        onSelectItem={onSelectItem}
        status="ready"
        summary={summary}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /dairy & eggs/i }));
    const tile = screen.getByRole("button", { name: /fresh milk 2%/i });
    fireEvent.click(tile);
    expect(onSelectItem).toHaveBeenCalledWith(matchedItem);
  });

  it("shows a pending item as non-interactive, not a button", () => {
    render(
      <NutritionPanel currency="CAD" onCloseItem={vi.fn()} onSelectItem={vi.fn()} status="ready" summary={summary} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /snacks & pantry/i }));
    expect(screen.getByText("No Name Trail Mix")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /no name trail mix/i })).not.toBeInTheDocument();
  });

  it("shows a no_match item distinctly from a pending item", () => {
    render(
      <NutritionPanel currency="CAD" onCloseItem={vi.fn()} onSelectItem={vi.fn()} status="ready" summary={summary} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /snacks & pantry/i }));
    expect(screen.getByText("Mystery Snack")).toBeInTheDocument();
    expect(screen.getByText("Not found")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mystery snack/i })).not.toBeInTheDocument();
  });

  it("shows a purchase-count badge only when purchase_count is greater than one", () => {
    render(
      <NutritionPanel currency="CAD" onCloseItem={vi.fn()} onSelectItem={vi.fn()} status="ready" summary={summary} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /dairy & eggs/i }));
    fireEvent.click(screen.getByRole("button", { name: /snacks & pantry/i }));
    expect(screen.getByText("×2")).toBeInTheDocument();
    expect(screen.queryByText("×1")).not.toBeInTheDocument();
  });

  it("labels an estimated NOVA group distinctly from a source-stated one", () => {
    render(
      <NutritionPanel currency="CAD" onCloseItem={vi.fn()} onSelectItem={vi.fn()} status="ready" summary={summary} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /snacks & pantry/i }));
    expect(screen.getByLabelText("NOVA 4 (estimated)")).toBeInTheDocument();
  });

  it("shows a fresh-note instead of tiles when every item in a group is unmatched", () => {
    const allUnmatchedSummary: NutritionSummary = {
      ...summary,
      groups: [
        {
          category_slug: "food_dining.groceries.produce",
          category_name: "Produce",
          items: [pendingItem],
        },
      ],
    };
    render(
      <NutritionPanel
        currency="CAD"
        onCloseItem={vi.fn()}
        onSelectItem={vi.fn()}
        status="ready"
        summary={allUnmatchedSummary}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /produce/i }));
    expect(screen.getByText(/haven't been matched to a nutrition source yet/i)).toBeInTheDocument();
  });

  it("renders the embedded drawer in place of the list when an item is selected", () => {
    render(
      <NutritionPanel
        currency="CAD"
        onCloseItem={vi.fn()}
        onSelectItem={vi.fn()}
        selectedItem={matchedItem}
        status="ready"
        summary={summary}
      />,
    );

    expect(screen.getByText("Fresh Milk 2%")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Nutrition" })).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no grocery items at all", () => {
    render(
      <NutritionPanel
        currency="CAD"
        onCloseItem={vi.fn()}
        onSelectItem={vi.fn()}
        status="ready"
        summary={{ ...summary, total_item_count: 0, matched_item_count: 0, groups: [] }}
      />,
    );

    expect(screen.getByText(/no grocery items in cad yet/i)).toBeInTheDocument();
  });
});
