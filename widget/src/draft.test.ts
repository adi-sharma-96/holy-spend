import { describe, expect, it } from "vitest";
import { draftFromSnapshot, emptyDraft, emptyItem, localIsoDate, savePayload } from "./draft";

describe("draft helpers", () => {
  it("creates a predictable empty manual draft", () => {
    const draft = emptyDraft(new Date("2026-07-27T12:00:00Z"));
    expect(draft.date).toBe("2026-07-27");
    expect(draft.currency).toBe("CAD");
    expect(draft.items).toEqual([]);
    expect(draft.adjustments).toEqual([]);
    expect(draft.notes).toBe("");
  });

  it("uses the browser's local calendar day, not the UTC day", () => {
    // toISOString() always normalizes to UTC, which silently rolls a manual
    // expense's default date to "tomorrow" for any user west of UTC once
    // it's late evening locally. localIsoDate must read local components.
    const now = new Date();
    const expected = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
      now.getDate(),
    ).padStart(2, "0")}`;
    expect(localIsoDate(now)).toBe(expected);
    expect(emptyDraft(now).date).toBe(expected);
  });

  it("preserves the server revision and receipt identity", () => {
    const draft = draftFromSnapshot({
      transaction: {
        id: "tx-1",
        status: "draft",
        source_type: "receipt",
        transaction_type: "expense",
        transaction_date: "2026-07-27",
        merchant_name_raw: "Market",
        notes: "Team lunch",
        currency: "CAD",
        fee_amount: "0.50",
        deposit_amount: "1.00",
        rounding_amount: "-0.01",
        total_amount: "12.50",
        updated_at: "2026-07-27T12:00:00Z",
        items: [
          {
            id: "item-1",
            raw_name: "Soup",
            category_slug: "dining",
            theme_slugs: [],
            quantity: "2",
            unit_price_amount: "5.00",
            line_total_amount: "10.00",
          },
        ],
        adjustments: [
          {
            id: "adjustment-1",
            type: "tip",
            subtype: null,
            amount: "2.50",
            description: "Server tip",
            raw_label: "Driver tip",
            affects_total: true,
            metadata: { printed: true },
          },
        ],
      },
      receipt: {
        receipt: { id: "receipt-1", transaction_id: "tx-1" },
        files: [],
      },
    });
    expect(draft.revision).toBe("2026-07-27T12:00:00Z");
    expect(draft.receiptId).toBe("receipt-1");
    expect(draft.notes).toBe("Team lunch");
    expect(draft.fee).toBe("0.50");
    expect(draft.deposit).toBe("1.00");
    expect(draft.rounding).toBe("-0.01");
    expect(draft.items[0]!.unitPrice).toBe("5.00");
    expect(draft.items[0]!.existingItemId).toBe("item-1");
    expect(draft.adjustments[0]).toEqual({
      itemIndex: undefined,
      type: "tip",
      subtype: "",
      amount: "2.50",
      description: "Server tip",
      rawLabel: "Driver tip",
      affectsTotal: true,
      metadata: { printed: true },
    });
  });

  it("does not put binary data or owner IDs into the save request", () => {
    const payload = savePayload(
      {
        ...emptyDraft(new Date("2026-07-27T12:00:00Z")),
        merchant: "Market",
        notes: "Keep the original",
        total: "12.50",
        items: [
          {
            ...emptyItem("dining"),
            name: "Soup",
            quantity: "2",
            unitPrice: "5.00",
            lineTotal: "10.00",
          },
        ],
        adjustments: [
          {
            type: "discount",
            subtype: "membership_benefit",
            amount: "2.50",
            description: "Member saving",
            rawLabel: "You saved",
            affectsTotal: false,
            metadata: { program: "member" },
          },
        ],
      },
      "request-123",
    );
    expect(JSON.stringify(payload)).not.toContain("user_id");
    expect(JSON.stringify(payload)).not.toContain("base64");
    expect(payload.client_request_id).toBe("request-123");
    expect(payload.draft).toMatchObject({
      notes: "Keep the original",
      items: [{ quantity: "2", unit_price_amount: "5.00" }],
      adjustments: [
        {
          type: "discount",
          subtype: "membership_benefit",
          amount: "2.50",
          affects_total: false,
          metadata: { program: "member" },
        },
      ],
    });
  });

  it("keeps unchanged evidence and drops evidence for edited measurements", () => {
    const item = {
      ...emptyItem("groceries.grains.flour.corn"),
      name: "Corn flour",
      quantity: "1",
      packageValue: "500",
      packageUnit: "g",
      lineTotal: "3.00",
      existingEvidence: {
        name: "Corn flour", brand: "", categorySlug: "groceries.grains.flour.corn",
        quantity: "1", unit: "each", measuredValue: "", measuredUnit: "",
        packageValue: "500", packageUnit: "g",
        unitPrice: "", unitPriceBasisValue: "", unitPriceBasisUnit: "", lineTotal: "3.00",
        productIdentityKey: "corn-flour-500g", productTypeKey: "corn-flour",
        fieldProvenance: {
          identity: { source: "user_confirmed" },
          package_size: { source: "estimate" },
          package_count: { source: "user_confirmed" },
        },
      },
    };
    const form = { ...emptyDraft(), total: "3.00", items: [item] };
    const first = (savePayload(form, "one").draft as { items: Record<string, unknown>[] }).items[0]!;
    expect(first.product_identity_key).toBe("corn-flour-500g");
    expect(first.field_provenance).toMatchObject({ package_size: { source: "estimate" } });
    item.packageValue = "750";
    const second = (savePayload(form, "two").draft as { items: Record<string, unknown>[] }).items[0]!;
    expect(second.product_identity_key).toBeUndefined();
    expect(second.field_provenance).toEqual({});
  });

  it("drops stale measurement evidence when the printed price basis changes", () => {
    const item = {
      ...emptyItem("food_dining.groceries.produce.fruit.apples_pears.apples"),
      name: "Apples", quantity: "1", unit: "each", unitPrice: "5",
      unitPriceBasisValue: "1", unitPriceBasisUnit: "kg", lineTotal: "5",
      existingEvidence: {
        name: "Apples", brand: "", categorySlug: "food_dining.groceries.produce.fruit.apples_pears.apples",
        quantity: "1", unit: "each", measuredValue: "", measuredUnit: "",
        packageValue: "", packageUnit: "",
        unitPrice: "5", unitPriceBasisValue: "1", unitPriceBasisUnit: "kg", lineTotal: "5",
        productIdentityKey: "apples", productTypeKey: "apple.honeycrisp",
        fieldProvenance: { identity: { source: "user_confirmed" },
          measured_value: { source: "user_confirmed" } },
      },
    };
    item.unitPriceBasisValue = "2";
    const fields = (savePayload({ ...emptyDraft(), total: "5", items: [item] }, "changed").draft as {
      items: Record<string, unknown>[]
    }).items[0]!;
    expect(fields.field_provenance).toEqual({ identity: { source: "user_confirmed" } });
  });

  it("sends stable item IDs when lines are reordered or inserted", () => {
    const apple = { ...emptyItem("groceries"), existingItemId: "apple-id", name: "Apples", lineTotal: "1" };
    const pear = { ...emptyItem("groceries"), existingItemId: "pear-id", name: "Pears", lineTotal: "1" };
    const orange = { ...emptyItem("groceries"), name: "Oranges", lineTotal: "1" };
    const draft = { ...emptyDraft(), total: "3", items: [pear, orange, apple] };
    const items = (savePayload(draft, "reordered").draft as { items: Record<string, unknown>[] }).items;
    expect(items.map((item) => item.existing_item_id)).toEqual(["pear-id", undefined, "apple-id"]);
  });
});
