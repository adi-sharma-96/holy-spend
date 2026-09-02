import { describe, expect, it } from "vitest";
import { quantityLabel } from "./format";

describe("quantityLabel", () => {
  it("prefers measured_value/measured_unit when present", () => {
    expect(
      quantityLabel({ measured_value: "700", measured_unit: "g", quantity: "1", unit: "pc" }),
    ).toBe("700 g");
  });

  it("prefers package_value/package_unit over quantity/unit", () => {
    expect(
      quantityLabel({ package_value: "300", package_unit: "g", quantity: "1", unit: "item" }),
    ).toBe("300 g");
  });

  it("falls back to quantity/unit for weighed produce with no separate measured_value", () => {
    // Loose produce priced per kg has no distinct "package size" - the
    // purchased weight IS the size, captured as quantity+unit. Price Watch's
    // history panel used to only check measured_value/package_value and
    // showed "Original size not captured" for these even though the weight
    // was right there in quantity/unit (real bug: FreshCo "Tomato On The
    // Vine", quantity=1.01, unit=kg, measured_value=null).
    expect(quantityLabel({ quantity: "1.01", unit: "kg" })).toBe("1.01 kg");
  });

  it("falls back to a placeholder when nothing at all was captured", () => {
    expect(quantityLabel({})).toBe("—");
  });
});
