import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NutritionFactsDrawer } from "./NutritionFactsDrawer";
import { openPrivateUrl } from "../bridge";
import type { NutritionItem } from "../types";

vi.mock("../bridge", () => ({
  openPrivateUrl: vi.fn(),
}));

const item: NutritionItem = {
  transaction_item_id: "d1111111-1111-4111-8111-111111111111",
  identity_key: "cheddar::no-frills",
  display_name: "Old Cheddar Cheese",
  brand: "No Frills",
  status: "matched",
  purchase_count: 1,
  nutriscore_grade: "d",
  nutriscore_source: "computed",
  nova_group: 3,
  source: "Open Food Facts",
  source_ref: "https://world.openfoodfacts.org/product/example-cheese",
  spend_amount: "12.00",
  energy_kcal_100g: 402,
  protein_100g: 25,
  fat_100g: 33,
  saturated_fat_100g: 21,
  trans_fat_100g: 1.2,
  carbohydrates_100g: 1.3,
  sugars_100g: 0.5,
  added_sugars_100g: 0,
  fiber_100g: 0,
  sodium_mg_100g: 620,
  cholesterol_mg_100g: 105,
  potassium_mg_100g: 76,
  calcium_mg_100g: 720,
  iron_mg_100g: 0.7,
};

describe("NutritionFactsDrawer", () => {
  it("renders headline stats from the item's per-100g facts", () => {
    render(<NutritionFactsDrawer embedded item={item} onClose={vi.fn()} />);

    expect(screen.getByText("Old Cheddar Cheese")).toBeInTheDocument();
    expect(screen.getByText("402")).toBeInTheDocument();
    expect(screen.getByText("25")).toBeInTheDocument();
    expect(screen.getByText("33")).toBeInTheDocument();
    expect(screen.getByText("1.3")).toBeInTheDocument();
    expect(screen.getByText("620")).toBeInTheDocument();
  });

  it("shows the grade badge with the matching grade class", () => {
    render(<NutritionFactsDrawer embedded item={item} onClose={vi.fn()} />);
    const grade = screen.getByText("D");
    expect(grade.className).toContain("grade-d");
  });

  it("shows the NOVA note text matching the item's nova_group", () => {
    render(<NutritionFactsDrawer embedded item={item} onClose={vi.fn()} />);
    expect(screen.getByText(/NOVA 3, processed food/i)).toBeInTheDocument();
  });

  it("omits the NOVA note when nova_group is absent", () => {
    render(<NutritionFactsDrawer embedded item={{ ...item, nova_group: null }} onClose={vi.fn()} />);
    expect(screen.queryByText(/NOVA/i)).not.toBeInTheDocument();
  });

  it("renders the new nutrient rows added for the data-quality overhaul", () => {
    render(<NutritionFactsDrawer embedded item={item} onClose={vi.fn()} />);

    expect(screen.getByText("Trans fat")).toBeInTheDocument();
    expect(screen.getByText("1.2")).toBeInTheDocument();
    expect(screen.getByText("Cholesterol")).toBeInTheDocument();
    expect(screen.getByText("105")).toBeInTheDocument();
    expect(screen.getByText("Added sugars")).toBeInTheDocument();
    expect(screen.getByText("Potassium")).toBeInTheDocument();
    expect(screen.getByText("76")).toBeInTheDocument();
    expect(screen.getByText("Calcium")).toBeInTheDocument();
    expect(screen.getByText("720")).toBeInTheDocument();
    expect(screen.getByText("Iron")).toBeInTheDocument();
    expect(screen.getByText("0.7")).toBeInTheDocument();
  });

  it("shows a dash for a new nutrient field that's missing", () => {
    render(
      <NutritionFactsDrawer embedded item={{ ...item, potassium_mg_100g: null }} onClose={vi.fn()} />,
    );
    const row = screen.getByText("Potassium").closest(".facts-row");
    expect(row).toHaveTextContent("—");
  });

  it("labels the NOVA note as estimated when nova_group_estimated is true", () => {
    const { container } = render(
      <NutritionFactsDrawer embedded item={{ ...item, nova_group_estimated: true }} onClose={vi.fn()} />,
    );
    expect(screen.getByText(/estimated from ingredients/i)).toBeInTheDocument();
    expect(container.querySelector(".nova-note-estimated")).not.toBeNull();
  });

  it("does not label the NOVA note as estimated when nova_group_estimated is false", () => {
    const { container } = render(
      <NutritionFactsDrawer embedded item={{ ...item, nova_group_estimated: false }} onClose={vi.fn()} />,
    );
    expect(screen.queryByText(/estimated from ingredients/i)).not.toBeInTheDocument();
    expect(container.querySelector(".nova-note-estimated")).toBeNull();
  });

  it("shows an 'as reported' marker on the grade badge only when the grade is source-stated", () => {
    const { rerender } = render(
      <NutritionFactsDrawer embedded item={{ ...item, nutriscore_source: "source_stated" }} onClose={vi.fn()} />,
    );
    expect(screen.getByText("as reported")).toBeInTheDocument();

    rerender(<NutritionFactsDrawer embedded item={{ ...item, nutriscore_source: "computed" }} onClose={vi.fn()} />);
    expect(screen.queryByText("as reported")).not.toBeInTheDocument();
  });

  it("shows a source link only when source_ref is a real URL, opened via the host bridge", () => {
    render(<NutritionFactsDrawer embedded item={item} onClose={vi.fn()} />);
    const link = screen.getByRole("button", { name: /view on open food facts/i });
    fireEvent.click(link);
    expect(openPrivateUrl).toHaveBeenCalledWith(item.source_ref);
  });

  it("omits the source link when source_ref is missing", () => {
    render(<NutritionFactsDrawer embedded item={{ ...item, source_ref: null }} onClose={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /view on/i })).not.toBeInTheDocument();
  });

  it("omits the source link when source_ref isn't a usable URL", () => {
    render(<NutritionFactsDrawer embedded item={{ ...item, source_ref: "UPC-041631000027" }} onClose={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /view on/i })).not.toBeInTheDocument();
  });

  it("renders as a backdrop modal and closes on backdrop click, not content click", () => {
    const onClose = vi.fn();
    const { container } = render(<NutritionFactsDrawer item={item} onClose={onClose} />);

    const backdrop = container.querySelector(".drawer-backdrop");
    expect(backdrop).not.toBeNull();

    fireEvent.mouseDown(screen.getByText("Old Cheddar Cheese"));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseDown(backdrop as Element);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<NutritionFactsDrawer embedded item={item} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /back to nutrition/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  describe("per-serving display toggle", () => {
    const servingItem: NutritionItem = { ...item, serving_size_g: 30, serving_label: "1 slice (30g)" };

    it("hides the toggle and stays on per-100g values when serving_size_g is null", () => {
      render(<NutritionFactsDrawer embedded item={item} onClose={vi.fn()} />);
      expect(screen.queryByRole("group", { name: /nutrition facts display/i })).not.toBeInTheDocument();
      expect(screen.getByText("per 100g")).toBeInTheDocument();
      expect(screen.getByText("402")).toBeInTheDocument();
    });

    it("renders the toggle and defaults to per-100g values when serving data is present", () => {
      render(<NutritionFactsDrawer embedded item={servingItem} onClose={vi.fn()} />);
      expect(screen.getByRole("group", { name: /nutrition facts display/i })).toBeInTheDocument();
      expect(screen.getAllByText("per 100g").length).toBeGreaterThan(0);
      expect(screen.getByText("402")).toBeInTheDocument();
    });

    it("scales headline and facts-table values by serving_size_g / 100 when switched to serving mode", () => {
      render(<NutritionFactsDrawer embedded item={servingItem} onClose={vi.fn()} />);

      fireEvent.click(screen.getByRole("button", { name: "Serving" }));

      expect(screen.getAllByText("per 1 slice (30g)").length).toBeGreaterThan(0);
      // energy_kcal_100g 402 * 30 / 100 = 120.6
      expect(screen.getByText("120.6")).toBeInTheDocument();
      // sodium_mg_100g 620 * 30 / 100 = 186
      expect(screen.getByText("186")).toBeInTheDocument();
      expect(screen.queryByText("402")).not.toBeInTheDocument();
    });

    it("switches back to per-100g values when toggled back", () => {
      render(<NutritionFactsDrawer embedded item={servingItem} onClose={vi.fn()} />);

      fireEvent.click(screen.getByRole("button", { name: "Serving" }));
      fireEvent.click(screen.getByRole("button", { name: "100g" }));

      expect(screen.getAllByText("per 100g").length).toBeGreaterThan(0);
      expect(screen.getByText("402")).toBeInTheDocument();
    });
  });
});
